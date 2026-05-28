"""Tests de la configuration centralisée."""

from __future__ import annotations

import importlib


def test_settings_load_defaults(monkeypatch) -> None:
    monkeypatch.setenv("FAILURE_ALERT_THRESHOLD", "0.8")
    monkeypatch.setenv("APP_SITE_ID", "site-fr-01")
    import common.config

    importlib.reload(common.config)
    s = common.config.settings
    assert s.failure_alert_threshold == 0.8
    assert s.app_site_id == "site-fr-01"


def test_paths_ensure_creates(tmp_path) -> None:
    import common.config

    settings = common.config.Settings.load()
    settings.paths.ensure()
    for p in (settings.paths.bronze, settings.paths.silver, settings.paths.gold):
        assert p.exists()
