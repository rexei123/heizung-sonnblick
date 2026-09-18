FROM python:3.12-slim

WORKDIR /app

# System-Dependencies (libpq für asyncpg build, build-essential für psutil etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python-Dependencies
# Editable Install: src/ wird zur Laufzeit aus dem Volume gelesen (siehe
# docker-compose.yml). Dadurch reicht "docker compose restart api" fuer
# Code-Aenderungen; "docker compose build api" ist nur noch bei
# pyproject-Aenderungen (neue Dependencies) noetig.
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -e ".[dev]"

# Quellcode und Migrationen
COPY alembic.ini ./
COPY alembic ./alembic
COPY tests ./tests
# Hand-Smoke-Tools ohne Test-Coverage (heute nur smoke_engine_lock.py).
# Die Hotelier-Skripte liegen NICHT hier, sondern als Sub-Package in src/ und
# kommen ueber den editable Install ins Image. Aufruf seit Sprint 17
# einheitlich via `docker exec <api-container> python -m heizung.scripts.<name>`
# (seed_rooms, pair_devices, activate_open_window_detection,
# sync_room_statuses). Der alte Pfad `python scripts/<name>.py` gilt nur noch
# fuer die Smoke-Tools in diesem Verzeichnis.
COPY scripts ./scripts

# Entrypoint (führt beim Start automatisch alembic upgrade head aus)
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Non-Root
RUN useradd -m -u 1000 app && chown -R app:app /app
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "heizung.main:app", "--host", "0.0.0.0", "--port", "8000"]
