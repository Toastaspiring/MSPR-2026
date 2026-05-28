"""Fonctions de transformation Bronze → Silver pour le dataset MECHA réel.

Schéma source (Bronze) :
  - `machine_X_targetcycleN.csv` : séries temporelles capteurs (1 ligne / heure)
        timestamp, consumption_kWh, temperature_C, vibration, pressure,
        cycle_duration, rpm, voltage, failure
  - `intervention_data_machineN.csv` : log des défaillances réelles
        timestamp, failure_type (Breakage/Overheat), temperature, rpm,
        vibration, pressure

Ces fonctions sont pures (sans I/O), elles sont testables unitairement
avec pytest (cf. section 5.2 du document d'architecture).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

# Colonnes capteurs attendues côté séries temporelles
SENSOR_COLUMNS: tuple[str, ...] = (
    "consumption_kWh",
    "temperature_C",
    "vibration",
    "pressure",
    "cycle_duration",
    "rpm",
    "voltage",
)

# Colonnes attendues en sortie Silver
SILVER_COLUMNS: tuple[str, ...] = (
    "machine_id",
    "target_cycle",
    "timestamp",
    *SENSOR_COLUMNS,
    "failure",
)

# Plages physiques pour le bornage des outliers
# (valeurs établies à partir d'une inspection rapide du jeu MECHA)
SENSOR_RANGES: dict[str, tuple[float, float]] = {
    "consumption_kWh": (0.0, 1000.0),
    "temperature_C": (-20.0, 200.0),
    "vibration": (0.0, 50.0),
    "pressure": (0.0, 200.0),
    "cycle_duration": (0.0, 300.0),
    "rpm": (0.0, 5000.0),
    "voltage": (0.0, 500.0),
}

# Types de défaillance connus (label multi-classes)
FAILURE_TYPES: tuple[str, ...] = ("Breakage", "Overheat")
NO_FAILURE_LABEL = "none"


# ---------------------------------------------------------------------------
# Parsing du nom de fichier — extraction machine_id et target_cycle
# ---------------------------------------------------------------------------
_TS_PATTERN = re.compile(r"machine_(\d+)_targetcycle(\d+)\.csv$", re.IGNORECASE)
_INT_PATTERN = re.compile(r"intervention_data_machine(\d+)\.csv$", re.IGNORECASE)


def parse_timeseries_filename(filename: str | Path) -> tuple[int, int] | None:
    """`machine_2_targetcycle60.csv` → `(machine_id=2, target_cycle=60)`."""
    name = Path(filename).name
    m = _TS_PATTERN.search(name)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def parse_intervention_filename(filename: str | Path) -> int | None:
    """`intervention_data_machine3.csv` → `machine_id=3`."""
    name = Path(filename).name
    m = _INT_PATTERN.search(name)
    if not m:
        return None
    return int(m.group(1))


# ---------------------------------------------------------------------------
# Helpers génériques (réutilisés par tous les pipelines)
# ---------------------------------------------------------------------------
def parse_timestamps(df: pd.DataFrame, column: str = "timestamp") -> pd.DataFrame:
    """Convertit `timestamp` en datetime UTC tz-aware. Invalides → NaT."""
    out = df.copy()
    out[column] = pd.to_datetime(out[column], errors="coerce", utc=True)
    return out


def cast_numeric(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    """Force le type numérique ; valeurs non convertibles → NaN."""
    out = df.copy()
    for col in columns:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def clip_outliers(df: pd.DataFrame, ranges: dict[str, tuple[float, float]]) -> pd.DataFrame:
    """Borne les valeurs hors plage physique sans supprimer la ligne."""
    out = df.copy()
    for col, (low, high) in ranges.items():
        if col in out.columns:
            out[col] = out[col].clip(lower=low, upper=high)
    return out


def impute_sensor_nulls(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    """Interpolation linéaire par machine, puis forward/back-fill.

    Conserve la séquence temporelle des capteurs : un trou est comblé par
    la moyenne entre les valeurs encadrantes, beaucoup plus utile pour les
    fenêtres glissantes que de supprimer la ligne.
    """
    out = df.sort_values(["machine_id", "timestamp"]).copy()
    cols = [c for c in columns if c in out.columns]
    if not cols:
        return out

    parts: list[pd.DataFrame] = []
    for _, g in out.groupby("machine_id", sort=False):
        g = g.copy()
        g[cols] = g[cols].interpolate(method="linear", limit_direction="both")
        g[cols] = g[cols].ffill().bfill()
        parts.append(g)
    return pd.concat(parts, ignore_index=True) if parts else out


def deduplicate(df: pd.DataFrame, keys: Iterable[str]) -> pd.DataFrame:
    """Déduplique en gardant la dernière mesure."""
    return df.sort_values(list(keys)).drop_duplicates(subset=list(keys), keep="last").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Bronze → Silver — séries temporelles capteurs
# ---------------------------------------------------------------------------
def timeseries_bronze_to_silver(
    df_bronze: pd.DataFrame,
    machine_id: int,
    target_cycle: int,
) -> pd.DataFrame:
    """Pipeline complet pour un fichier `machine_X_targetcycleN.csv`.

    Étapes :
      1. Ajout des colonnes contextuelles `machine_id` + `target_cycle`
      2. Parsing des timestamps
      3. Cast numérique des 7 capteurs + `failure`
      4. Bornage des outliers selon SENSOR_RANGES
      5. Imputation des trous capteur (interpolation linéaire)
      6. Suppression des lignes sans timestamp valide
      7. Déduplication (machine_id, timestamp) — dernière mesure conservée
    """
    df = df_bronze.copy()
    df["machine_id"] = int(machine_id)
    df["target_cycle"] = int(target_cycle)

    df = parse_timestamps(df, "timestamp")
    df = cast_numeric(df, [*SENSOR_COLUMNS, "failure"])
    df = clip_outliers(df, SENSOR_RANGES)
    df = impute_sensor_nulls(df, SENSOR_COLUMNS)

    # Le label `failure` peut comporter des trous — on les considère comme 0
    # (pas de défaillance déclarée). Les vraies défaillances seront enrichies
    # par le merge avec les interventions plus tard.
    df["failure"] = df["failure"].fillna(0).clip(lower=0, upper=1).astype(int)

    df = df.dropna(subset=["timestamp"]).reset_index(drop=True)
    df = deduplicate(df, ("machine_id", "timestamp"))

    # Re-ordonne les colonnes pour Silver
    cols = [c for c in SILVER_COLUMNS if c in df.columns]
    return df[cols].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Bronze → Silver — interventions (défaillances déclarées)
# ---------------------------------------------------------------------------
def interventions_bronze_to_silver(
    df_bronze: pd.DataFrame,
    machine_id: int,
) -> pd.DataFrame:
    """Nettoyage du fichier interventions pour une machine donnée."""
    df = df_bronze.copy()
    df["machine_id"] = int(machine_id)
    df = parse_timestamps(df, "timestamp")
    df["failure_type"] = (
        df["failure_type"].astype(str).str.strip().where(df["failure_type"].isin(FAILURE_TYPES), other=pd.NA)
    )
    df = df.dropna(subset=["timestamp", "failure_type"]).reset_index(drop=True)
    keep = ["machine_id", "timestamp", "failure_type", "temperature", "rpm", "vibration", "pressure"]
    return df[[c for c in keep if c in df.columns]].sort_values(["machine_id", "timestamp"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Silver → Gold — feature engineering
# ---------------------------------------------------------------------------
def silver_to_gold(
    df_silver: pd.DataFrame,
    df_interventions: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Construit les features prêtes pour l'entraînement ML.

    Features dérivées :
      - rolling mean/std sur 10 mesures (par machine) pour les capteurs clés
      - delta (gradient temporel) pour température, vibration, pression
      - load_proxy = rpm × pressure / (voltage + ε)
      - hours_since_last_intervention (jointure as-of avec interventions)
      - failure_type (label multi-classes) — joint depuis interventions
        avec une fenêtre de tolérance de ±1 h autour du timestamp.
    """
    if df_silver.empty:
        return df_silver.copy()

    df = df_silver.sort_values(["machine_id", "timestamp"]).copy()

    # Rolling features par machine
    grouped = df.groupby("machine_id", group_keys=False, sort=False)
    for col in ("temperature_C", "vibration", "pressure"):
        df[f"{col}_roll_mean_10"] = grouped[col].transform(lambda s: s.rolling(window=10, min_periods=1).mean())
        df[f"{col}_roll_std_10"] = grouped[col].transform(lambda s: s.rolling(window=10, min_periods=1).std().fillna(0))
        df[f"{col}_delta"] = grouped[col].transform(lambda s: s.diff().fillna(0))

    # Charge mécanique normalisée : rpm × pression / (voltage + ε)
    df["load_proxy"] = (df["rpm"] * df["pressure"]) / (df["voltage"].abs() + 1.0)

    # Energie sur le cycle
    df["energy_per_cycle"] = df["consumption_kWh"] * df["cycle_duration"]

    # Jointure as-of avec les interventions pour récupérer failure_type
    df["failure_type"] = NO_FAILURE_LABEL
    df["hours_since_last_intervention"] = np.nan

    if df_interventions is not None and not df_interventions.empty:
        df = _attach_intervention_context(df, df_interventions)

    # Si on n'a jamais vu d'intervention, on remplit par un horizon long
    df["hours_since_last_intervention"] = df["hours_since_last_intervention"].fillna(9999.0)

    return df.reset_index(drop=True)


