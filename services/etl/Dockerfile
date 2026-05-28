# ============================================================================
# Service ETL — pipeline Bronze → Silver → Gold
# Multi-stage build (section 4.1 — réduction de la surface d'attaque).
# ============================================================================

# ---- Stage 1 : compilation des dépendances natives (numpy, pandas, pyarrow) -
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# build-essential + librairies headers nécessaires pour pyarrow/numpy
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY services/etl/requirements.txt ./
RUN pip install --user --no-warn-script-location -r requirements.txt

# ---- Stage 2 : image runtime minimale -------------------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/home/mecha/.local/bin:$PATH

# Utilisateur non-root (section 4.1 — principe de moindre privilège)
RUN useradd --create-home --shell /bin/bash --uid 1001 mecha \
    && mkdir -p /data/bronze /data/silver /data/gold /models /logs \
    && chown -R mecha:mecha /data /models /logs

WORKDIR /app

# Récupère uniquement les wheels installés depuis le builder
COPY --from=builder --chown=mecha:mecha /root/.local /home/mecha/.local

# Code applicatif
COPY --chown=mecha:mecha services/common /app/common
COPY --chown=mecha:mecha services/etl /app/etl

USER mecha

# Healthcheck léger : le module doit s'importer sans erreur
HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
    CMD python -c "import etl.pipeline" || exit 1

ENTRYPOINT ["python", "-m", "etl.main"]
