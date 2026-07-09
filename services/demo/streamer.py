"""Mode DEMO — rejoue le jeu de données comme s'il arrivait en temps réel.

Objectif : alimenter Postgres (et donc Grafana) avec un flux continu de
mesures et de prédictions DBSCAN, pour obtenir des graphiques qui
« bougent » pendant une démonstration, sans attendre les cycles
ETL/scheduler.

Principe :
  1. On charge une trame de rejeu (dernier Parquet Gold s'il existe,
     sinon trame synthétique réaliste avec anomalies injectées).
  2. **Warmup** : on rejoue les N dernières minutes en une passe pour
     que les dashboards aient déjà des points affichables à l'ouverture.
  3. À chaque tick, on prélève un lot (par timestamp source ou par taille
     fixe), on ré-horodate à « maintenant », puis :
       - insertion batch dans `sensor_data` (séries capteurs Grafana) ;
       - appel `/predict` avec une session HTTP persistante ; l'API scinde
         chaque point selon le modèle DBSCAN de la machine et le persiste
         dans `predictions`.
  4. On boucle en repartant du début de la trame.

Toute la logique « pure » (génération, mise en forme des lignes) est
isolée des effets de bord pour rester testable unitairement.
"""

from __future__ import annotations

import math
import os
import signal
import sys
import time
from pathlib import Path
from typing import Iterator

import numpy as np
import pandas as pd

from common.logger import setup_logger

log = setup_logger("demo")

