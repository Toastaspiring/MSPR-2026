"""Tests unitaires des transformations Bronze → Silver pour le vrai schéma MECHA."""

from __future__ import annotations

import numpy as np
import pandas as pd

from etl.bronze_to_silver_functions import (
    NO_FAILURE_LABEL,
    SENSOR_COLUMNS,
    SILVER_COLUMNS,
    cast_numeric,
    clip_outliers,
    deduplicate,
    impute_sensor_nulls,
    interventions_bronze_to_silver,
    parse_intervention_filename,
    parse_timestamps,
    parse_timeseries_filename,
    silver_to_gold,
    timeseries_bronze_to_silver,
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


class TestPrimitives:
    def test_parse_timestamps_invalid_to_nat(self) -> None:
        df = pd.DataFrame({"timestamp": ["plop"]})
        out = parse_timestamps(df)
        assert out["timestamp"].isna().all()

    def test_cast_numeric_handles_missing_columns(self) -> None:
        df = pd.DataFrame({"a": ["1", "2", "x"]})
        out = cast_numeric(df, ["a", "missing"])
        assert out["a"].iloc[2] != out["a"].iloc[2]  # NaN

    def test_clip_outliers_respects_ranges(self) -> None:
        df = pd.DataFrame({"vibration": [-5, 20, 100]})
        out = clip_outliers(df, {"vibration": (0, 50)})
        assert out["vibration"].tolist() == [0, 20, 50]

    def test_impute_sensor_nulls_interpolates(self) -> None:
        df = pd.DataFrame(
            {
                "machine_id": [1, 1, 1, 1],
                "timestamp": pd.to_datetime(
                    [
                        "2026-01-01 00:00",
                        "2026-01-01 01:00",
                        "2026-01-01 02:00",
                        "2026-01-01 03:00",
                    ],
                    utc=True,
                ),
                "voltage": [230.0, np.nan, np.nan, 234.0],
            }
        )
        out = impute_sensor_nulls(df, ["voltage"])
        # 230 → ? → ? → 234 → interpolation linéaire ≈ 231.33, 232.67
        assert out["voltage"].isna().sum() == 0
        assert 231 < out["voltage"].iloc[1] < 232
        assert 232 < out["voltage"].iloc[2] < 233

    def test_deduplicate_keeps_last(self) -> None:
        df = pd.DataFrame({"k": ["a", "a", "b"], "v": [1, 2, 3]})
        out = deduplicate(df, ["k"])
        assert len(out) == 2
        assert out[out["k"] == "a"]["v"].iloc[0] == 2


class TestTimeseriesBronzeToSilver:
    def test_drops_invalid_timestamp(self, sample_timeseries_bronze) -> None:
        out = timeseries_bronze_to_silver(sample_timeseries_bronze, machine_id=1, target_cycle=30)
        # 7 lignes − 1 timestamp invalide − 1 doublon = 5
        assert len(out) == 5

    def test_clips_consumption_outlier(self, sample_timeseries_bronze) -> None:
        out = timeseries_bronze_to_silver(sample_timeseries_bronze, machine_id=1, target_cycle=30)
        assert out["consumption_kWh"].max() <= 1000

    def test_imputes_voltage_null(self, sample_timeseries_bronze) -> None:
        out = timeseries_bronze_to_silver(sample_timeseries_bronze, machine_id=1, target_cycle=30)
        assert out["voltage"].isna().sum() == 0

    def test_failure_null_becomes_zero(self, sample_timeseries_bronze) -> None:
        out = timeseries_bronze_to_silver(sample_timeseries_bronze, machine_id=1, target_cycle=30)
        assert out["failure"].dtype.kind in {"i", "u"}
        assert set(out["failure"].unique()).issubset({0, 1})

    def test_adds_machine_and_target_cycle(self, sample_timeseries_bronze) -> None:
        out = timeseries_bronze_to_silver(sample_timeseries_bronze, machine_id=2, target_cycle=60)
        assert (out["machine_id"] == 2).all()
        assert (out["target_cycle"] == 60).all()

    def test_columns_complete(self, sample_timeseries_bronze) -> None:
        out = timeseries_bronze_to_silver(sample_timeseries_bronze, machine_id=1, target_cycle=30)
        for col in SILVER_COLUMNS:
            assert col in out.columns, f"colonne manquante : {col}"

    def test_idempotent(self, sample_timeseries_bronze) -> None:
        once = timeseries_bronze_to_silver(sample_timeseries_bronze, 1, 30)
        # On ré-attaque le pipeline en repassant la sortie au format brut.
        # On retire machine_id/target_cycle d'abord pour ne pas être en conflit.
        raw_again = once.drop(columns=["machine_id", "target_cycle"])
        raw_again["timestamp"] = raw_again["timestamp"].astype(str)
        twice = timeseries_bronze_to_silver(raw_again, 1, 30)
        assert len(once) == len(twice)


class TestInterventionsSilver:
    def test_drops_unknown_failure_types(self, sample_interventions_bronze) -> None:
        out = interventions_bronze_to_silver(sample_interventions_bronze, machine_id=1)
        # 4 lignes − 1 timestamp invalide − 1 type 'Unknown' = 2
        assert len(out) == 2
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

    def test_hours_since_last_intervention_filled(self, sample_silver, sample_interventions_silver) -> None:
        gold = silver_to_gold(sample_silver, sample_interventions_silver)
        # Doit être renseigné (pas NaN) après jointure as-of
        assert gold["hours_since_last_intervention"].notna().all()

    def test_failure_type_default_none(self, sample_silver) -> None:
        gold = silver_to_gold(sample_silver, df_interventions=None)
        assert (gold["failure_type"] == NO_FAILURE_LABEL).all()

    def test_failure_type_matches_intervention(self, sample_silver, sample_interventions_silver) -> None:
        # Une intervention "Breakage" tombe pile à 04:00 → ce point doit avoir
        # failure_type = "Breakage" dans Gold (tolérance ±1h).
        gold = silver_to_gold(sample_silver, sample_interventions_silver)
        assert "Breakage" in set(gold["failure_type"].unique())


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
        assert "load_proxy" in gold_df.columns
        # Toutes les colonnes capteurs sont présentes
        for c in SENSOR_COLUMNS:
            assert c in gold_df.columns
