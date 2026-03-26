"""
API Dialer — Endpoints pour le power dialer.
Gestion des sessions d'appel et selection du prochain lead a appeler.
Integration Twilio pour les appels depuis le navigateur.
"""

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.logging import get_logger
from app.models.call import Call, CALL_STATUSES
from app.models.lead import Lead
from app.models.user import User
from app.services.twilio_service import get_twilio_service

router = APIRouter()
logger = get_logger("dialer")


# --- Schemas Pydantic ---

class SessionResponse(BaseModel):
    """Reponse pour le demarrage/fin de session."""
    message: str
    started_at: datetime | None = None
    ended_at: datetime | None = None


# --- Statuts blacklistes (ne plus appeler) ---
BLACKLIST_STATUSES = [
    status for status, config in CALL_STATUSES.items()
    if config.get("blacklist") or config.get("archive")
]


@router.get("/next")
async def get_next_lead(db: AsyncSession = Depends(get_db)):
    """
    Retourne le prochain lead a appeler.
    Criteres de selection :
    - Score le plus eleve
    - Pas dans la blacklist (statut do_not_call, wrong_number, etc.)
    - Pas d'appel recent (< 2h) pour eviter le harcelement
    - Doit avoir un numero de telephone
    """
    two_hours_ago = datetime.now(timezone.utc) - timedelta(hours=2)

    # Sous-requete : leads blacklistes (dernier appel avec statut blacklist/archive)
    blacklisted_subq = (
        select(Call.lead_id)
        .where(Call.status.in_(BLACKLIST_STATUSES))
        .distinct()
        .subquery()
    )

    # Sous-requete : leads appeles recemment (moins de 2h)
    recent_calls_subq = (
        select(Call.lead_id)
        .where(Call.started_at >= two_hours_ago)
        .distinct()
        .subquery()
    )

    # Requete principale : lead avec le meilleur score, pas blackliste, pas appele recemment
    query = (
        select(Lead)
        .where(Lead.phone.isnot(None))
        .where(Lead.phone != "")
        .where(Lead.has_website == False)
        .where(Lead.id.notin_(select(blacklisted_subq.c.lead_id)))
        .where(Lead.id.notin_(select(recent_calls_subq.c.lead_id)))
        .order_by(Lead.lead_score.desc())
        .limit(1)
    )

    result = await db.execute(query)
    lead = result.scalar_one_or_none()

    if not lead:
        raise HTTPException(404, "Aucun lead disponible a appeler pour le moment")

    # Compter le nombre d'appels precedents pour ce lead
    call_count = (await db.execute(
        select(func.count(Call.id)).where(Call.lead_id == lead.id)
    )).scalar() or 0

    return {
        "id": lead.id,
        "business_name": lead.business_name,
        "phone": lead.phone,
        "phone_e164": lead.phone_e164,
        "email": lead.email,
        "address": lead.address,
        "city": lead.city,
        "category": lead.category,
        "rating": lead.rating,
        "review_count": lead.review_count,
        "lead_score": lead.lead_score,
        "maps_url": lead.maps_url,
        "previous_calls": call_count,
    }


