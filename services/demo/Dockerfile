# ============================================================================
# Service DEMO — rejoue le jeu de données comme un flux temps réel.
# Multi-stage build (section 4.1 — réduction de la surface d'attaque).
# ============================================================================

# ---- Stage 1 : compilation des dépendances natives (numpy, pandas, pyarrow) -
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY services/demo/requirements.txt ./
RUN pip install --user --no-warn-script-location -r requirements.txt

# ---- Stage 2 : image runtime minimale -------------------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/home/mecha/.local/bin:$PATH

RUN useradd --create-home --shell /bin/bash --uid 1001 mecha \
    && mkdir -p /data/gold /logs \
    && chown -R mecha:mecha /data /logs

WORKDIR /app

COPY --from=builder --chown=mecha:mecha /root/.local /home/mecha/.local

COPY --chown=mecha:mecha services/common /app/common
COPY --chown=mecha:mecha services/demo /app/demo

USER mecha

HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
    CMD python -c "import demo.streamer" || exit 1

ENTRYPOINT ["python", "-m", "demo.streamer"]
