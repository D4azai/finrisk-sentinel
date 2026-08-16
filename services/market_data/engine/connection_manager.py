import asyncio
import logging
from typing import AsyncGenerator, Callable, Any
from services.market_data.engine.circuit_breaker import CircuitBreaker, CircuitBreakerOpenException

logger = logging.getLogger("market_data.connection_manager")

class ResilientConnectionManager:
    def __init__(
        self,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        circuit_breaker: CircuitBreaker | None = None
    ):
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.circuit_breaker = circuit_breaker or CircuitBreaker()

    async def stream_with_retry(
        self,
        stream_factory: Callable[[], AsyncGenerator[Any, None]]
    ) -> AsyncGenerator[Any, None]:
        attempt = 0
        while True:
            if not self.circuit_breaker.can_execute():
                logger.error("Circuit breaker is OPEN. Delaying connection attempt...")
                await asyncio.sleep(self.base_delay)
                continue

            try:
                logger.info("Initiating stream connection...")
                attempt += 1
                async for frame in stream_factory():
                    attempt = 0  # Reset backoff on successful frame receipt
                    self.circuit_breaker.record_success()
                    yield frame
            except asyncio.CancelledError:
                logger.info("Stream cancelled by task runner.")
                raise
            except Exception as exc:
                self.circuit_breaker.record_failure()
                delay = min(self.base_delay * (2 ** (attempt - 1)), self.max_delay)
                logger.error(f"Stream error: {exc}. Retrying in {delay:.2f}s (Attempt {attempt})...")
                await asyncio.sleep(delay)