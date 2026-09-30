import asyncio
import os
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from services.common.runtime import Health, supervise
from services.common.settings import InfrastructureSettings
from services.market_data.engine.connection_manager import ResilientConnectionManager


@pytest.fixture(autouse=True)
def isolate_settings_environment(monkeypatch):
    for key in os.environ:
        if key.startswith("FINRISK_"):
            monkeypatch.delenv(key)


def settings(**changes):
    return InfrastructureSettings(
        _env_file=None,
        database_url="postgresql://user:pass@localhost/db?sslmode=verify-full",
        kafka_username="user",
        kafka_password="password",
        **changes,
    )


def test_production_rejects_plaintext_even_with_override():
    with pytest.raises(ValidationError):
        settings(kafka_security_protocol="PLAINTEXT", allow_insecure_local=True)


def test_missing_kafka_credentials_rejected():
    with pytest.raises(ValidationError):
        InfrastructureSettings(_env_file=None, database_url="postgresql://u:p@host/db")


def test_local_plaintext_requires_explicit_opt_in():
    kwargs = dict(
        _env_file=None,
        environment="development",
        kafka_security_protocol="PLAINTEXT",
        database_url="postgresql://u:p@host/db",
    )
    with pytest.raises(ValidationError):
        InfrastructureSettings(**kwargs)
    assert InfrastructureSettings(**kwargs, allow_insecure_local=True)


async def test_clean_eof_retries_with_limit(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep)
    disconnect = AsyncMock()
    manager = ResilientConnectionManager(
        base_delay=0.01, max_delay=0.02, max_attempts=2, on_disconnect=disconnect
    )

    async def empty():
        if False:
            yield None

    with pytest.raises(RuntimeError, match="attempt limit"):
        await anext(manager.stream_with_retry(empty))
    assert sleep.await_count == 1
    assert disconnect.await_count == 2
    assert 0.005 <= sleep.await_args.args[0] <= 0.01


async def test_idle_feed_is_closed():
    closed = asyncio.Event()

    async def idle():
        try:
            await asyncio.Event().wait()
            yield None
        finally:
            closed.set()

    manager = ResilientConnectionManager(idle_timeout=0.01, max_attempts=1)
    with pytest.raises(RuntimeError):
        await anext(manager.stream_with_retry(idle))
    assert closed.is_set()


async def test_cancellation_does_not_reconnect():
    closed = asyncio.Event()

    async def stream():
        try:
            yield 1
            await asyncio.Event().wait()
        finally:
            closed.set()

    manager = ResilientConnectionManager()
    iterator = manager.stream_with_retry(stream)
    assert await anext(iterator) == 1
    task = asyncio.create_task(anext(iterator))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()


async def test_supervisor_cancels_peers_before_returning():
    closed = asyncio.Event()

    async def worker():
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()

    async def failed():
        await asyncio.sleep(0.01)
        raise RuntimeError("failure")

    with pytest.raises(RuntimeError, match="failure"):
        await supervise(worker(), failed())
    assert closed.is_set()


def test_readiness_requires_dependencies_and_freshness():
    health = Health(settings())
    assert not health.ready()
    health.db_ok = health.broker_ok = True
    health.touch()
    assert health.ready()
    health.stopping = True
    assert not health.ready()
