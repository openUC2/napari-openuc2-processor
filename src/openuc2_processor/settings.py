"""Persisted user preferences (default storage dir, ID resolver base URL).

Backed by Qt ``QSettings`` when qtpy is importable, otherwise a small JSON file
under the user home so the non-GUI parts (sources, engine) stay testable without
a Qt event loop.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

ORG = "openUC2"
APP = "openuc2-processor"


def default_storage_dir() -> str:
    """``~/Downloads`` when it exists, otherwise the home directory."""
    downloads = Path.home() / "Downloads"
    return str(downloads if downloads.is_dir() else Path.home())


DEFAULTS: Dict[str, Any] = {
    "storage_dir": default_storage_dir(),
    # Base used to resolve bare numeric IDs (e.g. "13457227" -> Zenodo record).
    "id_base_url": "https://zenodo.org",
    # Last host:port entered in the Downloader's "Microscope" browse tab.
    "last_microscope_url": "",
    "load_as_stack": False,
    "visualize_results": False,
}


class Settings:
    """Tiny key/value store with sensible defaults."""

    def __init__(self) -> None:
        self._qsettings = None
        try:  # Prefer native persistence when Qt is available.
            from qtpy.QtCore import QSettings

            self._qsettings = QSettings(ORG, APP)
        except Exception:  # pragma: no cover - exercised on headless/no-qt envs
            self._json_path = Path.home() / ".openuc2_processor" / "settings.json"
            self._cache = self._load_json()

    # -- public API ---------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        fallback = DEFAULTS.get(key, default)
        if self._qsettings is not None:
            val = self._qsettings.value(key, fallback)
            return _coerce_like(val, fallback)
        return self._cache.get(key, fallback)

    def set(self, key: str, value: Any) -> None:
        if self._qsettings is not None:
            self._qsettings.setValue(key, value)
            self._qsettings.sync()
        else:
            self._cache[key] = value
            self._save_json()

    # -- json fallback ------------------------------------------------------
    def _load_json(self) -> Dict[str, Any]:
        try:
            with open(self._json_path) as fh:
                return json.load(fh)
        except Exception:
            return {}

    def _save_json(self) -> None:
        try:
            os.makedirs(self._json_path.parent, exist_ok=True)
            with open(self._json_path, "w") as fh:
                json.dump(self._cache, fh, indent=2)
        except Exception:
            pass


def _coerce_like(value: Any, like: Any) -> Any:
    """QSettings may return strings for everything; coerce to the default's type."""
    if isinstance(like, bool):
        if isinstance(value, str):
            return value.lower() in ("1", "true", "yes", "on")
        return bool(value)
    if isinstance(like, int) and not isinstance(value, bool):
        try:
            return int(value)
        except (TypeError, ValueError):
            return like
    if isinstance(like, float):
        try:
            return float(value)
        except (TypeError, ValueError):
            return like
    return value
