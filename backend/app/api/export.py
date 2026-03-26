"""
API Export — Export des leads en CSV et Excel.
StreamingResponse pour ne pas surcharger la memoire sur de gros volumes.
"""

import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.lead import Lead

router = APIRouter()


# --- Colonnes exportees ---
EXPORT_COLUMNS = [
    ("id", "ID"),
    ("business_name", "Entreprise"),
    ("phone", "Telephone"),
    ("phone_e164", "Telephone E164"),
    ("email", "Email"),
    ("website", "Site web"),
    ("address", "Adresse"),
    ("city", "Ville"),
    ("postal_code", "Code postal"),
    ("country", "Pays"),
    ("category", "Categorie"),
    ("rating", "Note Google"),
    ("review_count", "Nombre d'avis"),
    ("lead_score", "Score"),
    ("source", "Source"),
]


def _build_leads_query(
    city: str | None,
    category: str | None,
    has_website: bool,
    min_score: int,
):
    """Construit la requete de filtre (reutilisee par CSV et Excel)."""
    query = select(Lead).where(Lead.has_website == has_website)

    if city:
        query = query.where(Lead.city.ilike(f"%{city}%"))
    if category:
        query = query.where(Lead.category.ilike(f"%{category}%"))
    if min_score > 0:
        query = query.where(Lead.lead_score >= min_score)

    return query.order_by(Lead.lead_score.desc())


@router.get("/csv")
async def export_csv(
    city: str | None = Query(None, description="Filtrer par ville"),
    category: str | None = Query(None, description="Filtrer par categorie"),
    has_website: bool = Query(False, description="Inclure ceux avec site web"),
    min_score: int = Query(0, description="Score minimum"),
    db: AsyncSession = Depends(get_db),
):
    """
    Exporte les leads filtres en CSV via StreamingResponse.
    Memes filtres que GET /api/leads/.
    """
    query = _build_leads_query(city, category, has_website, min_score)
    result = await db.execute(query)
    leads = result.scalars().all()

    # Generateur CSV en streaming
    def generate_csv():
        output = io.StringIO()
        writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_MINIMAL)

        # En-tete
        writer.writerow([col[1] for col in EXPORT_COLUMNS])
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)

        # Lignes
        for lead in leads:
            writer.writerow([getattr(lead, col[0], "") or "" for col in EXPORT_COLUMNS])
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"leads_export_{timestamp}.csv"

    return StreamingResponse(
        generate_csv(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/excel")
async def export_excel(
    city: str | None = Query(None, description="Filtrer par ville"),
    category: str | None = Query(None, description="Filtrer par categorie"),
    has_website: bool = Query(False, description="Inclure ceux avec site web"),
    min_score: int = Query(0, description="Score minimum"),
    db: AsyncSession = Depends(get_db),
):
    """
    Exporte les leads filtres en Excel (XLSX).
    Necessite openpyxl — retourne 501 si non disponible.
    """
    try:
        from openpyxl import Workbook
    except ImportError:
        raise HTTPException(
            501,
            "Export Excel non disponible — le package openpyxl n'est pas installe"
        )

    query = _build_leads_query(city, category, has_website, min_score)
    result = await db.execute(query)
    leads = result.scalars().all()

    # Creer le workbook Excel
    wb = Workbook()
    ws = wb.active
    ws.title = "Leads"

    # En-tete avec style
    headers = [col[1] for col in EXPORT_COLUMNS]
    ws.append(headers)

    # Mettre les en-tetes en gras
    from openpyxl.styles import Font
    bold_font = Font(bold=True)
    for cell in ws[1]:
        cell.font = bold_font

    # Lignes de donnees
    for lead in leads:
        row = [getattr(lead, col[0], "") or "" for col in EXPORT_COLUMNS]
        ws.append(row)

    # Ajuster la largeur des colonnes
    for col_idx, (attr, header) in enumerate(EXPORT_COLUMNS, start=1):
        ws.column_dimensions[chr(64 + col_idx) if col_idx <= 26 else "A"].width = max(len(header) + 4, 12)

    # Sauvegarder en memoire
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"leads_export_{timestamp}.xlsx"

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
