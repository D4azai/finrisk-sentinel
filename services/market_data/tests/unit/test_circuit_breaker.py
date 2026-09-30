import time

from services.market_data.engine.circuit_breaker import CircuitBreaker


def test_circuit_breaker_initial_state():
    breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)
    assert breaker.state == "CLOSED"
    assert breaker.can_execute() is True


def test_circuit_breaker_opens_on_threshold():
    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=1.0)

    breaker.record_failure()
    assert breaker.state == "CLOSED"

    breaker.record_failure()
    assert breaker.state == "OPEN"
    assert breaker.can_execute() is False


def test_circuit_breaker_half_open_recovery():
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=0.2)
    breaker.record_failure()
    assert breaker.state == "OPEN"

    time.sleep(0.25)
    assert breaker.can_execute() is True
    assert breaker.state == "HALF-OPEN"

    breaker.record_success()
    assert breaker.state == "CLOSED"
