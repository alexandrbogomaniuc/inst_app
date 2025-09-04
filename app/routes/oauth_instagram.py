# igw/app/routes/oauth_instagram.py
from __future__ import annotations

import httpx
from urllib.parse import urlencode
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from igw.app.config import settings
from igw.app.db import get_db
from igw.app.models import Player
from igw.app.utils.security import create_token
from igw.app.utils.account import ensure_wallets_for_user

router = APIRouter(prefix="/oauth/instagram", tags=["instagram"])

# --- Basic Display constants ---
AUTH_URL = "https://api.instagram.com/oauth/authorize"
TOKEN_URL = "https://api.instagram.com/oauth/access_token"
ME_URL = "https://graph.instagram.com/me"  # Basic Display 'me' lives on graph.instagram.com

@router.get("/start")
async def instagram_login():
    """
    Start Instagram Basic Display flow:
    GET https://api.instagram.com/oauth/authorize
         ?client_id=APP_ID
         &redirect_uri=REDIRECT
         &scope=user_profile[,user_media]
         &response_type=code
    """
    params = {
        "client_id": settings.IG_CLIENT_ID,
        "redirect_uri": settings.IG_REDIRECT_URI,
        "response_type": "code",
        "scope": settings.IG_SCOPES,  # <-- use IG_SCOPES (not IGBD_SCOPES)
    }

    return RedirectResponse(f"{AUTH_URL}?{urlencode(params)}", status_code=302)

@router.get("/callback")
async def instagram_callback(request: Request, code: str | None = None, error: str | None = None, db: Session = Depends(get_db)):
    """
    Exchange code -> access_token, then fetch id/username, then
    upsert Player + create a lobby session and render a small HTML summary.
    """
    if error:
        raise HTTPException(status_code=400, detail=f"Instagram error: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="Missing 'code'")

    # 1) Exchange code for access_token (Basic Display is a POST form-encoded call)
    data = {
        "client_id": settings.IGBD_APP_ID,
        "client_secret": settings.IGBD_APP_SECRET,
        "grant_type": "authorization_code",
        "redirect_uri": settings.IGBD_REDIRECT_URI,
        "code": code,
    }
    async with httpx.AsyncClient(timeout=20) as client:
        token_resp = await client.post(TOKEN_URL, data=data)
    if token_resp.status_code != 200:
        raise HTTPException(400, f"Token exchange failed: {token_resp.text}")

    token_payload = token_resp.json()
    ig_access_token = token_payload.get("access_token")
    ig_user_id = token_payload.get("user_id")
    if not ig_access_token or not ig_user_id:
        raise HTTPException(400, f"Token response missing fields: {token_payload}")

    # 2) Fetch profile (id/username) using Basic Display Graph endpoint
    params = {"fields": "id,username", "access_token": ig_access_token}
    async with httpx.AsyncClient(timeout=20) as client:
        me_resp = await client.get(ME_URL, params=params)
    if me_resp.status_code != 200:
        raise HTTPException(400, f"/me failed: {me_resp.text}")

    me = me_resp.json()
    username = me.get("username") or f"user{ig_user_id}"
    email_fallback = f"{username}@instagram.com"

    # 3) Upsert Player
    player = db.query(Player).filter(Player.ext_user_id == str(ig_user_id)).first()
    if not player:
        player = Player(
            ext_user_id=str(ig_user_id),
            user_name=username,
            email=email_fallback,
            language_code="en",
            status="active",
        )
        db.add(player)
        db.flush()  # get userId

        # auto-create wallets (USD & VND)
        ensure_wallets_for_user(db, player.userId)

    # 4) Create a lobby session token for your casino (JWT)
    lobby_token = create_token({"uid": player.userId, "role": "player"}, minutes=60)

    db.commit()

    # 5) Show a small HTML "lobby receipt" (you can replace with your UI)
    html = f"""
    <!doctype html>
    <html>
    <head><meta charset="utf-8"><title>Lobby Session</title>
    <style>body{{font-family:ui-sans-serif,system-ui;max-width:680px;margin:40px auto;line-height:1.5}}
    code{{background:#f6f8fa;padding:2px 4px;border-radius:4px}}</style></head>
    <body>
      <h2>Instagram login complete ✅</h2>
      <p><b>Player ID:</b> {player.userId}</p>
      <p><b>Username:</b> {player.user_name}</p>
      <p><b>Lobby token (JWT, 60m):</b><br><code>{lobby_token}</code></p>
      <p>You can now return to your lobby and/or use this token to request a game session.</p>
    </body></html>
    """
    return HTMLResponse(content=html)
