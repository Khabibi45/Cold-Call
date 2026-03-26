"""
API Leads — CRUD + filtrage des entreprises scrapees.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.lead import Lead

router = APIRouter()


@router.get("/")
async def list_leads(
    city: str | None = Query(None, description="Filtrer par ville"),
    category: str | None = Query(None, description="Filtrer par categorie"),
    has_website: bool = Query(False, description="Inclure ceux avec site web"),
    min_score: int = Query(0, description="Score minimum"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Liste les leads avec filtres, pagination et tri par score."""
    query = select(Lead).where(Lead.has_website == has_website)

    if city:
        query = query.where(Lead.city.ilike(f"%{city}%"))
    if category:
        query = query.where(Lead.category.ilike(f"%{category}%"))
    if min_score > 0:
        query = query.where(Lead.lead_score >= min_score)

    # Comptage total
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Pagination + tri par score desc
    query = query.order_by(Lead.lead_score.desc()).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    leads = result.scalars().all()

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
        "data": [
            {
                "id": l.id,
                "business_name": l.business_name,
                "phone": l.phone,
                "email": l.email,
                "address": l.address,
                "city": l.city,
                "category": l.category,
                "rating": l.rating,
                "review_count": l.review_count,
                "lead_score": l.lead_score,
                "maps_url": l.maps_url,
                "scraped_at": l.scraped_at.isoformat() if l.scraped_at else None,
            }
            for l in leads
        ],
    }


@router.get("/cities")
async def list_cities(db: AsyncSession = Depends(get_db)):
    """Liste les villes distinctes avec leur nombre de leads."""
    result = await db.execute(
        select(Lead.city, func.count(Lead.id).label("count"))
        .where(Lead.has_website == False)
        .group_by(Lead.city)
        .order_by(func.count(Lead.id).desc())
    )
    return [{"city": row.city, "count": row.count} for row in result.all()]


@router.get("/categories")
async def list_categories(db: AsyncSession = Depends(get_db)):
    """Liste les categories distinctes avec leur nombre de leads."""
    result = await db.execute(
        select(Lead.category, func.count(Lead.id).label("count"))
        .where(Lead.has_website == False)
        .group_by(Lead.category)
        .order_by(func.count(Lead.id).desc())
    )
    return [{"category": row.category, "count": row.count} for row in result.all()]
