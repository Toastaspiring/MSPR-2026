"""Tests unitaires du mode DEMO — logique pure (sans I/O HTTP/SQL)."""

from __future__ import annotations

import pandas as pd

from demo.streamer import (
    SENSOR_COLS,
    clamp_sensor_values,
    iter_ticks,
    predict_readings,
    sensor_records,
    synthesize_frame,
)


def test_synthesize_frame_shape_and_columns():
    df = synthesize_frame(n_machines=3, n_points=48, seed=7)
    assert len(df) == 3 * 48
    for col in SENSOR_COLS:
        assert col in df.columns
    assert set(df["machine_id"].unique()) == {1, 2, 3}
    # timestamps tz-aware UTC, triés
    assert str(df["timestamp"].dt.tz) == "UTC"
    assert df["timestamp"].is_monotonic_increasing


def test_synthesize_frame_injects_anomalies():
    df = synthesize_frame(n_machines=4, n_points=200, seed=1)
    # Au moins une ligne en anomalie (failure != 0) doit être générée.
    assert (df["failure"] != 0).any()
    assert set(df["failure"].unique()).issubset({0, 1, 2})


def test_synthesize_frame_is_deterministic():
    a = synthesize_frame(2, 24, seed=123)
    b = synthesize_frame(2, 24, seed=123)
    pd.testing.assert_frame_equal(a, b)


def test_clamp_sensor_values_bounds():
    rec = {
        "temperature_C": 999.0,  # > 200
        "vibration": -5.0,  # < 0
        "rpm": 99999.0,  # > 5000
        "voltage": 230.0,  # ok
    }
    out = clamp_sensor_values(rec)
    assert out["temperature_C"] == 200.0
    assert out["vibration"] == 0.0
    assert out["rpm"] == 5000.0
    assert out["voltage"] == 230.0


def test_sensor_records_restamps_and_types():
    df = synthesize_frame(2, 5, seed=2)
    tick = df.head(2)
    now = pd.Timestamp("2030-01-01T12:00:00Z")
    records = sensor_records(tick, now)
    assert len(records) == 2
    for rec in records:
        assert rec["timestamp"] == now.to_pydatetime()
        assert isinstance(rec["machine_id"], int)
        assert isinstance(rec["target_cycle"], int)
        assert isinstance(rec["failure"], int)
        assert set(rec).issubset(set(SENSOR_COLS))


def test_predict_readings_has_required_fields_within_bounds():
    df = synthesize_frame(1, 3, seed=3)
    readings = predict_readings(df)
    assert len(readings) == 3
    required = {
        "machine_id",
        "target_cycle",
        "consumption_kWh",
        "temperature_C",
        "vibration",
        "pressure",
        "cycle_duration",
        "rpm",
        "voltage",
    }
    for r in readings:
        assert required.issubset(set(r))
        assert 0 <= r["temperature_C"] <= 200
        assert 0 <= r["vibration"] <= 50
        assert 0 <= r["rpm"] <= 5000


def test_predict_readings_strips_extra_features():
    """SensorReading côté API a extra='forbid' : le streamer doit filtrer les
    colonnes non-DBSCAN pour éviter un 422 pendant la démo."""
    df = synthesize_frame(1, 2, seed=4)
    df["temperature_C_roll_mean_10"] = 50.0
    df["hours_since_last_intervention"] = 12.0
    df["failure"] = 1
    readings = predict_readings(df)
    for r in readings:
        assert "temperature_C_roll_mean_10" not in r
        assert "hours_since_last_intervention" not in r
        assert "failure" not in r
        assert "timestamp" not in r


def test_iter_ticks_fixed_rows():
    df = synthesize_frame(2, 5, seed=5)  # 10 lignes
    ticks = list(iter_ticks(df, rows_per_tick=4))
    assert [len(t) for t in ticks] == [4, 4, 2]


def test_iter_ticks_group_by_timestamp():
    df = synthesize_frame(3, 4, seed=6)  # 3 machines × 4 timestamps
    ticks = list(iter_ticks(df, rows_per_tick=0))
    assert len(ticks) == 4  # un tick par timestamp distinct
    for t in ticks:
        assert len(t) == 3  # 3 machines par timestamp
