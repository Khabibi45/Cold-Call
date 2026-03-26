"""
Modele Lead — Entreprise scrapee sans site web.
Contrainte UNIQUE sur phone_e164 pour anti-doublon niveau DB.
"""

from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, Text, JSON,
    Index, UniqueConstraint
)

from app.core.database import Base


class Lead(Base):
    """Une entreprise scrapee depuis Google Maps / Foursquare / etc."""

    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # --- Identifiants ---
    place_id = Column(String(255), unique=True, nullable=True, index=True)
    source = Column(String(50), nullable=False, default="google_maps")

    # --- Infos entreprise ---
    business_name = Column(String(255), nullable=False)
    phone = Column(String(50), nullable=True)
    phone_e164 = Column(String(20), nullable=True, unique=True, index=True)
    email = Column(String(255), nullable=True)
    website = Column(String(500), nullable=True)
    has_website = Column(Boolean, default=False, index=True)

    # --- Localisation ---
    address = Column(Text, nullable=True)
    city = Column(String(100), nullable=True, index=True)
    postal_code = Column(String(20), nullable=True)
    country = Column(String(50), default="FR")
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    # --- Google Maps data ---
    category = Column(String(255), nullable=True, index=True)
    rating = Column(Float, nullable=True)
    review_count = Column(Integer, default=0)
    photo_count = Column(Integer, default=0)
    maps_url = Column(String(500), nullable=True)

    # --- Scoring ---
    lead_score = Column(Integer, default=0, index=True)

    # --- Donnees brutes ---
    raw_data = Column(JSON, nullable=True)

    # --- Timestamps ---
    scraped_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # --- Index composite pour recherche rapide ---
    __table_args__ = (
        Index("ix_leads_city_category", "city", "category"),
        Index("ix_leads_has_website_score", "has_website", "lead_score"),
    )

    def __repr__(self) -> str:
        return f"<Lead {self.business_name} ({self.city})>"
