"""
Endpoints Google Maps Scraper — Playwright stealth, zero API.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.maps_scraper import get_maps_scraper
from app.models.scrape_job import SUGGESTED_SUBCATEGORIES

router = APIRouter()


class MapsScrapeRequest(BaseModel):
    query: str = Field(..., description="Categorie (ex: restaurant)")
    city: str = Field(default="Toulouse", description="Ville")
    num_workers: int = Field(default=3, ge=1, le=5, description="Nombre d'agents paralleles (1-5)")


@router.post("/start")
async def start_maps_scrape(req: MapsScrapeRequest):
    scraper = get_maps_scraper()
    if scraper.status['running']:
        raise HTTPException(409, "Scrape deja en cours")
    # Construire la liste de queries : principale + sous-categories
    queries = [req.query] + SUGGESTED_SUBCATEGORIES.get(req.query, [])
    scraper.start_background(queries, req.city, num_workers=req.num_workers)
    return {
        "message": f"Scrape Maps lance : {len(queries)} categories pour {req.city} ({req.num_workers} agents)",
        "queries": queries,
        "num_workers": req.num_workers,
    }


@router.get("/status")
async def maps_scrape_status(logs_count: int = Query(20, ge=1, le=500, description="Nombre de logs a retourner")):
    """Retourne le statut du scraper avec les N derniers logs."""
    scraper = get_maps_scraper()
    status = scraper.status
    # Remplacer les logs par defaut par le nombre demande
    status["logs"] = list(scraper._logs)[-logs_count:]
    return status


@router.get("/logs")
async def maps_scrape_logs(count: int = Query(500, ge=1, le=500)):
    """Retourne les N derniers logs du scraper Maps."""
    scraper = get_maps_scraper()
    logs = list(scraper._logs)[-count:]
    return {"total": len(scraper._logs), "data": logs}


@router.post("/stop")
async def stop_maps_scrape():
    """Arret propre du scrape (attend la fin de l'action en cours)."""
    scraper = get_maps_scraper()
    if not scraper.status['running']:
        # Meme si pas "running", force le reset de l'etat au cas ou c'est bloque
        scraper._running = False
        scraper._step = "Arrete"
        return {"message": "Etat reinitialise"}
    scraper.stop()
    return {"message": "Arret demande"}


@router.post("/force-stop")
async def force_stop_maps_scrape():
    """Arret FORCE : tue le task, ferme le navigateur, reset tout."""
    scraper = get_maps_scraper()
    await scraper.force_stop()
    return {"message": "Scrape force-stoppe"}
