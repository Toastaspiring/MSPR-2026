"""Application FastAPI — exposition des prédictions MECHA.

Endpoints :
  - GET  /health      : santé du service + statut des modèles
  - GET  /metrics     : métriques Prometheus (scrapées par Grafana/Prometheus)
  - POST /predict     : scoring batch (failure, failure_type, RUL)
  - GET  /           : redirection vers la doc OpenAPI

Les prédictions sont également écrites en best-effort dans Postgres
(table `predictions`) pour alimenter les dashboards Grafana.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone

import numpy as np
import pandas as pd
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
)
from .warehouse import insert_predictions

log = setup_logger("api")


def _safe_counter(name: str, doc: str, labels: list[str] | None = None) -> Counter:
    """Crée un Counter en réutilisant l'existant si déjà enregistré (tests, reload)."""
    existing = REGISTRY._names_to_collectors.get(name)  # type: ignore[attr-defined]
    if existing is not None:
        return existing  # type: ignore[return-value]
    return Counter(name, doc, labels or [])


def _safe_histogram(name: str, doc: str) -> Histogram:
    existing = REGISTRY._names_to_collectors.get(name)  # type: ignore[attr-defined]
    if existing is not None:
        return existing  # type: ignore[return-value]
    return Histogram(name, doc)


# Ordre des features attendu par les modèles (cohérent avec trainer.train.FEATURE_COLUMNS)
FEATURE_COLUMNS: list[str] = [
    "target_cycle",
    "consumption_kWh",
    "temperature_C",
    "vibration",
    "pressure",
    "cycle_duration",
    "rpm",
    "voltage",
    "temperature_C_roll_mean_10",
    "temperature_C_roll_std_10",
    "temperature_C_delta",
    "vibration_roll_mean_10",
    "vibration_roll_std_10",
    "vibration_delta",
    "pressure_roll_mean_10",
    "pressure_roll_std_10",
    "pressure_delta",
    "load_proxy",
    "energy_per_cycle",
    "hours_since_last_intervention",
]

# ----- Métriques Prometheus (idempotent face aux importlib.reload) ----------
PREDICT_REQUESTS = _safe_counter("mecha_api_predict_requests", "Nombre total de requêtes /predict", ["status"])
PREDICT_LATENCY = _safe_histogram("mecha_api_predict_latency_seconds", "Latence du endpoint /predict")
PREDICTIONS_BY_MACHINE = _safe_counter("mecha_api_predictions", "Prédictions produites par machine", ["machine_id"])
ALERTS_BY_LEVEL = _safe_counter("mecha_api_alerts", "Alertes émises par niveau", ["level"])
ALERTS_BY_TYPE = _safe_counter(
    "mecha_api_alerts_by_type", "Alertes émises par type de défaillance prédit", ["failure_type"]
)


# ----- Lifespan -------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Démarrage API — env={} site={}", settings.app_env, settings.app_site_id)
    registry.maybe_reload()
    if not registry.loaded:
        log.warning("Aucun modèle chargé au démarrage — /predict retournera 503.")
    yield
    log.info("Arrêt de l'API.")


