"""
Configuration Alembic pour migrations async avec SQLAlchemy 2.0.
Charge la DATABASE_URL depuis la config Pydantic de l'application.
"""

import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Ajouter le dossier backend/ au sys.path pour importer l'app
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.core.database import Base

# Importer tous les modeles pour que Base.metadata les connaisse
from app.models.user import User  # noqa: F401
from app.models.lead import Lead  # noqa: F401
from app.models.call import Call  # noqa: F401

# Configuration Alembic
config = context.config

# Configurer le logging depuis alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata cible pour la generation automatique de migrations
target_metadata = Base.metadata

# Injecter la DATABASE_URL depuis les settings de l'application
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)


def run_migrations_offline() -> None:
    """
    Execute les migrations en mode 'offline'.
    Genere le SQL sans connexion a la base de donnees.
    Utile pour generer des scripts de migration a executer manuellement.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Execute les migrations avec une connexion synchrone."""
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """
    Execute les migrations en mode 'online' avec un engine async.
    Cree un engine asyncpg, puis execute les migrations dans un contexte sync.
    """
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Point d'entree pour le mode online — lance l'event loop async."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
