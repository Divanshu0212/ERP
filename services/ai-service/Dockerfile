# syntax=docker/dockerfile:1
#
# ai-service — standalone FastAPI microservice (NO suerp_common / Django).
# Build context is this service directory (self-contained requirements):
#   docker build -f services/ai-service/Dockerfile -t suerp/ai-service services/ai-service

# --- deps stage: install Python dependencies -------------------------------
FROM python:3.12-slim AS deps

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip \
    && pip install -r /app/requirements.txt

# --- runtime stage: copy app code and run uvicorn --------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN useradd --create-home --uid 1000 appuser

COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

WORKDIR /app
COPY . /app
RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

# HTTP inference API. The event consumer runs as a separate process:
#   python -m app.consumer
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
