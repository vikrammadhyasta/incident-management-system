from pydantic_settings import BaseSettings
from pydantic import ConfigDict
from typing import Optional


class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env", case_sensitive=True)
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://ims_user:ims_pass@localhost:5432/ims_db"
    MONGODB_URL: str = "mongodb://ims_user:ims_pass@localhost:27017/ims_signals?authSource=admin"
    REDIS_URL: str = "redis://localhost:6379/0"

    # Signal processing
    SIGNAL_BUFFER_SIZE: int = 50_000          # Max in-memory queue depth
    DEBOUNCE_WINDOW_SECONDS: int = 10          # Dedup window per component
    DEBOUNCE_THRESHOLD: int = 100              # Signals before creating 1 work item
    RATE_LIMIT_PER_SECOND: int = 15_000        # Ingestion rate cap

    # Workers
    SIGNAL_WORKER_CONCURRENCY: int = 8         # Async worker coroutines
    METRICS_INTERVAL_SECONDS: int = 5          # Console throughput print interval

    # Auth (bonus: simple API key)
    API_KEY: Optional[str] = "ims-dev-key-change-in-prod"

    # App
    LOG_LEVEL: str = "INFO"
    ENVIRONMENT: str = "development"


settings = Settings()