@router.post("/call-next")
async def call_next_lead(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Combine la selection du prochain lead + lancement de l'appel Twilio.
    1. Recupere le prochain lead a appeler (meme logique que GET /next)
    2. Lance l'appel via Twilio dans la conference de l'agent
    3. Cree un enregistrement Call en DB
    4. Retourne les infos du lead + call_sid
    """
    # Verifier que Twilio est configure
    service = get_twilio_service()
    if not service.is_configured:
        raise HTTPException(
            status_code=503,
            detail="Twilio n'est pas configure. Verifiez les variables d'environnement.",
        )

    two_hours_ago = datetime.now(timezone.utc) - timedelta(hours=2)

    # Sous-requete : leads blacklistes
    blacklisted_subq = (
        select(Call.lead_id)
        .where(Call.status.in_(BLACKLIST_STATUSES))
        .distinct()
        .subquery()
    )

    # Sous-requete : leads appeles recemment
    recent_calls_subq = (
        select(Call.lead_id)
        .where(Call.started_at >= two_hours_ago)
        .distinct()
        .subquery()
    )

    # Requete principale
    query = (
        select(Lead)
        .where(Lead.phone.isnot(None))
        .where(Lead.phone != "")
        .where(Lead.has_website == False)
        .where(Lead.id.notin_(select(blacklisted_subq.c.lead_id)))
        .where(Lead.id.notin_(select(recent_calls_subq.c.lead_id)))
        .order_by(Lead.lead_score.desc())
        .limit(1)
    )

    result = await db.execute(query)
    lead = result.scalar_one_or_none()

    if not lead:
        raise HTTPException(404, "Aucun lead disponible a appeler pour le moment")

    # Verifier le numero de telephone
    phone = lead.phone_e164 or lead.phone
    if not phone:
        raise HTTPException(400, "Le lead selectionne n'a pas de numero de telephone")

    # Nom de la conference : unique par agent
    conference_name = f"agent_{current_user.id}"

    # Lancer l'appel via Twilio
    try:
        call_sid = service.initiate_call(
            to_number=phone,
            conference_name=conference_name,
        )
    except Exception as e:
        logger.error("erreur_call_next", error=str(e), lead_id=lead.id)
        raise HTTPException(status_code=502, detail=f"Erreur Twilio : {str(e)}")

    # Creer l'enregistrement Call en DB
    call = Call(
        lead_id=lead.id,
        user_id=current_user.id,
        status="no_answer",
        twilio_call_sid=call_sid,
        started_at=datetime.now(timezone.utc),
    )
    db.add(call)
    await db.flush()

    # Compter les appels precedents
    call_count = (await db.execute(
        select(func.count(Call.id)).where(Call.lead_id == lead.id)
    )).scalar() or 0

    logger.info(
        "call_next_lance",
        call_id=call.id,
        call_sid=call_sid,
        lead_id=lead.id,
        user_id=current_user.id,
    )

    return {
        "call": {
            "call_id": call.id,
            "call_sid": call_sid,
            "conference_name": conference_name,
        },
        "lead": {
            "id": lead.id,
            "business_name": lead.business_name,
            "phone": lead.phone,
            "phone_e164": lead.phone_e164,
            "email": lead.email,
            "address": lead.address,
            "city": lead.city,
            "category": lead.category,
            "rating": lead.rating,
            "review_count": lead.review_count,
            "lead_score": lead.lead_score,
            "maps_url": lead.maps_url,
            "previous_calls": call_count,
        },
    }


@router.post("/start-session")
async def start_session(
    current_user: User = Depends(get_current_user),
):
    """
    Marque le debut d'une session de calling.
    Retourne le timestamp de debut pour tracking cote frontend.
    """
    now = datetime.now(timezone.utc)
    return {
        "message": f"Session de calling demarree pour {current_user.name or current_user.email}",
        "user_id": current_user.id,
        "started_at": now.isoformat(),
    }


@router.post("/end-session")
async def end_session(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Marque la fin d'une session de calling.
    Retourne un resume de la session (nombre d'appels effectues aujourd'hui).
    """
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Compter les appels de l'utilisateur aujourd'hui
    calls_today = (await db.execute(
        select(func.count(Call.id))
        .where(Call.user_id == current_user.id)
        .where(Call.started_at >= today_start)
    )).scalar() or 0

    # Compter les resultats positifs aujourd'hui
    positive_statuses = ["interested", "callback", "meeting_booked", "follow_up"]
    positive_today = (await db.execute(
        select(func.count(Call.id))
        .where(Call.user_id == current_user.id)
        .where(Call.started_at >= today_start)
        .where(Call.status.in_(positive_statuses))
    )).scalar() or 0

    return {
        "message": "Session de calling terminee",
        "user_id": current_user.id,
        "ended_at": now.isoformat(),
        "summary": {
            "calls_today": calls_today,
            "positive_results": positive_today,
        },
    }
