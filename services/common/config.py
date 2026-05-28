"""Configuration centralisée — toutes les valeurs proviennent du .env.

Aucune valeur sensible n'est codée en dur ; chaque service lit la
configuration via cette unique source de vérité.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env(key: str, default: str | None = None, required: bool = False) -> str:
    value = os.environ.get(key, default)
    if required and (value is None or value == ""):
        raise RuntimeError(f"Variable d'environnement obligatoire absente : {key}")
    return value  # type: ignore[return-value]


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key)
    return float(raw) if raw else default


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    return int(raw) if raw else default


@dataclass(frozen=True)
class Paths:
    bronze: Path
    silver: Path
    gold: Path
    models: Path
    logs: Path

    @classmethod
    def from_env(cls) -> "Paths":
        return cls(
            bronze=Path(_env("BRONZE_DIR", "/data/bronze")),
            silver=Path(_env("SILVER_DIR", "/data/silver")),
            gold=Path(_env("GOLD_DIR", "/data/gold")),
            models=Path(_env("MODELS_DIR", "/models")),
            logs=Path(_env("LOGS_DIR", "/logs")),
        )

    def ensure(self) -> None:
        for p in (self.bronze, self.silver, self.gold, self.models, self.logs):
            p.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class Settings:
    paths: Paths
    failure_alert_threshold: float
    etl_cron: str
    retrain_cron: str
    log_level: str
    log_format: str
    api_host: str
    api_port: int
    api_workers: int
    api_base_url: str
    dashboard_port: int
    dashboard_title: str
    mlflow_tracking_uri: str
    mlflow_experiment: str
    app_env: str
    app_site_id: str

    @classmethod
    def load(cls) -> "Settings":
        return cls(
            paths=Paths.from_env(),
            failure_alert_threshold=_env_float("FAILURE_ALERT_THRESHOLD", 0.75),
            etl_cron=_env("ETL_CRON_SCHEDULE", "0 */6 * * *"),
            retrain_cron=_env("RETRAIN_CRON_SCHEDULE", "0 2 * * 0"),
            log_level=_env("LOG_LEVEL", "INFO"),
            log_format=_env("LOG_FORMAT", "json"),
            api_host=_env("API_HOST", "0.0.0.0"),
            api_port=_env_int("API_PORT", 8000),
            api_workers=_env_int("API_WORKERS", 2),
            api_base_url=_env("API_BASE_URL", "http://api:8000"),
            dashboard_port=_env_int("DASHBOARD_PORT", 8501),
            dashboard_title=_env("DASHBOARD_TITLE", "MECHA — Maintenance Prédictive"),
            mlflow_tracking_uri=_env("MLFLOW_TRACKING_URI", "file:///models/mlruns"),
            mlflow_experiment=_env("MLFLOW_EXPERIMENT_NAME", "mecha-failure-prediction"),
            app_env=_env("APP_ENV", "development"),
            app_site_id=_env("APP_SITE_ID", "local"),
        )


# Instance unique chargée à l'import
settings = Settings.load()