SENSOR_COLS = [
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

# Bornes physiques acceptées par l'API (cf. schemas.SensorReading). On clampe
# pour ne jamais produire un 422 côté API pendant la démo.
_BOUNDS = {
    "consumption_kWh": (0.0, 1000.0),
    "temperature_C": (-20.0, 200.0),
    "vibration": (0.0, 50.0),
    "pressure": (0.0, 200.0),
    "cycle_duration": (0.0, 300.0),
    "rpm": (0.0, 5000.0),
    "voltage": (0.0, 500.0),
}

# Colonnes minimales attendues côté API DBSCAN.
_API_FIELDS = (
    "machine_id",
    "target_cycle",
    "consumption_kWh",
    "temperature_C",
    "vibration",
    "pressure",
    "cycle_duration",
    "rpm",
    "voltage",
)


# ---------------------------------------------------------------------------
# Configuration (env)
# ---------------------------------------------------------------------------
class DemoConfig:
    """Paramètres du mode DEMO, lus depuis l'environnement."""

    def __init__(self) -> None:
        self.api_base_url = os.environ.get("API_BASE_URL", "http://api:8000")
        self.gold_dir = Path(os.environ.get("GOLD_DIR", "/data/gold"))
        self.source = os.environ.get("DEMO_SOURCE", "auto").lower()  # auto|gold|synthetic
        self.interval_seconds = float(os.environ.get("DEMO_INTERVAL_SECONDS", "1"))
        self.rows_per_tick = int(os.environ.get("DEMO_ROWS_PER_TICK", "0"))  # 0 = 1 point/machine
        self.machines = int(os.environ.get("DEMO_MACHINES", "5"))
        self.points = int(os.environ.get("DEMO_SYNTHETIC_POINTS", "720"))
        self.loop = os.environ.get("DEMO_LOOP", "true").lower() in {"1", "true", "yes"}
        self.seed = int(os.environ.get("DEMO_SEED", "42"))
        # Warmup : nombre de ticks à rejouer d'un coup au démarrage, écartés
        # de `warmup_stride_seconds` dans le passé pour former une courbe.
        self.warmup_ticks = int(os.environ.get("DEMO_WARMUP_TICKS", "60"))
        self.warmup_stride_seconds = float(os.environ.get("DEMO_WARMUP_STRIDE_SECONDS", "5"))
        # Cap sur la taille chargée (Gold peut faire des dizaines de milliers
        # de lignes ; pour la démo on garde une fenêtre récente pour boucler
        # rapidement et voir le rejeu défiler).
        self.max_replay_rows = int(os.environ.get("DEMO_MAX_REPLAY_ROWS", "4000"))
        # Timeout HTTP par batch (secondes).
        self.http_timeout = float(os.environ.get("DEMO_HTTP_TIMEOUT", "5"))


# ---------------------------------------------------------------------------
# Logique pure — génération et mise en forme (testable sans I/O)
# ---------------------------------------------------------------------------
def synthesize_frame(n_machines: int, n_points: int, seed: int = 42) -> pd.DataFrame:
    """Génère une trame capteurs réaliste avec anomalies injectées."""
    rng = np.random.default_rng(seed)
    rows: list[dict] = []
    base_ts = pd.Timestamp.now(tz="UTC").floor("h") - pd.Timedelta(hours=n_points)

    for machine_id in range(1, n_machines + 1):
        target_cycle = int(rng.choice([30, 60, 90]))
        phase = rng.uniform(0, 2 * math.pi)
        n_episodes = int(rng.integers(1, 3))
        episodes = sorted(int(rng.integers(int(n_points * 0.2), n_points)) for _ in range(n_episodes))

        for i in range(n_points):
            ts = base_ts + pd.Timedelta(hours=i)
            daily = math.sin(2 * math.pi * i / 24.0 + phase)

            anomaly = 0.0
            failure = 0
            for ep in episodes:
                if ep - 12 <= i <= ep:
                    anomaly = max(anomaly, (i - (ep - 12)) / 12.0)
            if anomaly > 0.6:
                failure = int(rng.choice([1, 2]))

            temperature = 55 + 8 * daily + rng.normal(0, 1.5) + 35 * anomaly
            vibration = 1.2 + 0.3 * daily + abs(rng.normal(0, 0.15)) + 4.0 * anomaly
            pressure = 50 + 4 * daily + rng.normal(0, 1.2) - 6 * anomaly
            rpm = 1500 + 60 * daily + rng.normal(0, 20) - 250 * anomaly
            voltage = 230 + rng.normal(0, 2)
            cycle_duration = 35 + 3 * daily + rng.normal(0, 1)
            consumption = 16 + 3 * daily + rng.normal(0, 0.8) + 4 * anomaly

            rows.append(
                {
                    "machine_id": machine_id,
                    "target_cycle": target_cycle,
                    "timestamp": ts,
                    "consumption_kWh": consumption,
                    "temperature_C": temperature,
                    "vibration": vibration,
                    "pressure": pressure,
                    "cycle_duration": cycle_duration,
                    "rpm": rpm,
                    "voltage": voltage,
                    "failure": failure,
                }
            )

    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df.sort_values(["timestamp", "machine_id"]).reset_index(drop=True)


def clamp_sensor_values(record: dict) -> dict:
    """Clampe les colonnes capteurs dans les bornes acceptées par l'API."""
    out = dict(record)
    for col, (lo, hi) in _BOUNDS.items():
        if col in out and out[col] is not None and not pd.isna(out[col]):
            out[col] = float(min(max(float(out[col]), lo), hi))
    return out


def _row_to_sensor_record(row: dict, now: pd.Timestamp) -> dict:
    rec = {c: row[c] for c in SENSOR_COLS if c in row}
    rec = clamp_sensor_values(rec)
    rec["timestamp"] = now.to_pydatetime()
    rec["machine_id"] = int(row["machine_id"])
    rec["target_cycle"] = int(row.get("target_cycle", 30))
    rec["failure"] = int(row.get("failure", 0) or 0)
    return rec


def sensor_records(df_tick: pd.DataFrame, now: pd.Timestamp) -> list[dict]:
    """Construit les lignes `sensor_data` ré-horodatées à `now`."""
    return [_row_to_sensor_record(row, now) for row in df_tick.to_dict("records")]


def _row_to_reading(row: dict) -> dict:
    reading = clamp_sensor_values(
        {
            "machine_id": int(row["machine_id"]),
            "target_cycle": int(row.get("target_cycle", 30)),
            "consumption_kWh": float(row["consumption_kWh"]),
            "temperature_C": float(row["temperature_C"]),
            "vibration": float(row["vibration"]),
            "pressure": float(row["pressure"]),
            "cycle_duration": float(row["cycle_duration"]),
            "rpm": float(row["rpm"]),
            "voltage": float(row["voltage"]),
        }
    )
    # Ne conserve que les champs acceptés par SensorReading (extra=forbid).
    return {k: reading[k] for k in _API_FIELDS if k in reading}


def predict_readings(df_tick: pd.DataFrame) -> list[dict]:
    """Construit le payload `/predict` (une SensorReading par ligne)."""
    return [_row_to_reading(row) for row in df_tick.to_dict("records")]


def iter_ticks(df: pd.DataFrame, rows_per_tick: int) -> Iterator[pd.DataFrame]:
    """Découpe la trame en lots successifs pour le rejeu."""
    if rows_per_tick > 0:
        for start in range(0, len(df), rows_per_tick):
            yield df.iloc[start : start + rows_per_tick]
        return
    for _, group in df.groupby("timestamp", sort=True):
        yield group


# ---------------------------------------------------------------------------
# Effets de bord — chargement, HTTP, SQL
# ---------------------------------------------------------------------------
def _latest_gold(gold_dir: Path) -> Path | None:
    files = sorted(gold_dir.glob("gold_*.parquet"))
    return files[-1] if files else None


def load_replay_frame(cfg: DemoConfig) -> pd.DataFrame:
    """Charge la trame de rejeu selon la source configurée."""
    if cfg.source in {"auto", "gold"}:
        gold = _latest_gold(cfg.gold_dir)
        if gold is not None:
            log.info("DEMO : rejeu du Parquet Gold {}", gold.name)
            df = pd.read_parquet(gold)
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
            df = df.sort_values(["timestamp", "machine_id"]).reset_index(drop=True)
            # Cap : on garde les N dernières lignes pour boucler rapidement.
            if len(df) > cfg.max_replay_rows > 0:
                log.info(
                    "DEMO : trame Gold {} lignes — on garde les {} dernières.",
                    len(df),
                    cfg.max_replay_rows,
                )
                df = df.tail(cfg.max_replay_rows).reset_index(drop=True)
            return df
        if cfg.source == "gold":
            raise RuntimeError(f"Aucun Parquet Gold dans {cfg.gold_dir} (DEMO_SOURCE=gold).")
        log.info("DEMO : aucun Gold trouvé, génération d'une trame synthétique.")
    log.info("DEMO : trame synthétique — {} machines × {} points.", cfg.machines, cfg.points)
    return synthesize_frame(cfg.machines, cfg.points, cfg.seed)


def _engine():
    from sqlalchemy import create_engine

    dsn = os.environ.get("POSTGRES_DSN")
    if not dsn:
        raise RuntimeError("POSTGRES_DSN absent — mode DEMO impossible.")
    return create_engine(dsn, pool_pre_ping=True, future=True)


_INSERT_SENSOR_SQL = """
    INSERT INTO sensor_data
        (machine_id, target_cycle, "timestamp", "consumption_kWh",
         "temperature_C", vibration, pressure, cycle_duration,
         rpm, voltage, failure)
    VALUES
        (:machine_id, :target_cycle, :timestamp, :consumption_kWh,
         :temperature_C, :vibration, :pressure, :cycle_duration,
         :rpm, :voltage, :failure)
"""


def _insert_sensor_rows(engine, records: list[dict]) -> int:
    if not records:
        return 0
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text(_INSERT_SENSOR_SQL), records)
    return len(records)


