"""Persistance des prédictions dans Postgres pour Grafana (DBSCAN).

L'API insère chaque prédiction dans la table `predictions`, lue par Grafana
via le datasource Postgres. En cas d'indisponibilité de Postgres, on
dégrade gracieusement (warning + on continue) — la réponse HTTP reste
correcte pour le client.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Iterable

from common.logger import setup_logger

log = setup_logger("api")


def _engine():
    from sqlalchemy import create_engine

    dsn = os.environ.get("POSTGRES_DSN")
    if not dsn:
        raise RuntimeError("POSTGRES_DSN absent")
    return create_engine(dsn, pool_pre_ping=True, future=True)


_ENGINE = None
_ENGINE_FAILED = False


def _get_engine_safe():
    global _ENGINE, _ENGINE_FAILED
    if _ENGINE_FAILED:
        return None
    if _ENGINE is not None:
        return _ENGINE
    try:
        _ENGINE = _engine()
        return _ENGINE
    except Exception as exc:  # noqa: BLE001
        log.warning("Postgres non configuré, prédictions non persistées : {}", exc)
        _ENGINE_FAILED = True
        return None


def insert_predictions(rows: Iterable[dict]) -> int:
    """Insère des prédictions DBSCAN dans la table `predictions`.

    Chaque `row` doit contenir : machine_id, model_version, cluster_label,
    anomaly, anomaly_score, alert, alert_level. `recorded_at` ajouté auto.
    """
    engine = _get_engine_safe()
    if engine is None:
        return 0

    rows = list(rows)
    if not rows:
        return 0

    now = datetime.now(timezone.utc)
    for r in rows:
        r.setdefault("recorded_at", now)

    try:
        from sqlalchemy import text

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO predictions
                        (recorded_at, machine_id, model_version,
                         cluster_label, anomaly, anomaly_score,
                         alert, alert_level)
                    VALUES
                        (:recorded_at, :machine_id, :model_version,
                         :cluster_label, :anomaly, :anomaly_score,
                         :alert, :alert_level)
                    """
                ),
                rows,
            )
        return len(rows)
    except Exception as exc:  # noqa: BLE001
        log.warning("Insertion Postgres en échec : {}", exc)
        return 0
