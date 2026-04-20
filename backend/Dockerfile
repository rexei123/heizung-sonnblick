FROM python:3.12-slim

WORKDIR /app

# System-Dependencies (libpq für asyncpg build, build-essential für psutil etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python-Dependencies
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir ".[dev]"

# Quellcode und Migrationen
COPY alembic.ini ./
COPY alembic ./alembic
COPY tests ./tests

# Non-Root
RUN useradd -m -u 1000 app && chown -R app:app /app
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "heizung.main:app", "--host", "0.0.0.0", "--port", "8000"]