def _post_predict(session, cfg: DemoConfig, readings: list[dict]) -> int:
    if not readings:
        return 0
    resp = session.post(
        f"{cfg.api_base_url}/predict",
        json={"readings": readings},
        timeout=cfg.http_timeout,
    )
    resp.raise_for_status()
    return len(readings)


def _wait_for_api(session, cfg: DemoConfig, max_wait: float = 60.0) -> bool:
    """Attend que l'API charge son bundle DBSCAN avant de commencer."""
    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline and _RUNNING:
        try:
            resp = session.get(f"{cfg.api_base_url}/health", timeout=2)
            if resp.ok and resp.json().get("models_loaded"):
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1.0)
    return False


# ---------------------------------------------------------------------------
# Boucle principale
# ---------------------------------------------------------------------------
_RUNNING = True


def _install_signal_handlers() -> None:
    def _stop(signum, frame) -> None:  # noqa: ARG001
        global _RUNNING
        log.info("Signal {} reçu — arrêt du mode DEMO.", signum)
        _RUNNING = False

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)


def _warmup(engine, session, cfg: DemoConfig, ticks: list[pd.DataFrame]) -> None:
    """Injecte les N dernières minutes en une passe pour peupler Grafana."""
    if cfg.warmup_ticks <= 0 or not ticks:
        return
    slice_ = ticks[-cfg.warmup_ticks :]
    now = pd.Timestamp.now(tz="UTC")
    stride = pd.Timedelta(seconds=cfg.warmup_stride_seconds)

    log.info("DEMO warmup : rejeu de {} ticks (recul de {}s par tick).", len(slice_), cfg.warmup_stride_seconds)
    total_sensor = 0
    total_pred = 0
    for offset, tick in enumerate(reversed(slice_)):
        ts = now - stride * offset
        try:
            total_sensor += _insert_sensor_rows(engine, sensor_records(tick, ts))
        except Exception as exc:  # noqa: BLE001
            log.warning("Warmup : insertion sensor_data échouée : {}", exc)
        try:
            total_pred += _post_predict(session, cfg, predict_readings(tick))
        except Exception as exc:  # noqa: BLE001
            log.warning("Warmup : /predict échoué : {}", exc)
    log.info("DEMO warmup terminé : {} mesures, {} prédictions injectées.", total_sensor, total_pred)


