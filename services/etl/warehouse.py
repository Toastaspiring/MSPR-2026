"""Chargement des tables opérationnelles dans Postgres pour Grafana.

Les Parquet Silver/Gold restent la source de vérité (audit, retraining).
Postgres sert de **datastore opérationnel** : Grafana le lit pour
afficher les séries temporelles, les interventions et les dernières
features de chaque machine.
"""

from __future__ import annotations

import os

import pandas as pd

from common.logger import setup_logger

log = setup_logger("etl")

# Colonnes que l'on stocke dans Postgres pour les séries Silver.
# Les 12 colonnes de traçabilité produites par le pipeline canonique ne sont
# PAS chargées en BDD (audit-only) : on les conserve dans les Parquet Silver.
_SENSOR_COLS = [
    "machine_id",
    "target_cycle",
    "timestamp",
    "consumption_kWh",
    "temperature_C",
    "vibration",
    "pressure",
    "cycle_duration",
    "rpm",
    "voltage",
    "failure",
]

# Colonnes attendues côté `feature_snapshot` Postgres (cf. init SQL).
_FEATURE_SNAPSHOT_COLS = [
    *_SENSOR_COLS,
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
    "failure_type",
]


def _engine():
    """Connecte à Postgres via sqlalchemy (import paresseux pour les tests)."""
    from sqlalchemy import create_engine

    url = os.environ.get("POSTGRES_DSN")
    if not url:
        raise RuntimeError("POSTGRES_DSN absent — alimentation BDD impossible.")
    return create_engine(url, pool_pre_ping=True, future=True)


def upsert_silver_to_postgres(
    df_silver: pd.DataFrame,
    df_interventions: pd.DataFrame,
    df_gold: pd.DataFrame,
) -> None:
    """Charge Silver + Interventions + dernier snapshot Gold dans Postgres.

    Stratégie : `TRUNCATE` puis `COPY` pour rester simple et idempotent.
    Volumétrie attendue : quelques dizaines de milliers de lignes / machine.
    """
    if df_silver.empty:
        log.info("Postgres : Silver vide, on saute le chargement.")
        return

    engine = _engine()

    # 1) sensor_data : séries Silver complètes
    payload = df_silver[[c for c in _SENSOR_COLS if c in df_silver.columns]].copy()
    payload["timestamp"] = pd.to_datetime(payload["timestamp"], utc=True)
    with engine.begin() as conn:
        conn.exec_driver_sql("TRUNCATE TABLE sensor_data")
        payload.to_sql("sensor_data", conn, if_exists="append", index=False, method="multi", chunksize=5000)
    log.info("Postgres : sensor_data rechargée ({} lignes)", len(payload))

    # 2) interventions
    if not df_interventions.empty:
        ints = df_interventions.copy()
        ints["timestamp"] = pd.to_datetime(ints["timestamp"], utc=True)
        with engine.begin() as conn:
            conn.exec_driver_sql("TRUNCATE TABLE interventions")
            ints.to_sql("interventions", conn, if_exists="append", index=False, method="multi", chunksize=5000)
        log.info("Postgres : interventions rechargée ({} lignes)", len(ints))

    # 3) feature_snapshot : dernier point Gold par machine (pour scoring rapide).
    # On filtre les colonnes pour matcher exactement le schéma SQL (traçabilité ignorée).
    if df_gold is not None and not df_gold.empty:
        last = df_gold.sort_values("timestamp").groupby("machine_id").tail(1).reset_index(drop=True)
        last["timestamp"] = pd.to_datetime(last["timestamp"], utc=True)
        # Garde-fou explicite : les colonnes NOT NULL côté Postgres doivent
        # exister dans le DataFrame, sinon on lève AVANT le `to_sql` pour
        # obtenir un message d'erreur clair (vs. erreur SQL cryptique).
        required_cols = {"machine_id", "target_cycle", "timestamp"}
        missing = required_cols - set(last.columns)
        if missing:
            raise RuntimeError(f"feature_snapshot : colonnes NOT NULL manquantes dans Gold : {sorted(missing)}")
        # Sélection dans l'ordre exact défini ; les colonnes optionnelles
        # absentes sont insérées en NaN.
        for col in _FEATURE_SNAPSHOT_COLS:
            if col not in last.columns:
                last[col] = pd.NA
        last = last[_FEATURE_SNAPSHOT_COLS]
        with engine.begin() as conn:
            conn.exec_driver_sql("TRUNCATE TABLE feature_snapshot")
            last.to_sql(
                "feature_snapshot",
                conn,
                if_exists="append",
                index=False,
                method="multi",
                chunksize=100,
            )
        log.info("Postgres : feature_snapshot rechargée ({} machines)", len(last))
