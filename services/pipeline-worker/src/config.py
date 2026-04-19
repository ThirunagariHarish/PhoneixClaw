"""Pipeline Worker configuration via pydantic-settings."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    REDIS_URL: str = "redis://localhost:6379"
    DATABASE_URL: str = "postgresql+asyncpg://phoenixtrader:localdev@localhost:5432/phoenixtrader"
    INFERENCE_SERVICE_URL: str = "http://localhost:8045"
    BROKER_GATEWAY_URL: str = "http://localhost:8030"
    FEATURE_PIPELINE_URL: str = "http://localhost:8050"
    PIPELINE_WORKER_PORT: int = 8055
    MAX_WORKERS: int = 50
    HEARTBEAT_INTERVAL_SEC: int = 30
    API_BASE_URL: str = "http://localhost:8011"

    model_config = {"env_prefix": "", "case_sensitive": True}


settings = Settings()
