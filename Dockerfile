FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c AS build
WORKDIR /build
COPY requirements.lock ./
RUN pip install --no-cache-dir --require-hashes --prefix=/install -r requirements.lock

FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --create-home app
WORKDIR /app
COPY --from=build /install /usr/local
COPY --chown=app:app services ./services
COPY --chown=app:app scripts ./scripts
COPY --chown=app:app inspect_stream.py ./
USER app
HEALTHCHECK --interval=15s --timeout=3s --start-period=30s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/live', timeout=2)"]
CMD ["python", "-m", "services.ingestion.main"]