def run(cfg: DemoConfig | None = None) -> int:
    cfg = cfg or DemoConfig()
    _install_signal_handlers()

    df = load_replay_frame(cfg)
    if df.empty:
        log.error("DEMO : trame de rejeu vide, rien à streamer.")
        return 1

    engine = _engine()

    import requests

    session = requests.Session()

    log.info("DEMO : attente du chargement du bundle DBSCAN par l'API...")
    if not _wait_for_api(session, cfg):
        log.error("DEMO : l'API n'a pas chargé son bundle DBSCAN à temps — abandon.")
        return 2

    ticks = list(iter_ticks(df, cfg.rows_per_tick))
    log.info(
        "DEMO démarré — {} lignes, {} ticks, intervalle={}s, boucle={}, API={}",
        len(df),
        len(ticks),
        cfg.interval_seconds,
        cfg.loop,
        cfg.api_base_url,
    )

    _warmup(engine, session, cfg, ticks)

    while _RUNNING:
        for tick in ticks:
            if not _RUNNING:
                break
            now = pd.Timestamp.now(tz="UTC")
            try:
                n_sensors = _insert_sensor_rows(engine, sensor_records(tick, now))
            except Exception as exc:  # noqa: BLE001
                log.warning("DEMO : insertion sensor_data échouée : {}", exc)
                n_sensors = 0
            try:
                n_pred = _post_predict(session, cfg, predict_readings(tick))
            except Exception as exc:  # noqa: BLE001
                log.warning("DEMO : appel /predict échoué : {}", exc)
                n_pred = 0
            log.debug("DEMO tick — {} mesures, {} prédictions", n_sensors, n_pred)
            time.sleep(cfg.interval_seconds)
        if not cfg.loop:
            break

    log.info("DEMO terminé.")
    return 0


def main() -> int:
    try:
        return run()
    except Exception as exc:  # noqa: BLE001
        print(f"[DEMO] échec : {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
