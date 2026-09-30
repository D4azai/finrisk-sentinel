import asyncio
import logging
import random
from contextlib import aclosing

from services.market_data.engine.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)


class ResilientConnectionManager:
    def __init__(
        self,
        base_delay=1.0,
        max_delay=60.0,
        circuit_breaker=None,
        max_attempts=0,
        idle_timeout=30.0,
        on_disconnect=None,
    ):
        if base_delay <= 0 or max_delay < base_delay or idle_timeout <= 0 or max_attempts < 0:
            raise ValueError("Invalid retry settings")
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self.max_attempts = max_attempts
        self.idle_timeout = idle_timeout
        self.on_disconnect = on_disconnect

    async def stream_with_retry(self, stream_factory):
        failures = 0
        while True:
            if not self.circuit_breaker.can_execute():
                await asyncio.sleep(self.base_delay)
                continue
            try:
                async with aclosing(stream_factory()) as stream:
                    while True:
                        # Timeout only the upstream read, never downstream durable writes.
                        async with asyncio.timeout(self.idle_timeout):
                            frame = await anext(stream)
                        failures = 0
                        self.circuit_breaker.record_success()
                        yield frame
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                failures += 1
                self.circuit_breaker.record_failure()
                if self.on_disconnect:
                    await self.on_disconnect(type(exc).__name__)
                if self.max_attempts and failures >= self.max_attempts:
                    raise RuntimeError("Reconnect attempt limit reached") from None
                ceiling = min(self.max_delay, self.base_delay * 2 ** min(failures - 1, 20))
                delay = random.uniform(ceiling / 2, ceiling)
                logger.warning(
                    "Feed disconnected; reconnecting", extra={"error_type": type(exc).__name__}
                )
                await asyncio.sleep(delay)
