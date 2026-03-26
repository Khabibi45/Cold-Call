"""
Service scraper — Outscraper API pour Google Maps.
Scrape, normalise, deduplique et insere les leads.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import async_session
from app.models.lead import Lead
from app.services.dedup import DeduplicationService

logger = logging.getLogger(__name__)
settings = get_settings()

# --- Categories Tier pour le scoring ---
TIER_1 = {
    "restaurant", "coiffeur", "coiffure", "salon de beaute", "beaute",
    "photographe", "coach sportif", "veterinaire", "dentiste",
    "restaurant gastronomique", "hair salon", "beauty salon",
    "photographer", "gym", "veterinary", "dentist",
}
TIER_2 = {
    "artisan", "gite", "auto-ecole", "fleuriste", "garage",
    "plombier", "electricien", "menuisier", "peintre",
    "driving school", "florist", "mechanic", "plumber", "electrician",
}
TIER_3 = {
    "boulangerie", "epicerie", "tabac", "bakery", "grocery",
}


class ScraperService:
    """Scrape Google Maps via Outscraper, dedup + insert."""

    def __init__(self) -> None:
        self._running = False
        self._should_stop = False
        self._task: asyncio.Task | None = None
        self._stats: dict[str, int] = {
            "total": 0,
            "inserted": 0,
            "duplicates": 0,
            "errors": 0,
            "no_phone": 0,
        }
        self._current_query: str = ""
        self._current_city: str = ""

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------
    @staticmethod
    def calculate_score(lead_data: dict) -> int:
        """Calcule le lead_score selon les criteres du BRAINSTORM.md (0-100)."""
        score = 0

        # --- Nombre avis Google (25%) ---
        reviews = lead_data.get("review_count") or 0
        if reviews >= 50:
            score += 25
        elif reviews >= 20:
            score += 20
        elif reviews >= 5:
            score += 12
        else:
            score += 5

        # --- Note Google (10%) ---
        rating = lead_data.get("rating") or 0
        if rating >= 4.7:
            score += 10
        elif rating >= 4.2:
            score += 8
        elif rating >= 3.5:
            score += 5
        else:
            score += 2

        # --- Nombre photos (15%) ---
        photos = lead_data.get("photo_count") or 0
        if photos >= 15:
            score += 15
        elif photos >= 5:
            score += 10
        elif photos >= 1:
            score += 6
        else:
            score += 1

        # --- Categorie business (20%) ---
        category = (lead_data.get("category") or "").lower().strip()
        if any(t in category for t in TIER_1):
            score += 20
        elif any(t in category for t in TIER_2):
            score += 14
        elif any(t in category for t in TIER_3):
            score += 8
        else:
            score += 10  # categorie inconnue = milieu

        # --- Pas de site web = bonus (obligatoire mais on donne des points) ---
        has_website = lead_data.get("has_website", False)
        if not has_website:
            score += 15
        else:
            score += 0

        # --- Reseaux sociaux (10%) ---
        # Outscraper ne fournit pas toujours cette info, score par defaut
        score += 5

        return min(score, 100)

    # ------------------------------------------------------------------
    # Outscraper API
    # ------------------------------------------------------------------
    async def scrape_outscraper(self, query: str, city: str, limit: int = 100) -> list[dict]:
        """Appelle l'API Outscraper Google Maps Search."""
        if not settings.outscraper_api_key:
            raise ValueError("OUTSCRAPER_API_KEY non configuree")

        search_query = f"{query} {city}"
        url = "https://api.app.outscraper.com/maps/search-v3"
        params = {
            "query": search_query,
            "limit": limit,
            "language": "fr",
            "region": "FR",
            "async": "false",
        }
        headers = {"X-API-KEY": settings.outscraper_api_key}

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()

        # Outscraper retourne une liste de listes de resultats
        results = []
        if isinstance(data, dict) and "data" in data:
            for group in data["data"]:
                if isinstance(group, list):
                    results.extend(group)
                elif isinstance(group, dict):
                    results.append(group)
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, list):
                    results.extend(item)
                elif isinstance(item, dict):
                    results.append(item)

        return results

    # ------------------------------------------------------------------
    # Traitement d'un resultat Outscraper
    # ------------------------------------------------------------------
    def _parse_outscraper_result(self, item: dict) -> dict[str, Any] | None:
        """Transforme un resultat Outscraper en dict compatible Lead."""
        dedup = DeduplicationService.get_instance()

        business_name = item.get("name") or item.get("query")
        if not business_name:
            return None

        raw_phone = item.get("phone") or item.get("phone_number") or ""
        phone_e164 = dedup.normalize_phone(str(raw_phone)) if raw_phone else None

        if not phone_e164:
            self._stats["no_phone"] += 1
            return None

        place_id = item.get("place_id") or item.get("google_id")
        website = item.get("site") or item.get("website") or ""
        has_website = bool(website and website.strip())

        lead_data = {
            "place_id": place_id,
            "source": "outscraper",
            "business_name": business_name,
            "phone": str(raw_phone),
            "phone_e164": phone_e164,
            "email": item.get("email"),
            "website": website if has_website else None,
            "has_website": has_website,
            "address": item.get("full_address") or item.get("address"),
            "city": item.get("city") or item.get("address_parsed", {}).get("city"),
            "postal_code": item.get("postal_code") or item.get("address_parsed", {}).get("postal_code"),
            "country": item.get("country_code", "FR"),
            "latitude": item.get("latitude"),
            "longitude": item.get("longitude"),
            "category": item.get("category") or item.get("type"),
            "rating": item.get("rating"),
            "review_count": item.get("reviews") or item.get("review_count") or 0,
            "photo_count": item.get("photos_count") or item.get("photo_count") or 0,
            "maps_url": item.get("google_maps_url") or item.get("link"),
            "raw_data": item,
        }

        lead_data["lead_score"] = self.calculate_score(lead_data)
        return lead_data

    # ------------------------------------------------------------------
    # Pipeline complet : scrape → dedup → insert
    # ------------------------------------------------------------------
    async def run_scrape(self, query: str, city: str, limit: int = 100) -> dict:
        """Lance un scrape complet : API → parse → dedup → insert."""
        self._running = True
        self._should_stop = False
        self._current_query = query
        self._current_city = city
        self._stats = {"total": 0, "inserted": 0, "duplicates": 0, "errors": 0, "no_phone": 0}

        dedup = DeduplicationService.get_instance()

        try:
            # 1. Appel API Outscraper
            logger.info("Scrape Outscraper : query=%s city=%s limit=%d", query, city, limit)
            raw_results = await self.scrape_outscraper(query, city, limit)
            self._stats["total"] = len(raw_results)
            logger.info("Outscraper retourne %d resultats", len(raw_results))

            # 2. Parse + dedup + insert
            async with async_session() as session:
                for item in raw_results:
                    if self._should_stop:
                        logger.info("Scrape arrete par l'utilisateur")
                        break

                    try:
                        lead_data = self._parse_outscraper_result(item)
                        if lead_data is None:
                            continue

                        # Check dedup RAM
                        if dedup.is_duplicate(
                            phone_e164=lead_data["phone_e164"],
                            place_id=lead_data.get("place_id"),
                        ):
                            self._stats["duplicates"] += 1
                            continue

                        # INSERT ON CONFLICT DO NOTHING
                        stmt = text("""
                            INSERT INTO leads (
                                place_id, source, business_name, phone, phone_e164,
                                email, website, has_website, address, city, postal_code,
                                country, latitude, longitude, category, rating,
                                review_count, photo_count, maps_url, lead_score,
                                raw_data, scraped_at, updated_at
                            ) VALUES (
                                :place_id, :source, :business_name, :phone, :phone_e164,
                                :email, :website, :has_website, :address, :city, :postal_code,
                                :country, :latitude, :longitude, :category, :rating,
                                :review_count, :photo_count, :maps_url, :lead_score,
                                :raw_data::jsonb, NOW(), NOW()
                            )
                            ON CONFLICT (phone_e164) DO NOTHING
                        """)
                        result = await session.execute(stmt, lead_data)

                        if result.rowcount > 0:
                            dedup.register(lead_data["phone_e164"], lead_data.get("place_id"))
                            self._stats["inserted"] += 1
                        else:
                            self._stats["duplicates"] += 1

                    except Exception as e:
                        logger.warning("Erreur traitement lead : %s", e)
                        self._stats["errors"] += 1

                await session.commit()

        except Exception as e:
            logger.error("Erreur scrape Outscraper : %s", e)
            raise
        finally:
            self._running = False

        logger.info("Scrape termine : %s", self._stats)
        return self._stats

    # ------------------------------------------------------------------
    # Controle du scrape async
    # ------------------------------------------------------------------
    def start_background(self, query: str, city: str, limit: int = 100) -> None:
        """Lance le scrape en tache de fond."""
        if self._running:
            raise RuntimeError("Un scrape est deja en cours")
        self._task = asyncio.create_task(self.run_scrape(query, city, limit))

    def stop(self) -> None:
        """Demande l'arret du scrape en cours."""
        self._should_stop = True

    @property
    def status(self) -> dict:
        return {
            "running": self._running,
            "query": self._current_query,
            "city": self._current_city,
            "stats": self._stats.copy(),
        }
