import asyncio
import json
import logging
import signal
import time
from contextlib import suppress

from aiohttp import web
from prometheus_client import CollectorRegistry, Counter, Gauge, generate_latest


class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps(
            {
                "time": self.formatTime(record),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                **({"error_type": record.error_type} if hasattr(record, "error_type") else {}),
            }
        )


def configure_logging():
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    # Libraries may include connection strings or protocol payloads in diagnostic logs.
    logging.getLogger("aiokafka").setLevel(logging.CRITICAL)
    logging.getLogger("websockets").setLevel(logging.CRITICAL)


class Health:
    def __init__(self, settings):
        self.settings = settings
        self.db_ok = False
        self.broker_ok = False
        self.last_frame = 0.0
        self.stopping = False
        self.registry = CollectorRegistry()
        self.received = Counter(
            "finrisk_received_total", "Received records", registry=self.registry
        )
        self.processed = Counter(
            "finrisk_processed_total", "Processing outcomes", ["outcome"], registry=self.registry
        )
        self.published = Counter(
            "finrisk_published_total", "Published outbox rows", registry=self.registry
        )
        self.failures = Counter(
            "finrisk_failures_total", "Infrastructure failures", ["reason"], registry=self.registry
        )
        self.pending = Gauge(
            "finrisk_outbox_pending", "Pending outbox rows", registry=self.registry
        )
        self.oldest = Gauge(
            "finrisk_outbox_oldest_seconds", "Oldest pending row age", registry=self.registry
        )
        self.freshness = Gauge(
            "finrisk_feed_age_seconds", "Seconds since last accepted input", registry=self.registry
        )
        self.runner = None

    def touch(self):
        self.last_frame = time.monotonic()

    def ready(self):
        fresh = (
            self.last_frame
            and time.monotonic() - self.last_frame < self.settings.readiness_timeout_sec
        )
        return bool(not self.stopping and self.db_ok and self.broker_ok and fresh)

    async def start(self):
        async def live(request):
            return web.json_response(
                {"alive": not self.stopping}, status=503 if self.stopping else 200
            )

        async def ready(request):
            return web.json_response(
                {"ready": self.ready(), "database": self.db_ok, "broker": self.broker_ok},
                status=200 if self.ready() else 503,
            )

        async def metrics(request):
            return web.Response(
                body=generate_latest(self.registry),
                headers={"Content-Type": "text/plain; version=0.0.4"},
            )

        app = web.Application(client_max_size=1024)
        app.add_routes(
            [web.get("/live", live), web.get("/ready", ready), web.get("/metrics", metrics)]
        )
        self.runner = web.AppRunner(app, access_log=None)
        await self.runner.setup()
        await web.TCPSite(self.runner, self.settings.health_host, self.settings.health_port).start()

    async def close(self):
        self.stopping = True
        if self.runner:
            await self.runner.cleanup()

    async def watch(self, store):
        while True:
            try:
                async with store.pool.acquire() as connection:
                    row = await connection.fetchrow(
                        """SELECT count(*) AS pending,
                           COALESCE(EXTRACT(EPOCH FROM now()-min(created_at)),0) AS age
                           FROM outbox WHERE published_at IS NULL"""
                    )
                self.db_ok = True
                self.pending.set(row["pending"])
                self.oldest.set(float(row["age"]))
            except Exception as exc:
                self.db_ok = False
                self.failures.labels(type(exc).__name__).inc()
            self.freshness.set(time.monotonic() - self.last_frame if self.last_frame else -1)
            await asyncio.sleep(2)


async def supervise(*coroutines):
    """Cancel intake/work first, then callers close resources in finally blocks."""
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    originals = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        originals[sig] = signal.getsignal(sig)
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))
    tasks = [asyncio.create_task(coro) for coro in coroutines]
    waiter = asyncio.create_task(stop.wait())
    try:
        done, _ = await asyncio.wait([*tasks, waiter], return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            if task is not waiter:
                await task
                raise RuntimeError("A supervised worker exited unexpectedly")
    finally:
        for task in [*tasks, waiter]:
            task.cancel()
        await asyncio.gather(*tasks, waiter, return_exceptions=True)
        for sig, handler in originals.items():
            with suppress(NotImplementedError):
                loop.remove_signal_handler(sig)
            signal.signal(sig, handler)


async def bounded_close(callback):
    try:
        async with asyncio.timeout(10):
            await callback()
    except TimeoutError:
        logging.getLogger(__name__).warning("Resource shutdown deadline exceeded")


def run(main):
    configure_logging()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        # Never dump settings validation input/DSNs or raw exchange payloads.
        logging.getLogger(__name__).critical(
            "Service failed; inspect health metrics and configuration",
            extra={"error_type": type(exc).__name__},
        )
        raise SystemExit(1) from None
