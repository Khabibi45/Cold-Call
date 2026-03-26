"""
Securite : hashing Argon2, generation/verification JWT, utils auth.
Argon2 choisi car : pas de bug passlib+bcrypt>=4.1, recommandation OWASP 2025.
"""

from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from jose import JWTError, jwt

from app.core.config import get_settings

settings = get_settings()
ph = PasswordHasher()


# --- Hashing mots de passe ---

def hash_password(password: str) -> str:
    """Hash un mot de passe avec Argon2id."""
    return ph.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    """Verifie un mot de passe contre son hash Argon2."""
    try:
        return ph.verify(hashed, password)
    except VerifyMismatchError:
        return False


# --- JWT ---

def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Cree un JWT access token (courte duree)."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.jwt_access_token_expire_minutes))
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(data: dict) -> str:
    """Cree un JWT refresh token (longue duree)."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_token_expire_days)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict | None:
    """Decode et valide un JWT. Retourne None si invalide/expire."""
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        return payload
    except JWTError:
        return None
