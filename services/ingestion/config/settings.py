from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class IngestionSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="INGESTION_", env_file=".env", extra="ignore")
    consumer_group: str = "finrisk-ingestion-v1"
    max_allowed_staleness_sec: float = Field(default=5, gt=0)
    max_future_skew_sec: float = Field(default=2, ge=0)
