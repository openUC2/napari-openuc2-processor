"""Microscope FileManager browsing: URL normalization + tree-to-children filtering."""

import http.server
import json
import threading
from urllib.parse import parse_qs, urlparse

import pytest

from openuc2_processor.sources import microscope

# Mirrors what ImSwitch's GET /imswitch/api/FileManager/?path=... returns: a
# flat, recursive listing of everything under `path`, with paths relative to
# the server's data root (see ImSwitchServer.py's list_items/scan_directory).
_FULL_TREE = [
    {"name": "expA", "isDirectory": True, "path": "/expA"},
    {"name": "img1.tif", "isDirectory": False, "path": "/expA/img1.tif", "size": 100},
    {"name": "sub", "isDirectory": True, "path": "/expA/sub"},
    {"name": "img2.tif", "isDirectory": False, "path": "/expA/sub/img2.tif", "size": 200},
    {"name": "readme.txt", "isDirectory": False, "path": "/readme.txt", "size": 10},
]


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/imswitch/api/FileManager/":
            self.send_response(404)
            self.end_headers()
            return
        path = parse_qs(parsed.query).get("path", [""])[0]
        cur = path.rstrip("/")
        if cur:
            items = [
                it for it in _FULL_TREE
                if it["path"] == cur or it["path"].startswith(cur + "/")
            ]
            items = [it for it in items if it["path"] != cur]
        else:
            items = _FULL_TREE
        body = json.dumps(items).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence
        pass


@pytest.fixture
def fake_imswitch():
    pytest.importorskip("requests")
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"127.0.0.1:{port}"
    srv.shutdown()


# -- URL helpers --------------------------------------------------------

def test_normalize_base_url_adds_scheme():
    assert microscope.normalize_base_url("192.168.1.100:8001") == "http://192.168.1.100:8001"


def test_normalize_base_url_keeps_scheme_strips_slash_and_quotes():
    assert microscope.normalize_base_url('"https://host:8001/"') == "https://host:8001"


def test_normalize_base_url_empty_raises():
    with pytest.raises(ValueError):
        microscope.normalize_base_url("")


def test_api_base():
    assert (
        microscope.api_base("host:8001")
        == "http://host:8001/imswitch/api/FileManager"
    )


def test_download_url():
    url = microscope.download_url("host:8001", "/expA/img1.tif")
    assert url == "http://host:8001/imswitch/api/FileManager/download/expA/img1.tif"


def test_download_url_no_selection_raises():
    with pytest.raises(ValueError):
        microscope.download_url("host:8001", "")


# -- browsing over real HTTP ---------------------------------------------

def test_list_items_root_is_full_recursive_tree(fake_imswitch):
    items = microscope.list_items(fake_imswitch)
    assert {it["path"] for it in items} == {it["path"] for it in _FULL_TREE}


def test_children_root_is_one_level_only(fake_imswitch):
    names = {it["name"] for it in microscope.children(fake_imswitch)}
    assert names == {"expA", "readme.txt"}


def test_children_of_subdir(fake_imswitch):
    names = {it["name"] for it in microscope.children(fake_imswitch, "/expA")}
    assert names == {"img1.tif", "sub"}


def test_children_of_leaf_subdir(fake_imswitch):
    names = {it["name"] for it in microscope.children(fake_imswitch, "/expA/sub")}
    assert names == {"img2.tif"}
