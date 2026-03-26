"""
Tests d'integration — Endpoints leads (/api/leads).
Teste le listing, la creation, les filtres et la pagination.
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead import Lead


@pytest.mark.asyncio
class TestListLeads:
    """Tests de l'endpoint GET /api/leads/."""

    async def test_liste_vide(self, client: AsyncClient, auth_headers):
        """Sans leads en base, la liste retourne un tableau vide."""
        response = await client.get("/api/leads/", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["data"] == []

    async def test_liste_avec_leads(self, client: AsyncClient, auth_headers, test_lead):
        """Avec un lead en base, il apparait dans la liste."""
        response = await client.get("/api/leads/", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        assert any(l["business_name"] == "Boulangerie Test" for l in data["data"])

    async def test_liste_non_authentifie(self, client: AsyncClient):
        """Sans token, l'acces aux leads est refuse (401)."""
        response = await client.get("/api/leads/")
        assert response.status_code == 401


@pytest.mark.asyncio
class TestFiltres:
    """Tests des filtres sur les leads."""

    async def test_filtre_par_ville(self, client: AsyncClient, auth_headers, db_session: AsyncSession):
        """Le filtre city retourne uniquement les leads de la ville demandee."""
        # Creer 2 leads dans des villes differentes
        lead_toulouse = Lead(business_name="Resto Toulouse", city="Toulouse", category="Restaurant", source="google_maps", has_website=False, lead_score=50)
        lead_paris = Lead(business_name="Resto Paris", city="Paris", category="Restaurant", source="google_maps", has_website=False, lead_score=50)
        db_session.add_all([lead_toulouse, lead_paris])
        await db_session.commit()

        response = await client.get("/api/leads/?city=Toulouse", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        # Tous les resultats doivent contenir "Toulouse"
        for lead in data["data"]:
            assert "toulouse" in lead["city"].lower()

    async def test_filtre_par_categorie(self, client: AsyncClient, auth_headers, db_session: AsyncSession):
        """Le filtre category retourne uniquement les leads de la categorie demandee."""
        lead_boulangerie = Lead(business_name="Pain d'Or", city="Lyon", category="Boulangerie", source="google_maps", has_website=False, lead_score=60)
        lead_plombier = Lead(business_name="Plombier Express", city="Lyon", category="Plombier", source="google_maps", has_website=False, lead_score=40)
        db_session.add_all([lead_boulangerie, lead_plombier])
        await db_session.commit()

        response = await client.get("/api/leads/?category=Boulangerie", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        for lead in data["data"]:
            assert "boulangerie" in lead["category"].lower()


@pytest.mark.asyncio
class TestPagination:
    """Tests de la pagination des leads."""

    async def test_pagination_page_1(self, client: AsyncClient, auth_headers, db_session: AsyncSession):
        """La premiere page retourne le bon nombre de resultats."""
        # Creer 5 leads
        leads = [
            Lead(business_name=f"Entreprise {i}", city="Marseille", category="Test", source="google_maps", has_website=False, lead_score=i * 10)
            for i in range(5)
        ]
        db_session.add_all(leads)
        await db_session.commit()

        response = await client.get("/api/leads/?page=1&per_page=3", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 3
        assert data["total"] == 5
        assert data["pages"] == 2

    async def test_pagination_page_2(self, client: AsyncClient, auth_headers, db_session: AsyncSession):
        """La deuxieme page retourne le reste des resultats."""
        leads = [
            Lead(business_name=f"Societe {i}", city="Bordeaux", category="Test", source="google_maps", has_website=False, lead_score=i * 10)
            for i in range(5)
        ]
        db_session.add_all(leads)
        await db_session.commit()

        response = await client.get("/api/leads/?page=2&per_page=3", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 2  # 5 leads, page 2 de 3 = 2 restants
