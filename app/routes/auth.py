from fastapi import APIRouter, Depends, HTTPException, status, Header
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session
from datetime import datetime
from igw.app.db import get_db
from igw.app.models import Player, UserSession
from igw.app.utils.security import hash_password, create_token,decode_token

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    first_name: str
    last_name: str
    language_code: str = "en"
    country: str | None = None


class RegisterResponse(BaseModel):
    user_id: int
    email: EmailStr
    token: str


@router.post("/register", response_model=RegisterResponse)
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    existing = db.scalar(select(Player).where(Player.email == req.email))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        )

    player = Player(
        email=req.email,
        password_hash=hash_password(req.password),
        first_name=req.first_name,
        last_name=req.last_name,
        language_code=req.language_code,
        country=req.country,
        status="active",
    )
    db.add(player)
    db.flush()  # get new id
    token = create_token(str(player.user_id))
    db.commit()

    return RegisterResponse(user_id=player.user_id, email=player.email, token=token)

@router.post("/logout")
def logout(authorization: str | None = Header(None), db: Session = Depends(get_db)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=400, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = decode_token(token)
        uid = payload.get("uid") or int(payload.get("sub"))
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    s = (
        db.query(UserSession)
        .filter(UserSession.userId == uid, UserSession.token == token, UserSession.status == "active")
        .first()
    )
    if not s:
        # idempotent: already closed or not found
        return {"result": "ok"}

    s.status = "logged_out"
    s.logout_time = datetime.utcnow()
    db.add(s)
    db.commit()
    return {"result": "ok"}