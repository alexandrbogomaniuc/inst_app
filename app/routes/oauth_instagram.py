from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session as OrmSession
import requests
from ..config import settings
from ..db import get_db
from ..models import Player, Wallet, Session as DbSession
from ..utils.security import create_token

router = APIRouter(prefix="/oauth/instagram", tags=["oauth-instagram"])

def _graph_url(path: str) -> str:
    base = f"https://graph.facebook.com/{settings.graph_version}"
    return f"{base}{path}"

@router.get("/start")
async def instagram_login():
    # Use Facebook OAuth dialog for Instagram Business Login
    dialog = f"https://www.facebook.com/{settings.graph_version}/dialog/oauth"
    scope = ",".join([
        "public_profile",
        "email",
        "pages_show_list",
        "pages_read_engagement",
        "instagram_basic",
        "instagram_manage_comments",
        "instagram_manage_messages",
        "instagram_manage_insights",
    ])
    params = {
        "client_id": settings.ig_client_id,
        "redirect_uri": settings.ig_redirect_uri,
        "response_type": "code",
        "scope": scope,
    }
    return RedirectResponse(f"{dialog}?"+ "&".join(f"{k}={requests.utils.quote(v)}" for k,v in params.items()))

@router.get("/callback")
async def instagram_callback(request: Request, code: str | None = None, error: str | None = None, db: OrmSession = Depends(get_db)):
    if error:
        raise HTTPException(status_code=400, detail=f"OAuth error: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="Missing code")

    # 1) Exchange code for a Facebook user access token
    tok_res = requests.get(_graph_url("/oauth/access_token"), params={
        "client_id": settings.ig_client_id,
        "client_secret": settings.ig_client_secret,
        "redirect_uri": settings.ig_redirect_uri,
        "code": code,
    }, timeout=15)
    if tok_res.status_code != 200:
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {tok_res.text}")
    access_token = tok_res.json().get("access_token")

    # 2) Find an IG Business account linked to the user's Pages
    pages = requests.get(_graph_url("/me/accounts"), params={"access_token": access_token, "fields": "instagram_business_account"}, timeout=15)
    if pages.status_code != 200:
        raise HTTPException(status_code=400, detail=f"/me/accounts failed: {pages.text}")

    data = pages.json().get("data", [])
    ig_user_id = None
    for p in data:
        iba = p.get("instagram_business_account")
        if iba and "id" in iba:
            ig_user_id = iba["id"]
            break

    if not ig_user_id:
        # user has no linked IG business account
        raise HTTPException(status_code=403, detail="No linked Instagram Business account on the Facebook profile you used.")

    # 3) Try to get IG username so we can build a non-null email
    ig_profile = requests.get(_graph_url(f"/{ig_user_id}"), params={"access_token": access_token, "fields": "id,username"}, timeout=15)
    username = None
    if ig_profile.status_code == 200:
        username = ig_profile.json().get("username")

    # Fallbacks for required DB fields
    username = username or f"ig_{ig_user_id}"
    email = f"{username}@instagram.com"  # << non-null, unique enough for our case
    # Password is required by schema; mark as OAuth-only
    password_hash = f"oauth:{ig_user_id}"

    # 4) Upsert player
    player = db.query(Player).filter(Player.ext_user_id == str(ig_user_id)).first()
    if not player:
        player = Player(
            ext_user_id=str(ig_user_id),
            user_name=username,
            email=email,
            password_hash=password_hash,
            language_code="en",
            status="active",
        )
        db.add(player)
        db.flush()  # to get player.userId

        # 5) Ensure two wallets (USD & VND)
        usd = Wallet(userId=player.userId, wallet_type="main", currency_code="USD")
        vnd = Wallet(userId=player.userId, wallet_type="main", currency_code="VND")
        db.add_all([usd, vnd])
    else:
        # backfill username/email if they were blank
        if not player.user_name:
            player.user_name = username
        if not player.email:
            player.email = email

    # 6) Create session + JWT
    jwt_token = create_token(sub=str(player.userId), extra={"ig_user_id": str(ig_user_id)})
    login_ip = request.client.host if request.client else "unknown"
    db.add(DbSession(userId=player.userId, token=jwt_token, Login_IP=login_ip))

    db.commit()

    return JSONResponse({
        "ok": True,
        "userId": player.userId,
        "ext_user_id": player.ext_user_id,
        "username": player.user_name,
        "session_token": jwt_token,
    })
