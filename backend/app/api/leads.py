"""
API Leads — CRUD + filtrage des entreprises scrapees.
Tri avance, stats detaillees, filtres dynamiques.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, case, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.lead import Lead
from app.models.call import Call
from app.models.user import User

router = APIRouter()


# --- Schemas Pydantic ---

class LeadCreate(BaseModel):
    """Schema pour la creation manuelle d'un lead."""
    business_name: str = Field(..., min_length=1, max_length=255, description="Nom de l'entreprise")
    phone: str | None = Field(None, max_length=50, description="Numero de telephone")
    phone_e164: str | None = Field(None, max_length=20, description="Numero au format E.164")
    email: str | None = Field(None, max_length=255, description="Email de contact")
    website: str | None = Field(None, max_length=500, description="Site web")
    address: str | None = Field(None, description="Adresse postale")
    city: str | None = Field(None, max_length=100, description="Ville")
    postal_code: str | None = Field(None, max_length=20, description="Code postal")
    country: str = Field("FR", max_length=50, description="Code pays")
    category: str | None = Field(None, max_length=255, description="Categorie d'activite")
    source: str = Field("manual", max_length=50, description="Source du lead")


# --- Colonnes de tri autorisees ---
SORT_COLUMNS = {
    "score": Lead.lead_score,
    "rating": Lead.rating,
    "review_count": Lead.review_count,
    "scraped_at": Lead.scraped_at,
    "city": Lead.city,
    "category": Lead.category,
    "business_name": Lead.business_name,
}


def _serialize_lead(l: Lead) -> dict:
    """Serialise un lead en dictionnaire (reutilisable)."""
    return {
        "id": l.id,
        "business_name": l.business_name,
        "phone": l.phone,
        "phone_e164": l.phone_e164,
        "email": l.email,
        "website": l.website,
        "has_website": l.has_website,
        "address": l.address,
        "city": l.city,
        "postal_code": l.postal_code,
        "country": l.country,
        "category": l.category,
        "rating": l.rating,
        "review_count": l.review_count,
        "lead_score": l.lead_score,
        "maps_url": l.maps_url,
        "scraped_at": l.scraped_at.isoformat() if l.scraped_at else None,
        "updated_at": l.updated_at.isoformat() if l.updated_at else None,
    }


def _serialize_call(c: Call) -> dict:
    """Serialise un appel en dictionnaire."""
    return {
        "id": c.id,
        "status": c.status,
        "duration_seconds": c.duration_seconds,
        "notes": c.notes,
        "contact_email": c.contact_email,
        "callback_at": c.callback_at.isoformat() if c.callback_at else None,
        "started_at": c.started_at.isoformat() if c.started_at else None,
    }


