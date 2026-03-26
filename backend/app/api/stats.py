"""
API Stats — Metriques et analytics pour le dashboard.
Appels/jour, taux de connexion, repartition statuts, heatmap horaire.
Top villes/categories, leads/appels du jour.
"""

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, extract, cast, Date, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.call import Call
from app.models.lead import Lead
from app.models.user import User

router = APIRouter()


@router.get("/overview")
async def stats_overview(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Stats globales de la plateforme, enrichies avec top villes/categories et compteurs du jour."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Compteurs globaux
    total_leads = (await db.execute(select(func.count(Lead.id)))).scalar() or 0
    leads_sans_site = (await db.execute(select(func.count(Lead.id)).where(Lead.has_website == False))).scalar() or 0
    total_calls = (await db.execute(select(func.count(Call.id)))).scalar() or 0
    total_meetings = (await db.execute(
        select(func.count(Call.id)).where(Call.status == "meeting_booked")
    )).scalar() or 0
    total_interested = (await db.execute(
        select(func.count(Call.id)).where(Call.status == "interested")
    )).scalar() or 0

    # Compteurs du jour
    leads_today = (await db.execute(
        select(func.count(Lead.id)).where(Lead.scraped_at >= today_start)
    )).scalar() or 0
    calls_today = (await db.execute(
        select(func.count(Call.id)).where(Call.started_at >= today_start)
    )).scalar() or 0

    # Top 5 villes avec le plus de leads
    top_cities_result = await db.execute(
        select(Lead.city, func.count(Lead.id).label("count"))
        .where(Lead.city.isnot(None))
        .where(Lead.has_website == False)
        .group_by(Lead.city)
        .order_by(func.count(Lead.id).desc())
        .limit(5)
    )
    top_cities = [{"city": row.city, "count": row.count} for row in top_cities_result.all()]

    # Top 5 categories avec le plus de leads
    top_categories_result = await db.execute(
        select(Lead.category, func.count(Lead.id).label("count"))
        .where(Lead.category.isnot(None))
        .where(Lead.has_website == False)
        .group_by(Lead.category)
        .order_by(func.count(Lead.id).desc())
        .limit(5)
    )
    top_categories = [{"category": row.category, "count": row.count} for row in top_categories_result.all()]

    return {
        "total_leads": total_leads,
        "leads_sans_site": leads_sans_site,
        "total_calls": total_calls,
        "total_meetings": total_meetings,
        "total_interested": total_interested,
        "conversion_rate": round(total_meetings / total_calls * 100, 2) if total_calls > 0 else 0,
        "leads_today": leads_today,
        "calls_today": calls_today,
        "top_cities": top_cities,
        "top_categories": top_categories,
    }


@router.get("/calls-per-day")
async def calls_per_day(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
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
    current_user: User = Depends(get_current_user),
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
    current_user: User = Depends(get_current_user),
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
