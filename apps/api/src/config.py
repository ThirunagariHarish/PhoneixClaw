"""
Phoenix v2 API configuration.

Uses pydantic-settings for all configuration from environment variables.
Reference: ImplementationPlan.md Section 1.4, Centralized Config.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """API service settings loaded from environment."""

    model_config = SettingsConfigDict(
        env_prefix="API_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8011
    database_url: str = ""
    redis_url: str = ""


class AuthSettings(BaseSettings):
    """JWT and auth (no API_ prefix to match .env.example)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60
    jwt_refresh_token_expire_days: int = 7


settings = Settings()
auth_settings = AuthSettings()
