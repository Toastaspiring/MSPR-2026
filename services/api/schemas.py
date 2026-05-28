"""Schémas Pydantic d'entrée / sortie de l'API MECHA."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AlertLevel = Literal["nominal", "warning", "critical"]
FailureType = Literal["none", "Breakage", "Overheat"]


class SensorReading(BaseModel):
    """Mesure capteur instantanée pour une machine MECHA."""

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

    # Features dérivées — facultatives, calculées par l'API si absentes
    temperature_C_roll_mean_10: float | None = None
    temperature_C_roll_std_10: float | None = None
    temperature_C_delta: float | None = None
    vibration_roll_mean_10: float | None = None
    vibration_roll_std_10: float | None = None
    vibration_delta: float | None = None
    pressure_roll_mean_10: float | None = None
    pressure_roll_std_10: float | None = None
    pressure_delta: float | None = None
    hours_since_last_intervention: float | None = None


class PredictionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    readings: list[SensorReading] = Field(..., min_length=1, max_length=1000)


class PredictionItem(BaseModel):
    machine_id: int
    failure_probability: float = Field(..., ge=0, le=1)
    predicted_failure_type: FailureType
    failure_type_probabilities: dict[str, float]
    predicted_rul_hours: float = Field(..., ge=0)
    alert: bool
    alert_level: AlertLevel


class PredictionResponse(BaseModel):
    model_version: str
    threshold: float
    predictions: list[PredictionItem]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    models_loaded: bool
    model_trained_at: str | None = None
    type_classes: list[str] = Field(default_factory=list)
    site_id: str
    timestamp: datetime
