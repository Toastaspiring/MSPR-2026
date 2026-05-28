"""Orchestration du pipeline ETL Bronze -> Silver -> Gold pour MECHA.

Bronze (CSV bruts mis à disposition par MECHA) :
  - `machine_X_targetcycleN.csv`     -> séries temporelles capteurs
  - `intervention_data_machineN.csv` -> log des défaillances réelles

Silver / Gold : fichiers Parquet horodatés (compression snappy).

Postgres (couche opérationnelle pour Grafana) :
  - sensor_data        — colonnes capteurs Silver uniquement (sans
                         traçabilité, qui reste dans les Parquet pour
                         l'audit)
  - interventions      — log Silver des défaillances
  - feature_snapshot   — dernier point Gold par machine (scoring rapide)

Logique de transformation Bronze -> Silver : version canonique du notebook
MECHA (cf. `bronze_to_silver_functions.transform_bronze_to_silver`).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from common.config import settings
from common.logger import setup_logger

from .bronze_to_silver_functions import (
    interventions_bronze_to_silver,
    load_bronze_csv,
    parse_intervention_filename,
    parse_timeseries_filename,
    silver_to_gold,
    transform_bronze_to_silver_with_context,
)
from .warehouse import upsert_silver_to_postgres

log = setup_logger("etl")


# ---------------------------------------------------------------------------
# Helpers I/O
# ---------------------------------------------------------------------------
def _write_layer(df: pd.DataFrame, output_dir: Path, layer: str) -> Path | None:
    if df.empty:
        log.warning("Couche {} : DataFrame vide, rien à écrire.", layer)
        return None
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_file = output_dir / f"{layer}_{stamp}.parquet"
    df.to_parquet(out_file, index=False, compression="snappy")
    log.info(
        "{} : écrit {} ({} lignes, {} colonnes)",
        layer.title(),
        out_file.name,
        len(df),
        len(df.columns),
    )
    return out_file


# ---------------------------------------------------------------------------
# Ingestion Bronze -> Silver
# ---------------------------------------------------------------------------
def _ingest_timeseries(bronze_dir: Path) -> pd.DataFrame:
    """Concatène toutes les séries `machine_*_targetcycle*.csv` après transform canonique."""
    files = sorted(bronze_dir.glob("machine_*_targetcycle*.csv"))
    if not files:
        log.warning("Aucun fichier de séries temporelles trouvé dans {}", bronze_dir)
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    for f in files:
        meta = parse_timeseries_filename(f)
        if meta is None:
            log.warning("Nom de fichier non reconnu : {}", f.name)
            continue
        machine_id, target_cycle = meta
        try:
            df_bronze = load_bronze_csv(f)
        except Exception as exc:  # noqa: BLE001
            log.error("Erreur de lecture {} : {}", f.name, exc)
            continue
        if df_bronze.empty:
            continue
        try:
            silver = transform_bronze_to_silver_with_context(
                df_bronze, machine_id, target_cycle
            )
        except Exception as exc:  # noqa: BLE001
            log.error(
                "Erreur de transformation {} : machine={} target_cycle={}h : {}",
                f.name,
                machine_id,
                target_cycle,
                exc,
            )
            continue
        log.info(
            "Silver série canonique : machine={} target_cycle={}h -> {} lignes",
            machine_id,
            target_cycle,
            len(silver),
        )
        frames.append(silver)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _ingest_interventions(bronze_dir: Path) -> pd.DataFrame:
    """Concatène tous les fichiers `intervention_data_machineN.csv`."""
    files = sorted(bronze_dir.glob("intervention_data_machine*.csv"))
    if not files:
        log.info("Aucun fichier d'interventions trouvé (pas bloquant).")
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    for f in files:
        machine_id = parse_intervention_filename(f)
        if machine_id is None:
            log.warning("Nom de fichier d'intervention non reconnu : {}", f.name)
            continue
        try:
            # On réutilise le même loader que pour les séries — logging
            # uniforme et future validation/encodage centralisés.
            df_bronze = load_bronze_csv(f)
        except Exception as exc:  # noqa: BLE001
            log.error("Erreur de lecture {} : {}", f.name, exc)
            continue
        if df_bronze.empty:
            continue
        silver = interventions_bronze_to_silver(df_bronze, machine_id)
        log.info("Silver interventions : machine={} -> {} lignes", machine_id, len(silver))
        frames.append(silver)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------
def run() -> None:
    log.info("=== Démarrage du pipeline ETL — site={} ===", settings.app_site_id)
    settings.paths.ensure()

    # ---- Silver --------------------------------------------------------
    df_silver_ts = _ingest_timeseries(settings.paths.bronze)
    if df_silver_ts.empty:
        log.warning("Aucune série temporelle Silver — fin du pipeline.")
        return

    df_silver_int = _ingest_interventions(settings.paths.bronze)

    _write_layer(df_silver_ts, settings.paths.silver, "silver_sensor")
    if not df_silver_int.empty:
        _write_layer(df_silver_int, settings.paths.silver, "silver_interventions")

    # ---- Gold ----------------------------------------------------------
    df_gold = silver_to_gold(df_silver_ts, df_silver_int)
    gold_path = _write_layer(df_gold, settings.paths.gold, "gold")

    # ---- Postgres (couche opérationnelle Grafana) ----------------------
    try:
        upsert_silver_to_postgres(df_silver_ts, df_silver_int, df_gold)
    except Exception as exc:  # noqa: BLE001
        log.warning("Postgres indisponible — Parquet écrits, alimentation BDD ignorée : {}", exc)

    log.info(
        "=== Pipeline ETL terminé : {} machines, {} lignes Gold ({}) ===",
        df_silver_ts["machine_id"].nunique() if not df_silver_ts.empty else 0,
        len(df_gold),
        gold_path.name if gold_path else "n/a",
    )
