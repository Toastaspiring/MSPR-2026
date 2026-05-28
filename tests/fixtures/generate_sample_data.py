"""(Conservé pour compatibilité — la démo utilise les CSV réels du dossier
``data/bronze/`` fournis par MECHA.)

Ce script reste utile pour les tests CI qui ne peuvent pas embarquer les
données réelles : il génère un mini-jeu synthétique au MÊME schéma que
les fichiers MECHA :

  - ``data/bronze/machine_<id>_targetcycle<N>.csv``
  - ``data/bronze/intervention_data_machine<id>.csv``

Utiliser uniquement si ``data/bronze/`` est vide.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

SCHEMA_TIMESERIES = [
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

SCHEMA_INTERVENTIONS = [
    "timestamp",
    "failure_type",
    "temperature",
    "rpm",
    "vibration",
    "pressure",
]


def _generate_timeseries(machine_id: int, target_cycle: int, hours: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    ts = [base + timedelta(hours=i) for i in range(hours)]
    consumption = rng.uniform(13, 22, hours)
    temperature = rng.normal(50, 10, hours).clip(20, 100)
    vibration = rng.uniform(0.5, 2.0, hours)
    pressure = rng.uniform(40, 65, hours)
    cycle_duration = rng.uniform(30, 40, hours)
    rpm = rng.uniform(1400, 1600, hours)
    voltage = rng.normal(230, 5, hours)
    failure = (temperature > 90).astype(int)

    return pd.DataFrame(
        {
            "timestamp": [t.strftime("%Y-%m-%d %H:%M:%S") for t in ts],
            "consumption_kWh": consumption,
            "temperature_C": temperature,
            "vibration": vibration,
            "pressure": pressure,
            "cycle_duration": cycle_duration,
            "rpm": rpm,
            "voltage": voltage,
            "failure": failure.astype(float),
        }
    )[SCHEMA_TIMESERIES]


def _generate_interventions(machine_id: int, n: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed + 100)
    base = datetime(2026, 1, 5, tzinfo=timezone.utc)
    timestamps = [base + timedelta(hours=int(rng.integers(0, 24 * 60))) for _ in range(n)]
    return pd.DataFrame(
        {
            "timestamp": [t.strftime("%Y-%m-%d %H:%M:%S") for t in timestamps],
            "failure_type": rng.choice(["Breakage", "Overheat"], size=n).tolist(),
            "temperature": rng.uniform(50, 110, n),
            "rpm": rng.uniform(1500, 1700, n),
            "vibration": rng.uniform(1.0, 5.0, n),
            "pressure": rng.uniform(45, 70, n),
        }
    )[SCHEMA_INTERVENTIONS]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--machines", type=int, default=3, help="Nombre de machines")
    parser.add_argument("--hours", type=int, default=720, help="Heures de série / machine (~30j)")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/bronze"),
        help="Dossier de sortie",
    )
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    target_cycles = [30, 60, 10][: args.machines] + [30] * max(0, args.machines - 3)

    for i in range(1, args.machines + 1):
        tc = target_cycles[i - 1]
        ts = _generate_timeseries(i, tc, args.hours, seed=i)
        out = args.output / f"machine_{i}_targetcycle{tc}.csv"
        ts.to_csv(out, index=False)
        print(f"Généré : {out} ({len(ts)} lignes)")

        n_int = max(5, args.hours // 30)
        ints = _generate_interventions(i, n_int, seed=i)
        out_int = args.output / f"intervention_data_machine{i}.csv"
        ints.to_csv(out_int, index=False)
        print(f"Généré : {out_int} ({len(ints)} interventions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
