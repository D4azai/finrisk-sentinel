from pydantic_settings import BaseSettings, SettingsConfigDict


class IngestionSettings(BaseSettings):
        zmq_sub_endpoint: str = "tcp://market_data:5555"
        zmq_clean_pub_endpoint: str = "tcp://0.0.0.0:5556"
        subscriptions: list[str] = [""]  # Subscribe to all topics by default
        max_allowed_staleness_sec: float = 5.0
        market_data_public_key: str | None = None
        zmq_public_key: str | None = None
        zmq_secret_key: str | None = None
        model_config = SettingsConfigDict(env_prefix="INGESTION_", env_file=".env", extra="ignore")


settings = IngestionSettings()