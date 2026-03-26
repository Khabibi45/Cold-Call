"""
Point d'entree FastAPI — Cold Call Platform.
Configure CORS, rate limiting, routes, logging structure et monitoring Sentry.
"""

from contextlib import asynccontextmanager

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.core.config import get_settings
from app.core.database import engine, Base
from app.core.logging import setup_logging, get_logger, RequestLoggingMiddleware
from app.api.health import router as health_router
from app.api.leads import router as leads_router
from app.api.calls import router as calls_router
from app.api.stats import router as stats_router
from app.api.auth import router as auth_router
from app.api.scraper import router as scraper_router
from app.api.import_leads import router as import_router
from app.api.dialer import router as dialer_router
from app.api.export import router as export_router
from app.api.twilio_endpoints import router as twilio_router
from app.api.oauth import router as oauth_router
from app.api.websocket import router as ws_router
from app.core.rate_limiter import limiter
from app.services.dedup import DeduplicationService
from app.models.scrape_job import ScrapeJob  # noqa: F401 — force la creation de la table au demarrage

settings = get_settings()

# --- Logging structure ---
setup_logging(json_output=settings.app_env != "development")
logger = get_logger("main")


# --- Sentry (monitoring erreurs) ---
if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        traces_sample_rate=0.1,
        environment=settings.app_env,
        integrations=[
            FastApiIntegration(transaction_style="endpoint"),
            StarletteIntegration(transaction_style="endpoint"),
        ],
        send_default_pii=False,
    )


# --- Lifespan : creation des tables au demarrage ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("demarrage_application", env=settings.app_env)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Charger le Bloom Filter et le Set place_ids depuis la DB
    dedup = DeduplicationService.get_instance()
    await dedup.load_from_db()
    logger.info("dedup_service_charge", **dedup.stats)
    yield
    logger.info("arret_application")
    await engine.dispose()


# --- App FastAPI ---
app = FastAPI(
    title="Cold Call Platform",
    description="Plateforme SaaS de cold calling avec scraper Google Maps et power dialer",
    version="1.0.0",
    lifespan=lifespan,
)

# --- Middleware logging structure (avant CORS pour capturer toutes les requetes) ---
app.add_middleware(RequestLoggingMiddleware)

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

# --- Session middleware (requis par authlib pour OAuth2 state) ---
app.add_middleware(SessionMiddleware, secret_key=settings.jwt_secret_key)


# --- Sentry : contexte utilisateur quand disponible ---
@app.middleware("http")
async def sentry_user_context(request: Request, call_next):
    """Ajoute le contexte utilisateur a Sentry si un token JWT est present."""
    if settings.sentry_dsn:
        # Tenter d'extraire l'info user du header Authorization
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            try:
                from app.core.security import decode_token
                token = auth_header.split(" ", 1)[1]
                payload = decode_token(token)
                if payload:
                    sentry_sdk.set_user({
                        "id": payload.get("sub"),
                        "email": payload.get("email"),
                    })
            except Exception:
                pass  # Ne pas bloquer la requete si le parsing echoue
    response = await call_next(request)
    return response


# --- Routes ---
app.include_router(health_router, prefix="/api", tags=["Sante"])
app.include_router(auth_router, prefix="/api/auth", tags=["Authentification"])
app.include_router(leads_router, prefix="/api/leads", tags=["Leads"])
app.include_router(calls_router, prefix="/api/calls", tags=["Appels"])
app.include_router(stats_router, prefix="/api/stats", tags=["Statistiques"])
app.include_router(scraper_router, prefix="/api/scraper", tags=["Scraper"])
app.include_router(import_router, prefix="/api/leads", tags=["Import"])
app.include_router(dialer_router, prefix="/api/dialer", tags=["Power Dialer"])
app.include_router(twilio_router, prefix="/api/twilio", tags=["Twilio"])
app.include_router(export_router, prefix="/api/export", tags=["Export"])
app.include_router(oauth_router, prefix="/api/auth", tags=["OAuth2"])
app.include_router(ws_router, prefix="/api", tags=["WebSocket"])

from app.api.test_runner import router as tests_router
app.include_router(tests_router, prefix="/api/tests", tags=["Tests"])
