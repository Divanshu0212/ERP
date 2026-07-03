# syntax=docker/dockerfile:1
#
# Build context MUST be the monorepo root (so the editable install of
# ../../shared/libs/suerp_common in requirements.txt can be copied in):
#   docker build -f services/analytics-service/Dockerfile -t suerp/analytics-service .

# --- deps stage: install Python dependencies -------------------------------
FROM python:3.12-slim AS deps

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY shared/libs/suerp_common /app/shared/libs/suerp_common
COPY services/analytics-service/requirements.txt /app/services/analytics-service/requirements.txt

RUN pip install --upgrade pip \
    && pip install -r /app/services/analytics-service/requirements.txt

# --- runtime stage: copy app code and run gunicorn -------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 appuser

COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

WORKDIR /app
COPY shared/libs/suerp_common /app/shared/libs/suerp_common
COPY services/analytics-service /app/services/analytics-service

WORKDIR /app/services/analytics-service
RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
