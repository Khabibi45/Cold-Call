"""
Modele User — Utilisateur de la plateforme.
Supporte auth locale (email/password) et OAuth2 (Google/GitHub).
"""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Boolean, DateTime

from app.core.database import Base


class User(Base):
    """Utilisateur de la plateforme Cold Call."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # --- Identite ---
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=True)
    avatar_url = Column(String(500), nullable=True)

    # --- Auth locale ---
    password_hash = Column(String(255), nullable=True)

    # --- OAuth2 ---
    oauth_provider = Column(String(50), nullable=True)
    oauth_id = Column(String(255), nullable=True)

    # --- Etat ---
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)

    # --- Stripe ---
    stripe_customer_id = Column(String(255), nullable=True)
    subscription_plan = Column(String(50), default="free")

    # --- Timestamps ---
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_login = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<User {self.email}>"
