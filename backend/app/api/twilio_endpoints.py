"""
Endpoints Twilio — Gestion des tokens, appels et webhooks.
ATTENTION : Les webhooks (/voice, /voice/outbound, /status-callback) sont appeles
directement par Twilio et ne doivent PAS avoir de protection JWT.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.logging import get_logger
from app.models.call import Call
from app.models.lead import Lead
from app.models.user import User
from app.services.twilio_service import get_twilio_service

logger = get_logger("twilio_endpoints")
router = APIRouter()


# --- Schemas Pydantic ---

class MakeCallRequest(BaseModel):
    """Requete pour lancer un appel vers un lead."""
    lead_id: int


class HangupRequest(BaseModel):
    """Requete pour raccrocher un appel."""
    call_sid: str


# --- Helper : verification de la config Twilio ---

def _check_twilio_configured():
    """Leve une 503 si Twilio n'est pas configure."""
    service = get_twilio_service()
    if not service.is_configured:
        raise HTTPException(
            status_code=503,
            detail="Twilio n'est pas configure. Verifiez les variables d'environnement.",
        )
    return service


# --- Helper : validation de la signature Twilio sur les webhooks ---

async def _validate_twilio_signature(request: Request) -> dict:
    """
    Valide la signature Twilio d'une requete webhook entrante.
    En mode development, la validation est desactivee pour faciliter le debug.
    Retourne les parametres du formulaire.
    """
    service = get_twilio_service()
    settings = get_settings()
    form_data = await request.form()
    params = dict(form_data)

    # En production, valider la signature Twilio
    if settings.app_env != "development":
        signature = request.headers.get("X-Twilio-Signature", "")
        # Reconstruire l'URL complete
        url = str(request.url)
        if not service.validate_request(url, params, signature):
            logger.warning("signature_twilio_invalide", url=url)
            raise HTTPException(status_code=403, detail="Signature Twilio invalide")

    return params


# ======================================================================
# ENDPOINTS APPELES PAR LE FRONTEND (proteges JWT)
# ======================================================================

@router.post("/token")
async def get_twilio_token(
    current_user: User = Depends(get_current_user),
):
    """
    Genere un Access Token Twilio pour le Voice JS SDK.
    Le frontend l'utilise pour initialiser Twilio.Device.
    """
    service = _check_twilio_configured()

    token = service.generate_access_token(user_id=str(current_user.id))

    logger.info("token_twilio_genere", user_id=current_user.id)
    return {
        "token": token,
        "identity": f"agent_{current_user.id}",
    }


