# igw/app/routes/oauth_instagram.py
from __future__ import annotations

from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session

from igw.app.config import settings
from igw.app.db import get_db
from igw.app.models import Player, UserSession, Wallet  # <- add Wallet
from igw.app.utils.account import ensure_wallets_for_user
from igw.app.utils.security import create_token
from igw.app.utils.sessions import exp_from_jwt            # <-- NEW: to fill expires_at
from igw.app.providers.bsg.settings import bsg_settings, get_bank_settings  # <- new

router = APIRouter(prefix="/oauth/instagram", tags=["oauth-instagram"])


def _require_basic_display_config():
    if settings.IG_AUTH_MODE != "basic_display":
        raise HTTPException(status_code=500, detail="IG_AUTH_MODE is not 'basic_display'")
    if not settings.IGBD_APP_ID:
        raise HTTPException(status_code=500, detail="IGBD_APP_ID not configured")
    if not settings.IGBD_APP_SECRET:
        raise HTTPException(status_code=500, detail="IGBD_APP_SECRET not configured")
    if not settings.IGBD_REDIRECT_URI:
        raise HTTPException(status_code=500, detail="IGBD_REDIRECT_URI not configured")


@router.get("/start")
async def instagram_login():
    """
    Instagram Basic Display OAuth — shows Instagram-branded consent UI.
    """
    _require_basic_display_config()

    base = "https://api.instagram.com/oauth/authorize"
    params = {
        "client_id": settings.IGBD_APP_ID,
        "redirect_uri": settings.IGBD_REDIRECT_URI,
        "scope": settings.IGBD_SCOPES,
        "response_type": "code",
    }
    url = f"{base}?{urlencode(params)}"
    print(f"[IG-OAUTH] authorize -> {url}")
    return RedirectResponse(url)


