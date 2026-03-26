"""
Modele Call — Historique de chaque appel passe.
Lie a un Lead et un User. Stocke statut, duree, notes, enregistrement.
"""

from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, DateTime, Text, ForeignKey, Float
)
from sqlalchemy.orm import relationship

from app.core.database import Base


# --- Statuts d'appel standardises ---
CALL_STATUSES = {
    "no_answer": {"label": "Pas de reponse", "color": "#6b7280", "auto_retry": True, "retry_delay_hours": 48},
    "busy": {"label": "Occupe", "color": "#6b7280", "auto_retry": True, "retry_delay_hours": 2},
    "voicemail": {"label": "Messagerie vocale", "color": "#3b82f6", "auto_retry": True, "retry_delay_hours": 24},
    "wrong_number": {"label": "Mauvais numero", "color": "#ef4444", "auto_retry": False, "archive": True},
    "disconnected": {"label": "Numero HS", "color": "#ef4444", "auto_retry": False, "archive": True},
    "gatekeeper": {"label": "Standard/Accueil", "color": "#f97316", "auto_retry": True, "retry_delay_hours": 24},
    "interested": {"label": "Interesse", "color": "#22c55e", "auto_retry": False, "follow_up": True},
    "not_interested": {"label": "Pas interesse", "color": "#ef4444", "auto_retry": False, "archive": True},
    "callback": {"label": "Rappel planifie", "color": "#a855f7", "auto_retry": False, "calendar": True},
    "meeting_booked": {"label": "RDV pris", "color": "#10b981", "auto_retry": False, "calendar": True},
    "follow_up": {"label": "A relancer", "color": "#f59e0b", "auto_retry": False, "follow_up": True},
    "not_qualified": {"label": "Non qualifie", "color": "#6b7280", "auto_retry": False, "archive": True},
    "already_customer": {"label": "Deja client", "color": "#3b82f6", "auto_retry": False},
    "do_not_call": {"label": "Ne plus appeler", "color": "#000000", "auto_retry": False, "blacklist": True},
    "left_company": {"label": "Parti/Mauvais contact", "color": "#6b7280", "auto_retry": False, "archive": True},
}


class Call(Base):
    """Un appel telephonique passe a un lead."""

    __tablename__ = "calls"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # --- Relations ---
    lead_id = Column(Integer, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    # --- Appel ---
    status = Column(String(30), nullable=False, default="no_answer", index=True)
    duration_seconds = Column(Float, default=0)
    started_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    ended_at = Column(DateTime(timezone=True), nullable=True)

    # --- Notes & suivi ---
    notes = Column(Text, nullable=True)
    contact_email = Column(String(255), nullable=True)
    callback_at = Column(DateTime(timezone=True), nullable=True, index=True)

    # --- Twilio ---
    twilio_call_sid = Column(String(50), nullable=True)
    recording_url = Column(String(500), nullable=True)

    # --- Relations ORM ---
    lead = relationship("Lead", backref="calls", lazy="selectin")
    user = relationship("User", backref="calls", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Call {self.id} lead={self.lead_id} status={self.status}>"
