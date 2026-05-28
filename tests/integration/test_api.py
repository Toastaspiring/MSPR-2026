"""Test d'intégration de l'API FastAPI sans serveur réel (TestClient).

Couvre : seed des 3 modèles → /health → /predict (single + batch +
validation) → /metrics au format Prometheus.
"""

from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sklearn.ensemble import GradientBoostingRegressor, RandomForestClassifier
from sklearn.preprocessing import LabelEncoder


def _seed_models(models_dir: Path) -> None:
    """Entraîne 3 mini-modèles cohérents avec api.main.FEATURE_COLUMNS."""
    from api.main import FEATURE_COLUMNS

    rng = np.random.default_rng(42)
    n = 300
    X = pd.DataFrame(rng.uniform(size=(n, len(FEATURE_COLUMNS))) * 100, columns=FEATURE_COLUMNS)

    # Labels synthétiques
    y_failure = (X["temperature_C"] > 60).astype(int)
    # 3 classes : none / Breakage / Overheat
    y_type = np.where(X["temperature_C"] > 80, "Overheat", np.where(X["vibration"] > 60, "Breakage", "none"))
    y_rul = np.clip(X["target_cycle"] - X["hours_since_last_intervention"], 0, 200)

    failure = RandomForestClassifier(n_estimators=20, random_state=42).fit(X, y_failure)
    encoder = LabelEncoder().fit(y_type)
    type_clf = RandomForestClassifier(n_estimators=20, random_state=42).fit(X, encoder.transform(y_type))
    reg = GradientBoostingRegressor(n_estimators=20, random_state=42).fit(X, y_rul)

    joblib.dump(failure, models_dir / "classifier_failure.joblib")
    joblib.dump(type_clf, models_dir / "classifier_type.joblib")
    joblib.dump(encoder, models_dir / "type_encoder.joblib")
    joblib.dump(reg, models_dir / "regressor_rul.joblib")

    (models_dir / "metadata.json").write_text(
        '{"trained_at":"test","feature_columns":[],"failure_metrics":{},'
        '"failure_type_metrics":{},"rul_metrics":{},"type_classes":["Breakage","Overheat","none"]}',
        encoding="utf-8",
    )


@pytest.fixture
def client(isolated_paths) -> TestClient:
    _seed_models(isolated_paths / "models")
    import importlib

    import api.main as api_main
    import api.model_loader as ml

    importlib.reload(ml)
    importlib.reload(api_main)
    return TestClient(api_main.app)


class TestHealth:
    def test_returns_ok_with_loaded_models(self, client: TestClient) -> None:
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["models_loaded"] is True
        assert "Breakage" in data["type_classes"]


class TestPredict:
    BASE_READING = {
        "machine_id": 1,
        "target_cycle": 30,
        "consumption_kWh": 18.0,
        "temperature_C": 65.0,
        "vibration": 1.2,
        "pressure": 50.0,
        "cycle_duration": 35.0,
        "rpm": 1500.0,
        "voltage": 230.0,
    }

    def test_single_prediction(self, client: TestClient) -> None:
        r = client.post("/predict", json={"readings": [self.BASE_READING]})
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["predictions"]) == 1
        pred = body["predictions"][0]
        assert pred["machine_id"] == 1
        assert 0.0 <= pred["failure_probability"] <= 1.0
        assert pred["predicted_failure_type"] in {"none", "Breakage", "Overheat"}
        assert pred["alert_level"] in {"nominal", "warning", "critical"}
        # Somme des probabilités par type ≈ 1
        s = sum(pred["failure_type_probabilities"].values())
        assert abs(s - 1.0) < 1e-3

    def test_batch_prediction(self, client: TestClient) -> None:
        readings = [{**self.BASE_READING, "temperature_C": 50.0 + i} for i in range(10)]
        r = client.post("/predict", json={"readings": readings})
        assert r.status_code == 200
        assert len(r.json()["predictions"]) == 10

    def test_rejects_empty_payload(self, client: TestClient) -> None:
        r = client.post("/predict", json={"readings": []})
        assert r.status_code == 422

    def test_rejects_out_of_range(self, client: TestClient) -> None:
        r = client.post("/predict", json={"readings": [{**self.BASE_READING, "temperature_C": 500.0}]})
        assert r.status_code == 422


class TestMetrics:
    def test_metrics_endpoint_prometheus_format(self, client: TestClient) -> None:
        r = client.get("/metrics")
        assert r.status_code == 200
        # Format Prometheus standard généré par prometheus_client
        body = r.text
        assert "# HELP" in body
        assert "# TYPE" in body
        assert "mecha_api_predict_requests_total" in body
