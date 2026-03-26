"""
API Calls — Enregistrement d'appels, statuts, notes, planning.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, update, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.call import Call, CALL_STATUSES
from app.models.lead import Lead
from app.models.user import User

router = APIRouter()


class CallCreate(BaseModel):
    """Schema pour enregistrer un appel."""
    lead_id: int
    status: str = Field(..., description="Code statut (ex: interested, no_answer)")
    duration_seconds: float = 0
    notes: str | None = None
    contact_email: str | None = None
    callback_at: datetime | None = None


class CallUpdate(BaseModel):
    """Schema pour mettre a jour un appel."""
    status: str | None = None
    notes: str | None = None
    contact_email: str | None = None
    callback_at: datetime | None = None


@router.get("/")
async def list_calls(
    status: str | None = Query(None, description="Filtrer par statut d'appel"),
    lead_id: int | None = Query(None, description="Filtrer par lead"),
    date_from: datetime | None = Query(None, description="Date de debut (ISO 8601)"),
    date_to: datetime | None = Query(None, description="Date de fin (ISO 8601)"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Liste paginee de tous les appels avec filtres optionnels."""
    query = select(Call)

    # Filtres
    if status:
        if status not in CALL_STATUSES:
            raise HTTPException(400, f"Statut invalide. Statuts valides: {list(CALL_STATUSES.keys())}")
        query = query.where(Call.status == status)
    if lead_id:
        query = query.where(Call.lead_id == lead_id)
    if date_from:
        query = query.where(Call.started_at >= date_from)
    if date_to:
        query = query.where(Call.started_at <= date_to)

    # Comptage total
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Pagination + tri par date desc
    query = query.order_by(desc(Call.started_at)).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    calls = result.scalars().all()

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
        "data": [
            {
                "id": c.id,
                "lead_id": c.lead_id,
                "user_id": c.user_id,
                "business_name": c.lead.business_name if c.lead else None,
                "phone": c.lead.phone if c.lead else None,
                "status": c.status,
                "duration_seconds": c.duration_seconds,
                "notes": c.notes,
                "contact_email": c.contact_email,
                "callback_at": c.callback_at.isoformat() if c.callback_at else None,
                "started_at": c.started_at.isoformat() if c.started_at else None,
                "ended_at": c.ended_at.isoformat() if c.ended_at else None,
            }
            for c in calls
        ],
    }


@router.post("/")
async def create_call(
    data: CallCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Enregistre un nouvel appel avec son statut. user_id rempli automatiquement via JWT."""
    if data.status not in CALL_STATUSES:
        raise HTTPException(400, f"Statut invalide. Statuts valides: {list(CALL_STATUSES.keys())}")

    # Verifier que le lead existe
    lead = await db.get(Lead, data.lead_id)
    if not lead:
        raise HTTPException(404, "Lead introuvable")

    call = Call(
        lead_id=data.lead_id,
        user_id=current_user.id,
        status=data.status,
        duration_seconds=data.duration_seconds,
        notes=data.notes,
        contact_email=data.contact_email,
        callback_at=data.callback_at,
        started_at=datetime.now(timezone.utc),
    )
    db.add(call)
    await db.flush()

    # Si email fourni, mettre a jour le lead
    if data.contact_email:
        await db.execute(update(Lead).where(Lead.id == data.lead_id).values(email=data.contact_email))

    # Si blacklist, marquer le lead
    status_config = CALL_STATUSES[data.status]
    if status_config.get("blacklist"):
        await db.execute(update(Lead).where(Lead.id == data.lead_id).values(has_website=True))

    return {"id": call.id, "status": call.status, "lead_id": call.lead_id}


@router.patch("/{call_id}")
async def update_call(call_id: int, data: CallUpdate, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Met a jour un appel existant (statut, notes, callback)."""
    call = await db.get(Call, call_id)
    if not call:
        raise HTTPException(404, "Appel introuvable")

    if data.status and data.status not in CALL_STATUSES:
        raise HTTPException(400, f"Statut invalide. Statuts valides: {list(CALL_STATUSES.keys())}")

    if data.status:
        call.status = data.status
    if data.notes is not None:
        call.notes = data.notes
    if data.contact_email is not None:
        call.contact_email = data.contact_email
    if data.callback_at is not None:
        call.callback_at = data.callback_at

    return {"id": call.id, "status": call.status, "updated": True}


@router.get("/recent")
async def recent_calls(
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Les N derniers appels passes, avec info du lead."""
    result = await db.execute(
        select(Call)
        .order_by(desc(Call.started_at))
        .limit(limit)
    )
    calls = result.scalars().all()
    return [
        {
            "id": c.id,
            "lead_id": c.lead_id,
            "business_name": c.lead.business_name if c.lead else None,
            "phone": c.lead.phone if c.lead else None,
            "status": c.status,
            "duration_seconds": c.duration_seconds,
            "started_at": c.started_at.isoformat() if c.started_at else None,
            "notes": c.notes,
        }
        for c in calls
    ]


@router.get("/statuses")
async def get_statuses():
    """Retourne tous les statuts d'appel disponibles avec leur config."""
    return CALL_STATUSES


@router.get("/callbacks")
async def get_callbacks(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Liste les rappels planifies (callbacks a venir)."""
    result = await db.execute(
        select(Call)
        .where(Call.callback_at.isnot(None))
        .where(Call.callback_at >= datetime.now(timezone.utc))
        .order_by(Call.callback_at.asc())
        .limit(100)
    )
    calls = result.scalars().all()
    return [
        {
            "id": c.id,
            "lead_id": c.lead_id,
            "business_name": c.lead.business_name if c.lead else None,
            "phone": c.lead.phone if c.lead else None,
            "callback_at": c.callback_at.isoformat(),
            "notes": c.notes,
        }
        for c in calls
    ]


@router.get("/{call_id}")
async def get_call(call_id: int, db: AsyncSession = Depends(get_db)):
    """Detail complet d'un appel avec les informations du lead associe."""
    call = await db.get(Call, call_id)
    if not call:
        raise HTTPException(404, "Appel introuvable")

    return {
        "id": call.id,
        "lead_id": call.lead_id,
        "user_id": call.user_id,
        "business_name": call.lead.business_name if call.lead else None,
        "phone": call.lead.phone if call.lead else None,
        "status": call.status,
        "duration_seconds": call.duration_seconds,
        "notes": call.notes,
        "contact_email": call.contact_email,
        "callback_at": call.callback_at.isoformat() if call.callback_at else None,
        "started_at": call.started_at.isoformat() if call.started_at else None,
        "ended_at": call.ended_at.isoformat() if call.ended_at else None,
        "twilio_call_sid": call.twilio_call_sid,
        "recording_url": call.recording_url,
    }
