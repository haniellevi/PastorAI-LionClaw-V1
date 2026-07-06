# PastorAI backend — imagem única usada por 3 processos:
#   - API:          uvicorn app.main:app
#   - queue worker: python -m app.workers.queue_worker
#   - cron worker:  python -m app.workers.cron_worker
# O comando é sobrescrito por serviço no docker-compose.

FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# psycopg2-binary já traz libpq embutida — sem necessidade de build-essential/libpq-dev.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY migrations ./migrations

# Usuário não-root (segurança).
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Healthcheck bate no /health (liveness sem banco).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3).status==200 else 1)" || exit 1

# Default: API. Workers sobrescrevem com 'command:' no compose.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
