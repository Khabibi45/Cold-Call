"""
Tests d'integration — Endpoints appels (/api/calls).
Teste la creation, la mise a jour et les callbacks.
"""

from datetime import datetime, timezone, timedelta

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead import Lead
from app.models.call import Call


@pytest.mark.asyncio
class TestCreateCall:
    """Tests de l'endpoint POST /api/calls/."""

    async def test_creer_appel_statut_valide(self, client: AsyncClient, test_lead):
        """Creer un appel avec un statut valide retourne 200."""
        response = await client.post("/api/calls/", json={
            "lead_id": test_lead.id,
            "status": "no_answer",
            "duration_seconds": 15.5,
            "notes": "Pas de reponse, reessayer demain.",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "no_answer"
        assert data["lead_id"] == test_lead.id
        assert "id" in data

    async def test_creer_appel_statut_invalide(self, client: AsyncClient, test_lead):
        """Creer un appel avec un statut inconnu retourne 400."""
        response = await client.post("/api/calls/", json={
            "lead_id": test_lead.id,
            "status": "statut_inexistant",
        })
        assert response.status_code == 400

    async def test_creer_appel_lead_inexistant(self, client: AsyncClient):
        """Creer un appel pour un lead qui n'existe pas retourne 404."""
        response = await client.post("/api/calls/", json={
            "lead_id": 99999,
            "status": "no_answer",
        })
        assert response.status_code == 404

    async def test_creer_appel_interested(self, client: AsyncClient, test_lead):
        """Creer un appel avec statut 'interested' fonctionne."""
        response = await client.post("/api/calls/", json={
            "lead_id": test_lead.id,
            "status": "interested",
            "notes": "Le gerant est interesse, rappeler lundi.",
            "contact_email": "gerant@boulangerie.fr",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "interested"

    async def test_creer_appel_avec_callback(self, client: AsyncClient, test_lead):
        """Creer un appel avec date de rappel planifie."""
        callback_date = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        response = await client.post("/api/calls/", json={
            "lead_id": test_lead.id,
            "status": "callback",
            "callback_at": callback_date,
            "notes": "Rappeler mercredi matin.",
        })
        assert response.status_code == 200
        assert response.json()["status"] == "callback"


@pytest.mark.asyncio
class TestUpdateCall:
    """Tests de l'endpoint PATCH /api/calls/{id}."""

    async def test_update_statut(self, client: AsyncClient, db_session: AsyncSession, test_lead):
        """Mettre a jour le statut d'un appel existant."""
        # Creer un appel d'abord
        call = Call(
            lead_id=test_lead.id,
            status="no_answer",
            duration_seconds=0,
            started_at=datetime.now(timezone.utc),
        )
        db_session.add(call)
        await db_session.commit()
        await db_session.refresh(call)

        # Mettre a jour le statut
        response = await client.patch(f"/api/calls/{call.id}", json={
            "status": "interested",
            "notes": "Finalement interesse apres rappel.",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "interested"
        assert data["updated"] is True

    async def test_update_appel_inexistant(self, client: AsyncClient):
        """Mettre a jour un appel inexistant retourne 404."""
        response = await client.patch("/api/calls/99999", json={
            "status": "interested",
        })
        assert response.status_code == 404

    async def test_update_statut_invalide(self, client: AsyncClient, db_session: AsyncSession, test_lead):
        """Mettre a jour avec un statut invalide retourne 400."""
        call = Call(
            lead_id=test_lead.id,
            status="no_answer",
            started_at=datetime.now(timezone.utc),
        )
        db_session.add(call)
        await db_session.commit()
        await db_session.refresh(call)

        response = await client.patch(f"/api/calls/{call.id}", json={
            "status": "statut_bidon",
        })
        assert response.status_code == 400


@pytest.mark.asyncio
class TestCallbacks:
    """Tests de l'endpoint GET /api/calls/callbacks."""

    async def test_callbacks_vide(self, client: AsyncClient):
        """Sans callbacks planifies, la liste est vide."""
        response = await client.get("/api/calls/callbacks")
        assert response.status_code == 200
        assert response.json() == []

    async def test_callbacks_futur(self, client: AsyncClient, db_session: AsyncSession, test_lead):
        """Un callback dans le futur apparait dans la liste."""
        callback_date = datetime.now(timezone.utc) + timedelta(days=1)
        call = Call(
            lead_id=test_lead.id,
            status="callback",
            callback_at=callback_date,
            notes="Rappel prevu demain",
            started_at=datetime.now(timezone.utc),
        )
        db_session.add(call)
        await db_session.commit()

        response = await client.get("/api/calls/callbacks")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        assert data[0]["notes"] == "Rappel prevu demain"

    async def test_callbacks_passe_non_inclus(self, client: AsyncClient, db_session: AsyncSession, test_lead):
        """Un callback dans le passe n'apparait pas dans la liste."""
        past_date = datetime.now(timezone.utc) - timedelta(days=1)
        call = Call(
            lead_id=test_lead.id,
            status="callback",
            callback_at=past_date,
            started_at=datetime.now(timezone.utc),
        )
        db_session.add(call)
        await db_session.commit()

        response = await client.get("/api/calls/callbacks")
        assert response.status_code == 200
        # Le callback passe ne doit pas apparaitre
        assert len(response.json()) == 0
