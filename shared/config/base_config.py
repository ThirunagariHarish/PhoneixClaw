import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


@dataclass
class KafkaConfig:
    bootstrap_servers: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    schema_registry_url: str = os.getenv("SCHEMA_REGISTRY_URL", "http://localhost:8081")
    consumer_group: str = os.getenv("KAFKA_CONSUMER_GROUP", "default-group")
    auto_offset_reset: str = os.getenv("KAFKA_AUTO_OFFSET_RESET", "earliest")


@dataclass
class DatabaseConfig:
    url: str = os.getenv("DATABASE_URL", "postgresql+asyncpg://phoenixtrader:localdev@localhost:5432/phoenixtrader")


@dataclass
class RedisConfig:
    url: str = os.getenv("REDIS_URL", "redis://localhost:6379")


@dataclass
class AuthConfig:
    secret_key: str = os.getenv("JWT_SECRET_KEY", "dev-secret-key-change-in-production")
    algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")
    access_token_expire_minutes: int = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
    refresh_token_expire_days: int = int(os.getenv("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "7"))


@dataclass
class CredentialEncryptionConfig:
    key: str = os.getenv("CREDENTIAL_ENCRYPTION_KEY", "")


@dataclass
class BrokerConfig:
    api_key: str = os.getenv("ALPACA_API_KEY", "")
    secret_key: str = os.getenv("ALPACA_SECRET_KEY", "")
    base_url: str = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    paper: bool = os.getenv("ALPACA_PAPER", "true").lower() == "true"


@dataclass
class RiskConfig:
    max_position_size: int = int(os.getenv("MAX_POSITION_SIZE", "10"))
    max_total_contracts: int = int(os.getenv("MAX_TOTAL_CONTRACTS", "100"))
    max_notional_value: float = float(os.getenv("MAX_NOTIONAL_VALUE", "50000.0"))
    max_daily_loss: float = float(os.getenv("MAX_DAILY_LOSS", "1000.0"))
    ticker_blacklist: list[str] = field(
        default_factory=lambda: [t.strip() for t in os.getenv("TICKER_BLACKLIST", "").split(",") if t.strip()]
    )
    enable_trading: bool = os.getenv("ENABLE_TRADING", "true").lower() == "true"
    dry_run_mode: bool = os.getenv("DRY_RUN_MODE", "false").lower() == "true"


@dataclass
class ExecutionConfig:
    buffer_percentage: float = float(os.getenv("BUFFER_PERCENTAGE", "0.15"))
    buffer_max_percentage: float = float(os.getenv("BUFFER_MAX_PERCENTAGE", "0.30"))
    buffer_min_price: float = float(os.getenv("BUFFER_MIN_PRICE", "0.01"))
    buffer_overrides: str = os.getenv("BUFFER_OVERRIDES", "{}")
    default_profit_target: float = float(os.getenv("DEFAULT_PROFIT_TARGET", "0.30"))
    default_stop_loss: float = float(os.getenv("DEFAULT_STOP_LOSS", "0.20"))


@dataclass
class MonitorConfig:
    poll_interval_seconds: int = int(os.getenv("MONITOR_POLL_INTERVAL_SECONDS", "5"))
    trailing_stop_enabled: bool = os.getenv("TRAILING_STOP_ENABLED", "false").lower() == "true"
    trailing_stop_offset: float = float(os.getenv("TRAILING_STOP_OFFSET", "0.10"))


@dataclass
class GatewayConfig:
    approval_mode: str = os.getenv("APPROVAL_MODE", "auto")
    approval_timeout_seconds: int = int(os.getenv("APPROVAL_TIMEOUT_SECONDS", "300"))


@dataclass
class SmtpConfig:
    host: str = os.getenv("SMTP_HOST", "")
    port: int = int(os.getenv("SMTP_PORT", "587"))
    user: str = os.getenv("SMTP_USER", "")
    password: str = os.getenv("SMTP_PASSWORD", "")
    from_email: str = os.getenv("SMTP_FROM_EMAIL", "")
    use_tls: bool = os.getenv("SMTP_USE_TLS", "true").lower() == "true"


@dataclass
class AppConfig:
    kafka: KafkaConfig = field(default_factory=KafkaConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)
    credential_encryption: CredentialEncryptionConfig = field(default_factory=CredentialEncryptionConfig)
    broker: BrokerConfig = field(default_factory=BrokerConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    monitor: MonitorConfig = field(default_factory=MonitorConfig)
    gateway: GatewayConfig = field(default_factory=GatewayConfig)
    smtp: SmtpConfig = field(default_factory=SmtpConfig)
    log_level: str = os.getenv("LOG_LEVEL", "INFO")


config = AppConfig()
