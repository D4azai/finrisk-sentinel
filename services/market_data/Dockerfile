FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*

# Copy only the service's pyproject and install the market_data package in-place
COPY services/market_data/pyproject.toml services/market_data/pyproject.toml
RUN pip install --no-cache-dir ./services/market_data

# Copy the entire services tree so shared modules (logging_*) are available
COPY services /app/services
ENV PYTHONPATH=/app

CMD ["python", "services/market_data/main.py"]