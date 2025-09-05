# igw/app/routes/oauth_instagram.py
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

    # IMPORTANT: host is api.instagram.com for Basic Display
    base = "https://api.instagram.com/oauth/authorize"
    params = {
        "client_id": settings.IGBD_APP_ID,
        "redirect_uri": settings.IGBD_REDIRECT_URI,
        "scope": settings.IGBD_SCOPES,  # user_profile (and optionally user_media)
        "response_type": "code",
    }
    return RedirectResponse(f"{base}?{urlencode(params)}")


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

        # 2) Fetch username via Graph API (Basic Display-compatible)
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

    # 5) Simple confirmation page
    html = f"""
    <style>
      body{{font-family:ui-sans-serif,system-ui,Segoe UI,Roboto,Arial;margin:40px;line-height:1.4}}
      pre{{background:#f6f8fa;padding:16px;border-radius:8px;overflow:auto}}
    </style>
    <h2>Instagram login — success</h2>
    <pre>
user:   {{ "id": {player.userId}, "username": "{player.user_name}" }}
token:  "{lobby_token}"
    </pre>
    """
    return HTMLResponse(html)
