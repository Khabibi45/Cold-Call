"""
Point d'entree FastAPI — Cold Call Platform.
Configure CORS, rate limiting, routes, et health check.
"""

from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.core.config import get_settings
from app.core.database import engine, Base
from app.api.health import router as health_router
from app.api.leads import router as leads_router
from app.api.calls import router as calls_router
from app.api.stats import router as stats_router
from app.api.auth import router as auth_router
from app.core.rate_limiter import limiter

settings = get_settings()


# --- Sentry (monitoring erreurs) ---
if settings.sentry_dsn:
    sentry_sdk.init(dsn=settings.sentry_dsn, traces_sample_rate=0.1)


# --- Lifespan : creation des tables au demarrage ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


# --- App FastAPI ---
app = FastAPI(
    title="Cold Call Platform",
    description="Plateforme SaaS de cold calling avec scraper Google Maps et power dialer",
    version="1.0.0",
    lifespan=lifespan,
)

# --- Rate limiter ---
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["*"],
)

# --- Routes ---
app.include_router(health_router, prefix="/api", tags=["Sante"])
app.include_router(auth_router, prefix="/api/auth", tags=["Authentification"])
app.include_router(leads_router, prefix="/api/leads", tags=["Leads"])
app.include_router(calls_router, prefix="/api/calls", tags=["Appels"])
app.include_router(stats_router, prefix="/api/stats", tags=["Statistiques"])
