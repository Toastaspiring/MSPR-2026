"""Entraînement des modèles MECHA sur le dataset réel.

Trois modèles complémentaires :
  - **classifier_failure**  (Random Forest, binaire) : P(défaillance imminente)
  - **classifier_type**     (Random Forest, multi-classes) :
        Breakage / Overheat / none
  - **regressor_cycle**     (Gradient Boosting) : heures avant la prochaine
        intervention (RUL — Remaining Useful Life)

Suivi des expériences via MLflow (tracking local sur le volume models-store).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import mlflow
import mlflow.sklearn
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    mean_absolute_error,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder

from common.config import settings
from common.logger import setup_logger

log = setup_logger("trainer")

# Toutes les features numériques disponibles dans Gold
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

NO_FAILURE_LABEL = "none"


def _latest_gold_dataset(gold_dir: Path) -> Path | None:
    files = sorted(gold_dir.glob("gold_*.parquet"))
    return files[-1] if files else None


def _prepare_dataset(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, pd.Series, pd.Series]:
    """Renvoie X et 3 cibles : failure (binaire), failure_type (multi), rul (heures).

    Schéma canonique du notebook : `failure` est ternaire (0/1/2).
    Pour le classifier binaire on agrège : (failure > 0) => panne en cours.
    Le label multi-classes `failure_type` reste textuel (none/Breakage/Overheat).
    """
    missing = [c for c in FEATURE_COLUMNS if c not in df.columns]
    if missing:
        raise RuntimeError(f"Colonnes attendues manquantes dans Gold : {missing}")

    X = df[FEATURE_COLUMNS].astype(float).fillna(0.0)
    # `failure` 0/1/2 -> binaire (panne ou non)
    y_failure = (df["failure"].astype(int) > 0).astype(int)
    y_failure_type = df.get("failure_type", pd.Series([NO_FAILURE_LABEL] * len(df))).fillna(NO_FAILURE_LABEL)

    # RUL = heures avant la PROCHAINE intervention (par machine). On le
    # déduit de `hours_since_last_intervention` en prenant son symétrique :
    # plus on est loin de la dernière intervention, plus on est proche de
    # la suivante (proxy raisonnable en absence d'horodatage explicite des
    # interventions à venir). On clippe entre 0 et target_cycle * 2.
    rul_proxy = (df["target_cycle"] - df["hours_since_last_intervention"]).clip(lower=0)
    rul_proxy = rul_proxy.where(rul_proxy.notna(), df["target_cycle"])

    return X, y_failure, y_failure_type, rul_proxy.astype(float)


def _train_binary_classifier(X: pd.DataFrame, y: pd.Series) -> tuple[RandomForestClassifier, dict]:
    stratify = y if y.nunique() > 1 else None
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=stratify)
    clf = RandomForestClassifier(
        n_estimators=200,
        max_depth=12,
        n_jobs=-1,
        random_state=42,
        class_weight="balanced",
    )
    clf.fit(X_train, y_train)
    y_pred = clf.predict(X_test)
    metrics = {
        "accuracy": float(accuracy_score(y_test, y_pred)),
        "f1": float(f1_score(y_test, y_pred, zero_division=0)),
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
    }
    if clf.n_classes_ > 1:
        proba = clf.predict_proba(X_test)[:, 1]
        metrics["roc_auc"] = float(roc_auc_score(y_test, proba))
    log.info("Classifier (binaire) — metrics : {}", metrics)
    return clf, metrics


def _train_type_classifier(X: pd.DataFrame, y_str: pd.Series) -> tuple[RandomForestClassifier, LabelEncoder, dict]:
    encoder = LabelEncoder().fit(y_str)
    y = encoder.transform(y_str)

    stratify = y if pd.Series(y).nunique() > 1 else None
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=stratify)
    clf = RandomForestClassifier(
        n_estimators=200,
        max_depth=12,
        n_jobs=-1,
        random_state=42,
        class_weight="balanced",
    )
    clf.fit(X_train, y_train)
    metrics = {
        "accuracy": float(accuracy_score(y_test, clf.predict(X_test))),
        "macro_f1": float(f1_score(y_test, clf.predict(X_test), average="macro", zero_division=0)),
        "classes": list(map(str, encoder.classes_)),
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
    }
    log.info("Classifier (type) — metrics : {}", metrics)
    return clf, encoder, metrics


def _train_regressor(X: pd.DataFrame, y: pd.Series) -> tuple[GradientBoostingRegressor, dict]:
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    reg = GradientBoostingRegressor(n_estimators=200, max_depth=4, learning_rate=0.05, random_state=42)
    reg.fit(X_train, y_train)
    y_pred = reg.predict(X_test)
    metrics = {
        "mae": float(mean_absolute_error(y_test, y_pred)),
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
    }
    log.info("Regressor (RUL) — metrics : {}", metrics)
    return reg, metrics


def run() -> None:
    log.info("=== Démarrage de l'entraînement — site={} ===", settings.app_site_id)
    settings.paths.ensure()

    gold = _latest_gold_dataset(settings.paths.gold)
    if gold is None:
        raise RuntimeError("Gold layer empty — lancer l'ETL d'abord.")

    df = pd.read_parquet(gold)
    log.info("Dataset Gold chargé : {} ({} lignes, {} machines)", gold.name, len(df), df["machine_id"].nunique())

    X, y_failure, y_type, y_rul = _prepare_dataset(df)

    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    mlflow.set_experiment(settings.mlflow_experiment)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    with mlflow.start_run(run_name=f"train-{stamp}"):
        mlflow.log_param("site_id", settings.app_site_id)
        mlflow.log_param("n_samples", len(X))
        mlflow.log_param("n_machines", df["machine_id"].nunique())

        clf_fail, clf_fail_metrics = _train_binary_classifier(X, y_failure)
        for k, v in clf_fail_metrics.items():
            if isinstance(v, (int, float)):
                mlflow.log_metric(f"clf_failure_{k}", v)
        mlflow.sklearn.log_model(clf_fail, "classifier_failure")

        clf_type, encoder, clf_type_metrics = _train_type_classifier(X, y_type)
        for k, v in clf_type_metrics.items():
            if isinstance(v, (int, float)):
                mlflow.log_metric(f"clf_type_{k}", v)
        mlflow.sklearn.log_model(clf_type, "classifier_type")

        reg, reg_metrics = _train_regressor(X, y_rul)
        for k, v in reg_metrics.items():
            mlflow.log_metric(f"reg_{k}", v)
        mlflow.sklearn.log_model(reg, "regressor_rul")

    # Persistance pour l'API
    paths = settings.paths.models
    joblib.dump(clf_fail, paths / "classifier_failure.joblib")
    joblib.dump(clf_type, paths / "classifier_type.joblib")
    joblib.dump(encoder, paths / "type_encoder.joblib")
    joblib.dump(reg, paths / "regressor_rul.joblib")

    metadata = {
        "trained_at": stamp,
        "site_id": settings.app_site_id,
        "feature_columns": FEATURE_COLUMNS,
        "failure_metrics": clf_fail_metrics,
        "failure_type_metrics": clf_type_metrics,
        "rul_metrics": reg_metrics,
        "n_machines": int(df["machine_id"].nunique()),
        "source_dataset": gold.name,
        "type_classes": [str(c) for c in encoder.classes_],
    }
    (paths / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    log.info("Modèles persistés dans {}", paths)
    log.info("=== Entraînement terminé ===")
