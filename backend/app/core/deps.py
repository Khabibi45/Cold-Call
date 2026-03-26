"""
Dependencies FastAPI — Injection de l'utilisateur courant via JWT.
Centralise toute la logique d'authentification pour eviter la duplication.
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_token
from app.models.user import User

# Le tokenUrl correspond a l'endpoint de login pour la doc Swagger
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Decode le JWT access token, verifie son type et son expiration,
    puis charge l'utilisateur depuis la base de donnees.
    Leve une HTTPException 401 si le token est invalide ou l'utilisateur introuvable.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token invalide ou expire",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Decoder le token
    payload = decode_token(token)
    if payload is None:
        raise credentials_exception

    # Verifier que c'est bien un access token (pas un refresh)
    if payload.get("type") != "access":
        raise credentials_exception

    # Extraire l'ID utilisateur du claim "sub"
    user_id_str: str | None = payload.get("sub")
    if user_id_str is None:
        raise credentials_exception

    try:
        user_id = int(user_id_str)
    except (ValueError, TypeError):
        raise credentials_exception

    # Charger l'utilisateur depuis la DB
    user = await db.get(User, user_id)
    if user is None:
        raise credentials_exception

    # Verifier que le compte est actif
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Compte desactive",
        )

    return user


async def get_current_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Verifie que l'utilisateur courant est administrateur.
    Utile pour proteger les endpoints d'administration.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acces reserve aux administrateurs",
        )
    return current_user
