"""Tests unitaires du pipeline Bronze -> Silver canonique (version notebook MECHA)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from etl.bronze_to_silver_functions import (
    BUSINESS_COLUMNS,
    FAILURE_LABEL,
    NUMERIC_SENSOR_COLUMNS,
    NO_FAILURE_LABEL,
    TRACEABILITY_COLUMNS,
    complete_hourly_timestamps,
    convert_and_sort_timestamps,
    correct_failure_nan,
    correct_numeric_nan,
    correct_outliers,
    detect_outliers,
    initialize_traceability_columns,
    interventions_bronze_to_silver,
    manage_duplicates,
    parse_intervention_filename,
    parse_timeseries_filename,
    silver_to_gold,
    transform_bronze_to_silver,
    transform_bronze_to_silver_with_context,
    validate_schema,
)


class TestFilenameParsing:
    def test_timeseries_filename(self) -> None:
        assert parse_timeseries_filename("machine_2_targetcycle60.csv") == (2, 60)
        assert parse_timeseries_filename("data/bronze/machine_3_targetcycle10.csv") == (3, 10)
        assert parse_timeseries_filename("random.csv") is None

    def test_intervention_filename(self) -> None:
        assert parse_intervention_filename("intervention_data_machine1.csv") == 1
        assert parse_intervention_filename("intervention_data_machine42.csv") == 42
        assert parse_intervention_filename("interventions.csv") is None


class TestSchemaValidation:
    def test_report_structure(self, sample_timeseries_bronze) -> None:
        report = validate_schema(sample_timeseries_bronze)
        # Le rapport est toujours retourné, et contient au moins une catégorie de problèmes
        assert isinstance(report, dict)
        assert {"colonnes_manquantes", "colonnes_supplementaires", "problemes_conversion", "problemes_valeurs"} <= set(
            report.keys()
        )
        # Le fixture contient un NaN voltage + un timestamp invalide -> au moins un problème
        problems = sum(len(v) for v in report.values())
        assert problems > 0

    def test_detects_invalid_failure_values(self) -> None:
        df = pd.DataFrame(
            {
                "timestamp": ["2026-01-01 00:00:00"],
                "failure": [9],  # valeur non prévue
                "consumption_kWh": [10.0],
                "temperature_C": [50.0],
                "vibration": [1.0],
                "pressure": [50.0],
                "cycle_duration": [30.0],
                "rpm": [1500.0],
                "voltage": [230.0],
            }
        )
        report = validate_schema(df)
        assert any("failure contient des valeurs non prévues" in p for p in report["problemes_valeurs"])


class TestInitializeTraceabilityColumns:
    def test_adds_all_traceability_columns(self, sample_timeseries_bronze) -> None:
        out = initialize_traceability_columns(sample_timeseries_bronze)
        for col in TRACEABILITY_COLUMNS:
            assert col in out.columns, f"colonne de traçabilité manquante : {col}"

    def test_default_quality_flag_is_ok(self, sample_timeseries_bronze) -> None:
        out = initialize_traceability_columns(sample_timeseries_bronze)
        assert (out["quality_flag"] == "OK").all()


class TestConvertAndSortTimestamps:
    def test_invalid_becomes_nat(self, sample_timeseries_bronze) -> None:
        out = convert_and_sort_timestamps(sample_timeseries_bronze)
        # Le fixture a 1 timestamp invalide -> doit devenir NaT
        assert out["timestamp"].isna().sum() == 1

    def test_sorted_ascending(self, sample_timeseries_bronze) -> None:
        out = convert_and_sort_timestamps(sample_timeseries_bronze)
        # Les valeurs non-NaT doivent être triées
        valid = out.dropna(subset=["timestamp"])
        assert valid["timestamp"].is_monotonic_increasing


class TestManageDuplicates:
    def test_resolves_timestamp_conflict(self, sample_timeseries_bronze) -> None:
        df = initialize_traceability_columns(sample_timeseries_bronze)
        df = convert_and_sort_timestamps(df)
        out = manage_duplicates(df)
        # Une fois résolu, il ne reste plus de doublon de timestamp
        assert out.duplicated(subset=["timestamp"]).sum() == 0


class TestCompleteHourlyTimestamps:
    def test_fills_gaps(self) -> None:
        df = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(["2026-01-01 00:00", "2026-01-01 03:00"]),
                "consumption_kWh": [10.0, 12.0],
                "temperature_C": [50.0, 55.0],
                "vibration": [1.0, 1.1],
                "pressure": [50.0, 52.0],
                "cycle_duration": [30.0, 32.0],
                "rpm": [1500.0, 1510.0],
                "voltage": [230.0, 232.0],
                "failure": [0, 0],
            }
        )
        df = initialize_traceability_columns(df)
        out = complete_hourly_timestamps(df)
        # 4 heures (00, 01, 02, 03) -> 4 lignes
        assert len(out) == 4
        # Les nouvelles lignes sont marquées
        assert out["is_missing_timestamp"].sum() == 2


class TestCorrectFailureNan:
    def test_rule_same_before_after(self) -> None:
        df = pd.DataFrame(
            {
                "timestamp": pd.date_range("2026-01-01", periods=3, freq="h"),
                "failure": [0.0, np.nan, 0.0],
                "rpm": [1500.0, 1500.0, 1500.0],
            }
        )
        df = initialize_traceability_columns(df)
        out = correct_failure_nan(df)
        assert out.loc[1, "failure"] == 0
        assert out.loc[1, "is_failure_nan_corrected"] == 1


class TestDetectAndCorrectOutliers:
    def test_5sigma_detection_marks_outlier(self) -> None:
        # 9 valeurs nominales + 1 valeur très éloignée
        df = pd.DataFrame(
            {
                "timestamp": pd.date_range("2026-01-01", periods=10, freq="h"),
                "consumption_kWh": [15.0] * 9 + [500.0],
                "temperature_C": [50.0] * 10,
                "vibration": [1.0] * 10,
                "pressure": [50.0] * 10,
                "cycle_duration": [30.0] * 10,
                "rpm": [1500.0] * 10,
                "voltage": [230.0] * 10,
                "failure": [0] * 10,
            }
        )
        df = initialize_traceability_columns(df)
        df = detect_outliers(df, sigma_threshold=2)  # seuil bas pour valider la mécanique
        # Au moins l'index 9 doit être marqué outlier sur consumption_kWh
        assert df.loc[9, "is_outlier"] == 1
        assert "consumption_kWh" in str(df.loc[9, "outlier_columns"])

    def test_outliers_ignored_when_failure_not_zero(self) -> None:
        # La détection ne tourne QUE sur les lignes failure=0 ; les lignes failure>0 sont protégées
        df = pd.DataFrame(
            {
                "timestamp": pd.date_range("2026-01-01", periods=5, freq="h"),
                "consumption_kWh": [15.0, 15.0, 500.0, 15.0, 15.0],
                "temperature_C": [50.0] * 5,
                "vibration": [1.0] * 5,
                "pressure": [50.0] * 5,
                "cycle_duration": [30.0] * 5,
                "rpm": [1500.0] * 5,
                "voltage": [230.0] * 5,
                "failure": [0, 0, 1, 0, 0],  # la valeur 500 est sur une ligne en panne
            }
        )
        df = initialize_traceability_columns(df)
        df = detect_outliers(df, sigma_threshold=2)
        # La ligne en panne ne doit pas être marquée outlier
        assert df.loc[2, "is_outlier"] == 0


class TestCorrectNumericNan:
    def test_imputes_with_neighbors_median(self) -> None:
        df = pd.DataFrame(
            {
                "timestamp": pd.date_range("2026-01-01", periods=5, freq="h"),
                "consumption_kWh": [15.0, 16.0, 15.0, 17.0, 16.0],
                "temperature_C": [50.0, 51.0, np.nan, 53.0, 52.0],
                "vibration": [1.0] * 5,
                "pressure": [50.0] * 5,
                "cycle_duration": [30.0] * 5,
                "rpm": [1500.0] * 5,
                "voltage": [230.0] * 5,
                "failure": [0] * 5,
            }
        )
        df = initialize_traceability_columns(df)
        df = detect_outliers(df)
        out = correct_numeric_nan(df)
        # Médiane de [50, 51, 53, 52] = 51.5
        assert out.loc[2, "temperature_C"] == 51.5
        assert out.loc[2, "is_nan_corrected"] == 1


class TestTransformBronzeToSilverCanonical:
    def test_returns_dataframe_with_traceability(self, sample_timeseries_bronze) -> None:
        out = transform_bronze_to_silver(sample_timeseries_bronze)
        for col in TRACEABILITY_COLUMNS:
            assert col in out.columns

    def test_failure_is_int_after_pipeline(self, sample_timeseries_bronze) -> None:
        out = transform_bronze_to_silver(sample_timeseries_bronze)
        assert out["failure"].dtype.kind in {"i", "u"}
        assert set(out["failure"].unique()).issubset({0, 1, 2})

    def test_hourly_grid_complete(self, sample_timeseries_bronze) -> None:
        out = transform_bronze_to_silver(sample_timeseries_bronze)
        # Pas de gap horaire entre min et max
        if len(out) > 1:
            deltas = out["timestamp"].diff().dropna()
            assert (deltas == pd.Timedelta(hours=1)).all()


class TestContextWrapper:
    def test_adds_machine_id_and_target_cycle(self, sample_timeseries_bronze) -> None:
        out = transform_bronze_to_silver_with_context(sample_timeseries_bronze, machine_id=2, target_cycle=60)
        assert (out["machine_id"] == 2).all()
        assert (out["target_cycle"] == 60).all()
        # Les colonnes contextuelles doivent être en tête
        assert list(out.columns[:3]) == ["machine_id", "target_cycle", "timestamp"]


class TestInterventionsSilver:
    def test_drops_unknown_failure_types(self, sample_interventions_bronze) -> None:
        out = interventions_bronze_to_silver(sample_interventions_bronze, machine_id=1)
        assert set(out["failure_type"].unique()) <= {"Breakage", "Overheat"}

    def test_machine_id_attached(self, sample_interventions_bronze) -> None:
        out = interventions_bronze_to_silver(sample_interventions_bronze, machine_id=3)
        assert (out["machine_id"] == 3).all()


class TestSilverToGold:
    def test_adds_engineered_features(self, sample_silver) -> None:
        gold = silver_to_gold(sample_silver)
        for col in (
            "temperature_C_roll_mean_10",
            "temperature_C_roll_std_10",
            "temperature_C_delta",
            "vibration_roll_mean_10",
            "vibration_roll_std_10",
            "vibration_delta",
            "pressure_roll_mean_10",
            "pressure_delta",
            "load_proxy",
            "energy_per_cycle",
        ):
            assert col in gold.columns, f"feature manquante : {col}"

    def test_load_proxy_is_finite(self, sample_silver) -> None:
        gold = silver_to_gold(sample_silver)
        assert np.isfinite(gold["load_proxy"]).all()

    def test_failure_type_default_from_failure_column(self, sample_silver) -> None:
        gold = silver_to_gold(sample_silver, df_interventions=None)
        # Si failure=0 partout, failure_type="none"
        # Si failure=1 quelque part, failure_type="Breakage"
        expected = {FAILURE_LABEL[v] for v in set(sample_silver["failure"].unique())}
        assert set(gold["failure_type"].unique()) <= expected | {NO_FAILURE_LABEL}

    def test_hours_since_last_intervention_filled(self, sample_silver, sample_interventions_silver) -> None:
        gold = silver_to_gold(sample_silver, sample_interventions_silver)
        assert gold["hours_since_last_intervention"].notna().all()


class TestETLEndToEnd:
    def test_pipeline_runs_on_real_filenames(
        self, isolated_paths, sample_timeseries_bronze, sample_interventions_bronze
    ) -> None:
        from etl.pipeline import run

        bronze_dir = isolated_paths / "bronze"
        sample_timeseries_bronze.to_csv(bronze_dir / "machine_1_targetcycle30.csv", index=False)
        sample_interventions_bronze.to_csv(bronze_dir / "intervention_data_machine1.csv", index=False)

        run()

        silver_files = list((isolated_paths / "silver").glob("silver_sensor_*.parquet"))
        gold_files = list((isolated_paths / "gold").glob("gold_*.parquet"))
        assert len(silver_files) == 1
        assert len(gold_files) == 1

        gold_df = pd.read_parquet(gold_files[0])
        assert len(gold_df) > 0
        assert (gold_df["machine_id"] == 1).all()
        assert (gold_df["target_cycle"] == 30).all()
        # Les colonnes capteurs et la traçabilité sont conservées
        for c in NUMERIC_SENSOR_COLUMNS:
            assert c in gold_df.columns
        assert "quality_flag" in gold_df.columns
        assert "load_proxy" in gold_df.columns


@pytest.mark.parametrize("col", BUSINESS_COLUMNS)
def test_business_columns_present_after_transform(sample_timeseries_bronze, col):
    """Les colonnes métier de base restent toujours présentes."""
    out = transform_bronze_to_silver(sample_timeseries_bronze)
    assert col in out.columns
