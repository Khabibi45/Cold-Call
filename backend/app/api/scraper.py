"""
API Scraper — Lancer, surveiller et arreter un scrape Google Maps.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.scraper import ScraperService

router = APIRouter()

# Instance unique du scraper (partage entre les endpoints)
_scraper = ScraperService()


class ScrapeRequest(BaseModel):
    """Parametres pour lancer un scrape."""
    query: str = Field(..., description="Categorie a scraper (ex: 'restaurant', 'coiffeur')")
    city: str = Field(..., description="Ville cible (ex: 'Toulouse', 'Paris')")
    limit: int = Field(default=100, ge=1, le=1000, description="Nombre max de resultats")


@router.post("/start")
async def start_scrape(req: ScrapeRequest):
    """Lance un scrape Outscraper/Foursquare en tache de fond."""
    if _scraper.status["running"]:
        raise HTTPException(status_code=409, detail="Un scrape est deja en cours")

    # Fix #11 : Verifier qu'au moins une API est configuree avant de lancer
    if not _scraper.is_any_api_configured:
        raise HTTPException(
            status_code=400,
            detail="Aucune cle API configuree (OUTSCRAPER_API_KEY et/ou FOURSQUARE_API_KEY requise)",
        )

    try:
        _scraper.start_background(query=req.query, city=req.city, limit=req.limit)
    except (RuntimeError, ValueError) as e:
        raise HTTPException(status_code=409, detail=str(e))

    return {
        "message": f"Scrape lance : {req.query} a {req.city} (limit={req.limit})",
        "status": _scraper.status,
    }


@router.get("/status")
async def scrape_status():
    """Retourne le statut du scrape en cours ou du dernier scrape."""
    return _scraper.status


@router.post("/stop")
async def stop_scrape():
    """Arrete le scrape en cours."""
    if not _scraper.status["running"]:
        raise HTTPException(status_code=400, detail="Aucun scrape en cours")

    _scraper.stop()
    return {"message": "Arret demande", "status": _scraper.status}
