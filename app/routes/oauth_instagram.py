# igw/app/routes/oauth_instagram.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session
from urllib.parse import urlencode
import httpx
from datetime import datetime, timedelta

from igw.app.config import settings
from igw.app.db import get_db
from igw.app.models import Player, UserSession, Wallet
from igw.app.utils.security import create_token
from igw.app.utils.account import ensure_wallets_for_user


router = APIRouter(prefix="/oauth/instagram", tags=["oauth-instagram"])


@router.get("/start")
async def instagram_login_start() -> RedirectResponse:
    """
    Starts OAuth.
    - instagram_login -> instagram.com authorize (user_profile scope)
    - facebook_login  -> facebook.com dialog (business scopes)
    """
    if settings.OAUTH_FLOW == "instagram_login":
        if not settings.IGBD_APP_ID:
            raise HTTPException(status_code=500, detail="IGBD_APP_ID not configured")
        params = {
            "client_id": settings.IGBD_APP_ID,
            "redirect_uri": settings.IG_REDIRECT_URI,
            "response_type": "code",
            "scope": settings.IG_SCOPES,  # typically "user_profile"
        }
        url = f"https://www.instagram.com/oauth/authorize?{urlencode(params)}"
        return RedirectResponse(url)

    # Fallback: Business login via Facebook dialog
    if not settings.IG_CLIENT_ID:
        raise HTTPException(status_code=500, detail="IG_CLIENT_ID not configured")
    params = {
        "client_id": settings.IG_CLIENT_ID,
        "redirect_uri": settings.IG_REDIRECT_URI,
        "response_type": "code",
        "scope": settings.IG_SCOPES,  # e.g., instagram_basic,pages_show_list,...
    }
    url = f"https://www.facebook.com/{settings.GRAPH_VERSION}/dialog/oauth?{urlencode(params)}"
    return RedirectResponse(url)


@router.get("/callback")
async def instagram_callback(request: Request, code: str | None = None, error: str | None = None, db: Session = Depends(get_db)):
    if error:
        raise HTTPException(status_code=400, detail=f"OAuth error: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="Missing 'code' in callback")

    client_ip = request.client.host if request.client else None

    if settings.OAUTH_FLOW == "instagram_login":
        # Exchange code for access_token using the Instagram Login product
        if not settings.IGBD_APP_ID or not settings.IGBD_APP_SECRET:
            raise HTTPException(status_code=500, detail="IGBD_APP_ID/IGBD_APP_SECRET not configured")

        token_url = "https://api.instagram.com/oauth/access_token"
        form = {
            "client_id": settings.IGBD_APP_ID,
            "client_secret": settings.IGBD_APP_SECRET,
            "grant_type": "authorization_code",
            "redirect_uri": settings.IG_REDIRECT_URI,
            "code": code,
        }
        async with httpx.AsyncClient(timeout=20) as client:
            tok = await client.post(token_url, data=form)
            if tok.status_code != 200:
                raise HTTPException(status_code=502, detail=f"Token exchange failed: {tok.text}")
            data = tok.json()
            access_token = data.get("access_token")
            ig_user_id = str(data.get("user_id"))

            if not access_token or not ig_user_id:
                raise HTTPException(status_code=502, detail="Token exchange response missing fields")

            # Fetch username
            me_url = "https://graph.instagram.com/me"
            params = {"fields": "id,username", "access_token": access_token}
            me = await client.get(me_url, params=params)
            if me.status_code != 200:
                raise HTTPException(status_code=502, detail=f"Fetch profile failed: {me.text}")
            me_data = me.json()
            username = me_data.get("username") or f"ig_{ig_user_id}"

    else:
        # (Optional) Implement FB dialog code→token exchange if you want to keep the business flow too.
        raise HTTPException(status_code=501, detail="facebook_login callback not implemented in this handler")

    # Upsert player
    player = db.query(Player).filter(Player.ext_user_id == ig_user_id).first()
    if not player:
        player = Player(
            user_name=username,
            ext_user_id=ig_user_id,
            email=f"{username}@instagram.com",
            language_code="en",
            status="active",
        )
        db.add(player)
        db.flush()  # to get player.userId

    # Always keep username up-to-date
    if player.user_name != username:
        player.user_name = username

    # Ensure wallets (USD, VND)
    ensure_wallets_for_user(db, player.userId)

    # Create a lobby session
    jwt_payload = {"sub": str(player.userId), "type": "lobby"}
    lobby_token = create_token(jwt_payload, expires_minutes=60 * 24)  # 24h
    session = UserSession(
        userId=player.userId,
        token=lobby_token,
        session_type="lobby",
        provider=None,
        meta={"ig_user_id": ig_user_id},
        login_time=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(hours=24),
        status="active",
        Login_IP=client_ip,
    )
    db.add(session)
    db.commit()

    # Get balances for pretty page
    wallets = {w.currency_code: w.balance for w in db.query(Wallet).filter(Wallet.userId == player.userId).all()}
    usd = wallets.get("USD", 0)
    vnd = wallets.get("VND", 0)

    html = f"""
    <html>
      <head>
        <title>IGW — Login Complete</title>
        <style>
          body {{ font-family: system-ui,-apple-system,Segoe UI,Roboto; padding: 32px; background: #0b1020; color: #eef2ff; }}
          .card {{ max-width: 720px; margin: auto; background: #121a35; border-radius: 16px; padding: 24px; box-shadow: 0 10px 30px rgba(0,0,0,.3); }}
          h1 {{ margin-top: 0; }}
          .row {{ display:flex; gap:16px; }}
          .pill {{ background:#1e2a55; border-radius:12px; padding:8px 12px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
          code {{ word-break: break-all; }}
        </style>
      </head>
      <body>
        <div class="card">
          <h1>Welcome, {username}</h1>
          <p>User ID: <span class="pill">{player.userId}</span> &nbsp; IG ID: <span class="pill">{ig_user_id}</span></p>
          <h3>Lobby Token (JWT)</h3>
          <code>{lobby_token}</code>
          <h3>Wallets</h3>
          <div class="row">
            <div class="pill">USD: {usd:.2f}</div>
            <div class="pill">VND: {vnd:.2f}</div>
          </div>
        </div>
      </body>
    </html>
    """
    return HTMLResponse(html)
