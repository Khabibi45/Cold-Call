"""
API Calls — Enregistrement d'appels, statuts, notes, planning.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.call import Call, CALL_STATUSES
from app.models.lead import Lead

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


@router.post("/")
async def create_call(data: CallCreate, db: AsyncSession = Depends(get_db)):
    """Enregistre un nouvel appel avec son statut."""
    if data.status not in CALL_STATUSES:
        raise HTTPException(400, f"Statut invalide. Statuts valides: {list(CALL_STATUSES.keys())}")

    # Verifier que le lead existe
    lead = await db.get(Lead, data.lead_id)
    if not lead:
        raise HTTPException(404, "Lead introuvable")

    call = Call(
        lead_id=data.lead_id,
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
async def update_call(call_id: int, data: CallUpdate, db: AsyncSession = Depends(get_db)):
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


@router.get("/statuses")
async def get_statuses():
    """Retourne tous les statuts d'appel disponibles avec leur config."""
    return CALL_STATUSES


@router.get("/callbacks")
async def get_callbacks(db: AsyncSession = Depends(get_db)):
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
