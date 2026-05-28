"""
Fonctions de transformation Bronze -> Silver — version canonique notebook.

Source : pipeline validé dans le notebook Jupyter de MECHA (livré par l'équipe
data). Les fonctions sont volontairement séparées pour rendre le pipeline
lisible, testable et traçable.

Différences vs. un pipeline naïf :
  - `failure` est **ternaire** (0 = nominal, 1 = Breakage, 2 = Overheat)
  - **12 colonnes de traçabilité** ajoutées à chaque ligne pour expliquer les
    corrections appliquées (audit, RGPD, debug)
  - **Reconstruction complète de la grille horaire** entre min et max timestamp
  - **Détection d'outliers à 5σ** uniquement sur les lignes `failure=0`
    (les données en panne ne doivent pas polluer la moyenne)
  - **Corrections de `failure NaN`** par règles métier prenant en compte le
    rpm courant et les états avant/après
  - **Imputation des NaN numériques** par médiane des voisins valides non
    aberrants (fenêtre ±2 lignes)

Wrapper MECHA :
  - `transform_bronze_to_silver_with_context()` ajoute `machine_id` et
    `target_cycle` extraits du nom de fichier `machine_X_targetcycleN.csv`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

# Utilise le logger central du projet (`common.logger.logger`) au lieu d'importer
# loguru directement, pour bénéficier de la configuration uniforme (rotation,
# format JSON, sortie fichier) appliquée par `setup_logger()` côté services.
from common.logger import logger

EXPECTED_SCHEMA: Dict[str, str] = {
    "timestamp": "datetime",
    "failure": "int",
    "consumption_kWh": "float",
    "temperature_C": "float",
    "vibration": "float",
    "pressure": "float",
    "cycle_duration": "float",
    "rpm": "float",
    "voltage": "float",
}

BUSINESS_COLUMNS: List[str] = [
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

NUMERIC_SENSOR_COLUMNS: List[str] = [
    "consumption_kWh",
    "temperature_C",
    "vibration",
    "pressure",
    "cycle_duration",
    "rpm",
    "voltage",
]

# Colonnes de traçabilité produites par le pipeline (utiles à l'audit)
TRACEABILITY_COLUMNS: List[str] = [
    "is_outlier",
    "outlier_columns",
    "quality_flag",
    "correction_details",
    "is_missing_timestamp",
    "is_failure_nan_corrected",
    "failure_nan_correction_details",
    "is_duplicate_corrected",
    "duplicate_correction_details",
    "is_nan_corrected",
    "nan_columns",
    "nan_correction_details",
]

PHYSICAL_CONSTRAINTS: Dict[str, Tuple[float | None, float | None]] = {
    "consumption_kWh": (0, None),
    "temperature_C": (-50, 200),
    "vibration": (0, None),
    "pressure": (0, None),
    "cycle_duration": (0, None),
    "rpm": (0, None),
    "voltage": (0, None),
}

# Mapping `failure` (entier) -> libellé métier pour l'enrichissement Gold
FAILURE_LABEL: Dict[int, str] = {0: "none", 1: "Breakage", 2: "Overheat"}
FAILURE_TYPES: tuple[str, ...] = ("Breakage", "Overheat")
NO_FAILURE_LABEL = "none"


# ---------------------------------------------------------------------------
# Helpers fichiers MECHA — extraction machine_id / target_cycle
# ---------------------------------------------------------------------------
_TS_PATTERN = re.compile(r"machine_(\d+)_targetcycle(\d+)\.csv$", re.IGNORECASE)
_INT_PATTERN = re.compile(r"intervention_data_machine(\d+)\.csv$", re.IGNORECASE)


def parse_timeseries_filename(filename: str | Path) -> tuple[int, int] | None:
    """`machine_2_targetcycle60.csv` -> `(machine_id=2, target_cycle=60)`."""
    name = Path(filename).name
    m = _TS_PATTERN.search(name)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def parse_intervention_filename(filename: str | Path) -> int | None:
    """`intervention_data_machine3.csv` -> `machine_id=3`."""
    name = Path(filename).name
    m = _INT_PATTERN.search(name)
    if not m:
        return None
    return int(m.group(1))


# ---------------------------------------------------------------------------
# Pipeline canonique — code repris tel quel du notebook
# ---------------------------------------------------------------------------
def load_bronze_csv(input_path: str | Path) -> pd.DataFrame:
    """Charge un fichier CSV Bronze."""
    input_path = Path(input_path)
    logger.info("Chargement du fichier Bronze : {}", input_path)
    df = pd.read_csv(input_path)
    logger.info("Fichier chargé : {} lignes, {} colonnes", df.shape[0], df.shape[1])
    return df


def validate_schema(df: pd.DataFrame) -> dict:
    """Valide la structure du fichier Bronze et produit un rapport (non bloquant)."""
    logger.info("Validation structurelle du schéma")
    report = {
        "colonnes_manquantes": [],
        "colonnes_supplementaires": [],
        "problemes_conversion": [],
        "problemes_valeurs": [],
    }

    for col in EXPECTED_SCHEMA:
        if col not in df.columns:
            report["colonnes_manquantes"].append(col)

    for col in df.columns:
        if col not in EXPECTED_SCHEMA:
            report["colonnes_supplementaires"].append(col)

    for col, expected_type in EXPECTED_SCHEMA.items():
        if col not in df.columns:
            continue

        if expected_type == "datetime":
            original_nan = df[col].isna()
            converted = pd.to_datetime(df[col], errors="coerce")
            invalid = converted.isna() & ~original_nan
            if invalid.sum() > 0:
                report["problemes_conversion"].append(f"{col}: {invalid.sum()} valeur(s) non convertibles en datetime")

        elif expected_type in {"int", "float"}:
            original_nan = df[col].isna()
            converted = pd.to_numeric(df[col], errors="coerce")
            invalid = converted.isna() & ~original_nan
            if invalid.sum() > 0:
                report["problemes_conversion"].append(f"{col}: {invalid.sum()} valeur(s) non convertibles en numérique")

    if "timestamp" in df.columns:
        duplicated_timestamps = df["timestamp"].duplicated().sum()
        if duplicated_timestamps > 0:
            report["problemes_valeurs"].append(f"timestamp: {duplicated_timestamps} doublon(s)")

        missing_timestamps = df["timestamp"].isna().sum()
        if missing_timestamps > 0:
            report["problemes_valeurs"].append(f"timestamp: {missing_timestamps} valeur(s) manquante(s)")

    # timestamp est déjà couvert par le bloc spécifique ci-dessus ; on l'exclut
    # de la boucle générique pour ne pas dupliquer le message dans le rapport.
    for col in EXPECTED_SCHEMA:
        if col == "timestamp":
            continue
        if col in df.columns:
            nb_nan = df[col].isna().sum()
            if nb_nan > 0:
                report["problemes_valeurs"].append(f"{col}: {nb_nan} valeur(s) manquante(s)")

    if "failure" in df.columns:
        failure_values = set(pd.to_numeric(df["failure"], errors="coerce").dropna().unique())
        invalid_failure_values = failure_values - {0, 1, 2}
        if invalid_failure_values:
            report["problemes_valeurs"].append(f"failure contient des valeurs non prévues : {invalid_failure_values}")

    for col, (lower_bound, upper_bound) in PHYSICAL_CONSTRAINTS.items():
        if col not in df.columns:
            continue

        numeric_series = pd.to_numeric(df[col], errors="coerce")

        if lower_bound is not None:
            nb_lower = (numeric_series < lower_bound).sum()
            if nb_lower > 0:
                report["problemes_valeurs"].append(f"{col}: {nb_lower} valeur(s) < {lower_bound}")

        if upper_bound is not None:
            nb_upper = (numeric_series > upper_bound).sum()
            if nb_upper > 0:
                report["problemes_valeurs"].append(f"{col}: {nb_upper} valeur(s) > {upper_bound}")

    for category, elements in report.items():
        if elements:
            for element in elements:
                logger.warning("{} - {}", category, element)
        else:
            logger.info("{} : aucun problème détecté", category)

    return report


def initialize_traceability_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Initialise les colonnes de traçabilité utilisées pendant le nettoyage."""
    logger.info("Initialisation des colonnes de traçabilité")
    df = df.copy()

    default_values = {
        "is_outlier": 0,
        "outlier_columns": "",
        "quality_flag": "OK",
        "correction_details": "",
        "is_missing_timestamp": 0,
        "is_failure_nan_corrected": 0,
        "failure_nan_correction_details": "",
        "is_duplicate_corrected": 0,
        "duplicate_correction_details": "",
        "is_nan_corrected": 0,
        "nan_columns": "",
        "nan_correction_details": "",
    }

    for col, default_value in default_values.items():
        if col not in df.columns:
            df[col] = default_value
        else:
            df[col] = df[col].fillna(default_value)

    return df


