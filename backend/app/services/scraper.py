"""
Service scraper — Outscraper + Foursquare API pour Google Maps.
Scrape, normalise, deduplique et insere les leads.
Production-ready : connection pooling, retry, rate limiting, checkpoint/resume.
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from aiolimiter import AsyncLimiter
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
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

# --- Fix #3 : Rate limiting Outscraper (5 requetes / 60 secondes) ---
_outscraper_limiter = AsyncLimiter(max_rate=5, time_period=60)
# Rate limiter Foursquare (plus genereux, 50 req/min)
_foursquare_limiter = AsyncLimiter(max_rate=50, time_period=60)


def _is_retryable_httpx_error(exc: BaseException) -> bool:
    """Retourne True si l'erreur est retryable (reseau ou 5xx). Pas les 4xx."""
    if isinstance(exc, (httpx.ConnectError, httpx.TimeoutException, httpx.PoolTimeout)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return False


class ScraperService:
    """Scrape Google Maps via Outscraper + Foursquare, dedup + insert."""

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

        # Fix #1 : Connection pooling httpx — un seul client reutilise
        self._http_client: httpx.AsyncClient = httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=10.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )

        # Fix #4 : Batch WebSocket — accumuler les leads avant broadcast
        self._lead_buffer: list[dict] = []
        self._last_lead_broadcast: float = 0.0
        self._last_stats_broadcast: float = 0.0

        # Fix #11 : Validation cles API au demarrage
        if not settings.outscraper_api_key and not settings.foursquare_api_key:
            logger.warning("Aucune cle API scraper configuree (outscraper / foursquare)")

    # --- Fix #1 : Fermeture propre du client HTTP ---
    async def close(self) -> None:
        """Ferme proprement le client HTTP."""
        await self._http_client.aclose()
        logger.info("Client HTTP ferme proprement")

    # --- Fix #11 : Properties de verification des cles API ---
    @property
    def is_outscraper_configured(self) -> bool:
        """Verifie que la cle Outscraper est configuree."""
        return bool(settings.outscraper_api_key and settings.outscraper_api_key.strip())

    @property
    def is_foursquare_configured(self) -> bool:
        """Verifie que la cle Foursquare est configuree."""
        return bool(settings.foursquare_api_key and settings.foursquare_api_key.strip())

    @property
    def is_any_api_configured(self) -> bool:
        """Verifie qu'au moins une API est configuree."""
        return self.is_outscraper_configured or self.is_foursquare_configured

    # ------------------------------------------------------------------
    # Scoring — Fix #7 : criteres complets
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

        # --- Fix #7 : "Repond aux avis" (10%) ---
        raw_data = lead_data.get("raw_data") or {}
        owner_answers = raw_data.get("owner_answer_count") or raw_data.get("owner_answer") or 0
        if isinstance(owner_answers, (int, float)) and owner_answers > 0:
            score += 10
        elif isinstance(owner_answers, str) and owner_answers.strip():
            score += 10
        else:
            score += 0

        # --- Fix #7 : "A des photos" (10%) — remplace "concurrent a un site" ---
        if photos > 0:
            score += 10
        else:
            score += 0

        # --- Fix #7 : "Social media" (10%) ---
        raw_str = json.dumps(raw_data).lower() if raw_data else ""
        has_facebook = "facebook" in raw_str
        has_instagram = "instagram" in raw_str
        if has_facebook and has_instagram:
            score += 10
        elif has_facebook or has_instagram:
            score += 5
        else:
            score += 0

        return min(score, 100)

    # ------------------------------------------------------------------
    # Fix #2 + #3 + #8 : Outscraper API avec retry, rate limiting, validation JSON
    # ------------------------------------------------------------------
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException, httpx.PoolTimeout)),
        before_sleep=lambda retry_state: logger.warning(
            "Retry Outscraper API (tentative %d) apres erreur : %s",
            retry_state.attempt_number,
            retry_state.outcome.exception() if retry_state.outcome else "inconnu",
        ),
    )
    async def scrape_outscraper(self, query: str, city: str, limit: int = 100) -> list[dict]:
        """Appelle l'API Outscraper Google Maps Search."""
        if not self.is_outscraper_configured:
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

        # Fix #3 : Rate limiting — attendre si necessaire
        logger.debug("Attente rate limiter Outscraper...")
        async with _outscraper_limiter:
            logger.debug("Rate limiter Outscraper OK, appel API")
            response = await self._http_client.get(url, params=params, headers=headers)

        # Fix #2 : Retry uniquement sur 5xx, pas sur 4xx
        if response.status_code >= 500:
            response.raise_for_status()
        elif response.status_code >= 400:
            logger.error("Erreur Outscraper %d (non-retryable) : %s", response.status_code, response.text[:500])
            return []

        # Fix #8 : Validation JSON reponse
        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError) as e:
            logger.error("Reponse Outscraper non-JSON : %s (status=%d)", e, response.status_code)
            return []

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
    # Fix #6 : Foursquare Places API
    # ------------------------------------------------------------------
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException, httpx.PoolTimeout)),
        before_sleep=lambda retry_state: logger.warning(
            "Retry Foursquare API (tentative %d) apres erreur : %s",
            retry_state.attempt_number,
            retry_state.outcome.exception() if retry_state.outcome else "inconnu",
        ),
    )
    async def scrape_foursquare(self, query: str, city: str, limit: int = 50) -> list[dict]:
        """Appelle l'API Foursquare Places Search."""
        if not self.is_foursquare_configured:
            raise ValueError("FOURSQUARE_API_KEY non configuree")

        url = "https://api.foursquare.com/v3/places/search"
        params = {
            "query": query,
            "near": city,
            "limit": min(limit, 50),  # Foursquare limite a 50 par requete
            "fields": "name,location,tel,website,rating,categories,photos",
        }
        headers = {
            "Authorization": settings.foursquare_api_key,
            "Accept": "application/json",
        }

        # Rate limiting Foursquare
        logger.debug("Attente rate limiter Foursquare...")
        async with _foursquare_limiter:
            logger.debug("Rate limiter Foursquare OK, appel API")
            response = await self._http_client.get(url, params=params, headers=headers)

        # Retry uniquement sur 5xx
        if response.status_code >= 500:
            response.raise_for_status()
        elif response.status_code >= 400:
            logger.error("Erreur Foursquare %d (non-retryable) : %s", response.status_code, response.text[:500])
            return []

        # Validation JSON reponse
        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError) as e:
            logger.error("Reponse Foursquare non-JSON : %s (status=%d)", e, response.status_code)
            return []

        raw_places = data.get("results", [])

        # Parser les resultats au meme format qu'Outscraper, filtrer sans website
        results = []
        for place in raw_places:
            website = place.get("website", "")
            # Filtrer ceux SANS website (on veut les business sans site)
            if website and website.strip():
                continue

            location = place.get("location", {})
            categories = place.get("categories", [])
            category_name = categories[0].get("name", "") if categories else ""
            photo_count = len(place.get("photos", []))

            parsed = {
                "name": place.get("name"),
                "phone": place.get("tel", ""),
                "site": website,
                "full_address": location.get("formatted_address", ""),
                "city": location.get("locality", city),
                "postal_code": location.get("postcode", ""),
                "country_code": location.get("country", "FR"),
                "latitude": location.get("latitude"),
                "longitude": location.get("longitude"),
                "category": category_name,
                "rating": place.get("rating"),
                "reviews": 0,  # Foursquare ne donne pas le count dans ce endpoint
                "photos_count": photo_count,
                "place_id": place.get("fsq_id"),
                # Garder les raw data Foursquare
                "_foursquare_raw": place,
            }
            results.append(parsed)

        logger.info("Foursquare retourne %d resultats (apres filtre sans website)", len(results))
        return results

    # ------------------------------------------------------------------
    # Traitement d'un resultat Outscraper / Foursquare
    # ------------------------------------------------------------------
    def _parse_outscraper_result(self, item: dict, source: str = "outscraper") -> dict[str, Any] | None:
        """Transforme un resultat Outscraper/Foursquare en dict compatible Lead."""
        dedup = DeduplicationService.get_instance()

        business_name = item.get("name") or item.get("query")
        if not business_name:
            return None

        raw_phone = item.get("phone") or item.get("phone_number") or item.get("tel") or ""
        phone_e164 = dedup.normalize_phone(str(raw_phone)) if raw_phone else None

        if not phone_e164:
            self._stats["no_phone"] += 1
            return None

        place_id = item.get("place_id") or item.get("google_id") or item.get("fsq_id")
        website = item.get("site") or item.get("website") or ""
        has_website = bool(website and website.strip())

        lead_data = {
            "place_id": place_id,
            "source": source,
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
    # Fix #4 : Batch WebSocket broadcasts
    # ------------------------------------------------------------------
    async def _flush_lead_buffer(self) -> None:
        """Envoie les leads accumules via WebSocket (batch)."""
        if not self._lead_buffer:
            return
        try:
            from app.api.websocket import manager
            await manager.broadcast({
                "type": "new_leads_batch",
                "data": self._lead_buffer.copy(),
            })
        except Exception as e:
            logger.debug("Broadcast WebSocket batch echoue : %s", e)
        self._lead_buffer.clear()
        self._last_lead_broadcast = time.monotonic()

    async def _maybe_broadcast_lead(self, lead_data: dict) -> None:
        """Accumule un lead et broadcast si 10 leads OU 5 secondes ecoulees."""
        self._lead_buffer.append({
            "business_name": lead_data.get("business_name"),
            "city": lead_data.get("city"),
            "phone": lead_data.get("phone"),
            "category": lead_data.get("category"),
            "lead_score": lead_data.get("lead_score"),
            "has_website": lead_data.get("has_website"),
        })
        now = time.monotonic()
        # Broadcast tous les 10 leads OU toutes les 5 secondes
        if len(self._lead_buffer) >= 10 or (now - self._last_lead_broadcast) >= 5.0:
            await self._flush_lead_buffer()

    async def _maybe_broadcast_stats(self) -> None:
        """Broadcaster les stats max 1 fois toutes les 5 secondes."""
        now = time.monotonic()
        if (now - self._last_stats_broadcast) < 5.0:
            return
        self._last_stats_broadcast = now
        try:
            from app.api.websocket import manager
            await manager.broadcast({
                "type": "stats",
                "data": {
                    "total": self._stats["total"],
                    "inserted": self._stats["inserted"],
                    "duplicates": self._stats["duplicates"],
                    "errors": self._stats["errors"],
                    "no_phone": self._stats["no_phone"],
                },
            })
        except Exception as e:
            logger.debug("Broadcast WebSocket stats echoue : %s", e)

    # ------------------------------------------------------------------
    # Fix #5 + #10 : Checkpoint Redis pour recovery
    # ------------------------------------------------------------------
    async def _get_redis(self):
        """Retourne un client Redis (lazy)."""
        import redis.asyncio as aioredis
        return aioredis.from_url(settings.redis_url, decode_responses=True)

    async def _save_checkpoint(self, query: str, city: str, source: str, page: int, offset: int) -> None:
        """Sauvegarde le checkpoint du scrape dans Redis."""
        try:
            r = await self._get_redis()
            checkpoint = json.dumps({
                "query": query,
                "city": city,
                "source": source,
                "page": page,
                "offset": offset,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            await r.set("scrape:checkpoint", checkpoint, ex=86400)  # expire 24h
            await r.aclose()
            logger.debug("Checkpoint sauvegarde : page=%d offset=%d", page, offset)
        except Exception as e:
            logger.warning("Impossible de sauvegarder le checkpoint Redis : %s", e)

    async def _load_checkpoint(self) -> dict | None:
        """Charge un checkpoint depuis Redis s'il existe."""
        try:
            r = await self._get_redis()
            data = await r.get("scrape:checkpoint")
            await r.aclose()
            if data:
                checkpoint = json.loads(data)
                logger.info("Checkpoint trouve : %s", checkpoint)
                return checkpoint
        except Exception as e:
            logger.warning("Impossible de charger le checkpoint Redis : %s", e)
        return None

    async def _clear_checkpoint(self) -> None:
        """Supprime le checkpoint Redis (scrape termine normalement)."""
        try:
            r = await self._get_redis()
            await r.delete("scrape:checkpoint")
            await r.aclose()
            logger.debug("Checkpoint Redis supprime")
        except Exception as e:
            logger.warning("Impossible de supprimer le checkpoint Redis : %s", e)

    # ------------------------------------------------------------------
    # Pipeline : traitement d'un batch de resultats (partage Outscraper/Foursquare)
    # ------------------------------------------------------------------
    async def _process_results(self, raw_results: list[dict], source: str = "outscraper") -> None:
        """Dedup + insert + broadcast pour une liste de resultats."""
        dedup = DeduplicationService.get_instance()

        async with async_session() as session:
            for idx, item in enumerate(raw_results):
                if self._should_stop:
                    logger.info("Scrape arrete par l'utilisateur")
                    break

                try:
                    lead_data = self._parse_outscraper_result(item, source=source)
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
                        # Fix #4 : Broadcast batch au lieu de chaque lead
                        await self._maybe_broadcast_lead(lead_data)
                    else:
                        self._stats["duplicates"] += 1

                    # Fix #4 : Stats throttlees a 1 fois / 5 secondes
                    await self._maybe_broadcast_stats()

                except Exception as e:
                    logger.warning("Erreur traitement lead : %s", e)
                    self._stats["errors"] += 1

            await session.commit()

        # Fix #4 : Flush les leads restants dans le buffer
        await self._flush_lead_buffer()
        # Broadcast final des stats
        self._last_stats_broadcast = 0  # forcer le broadcast
        await self._maybe_broadcast_stats()

    # ------------------------------------------------------------------
    # Pipeline complet : scrape → dedup → insert (avec recovery)
    # ------------------------------------------------------------------
    async def run_scrape(self, query: str, city: str, limit: int = 100) -> dict:
        """Lance un scrape complet : API → parse → dedup → insert.
        Fix #5 : Wrapper avec recovery — si crash, attend 30s et reprend.
        Fix #10 : Checkpoint/resume via Redis.
        """
        self._running = True
        self._should_stop = False
        self._current_query = query
        self._current_city = city
        self._stats = {"total": 0, "inserted": 0, "duplicates": 0, "errors": 0, "no_phone": 0}
        self._lead_buffer = []
        self._last_lead_broadcast = time.monotonic()
        self._last_stats_broadcast = 0.0

        # Fix #10 : Verifier s'il y a un checkpoint a reprendre
        checkpoint = await self._load_checkpoint()
        resume_offset = 0
        if checkpoint and checkpoint.get("query") == query and checkpoint.get("city") == city:
            resume_offset = checkpoint.get("offset", 0)
            logger.info("Reprise du scrape a l'offset %d (checkpoint)", resume_offset)

        max_retries = 3  # Fix #5 : nombre max de recovery apres crash
        attempt = 0

        while attempt < max_retries and not self._should_stop:
            attempt += 1
            try:
                # 1. Appel API Outscraper (si configure)
                all_results = []
                if self.is_outscraper_configured:
                    logger.info("Scrape Outscraper : query=%s city=%s limit=%d", query, city, limit)
                    outscraper_results = await self.scrape_outscraper(query, city, limit)
                    all_results.extend(outscraper_results)
                    logger.info("Outscraper retourne %d resultats", len(outscraper_results))

                # Fix #6 : Appel Foursquare (si configure)
                if self.is_foursquare_configured:
                    logger.info("Scrape Foursquare : query=%s city=%s", query, city)
                    try:
                        foursquare_results = await self.scrape_foursquare(query, city, min(limit, 50))
                        all_results.extend(foursquare_results)
                        logger.info("Foursquare retourne %d resultats", len(foursquare_results))
                    except Exception as e:
                        logger.warning("Erreur Foursquare (non-bloquant) : %s", e)

                self._stats["total"] = len(all_results)

                # Fix #10 : Appliquer l'offset du checkpoint
                if resume_offset > 0 and resume_offset < len(all_results):
                    logger.info("Skip des %d premiers resultats (checkpoint)", resume_offset)
                    all_results = all_results[resume_offset:]

                # 2. Traitement des resultats
                await self._process_results(all_results)

                # Fix #10 : Sauvegarder le checkpoint apres chaque batch
                await self._save_checkpoint(query, city, "all", 1, len(all_results))

                # Fix #10 : Scrape termine normalement — supprimer le checkpoint
                await self._clear_checkpoint()

                # Sortir de la boucle de recovery
                break

            except Exception as e:
                # Fix #5 : Recovery — logger, attendre, reprendre
                logger.error(
                    "Crash scrape (tentative %d/%d) : %s",
                    attempt, max_retries, e,
                )
                if attempt < max_retries and not self._should_stop:
                    logger.info("Attente 30s avant reprise...")
                    await asyncio.sleep(30)
                    # Sauvegarder le checkpoint pour la reprise
                    current_offset = self._stats["inserted"] + self._stats["duplicates"] + self._stats["errors"]
                    await self._save_checkpoint(query, city, "all", 1, current_offset)
                else:
                    logger.error("Scrape abandonne apres %d tentatives", max_retries)
                    raise

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
        # Fix #11 : Verifier qu'au moins une API est configuree
        if not self.is_any_api_configured:
            raise ValueError("Aucune cle API configuree (outscraper / foursquare)")
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
