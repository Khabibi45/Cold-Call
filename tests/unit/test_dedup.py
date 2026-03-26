"""
Tests unitaires — Service de deduplication (normalisation telephone, Bloom Filter).
Verifie les differents formats de numeros francais et le comportement du filtre.
"""

import pytest

from app.services.dedup import DeduplicationService


class TestNormalizePhone:
    """Tests de la normalisation des numeros de telephone francais."""

    def test_format_local_espaces(self):
        """Format francais standard avec espaces : 05 61 00 00 00."""
        result = DeduplicationService.normalize_phone("05 61 00 00 00")
        assert result == "+33561000000"

    def test_format_local_sans_espaces(self):
        """Format francais compact : 0561000000."""
        result = DeduplicationService.normalize_phone("0561000000")
        assert result == "+33561000000"

    def test_format_local_avec_points(self):
        """Format francais avec points : 05.61.00.00.00."""
        result = DeduplicationService.normalize_phone("05.61.00.00.00")
        assert result == "+33561000000"

    def test_format_local_avec_tirets(self):
        """Format francais avec tirets : 05-61-00-00-00."""
        result = DeduplicationService.normalize_phone("05-61-00-00-00")
        assert result == "+33561000000"

    def test_format_international_plus33(self):
        """Format international +33 : +33561000000."""
        result = DeduplicationService.normalize_phone("+33561000000")
        assert result == "+33561000000"

    def test_format_international_plus33_espaces(self):
        """Format international avec espaces : +33 5 61 00 00 00."""
        result = DeduplicationService.normalize_phone("+33 5 61 00 00 00")
        assert result == "+33561000000"

    def test_format_international_0033(self):
        """Format international 0033 : 0033561000000."""
        result = DeduplicationService.normalize_phone("0033561000000")
        assert result == "+33561000000"

    def test_format_international_0033_espaces(self):
        """Format 0033 avec espaces : 0033 5 61 00 00 00."""
        result = DeduplicationService.normalize_phone("0033 5 61 00 00 00")
        assert result == "+33561000000"

    def test_numero_mobile(self):
        """Numero mobile francais : 06 12 34 56 78."""
        result = DeduplicationService.normalize_phone("06 12 34 56 78")
        assert result == "+33612345678"

    def test_numero_invalide(self):
        """Un numero invalide retourne None."""
        result = DeduplicationService.normalize_phone("12345")
        assert result is None

    def test_chaine_vide(self):
        """Une chaine vide retourne None."""
        result = DeduplicationService.normalize_phone("")
        assert result is None

    def test_none_like_chaine(self):
        """Caracteres non-numeriques retournent None."""
        result = DeduplicationService.normalize_phone("pas un numero")
        assert result is None


class TestBloomFilter:
    """Tests du Bloom Filter et du mecanisme de deduplication."""

    def setup_method(self):
        """Reinitialise le service avant chaque test (isolation)."""
        # Creer une nouvelle instance (pas le singleton) pour isoler les tests
        self.dedup = DeduplicationService()

    def test_is_duplicate_vide(self):
        """Un Bloom Filter vide ne contient aucun doublon."""
        assert self.dedup.is_duplicate(phone_e164="+33561000000") is False

    def test_register_puis_is_duplicate(self):
        """Apres register, is_duplicate retourne True pour le meme numero."""
        self.dedup.register(phone_e164="+33561000000", place_id=None)
        assert self.dedup.is_duplicate(phone_e164="+33561000000") is True

    def test_register_place_id(self):
        """Le Set place_id detecte les doublons correctement."""
        self.dedup.register(phone_e164=None, place_id="ChIJ123456")
        assert self.dedup.is_duplicate(place_id="ChIJ123456") is True

    def test_not_duplicate_different_phone(self):
        """Un numero different n'est pas un doublon."""
        self.dedup.register(phone_e164="+33561000000", place_id=None)
        assert self.dedup.is_duplicate(phone_e164="+33561999999") is False

    def test_not_duplicate_different_place_id(self):
        """Un place_id different n'est pas un doublon."""
        self.dedup.register(phone_e164=None, place_id="ChIJ111")
        assert self.dedup.is_duplicate(place_id="ChIJ999") is False

    def test_register_both(self):
        """On peut enregistrer un phone ET un place_id en meme temps."""
        self.dedup.register(phone_e164="+33561000000", place_id="ChIJ_ABC")
        assert self.dedup.is_duplicate(phone_e164="+33561000000") is True
        assert self.dedup.is_duplicate(place_id="ChIJ_ABC") is True

    def test_stats_apres_register(self):
        """Les stats refletent le nombre d'enregistrements."""
        self.dedup.register(phone_e164="+33561000001", place_id="P1")
        self.dedup.register(phone_e164="+33561000002", place_id="P2")
        stats = self.dedup.stats
        assert stats["bloom_count"] == 2
        assert stats["place_id_count"] == 2

    def test_is_duplicate_none_values(self):
        """Passer None ne declenche pas de faux positif."""
        self.dedup.register(phone_e164="+33561000000", place_id="ChIJ_X")
        assert self.dedup.is_duplicate(phone_e164=None, place_id=None) is False
