"""Schémas Pydantic d'entrée / sortie de l'API MECHA (DBSCAN)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AlertLevel = Literal["nominal", "warning", "critical"]


class SensorReading(BaseModel):
    """Mesure capteur instantanée pour une machine MECHA.

    Le modèle DBSCAN consomme les 7 grandeurs physiques suivantes ; le
    ratio `cycle_ratio = cycle_duration / target_cycle` est dérivé côté API.
    """

    model_config = ConfigDict(extra="forbid")

    machine_id: int = Field(..., ge=1, description="Identifiant machine (1..N)")
    target_cycle: int = Field(..., ge=1, le=10000, description="Cycle de maintenance cible (heures)")

    consumption_kWh: float = Field(..., ge=0, le=1000)
    temperature_C: float = Field(..., ge=-20, le=200)
    vibration: float = Field(..., ge=0, le=50)
    pressure: float = Field(..., ge=0, le=200)
    cycle_duration: float = Field(..., ge=0, le=300)
    rpm: float = Field(..., ge=0, le=5000)
    voltage: float = Field(..., ge=0, le=500)


class PredictionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    readings: list[SensorReading] = Field(..., min_length=1, max_length=1000)


class PredictionItem(BaseModel):
    machine_id: int
    cluster_label: int = Field(..., description="Identifiant du cluster DBSCAN ; -1 = anomalie/bruit")
    anomaly: bool
    anomaly_score: float = Field(..., ge=0, le=1, description="Distance normalisée au voisin core le plus proche")
    alert: bool
    alert_level: AlertLevel


class PredictionResponse(BaseModel):
    model_version: str
    threshold: float = Field(..., description="Seuil d'alerte critique sur `anomaly_score`")
    predictions: list[PredictionItem]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    models_loaded: bool
    model_trained_at: str | None = None
    n_machines_trained: int = 0
    site_id: str
    timestamp: datetime