@router.get("/callback")
async def instagram_callback(
    request: Request,
    code: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
):
    """
    Exchange ?code -> access token, read username, upsert Player,
    ensure two wallets (USD,VND), create lobby & BSG game sessions,
    and render an HTML summary with wallet balances + CW start link.
    """
    _require_basic_display_config()

    if error:
        raise HTTPException(status_code=400, detail=f"OAuth error: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="Missing ?code")

    async with httpx.AsyncClient(timeout=25) as cx:
        # 1) Exchange code for access token (POST form)
        token_resp = await cx.post(
            "https://api.instagram.com/oauth/access_token",
            data={
                "client_id": settings.IGBD_APP_ID,
                "client_secret": settings.IGBD_APP_SECRET,
                "grant_type": "authorization_code",
                "redirect_uri": settings.IGBD_REDIRECT_URI,
                "code": code,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        token_resp.raise_for_status()
        tok = token_resp.json()
        access_token = tok.get("access_token")
        ig_user_id = tok.get("user_id")
        if not access_token or not ig_user_id:
            raise HTTPException(status_code=400, detail=f"Malformed token response: {tok}")

        # 2) Fetch username via Graph API
        me_resp = await cx.get(
            f"https://graph.instagram.com/{ig_user_id}",
            params={"fields": "id,username", "access_token": access_token},
        )
        me_resp.raise_for_status()
        me = me_resp.json()
        username = me.get("username") or f"ig_{ig_user_id}"

    # 3) Upsert Player
    player = db.query(Player).filter(Player.ext_user_id == str(ig_user_id)).first()
    if not player:
        email = f"{username}@instagram.com"  # placeholder policy you requested
        player = Player(
            user_name=username,
            ext_user_id=str(ig_user_id),
            email=email,
            language_code="en",
            status="active",
        )
        db.add(player)
        db.flush()
        ensure_wallets_for_user(db, player.userId)

    # Fetch wallets (USD & VND) to show balances
    wallets = db.query(Wallet).filter(Wallet.userId == player.userId).all()
    by_ccy = {w.currency_code.upper(): w for w in wallets}

    # 4) Create lobby session (JWT) — TTL is app-level now
    lobby_token = create_token({
        "uid": player.userId,
        "type": "lobby",
        "exp_m": settings.LOBBY_TOKEN_EXP_MIN,   # <-- use app-level TTL
    })
    lobby_sess = UserSession(
        userId=player.userId,
        token=lobby_token,
        session_type="lobby",
        provider="instagram_basic_display",
        status="active",
        Login_IP=(request.client.host if request and request.client else None),
        expires_at=exp_from_jwt(lobby_token),     # <-- fill DB expires_at
    )
    db.add(lobby_sess)

    # 5) Create a BSG game token + session (token BSG will send back to /betsoft/authenticate)
    base = bsg_settings()
    bank = get_bank_settings(base.BSG_DEFAULT_BANK_ID)

    game_claims = {
        "uid": player.userId,
        "type": "game",
        "provider": "bsg",
        "bankId": bank.BSG_BANK_ID,
        "gameId": bank.BSG_DEFAULT_GAME_ID,
        "exp_m": 60,  # keep your default game TTL, or use bank.BSG_TOKEN_GAME_EXP_MIN if you have it
    }
    bsg_token = create_token(game_claims)
    game_sess = UserSession(
        userId=player.userId,
        token=bsg_token,
        session_type="game",
        provider="bsg",
        status="active",
        Login_IP=(request.client.host if request and request.client else None),
        meta={"bankId": bank.BSG_BANK_ID, "gameId": bank.BSG_DEFAULT_GAME_ID},
        expires_at=exp_from_jwt(bsg_token),       # <-- fill DB expires_at
    )
    db.add(game_sess)
    db.commit()

    # 6) Build CW game start URL (uses the **BSG token**, not the lobby token)
    start_host = (
        bank.BSG_CW_START_BASE
        or base.BSG_CW_START_BASE_DEFAULT
        or "https://5for5media-ng-copy.nucleusgaming.com"
    )
    cw_query = urlencode(
        {
            "bankId": bank.BSG_BANK_ID,
            "gameId": bank.BSG_DEFAULT_GAME_ID,
            "mode": "real",
            "token": bsg_token,
            "lang": "en",
        }
    )
    start_url = f"{start_host}/cwstartgamev2.do?{cw_query}"

    # 7) Simple confirmation page w/ balances + logout button (POST /auth/logout with lobby token)
    usd_bal = f"{by_ccy.get('USD').balance:.2f}" if by_ccy.get("USD") else "0.00"
    vnd_bal = f"{by_ccy.get('VND').balance:.2f}" if by_ccy.get("VND") else "0.00"

    html = f"""
    <style>
      body{{font-family:ui-sans-serif,system-ui,Segoe UI,Roboto,Arial;margin:40px;line-height:1.5}}
      pre{{background:#0b1020;color:#e6edf3;padding:16px;border-radius:8px;overflow:auto}}
      .row span{{display:inline-block;min-width:160px;color:#64748b}}
      a.button,button.button{{display:inline-block;margin-top:12px;padding:10px 14px;border-radius:8px;border:1px solid #cbd5e1;text-decoration:none;background:white;cursor:pointer}}
      h2{{margin-bottom:6px}}
      code.small{{font-size:12px}}
    </style>
    <h2>Instagram login — success</h2>

    <div class="row"><span>User ID:</span> {player.userId}</div>
    <div class="row"><span>Username:</span> {player.user_name}</div>
    <div class="row"><span>Wallet USD:</span> {usd_bal}</div>
    <div class="row"><span>Wallet VND:</span> {vnd_bal}</div>

    <div class="row"><span>Lobby token (exp in {settings.LOBBY_TOKEN_EXP_MIN}m):</span></div>
    <pre>{lobby_token}</pre>

    <div class="row"><span>BSG token (game):</span></div>
    <pre>{bsg_token}</pre>

    <div class="row"><span>Start Game URL:</span></div>
    <pre>{start_url}</pre>

    <a class="button" href="{start_url}" target="_blank" rel="noopener">Launch test game</a>
    <button class="button" onclick="logout()">Logout</button>

    <script>
      async function logout() {{
        try {{
          const resp = await fetch('/auth/logout', {{
            method: 'POST',
            headers: {{
              'Authorization': 'Bearer {lobby_token}',
            }},
          }});
          if (resp.ok) {{
            alert('Logged out.');
            window.location.href = '/';
          }} else {{
            const t = await resp.text();
            alert('Logout failed: ' + t);
          }}
        }} catch (e) {{
          alert('Logout error: ' + e);
        }}
      }}
    </script>
    """
    return HTMLResponse(html)
