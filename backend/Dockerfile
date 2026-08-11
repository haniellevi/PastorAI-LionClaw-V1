# PastorAI backend — imagem única usada por 4 processos:
# - API: uvicorn app.main:app
# - queue worker: python -m app.workers.queue_worker
# - cron worker: python -m app.workers.cron_worker
# - broadcast worker: python -m app.workers.broadcast_worker
# O comando é sobrescrito por serviço no docker-compose.
# A tag legivel facilita manutencao; o digest torna a base imutavel.
FROM python:3.13.14-slim-trixie@sha256:9662417aace5ae7b8e2609cce472b72a8958e134ba372808abe9cc1a0c0125e6 AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# psycopg2-binary já traz libpq embutida — sem necessidade de build-essential/libpq-dev.
COPY requirements.lock ./
RUN python -m pip install --require-hashes -r requirements.lock

COPY app ./app
COPY migrations ./migrations

# Usuário não-root (segurança).
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Default: API. O healthcheck fica no serviço backend do Compose, porque esta
# mesma imagem também executa workers que não escutam na porta 8000.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
