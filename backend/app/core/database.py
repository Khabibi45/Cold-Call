"""
Connexion PostgreSQL async avec SQLAlchemy 2.0.
Pool configure pour eviter l'exhaustion (pool_size=20, max_overflow=10).
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=settings.app_debug,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=3600,
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    """Classe de base pour tous les modeles SQLAlchemy."""
    pass


async def get_db() -> AsyncSession:
    """Dependency FastAPI — fournit une session DB avec cleanup automatique."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
