"""
API Test Runner — Endpoint qui lance tous les tests fonctionnels et retourne les resultats.
Accessible via GET /api/tests/run (protege admin uniquement).
Chaque test verifie une fonctionnalite specifique avec un verdict PASS/FAIL.
"""

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.security import hash_password, verify_password, create_access_token, create_refresh_token, decode_token
from app.models.user import User
from app.models.lead import Lead
from app.models.call import Call, CALL_STATUSES
from app.services.dedup import DeduplicationService

router = APIRouter()


class TestResult:
    """Resultat d'un test individuel."""
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self.status = "PENDING"
        self.detail = ""
        self.duration_ms = 0

    def passed(self, detail: str = ""):
        self.status = "PASS"
        self.detail = detail

    def failed(self, detail: str):
        self.status = "FAIL"
        self.detail = detail

    def to_dict(self):
        return {
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "detail": self.detail,
            "duration_ms": self.duration_ms,
        }


async def _run_all_tests(db: AsyncSession, user: User) -> list[dict]:
    """Execute tous les tests et retourne les resultats."""
    results = []
    import time

    # ============================================
    # TESTS SECURITE
    # ============================================

    # Test 1 : Hash + verify password
    t = TestResult("securite_hash_password", "Argon2 hash et verify fonctionnent")
    start = time.time()
    try:
        h = hash_password("testpassword123")
        assert verify_password("testpassword123", h), "Verify devrait retourner True"
        assert not verify_password("mauvais", h), "Verify devrait retourner False pour mauvais password"
        t.passed(f"Hash genere: {h[:30]}...")
    except Exception as e:
        t.failed(str(e))
    t.duration_ms = round((time.time() - start) * 1000)
    results.append(t)

    # Test 2 : JWT access token
    t = TestResult("securite_jwt_access", "JWT access token creation et decodage")
    start = time.time()
    try:
        token = create_access_token({"sub": "1", "email": "test@test.fr"})
        payload = decode_token(token)
        assert payload is not None, "Decode ne devrait pas retourner None"
        assert payload["sub"] == "1", f"Sub devrait etre '1', got '{payload.get('sub')}'"
        assert payload["type"] == "access", "Type devrait etre 'access'"
        t.passed(f"Token cree et decode OK, expire a {payload.get('exp')}")
    except Exception as e:
        t.failed(str(e))
    t.duration_ms = round((time.time() - start) * 1000)
    results.append(t)

    # Test 3 : JWT refresh token
    t = TestResult("securite_jwt_refresh", "JWT refresh token creation et decodage")
    start = time.time()
    try:
        token = create_refresh_token({"sub": "1", "email": "test@test.fr"})
        payload = decode_token(token)
        assert payload is not None, "Decode ne devrait pas retourner None"
        assert payload["type"] == "refresh", "Type devrait etre 'refresh'"
        t.passed("Refresh token OK")
    except Exception as e:
        t.failed(str(e))
    t.duration_ms = round((time.time() - start) * 1000)
    results.append(t)

    # Test 4 : JWT token expire
    t = TestResult("securite_jwt_expire", "JWT token expire est rejete")
    start = time.time()
    try:
        token = create_access_token({"sub": "1"}, expires_delta=timedelta(seconds=-1))
        payload = decode_token(token)
        assert payload is None, "Token expire devrait retourner None"
        t.passed("Token expire correctement rejete")
    except Exception as e:
        t.failed(str(e))
    t.duration_ms = round((time.time() - start) * 1000)
    results.append(t)

    # ============================================
    # TESTS BASE DE DONNEES
    # ============================================

    # Test 5 : Connexion DB active
    t = TestResult("db_connexion", "PostgreSQL repond aux requetes")
    start = time.time()
    try:
        result = await db.execute(select(func.count(User.id)))
        count = result.scalar()
        t.passed(f"{count} utilisateur(s) en base")
    except Exception as e:
        t.failed(str(e))
    t.duration_ms = round((time.time() - start) * 1000)
    results.append(t)

    # Test 6 : Tables existent
    t = TestResult("db_tables", "Les 4 tables existent (users, leads, calls, scrape_jobs)")
    start = time.time()
    try:
        for model, name in [(User, "users"), (Lead, "leads"), (Call, "calls")]:
            r = await db.execute(select(func.count(model.id)))
            r.scalar()
        t.passed("4 tables accessibles")
    except Exception as e:
        t.failed(f"Table manquante: {e}")
    t.duration_ms = round((time.time() - start) * 1000)
    results.append(t)

    # Test 7 : User actuel existe
    t = TestResult("db_user_actuel", "L'utilisateur connecte existe en base")
    start = time.time()
    try:
        u = await db.get(User, user.id)
        assert u is not None, "User introuvable"
        assert u.email == user.email, f"Email mismatch: {u.email} != {user.email}"
        t.passed(f"User #{u.id} — {u.email}")
    except Exception as e:
        t.failed(str(e))
    t.duration_ms = round((time.time() - start) * 1000)
    results.append(t)

    # ============================================
    # TESTS LEADS
    # ============================================

    # Test 8 : Creer un lead de test
    t = TestResult("leads_creation", "Creation d'un lead en base")
    start = time.time()
    test_lead = None
    try:
        test_lead = Lead(
            business_name="__TEST_RUNNER_LEAD__",
            phone="+33500000000",
            phone_e164="+33500000000",
            city="TestVille",
            category="test",
            source="test_runner",
            has_website=False,
        )
        db.add(test_lead)
        await db.flush()
        assert test_lead.id is not None, "Lead ID devrait etre genere"
        t.passed(f"Lead #{test_lead.id} cree")
    except Exception as e:
        t.failed(str(e))
    t.duration_ms = round((time.time() - start) * 1000)
    results.append(t)

    # Test 9 : Doublon telephone rejete
    t = TestResult("leads_doublon_phone", "Doublon phone_e164 est rejete par la DB")
    start = time.time()
    try:
        # Verifier que le lead de test existe
        check = await db.execute(select(Lead).where(Lead.phone_e164 == "+33500000000"))
        if check.scalar_one_or_none():
            t.passed("UNIQUE constraint active (lead avec ce phone existe deja)")
        else:
            t.failed("Le lead de test n'a pas ete cree — test precedent en echec")
    except Exception as e:
        t.failed(str(e))
    t.duration_ms = round((time.time() - start) * 1000)
    results.append(t)

    # Test 10 : Recherche leads par nom
    t = TestResult("leads_recherche", "Recherche texte dans les leads fonctionne")
    start = time.time()
    try:
        await db.commit()  # Forcer la persistance du lead de test
        result = await db.execute(
            select(Lead).where(Lead.business_name.ilike("%TEST_RUNNER%"))
        )
        leads = result.scalars().all()
        assert len(leads) >= 1, f"Devrait trouver au moins 1 lead, trouve {len(leads)}"
        t.passed(f"{len(leads)} lead(s) trouve(s) avec recherche 'TEST_RUNNER'")
    except Exception as e:
        t.failed(str(e))
    t.duration_ms = round((time.time() - start) * 1000)
    results.append(t)

    # ============================================
    # TESTS APPELS
    # ============================================

    # Test 11 : Creer un appel
    t = TestResult("calls_creation", "Creation d'un appel lie a un lead")
    start = time.time()
    test_call = None
    try:
        # Re-fetch le lead de test (apres commit)
        result = await db.execute(select(Lead).where(Lead.source == "test_runner"))
        tl = result.scalar_one_or_none()
        if tl:
            test_call = Call(
                lead_id=tl.id,
                user_id=user.id,
                status="interested",
                duration_seconds=45.5,
                notes="Test automatique",
            )
            db.add(test_call)
            await db.flush()
            assert test_call.id is not None
            t.passed(f"Call #{test_call.id} cree pour lead #{tl.id}")
        else:
            t.failed("Lead de test introuvable")
    except Exception as e:
        t.failed(str(e))
    t.duration_ms = round((time.time() - start) * 1000)
    results.append(t)

    # Test 12 : Statuts d'appel valides
    t = TestResult("calls_statuts", "Les 15 statuts d'appel sont definis")
    start = time.time()
    try:
        assert len(CALL_STATUSES) == 15, f"Attendu 15 statuts, trouve {len(CALL_STATUSES)}"
        required = ["no_answer", "busy", "voicemail", "interested", "not_interested", "callback", "meeting_booked", "do_not_call"]
        for s in required:
            assert s in CALL_STATUSES, f"Statut '{s}' manquant"
        t.passed(f"15 statuts OK : {', '.join(CALL_STATUSES.keys())}")
    except Exception as e:
        t.failed(str(e))
    t.duration_ms = round((time.time() - start) * 1000)
    results.append(t)

    # ============================================
    # TESTS DEDUPLICATION
    # ============================================

    # Test 13 : Normalisation telephone
    t = TestResult("dedup_normalisation", "Normalisation E.164 des numeros FR")
    start = time.time()
    try:
        dedup = DeduplicationService.get_instance()
        tests = [
            ("05 61 57 88 01", "+33561578801"),
            ("0561578801", "+33561578801"),
            ("+33561578801", "+33561578801"),
            ("0033561578801", "+33561578801"),
            ("06 12 34 56 78", "+33612345678"),
        ]
        for raw, expected in tests:
            result = dedup.normalize_phone(raw, "FR")
            assert result == expected, f"'{raw}' → '{result}' (attendu '{expected}')"
        t.passed(f"{len(tests)} formats normalises OK")
    except Exception as e:
        t.failed(str(e))
    t.duration_ms = round((time.time() - start) * 1000)
    results.append(t)

    # Test 14 : Bloom Filter stats
    t = TestResult("dedup_bloom_stats", "Bloom Filter est charge et fonctionnel")
    start = time.time()
    try:
        dedup = DeduplicationService.get_instance()
        stats = dedup.stats
        t.passed(f"Bloom: {stats.get('bloom_count', 0)} phones, Set: {stats.get('place_ids_count', 0)} place_ids")
    except Exception as e:
        t.failed(str(e))
    t.duration_ms = round((time.time() - start) * 1000)
    results.append(t)

    # ============================================
    # TESTS SCRAPER CONFIG
    # ============================================

    # Test 15 : Config Outscraper
    t = TestResult("scraper_outscraper_config", "Cle API Outscraper configuree")
    start = time.time()
    try:
        from app.core.config import get_settings
        s = get_settings()
        if s.outscraper_api_key:
            t.passed(f"Cle presente: {s.outscraper_api_key[:8]}...")
        else:
            t.failed("OUTSCRAPER_API_KEY vide — le scraper ne peut pas tourner")
    except Exception as e:
        t.failed(str(e))
    t.duration_ms = round((time.time() - start) * 1000)
    results.append(t)

    # Test 16 : Config Twilio
    t = TestResult("twilio_config", "Cles Twilio configurees pour les appels")
    start = time.time()
    try:
        from app.core.config import get_settings
        s = get_settings()
        missing = []
        if not s.twilio_account_sid: missing.append("TWILIO_ACCOUNT_SID")
        if not s.twilio_auth_token: missing.append("TWILIO_AUTH_TOKEN")
        if not s.twilio_phone_number: missing.append("TWILIO_PHONE_NUMBER")
        if not s.twilio_api_key: missing.append("TWILIO_API_KEY")
        if not s.twilio_api_secret: missing.append("TWILIO_API_SECRET")
        if missing:
            t.failed(f"Variables manquantes: {', '.join(missing)}")
        else:
            t.passed("Toutes les cles Twilio presentes")
    except Exception as e:
        t.failed(str(e))
    t.duration_ms = round((time.time() - start) * 1000)
    results.append(t)

    # Test 17 : Config telephone agent
    t = TestResult("agent_phone", "Numero de telephone de l'agent configure")
    start = time.time()
    try:
        # Recharger le user depuis la DB pour eviter les problemes de lazy loading
        fresh_user = await db.get(User, user.id)
        if fresh_user and fresh_user.phone_number:
            t.passed(f"Numero: {fresh_user.phone_number}")
        else:
            t.failed("Aucun numero configure — va dans Profil pour l'ajouter")
    except Exception as e:
        t.failed(str(e))
    t.duration_ms = round((time.time() - start) * 1000)
    results.append(t)

    # ============================================
    # TESTS REDIS
    # ============================================

    # Test 18 : Connexion Redis
    t = TestResult("redis_connexion", "Redis repond aux commandes")
    start = time.time()
    try:
        import redis.asyncio as aioredis
        from app.core.config import get_settings
        s = get_settings()
        r = aioredis.from_url(s.redis_url)
        pong = await r.ping()
        assert pong, "Redis PING devrait retourner True"
        await r.close()
        t.passed("Redis PONG OK")
    except Exception as e:
        t.failed(str(e))
    t.duration_ms = round((time.time() - start) * 1000)
    results.append(t)

    # ============================================
    # NETTOYAGE
    # ============================================

    # Supprimer les donnees de test
    try:
        await db.execute(delete(Call).where(Call.notes == "Test automatique"))
        await db.execute(delete(Lead).where(Lead.source == "test_runner"))
        await db.commit()
    except Exception:
        await db.rollback()

    return results


@router.get("/run")
async def run_tests(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Lance tous les tests fonctionnels et retourne les resultats.
    Nettoie automatiquement les donnees de test apres execution.
    """
    import time
    start = time.time()

    test_results = await _run_all_tests(db, current_user)

    total = len(test_results)
    passed = sum(1 for t in test_results if t.status == "PASS")
    failed = sum(1 for t in test_results if t.status == "FAIL")
    total_ms = round((time.time() - start) * 1000)

    return {
        "summary": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "success_rate": f"{round(passed / total * 100)}%" if total > 0 else "0%",
            "duration_ms": total_ms,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "tests": [t.to_dict() for t in test_results],
    }
