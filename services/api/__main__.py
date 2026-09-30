import uvicorn

from services.common.runtime import configure_logging

configure_logging()
uvicorn.run(
    "services.api.main:app",
    host="0.0.0.0",
    port=8080,
    access_log=False,
    proxy_headers=False,
    limit_concurrency=200,
    timeout_graceful_shutdown=15,
    log_config=None,
)
