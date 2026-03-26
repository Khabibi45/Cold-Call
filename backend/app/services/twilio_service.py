"""
Service Twilio centralise — Gere les tokens, appels sortants et statuts.
Utilise la "Conference Room Technique" : l'agent rejoint une conference
persistante, le systeme dial les prospects dans la meme conference.
"""

from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VoiceGrant
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Dial
from twilio.request_validator import RequestValidator

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("twilio_service")


class TwilioService:
    """Service centralise pour toutes les interactions Twilio."""

    def __init__(self):
        self._settings = get_settings()
        self._client: Client | None = None
        self._validator: RequestValidator | None = None

    @property
    def is_configured(self) -> bool:
        """Verifie que les cles Twilio sont configurees."""
        s = self._settings
        return bool(
            s.twilio_account_sid
            and s.twilio_auth_token
            and s.twilio_api_key
            and s.twilio_api_secret
            and s.twilio_twiml_app_sid
            and s.twilio_phone_number
        )

    @property
    def client(self) -> Client:
        """Client Twilio REST (lazy init)."""
        if self._client is None:
            self._client = Client(
                self._settings.twilio_account_sid,
                self._settings.twilio_auth_token,
            )
        return self._client

    @property
    def validator(self) -> RequestValidator:
        """Validateur de signature Twilio (lazy init)."""
        if self._validator is None:
            self._validator = RequestValidator(self._settings.twilio_auth_token)
        return self._validator

    # ------------------------------------------------------------------
    # Tokens
    # ------------------------------------------------------------------

    def generate_access_token(self, user_id: str, ttl: int = 3600) -> str:
        """
        Genere un Twilio Access Token pour le Voice JS SDK du navigateur.
        Utilise twilio_api_key + twilio_api_secret (PAS account_sid/auth_token).
        Inclut un VoiceGrant avec le twiml_app_sid.

        :param user_id: identifiant unique de l'agent (utilise comme identity)
        :param ttl: duree de validite du token en secondes (defaut 1h)
        :return: token JWT signe
        """
        s = self._settings

        token = AccessToken(
            s.twilio_account_sid,
            s.twilio_api_key,
            s.twilio_api_secret,
            identity=f"agent_{user_id}",
            ttl=ttl,
        )

        # Grant Voice : permet d'emettre et recevoir des appels via le navigateur
        voice_grant = VoiceGrant(
            outgoing_application_sid=s.twilio_twiml_app_sid,
            incoming_allow=True,
        )
        token.add_grant(voice_grant)

        logger.info("token_genere", user_id=user_id, ttl=ttl)
        return token.to_jwt()

    # ------------------------------------------------------------------
    # Appels sortants
    # ------------------------------------------------------------------

    def initiate_call(self, to_number: str, conference_name: str) -> str:
        """
        Lance un appel sortant vers un numero PSTN et le place dans la conference.
        L'URL TwiML pointe vers /api/twilio/voice/outbound qui genere le TwiML
        pour rejoindre la conference de l'agent.

        :param to_number: numero au format E.164 (+33612345678)
        :param conference_name: nom de la conference (ex: agent_42)
        :return: call_sid Twilio
        """
        s = self._settings
        callback_base = s.app_url.rstrip("/")

        call = self.client.calls.create(
            to=to_number,
            from_=s.twilio_phone_number,
            url=f"{callback_base}/api/twilio/voice/outbound?conference={conference_name}",
            status_callback=f"{callback_base}/api/twilio/status-callback",
            status_callback_event=["initiated", "ringing", "answered", "completed"],
            status_callback_method="POST",
        )

        logger.info(
            "appel_lance",
            call_sid=call.sid,
            to=to_number,
            conference=conference_name,
        )
        return call.sid

    # ------------------------------------------------------------------
    # Gestion des appels
    # ------------------------------------------------------------------

    def hangup_call(self, call_sid: str) -> bool:
        """
        Raccroche un appel en cours via l'API Twilio.
        Passe le statut a 'completed' pour forcer la deconnexion.

        :param call_sid: identifiant Twilio de l'appel
        :return: True si l'operation a reussi
        """
        try:
            self.client.calls(call_sid).update(status="completed")
            logger.info("appel_raccroche", call_sid=call_sid)
            return True
        except Exception as e:
            logger.error("erreur_raccrochage", call_sid=call_sid, error=str(e))
            return False

    def get_call_status(self, call_sid: str) -> dict:
        """
        Recupere le statut d'un appel Twilio.

        :param call_sid: identifiant Twilio de l'appel
        :return: dict avec sid, status, duration, direction, etc.
        """
        try:
            call = self.client.calls(call_sid).fetch()
            return {
                "sid": call.sid,
                "status": call.status,
                "duration": call.duration,
                "direction": call.direction,
                "from_": call.from_formatted,
                "to": call.to_formatted,
                "start_time": str(call.start_time) if call.start_time else None,
                "end_time": str(call.end_time) if call.end_time else None,
            }
        except Exception as e:
            logger.error("erreur_statut_appel", call_sid=call_sid, error=str(e))
            return {"sid": call_sid, "status": "unknown", "error": str(e)}

    # ------------------------------------------------------------------
    # TwiML
    # ------------------------------------------------------------------

    @staticmethod
    def twiml_join_conference(conference_name: str) -> str:
        """
        Genere le TwiML pour rejoindre une conference.
        Utilise pour le webhook /voice (agent) et /voice/outbound (prospect).

        :param conference_name: nom de la conference
        :return: TwiML XML sous forme de string
        """
        response = VoiceResponse()
        dial = Dial()
        dial.conference(
            conference_name,
            start_conference_on_enter=True,
            end_conference_on_exit=False,
            beep=False,
        )
        response.append(dial)
        return str(response)

    # ------------------------------------------------------------------
    # Validation des requetes Twilio
    # ------------------------------------------------------------------

    def validate_request(self, url: str, params: dict, signature: str) -> bool:
        """
        Valide la signature d'une requete entrante Twilio.
        Protege contre les requetes forgees sur les webhooks.

        :param url: URL complete de la requete
        :param params: parametres POST de la requete
        :param signature: valeur du header X-Twilio-Signature
        :return: True si la signature est valide
        """
        return self.validator.validate(url, params, signature)


# --- Singleton ---
_twilio_service: TwilioService | None = None


def get_twilio_service() -> TwilioService:
    """Retourne l'instance singleton du service Twilio."""
    global _twilio_service
    if _twilio_service is None:
        _twilio_service = TwilioService()
    return _twilio_service