def convert_and_sort_timestamps(df: pd.DataFrame) -> pd.DataFrame:
    """Convertit la colonne timestamp en datetime UTC tz-aware puis trie.

    `utc=True` est explicite pour rester cohérent avec :
      - le pipeline interventions (`interventions_bronze_to_silver`)
      - les jointures `merge_asof` dans `silver_to_gold`
      - le typage Postgres `TIMESTAMPTZ`
    Sans cela, on aurait des timestamps tz-naïfs côté capteurs et tz-aware
    ailleurs, avec des erreurs de jointure ou d'insertion silencieuses.
    """
    logger.info("Conversion et tri des timestamps (UTC tz-aware)")
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def coerce_numeric_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce les colonnes numériques en types numériques (NaN si invalide).

    `validate_schema()` ne fait que rapporter — les opérations en aval
    (`median`, `mean`, `std`, `mode`) supposent des dtypes numériques.
    Cette étape garantit que les chaînes parasites deviennent NaN avant
    d'arriver dans `manage_duplicates` ou `detect_outliers`.

    Cas particulier `failure` : les valeurs hors {0, 1, 2} (ex: 9, -1)
    sont remontées par `validate_schema` mais doivent aussi être nettoyées
    ici, sinon `astype(int)` les laissera passer et `FAILURE_LABEL.get()`
    retournera None → biais d'entraînement. On les bascule en NaN avec un
    flag dédié pour que `correct_failure_nan` les route via son fallback.
    """
    logger.info("Coercition des colonnes numériques (capteurs + failure)")
    df = df.copy()
    for col in [*NUMERIC_SENSOR_COLUMNS, "failure"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Filtrer les valeurs `failure` hors set valide
    if "failure" in df.columns:
        valid_mask = df["failure"].isin([0, 1, 2]) | df["failure"].isna()
        invalid_indices = df[~valid_mask].index
        if len(invalid_indices) > 0:
            logger.warning(
                "{} valeur(s) `failure` hors {{0,1,2}} -> NaN + flag INVALID_FAILURE_VALUE",
                len(invalid_indices),
            )
            for idx in invalid_indices:
                _append_quality_flag(df, idx, "INVALID_FAILURE_VALUE", replace_ok=True)
            df.loc[invalid_indices, "failure"] = np.nan

    return df


def manage_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    """Supprime doublons stricts + résout conflits de timestamp (médiane + mode failure)."""
    logger.info("Gestion des doublons")
    df = df.copy()

    before_rows = len(df)
    strict_duplicates_mask = df.duplicated(subset=BUSINESS_COLUMNS, keep="first")
    nb_strict_duplicates = int(strict_duplicates_mask.sum())
    logger.info("Doublons stricts détectés : {}", nb_strict_duplicates)

    df = df.loc[~strict_duplicates_mask].copy()
    logger.info("Lignes avant/après suppression des doublons stricts : {} -> {}", before_rows, len(df))

    duplicated_timestamps = df[df.duplicated(subset=["timestamp"], keep=False)]["timestamp"].unique()
    # On exclut NaT : la comparaison `df["timestamp"] == NaT` est toujours False,
    # donc `group.iloc[0]` planterait sur un groupe vide. Les NaT sont traités
    # plus loin par `complete_hourly_timestamps()`.
    duplicated_timestamps = [ts for ts in duplicated_timestamps if pd.notna(ts)]
    logger.info("Timestamps en conflit détectés : {}", len(duplicated_timestamps))

    resolved_rows = []

    # Cap sur la longueur de la sérialisation des valeurs originales pour
    # éviter de gonfler `duplicate_correction_details` (et donc les Parquet
    # + les logs) quand un timestamp a beaucoup de doublons.
    _MAX_VALUES_IN_DETAILS = 5

    for ts in duplicated_timestamps:
        group = df[df["timestamp"] == ts].copy()
        resolved_row = group.iloc[0].copy()
        details = [f"timestamp conflict resolved for {ts}"]

        for col in NUMERIC_SENSOR_COLUMNS:
            original_values = group[col].tolist()
            median_value = group[col].median(skipna=True)
            resolved_row[col] = median_value
            # Tronque la liste sérialisée : on garde les N premières valeurs +
            # un récapitulatif (count) pour rester auditable sans exploser la
            # taille des artefacts.
            shown = original_values[:_MAX_VALUES_IN_DETAILS]
            suffix = (
                f", ... +{len(original_values) - _MAX_VALUES_IN_DETAILS} more"
                if len(original_values) > _MAX_VALUES_IN_DETAILS
                else ""
            )
            details.append(f"{col}: values={shown}{suffix} (n={len(original_values)}) -> median={median_value}")

        failure_values = group["failure"].dropna()

        if len(failure_values) == 0:
            resolved_failure = np.nan
            details.append("failure: all values NaN -> NaN")
        else:
            modes = failure_values.mode()
            if len(modes) == 1:
                resolved_failure = modes.iloc[0]
                details.append(f"failure: values={group['failure'].tolist()} -> mode={resolved_failure}")
            else:
                unique_values = set(failure_values.tolist())
                failure_states = unique_values.intersection({1.0, 2.0})
                if len(failure_states) == 1:
                    resolved_failure = list(failure_states)[0]
                    details.append(
                        f"failure: ambiguous values={group['failure'].tolist()} -> selected failure={resolved_failure}"
                    )
                else:
                    resolved_failure = np.nan
                    details.append(f"failure: ambiguous values={group['failure'].tolist()} -> unresolved NaN")

        resolved_row["failure"] = resolved_failure
        resolved_row["is_duplicate_corrected"] = 1

        current_flag = resolved_row.get("quality_flag", "OK")
        if pd.isna(current_flag) or current_flag == "OK":
            resolved_row["quality_flag"] = "TIMESTAMP_CONFLICT_RESOLVED"
        else:
            resolved_row["quality_flag"] = f"{current_flag}|TIMESTAMP_CONFLICT_RESOLVED"

        resolved_row["duplicate_correction_details"] = "; ".join(details)
        resolved_rows.append(resolved_row)

    if len(duplicated_timestamps) > 0:
        df_without_conflicts = df[~df["timestamp"].isin(duplicated_timestamps)].copy()
        df_resolved_conflicts = pd.DataFrame(resolved_rows)
        df = pd.concat([df_without_conflicts, df_resolved_conflicts], ignore_index=True)
        df = df.sort_values("timestamp").reset_index(drop=True)

    logger.info("Doublons timestamp restants : {}", df.duplicated(subset=["timestamp"]).sum())
    return df


def complete_hourly_timestamps(df: pd.DataFrame) -> pd.DataFrame:
    """Reconstruit une grille horaire complète entre le premier et le dernier timestamp."""
    logger.info("Reconstruction de la complétude temporelle horaire")
    df = df.copy()

    if df["timestamp"].isna().any():
        nb_invalid = int(df["timestamp"].isna().sum())
        logger.warning("{} timestamp(s) invalide(s) ignoré(s) avant reindexation temporelle", nb_invalid)
        df = df.dropna(subset=["timestamp"]).copy()

    if df.empty:
        logger.warning("DataFrame vide après suppression des timestamps invalides")
        return df

    original_timestamps = set(pd.to_datetime(df["timestamp"]))
    full_range = pd.date_range(
        start=df["timestamp"].min(),
        end=df["timestamp"].max(),
        freq="h",
    )

    df = df.set_index("timestamp").reindex(full_range).rename_axis("timestamp").reset_index()

    df["is_missing_timestamp"] = (~df["timestamp"].isin(original_timestamps)).astype(int)
    nb_created_rows = int(df["is_missing_timestamp"].sum())
    logger.info("Lignes créées pour compléter les timestamps : {}", nb_created_rows)

    # Les lignes imputées par la reindexation horaire doivent porter un flag
    # qualité dédié — pas "OK" — pour rester auditable.
    text_columns = [
        "quality_flag",
        "correction_details",
        "outlier_columns",
        "failure_nan_correction_details",
        "duplicate_correction_details",
        "nan_columns",
        "nan_correction_details",
    ]
    imputed_mask = df["is_missing_timestamp"] == 1
    for col in text_columns:
        if col in df.columns:
            if col == "quality_flag":
                # quality_flag : OK pour les lignes originales, MISSING_TIMESTAMP_IMPUTED pour les imputées
                df[col] = df[col].fillna("__PLACEHOLDER__")
                df.loc[imputed_mask & (df[col] == "__PLACEHOLDER__"), col] = "MISSING_TIMESTAMP_IMPUTED"
                df[col] = df[col].replace("__PLACEHOLDER__", "OK")
            else:
                df[col] = df[col].fillna("")

    flag_columns = [
        "is_outlier",
        "is_missing_timestamp",
        "is_failure_nan_corrected",
        "is_duplicate_corrected",
        "is_nan_corrected",
    ]
    for col in flag_columns:
        if col in df.columns:
            df[col] = df[col].fillna(0).astype(int)

    return df


def correct_failure_nan(df: pd.DataFrame) -> pd.DataFrame:
    """Corrige les valeurs manquantes de failure selon les règles métier du notebook."""
    logger.info("Correction des NaN de failure")
    df = df.copy()
    df["failure"] = pd.to_numeric(df["failure"], errors="coerce")

    indices_failure_nan = df[df["failure"].isna()].index
    logger.info("NaN dans failure détectés : {}", len(indices_failure_nan))

    for idx in indices_failure_nan:
        failure_before = df.loc[idx - 1, "failure"] if idx - 1 in df.index else np.nan
        failure_after = df.loc[idx + 1, "failure"] if idx + 1 in df.index else np.nan
        rpm_current = df.loc[idx, "rpm"] if "rpm" in df.columns else np.nan
        rpm_after = df.loc[idx + 1, "rpm"] if idx + 1 in df.index and "rpm" in df.columns else np.nan

        new_value = np.nan
        rule = "UNCERTAIN_FAILURE_CORRECTION"

        if pd.notna(failure_before) and pd.notna(failure_after) and failure_before == failure_after:
            new_value = failure_before
            rule = "same_before_after"

        elif failure_before == 0 and failure_after in [1, 2]:
            if pd.notna(rpm_after) and rpm_after > 0:
                new_value = 0
                rule = "transition_0_to_failure_next_rpm_positive"
            elif pd.notna(rpm_after) and rpm_after == 0:
                new_value = failure_after
                rule = "transition_0_to_failure_next_rpm_zero"

        elif failure_before in [1, 2] and failure_after == 0:
            if pd.notna(rpm_current) and rpm_current == 0:
                new_value = failure_before
                rule = "transition_failure_to_0_current_rpm_zero"
            elif pd.notna(rpm_current) and rpm_current > 0:
                new_value = 0
                rule = "transition_failure_to_0_current_rpm_positive"

        if pd.notna(new_value):
            df.loc[idx, "failure"] = new_value
            df.loc[idx, "is_failure_nan_corrected"] = 1
            _append_quality_flag(df, idx, "FAILURE_NAN_CORRECTED", replace_ok=True)

            if rule == "same_before_after":
                details = (
                    f"failure: NaN -> {new_value}; rule={rule}; "
                    f"failure_before={failure_before}; failure_after={failure_after}"
                )
            else:
                details = (
                    f"failure: NaN -> {new_value}; rule={rule}; "
                    f"failure_before={failure_before}; failure_after={failure_after}; "
                    f"rpm_current={rpm_current}; rpm_after={rpm_after}"
                )

            df.loc[idx, "failure_nan_correction_details"] = details
            # Log par index en DEBUG pour ne pas saturer les logs sur de longues séries.
            logger.debug("failure NaN corrigé à l'index {} : {}", idx, details)
        else:
            _append_quality_flag(df, idx, "UNCERTAIN_FAILURE_NAN", replace_ok=True)
            df.loc[idx, "failure_nan_correction_details"] = (
                f"failure not corrected; rule={rule}; "
                f"failure_before={failure_before}; failure_after={failure_after}; "
                f"rpm_current={rpm_current}; rpm_after={rpm_after}"
            )
            logger.warning("failure NaN non corrigé à l'index {} : cas ambigu", idx)

    remaining_failure_nan = int(df["failure"].isna().sum())
    logger.info("NaN restants dans failure : {}", remaining_failure_nan)

    # Fallback déterministe : tout NaN résiduel devient 0 (nominal) avec un
    # flag qualité dédié, pour garantir une colonne castable en int en aval
    # (`silver_to_gold` fait `df["failure"].astype(int).map(...)`).
    if remaining_failure_nan > 0:
        leftover = df[df["failure"].isna()].index
        logger.warning(
            "{} NaN résiduels dans failure -> défaut 0 + flag UNCERTAIN_FAILURE_DEFAULTED_TO_ZERO",
            remaining_failure_nan,
        )
        for idx in leftover:
            df.loc[idx, "failure"] = 0
            df.loc[idx, "is_failure_nan_corrected"] = 1
            _append_quality_flag(df, idx, "UNCERTAIN_FAILURE_DEFAULTED_TO_ZERO", replace_ok=True)
            current_details = (
                ""
                if pd.isna(df.loc[idx, "failure_nan_correction_details"])
                else str(df.loc[idx, "failure_nan_correction_details"])
            )
            df.loc[idx, "failure_nan_correction_details"] = (
                current_details + "; fallback: NaN -> 0 (deterministic default)"
            ).lstrip("; ")

    df["failure"] = df["failure"].astype(int)
    logger.info("Colonne failure convertie en int")

    return df


def detect_outliers(df: pd.DataFrame, sigma_threshold: float = 5) -> pd.DataFrame:
    """Détecte les outliers à `sigma_threshold`σ sur les lignes `failure=0`."""
    logger.info("Détection des outliers avec un seuil de {} sigma", sigma_threshold)
    df = df.copy()
    df["is_outlier"] = 0
    df["outlier_columns"] = ""

    normal_state_df = df[df["failure"] == 0].copy()

    for col in NUMERIC_SENSOR_COLUMNS:
        mean = normal_state_df[col].mean()
        std = normal_state_df[col].std()

        lower_bound = mean - sigma_threshold * std
        upper_bound = mean + sigma_threshold * std

        mask_outlier = (df["failure"] == 0) & ((df[col] < lower_bound) | (df[col] > upper_bound))

        outlier_indices = df[mask_outlier].index
        logger.info(
            "{} : moyenne={:.4f}, std={:.4f}, bornes=[{:.4f}; {:.4f}], outliers={}",
            col,
            mean if pd.notna(mean) else float("nan"),
            std if pd.notna(std) else float("nan"),
            lower_bound if pd.notna(lower_bound) else float("nan"),
            upper_bound if pd.notna(upper_bound) else float("nan"),
            len(outlier_indices),
        )

        for idx in outlier_indices:
            old_value = df.loc[idx, col]
            df.loc[idx, "is_outlier"] = 1

            current_outlier_cols = (
                "" if pd.isna(df.loc[idx, "outlier_columns"]) else str(df.loc[idx, "outlier_columns"])
            )
            if col not in current_outlier_cols:
                df.loc[idx, "outlier_columns"] = current_outlier_cols + f"{col}, "

            _append_quality_flag(df, idx, "OUTLIER_DETECTED", replace_ok=True, avoid_duplicate=True)

            current_details = (
                "" if pd.isna(df.loc[idx, "correction_details"]) else str(df.loc[idx, "correction_details"])
            )
            df.loc[idx, "correction_details"] = (
                current_details
                + f"[OUTLIER DETECTED] {col}={old_value:.4f}; "
                + f"bornes=[{lower_bound:.2f}; {upper_bound:.2f}] | "
            )

    return df


def correct_numeric_nan(df: pd.DataFrame) -> pd.DataFrame:
    """Corrige les NaN numériques par médiane locale des voisins valides non aberrants."""
    logger.info("Correction des NaN numériques")
    df = df.copy()
    df["is_nan_corrected"] = 0
    df["nan_columns"] = ""
    df["nan_correction_details"] = ""

    for col in NUMERIC_SENSOR_COLUMNS:
        nan_indices = df[df[col].isna()].index
        logger.info("{} : NaN détectés={}", col, len(nan_indices))

        for idx in nan_indices:
            neighbor_indices = list(range(idx - 2, idx)) + list(range(idx + 1, idx + 3))
            neighbor_indices = [i for i in neighbor_indices if i in df.index]

            neighbors_df = df.loc[neighbor_indices, [col, "is_outlier", "outlier_columns"]].copy()
            neighbors_df = neighbors_df[neighbors_df[col].notna()]
            neighbors_df = neighbors_df[neighbors_df["is_outlier"] != 1]
            neighbors_df = neighbors_df[
                ~neighbors_df["outlier_columns"].fillna("").astype(str).str.contains(col, regex=False)
            ]

            median_neighbors = neighbors_df[col].median()

            if pd.isna(median_neighbors):
                _append_quality_flag(df, idx, "UNCERTAIN_NAN_CORRECTION", replace_ok=True)
                current_details = (
                    "" if pd.isna(df.loc[idx, "nan_correction_details"]) else str(df.loc[idx, "nan_correction_details"])
                )
                df.loc[idx, "nan_correction_details"] = (
                    current_details + f"{col}: NaN not corrected; no valid non-outlier neighbors; "
                )
                logger.warning("{} NaN non corrigé à l'index {} : aucun voisin valide", col, idx)
                continue

            df.loc[idx, col] = median_neighbors
            df.loc[idx, "is_nan_corrected"] = 1
            _append_quality_flag(df, idx, "NAN_CORRECTED", replace_ok=True)

            current_nan_columns = "" if pd.isna(df.loc[idx, "nan_columns"]) else str(df.loc[idx, "nan_columns"])
            if col not in current_nan_columns:
                df.loc[idx, "nan_columns"] = current_nan_columns + f"{col}, "

            current_details = (
                "" if pd.isna(df.loc[idx, "nan_correction_details"]) else str(df.loc[idx, "nan_correction_details"])
            )
            df.loc[idx, "nan_correction_details"] = current_details + f"{col}: NaN -> {median_neighbors:.4f}; "
            # Log par index en DEBUG (peut générer des milliers d'entrées sur séries longues).
            logger.debug("{} NaN corrigé à l'index {} -> {:.4f}", col, idx, median_neighbors)

    df["nan_columns"] = df["nan_columns"].fillna("").str.rstrip(", ")
    df["nan_correction_details"] = df["nan_correction_details"].fillna("").str.rstrip("; ")

    return df


def correct_outliers(df: pd.DataFrame) -> pd.DataFrame:
    """Corrige les valeurs aberrantes par médiane locale des voisins valides."""
    logger.info("Correction des outliers")
    df = df.copy()

    for col in NUMERIC_SENSOR_COLUMNS:
        mask_outlier = (df["is_outlier"] == 1) & df["outlier_columns"].fillna("").astype(str).str.contains(
            col, regex=False
        )

        outlier_indices = df[mask_outlier].index
        logger.info("{} : outliers à corriger={}", col, len(outlier_indices))

        for idx in outlier_indices:
            old_value = df.loc[idx, col]

            neighbor_indices = list(range(idx - 2, idx)) + list(range(idx + 1, idx + 3))
            neighbor_indices = [i for i in neighbor_indices if i in df.index]

            neighbors_df = df.loc[neighbor_indices, [col, "is_outlier", "outlier_columns"]].copy()
            neighbors_df = neighbors_df[neighbors_df[col].notna()]
            neighbors_df = neighbors_df[neighbors_df["is_outlier"] != 1]
            neighbors_df = neighbors_df[
                ~neighbors_df["outlier_columns"].fillna("").astype(str).str.contains(col, regex=False)
            ]

            new_value = neighbors_df[col].median()

            if pd.isna(new_value):
                logger.warning("{} outlier non corrigé à l'index {} : aucun voisin valide", col, idx)
                continue

            df.loc[idx, col] = new_value
            _append_quality_flag(df, idx, "OUTLIER_CORRECTED", replace_ok=True, avoid_duplicate=True)

            current_details = (
                "" if pd.isna(df.loc[idx, "correction_details"]) else str(df.loc[idx, "correction_details"])
            )
            df.loc[idx, "correction_details"] = current_details + f"{col}: {old_value:.4f} -> {new_value:.4f}; "
            # Log par index en DEBUG (cf. correct_numeric_nan).
            logger.debug("{} outlier corrigé à l'index {} : {:.4f} -> {:.4f}", col, idx, old_value, new_value)

    df["outlier_columns"] = df["outlier_columns"].fillna("").str.rstrip(", ")
    df["correction_details"] = df["correction_details"].fillna("").str.rstrip("; ")

    return df


def transform_bronze_to_silver(df: pd.DataFrame) -> pd.DataFrame:
    """Applique l'ensemble du workflow Bronze -> Silver dans l'ordre du notebook."""
    logger.info("Début transformation Bronze -> Silver")
    logger.info("Dimensions initiales : {} lignes, {} colonnes", df.shape[0], df.shape[1])

    # Mode strict : si des colonnes attendues manquent, on lève tôt avec un
    # message clair. Sinon downstream (`manage_duplicates`, `detect_outliers`)
    # produirait un KeyError cryptique 5 étapes plus loin.
    report = validate_schema(df)
    if report["colonnes_manquantes"]:
        raise RuntimeError(
            "Bronze schéma invalide — colonnes attendues manquantes : " f"{sorted(report['colonnes_manquantes'])}"
        )

    df_silver = df.copy()
    df_silver = initialize_traceability_columns(df_silver)
    df_silver = convert_and_sort_timestamps(df_silver)
    df_silver = coerce_numeric_columns(df_silver)
    df_silver = manage_duplicates(df_silver)
    df_silver = complete_hourly_timestamps(df_silver)
    df_silver = correct_failure_nan(df_silver)
    df_silver = detect_outliers(df_silver)
    df_silver = correct_numeric_nan(df_silver)
    df_silver = correct_outliers(df_silver)

    logger.info("Dimensions finales : {} lignes, {} colonnes", df_silver.shape[0], df_silver.shape[1])
    logger.info("Fin transformation Bronze -> Silver")

    return df_silver


def save_silver_csv(df: pd.DataFrame, output_path: str | Path) -> None:
    """Exporte un DataFrame Silver au format CSV (utilisé hors pipeline conteneurisé)."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    logger.info("Dataset Silver exporté : {}", output_path)


