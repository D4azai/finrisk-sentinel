from pydantic_settings import BaseSettings, SettingsConfigDict


class MarketDataSettings(BaseSettings):
    exchange_name: str = "binance"
    symbols: list[str] = ["btcusdt", "ethusdt"]
    zmq_pub_endpoint: str = "tcp://0.0.0.0:5555"
    max_reconnect_attempts: int = 10
    base_reconnect_delay_sec: float = 1.0
    max_reconnect_delay_sec: float = 60.0
    zmq_public_key: str | None = None
    zmq_secret_key: str | None = None

    model_config = SettingsConfigDict(env_prefix="MARKET_DATA_", env_file=".env", extra="ignore")


settings = MarketDataSettings()