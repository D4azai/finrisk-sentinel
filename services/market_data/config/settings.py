from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class MarketDataSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MARKET_DATA_", env_file=".env", extra="ignore")
    exchange_name: str = "binance"
    symbols: list[str] = Field(default_factory=lambda: ["btcusdt", "ethusdt"])
    max_reconnect_attempts: int = Field(default=0, ge=0)
    base_reconnect_delay_sec: float = Field(default=1, gt=0)
    max_reconnect_delay_sec: float = Field(default=60, gt=0)
    idle_timeout_sec: float = Field(default=30, gt=0)

    @field_validator("symbols")
    @classmethod
    def valid_symbols(cls, values):
        if not values or len(values) > 100:
            raise ValueError("Configure between 1 and 100 symbols per collector")
        if any(not s.isascii() or not s.isalnum() or len(s) > 30 for s in values):
            raise ValueError("Symbols must be short ASCII alphanumeric identifiers")
        return sorted(set(s.lower() for s in values))

    @model_validator(mode="after")
    def valid_delays(self):
        if self.max_reconnect_delay_sec < self.base_reconnect_delay_sec:
            raise ValueError("Maximum delay must be at least base delay")
        return self