def _append_quality_flag(
    df: pd.DataFrame,
    idx: int,
    flag: str,
    *,
    replace_ok: bool = True,
    avoid_duplicate: bool = False,
) -> None:
    """Ajoute proprement un statut dans la colonne quality_flag."""
    current_flag = df.loc[idx, "quality_flag"] if "quality_flag" in df.columns else "OK"

    if pd.isna(current_flag) or (replace_ok and current_flag == "OK"):
        df.loc[idx, "quality_flag"] = flag
        return

    current_flag = str(current_flag)

    if avoid_duplicate and flag in current_flag.split("|"):
        return

    df.loc[idx, "quality_flag"] = f"{current_flag}|{flag}"


# ===========================================================================
# Wrapper MECHA — contexte multi-machines et interventions
# ===========================================================================
def transform_bronze_to_silver_with_context(
    df_bronze: pd.DataFrame,
    machine_id: int,
    target_cycle: int,
) -> pd.DataFrame:
    """Applique le pipeline canonique puis injecte `machine_id` et `target_cycle`.

    Le code applicatif MECHA travaille sur plusieurs machines simultanément ;
    on doit donc enrichir chaque ligne avec sa machine d'origine et le cycle
    de maintenance cible (extraits du nom de fichier).
    """
    df_silver = transform_bronze_to_silver(df_bronze)
    df_silver["machine_id"] = int(machine_id)
    df_silver["target_cycle"] = int(target_cycle)
    # On range les colonnes contextuelles en tête pour la lisibilité
    front = ["machine_id", "target_cycle", "timestamp"]
    rest = [c for c in df_silver.columns if c not in front]
    return df_silver[front + rest]


