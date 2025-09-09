# igw/app/routes/oauth_instagram.py
from __future__ import annotations
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session

from igw.app.config import settings
from igw.app.db import get_db
from igw.app.models import Player, UserSession, Wallet
from igw.app.utils.account import ensure_wallets_for_user
from igw.app.utils.security import create_token
from igw.app.providers.bsg.settings import bsg_settings, list_available_banks, get_bank_settings

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


def _pick_bank_id() -> str:
    base = bsg_settings()
    if base.BSG_DEFAULT_BANK_ID:
        return base.BSG_DEFAULT_BANK_ID
    banks = list_available_banks()
    if not banks:
        raise HTTPException(status_code=500, detail="No BSG bank configured")
    return banks[0]


@router.get("/start")
async def instagram_login():
    """
    Instagram Basic Display OAuth — Instagram-branded consent screen.
    """
    _require_basic_display_config()

    base = "https://api.instagram.com/oauth/authorize"
    params = {
        "client_id": settings.IGBD_APP_ID,
        "redirect_uri": settings.IGBD_REDIRECT_URI,
        "scope": settings.IGBD_SCOPES,  # you observed 'instagram_business_basic' works for you
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
    Exchange ?code -> Basic Display access token, read user id/username,
    upsert Player, ensure wallets, create a lobby session, and show a simple page.
    """
    _require_basic_display_config()

    if error:
        raise HTTPException(status_code=400, detail=f"OAuth error: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="Missing ?code")

    async with httpx.AsyncClient(timeout=25) as cx:
        # 1) Exchange code for access token (POST form)
        token_url = "https://api.instagram.com/oauth/access_token"
        print(f"[IG-OAUTH] token POST -> {token_url}")
        token_resp = await cx.post(
            token_url,
            data={
                "client_id": settings.IGBD_APP_ID,
                "client_secret": settings.IGBD_APP_SECRET,
                "grant_type": "authorization_code",
                "redirect_uri": settings.IGBD_REDIRECT_URI,
                "code": code,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            token_resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=400, detail=f"Token exchange failed: {e.response.text}")

        tok = token_resp.json()
        access_token = tok.get("access_token")
        ig_user_id = tok.get("user_id")
        if not access_token or not ig_user_id:
            raise HTTPException(status_code=400, detail=f"Malformed token response: {tok}")

        # 2) Fetch username via Graph API (Basic Display-compatible)
        me_url = f"https://graph.instagram.com/{ig_user_id}"
        print(f"[IG-OAUTH] me GET -> {me_url}?fields=id,username&access_token=***")
        me_resp = await cx.get(
            me_url,
            params={"fields": "id,username", "access_token": access_token},
        )
        try:
            me_resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=400, detail=f"Fetch IG user failed: {e.response.text}")

        me = me_resp.json()
        username = me.get("username") or f"ig_{ig_user_id}"

    # 3) Upsert Player
    player = db.query(Player).filter(Player.ext_user_id == str(ig_user_id)).first()
    if not player:
        # fallback email as agreed
        email = f"{username}@instagram.com"
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

    # 4) Create lobby session (JWT)
    lobby_token = create_token({"uid": player.userId, "type": "lobby"})
    sess = UserSession(
        userId=player.userId,
        token=lobby_token,
        session_type="lobby",
        provider="instagram_basic_display",
        status="active",
        Login_IP=(request.client.host if request and request.client else None),
    )
    db.add(sess)
    db.commit()

    # 5) Build a Start Game URL from per-bank settings (NO hardcoded gameId)
    bank_id = _pick_bank_id()
    bank = get_bank_settings(bank_id)
    start_host = bank.BSG_CW_START_BASE or bsg_settings().BSG_CW_START_BASE_DEFAULT or "https://5for5media-ng-copy.nucleusgaming.com"
    start_url = (
        f"{start_host}/cwstartgamev2.do?"
        f"bankId={bank.BSG_BANK_ID}"
        f"&gameId={bank.BSG_DEFAULT_GAME_ID}"
        f"&mode=real&token={lobby_token}&lang=en"
    )

    # 6) Show confirmation page (user/session + start link)
    html = f"""
    <style>
      body{{font-family:ui-sans-serif,system-ui,Segoe UI,Roboto,Arial;margin:40px;line-height:1.4}}
      pre{{background:#f6f8fa;padding:16px;border-radius:8px;overflow:auto}}
      a.button{{display:inline-block;margin-top:12px;padding:10px 16px;border-radius:8px;border:1px solid #ddd;text-decoration:none}}
    </style>
    <h2>Instagram login — success</h2>
    <pre>
user:   {{ "id": {player.userId}, "username": "{player.user_name}" }}
token:  "{lobby_token}"
bank:   "{bank.BSG_BANK_ID}"
game:   {bank.BSG_DEFAULT_GAME_ID}
    </pre>
    <a class="button" href="{start_url}" target="_blank">Start Test Game</a>
    <p style="margin-top:8px"><small>URL: {start_url}</small></p>
    """
    return HTMLResponse(html)
