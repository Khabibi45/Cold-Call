"""
Modele ScrapeJob — Memoire persistante des scrapes effectues.
Permet de ne pas refaire les memes recherches Outscraper et de suivre la progression.
"""

from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, DateTime, JSON, Index, UniqueConstraint
)

from app.core.database import Base


# Sous-categories suggeres automatiquement quand une query est completed
SUGGESTED_SUBCATEGORIES = {
    "restaurant": [
        "pizzeria", "kebab", "brasserie", "bistrot", "sushi",
        "restaurant italien", "restaurant chinois", "restaurant indien",
        "fast food", "creperie", "burger", "traiteur",
    ],
    "coiffeur": [
        "coiffure homme", "coiffure femme", "barbier", "salon de beaute",
        "estheticienne", "onglerie", "institut de beaute",
    ],
    "artisan": [
        "plombier", "electricien", "menuisier", "peintre", "serrurier",
        "carreleur", "macon", "couvreur", "chauffagiste",
    ],
    "garage": [
        "garage automobile", "carrosserie", "mecanique auto", "pneu",
        "controle technique", "lavage auto",
    ],
    "sante": [
        "dentiste", "veterinaire", "osteopathe", "kinesitherapeute",
        "opticien", "pharmacie", "podologue",
    ],
    "commerce": [
        "fleuriste", "boulangerie", "epicerie", "boucherie",
        "fromagerie", "caviste", "tabac presse",
    ],
    "sport": [
        "coach sportif", "salle de sport", "yoga", "pilates",
        "arts martiaux", "danse", "piscine",
    ],
    "services": [
        "auto-ecole", "photographe", "imprimerie", "pressing",
        "demenagement", "garde meuble", "location vehicule",
    ],
}


class ScrapeJob(Base):
    """Un job de scraping avec memoire de progression."""

    __tablename__ = "scrape_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Parametres de recherche
    query = Column(String(255), nullable=False)      # ex: "restaurant"
    city = Column(String(100), nullable=False)        # ex: "Toulouse"
    source = Column(String(50), default="outscraper")

    # Memoire de progression
    status = Column(String(30), default="pending")    # pending, running, completed, failed
    last_offset = Column(Integer, default=0)          # offset Outscraper pour pagination (skip)
    last_page = Column(Integer, default=0)
    total_found = Column(Integer, default=0)          # resultats bruts retournes par l'API
    total_inserted = Column(Integer, default=0)       # leads inseres en DB
    total_duplicates = Column(Integer, default=0)     # doublons detectes
    total_errors = Column(Integer, default=0)         # erreurs de traitement

    # Tracking des zones deja scrapees (grille GPS)
    scraped_zones = Column(JSON, default=list)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Index pour recherche rapide query+city
    __table_args__ = (
        Index("ix_scrape_jobs_query_city", "query", "city"),
        Index("ix_scrape_jobs_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<ScrapeJob {self.query} {self.city} ({self.status})>"
