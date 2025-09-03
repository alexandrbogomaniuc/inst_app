from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from igw.app.db import get_db
from igw.app.models import Player
from igw.app.utils.security import hash_password, create_token

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
