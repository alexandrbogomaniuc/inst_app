# igw/app/routes/oauth_instagram.py
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse
import httpx
from urllib.parse import urlencode
import re

from igw.app.db import get_db
from igw.app.models import Player, Wallet
from igw.app.config import settings

router = APIRouter(prefix="/oauth/instagram", tags=["instagram"])

# Instagram OAuth endpoints
OAUTH_AUTHORIZE_URL = "https://www.instagram.com/oauth/authorize"
OAUTH_TOKEN_URL = "https://api.instagram.com/oauth/access_token"


def ensure_two_wallets(db, player_id: int):
    """Create USD and VND CASH wallets if they don't already exist."""
    for currency in ("USD", "VND"):
        exists = (
            db.query(Wallet)
            .filter(
                Wallet.user_id == player_id,
                Wallet.currency_code == currency,
                Wallet.wallet_type == "CASH",
            )
            .first()
        )
        if not exists:
            db.add(
                Wallet(
                    user_id=player_id,
                    wallet_type="CASH",
                    currency_code=currency,
                    balance=0,
                )
            )


def make_instagram_email(username: str | None, ig_id: str) -> str:
    """
    Build placeholder email in the form `<accountname>@instagram.com`.
    If username is missing or invalid, fall back to ig_<id>@instagram.com.
    """
    if username:
        local = re.sub(r"[^a-zA-Z0-9._+-]", "", username).lower()
        if local:
            return f"{local}@instagram.com"
    return f"ig_{ig_id}@instagram.com"


@router.get("/start")
async def instagram_login():
    params = {
        "client_id": settings.ig_client_id,          # <— lower case field names
        "redirect_uri": str(settings.ig_redirect_uri),
        "response_type": "code",
        "scope": "instagram_business_basic",
    }
    return RedirectResponse(f"{OAUTH_AUTHORIZE_URL}?{urlencode(params)}")


@router.get("/callback")
async def instagram_callback(code: str, request: Request, db=Depends(get_db)):
    # 1) Exchange code -> access_token
    data = {
        "client_id": settings.ig_client_id,
        "client_secret": settings.ig_client_secret,
        "grant_type": "authorization_code",
        "redirect_uri": str(settings.ig_redirect_uri),
        "code": code,
    }
    async with httpx.AsyncClient(timeout=20) as client:
        token_resp = await client.post(OAUTH_TOKEN_URL, data=data)

    if token_resp.status_code != 200:
        raise HTTPException(400, f"token exchange failed: {token_resp.text}")

    tok = token_resp.json()
    access_token = tok.get("access_token")
    user_id = tok.get("user_id")
    if not access_token or not user_id:
        raise HTTPException(400, "invalid token response from Instagram")

    # 2) Fetch the IG user basic info (id, username)
    async with httpx.AsyncClient(timeout=20) as client:
        me_resp = await client.get(
            "https://graph.instagram.com/me",
            params={"fields": "id,username", "access_token": access_token},
        )

    if me_resp.status_code != 200:
        raise HTTPException(400, f"me fetch failed: {me_resp.text}")

    me = me_resp.json()
    ig_id = str(me.get("id"))
    ig_username = me.get("username")

    # 3) Upsert Player using ext_user_id (Instagram id)
    player = db.query(Player).filter(Player.ext_user_id == ig_id).first()

    if not player:
        # Build placeholder email using the Instagram username
        email = make_instagram_email(ig_username, ig_id)

        # Satisfy NOT NULL constraints on email & password_hash
        player = Player(
            ext_user_id=ig_id,
            user_name=ig_username,     # keep if your table has this column
            email=email,               # e.g. "accountname@instagram.com"
            password_hash="",          # placeholder; you can force “complete profile” later
            language_code="en",
            status="active",
        )
        db.add(player)
        db.flush()  # to get player.user_id

        # Create USD & VND wallets
        ensure_two_wallets(db, player.user_id)
        db.commit()
    else:
        # Backfill email if empty/NULL
        if not player.email:
            player.email = make_instagram_email(ig_username, ig_id)
        ensure_two_wallets(db, player.user_id)
        db.commit()

    return JSONResponse(
        {
            "ok": True,
            "player_id": player.user_id,
            "ext_user_id": player.ext_user_id,
            "user_name": getattr(player, "user_name", None),
            "email": player.email,
        }
    )
