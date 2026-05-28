# ============================================================================
# Service Scheduler — orchestre les exécutions périodiques de etl et trainer.
# Communique avec le démon Docker du host via le socket /var/run/docker.sock
# (monté en lecture/écriture par docker-compose).
# ============================================================================
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
COPY services/scheduler/requirements.txt ./
RUN pip install --user --no-warn-script-location -r requirements.txt

FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/home/mecha/.local/bin:$PATH

# Le scheduler reste root pour pouvoir accéder au socket Docker — on
# limite la surface en réduisant le contenu de l'image au strict minimum.
WORKDIR /app

COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

COPY services/common /app/common
COPY services/scheduler /app/scheduler

HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
    CMD python -c "import scheduler.runner" || exit 1

ENTRYPOINT ["python", "-m", "scheduler.runner"]
