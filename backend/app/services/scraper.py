"""
Service scraper — Outscraper + Foursquare API pour Google Maps.
Scrape, normalise, deduplique et insere les leads.
Production-ready : connection pooling, retry, rate limiting, checkpoint/resume.
Memoire persistante via ScrapeJobs pour eviter de gaspiller des credits API.
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
from sqlalchemy import text, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

import redis.asyncio as aioredis

from app.core.config import get_settings
from app.core.database import async_session
from app.models.lead import Lead
from app.models.scrape_job import ScrapeJob, SUGGESTED_SUBCATEGORIES
from app.services.dedup import DeduplicationService

logger = logging.getLogger(__name__)
settings = get_settings()

# ============================================
# CAP MENSUEL API — HARD LIMIT 10 000 REQUETES / MOIS
# Impossible a depasser. Aucune facturation possible.
# ============================================
MONTHLY_API_CAP = 10_000  # NE PAS MODIFIER — protection contre la facturation


class APICapExceeded(Exception):
    """Levee quand le cap mensuel de requetes API est atteint."""
    pass


class APICap:
    """Compteur mensuel de requetes API stocke dans Redis.
    Bloque TOUTE requete au-dela de MONTHLY_API_CAP."""

    REDIS_KEY_PREFIX = "api_cap"

    def __init__(self):
        self._redis: aioredis.Redis | None = None

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(settings.redis_url)
        return self._redis

    def _current_key(self) -> str:
        """Cle Redis unique par mois : api_cap:2026-03"""
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        return f"{self.REDIS_KEY_PREFIX}:{month}"

    async def get_count(self) -> int:
        """Nombre de requetes API ce mois-ci."""
        r = await self._get_redis()
        val = await r.get(self._current_key())
        return int(val) if val else 0

    async def increment(self, amount: int = 1) -> int:
        """Incremente le compteur. Retourne le nouveau total."""
        r = await self._get_redis()
        key = self._current_key()
        new_val = await r.incrby(key, amount)
        # Expiration auto a 35 jours (nettoyage des vieux mois)
        await r.expire(key, 60 * 60 * 24 * 35)
        return new_val

    async def remaining(self) -> int:
        """Requetes restantes ce mois-ci."""
        count = await self.get_count()
        return max(0, MONTHLY_API_CAP - count)

    async def check_or_raise(self, needed: int = 1) -> None:
        """Verifie qu'on a assez de credits. Leve APICapExceeded sinon."""
        remaining = await self.remaining()
        if remaining < needed:
            raise APICapExceeded(
                f"CAP MENSUEL ATTEINT : {await self.get_count()}/{MONTHLY_API_CAP} requetes utilisees. "
                f"Reste {remaining}. Le scraper est BLOQUE jusqu'au mois prochain. "
                f"Aucun frais ne sera facture."
            )

    async def stats(self) -> dict:
        """Stats du cap mensuel."""
        count = await self.get_count()
        return {
            "month": datetime.now(timezone.utc).strftime("%Y-%m"),
            "used": count,
            "remaining": max(0, MONTHLY_API_CAP - count),
            "cap": MONTHLY_API_CAP,
            "percent_used": round(count / MONTHLY_API_CAP * 100, 1) if MONTHLY_API_CAP > 0 else 0,
            "blocked": count >= MONTHLY_API_CAP,
        }


