"""Logger structuré (loguru) commun à tous les services.

Logs horodatés écrits dans le volume `logs-store` pour audit et debug,
conformément à la section 3.4 de l'architecture de déploiement.
"""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

from .config import settings


def setup_logger(service_name: str) -> "logger":  # type: ignore[valid-type]
    """Configure loguru pour un service donné. Idempotent."""
    logger.remove()

    fmt_console = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        f"<cyan>{service_name}</cyan> | "
        "<level>{message}</level>"
    )
    logger.add(sys.stderr, level=settings.log_level, format=fmt_console)

    log_dir: Path = settings.paths.logs / service_name
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.add(
        log_dir / f"{service_name}.log",
        level=settings.log_level,
        rotation="20 MB",
        retention="14 days",
        compression="zip",
        serialize=(settings.log_format == "json"),
        enqueue=True,
    )
    return logger


__all__ = ["setup_logger", "logger"]
