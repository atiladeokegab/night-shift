"""#438: the built page's JS went out uncompressed (933 kB, 263 kB gzipped). Only the static mount
is gzipped: the SSE line stream must reach the page as it is written."""

from fastapi.testclient import TestClient

import core.app as core_app
from core.app import Deps, create_app
from core.store import Store
from data.matches import list_matches, load_moments, video_map

KOBE = "0020500591"
JS = "export const a = 1;\n" * 200


def commentate(moment, history):
    return {
        "line_id": f"{moment['match_id']}-{moment['idx']}",
        "match_id": moment["match_id"],
        "moment_idx": moment["idx"],
        "text": "Bryant at the line.",
    }


def test_built_js_is_gzipped_when_asked(tmp_path, monkeypatch):
    web = tmp_path / "dist"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<!doctype html><div id=root></div>")
    (web / "assets" / "index-x.js").write_text(JS)
    monkeypatch.setattr(core_app, "WEB", web)
    client = TestClient(create_app(Store(tmp_path / "store")))

    r = client.get("/assets/index-x.js", headers={"Accept-Encoding": "gzip"})
    assert r.headers["content-encoding"] == "gzip"
    assert int(r.headers["content-length"]) < len(JS) / 10
    assert r.text == JS  # httpx undoes the gzip; the browser does the same
    raw = client.get("/assets/index-x.js", headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in raw.headers and raw.text == JS


def test_the_line_stream_is_never_gzipped(tmp_path, monkeypatch):
    monkeypatch.setattr(core_app, "WEB", tmp_path)  # a page is mounted, as on live
    (tmp_path / "index.html").write_text("<!doctype html>")
    deps = Deps(list_matches, load_moments, commentate, video_map)
    with TestClient(create_app(Store(tmp_path / "store"), deps)) as client:
        body = {"match_id": KOBE, "speed": 1, "start_idx": 11}
        rid = client.post("/replays", json=body).json()["replay_id"]
        headers = {"Accept-Encoding": "gzip"}
        with client.stream("GET", f"/replays/{rid}/stream", headers=headers) as stream:
            assert "content-encoding" not in stream.headers
            assert stream.headers["content-type"].startswith("text/event-stream")
            for row in stream.iter_lines():
                if row == "event: line":
                    break
            else:
                raise AssertionError("no line")