# Singleton global
_api_cap = APICap()

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
    """Scrape Google Maps via Outscraper + Foursquare, dedup + insert.
    Utilise les ScrapeJobs pour la memoire persistante des recherches."""

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
        self._current_job_id: int | None = None

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
    # ScrapeJob — Gestion memoire persistante
    # ------------------------------------------------------------------
    async def _get_or_create_job(self, query: str, city: str) -> tuple[ScrapeJob, bool]:
        """Recupere ou cree un ScrapeJob pour la query+city.
        Retourne (job, is_resume) : is_resume=True si on reprend un job existant.
        """
        async with async_session() as session:
            # Chercher un job existant pour cette query+city
            result = await session.execute(
                select(ScrapeJob)
                .where(and_(
                    ScrapeJob.query == query.lower().strip(),
                    ScrapeJob.city == city.strip(),
                ))
                .order_by(ScrapeJob.created_at.desc())
                .limit(1)
            )
            existing_job = result.scalar_one_or_none()

            if existing_job:
                if existing_job.status == "running":
                    # Job deja en cours — lever une erreur
                    raise RuntimeError(f"Un scrape est deja en cours pour '{query} {city}'")

                if existing_job.status == "completed":
                    # Job deja termine — reprendre avec un offset plus grand
                    existing_job.status = "running"
                    existing_job.last_offset = existing_job.last_offset + existing_job.total_found
                    existing_job.updated_at = datetime.now(timezone.utc)
                    await session.commit()
                    await session.refresh(existing_job)
                    logger.info(
                        "Reprise ScrapeJob #%d : query=%s city=%s offset=%d",
                        existing_job.id, query, city, existing_job.last_offset,
                    )
                    return existing_job, True

                if existing_job.status in ("pending", "failed"):
                    # Job en attente ou echoue — reprendre depuis le dernier offset
                    existing_job.status = "running"
                    existing_job.updated_at = datetime.now(timezone.utc)
                    await session.commit()
                    await session.refresh(existing_job)
                    logger.info(
                        "Reprise ScrapeJob #%d (ancien statut=%s) : offset=%d",
                        existing_job.id, existing_job.status, existing_job.last_offset,
                    )
                    return existing_job, True

            # Pas de job existant — en creer un nouveau
            new_job = ScrapeJob(
                query=query.lower().strip(),
                city=city.strip(),
                source="outscraper",
                status="running",
            )
            session.add(new_job)
            await session.commit()
            await session.refresh(new_job)
            logger.info("Nouveau ScrapeJob #%d : query=%s city=%s", new_job.id, query, city)
            return new_job, False

    async def _update_job(self, job_id: int, **kwargs) -> None:
        """Met a jour les champs d'un ScrapeJob."""
        async with async_session() as session:
            result = await session.execute(
                select(ScrapeJob).where(ScrapeJob.id == job_id)
            )
            job = result.scalar_one_or_none()
            if job:
                for key, value in kwargs.items():
                    setattr(job, key, value)
                job.updated_at = datetime.now(timezone.utc)
                await session.commit()

    async def _complete_job(self, job_id: int) -> None:
        """Marque un ScrapeJob comme termine."""
        await self._update_job(
            job_id,
            status="completed",
            completed_at=datetime.now(timezone.utc),
        )

    async def _fail_job(self, job_id: int, error_msg: str = "") -> None:
        """Marque un ScrapeJob comme echoue."""
        await self._update_job(job_id, status="failed")
        logger.error("ScrapeJob #%d echoue : %s", job_id, error_msg)

    # ------------------------------------------------------------------
    # ScrapeJob — Historique et suggestions
    # ------------------------------------------------------------------
    async def get_job_history(self, limit: int = 50) -> list[dict]:
        """Retourne l'historique des ScrapeJobs avec leurs stats."""
        async with async_session() as session:
            result = await session.execute(
                select(ScrapeJob)
                .order_by(ScrapeJob.created_at.desc())
                .limit(limit)
            )
            jobs = result.scalars().all()
            return [
                {
                    "id": j.id,
                    "query": j.query,
                    "city": j.city,
                    "source": j.source,
                    "status": j.status,
                    "last_offset": j.last_offset,
                    "total_found": j.total_found,
                    "total_inserted": j.total_inserted,
                    "total_duplicates": j.total_duplicates,
                    "total_errors": j.total_errors,
                    "created_at": j.created_at.isoformat() if j.created_at else None,
                    "updated_at": j.updated_at.isoformat() if j.updated_at else None,
                    "completed_at": j.completed_at.isoformat() if j.completed_at else None,
                }
                for j in jobs
            ]

    async def get_suggestions(self, city: str = "") -> list[dict]:
        """Retourne les prochaines queries a lancer, basees sur les jobs deja faits.
        Exclut les queries deja scrapees et propose des sous-categories.
        """
        async with async_session() as session:
            # Recuperer toutes les queries deja faites pour cette ville
            query_filter = select(ScrapeJob.query).where(ScrapeJob.city == city.strip()) if city else select(ScrapeJob.query)
            result = await session.execute(query_filter)
            done_queries = {row[0].lower() for row in result.all()}

        suggestions = []

        # Pour chaque query terminee, proposer ses sous-categories
        for done_query in done_queries:
            subcats = SUGGESTED_SUBCATEGORIES.get(done_query, [])
            for subcat in subcats:
                if subcat.lower() not in done_queries:
                    suggestions.append({
                        "query": subcat,
                        "city": city or "Toulouse",
                        "reason": f"Sous-categorie de '{done_query}'",
                    })

        # Ajouter les categories principales jamais scrapees
        all_main_categories = list(SUGGESTED_SUBCATEGORIES.keys())
        for cat in all_main_categories:
            if cat.lower() not in done_queries:
                suggestions.append({
                    "query": cat,
                    "city": city or "Toulouse",
                    "reason": "Categorie principale non scrapee",
                })

        # Dedupliquer par query et limiter a 20
        seen = set()
        unique_suggestions = []
        for s in suggestions:
            key = s["query"].lower()
            if key not in seen:
                seen.add(key)
                unique_suggestions.append(s)
            if len(unique_suggestions) >= 20:
                break

        return unique_suggestions

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
    # Supporte le parametre skip pour la pagination (memoire ScrapeJob)
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
    async def scrape_outscraper(self, query: str, city: str, limit: int = 100, skip: int = 0) -> list[dict]:
        """Appelle l'API Outscraper Google Maps Search.
        Parametre skip pour la pagination — evite de rescraper les memes fiches.
        VERIFIE LE CAP MENSUEL AVANT CHAQUE APPEL.
        """
        if not self.is_outscraper_configured:
            raise ValueError("OUTSCRAPER_API_KEY non configuree")

        # --- CAP MENSUEL : verification obligatoire ---
        await _api_cap.check_or_raise(needed=1)
        await _api_cap.increment(1)
        logger.info("api_cap_outscraper", **(await _api_cap.stats()))

        search_query = f"{query} {city}"
        url = "https://api.app.outscraper.com/maps/search-v3"
        params = {
            "query": search_query,
            "limit": limit,
            "language": "fr",
            "region": "FR",
            "async": "false",
        }
        # Pagination : utiliser skip pour ne pas retomber sur les memes resultats
        if skip > 0:
            params["skip"] = skip
            logger.info("Outscraper skip=%d (memoire ScrapeJob)", skip)

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
        """Appelle l'API Foursquare Places Search.
        VERIFIE LE CAP MENSUEL AVANT CHAQUE APPEL.
        """
        if not self.is_foursquare_configured:
            raise ValueError("FOURSQUARE_API_KEY non configuree")

        # --- CAP MENSUEL : verification obligatoire ---
        await _api_cap.check_or_raise(needed=1)
        await _api_cap.increment(1)
        logger.info("api_cap_foursquare", **(await _api_cap.stats()))

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
    # Pipeline complet : scrape → dedup → insert (avec memoire ScrapeJob)
    # ------------------------------------------------------------------
    async def run_scrape(self, query: str, city: str, limit: int = 100) -> dict:
        """Lance un scrape complet : ScrapeJob memoire → API → parse → dedup → insert.
        Utilise le ScrapeJob pour savoir ou reprendre (skip/offset).
        """
        self._running = True
        self._should_stop = False
        self._current_query = query
        self._current_city = city
        self._stats = {"total": 0, "inserted": 0, "duplicates": 0, "errors": 0, "no_phone": 0}
        self._lead_buffer = []
        self._last_lead_broadcast = time.monotonic()
        self._last_stats_broadcast = 0.0

        # Recuperer ou creer le ScrapeJob (memoire persistante)
        try:
            job, is_resume = await self._get_or_create_job(query, city)
            self._current_job_id = job.id
            skip_offset = job.last_offset if is_resume else 0
        except RuntimeError as e:
            self._running = False
            raise

        max_retries = 3
        attempt = 0

        while attempt < max_retries and not self._should_stop:
            attempt += 1
            try:
                # 1. Appel API Outscraper (si configure)
                all_results = []
                if self.is_outscraper_configured:
                    logger.info(
                        "Scrape Outscraper : query=%s city=%s limit=%d skip=%d (ScrapeJob #%d)",
                        query, city, limit, skip_offset, job.id,
                    )
                    outscraper_results = await self.scrape_outscraper(
                        query, city, limit, skip=skip_offset,
                    )
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

                # 2. Traitement des resultats
                await self._process_results(all_results)

                # 3. Mettre a jour le ScrapeJob avec les stats
                new_offset = skip_offset + len(all_results)
                await self._update_job(
                    job.id,
                    last_offset=new_offset,
                    total_found=(job.total_found or 0) + len(all_results),
                    total_inserted=(job.total_inserted or 0) + self._stats["inserted"],
                    total_duplicates=(job.total_duplicates or 0) + self._stats["duplicates"],
                    total_errors=(job.total_errors or 0) + self._stats["errors"],
                )

                # 4. Si Outscraper ne retourne plus de resultats → marquer completed
                if len(all_results) == 0:
                    logger.info("Outscraper ne retourne plus de resultats — ScrapeJob #%d termine", job.id)
                    await self._complete_job(job.id)
                else:
                    await self._complete_job(job.id)

                # 5. Checkpoint Redis (compatibilite)
                await self._clear_checkpoint()

                # Sortir de la boucle de recovery
                break

            except Exception as e:
                logger.error(
                    "Crash scrape (tentative %d/%d) : %s",
                    attempt, max_retries, e,
                )
                if attempt < max_retries and not self._should_stop:
                    logger.info("Attente 30s avant reprise...")
                    await asyncio.sleep(30)
                    await self._save_checkpoint(query, city, "all", 1, skip_offset)
                else:
                    await self._fail_job(job.id, str(e))
                    logger.error("Scrape abandonne apres %d tentatives", max_retries)
                    raise

        self._running = False
        self._current_job_id = None
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
            "job_id": self._current_job_id,
            "stats": self._stats.copy(),
        }
