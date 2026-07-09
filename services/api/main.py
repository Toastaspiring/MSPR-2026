"""Application FastAPI — exposition de la détection d'anomalies MECHA (DBSCAN).

Endpoints :
  - GET  /health   : santé du service + statut du bundle DBSCAN
  - GET  /metrics  : métriques Prometheus (scrapées par Prometheus/Grafana)
  - POST /predict  : scoring batch (cluster_label, anomaly, anomaly_score, alert)
  - GET  /         : redirection vers la doc OpenAPI

Les prédictions sont écrites en best-effort dans Postgres (table `predictions`)
pour alimenter les dashboards Grafana.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone

import numpy as np
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    Counter,
    Histogram,
    generate_latest,
)

from common.config import settings
from common.logger import setup_logger

from .model_loader import registry
from .schemas import (
    HealthResponse,
    PredictionItem,
    PredictionRequest,
    PredictionResponse,
    SensorReading,
)
from .warehouse import insert_predictions

log = setup_logger("api")


def _safe_counter(name: str, doc: str, labels: list[str] | None = None) -> Counter:
    existing = REGISTRY._names_to_collectors.get(name)  # type: ignore[attr-defined]
    if existing is not None:
        return existing  # type: ignore[return-value]
    return Counter(name, doc, labels or [])


def _safe_histogram(name: str, doc: str) -> Histogram:
    existing = REGISTRY._names_to_collectors.get(name)  # type: ignore[attr-defined]
    if existing is not None:
        return existing  # type: ignore[return-value]
    return Histogram(name, doc)


# Features consommées par DBSCAN — doivent rester alignées avec
# trainer.train.DBSCAN_FEATURES.
DBSCAN_FEATURES: list[str] = [
    "consumption_kWh",
    "temperature_C",
    "vibration",
    "pressure",
    "cycle_duration",
    "rpm",
    "voltage",
    "cycle_ratio",
]


PREDICT_REQUESTS = _safe_counter("mecha_api_predict_requests", "Nombre total de requêtes /predict", ["status"])
PREDICT_LATENCY = _safe_histogram("mecha_api_predict_latency_seconds", "Latence du endpoint /predict")
PREDICTIONS_BY_MACHINE = _safe_counter("mecha_api_predictions", "Prédictions produites par machine", ["machine_id"])
ALERTS_BY_LEVEL = _safe_counter("mecha_api_alerts", "Alertes émises par niveau", ["level"])
ANOMALIES_BY_MACHINE = _safe_counter(
    "mecha_api_anomalies", "Points classés en cluster -1 (anomalies)", ["machine_id"]
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Démarrage API — env={} site={}", settings.app_env, settings.app_site_id)
    registry.maybe_reload()
    if not registry.loaded:
        log.warning("Bundle DBSCAN non chargé au démarrage — /predict retournera 503.")
    yield
    log.info("Arrêt de l'API.")


app = FastAPI(
    title="MECHA — API de détection d'anomalies (DBSCAN)",
    description=(
        "Détection non supervisée par densité conformément au rendu écrit : "
        "cluster_label == -1 → anomalie, alerte remontée aux équipes maintenance."
    ),
    version="2.0.0",
    lifespan=lifespan,
)


def _alert_level(anomaly: bool, score: float) -> str:
    if not anomaly:
        return "nominal"
    if score >= max(0.9, settings.failure_alert_threshold):
        return "critical"
    return "warning"


def _readings_to_array(readings: list[SensorReading]) -> tuple[np.ndarray, list[int]]:
    """Construit la matrice DBSCAN et la liste des machine_ids alignée."""
    n = len(readings)
    X = np.empty((n, len(DBSCAN_FEATURES)), dtype=float)
    machine_ids: list[int] = []
    for i, r in enumerate(readings):
        cycle_ratio = float(r.cycle_duration) / float(r.target_cycle) if r.target_cycle else 1.0
        X[i] = (
            r.consumption_kWh,
            r.temperature_C,
            r.vibration,
            r.pressure,
            r.cycle_duration,
            r.rpm,
            r.voltage,
            cycle_ratio,
        )
        machine_ids.append(int(r.machine_id))
    return X, machine_ids


@app.get("/health", response_model=HealthResponse, tags=["meta"])
def health() -> HealthResponse:
    registry.maybe_reload()
    return HealthResponse(
        status="ok" if registry.loaded else "degraded",
        models_loaded=registry.loaded,
        model_trained_at=registry.trained_at,
        n_machines_trained=registry.n_machines,
        site_id=settings.app_site_id,
        timestamp=datetime.now(timezone.utc),
    )


@app.get("/metrics", response_class=PlainTextResponse, tags=["meta"])
def metrics():
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/predict", response_model=PredictionResponse, tags=["predict"])
def predict(req: PredictionRequest) -> PredictionResponse:
    registry.maybe_reload()
    if not registry.loaded:
        PREDICT_REQUESTS.labels(status="unavailable").inc()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Bundle DBSCAN non chargé — l'entraînement doit avoir été exécuté.",
        )

    with PREDICT_LATENCY.time():
        X, machine_ids = _readings_to_array(req.readings)
        try:
            cluster_labels, anomaly_scores = registry.predict(X, machine_ids)
        except Exception as exc:  # noqa: BLE001
            PREDICT_REQUESTS.labels(status="error").inc()
            log.exception("Erreur de prédiction : {}", exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        items: list[PredictionItem] = []
        rows_to_persist: list[dict] = []
        threshold = settings.failure_alert_threshold

        for reading, lbl, score in zip(req.readings, cluster_labels, anomaly_scores):
            is_anomaly = lbl == -1
            level = _alert_level(is_anomaly, float(score))
            is_alert = is_anomaly

            items.append(
                PredictionItem(
                    machine_id=reading.machine_id,
                    cluster_label=int(lbl),
                    anomaly=is_anomaly,
                    anomaly_score=float(score),
                    alert=is_alert,
                    alert_level=level,  # type: ignore[arg-type]
                )
            )
            rows_to_persist.append(
                {
                    "machine_id": reading.machine_id,
                    "model_version": registry.version,
                    "cluster_label": int(lbl),
                    "anomaly": is_anomaly,
                    "anomaly_score": float(score),
                    "alert": is_alert,
                    "alert_level": level,
                }
            )

            PREDICTIONS_BY_MACHINE.labels(machine_id=str(reading.machine_id)).inc()
            ALERTS_BY_LEVEL.labels(level=level).inc()
            if is_anomaly:
                ANOMALIES_BY_MACHINE.labels(machine_id=str(reading.machine_id)).inc()

        n_inserted = insert_predictions(rows_to_persist)
        if n_inserted:
            log.debug("Persisté {} prédictions dans Postgres", n_inserted)

        PREDICT_REQUESTS.labels(status="ok").inc()

    return PredictionResponse(
        model_version=registry.version,
        threshold=threshold,
        predictions=items,
    )


@app.get("/", include_in_schema=False)
def root() -> JSONResponse:
    return JSONResponse(
        {
            "service": "mecha-api",
            "version": "2.0.0",
            "algorithm": "DBSCAN",
            "docs": "/docs",
            "openapi": "/openapi.json",
        }
    )
