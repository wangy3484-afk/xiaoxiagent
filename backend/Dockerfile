FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend/src \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.lock ./requirements.lock
RUN python -m pip install --no-cache-dir --requirement requirements.lock

COPY backend ./backend

RUN addgroup --system opsagent \
    && adduser --system --ingroup opsagent opsagent \
    && mkdir -p /app/artifacts \
    && chown -R opsagent:opsagent /app

USER opsagent

EXPOSE 8000

CMD ["uvicorn", "ops_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
