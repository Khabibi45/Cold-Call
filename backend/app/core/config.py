"""
Configuration centralisee de l'application.
Toutes les variables d'environnement sont validees ici au demarrage.
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache


class Settings(BaseSettings):
    """Configuration principale — validee par Pydantic au demarrage."""

    # --- App ---
    app_env: str = Field(default="development")
    app_debug: bool = Field(default=False)
    app_url: str = Field(default="http://localhost:8092")
    cors_origins: str = Field(default="http://localhost:8092")

    # --- Base de donnees ---
    database_url: str = Field(default="postgresql+asyncpg://coldcall:coldcall@db:5432/coldcall")

    # --- Redis ---
    redis_url: str = Field(default="redis://redis:6379/0")

    # --- JWT ---
    jwt_secret_key: str = Field(default="dev-secret-change-in-production")
    jwt_algorithm: str = Field(default="HS256")
    jwt_access_token_expire_minutes: int = Field(default=15)
    jwt_refresh_token_expire_days: int = Field(default=30)

    # --- OAuth2 ---
    google_client_id: str = Field(default="")
    google_client_secret: str = Field(default="")
    google_redirect_uri: str = Field(default="http://localhost:8092/api/auth/google/callback")
    github_client_id: str = Field(default="")
    github_client_secret: str = Field(default="")
    github_redirect_uri: str = Field(default="http://localhost:8092/api/auth/github/callback")

    # --- Twilio ---
    twilio_account_sid: str = Field(default="")
    twilio_auth_token: str = Field(default="")
    twilio_phone_number: str = Field(default="")
    twilio_twiml_app_sid: str = Field(default="")
    twilio_api_key: str = Field(default="")
    twilio_api_secret: str = Field(default="")

    # --- Scraping ---
    outscraper_api_key: str = Field(default="")
    foursquare_api_key: str = Field(default="")

    # --- Stripe ---
    stripe_secret_key: str = Field(default="")
    stripe_publishable_key: str = Field(default="")
    stripe_webhook_secret: str = Field(default="")

    # --- Sentry ---
    sentry_dsn: str = Field(default="")

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    """Singleton des settings — cache en memoire."""
    return Settings()