def _attach_intervention_context(df_silver: pd.DataFrame, df_interventions: pd.DataFrame) -> pd.DataFrame:
    """Joint l'historique des interventions sur les séries temporelles.

    Pour chaque ligne capteur on ajoute :
      - `failure_type` : type de la dernière intervention dans une fenêtre
        de [-1h, +1h] autour du timestamp (sinon "none").
      - `hours_since_last_intervention` : âge en heures de la dernière
        intervention précédant (ou égalant) le timestamp courant.
    """
    df = df_silver.sort_values(["machine_id", "timestamp"]).copy()
    interv = df_interventions.sort_values(["machine_id", "timestamp"]).copy()

    out_parts: list[pd.DataFrame] = []
    for machine, group in df.groupby("machine_id", sort=False):
        sub_int = interv[interv["machine_id"] == machine].copy()
        g = group.sort_values("timestamp").copy()
        # Réinitialise les valeurs par défaut (déjà posées par silver_to_gold)
        g["failure_type"] = NO_FAILURE_LABEL
        g["hours_since_last_intervention"] = np.nan

        if sub_int.empty:
            out_parts.append(g)
            continue

        # 1) `hours_since_last_intervention` — merge_asof backward
        backward = pd.merge_asof(
            g[["timestamp"]].reset_index(drop=True),
            sub_int[["timestamp"]].rename(columns={"timestamp": "last_intervention_ts"}),
            left_on="timestamp",
            right_on="last_intervention_ts",
            direction="backward",
            allow_exact_matches=True,
        )
        hours = (backward["timestamp"] - backward["last_intervention_ts"]).dt.total_seconds() / 3600.0
        g["hours_since_last_intervention"] = hours.values

        # 2) `failure_type` — intervention la plus proche dans ±1h
        nearest = pd.merge_asof(
            g[["timestamp"]].reset_index(drop=True),
            sub_int[["timestamp", "failure_type"]].rename(columns={"failure_type": "_nearest_failure_type"}),
            on="timestamp",
            direction="nearest",
            tolerance=pd.Timedelta(hours=1),
        )
        mask = nearest["_nearest_failure_type"].notna().values
        if mask.any():
            g.loc[g.index[mask], "failure_type"] = nearest.loc[mask, "_nearest_failure_type"].values

        out_parts.append(g)

    return pd.concat(out_parts, ignore_index=True)
