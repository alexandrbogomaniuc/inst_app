# igw/app/routes/oauth_instagram.py
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session

from igw.app.config import settings
from igw.app.db import get_db
from igw.app.models import Player, Wallet
from igw.app.utils.security import create_token

router = APIRouter(prefix="/oauth/instagram", tags=["instagram"])

# --- Instagram Basic Display OAuth endpoints ---
AUTHORIZE_URL = "https://api.instagram.com/oauth/authorize"
TOKEN_URL = "https://api.instagram.com/oauth/access_token"
ME_URL = "https://graph.instagram.com/me"  # with Basic Display token: fields=id,username,(account_type,media_count)


@router.get("/start")
async def instagram_login():
    """
    Step 1: Redirect the user to Instagram's Basic Display authorize dialog.
    """
    params = {
        "client_id": settings.IG_CLIENT_ID,
        "redirect_uri": settings.IG_REDIRECT_URI,
        "response_type": "code",
        "scope": settings.IG_SCOPES,      # e.g. "user_profile" (and "user_media" if needed)
    }
    return RedirectResponse(f"{AUTHORIZE_URL}?{urlencode(params)}")


@router.get("/callback")
async def instagram_callback(
    request: Request,
    code: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
):
    """
    Step 2: Exchange the code for a short-lived access_token + user_id.
    Step 3: Fetch basic profile (id, username) from graph.instagram.com/me.
    Step 4: Upsert Player + ensure USD/VND wallets exist.
    """
    if error:
        raise HTTPException(400, f"Instagram error: {error}")
    if not code:
        raise HTTPException(400, "Missing 'code'.")

    # Exchange code for token
    async with httpx.AsyncClient(timeout=20) as client:
        form = {
            "client_id": settings.IG_CLIENT_ID,
            "client_secret": settings.IG_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "redirect_uri": settings.IG_REDIRECT_URI,
            "code": code,
        }
        token_resp = await client.post(TOKEN_URL, data=form)
        if token_resp.status_code != 200:
            raise HTTPException(502, f"Token exchange failed: {token_resp.text}")

        tok = token_resp.json()
        access_token = tok.get("access_token")
        user_id = tok.get("user_id")
        if not access_token or not user_id:
            raise HTTPException(502, "Token response missing access_token or user_id.")

        # Fetch basic profile
        me_params = {"fields": "id,username,account_type,media_count", "access_token": access_token}
        me_resp = await client.get(ME_URL, params=me_params)
        if me_resp.status_code != 200:
            raise HTTPException(502, f"Failed to fetch profile: {me_resp.text}")
        me = me_resp.json()

    ig_id = str(user_id)
    username = me.get("username") or f"ig_{ig_id}"

    # Upsert Player
    player: Player | None = db.query(Player).filter(Player.ext_user_id == ig_id).first()
    if not player:
        # Ensure unique placeholder email (email is NOT NULL + UNIQUE in your schema)
        base_email = f"{username}@instagram.com"
        email = base_email
        n = 1
        while db.query(Player).filter(Player.email == email).first() is not None:
            n += 1
            email = f"{username}+{n}@instagram.com"

        player = Player(
            user_name=username,
            ext_user_id=ig_id,
            email=email,
            language_code="en",
            status="active",
        )
        db.add(player)
        db.flush()  # get player.userId

        # Ensure USD & VND wallets
        for ccy in ("USD", "VND"):
            db.add(Wallet(userId=player.userId, wallet_type=settings.DEFAULT_WALLET_TYPE, currency_code=ccy, balance=0))
        db.commit()
    else:
        # Make sure wallets exist for USD & VND
        existing = {w.currency_code for w in player.wallets}
        for ccy in {"USD", "VND"} - existing:
            db.add(Wallet(userId=player.userId, wallet_type=settings.DEFAULT_WALLET_TYPE, currency_code=ccy, balance=0))
        db.commit()

    # Issue an app session token (optional, for your front-end)
    token = create_token({"sub": str(player.userId), "username": player.user_name})

    # Return JSON (you can redirect to your UI instead if you want)
    return JSONResponse(
        {
            "ok": True,
            "user": {"id": player.userId, "username": player.user_name},
            "token": token,
        }
    )
