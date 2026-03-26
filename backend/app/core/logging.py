"""
Configuration structlog — Logs structures JSON pour la plateforme Cold Call.
Middleware FastAPI integre pour tracer chaque requete HTTP.
"""

import time
from typing import Callable

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


def setup_logging(json_output: bool = True) -> None:
    """
    Configure structlog avec :
    - Timestamps ISO 8601
    - Niveau de log
    - Info appelant (module, fonction, ligne)
    - Sortie JSON (production) ou console (dev)
    """
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.CallsiteParameterAdder(
            parameters=[
                structlog.processors.CallsiteParameter.MODULE,
                structlog.processors.CallsiteParameter.FUNC_NAME,
                structlog.processors.CallsiteParameter.LINENO,
            ]
        ),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if json_output:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Retourne un logger structure configure."""
    return structlog.get_logger(name)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware FastAPI qui log chaque requete HTTP avec :
    - Methode HTTP
    - Path
    - Code de statut
    - Duree en millisecondes
    """

    def __init__(self, app, logger: structlog.stdlib.BoundLogger | None = None):
        super().__init__(app)
        self.logger = logger or get_logger("http")

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.perf_counter()

        # Extraire les infos de la requete
        method = request.method
        path = request.url.path
        client_ip = request.client.host if request.client else "unknown"

        try:
            response = await call_next(request)
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

            self.logger.info(
                "requete_http",
                method=method,
                path=path,
                status=response.status_code,
                duration_ms=duration_ms,
                client_ip=client_ip,
            )

            return response

        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

            self.logger.error(
                "requete_http_erreur",
                method=method,
                path=path,
                duration_ms=duration_ms,
                client_ip=client_ip,
                error=str(exc),
            )
            raise