def interventions_bronze_to_silver(
    df_bronze: pd.DataFrame,
    machine_id: int,
) -> pd.DataFrame:
    """Nettoyage du fichier interventions pour une machine donnée.

    Beaucoup plus simple que le pipeline capteurs : on ne fait que typer le
    timestamp, garder les `failure_type` valides et attacher le machine_id.
    """
    df = df_bronze.copy()
    df["machine_id"] = int(machine_id)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    df["failure_type"] = (
        df["failure_type"].astype(str).str.strip().where(df["failure_type"].isin(FAILURE_TYPES), other=pd.NA)
    )
    df = df.dropna(subset=["timestamp", "failure_type"]).reset_index(drop=True)
    keep = ["machine_id", "timestamp", "failure_type", "temperature", "rpm", "vibration", "pressure"]
    return df[[c for c in keep if c in df.columns]].sort_values(["machine_id", "timestamp"]).reset_index(drop=True)


# ===========================================================================
# Silver -> Gold (feature engineering) — utilisé par l'API et le trainer
# ===========================================================================
def silver_to_gold(
    df_silver: pd.DataFrame,
    df_interventions: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Construit les features prêtes pour l'entraînement ML.

    Features dérivées (par machine) :
      - rolling mean/std sur 10 mesures pour température, vibration, pression
      - delta (gradient temporel)
      - load_proxy = rpm × pression / (|voltage| + 1)
      - energy_per_cycle = consumption_kWh × cycle_duration
      - hours_since_last_intervention (jointure as-of avec interventions)
      - failure_type (label texte : `"none"` / `"Breakage"` / `"Overheat"`)
        dérivé soit du `failure` canonique (0/1/2 -> mapping FAILURE_LABEL),
        soit de la jointure avec interventions si fournies.
    """
    if df_silver.empty:
        return df_silver.copy()

    df = df_silver.sort_values(["machine_id", "timestamp"]).copy()

    # S'assurer que timestamp est tz-aware UTC pour les jointures
    if df["timestamp"].dt.tz is None:
        df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")
    else:
        df["timestamp"] = df["timestamp"].dt.tz_convert("UTC")

    # Rolling features par machine
    grouped = df.groupby("machine_id", group_keys=False, sort=False)
    for col in ("temperature_C", "vibration", "pressure"):
        df[f"{col}_roll_mean_10"] = grouped[col].transform(lambda s: s.rolling(window=10, min_periods=1).mean())
        df[f"{col}_roll_std_10"] = grouped[col].transform(lambda s: s.rolling(window=10, min_periods=1).std().fillna(0))
        df[f"{col}_delta"] = grouped[col].transform(lambda s: s.diff().fillna(0))

    df["load_proxy"] = (df["rpm"] * df["pressure"]) / (df["voltage"].abs() + 1.0)
    df["energy_per_cycle"] = df["consumption_kWh"] * df["cycle_duration"]

    # Label `failure_type` : par défaut dérivé de `failure` (0/1/2)
    df["failure_type"] = df["failure"].astype(int).map(FAILURE_LABEL).fillna(NO_FAILURE_LABEL)
    df["hours_since_last_intervention"] = np.nan

    if df_interventions is not None and not df_interventions.empty:
        df = _attach_intervention_context(df, df_interventions)

    df["hours_since_last_intervention"] = df["hours_since_last_intervention"].fillna(9999.0)

    return df.reset_index(drop=True)


def _attach_intervention_context(df_silver: pd.DataFrame, df_interventions: pd.DataFrame) -> pd.DataFrame:
    """Joint l'historique des interventions sur les séries temporelles.

    Pour chaque ligne capteur on ajoute :
      - `hours_since_last_intervention` (merge_asof backward)
      - `failure_type` raffiné si une intervention tombe dans ±1 h (sinon on
        garde le label dérivé de la colonne `failure`).
    """
    df = df_silver.sort_values(["machine_id", "timestamp"]).copy()
    interv = df_interventions.sort_values(["machine_id", "timestamp"]).copy()

    out_parts: list[pd.DataFrame] = []
    for machine, group in df.groupby("machine_id", sort=False):
        sub_int = interv[interv["machine_id"] == machine].copy()
        g = group.sort_values("timestamp").copy()

        if sub_int.empty:
            out_parts.append(g)
            continue

        # `hours_since_last_intervention` — merge_asof backward
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

        # `failure_type` raffiné si intervention dans ±1h
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
