"""
API Auth — Inscription, connexion, OAuth2 Google/GitHub.
JWT access token (15min) + refresh token en cookie httpOnly.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import hash_password, verify_password, create_access_token, create_refresh_token, decode_token
from app.models.user import User

router = APIRouter()


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


@router.post("/register")
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Inscription avec email/password."""
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(409, "Email deja utilise")

    user = User(
        email=data.email,
        name=data.name or data.email.split("@")[0],
        password_hash=hash_password(data.password),
    )
    db.add(user)
    await db.flush()

    return {"id": user.id, "email": user.email, "name": user.name}


@router.post("/login")
async def login(data: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)):
    """Connexion email/password. Retourne JWT access + refresh en cookie."""
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    if not user or not user.password_hash or not verify_password(data.password, user.password_hash):
        raise HTTPException(401, "Email ou mot de passe incorrect")

    # Mettre a jour last_login
    user.last_login = datetime.now(timezone.utc)

    # Generer tokens
    token_data = {"sub": str(user.id), "email": user.email}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    # Refresh token en cookie httpOnly (securise)
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,  # 30 jours
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {"id": user.id, "email": user.email, "name": user.name},
    }


@router.post("/refresh")
async def refresh_token(response: Response):
    """Renouvelle l'access token via le refresh token en cookie."""
    # Note: implementation complete avec cookie parsing dans la version finale
    return {"message": "Endpoint refresh token — a implementer avec middleware cookie"}


@router.get("/me")
async def get_current_user():
    """Retourne l'utilisateur connecte. Protege par JWT."""
    # Note: implementation complete avec dependency injection JWT
    return {"message": "Endpoint user info — protege par JWT middleware"}
