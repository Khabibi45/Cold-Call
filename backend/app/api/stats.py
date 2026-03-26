"""
API Stats — Metriques et analytics pour le dashboard.
Appels/jour, taux de connexion, repartition statuts, heatmap horaire.
"""

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, extract, cast, Date
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.call import Call
from app.models.lead import Lead

router = APIRouter()


@router.get("/overview")
async def stats_overview(db: AsyncSession = Depends(get_db)):
    """Stats globales de la plateforme."""
    total_leads = (await db.execute(select(func.count(Lead.id)))).scalar() or 0
    leads_sans_site = (await db.execute(select(func.count(Lead.id)).where(Lead.has_website == False))).scalar() or 0
    total_calls = (await db.execute(select(func.count(Call.id)))).scalar() or 0
    total_meetings = (await db.execute(
        select(func.count(Call.id)).where(Call.status == "meeting_booked")
    )).scalar() or 0
    total_interested = (await db.execute(
        select(func.count(Call.id)).where(Call.status == "interested")
    )).scalar() or 0

    return {
        "total_leads": total_leads,
        "leads_sans_site": leads_sans_site,
        "total_calls": total_calls,
        "total_meetings": total_meetings,
        "total_interested": total_interested,
        "conversion_rate": round(total_meetings / total_calls * 100, 2) if total_calls > 0 else 0,
    }


@router.get("/calls-per-day")
async def calls_per_day(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    """Nombre d'appels par jour sur les N derniers jours."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(
            cast(Call.started_at, Date).label("date"),
            func.count(Call.id).label("count"),
        )
        .where(Call.started_at >= since)
        .group_by(cast(Call.started_at, Date))
        .order_by(cast(Call.started_at, Date))
    )
    return [{"date": str(row.date), "count": row.count} for row in result.all()]


@router.get("/status-breakdown")
async def status_breakdown(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    """Repartition des statuts d'appel."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(Call.status, func.count(Call.id).label("count"))
        .where(Call.started_at >= since)
        .group_by(Call.status)
        .order_by(func.count(Call.id).desc())
    )
    return [{"status": row.status, "count": row.count} for row in result.all()]


@router.get("/hourly-heatmap")
async def hourly_heatmap(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    """Heatmap des appels connectes par heure (pour trouver les meilleurs creneaux)."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    connected_statuses = ["interested", "not_interested", "callback", "meeting_booked", "follow_up", "already_customer"]
    result = await db.execute(
        select(
            extract("dow", Call.started_at).label("day_of_week"),
            extract("hour", Call.started_at).label("hour"),
            func.count(Call.id).label("count"),
        )
        .where(Call.started_at >= since)
        .where(Call.status.in_(connected_statuses))
        .group_by("day_of_week", "hour")
    )
    return [
        {"day": int(row.day_of_week), "hour": int(row.hour), "count": row.count}
        for row in result.all()
    ]
