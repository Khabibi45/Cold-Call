"""
Fixtures partagees pour tous les tests — DB SQLite async de test, client HTTP, user de test.
Chaque test utilise une base de donnees isolee (pas de donnees partagees).
"""

import os
import asyncio
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Forcer les variables d'env AVANT l'import de l'app
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test.db"
os.environ["APP_ENV"] = "test"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-tests-only"
os.environ["SENTRY_DSN"] = ""

from app.core.database import Base, get_db
from app.core.security import hash_password, create_access_token
from app.models.user import User
from app.models.lead import Lead
from app.models.call import Call
from app.main import app


# --- Engine SQLite async pour les tests ---
TEST_DATABASE_URL = "sqlite+aiosqlite:///./test.db"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
)

TestSessionLocal = async_sessionmaker(
    test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# --- Boucle d'evenements unique pour pytest-asyncio ---
@pytest.fixture(scope="session")
def event_loop():
    """Cree une boucle asyncio unique pour toute la session de tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# --- Creation/suppression des tables pour chaque test ---
@pytest_asyncio.fixture(autouse=True)
async def setup_database():
    """Cree les tables avant chaque test et les supprime apres (isolation totale)."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


# --- Session DB de test ---
@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Fournit une session DB de test avec rollback automatique."""
    async with TestSessionLocal() as session:
        yield session


# --- Override de la dependency get_db pour pointer sur la DB de test ---
@pytest_asyncio.fixture(autouse=True)
async def override_get_db():
    """Remplace la dependency get_db par la session de test."""
    async def _get_test_db():
        async with TestSessionLocal() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _get_test_db
    yield
    app.dependency_overrides.clear()


# --- Client HTTP async pointe sur l'app FastAPI ---
@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Client httpx AsyncClient pour tester les endpoints sans serveur."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# --- User de test ---
@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> User:
    """Cree un utilisateur de test avec mot de passe 'password123'."""
    user = User(
        email="test@example.com",
        name="Test User",
        password_hash=hash_password("password123"),
        is_active=True,
        is_admin=False,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


# --- Token d'acces pour le user de test ---
@pytest_asyncio.fixture
async def auth_headers(test_user: User) -> dict[str, str]:
    """Retourne les headers Authorization avec un JWT valide pour le user de test."""
    token = create_access_token({"sub": str(test_user.id), "email": test_user.email})
    return {"Authorization": f"Bearer {token}"}


# --- Lead de test ---
@pytest_asyncio.fixture
async def test_lead(db_session: AsyncSession) -> Lead:
    """Cree un lead de test."""
    lead = Lead(
        business_name="Boulangerie Test",
        phone="05 61 00 00 01",
        phone_e164="+33561000001",
        city="Toulouse",
        category="Boulangerie",
        has_website=False,
        lead_score=75,
        source="google_maps",
    )
    db_session.add(lead)
    await db_session.commit()
    await db_session.refresh(lead)
    return lead
