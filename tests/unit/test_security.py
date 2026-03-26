"""
Tests unitaires — Module securite (hashing Argon2, tokens JWT).
Verifie le cycle complet : creation, verification, expiration.
"""

import time
from datetime import timedelta

import pytest

from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
)


class TestPasswordHashing:
    """Tests du hashing Argon2 pour les mots de passe."""

    def test_hash_password_retourne_hash_different(self):
        """Le hash ne doit jamais etre egal au mot de passe en clair."""
        password = "MonMotDePasse123!"
        hashed = hash_password(password)
        assert hashed != password
        assert len(hashed) > 0

    def test_hash_password_unique_a_chaque_appel(self):
        """Deux appels avec le meme mot de passe donnent des hash differents (salt aleatoire)."""
        password = "MotDePasse"
        hash1 = hash_password(password)
        hash2 = hash_password(password)
        assert hash1 != hash2

    def test_verify_password_correct(self):
        """verify_password retourne True avec le bon mot de passe."""
        password = "SuperSecret42"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_verify_password_incorrect(self):
        """verify_password retourne False avec un mauvais mot de passe."""
        hashed = hash_password("BonMotDePasse")
        assert verify_password("MauvaisMotDePasse", hashed) is False

    def test_verify_password_chaine_vide(self):
        """verify_password retourne False pour une chaine vide."""
        hashed = hash_password("password")
        assert verify_password("", hashed) is False


class TestAccessToken:
    """Tests du JWT access token."""

    def test_create_et_decode_access_token(self):
        """Un access token cree doit pouvoir etre decode avec les bonnes donnees."""
        data = {"sub": "42", "email": "user@test.com"}
        token = create_access_token(data)

        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == "42"
        assert payload["email"] == "user@test.com"
        assert payload["type"] == "access"

    def test_access_token_contient_expiration(self):
        """Le payload du token doit contenir un champ 'exp'."""
        token = create_access_token({"sub": "1"})
        payload = decode_token(token)
        assert "exp" in payload

    def test_access_token_expire(self):
        """Un token avec une duree negative doit etre considere comme expire."""
        # Creer un token deja expire (duree de -1 seconde)
        token = create_access_token({"sub": "1"}, expires_delta=timedelta(seconds=-1))
        payload = decode_token(token)
        assert payload is None  # Token expire -> None

    def test_access_token_duree_personnalisee(self):
        """On peut specifier une duree personnalisee pour le token."""
        token = create_access_token({"sub": "1"}, expires_delta=timedelta(hours=2))
        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == "1"


class TestRefreshToken:
    """Tests du JWT refresh token."""

    def test_create_et_decode_refresh_token(self):
        """Un refresh token cree doit pouvoir etre decode correctement."""
        data = {"sub": "99", "email": "admin@test.com"}
        token = create_refresh_token(data)

        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == "99"
        assert payload["email"] == "admin@test.com"
        assert payload["type"] == "refresh"

    def test_refresh_token_type_different_access(self):
        """Le type du refresh token est 'refresh', pas 'access'."""
        data = {"sub": "1"}
        access = create_access_token(data)
        refresh = create_refresh_token(data)

        access_payload = decode_token(access)
        refresh_payload = decode_token(refresh)

        assert access_payload["type"] == "access"
        assert refresh_payload["type"] == "refresh"


class TestDecodeToken:
    """Tests de la fonction decode_token avec tokens invalides."""

    def test_decode_token_invalide(self):
        """Un token malformed retourne None."""
        assert decode_token("ceci.nest.pas.un.jwt") is None

    def test_decode_token_chaine_vide(self):
        """Une chaine vide retourne None."""
        assert decode_token("") is None

    def test_decode_token_mauvaise_signature(self):
        """Un token signe avec une autre cle retourne None."""
        from jose import jwt
        fake_token = jwt.encode({"sub": "1"}, "mauvaise-cle", algorithm="HS256")
        assert decode_token(fake_token) is None
