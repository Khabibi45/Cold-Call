"""
API Scraper — Lancer, surveiller et arreter un scrape Google Maps.
Historique des jobs, suggestions de queries, memoire persistante.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.scraper import ScraperService, _api_cap, APICapExceeded

router = APIRouter()

# Instance unique du scraper (partage entre les endpoints)
_scraper = ScraperService()


@router.get("/cap")
async def api_cap_status():
    """Retourne le statut du cap mensuel API (10 000 requetes/mois max).
    Si blocked=true, le scraper est ARRETE et aucun frais ne sera facture."""
    return await _api_cap.stats()


class ScrapeRequest(BaseModel):
    """Parametres pour lancer un scrape."""
    query: str = Field(..., description="Categorie a scraper (ex: 'restaurant', 'coiffeur')")
    city: str = Field(..., description="Ville cible (ex: 'Toulouse', 'Paris')")
    limit: int = Field(default=100, ge=1, le=1000, description="Nombre max de resultats")


@router.post("/start")
async def start_scrape(req: ScrapeRequest):
    """Lance un scrape Outscraper/Foursquare en tache de fond.
    Utilise la memoire ScrapeJob : si la meme query+city a deja ete faite,
    reprend avec un offset plus grand pour ne pas gaspiller de credits API.
    """
    if _scraper.status["running"]:
        raise HTTPException(status_code=409, detail="Un scrape est deja en cours")

    # --- CAP MENSUEL : bloquer si le cap est atteint ---
    cap_stats = await _api_cap.stats()
    if cap_stats["blocked"]:
        raise HTTPException(
            status_code=429,
            detail=f"CAP MENSUEL ATTEINT : {cap_stats['used']}/{cap_stats['cap']} requetes utilisees. "
                   f"Le scraper est bloque jusqu'au mois prochain. Aucun frais ne sera facture.",
        )

    # Verifier qu'au moins une API est configuree avant de lancer
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


@router.get("/history")
async def scrape_history(limit: int = Query(50, ge=1, le=200)):
    """Retourne l'historique de tous les ScrapeJobs avec leurs stats.
    Permet de voir les queries deja faites et leur progression.
    """
    jobs = await _scraper.get_job_history(limit=limit)
    return {"total": len(jobs), "data": jobs}


@router.get("/suggestions")
async def scrape_suggestions(city: str = Query("Toulouse", description="Ville pour les suggestions")):
    """Retourne les prochaines queries a lancer.
    Basees sur les jobs deja faits : propose des sous-categories
    et des categories principales non encore scrapees.
    """
    suggestions = await _scraper.get_suggestions(city=city)
    return {"total": len(suggestions), "data": suggestions}
