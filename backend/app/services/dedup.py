"""
Service anti-doublon — Bloom Filter + Set en RAM.
Singleton initialise au demarrage avec les phone_e164 et place_id existants.
"""

import logging
from typing import Optional

import phonenumbers
from pybloom_live import ScalableBloomFilter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session
from app.models.lead import Lead

logger = logging.getLogger(__name__)


class DeduplicationService:
    """Anti-doublon 2 niveaux RAM : Bloom Filter (phones) + Set (place_ids)."""

    _instance: Optional["DeduplicationService"] = None

    def __init__(self) -> None:
        self._bloom: ScalableBloomFilter = ScalableBloomFilter(
            initial_capacity=100_000,
            error_rate=0.001,
            mode=ScalableBloomFilter.LARGE_SET_GROWTH,
        )
        self._place_ids: set[str] = set()
        self._loaded = False

    # ------------------------------------------------------------------
    # Singleton
    # ------------------------------------------------------------------
    @classmethod
    def get_instance(cls) -> "DeduplicationService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Initialisation depuis PostgreSQL
    # ------------------------------------------------------------------
    async def load_from_db(self) -> None:
        """Charge tous les phone_e164 et place_id existants dans le Bloom + Set."""
        phone_count = 0
        place_count = 0

        async with async_session() as session:
            # Charger les telephones
            result = await session.execute(
                select(Lead.phone_e164).where(Lead.phone_e164.isnot(None))
            )
            for (phone,) in result.all():
                self._bloom.add(phone)
                phone_count += 1

            # Charger les place_ids
            result = await session.execute(
                select(Lead.place_id).where(Lead.place_id.isnot(None))
            )
            for (pid,) in result.all():
                self._place_ids.add(pid)
                place_count += 1

        self._loaded = True
        logger.info(
            "DeduplicationService charge : %d phones (Bloom), %d place_ids (Set)",
            phone_count,
            place_count,
        )

    # ------------------------------------------------------------------
    # Normalisation telephone
    # ------------------------------------------------------------------
    @staticmethod
    def normalize_phone(raw: str, country: str = "FR") -> str | None:
        """Convertit un numero brut en format E.164. Retourne None si invalide."""
        if not raw:
            return None
        try:
            parsed = phonenumbers.parse(raw, country)
            if not phonenumbers.is_valid_number(parsed):
                return None
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        except phonenumbers.NumberParseException:
            return None

    # ------------------------------------------------------------------
    # Verification doublon
    # ------------------------------------------------------------------
    def is_duplicate(self, phone_e164: str | None = None, place_id: str | None = None) -> bool:
        """Verifie si le lead existe deja via Bloom (phone) ou Set (place_id)."""
        if phone_e164 and phone_e164 in self._bloom:
            return True
        if place_id and place_id in self._place_ids:
            return True
        return False

    # ------------------------------------------------------------------
    # Enregistrement
    # ------------------------------------------------------------------
    def register(self, phone_e164: str | None, place_id: str | None) -> None:
        """Ajoute un lead au Bloom Filter et au Set apres insertion DB reussie."""
        if phone_e164:
            self._bloom.add(phone_e164)
        if place_id:
            self._place_ids.add(place_id)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------
    @property
    def stats(self) -> dict:
        return {
            "bloom_count": self._bloom.count,
            "place_id_count": len(self._place_ids),
            "loaded": self._loaded,
        }
