"""Browse an ImSwitch microscope's FileManager over HTTP.

Given just ``host:port`` (or a full base URL) of a running ImSwitch server,
list the datasets under its data folder and resolve a picked one to the same
download URL the ImSwitch web UI's "Open in napari" button copies:
``<base>/imswitch/api/FileManager/download/<path>``.

Pure networking/parsing helpers only — no Qt — so they're testable headless.
See ``imswitch/imcontrol/controller/server/ImSwitchServer.py`` for the
server-side ``/api/FileManager/`` endpoints these mirror.
"""

from __future__ import annotations

import re
from typing import Dict, List
from urllib.parse import quote

_API_SUFFIX = "/imswitch/api/FileManager"
_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def normalize_base_url(raw: str) -> str:
    """Turn ``host:port`` or ``http(s)://host:port`` into a clean base URL.

    Plain ``urlparse().scheme`` can't tell "already has a scheme" from
    "host:port" apart (``host:8001`` parses with scheme ``host``), so match
    the http(s) prefix explicitly instead.
    """
    s = (raw or "").strip().strip('"').strip("'")
    if not s:
        raise ValueError("Enter the microscope's host (and port), e.g. 192.168.1.100:8001")
    if not _URL_RE.match(s):
        s = "http://" + s
    return s.rstrip("/")


def api_base(raw: str) -> str:
    return f"{normalize_base_url(raw)}{_API_SUFFIX}"


def list_items(raw: str, path: str = "") -> List[Dict]:
    """List datasets under *path* (ImSwitch's endpoint scans recursively)."""
    import requests

    resp = requests.get(f"{api_base(raw)}/", params={"path": path or ""}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def children(raw: str, path: str = "") -> List[Dict]:
    """Immediate children of *path*.

    ImSwitch's ``/FileManager/`` always returns the full recursive tree under
    *path*, so filter it down to a single directory level for a browsable list.
    """
    cur = (path or "").rstrip("/")
    out = []
    for item in list_items(raw, cur):
        p = item.get("path") or ""
        if cur:
            if not p.startswith(cur + "/"):
                continue
            rest = p[len(cur) + 1:]
        else:
            if not p.startswith("/"):
                continue
            rest = p[1:]
        if not rest or "/" in rest:
            continue
        out.append(item)
    return out


def download_url(raw: str, path: str) -> str:
    """Resolve a picked item's ``path`` to its download URL."""
    clean = (path or "").lstrip("/")
    if not clean:
        raise ValueError("No dataset selected.")
    return f"{api_base(raw)}/download/{quote(clean, safe='/')}"
