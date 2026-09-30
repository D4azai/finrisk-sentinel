import ssl
from typing import Literal
from urllib.parse import parse_qs, urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class InfrastructureSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FINRISK_", env_file=".env", extra="ignore")
    environment: Literal["development", "test", "production"] = "production"
    allow_insecure_local: bool = False
    database_url: SecretStr
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_security_protocol: Literal["PLAINTEXT", "SASL_SSL"] = "SASL_SSL"
    kafka_username: str | None = None
    kafka_password: SecretStr | None = None
    kafka_ca_file: str | None = None
    kafka_sasl_mechanism: Literal["SCRAM-SHA-256", "SCRAM-SHA-512"] = "SCRAM-SHA-512"
    raw_topic: str = "market.raw.v1"
    clean_topic: str = "market.trades.v1"
    quality_topic: str = "market.quality.v1"
    quarantine_topic: str = "market.quarantine.v1"
    max_payload_bytes: int = Field(default=65536, ge=1024, le=65536)
    health_host: str = "0.0.0.0"
    health_port: int = Field(default=8080, ge=1, le=65535)
    readiness_timeout_sec: float = Field(default=30, gt=0)
    publish_timeout_sec: float = Field(default=15, gt=0, le=60)
    max_outbox_pending: int = Field(default=100000, ge=1)

    @model_validator(mode="after")
    def secure_configuration(self):
        local = self.environment != "production" and self.allow_insecure_local
        if self.kafka_security_protocol == "PLAINTEXT":
            if not local:
                raise ValueError("Plaintext Kafka requires explicit non-production local mode")
            if self.kafka_username or self.kafka_password:
                raise ValueError("Kafka credentials cannot be used with plaintext mode")
        elif not self.kafka_username or not self.kafka_password:
            raise ValueError("SASL_SSL requires username and password")
        url = urlsplit(self.database_url.get_secret_value())
        if url.scheme not in {"postgres", "postgresql"} or not url.hostname:
            raise ValueError("A PostgreSQL connection URL is required")
        if not local and parse_qs(url.query).get("sslmode") != ["verify-full"]:
            raise ValueError("PostgreSQL requires sslmode=verify-full outside explicit local mode")
        if len({self.raw_topic, self.clean_topic, self.quality_topic, self.quarantine_topic}) != 4:
            raise ValueError("Pipeline topics must be distinct")
        return self

    def kafka_options(self):
        options = {
            "bootstrap_servers": self.kafka_bootstrap_servers,
            "security_protocol": self.kafka_security_protocol,
        }
        if self.kafka_security_protocol == "SASL_SSL":
            options.update(
                ssl_context=ssl.create_default_context(cafile=self.kafka_ca_file),
                sasl_mechanism=self.kafka_sasl_mechanism,
                sasl_plain_username=self.kafka_username,
                sasl_plain_password=self.kafka_password.get_secret_value(),
            )
        return options
