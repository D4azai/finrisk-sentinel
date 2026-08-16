import time
import logging

logger = logging.getLogger("market_data.circuit_breaker")

class CircuitBreakerOpenException(Exception):
    """Raised when an operation is attempted while circuit is open."""

class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 30.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = 0.0
        self.state = "CLOSED"  # States: CLOSED, OPEN, HALF-OPEN

    def can_execute(self) -> bool:
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "HALF-OPEN"
                logger.info("Circuit Breaker transitioned to HALF-OPEN. Probing feed...")
                return True
            return False
        return True

    def record_success(self) -> None:
        self.failure_count = 0
        if self.state != "CLOSED":
            logger.info("Circuit Breaker transitioned to CLOSED.")
            self.state = "CLOSED"

    def record_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_time = time.time()
        logger.warning(f"Circuit Breaker failure count: {self.failure_count}/{self.failure_threshold}")
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            logger.error("Circuit Breaker threshold hit. Entering OPEN state.")