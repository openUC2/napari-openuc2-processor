"""Download-source resolution + HTTP streaming/zip tests."""

import functools
import http.server
import os
import threading
import zipfile

import pytest

from openuc2_processor.download.manager import run_sync
from openuc2_processor.sources import (
    HttpUrlSource,
    LocalSource,
    ZenodoSource,
    resolve_source,
)
from openuc2_processor.sources.http_url import extract_zip


# -- resolution -------------------------------------------------------------

def test_resolve_local(tmp_path):
    assert isinstance(resolve_source(str(tmp_path)), LocalSource)


def test_resolve_url():
    assert isinstance(resolve_source("http://h/y.zip"), HttpUrlSource)
    assert isinstance(resolve_source("https://h/y.ome.zarr"), HttpUrlSource)


def test_resolve_id():
    s = resolve_source("13457227")
    assert isinstance(s, ZenodoSource) and s.record_id == "13457227"
    s2 = resolve_source("13457227.zarr")
    assert isinstance(s2, ZenodoSource) and s2.record_id == "13457227"


def test_resolve_id_custom_base():
    class FakeSettings:
        def get(self, key, default=None):
            return "https://sandbox.zenodo.org" if key == "id_base_url" else default

    s = resolve_source("123", FakeSettings())
    assert s.base_url == "https://sandbox.zenodo.org"
    assert s.api_url == "https://sandbox.zenodo.org/api/records/123"


def test_resolve_invalid():
    with pytest.raises(ValueError):
        resolve_source("definitely not a source")


# -- local source -----------------------------------------------------------

def test_local_source_passthrough(tmp_path):
    src = LocalSource(str(tmp_path))
    assert run_sync(src, str(tmp_path)) == str(tmp_path)


# -- zip extraction ---------------------------------------------------------

def test_extract_zip_returns_top_level(tmp_path):
    folder = tmp_path / "foo"
    folder.mkdir()
    (folder / "a.txt").write_text("hi")
    zpath = tmp_path / "foo.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.write(folder / "a.txt", arcname="foo/a.txt")

    dest = tmp_path / "out"
    dest.mkdir()
    top = extract_zip(str(zpath), str(dest))
    assert top == str(dest / "foo")
    assert (dest / "foo" / "a.txt").read_text() == "hi"


# -- real HTTP streaming ----------------------------------------------------

@pytest.fixture
def http_server(tmp_path_factory):
    pytest.importorskip("requests")
    docroot = tmp_path_factory.mktemp("docroot")
    (docroot / "data.bin").write_bytes(b"x" * 5000)

    class _Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):  # silence
            pass

    handler = functools.partial(_Quiet, directory=str(docroot))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}", docroot
    srv.shutdown()


def test_http_download_progress(http_server, tmp_path):
    base, _docroot = http_server
    events = []
    src = HttpUrlSource(base + "/data.bin")
    out = run_sync(src, str(tmp_path), on_progress=events.append)
    assert os.path.isfile(out)
    assert os.path.getsize(out) == 5000
    assert events and events[-1].done == 5000
    assert events[-1].total == 5000


def test_http_download_zip_extracted(http_server, tmp_path):
    base, docroot = http_server
    folder = docroot / "bar"
    folder.mkdir()
    (folder / "x.txt").write_text("data")
    with zipfile.ZipFile(docroot / "bar.zip", "w") as zf:
        zf.write(folder / "x.txt", arcname="bar/x.txt")

    src = HttpUrlSource(base + "/bar.zip")
    out = run_sync(src, str(tmp_path))
    assert os.path.isdir(out)
    assert out.endswith("bar")
    assert os.path.isfile(os.path.join(out, "x.txt"))
