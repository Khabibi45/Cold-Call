"""
API Import CSV — Upload et insertion de leads depuis un fichier CSV.
Format attendu : business_name, phone, address, city, category
"""

import csv
import io
import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.dedup import DeduplicationService
from app.services.scraper import ScraperService

logger = logging.getLogger(__name__)
router = APIRouter()

# Colonnes obligatoires dans le CSV
REQUIRED_COLUMNS = {"business_name", "phone"}
# Colonnes optionnelles reconnues
OPTIONAL_COLUMNS = {"address", "city", "category", "email", "postal_code", "country", "place_id"}


@router.post("/import")
async def import_csv(
    file: UploadFile = File(..., description="Fichier CSV a importer"),
    db: AsyncSession = Depends(get_db),
):
    """
    Importe des leads depuis un fichier CSV.
    Retourne les stats : importes, doublons, erreurs.
    """
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Le fichier doit etre un CSV (.csv)")

    # Lire le contenu
    content = await file.read()
    try:
        text_content = content.decode("utf-8-sig")  # gere le BOM Windows
    except UnicodeDecodeError:
        try:
            text_content = content.decode("latin-1")
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="Encodage du fichier non supporte (UTF-8 ou Latin-1 attendu)")

    reader = csv.DictReader(io.StringIO(text_content), delimiter=",")
    if reader.fieldnames is None:
        raise HTTPException(status_code=400, detail="Fichier CSV vide ou sans en-tete")

    # Normaliser les noms de colonnes (strip + lower)
    reader.fieldnames = [f.strip().lower().replace(" ", "_") for f in reader.fieldnames]

    # Verifier colonnes obligatoires
    missing = REQUIRED_COLUMNS - set(reader.fieldnames)
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Colonnes manquantes : {', '.join(missing)}. Attendu : business_name, phone",
        )

    dedup = DeduplicationService.get_instance()
    stats = {"total": 0, "imported": 0, "duplicates": 0, "errors": 0, "no_phone": 0}
    errors_detail: list[dict] = []

    for row_num, row in enumerate(reader, start=2):  # start=2 car ligne 1 = header
        stats["total"] += 1

        try:
            business_name = (row.get("business_name") or "").strip()
            if not business_name:
                stats["errors"] += 1
                errors_detail.append({"line": row_num, "reason": "business_name vide"})
                continue

            raw_phone = (row.get("phone") or "").strip()
            country = (row.get("country") or "FR").strip().upper()
            phone_e164 = dedup.normalize_phone(raw_phone, country=country)

            if not phone_e164:
                stats["no_phone"] += 1
                errors_detail.append({"line": row_num, "reason": f"Telephone invalide : {raw_phone}"})
                continue

            place_id = (row.get("place_id") or "").strip() or None

            # Check dedup RAM
            if dedup.is_duplicate(phone_e164=phone_e164, place_id=place_id):
                stats["duplicates"] += 1
                continue

            city = (row.get("city") or "").strip() or None
            category = (row.get("category") or "").strip() or None
            address = (row.get("address") or "").strip() or None
            email = (row.get("email") or "").strip() or None
            postal_code = (row.get("postal_code") or "").strip() or None

            # Calculer le score (basique pour import CSV — pas de rating/reviews)
            lead_data = {
                "has_website": False,
                "review_count": 0,
                "rating": 0,
                "photo_count": 0,
                "category": category or "",
            }
            lead_score = ScraperService.calculate_score(lead_data)

            # INSERT ON CONFLICT DO NOTHING
            stmt = text("""
                INSERT INTO leads (
                    place_id, source, business_name, phone, phone_e164,
                    email, has_website, address, city, postal_code,
                    country, category, lead_score, scraped_at, updated_at
                ) VALUES (
                    :place_id, 'csv_import', :business_name, :phone, :phone_e164,
                    :email, false, :address, :city, :postal_code,
                    :country, :category, :lead_score, NOW(), NOW()
                )
                ON CONFLICT (phone_e164) DO NOTHING
            """)
            result = await db.execute(stmt, {
                "place_id": place_id,
                "business_name": business_name,
                "phone": raw_phone,
                "phone_e164": phone_e164,
                "email": email,
                "address": address,
                "city": city,
                "postal_code": postal_code,
                "country": country,
                "category": category,
                "lead_score": lead_score,
            })

            if result.rowcount > 0:
                dedup.register(phone_e164, place_id)
                stats["imported"] += 1
            else:
                stats["duplicates"] += 1

        except Exception as e:
            logger.warning("Erreur import ligne %d : %s", row_num, e)
            stats["errors"] += 1
            errors_detail.append({"line": row_num, "reason": str(e)})

    return {
        "message": f"{stats['imported']} leads importes sur {stats['total']} lignes",
        "stats": stats,
        "errors": errors_detail[:50],  # Limiter a 50 erreurs dans la reponse
    }
