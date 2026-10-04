FROM python:3.13-slim@sha256:bb2988715db2cf7ace7b53f38f3cffbef7c7046a656bee66245eb0ed386e2e81 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend/src \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/tmp

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends fonts-wqy-zenhei \
    && rm -rf /var/lib/apt/lists/*

ENV OPS_AGENT_PDF_FONT_PATH=/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc \
    OPS_AGENT_PDF_BOLD_FONT_PATH=/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc

COPY requirements.runtime.lock ./requirements.runtime.lock
RUN python -m pip install --no-cache-dir --requirement requirements.runtime.lock

COPY alembic.ini ./alembic.ini
COPY pyproject.toml ./pyproject.toml
COPY backend ./backend
COPY docs ./docs

RUN addgroup --system opsagent \
    && adduser --system --ingroup opsagent opsagent \
    && mkdir -p /app/artifacts \
    && chown opsagent:opsagent /app/artifacts

USER opsagent

EXPOSE 8000

FROM runtime AS api

HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=12 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

CMD ["uvicorn", "ops_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS worker

HEALTHCHECK --interval=15s --timeout=10s --start-period=20s --retries=12 \
    CMD celery -A ops_agent.worker:celery_app inspect ping --destination "worker@$(hostname)" --timeout 5 | grep -q pong

CMD ["celery", "-A", "ops_agent.worker:celery_app", "worker", "--loglevel=INFO", "--hostname=worker@%h"]
