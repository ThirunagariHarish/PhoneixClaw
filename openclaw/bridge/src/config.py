"""
Bridge Service configuration. M1.7.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class BridgeSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    BRIDGE_TOKEN: str = "change-me"
    AGENTS_ROOT: str = "/tmp/phoenix-bridge-agents"
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = ""
    MINIO_SECRET_KEY: str = ""
    MINIO_BUCKET_SKILLS: str = "phoenix-skills"
    MINIO_USE_SSL: bool = False


settings = BridgeSettings()
