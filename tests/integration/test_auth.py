"""
Tests d'integration — Endpoints d'authentification (/api/auth).
Teste inscription, connexion, et acces au profil utilisateur.
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient


@pytest.mark.asyncio
class TestRegister:
    """Tests de l'endpoint POST /api/auth/register."""

    async def test_register_succes(self, client: AsyncClient):
        """L'inscription avec un email valide doit reussir (201 ou 200)."""
        response = await client.post("/api/auth/register", json={
            "email": "nouveau@example.com",
            "password": "MonMotDePasse123!",
            "name": "Nouveau User",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "nouveau@example.com"
        assert data["name"] == "Nouveau User"
        assert "id" in data

    async def test_register_email_duplique(self, client: AsyncClient, test_user):
        """L'inscription avec un email deja utilise doit retourner 409."""
        response = await client.post("/api/auth/register", json={
            "email": "test@example.com",  # Meme email que test_user
            "password": "AutreMotDePasse",
            "name": "Doublon",
        })
        assert response.status_code == 409

    async def test_register_email_invalide(self, client: AsyncClient):
        """L'inscription avec un email mal formate doit retourner 422."""
        response = await client.post("/api/auth/register", json={
            "email": "pas-un-email",
            "password": "password123",
        })
        assert response.status_code == 422

    async def test_register_sans_password(self, client: AsyncClient):
        """L'inscription sans mot de passe doit retourner 422."""
        response = await client.post("/api/auth/register", json={
            "email": "test2@example.com",
        })
        assert response.status_code == 422


@pytest.mark.asyncio
class TestLogin:
    """Tests de l'endpoint POST /api/auth/login."""

    async def test_login_succes(self, client: AsyncClient, test_user):
        """La connexion avec les bons identifiants retourne un access_token."""
        response = await client.post("/api/auth/login", json={
            "email": "test@example.com",
            "password": "password123",
        })
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["user"]["email"] == "test@example.com"

    async def test_login_mauvais_password(self, client: AsyncClient, test_user):
        """La connexion avec un mauvais mot de passe retourne 401."""
        response = await client.post("/api/auth/login", json={
            "email": "test@example.com",
            "password": "mauvais_password",
        })
        assert response.status_code == 401

    async def test_login_email_inexistant(self, client: AsyncClient):
        """La connexion avec un email inconnu retourne 401."""
        response = await client.post("/api/auth/login", json={
            "email": "inexistant@example.com",
            "password": "password123",
        })
        assert response.status_code == 401


@pytest.mark.asyncio
class TestMe:
    """Tests de l'endpoint GET /api/auth/me."""

    async def test_me_avec_token_valide(self, client: AsyncClient, test_user, auth_headers):
        """GET /me avec un token valide retourne les infos de l'utilisateur."""
        response = await client.get("/api/auth/me", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "test@example.com"
        assert data["name"] == "Test User"
        assert "id" in data

    async def test_me_sans_token(self, client: AsyncClient):
        """GET /me sans token retourne 401."""
        response = await client.get("/api/auth/me")
        assert response.status_code == 401

    async def test_me_token_invalide(self, client: AsyncClient):
        """GET /me avec un token invalide retourne 401."""
        response = await client.get("/api/auth/me", headers={
            "Authorization": "Bearer token.completement.faux"
        })
        assert response.status_code == 401