@router.post("/call")
async def make_call(
    data: MakeCallRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Lance un appel vers un lead.
    1. Recupere le lead et son numero en DB
    2. Dial le prospect dans la conference de l'agent
    3. Cree un enregistrement Call en DB avec le twilio_call_sid
    4. Retourne le call_sid et les infos du call
    """
    service = _check_twilio_configured()

    # Charger le lead depuis la DB
    lead = await db.get(Lead, data.lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead introuvable")

    # Verifier qu'il a un numero de telephone
    phone = lead.phone_e164 or lead.phone
    if not phone:
        raise HTTPException(status_code=400, detail="Ce lead n'a pas de numero de telephone")

    # Nom de la conference : unique par agent
    conference_name = f"agent_{current_user.id}"

    # Lancer l'appel via Twilio
    try:
        call_sid = service.initiate_call(
            to_number=phone,
            conference_name=conference_name,
        )
    except Exception as e:
        logger.error("erreur_lancement_appel", error=str(e), lead_id=data.lead_id)
        raise HTTPException(status_code=502, detail=f"Erreur Twilio : {str(e)}")

    # Creer l'enregistrement Call en DB
    call = Call(
        lead_id=lead.id,
        user_id=current_user.id,
        status="no_answer",  # Statut initial, sera mis a jour par le status-callback
        twilio_call_sid=call_sid,
        started_at=datetime.now(timezone.utc),
    )
    db.add(call)
    await db.flush()

    logger.info(
        "appel_lance",
        call_id=call.id,
        call_sid=call_sid,
        lead_id=lead.id,
        user_id=current_user.id,
    )

    return {
        "call_id": call.id,
        "call_sid": call_sid,
        "conference_name": conference_name,
        "lead_id": lead.id,
        "to_number": phone,
    }


@router.post("/hangup")
async def hangup(
    data: HangupRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Raccroche l'appel en cours (retire le prospect de la conference).
    """
    service = _check_twilio_configured()

    success = service.hangup_call(data.call_sid)
    if not success:
        raise HTTPException(status_code=502, detail="Impossible de raccrocher l'appel")

    logger.info("appel_raccroche", call_sid=data.call_sid, user_id=current_user.id)
    return {"message": "Appel raccroche", "call_sid": data.call_sid}


# ======================================================================
# WEBHOOKS APPELES PAR TWILIO (PAS de protection JWT)
# ======================================================================

@router.post("/voice", include_in_schema=False)
async def voice_webhook(request: Request):
    """
    Webhook TwiML appele par Twilio quand un appel est initie depuis le navigateur.
    Place l'agent dans sa conference personnelle.
    Le TwiML App dans Twilio Console doit pointer vers {APP_URL}/api/twilio/voice.
    """
    params = await _validate_twilio_signature(request)
    service = get_twilio_service()

    # L'identity est passee automatiquement par le Voice JS SDK
    # sous forme "agent_{user_id}" (defini dans le token)
    caller = params.get("Caller", "unknown")
    # Le caller pour un appel client SDK est "client:agent_42"
    identity = caller.replace("client:", "") if caller.startswith("client:") else caller
    conference_name = identity  # La conference porte le nom de l'agent

    logger.info("webhook_voice", caller=caller, conference=conference_name)

    twiml = service.twiml_join_conference(conference_name)
    return Response(content=twiml, media_type="application/xml")


@router.post("/voice/outbound", include_in_schema=False)
async def outbound_webhook(request: Request):
    """
    Webhook TwiML pour les appels sortants vers les prospects.
    Place le prospect dans la conference de l'agent.
    Le nom de la conference est passe en parametre GET ?conference=agent_42.
    """
    params = await _validate_twilio_signature(request)
    service = get_twilio_service()

    # Le nom de la conference est passe en query parameter
    conference_name = request.query_params.get("conference", "default")

    logger.info("webhook_outbound", conference=conference_name)

    twiml = service.twiml_join_conference(conference_name)
    return Response(content=twiml, media_type="application/xml")


@router.post("/status-callback", include_in_schema=False)
async def status_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Webhook Twilio pour les changements de statut d'appel.
    Met a jour le Call dans la DB (duree, statut Twilio, etc.).
    Evenements recus : initiated, ringing, answered, completed.
    """
    params = await _validate_twilio_signature(request)

    call_sid = params.get("CallSid", "")
    call_status = params.get("CallStatus", "")
    call_duration = params.get("CallDuration")
    recording_url = params.get("RecordingUrl")

    logger.info(
        "status_callback",
        call_sid=call_sid,
        status=call_status,
        duration=call_duration,
    )

    # Rechercher le Call en DB par twilio_call_sid
    result = await db.execute(
        select(Call).where(Call.twilio_call_sid == call_sid)
    )
    call = result.scalar_one_or_none()

    if not call:
        logger.warning("status_callback_call_introuvable", call_sid=call_sid)
        # Retourner 200 quand meme pour que Twilio ne re-essaie pas
        return Response(content="<Response/>", media_type="application/xml")

    # Mapper les statuts Twilio vers nos statuts internes
    twilio_to_internal = {
        "no-answer": "no_answer",
        "busy": "busy",
        "failed": "disconnected",
        "canceled": "no_answer",
    }

    # Mettre a jour le Call selon le statut Twilio
    if call_status == "completed":
        call.ended_at = datetime.now(timezone.utc)
        if call_duration:
            call.duration_seconds = float(call_duration)
        # Ne pas ecraser un statut deja defini par l'agent (interested, callback, etc.)
        # On ne met "no_answer" que si le statut n'a pas ete change manuellement
        if call.status == "no_answer" and call.duration_seconds and call.duration_seconds > 0:
            pass  # L'agent mettra a jour le statut manuellement apres l'appel

    elif call_status in twilio_to_internal:
        # Statuts terminaux negatifs : mettre a jour automatiquement
        call.status = twilio_to_internal[call_status]
        call.ended_at = datetime.now(timezone.utc)

    # Sauvegarder l'URL d'enregistrement si disponible
    if recording_url:
        call.recording_url = recording_url

    await db.flush()

    return Response(content="<Response/>", media_type="application/xml")