@router.get("/")
async def list_leads(
    city: str | None = Query(None, description="Filtrer par ville"),
    category: str | None = Query(None, description="Filtrer par categorie"),
    has_website: bool = Query(False, description="Inclure ceux avec site web"),
    min_score: int = Query(0, description="Score minimum"),
    sort_by: str = Query("score", description="Colonne de tri : score, rating, review_count, scraped_at, city, category"),
    sort_order: str = Query("desc", description="Ordre de tri : desc ou asc"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Liste les leads avec filtres, pagination et tri avance."""
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

    # Tri dynamique
    sort_column = SORT_COLUMNS.get(sort_by, Lead.lead_score)
    if sort_order == "asc":
        query = query.order_by(sort_column.asc().nullslast())
    else:
        query = query.order_by(sort_column.desc().nullslast())

    # Pagination
    query = query.offset((page - 1) * per_page).limit(per_page)
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
async def list_cities(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Liste les villes distinctes avec leur nombre de leads."""
    result = await db.execute(
        select(Lead.city, func.count(Lead.id).label("count"))
        .where(Lead.has_website == False)
        .where(Lead.city.isnot(None))
        .group_by(Lead.city)
        .order_by(func.count(Lead.id).desc())
    )
    return [{"city": row.city, "count": row.count} for row in result.all()]


@router.get("/categories")
async def list_categories(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Liste les categories distinctes avec leur nombre de leads."""
    result = await db.execute(
        select(Lead.category, func.count(Lead.id).label("count"))
        .where(Lead.has_website == False)
        .where(Lead.category.isnot(None))
        .group_by(Lead.category)
        .order_by(func.count(Lead.id).desc())
    )
    return [{"category": row.category, "count": row.count} for row in result.all()]


@router.get("/stats")
async def leads_stats(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Stats detaillees des leads : repartition par ville, categorie, score, etc."""
    # Total leads
    total = (await db.execute(select(func.count(Lead.id)))).scalar() or 0

    # Par ville (top 10)
    by_city_result = await db.execute(
        select(Lead.city, func.count(Lead.id).label("count"))
        .where(Lead.city.isnot(None))
        .group_by(Lead.city)
        .order_by(func.count(Lead.id).desc())
        .limit(10)
    )
    by_city = [{"city": row.city, "count": row.count} for row in by_city_result.all()]

    # Par categorie (top 10)
    by_category_result = await db.execute(
        select(Lead.category, func.count(Lead.id).label("count"))
        .where(Lead.category.isnot(None))
        .group_by(Lead.category)
        .order_by(func.count(Lead.id).desc())
        .limit(10)
    )
    by_category = [{"category": row.category, "count": row.count} for row in by_category_result.all()]

    # Par tranche de score
    by_score_result = await db.execute(
        select(
            case(
                (and_(Lead.lead_score >= 80, Lead.lead_score <= 100), "80-100"),
                (and_(Lead.lead_score >= 60, Lead.lead_score < 80), "60-79"),
                (and_(Lead.lead_score >= 40, Lead.lead_score < 60), "40-59"),
                (and_(Lead.lead_score >= 20, Lead.lead_score < 40), "20-39"),
                else_="0-19",
            ).label("range"),
            func.count(Lead.id).label("count"),
        )
        .group_by("range")
        .order_by("range")
    )
    by_score_range = [{"range": row.range, "count": row.count} for row in by_score_result.all()]

    # Score moyen
    avg_score = (await db.execute(select(func.avg(Lead.lead_score)))).scalar() or 0

    # Avec/sans telephone
    with_phone = (await db.execute(
        select(func.count(Lead.id)).where(Lead.phone.isnot(None)).where(Lead.phone != "")
    )).scalar() or 0
    without_phone = total - with_phone

    return {
        "total": total,
        "by_city": by_city,
        "by_category": by_category,
        "by_score_range": by_score_range,
        "avg_score": round(avg_score, 1),
        "with_phone": with_phone,
        "without_phone": without_phone,
    }


@router.get("/{lead_id}")
async def get_lead(lead_id: int, db: AsyncSession = Depends(get_db)):
    """Detail complet d'un lead avec son historique d'appels."""
    lead = await db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Lead introuvable")

    # Recuperer l'historique d'appels du lead, du plus recent au plus ancien
    result = await db.execute(
        select(Call)
        .where(Call.lead_id == lead_id)
        .order_by(Call.started_at.desc())
    )
    calls = result.scalars().all()

    data = _serialize_lead(lead)
    data["calls"] = [_serialize_call(c) for c in calls]
    data["total_calls"] = len(calls)

    return data


@router.post("/", status_code=201)
async def create_lead(data: LeadCreate, db: AsyncSession = Depends(get_db)):
    """
    Creation manuelle d'un lead.
    Deduplication par phone_e164 : si un lead avec le meme numero E.164
    existe deja, retourne une erreur 409.
    """
    # Deduplication par numero E.164 si fourni
    if data.phone_e164:
        existing = await db.execute(
            select(Lead).where(Lead.phone_e164 == data.phone_e164)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(409, "Un lead avec ce numero de telephone existe deja")

    lead = Lead(
        business_name=data.business_name,
        phone=data.phone,
        phone_e164=data.phone_e164,
        email=data.email,
        website=data.website,
        has_website=bool(data.website),
        address=data.address,
        city=data.city,
        postal_code=data.postal_code,
        country=data.country,
        category=data.category,
        source=data.source,
    )
    db.add(lead)
    await db.flush()

    return _serialize_lead(lead)


@router.delete("/{lead_id}", status_code=200)
async def delete_lead(lead_id: int, db: AsyncSession = Depends(get_db)):
    """
    Supprime un lead et ses appels associes (CASCADE).
    Retourne 404 si le lead n'existe pas.
    """
    lead = await db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Lead introuvable")

    await db.delete(lead)
    return {"message": f"Lead {lead_id} supprime avec succes"}