app = FastAPI(
    title="MECHA — API de maintenance prédictive",
    description=(
        "Trois modèles complémentaires : probabilité de défaillance, "
        "type prédit (Breakage / Overheat), durée résiduelle estimée."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# ----- Helpers --------------------------------------------------------------
def _alert_level(p: float) -> str:
    if p >= max(0.9, settings.failure_alert_threshold):
        return "critical"
    if p >= settings.failure_alert_threshold:
        return "warning"
    return "nominal"


def _readings_to_dataframe(readings) -> pd.DataFrame:
    rows = []
    for r in readings:
        # Compute derived features if not provided
        load_proxy = (r.rpm * r.pressure) / (abs(r.voltage) + 1.0)
        energy = r.consumption_kWh * r.cycle_duration
        rows.append(
            {
                "target_cycle": r.target_cycle,
                "consumption_kWh": r.consumption_kWh,
                "temperature_C": r.temperature_C,
                "vibration": r.vibration,
                "pressure": r.pressure,
                "cycle_duration": r.cycle_duration,
                "rpm": r.rpm,
                "voltage": r.voltage,
                "temperature_C_roll_mean_10": (
                    r.temperature_C_roll_mean_10 if r.temperature_C_roll_mean_10 is not None else r.temperature_C
                ),
                "temperature_C_roll_std_10": r.temperature_C_roll_std_10 or 0.0,
                "temperature_C_delta": r.temperature_C_delta or 0.0,
                "vibration_roll_mean_10": (
                    r.vibration_roll_mean_10 if r.vibration_roll_mean_10 is not None else r.vibration
                ),
                "vibration_roll_std_10": r.vibration_roll_std_10 or 0.0,
                "vibration_delta": r.vibration_delta or 0.0,
                "pressure_roll_mean_10": r.pressure_roll_mean_10 if r.pressure_roll_mean_10 is not None else r.pressure,
                "pressure_roll_std_10": r.pressure_roll_std_10 or 0.0,
                "pressure_delta": r.pressure_delta or 0.0,
                "load_proxy": load_proxy,
                "energy_per_cycle": energy,
                "hours_since_last_intervention": (
                    r.hours_since_last_intervention if r.hours_since_last_intervention is not None else 9999.0
                ),
            }
        )
    return pd.DataFrame(rows, columns=FEATURE_COLUMNS).astype(float)


# ----- Endpoints ------------------------------------------------------------
@app.get("/health", response_model=HealthResponse, tags=["meta"])
def health() -> HealthResponse:
    registry.maybe_reload()
    return HealthResponse(
        status="ok" if registry.loaded else "degraded",
        models_loaded=registry.loaded,
        model_trained_at=registry.trained_at,
        type_classes=registry.type_classes,
        site_id=settings.app_site_id,
        timestamp=datetime.now(timezone.utc),
    )


@app.get("/metrics", response_class=PlainTextResponse, tags=["meta"])
def metrics():
    """Export Prometheus standard — scrapé par Prometheus/Grafana."""
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/predict", response_model=PredictionResponse, tags=["predict"])
def predict(req: PredictionRequest) -> PredictionResponse:
    registry.maybe_reload()
    if not registry.loaded:
        PREDICT_REQUESTS.labels(status="unavailable").inc()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Modèles non chargés — l'entraînement doit avoir été exécuté.",
        )

    with PREDICT_LATENCY.time():
        X = _readings_to_dataframe(req.readings)
        try:
            probas, type_dicts, ruls = registry.predict(X)
        except Exception as exc:  # noqa: BLE001
            PREDICT_REQUESTS.labels(status="error").inc()
            log.exception("Erreur de prédiction : {}", exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        items: list[PredictionItem] = []
        rows_to_persist: list[dict] = []
        threshold = settings.failure_alert_threshold

        for reading, p, type_proba, rul in zip(req.readings, probas, type_dicts, ruls):
            level = _alert_level(float(p))
            is_alert = level != "nominal"
            predicted_type = max(type_proba, key=type_proba.get)

            items.append(
                PredictionItem(
                    machine_id=reading.machine_id,
                    failure_probability=float(np.clip(p, 0.0, 1.0)),
                    predicted_failure_type=predicted_type,  # type: ignore[arg-type]
                    failure_type_probabilities={k: float(v) for k, v in type_proba.items()},
                    predicted_rul_hours=float(max(0.0, rul)),
                    alert=is_alert,
                    alert_level=level,  # type: ignore[arg-type]
                )
            )
            rows_to_persist.append(
                {
                    "machine_id": reading.machine_id,
                    "model_version": registry.version,
                    "threshold": threshold,
                    "failure_probability": float(np.clip(p, 0.0, 1.0)),
                    "predicted_failure_type": predicted_type,
                    "predicted_rul_hours": float(max(0.0, rul)),
                    "alert_level": level,
                }
            )

            # Métriques Prometheus
            PREDICTIONS_BY_MACHINE.labels(machine_id=str(reading.machine_id)).inc()
            ALERTS_BY_LEVEL.labels(level=level).inc()
            if is_alert:
                ALERTS_BY_TYPE.labels(failure_type=predicted_type).inc()

        # Best-effort persistance Postgres
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
            "version": "1.0.0",
            "docs": "/docs",
            "openapi": "/openapi.json",
        }
    )
