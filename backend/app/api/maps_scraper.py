"""
Endpoints Google Maps Scraper — Playwright stealth, zero API.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.maps_scraper import get_maps_scraper
from app.models.scrape_job import SUGGESTED_SUBCATEGORIES

router = APIRouter()


class MapsScrapeRequest(BaseModel):
    query: str = Field(..., description="Categorie (ex: restaurant)")
    city: str = Field(default="Toulouse", description="Ville")


@router.post("/start")
async def start_maps_scrape(req: MapsScrapeRequest):
    scraper = get_maps_scraper()
    if scraper.status['running']:
        raise HTTPException(409, "Scrape deja en cours")
    # Construire la liste de queries : principale + sous-categories
    queries = [req.query] + SUGGESTED_SUBCATEGORIES.get(req.query, [])
    scraper.start_background(queries, req.city)
    return {
        "message": f"Scrape Maps lance : {len(queries)} categories pour {req.city}",
        "queries": queries,
    }


@router.get("/status")
async def maps_scrape_status():
    return get_maps_scraper().status


@router.post("/stop")
async def stop_maps_scrape():
    scraper = get_maps_scraper()
    if not scraper.status['running']:
        raise HTTPException(400, "Aucun scrape en cours")
    scraper.stop()
    return {"message": "Arret demande"}
