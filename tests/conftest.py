"""Configuration partagée pytest — chemins, fixtures, isolation .env."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Ajoute services/ au PYTHONPATH pour les imports `from common.config ...`
ROOT = Path(__file__).resolve().parent.parent
SERVICES = ROOT / "services"
if str(SERVICES) not in sys.path:
    sys.path.insert(0, str(SERVICES))


@pytest.fixture(autouse=True)
def isolated_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Chaque test reçoit son propre arbre /data, /models, /logs."""
    bronze = tmp_path / "bronze"
    silver = tmp_path / "silver"
    gold = tmp_path / "gold"
    models = tmp_path / "models"
    logs = tmp_path / "logs"
    for p in (bronze, silver, gold, models, logs):
        p.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("BRONZE_DIR", str(bronze))
    monkeypatch.setenv("SILVER_DIR", str(silver))
    monkeypatch.setenv("GOLD_DIR", str(gold))
    monkeypatch.setenv("MODELS_DIR", str(models))
    monkeypatch.setenv("LOGS_DIR", str(logs))
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    # Pas de Postgres pendant les tests : warehouse.* dégrade gracieusement.
    monkeypatch.delenv("POSTGRES_DSN", raising=False)

    import importlib

    import common.config  # noqa: WPS433

    importlib.reload(common.config)
    return tmp_path


# ---------------------------------------------------------------------------
# Fixtures de données conformes au VRAI schéma MECHA
# ---------------------------------------------------------------------------
@pytest.fixture
def sample_timeseries_bronze() -> pd.DataFrame:
    """Réplique exacte du schéma `machine_X_targetcycleN.csv` de MECHA."""
    return pd.DataFrame(
        {
            "timestamp": [
                "2026-01-01 00:00:00",
                "2026-01-01 01:00:00",
                "2026-01-01 02:00:00",  # voltage et failure NULL volontaires
                "2026-01-01 03:00:00",
                "not-a-date",  # timestamp invalide
                "2026-01-01 04:00:00",
                "2026-01-01 04:00:00",  # doublon
            ],
            "consumption_kWh": [17.95, 14.86, 14.90, 21.64, 14.66, 250.0, 15.66],  # 250 hors borne
            "temperature_C": [46.87, 41.61, 50.94, 68.71, 56.12, 49.32, 50.0],
            "vibration": [1.18, 0.79, 1.20, 1.32, 0.81, 1.38, 1.0],
            "pressure": [50.49, 46.65, 52.08, 44.56, 52.57, 54.23, 50.0],
            "cycle_duration": [37.10, 36.25, 31.74, 33.17, 33.70, 37.79, 35.0],
            "rpm": [1467.69, 1443.81, 1578.17, 1470.12, 1471.65, 1521.57, 1500.0],
            "voltage": [229.55, 231.08, np.nan, 230.13, 230.87, 227.61, 230.0],
            "failure": [0.0, 0.0, np.nan, 0.0, 0.0, 0.0, 0.0],
        }
    )


@pytest.fixture
def sample_interventions_bronze() -> pd.DataFrame:
    """Réplique du schéma `intervention_data_machineN.csv`."""
    return pd.DataFrame(
        {
            "timestamp": [
                "2026-01-01 04:00:00",
                "2026-01-02 15:00:00",
                "bad-date",
                "2026-01-03 11:00:00",
            ],
            "failure_type": ["Breakage", "Overheat", "Breakage", "Unknown"],
            "temperature": [59.5, 97.2, 73.1, 85.0],
            "rpm": [1622.1, 1535.8, 1654.2, 1600.0],
            "vibration": [3.34, 1.58, 3.14, 2.5],
            "pressure": [50.94, 53.44, 60.69, 55.0],
        }
    )


@pytest.fixture
def sample_silver(sample_timeseries_bronze) -> pd.DataFrame:
    """Silver généré depuis le bronze (machine_id=1, target_cycle=30)
    via le pipeline canonique du notebook MECHA."""
    from etl.bronze_to_silver_functions import transform_bronze_to_silver_with_context

    return transform_bronze_to_silver_with_context(sample_timeseries_bronze, machine_id=1, target_cycle=30)


@pytest.fixture
def sample_interventions_silver(sample_interventions_bronze) -> pd.DataFrame:
    from etl.bronze_to_silver_functions import interventions_bronze_to_silver

    return interventions_bronze_to_silver(sample_interventions_bronze, machine_id=1)
