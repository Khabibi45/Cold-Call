"""
API Auth — Inscription, connexion, refresh token, logout, profil utilisateur.
JWT access token (15min) + refresh token en cookie httpOnly.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
)
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
async def refresh(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    Renouvelle l'access token via le refresh token stocke en cookie httpOnly.
    Verifie que le token est de type 'refresh' et que l'utilisateur existe toujours.
    """
    if not refresh_token:
        raise HTTPException(401, "Refresh token manquant")

    # Decoder et valider le refresh token
    payload = decode_token(refresh_token)
    if payload is None:
        raise HTTPException(401, "Refresh token invalide ou expire")

    # Verifier que c'est bien un refresh token
    if payload.get("type") != "refresh":
        raise HTTPException(401, "Token de mauvais type")

    # Verifier que l'utilisateur existe toujours et est actif
    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(401, "Refresh token invalide")

    try:
        user_id = int(user_id_str)
    except (ValueError, TypeError):
        raise HTTPException(401, "Refresh token invalide")

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(401, "Utilisateur introuvable")

    if not user.is_active:
        raise HTTPException(403, "Compte desactive")

    # Generer un nouveau access token
    token_data = {"sub": str(user.id), "email": user.email}
    new_access_token = create_access_token(token_data)

    # Rotation du refresh token (securite : nouveau refresh a chaque refresh)
    new_refresh_token = create_refresh_token(token_data)
    response.set_cookie(
        key="refresh_token",
        value=new_refresh_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )

    return {
        "access_token": new_access_token,
        "token_type": "bearer",
    }


@router.get("/me")
async def me(current_user: User = Depends(get_current_user)):
    """Retourne les informations de l'utilisateur connecte. Protege par JWT."""
    return {
        "id": current_user.id,
        "email": current_user.email,
        "name": current_user.name,
        "avatar_url": current_user.avatar_url,
        "is_admin": current_user.is_admin,
        "subscription_plan": current_user.subscription_plan,
        "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
        "last_login": current_user.last_login.isoformat() if current_user.last_login else None,
    }


@router.post("/logout")
async def logout(response: Response):
    """Deconnexion — supprime le cookie refresh_token."""
    response.delete_cookie(
        key="refresh_token",
        httponly=True,
        secure=True,
        samesite="lax",
    )
    return {"message": "Deconnecte avec succes"}
