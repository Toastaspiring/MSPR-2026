"""Chargement et inférence du bundle DBSCAN produit par le trainer.

Fichier attendu dans `models-store/` :
  - anomaly_model.joblib  (dict : per_machine, global, features, eps, ...)
  - metadata.json         (résumé lisible : trained_at, taux d'anomalie, ...)
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path

import joblib
import numpy as np

from common.config import settings
from common.logger import setup_logger

log = setup_logger("api")


@dataclass
class LoadedBundle:
    bundle: dict | None = None
    metadata: dict | None = None
    mtimes: dict[str, float] = field(default_factory=dict)


class ModelRegistry:
    """Conteneur thread-safe pour le bundle DBSCAN chargé."""

    BUNDLE_FILE = "anomaly_model.joblib"

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._state = LoadedBundle()
        self._dir = settings.paths.models
        self._bundle_path = self._dir / self.BUNDLE_FILE
        self._meta_path = self._dir / "metadata.json"

    @property
    def loaded(self) -> bool:
        with self._lock:
            return self._state.bundle is not None

    @property
    def trained_at(self) -> str | None:
        with self._lock:
            if self._state.bundle is None:
                return None
            return self._state.bundle.get("trained_at")

    @property
    def version(self) -> str:
        return self.trained_at or "unknown"

    @property
    def n_machines(self) -> int:
        with self._lock:
            if self._state.bundle is None:
                return 0
            return len(self._state.bundle.get("per_machine", {}))

    @property
    def features(self) -> list[str]:
        with self._lock:
            if self._state.bundle is None:
                return []
            return list(self._state.bundle.get("features", []))

    def _mtime(self, p: Path) -> float:
        try:
            return p.stat().st_mtime
        except FileNotFoundError:
            return 0.0

    def maybe_reload(self) -> bool:
        with self._lock:
            mt = self._mtime(self._bundle_path)
            if mt == 0.0:
                return False
            if mt == self._state.mtimes.get("bundle"):
                return False

            log.info("Chargement du bundle DBSCAN depuis {}", self._bundle_path)
            bundle = joblib.load(self._bundle_path)

            meta = None
            if self._meta_path.exists():
                try:
                    meta = json.loads(self._meta_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError as exc:
                    log.warning("metadata.json invalide : {}", exc)

            self._state = LoadedBundle(
                bundle=bundle,
                metadata=meta,
                mtimes={"bundle": mt},
            )
            log.info(
                "Bundle rechargé — version={} — {} machines",
                self.version,
                self.n_machines,
            )
            return True

    def _model_for(self, machine_id: int) -> dict:
        assert self._state.bundle is not None
        per_machine = self._state.bundle["per_machine"]
        return per_machine.get(int(machine_id), self._state.bundle["global"])

    def predict(self, X: np.ndarray, machine_ids: list[int]) -> tuple[list[int], list[float]]:
        """Renvoie (cluster_labels, anomaly_scores) alignés sur X.

        `anomaly_score = clip(distance_to_nearest_core / eps, 0, 1)`.
        """
        with self._lock:
            if self._state.bundle is None:
                raise RuntimeError("Bundle DBSCAN non chargé — exécuter le trainer d'abord.")

        cluster_labels: list[int] = [0] * len(X)
        anomaly_scores: list[float] = [0.0] * len(X)

        # Regroupement par machine pour vectoriser scaler + kNN.
        by_machine: dict[int, list[int]] = {}
        for idx, mid in enumerate(machine_ids):
            by_machine.setdefault(int(mid), []).append(idx)

        for mid, indices in by_machine.items():
            model = self._model_for(mid)
            X_sub = X[indices]
            Xs = model["scaler"].transform(X_sub)
            distances, neighbor_idx = model["nn"].kneighbors(Xs, n_neighbors=1, return_distance=True)
            distances = distances.ravel()
            neighbor_idx = neighbor_idx.ravel()

            eps = float(model["eps"])
            core_labels: np.ndarray = model["core_labels"]

            for k, idx in enumerate(indices):
                d = float(distances[k])
                inside = d <= eps
                lbl = int(core_labels[neighbor_idx[k]]) if inside else -1
                cluster_labels[idx] = lbl
                anomaly_scores[idx] = float(min(d / eps, 1.0)) if eps > 0 else (0.0 if inside else 1.0)

        return cluster_labels, anomaly_scores


registry = ModelRegistry()
