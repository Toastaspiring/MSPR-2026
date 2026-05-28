# ============================================================================
# Service API — FastAPI exposant les prédictions
# ============================================================================
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY services/api/requirements.txt ./
RUN pip install --user --no-warn-script-location -r requirements.txt

FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/home/mecha/.local/bin:$PATH

RUN useradd --create-home --shell /bin/bash --uid 1001 mecha \
    && mkdir -p /data/bronze /data/silver /data/gold /models /logs \
    && chown -R mecha:mecha /data /models /logs
WORKDIR /app

COPY --from=builder --chown=mecha:mecha /root/.local /home/mecha/.local
COPY --chown=mecha:mecha services/common /app/common
COPY --chown=mecha:mecha services/api /app/api

USER mecha

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=15s \
    CMD python -c "import urllib.request, sys; \
sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=3).status == 200 else 1)" || exit 1

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
