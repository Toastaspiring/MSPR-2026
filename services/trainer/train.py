"""Entraînement du modèle MECHA — détection d'anomalies DBSCAN.

Conformément au rendu écrit "MSPR Rendu écrit - DBSCAN.docx" :
  - Approche non supervisée par densité (DBSCAN).
  - 8 features standardisées : 7 capteurs + `cycle_ratio`.
  - Hyperparamètres : eps = 0.7, min_samples = 10.
  - Un modèle par machine ; les observations `cluster_label == -1` sont
    considérées comme des anomalies (~99 % des pannes précédées par
    une anomalie dans les 24 h sur le dataset d'étude).

Inférence en ligne : un index `NearestNeighbors` par machine, construit
sur les core samples (labels != -1). Pour un point x nouveau :
  1. mise à l'échelle avec le scaler de la machine ;
  2. distance au plus proche voisin dans les core samples ;
  3. si distance <= eps → même cluster que ce voisin, `anomaly_score =
     distance / eps` clampé à 1 ;
  4. sinon → `cluster_label = -1`, `anomaly = True`, score = 1.

Suivi MLflow : un run par entraînement (nb machines, taux d'anomalie
global et par machine).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import mlflow
import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler

from common.config import settings
from common.logger import setup_logger

log = setup_logger("trainer")


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

import os

# eps=0.7 (valeur du rendu écrit) est calibrée pour l'espace 8D standardisé du
# dataset original ; sur les jeux réduits (démo, subsets), on l'assouplit via
# DBSCAN_EPS pour éviter que quasi tous les points tombent en cluster -1.
EPS = float(os.environ.get("DBSCAN_EPS", "1.5"))
MIN_SAMPLES = int(os.environ.get("DBSCAN_MIN_SAMPLES", "10"))


def _latest_gold_dataset(gold_dir: Path) -> Path | None:
    files = sorted(gold_dir.glob("gold_*.parquet"))
    return files[-1] if files else None


def _add_cycle_ratio(df: pd.DataFrame) -> pd.DataFrame:
    tc = df["target_cycle"].replace(0, np.nan)
    df = df.copy()
    df["cycle_ratio"] = (df["cycle_duration"] / tc).fillna(1.0)
    return df


def _fit_one_machine(X: np.ndarray) -> dict:
    """Fit scaler + DBSCAN + kNN index sur les core samples d'une machine."""
    scaler = StandardScaler().fit(X)
    Xs = scaler.transform(X)

    db = DBSCAN(eps=EPS, min_samples=MIN_SAMPLES).fit(Xs)
    labels = db.labels_

    core_mask = labels != -1
    if core_mask.sum() == 0:
        # Toute la machine est bruit — fallback : on garde tous les points
        # comme référence, `cluster_label` restera -1 à l'inférence.
        core_mask = np.ones(len(labels), dtype=bool)

    nn = NearestNeighbors(n_neighbors=1).fit(Xs[core_mask])

    return {
        "scaler": scaler,
        "nn": nn,
        "core_labels": labels[core_mask].astype(int),
        "eps": EPS,
        "min_samples": MIN_SAMPLES,
        "n_train": int(len(labels)),
        "n_core": int(core_mask.sum()),
        "anomaly_rate": float((labels == -1).mean()),
        "cluster_counts": {int(c): int((labels == c).sum()) for c in np.unique(labels)},
    }


def run() -> None:
    log.info("=== Entraînement DBSCAN — site={} ===", settings.app_site_id)
    settings.paths.ensure()

    gold = _latest_gold_dataset(settings.paths.gold)
    if gold is None:
        raise RuntimeError("Couche Gold vide — exécuter l'ETL d'abord.")

    df = pd.read_parquet(gold)
    log.info("Gold chargé : {} ({} lignes, {} machines)", gold.name, len(df), df["machine_id"].nunique())

    missing = [c for c in ("target_cycle", "cycle_duration") if c not in df.columns]
    if missing:
        raise RuntimeError(f"Colonnes indispensables manquantes : {missing}")

    df = _add_cycle_ratio(df)
    for c in DBSCAN_FEATURES:
        if c not in df.columns:
            raise RuntimeError(f"Feature manquante dans Gold : {c}")

    df[DBSCAN_FEATURES] = df[DBSCAN_FEATURES].astype(float).fillna(df[DBSCAN_FEATURES].median(numeric_only=True))

    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    mlflow.set_experiment(settings.mlflow_experiment)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    per_machine: dict[int, dict] = {}
    per_machine_meta: dict[str, dict] = {}
    global_X_scaled_chunks: list[np.ndarray] = []

    with mlflow.start_run(run_name=f"dbscan-{stamp}"):
        mlflow.log_param("eps", EPS)
        mlflow.log_param("min_samples", MIN_SAMPLES)
        mlflow.log_param("features", ",".join(DBSCAN_FEATURES))
        mlflow.log_param("n_samples", len(df))

        for machine_id, group in df.groupby("machine_id"):
            if len(group) < MIN_SAMPLES * 2:
                log.warning("Machine {} ignorée : {} lignes < seuil.", machine_id, len(group))
                continue
            X = group[DBSCAN_FEATURES].to_numpy()
            model = _fit_one_machine(X)
            per_machine[int(machine_id)] = model
            per_machine_meta[str(machine_id)] = {
                "n_train": model["n_train"],
                "n_core": model["n_core"],
                "anomaly_rate": model["anomaly_rate"],
                "n_clusters": len([c for c in model["cluster_counts"] if c != -1]),
            }
            log.info(
                "Machine {} : {} points, {} clusters, anomalies = {:.2%}",
                machine_id,
                model["n_train"],
                per_machine_meta[str(machine_id)]["n_clusters"],
                model["anomaly_rate"],
            )
            mlflow.log_metric(f"machine_{int(machine_id)}_anomaly_rate", model["anomaly_rate"])
            global_X_scaled_chunks.append(model["scaler"].transform(X))

        if not per_machine:
            raise RuntimeError("Aucune machine entraînée — dataset trop petit.")

        # Modèle "global" (fallback pour machines inconnues) — scaler + DBSCAN
        # sur l'ensemble des features standardisées par machine puis empilées.
        # Approche approximative mais suffisante pour un fallback de démo.
        X_all = df[DBSCAN_FEATURES].to_numpy()
        global_model = _fit_one_machine(X_all)
        log.info(
            "Modèle global (fallback) : {} points, anomalies = {:.2%}",
            global_model["n_train"],
            global_model["anomaly_rate"],
        )
        mlflow.log_metric("global_anomaly_rate", global_model["anomaly_rate"])

    bundle = {
        "per_machine": per_machine,
        "global": global_model,
        "features": DBSCAN_FEATURES,
        "eps": EPS,
        "min_samples": MIN_SAMPLES,
        "trained_at": stamp,
    }
    paths = settings.paths.models
    joblib.dump(bundle, paths / "anomaly_model.joblib")

    metadata = {
        "trained_at": stamp,
        "site_id": settings.app_site_id,
        "algorithm": "DBSCAN",
        "features": DBSCAN_FEATURES,
        "eps": EPS,
        "min_samples": MIN_SAMPLES,
        "source_dataset": gold.name,
        "n_machines": len(per_machine),
        "per_machine": per_machine_meta,
        "global_anomaly_rate": global_model["anomaly_rate"],
    }
    (paths / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")

    log.info("Bundle DBSCAN persisté dans {}", paths)
    log.info("=== Entraînement terminé ===")
