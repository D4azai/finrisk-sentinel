import asyncio
import logging
import random
import time
from typing import AsyncGenerator, Callable, Any
from services.market_data.engine.circuit_breaker import CircuitBreaker, CircuitState

logger = logging.getLogger("market_data.connection_manager")


class ResilientConnectionManager:
    def __init__(
            self,
            base_delay: float = 1.0,
            max_delay: float = 60.0,
            min_healthy_duration_sec: float = 10.0,
            circuit_breaker: CircuitBreaker | None = None
    ):
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.min_healthy_duration = min_healthy_duration_sec
        self.circuit_breaker = circuit_breaker or CircuitBreaker()

    def _calculate_backoff(self, attempt: int) -> float:
        """Calculates exponential backoff with full jitter to avoid thundering herd."""
        exponential = min(self.max_delay, self.base_delay * (2 ** (attempt - 1)))
        return random.uniform(self.base_delay, exponential)

    async def stream_with_retry(
            self,
            stream_factory: Callable[[], AsyncGenerator[Any, None]]
    ) -> AsyncGenerator[Any, None]:
        attempt = 0

        while True:
            if not self.circuit_breaker.can_execute():
                wait_time = self.circuit_breaker.get_remaining_recovery_time()
                logger.warning(f"Circuit breaker is OPEN. Pausing reconnect attempts for {wait_time:.1f}s...")
                await asyncio.sleep(wait_time + 0.1)
                continue

            attempt += 1
            connected_at = time.time()
            logger.info(f"Initiating stream connection (Attempt {attempt})...")

            try:
                async for frame in stream_factory():
                    # Only reset retry attempts if connection stayed alive past min threshold
                    if attempt > 0 and (time.time() - connected_at) >= self.min_healthy_duration:
                        attempt = 0

                    self.circuit_breaker.record_success()
                    yield frame

            except asyncio.CancelledError:
                logger.info("Stream cancelled by task runner.")
                raise
            except Exception as exc:
                self.circuit_breaker.record_failure()

                # Check if circuit opened after this failure
                if self.circuit_breaker.state == CircuitState.OPEN:
                    continue

                delay = self._calculate_backoff(attempt)
                logger.error(f"Stream error: {exc}. Retrying in {delay:.2f}s (Attempt {attempt})...")
                await asyncio.sleep(delay)