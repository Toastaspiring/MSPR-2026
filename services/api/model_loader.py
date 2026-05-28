"""Chargement et mise à jour à chaud des trois modèles MECHA.

Les fichiers attendus dans `models-store/` (écrits par le trainer) :
  - classifier_failure.joblib
  - classifier_type.joblib   (multi-classes : none / Breakage / Overheat)
  - type_encoder.joblib      (LabelEncoder sklearn associé)
  - regressor_rul.joblib
  - metadata.json
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path

import joblib

from common.config import settings
from common.logger import setup_logger

log = setup_logger("api")


@dataclass
class LoadedModels:
    failure: object | None = None
    failure_type: object | None = None
    type_encoder: object | None = None
    regressor: object | None = None
    metadata: dict | None = None
    mtimes: dict[str, float] = field(default_factory=dict)


class ModelRegistry:
    """Conteneur thread-safe pour les modèles chargés."""

    FILES = {
        "failure": "classifier_failure.joblib",
        "failure_type": "classifier_type.joblib",
        "type_encoder": "type_encoder.joblib",
        "regressor": "regressor_rul.joblib",
    }

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._models = LoadedModels()
        self._dir = settings.paths.models
        self._meta_path = self._dir / "metadata.json"

    # ----- propriétés publiques --------------------------------------
    @property
    def loaded(self) -> bool:
        with self._lock:
            return all(
                getattr(self._models, attr) is not None
                for attr in ("failure", "failure_type", "type_encoder", "regressor")
            )

    @property
    def trained_at(self) -> str | None:
        with self._lock:
            return (self._models.metadata or {}).get("trained_at")

    @property
    def version(self) -> str:
        with self._lock:
            return (self._models.metadata or {}).get("trained_at", "unknown")

    @property
    def type_classes(self) -> list[str]:
        with self._lock:
            if self._models.type_encoder is None:
                return []
            return [str(c) for c in self._models.type_encoder.classes_]

    # ----- chargement à chaud ----------------------------------------
    def _mtime(self, p: Path) -> float:
        try:
            return p.stat().st_mtime
        except FileNotFoundError:
            return 0.0

    def maybe_reload(self) -> bool:
        """Recharge si l'un des fichiers a changé. Retourne True si rechargé."""
        with self._lock:
            current_mtimes: dict[str, float] = {}
            for key, fname in self.FILES.items():
                current_mtimes[key] = self._mtime(self._dir / fname)
            if any(t == 0.0 for t in current_mtimes.values()):
                return False
            if current_mtimes == self._models.mtimes:
                return False

            log.info("Chargement des modèles depuis {}", self._dir)
            failure = joblib.load(self._dir / self.FILES["failure"])
            failure_type = joblib.load(self._dir / self.FILES["failure_type"])
            type_encoder = joblib.load(self._dir / self.FILES["type_encoder"])
            regressor = joblib.load(self._dir / self.FILES["regressor"])

            meta: dict | None = None
            if self._meta_path.exists():
                try:
                    meta = json.loads(self._meta_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError as exc:
                    log.warning("metadata.json invalide : {}", exc)

            self._models = LoadedModels(
                failure=failure,
                failure_type=failure_type,
                type_encoder=type_encoder,
                regressor=regressor,
                metadata=meta,
                mtimes=current_mtimes,
            )
            log.info("Modèles rechargés — version={}", self.version)
            return True

    # ----- inférence -------------------------------------------------
    def predict(self, X):
        """Renvoie (proba_failure, proba_type_dict, rul_hours) pour chaque ligne."""
        with self._lock:
            if not self.loaded:
                raise RuntimeError("Modèles non chargés — exécuter le trainer d'abord.")

            failure = self._models.failure
            failure_type = self._models.failure_type
            encoder = self._models.type_encoder
            regressor = self._models.regressor

        # P(failure=1)
        proba_fail = failure.predict_proba(X)
        p_fail = proba_fail[:, 1] if proba_fail.shape[1] > 1 else proba_fail[:, 0]

        # P(failure_type) par classe — encoder fixe l'ordre des classes
        proba_type = failure_type.predict_proba(X)
        classes = [str(c) for c in encoder.classes_]
        proba_type_dicts = [{cls: float(p) for cls, p in zip(classes, row)} for row in proba_type]

        # Prédiction RUL (heures)
        rul = regressor.predict(X)

        return p_fail.tolist(), proba_type_dicts, rul.tolist()


registry = ModelRegistry()
