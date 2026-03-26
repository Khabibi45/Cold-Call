"""
API OAuth2 — Connexion via Google et GitHub.
Cree ou retrouve l'utilisateur, genere JWT, redirige vers le frontend.
"""

import logging
from datetime import datetime, timezone

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import create_access_token, create_refresh_token
from app.models.user import User

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter()
oauth = OAuth()

# --- Enregistrement des providers OAuth2 (silencieux si pas configure) ---

_google_enabled = bool(settings.google_client_id and settings.google_client_secret)
_github_enabled = bool(settings.github_client_id and settings.github_client_secret)

if _google_enabled:
    oauth.register(
        name="google",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
    logger.info("OAuth2 Google configure")
else:
    logger.warning("OAuth2 Google non configure (client_id/secret manquants)")

if _github_enabled:
    oauth.register(
        name="github",
        client_id=settings.github_client_id,
        client_secret=settings.github_client_secret,
        access_token_url="https://github.com/login/oauth/access_token",
        authorize_url="https://github.com/login/oauth/authorize",
        api_base_url="https://api.github.com/",
        client_kwargs={"scope": "user:email"},
    )
    logger.info("OAuth2 GitHub configure")
else:
    logger.warning("OAuth2 GitHub non configure (client_id/secret manquants)")


# ============================================
# Helpers
# ============================================

async def _find_or_create_user(
    db: AsyncSession,
    email: str,
    name: str | None,
    avatar_url: str | None,
    oauth_provider: str,
    oauth_id: str,
) -> User:
    """Cherche un utilisateur par email ou (oauth_provider, oauth_id). Cree si absent."""

    # 1. Chercher par oauth_provider + oauth_id
    result = await db.execute(
        select(User).where(
            and_(User.oauth_provider == oauth_provider, User.oauth_id == oauth_id)
        )
    )
    user = result.scalar_one_or_none()

    # 2. Chercher par email
    if not user:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        # Lier le compte OAuth si l'utilisateur existe deja par email
        if user and not user.oauth_provider:
            user.oauth_provider = oauth_provider
            user.oauth_id = oauth_id

    # 3. Creer l'utilisateur si introuvable
    if not user:
        user = User(
            email=email,
            name=name or email.split("@")[0],
            avatar_url=avatar_url,
            oauth_provider=oauth_provider,
            oauth_id=oauth_id,
            # Pas de password_hash car OAuth
        )
        db.add(user)
        await db.flush()
        logger.info("Nouvel utilisateur OAuth cree : %s (%s)", email, oauth_provider)

    # Mettre a jour last_login et avatar
    user.last_login = datetime.now(timezone.utc)
    if avatar_url and not user.avatar_url:
        user.avatar_url = avatar_url

    await db.commit()
    return user


def _build_redirect(user: User) -> RedirectResponse:
    """Genere les JWT et redirige vers le frontend avec le token."""
    token_data = {"sub": str(user.id), "email": user.email}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    # Rediriger vers le frontend avec le access_token en query param
    redirect_url = f"{settings.app_url}/?token={access_token}"
    response = RedirectResponse(url=redirect_url)

    # Refresh token en cookie httpOnly
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,  # 30 jours
    )

    return response


# ============================================
# Google OAuth2
# ============================================

@router.get("/google")
async def google_login(request: Request):
    """Redirige vers la page de connexion Google."""
    if not _google_enabled:
        return {"error": "OAuth2 Google non configure"}
    redirect_uri = settings.google_redirect_uri
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback")
async def google_callback(request: Request, db: AsyncSession = Depends(get_db)):
    """Callback Google OAuth2 — cree/retrouve l'utilisateur et redirige."""
    if not _google_enabled:
        return RedirectResponse(url=f"{settings.app_url}/?error=google_not_configured")

    try:
        token = await oauth.google.authorize_access_token(request)
        user_info = token.get("userinfo")
        if not user_info:
            # Fallback : recuperer via l'endpoint userinfo
            user_info = await oauth.google.userinfo(token=token)

        email = user_info.get("email")
        if not email:
            return RedirectResponse(url=f"{settings.app_url}/?error=no_email")

        name = user_info.get("name")
        avatar_url = user_info.get("picture")
        oauth_id = user_info.get("sub")  # Google unique ID

        user = await _find_or_create_user(db, email, name, avatar_url, "google", oauth_id)
        return _build_redirect(user)

    except Exception as e:
        logger.error("Erreur callback Google OAuth : %s", e)
        return RedirectResponse(url=f"{settings.app_url}/?error=oauth_failed")


# ============================================
# GitHub OAuth2
# ============================================

@router.get("/github")
async def github_login(request: Request):
    """Redirige vers la page de connexion GitHub."""
    if not _github_enabled:
        return {"error": "OAuth2 GitHub non configure"}
    redirect_uri = settings.github_redirect_uri
    return await oauth.github.authorize_redirect(request, redirect_uri)


@router.get("/github/callback")
async def github_callback(request: Request, db: AsyncSession = Depends(get_db)):
    """Callback GitHub OAuth2 — cree/retrouve l'utilisateur et redirige."""
    if not _github_enabled:
        return RedirectResponse(url=f"{settings.app_url}/?error=github_not_configured")

    try:
        token = await oauth.github.authorize_access_token(request)

        # Recuperer le profil GitHub
        resp = await oauth.github.get("user", token=token)
        profile = resp.json()

        # GitHub ne retourne pas toujours l'email dans /user
        email = profile.get("email")
        if not email:
            # Recuperer les emails via l'API dediee
            email_resp = await oauth.github.get("user/emails", token=token)
            emails = email_resp.json()
            # Prendre l'email principal verifie
            for e in emails:
                if e.get("primary") and e.get("verified"):
                    email = e["email"]
                    break
            # Fallback : prendre le premier email verifie
            if not email:
                for e in emails:
                    if e.get("verified"):
                        email = e["email"]
                        break

        if not email:
            return RedirectResponse(url=f"{settings.app_url}/?error=no_email")

        name = profile.get("name") or profile.get("login")
        avatar_url = profile.get("avatar_url")
        oauth_id = str(profile.get("id"))  # GitHub unique ID

        user = await _find_or_create_user(db, email, name, avatar_url, "github", oauth_id)
        return _build_redirect(user)

    except Exception as e:
        logger.error("Erreur callback GitHub OAuth : %s", e)
        return RedirectResponse(url=f"{settings.app_url}/?error=oauth_failed")
