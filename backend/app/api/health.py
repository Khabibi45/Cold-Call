"""
Health check — utilise par Docker HEALTHCHECK et le monitoring.
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check():
    """Endpoint de sante. Retourne 200 si le service tourne."""
    return {"status": "ok", "service": "cold-call-api"}
