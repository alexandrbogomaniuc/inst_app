from __future__ import annotations

from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session

from igw.app.config import settings
from igw.app.db import get_db
from igw.app.models import Player, UserSession
from igw.app.utils.account import ensure_wallets_for_user
from igw.app.utils.security import create_token
from igw.app.providers.bsg.settings import (
    bsg_settings,
    get_bank_settings,
)

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
    Instagram Basic Display OAuth — Instagram-branded consent UI.
    """
    _require_basic_display_config()

    # Basic Display uses api.instagram.com
    base = "https://api.instagram.com/oauth/authorize"
    params = {
        "client_id": settings.IGBD_APP_ID,
        "redirect_uri": settings.IGBD_REDIRECT_URI,
        "scope": settings.IGBD_SCOPES,  # e.g. instagram_business_basic
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
    Exchange ?code -> access_token, read user id/username,
    upsert Player, ensure wallets, create a lobby session,
    create a BSG game session/token, and render a simple page.
    """
    _require_basic_display_config()

    if error:
        raise HTTPException(status_code=400, detail=f"OAuth error: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="Missing ?code")

    async with httpx.AsyncClient(timeout=25) as cx:
        # 1) Token exchange
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
        try:
            token_resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=400, detail=f"Token exchange failed: {e.response.text}")

        tok = token_resp.json()
        access_token = tok.get("access_token")
        ig_user_id = tok.get("user_id")
        if not access_token or not ig_user_id:
            raise HTTPException(status_code=400, detail=f"Malformed token response: {tok}")

        # 2) Fetch username
        me_resp = await cx.get(
            f"https://graph.instagram.com/{ig_user_id}",
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
        email = f"{username}@instagram.com"  # placeholder
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

    # 4) Create a lobby session token (for your site)
    lobby_token = create_token({"uid": player.userId, "type": "lobby"})
    sess_lobby = UserSession(
        userId=player.userId,
        token=lobby_token,
        session_type="lobby",
        provider="instagram_basic_display",
        status="active",
        Login_IP=(request.client.host if request and request.client else None),
    )
    db.add(sess_lobby)

    # 5) Create a BSG game token + session (this is the one to pass to BSG)
    base_cfg = bsg_settings()
    default_bank_id = base_cfg.BSG_DEFAULT_BANK_ID or 6111
    bank = get_bank_settings(int(default_bank_id))

    game_token = create_token(
        {"uid": player.userId, "type": "game", "provider": "bsg", "bankId": bank.BANK_ID, "gameId": bank.BSG_DEFAULT_GAME_ID},
        exp_minutes=bank.BSG_TOKEN_GAME_EXP_MIN,
    )
    sess_game = UserSession(
        userId=player.userId,
        token=game_token,
        session_type="game",
        provider="bsg",
        status="active",
        Login_IP=(request.client.host if request and request.client else None),
        meta={"bankId": bank.BANK_ID, "gameId": bank.BSG_DEFAULT_GAME_ID},
    )
    db.add(sess_game)
    db.commit()

    # 6) Build Start Game URL using BSG token (not the lobby token)
    start_host = bank.BSG_CW_START_BASE or base_cfg.BSG_CW_START_BASE_DEFAULT or "https://5for5media-ng-copy.nucleusgaming.com"
    start_url = (
        f"{start_host}/cwstartgamev2.do?"
        f"bankId={bank.BANK_ID}"
        f"&gameId={bank.BSG_DEFAULT_GAME_ID}"
        f"&mode=real"
        f"&token={game_token}"
        f"&lang=en"
    )

    html = f"""
    <style>
      body{{font-family:ui-sans-serif,system-ui,Segoe UI,Roboto,Arial;margin:40px;line-height:1.45}}
      pre{{background:#f6f8fa;padding:14px;border-radius:8px;overflow:auto}}
      a.button{{display:inline-block;padding:10px 14px;border-radius:8px;text-decoration:none;border:1px solid #d0d7de}}
    </style>
    <h2>Instagram login — success</h2>
    <pre>user:   {{ "id": {player.userId}, "username": "{player.user_name}" }}</pre>
    <pre>lobby_token:\n{lobby_token}</pre>
    <pre>bsg_game_token:\n{game_token}</pre>
    <p><a class="button" href="{start_url}" target="_blank">Start Test Game (bank {bank.BANK_ID}, game {bank.BSG_DEFAULT_GAME_ID})</a></p>
    <pre>Launch URL:\n{start_url}</pre>
    """
    return HTMLResponse(html)
