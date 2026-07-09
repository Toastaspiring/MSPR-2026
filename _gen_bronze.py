"""Génère des CSV Bronze synthétiques réalistes pour la démo MECHA.

Produit, dans data/bronze/ :
  - machine_<id>_targetcycle<N>.csv   (séries horaires capteurs, schéma ETL)
  - intervention_data_machine<id>.csv (log des défaillances -> RUL/type)

Schéma capteurs attendu par l'ETL (EXPECTED_SCHEMA) :
  timestamp, failure, consumption_kWh, temperature_C, vibration,
  pressure, cycle_duration, rpm, voltage
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path("data/bronze")
OUT.mkdir(parents=True, exist_ok=True)

N_MACHINES = 8
N_POINTS = 720  # 30 jours horaires
SENSOR_COLS = [
    "timestamp",
    "failure",
    "consumption_kWh",
    "temperature_C",
    "vibration",
    "pressure",
    "cycle_duration",
    "rpm",
    "voltage",
]


def synth_machine(machine_id: int, n_points: int, seed: int):
    rng = np.random.default_rng(seed)
    target_cycle = int(rng.choice([30, 60, 90]))
    phase = rng.uniform(0, 2 * math.pi)
    base_ts = pd.Timestamp.now(tz="UTC").floor("h") - pd.Timedelta(hours=n_points)

    n_episodes = int(rng.integers(2, 4))
    episodes = sorted(int(rng.integers(int(n_points * 0.15), n_points)) for _ in range(n_episodes))
    ep_type = {ep: int(rng.choice([1, 2])) for ep in episodes}

    rows = []
    interventions = []
    for i in range(n_points):
        ts = base_ts + pd.Timedelta(hours=i)
        daily = math.sin(2 * math.pi * i / 24.0 + phase)

        anomaly = 0.0
        cur_type = 0
        for ep in episodes:
            if ep - 12 <= i <= ep:
                a = (i - (ep - 12)) / 12.0
                if a >= anomaly:
                    anomaly = a
                    cur_type = ep_type[ep]

        failure = cur_type if anomaly > 0.6 else 0

        temperature = 55 + 8 * daily + rng.normal(0, 1.5) + 35 * anomaly
        vibration = 1.2 + 0.3 * daily + abs(rng.normal(0, 0.15)) + 4.0 * anomaly
        pressure = max(0.0, 50 + 4 * daily + rng.normal(0, 1.2) - 6 * anomaly)
        rpm = max(0.0, 1500 + 60 * daily + rng.normal(0, 20) - 250 * anomaly)
        voltage = 230 + rng.normal(0, 2)
        cycle_duration = max(0.0, 35 + 3 * daily + rng.normal(0, 1))
        consumption = max(0.0, 16 + 3 * daily + rng.normal(0, 0.8) + 4 * anomaly)

        rows.append(
            {
                "timestamp": ts.isoformat(),
                "failure": failure,
                "consumption_kWh": round(consumption, 3),
                "temperature_C": round(temperature, 3),
                "vibration": round(vibration, 4),
                "pressure": round(pressure, 3),
                "cycle_duration": round(cycle_duration, 3),
                "rpm": round(rpm, 1),
                "voltage": round(voltage, 2),
            }
        )

    # Interventions : une entrée au pic de chaque épisode
    for ep in episodes:
        i = min(ep, n_points - 1)
        ts = base_ts + pd.Timedelta(hours=i)
        ftype = "Breakage" if ep_type[ep] == 1 else "Overheat"
        interventions.append(
            {
                "timestamp": ts.isoformat(),
                "failure_type": ftype,
                "temperature": round(55 + 35, 2),
                "rpm": 1250.0,
                "vibration": 5.0,
                "pressure": 44.0,
            }
        )

    df = pd.DataFrame(rows, columns=SENSOR_COLS)
    df_int = pd.DataFrame(interventions)
    return target_cycle, df, df_int


total_rows = 0
for m in range(1, N_MACHINES + 1):
    tc, df, df_int = synth_machine(m, N_POINTS, seed=1000 + m)
    f_ts = OUT / f"machine_{m}_targetcycle{tc}.csv"
    f_int = OUT / f"intervention_data_machine{m}.csv"
    df.to_csv(f_ts, index=False)
    df_int.to_csv(f_int, index=False)
    total_rows += len(df)
    print(f"machine {m}: {f_ts.name} ({len(df)} lignes), {len(df_int)} interventions")

print(f"TOTAL: {N_MACHINES} machines, {total_rows} lignes capteurs")
