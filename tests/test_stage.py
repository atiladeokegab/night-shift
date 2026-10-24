from fastapi.testclient import TestClient

from core.app import create_app
from core.store import Store


def test_stage_serves_the_backup_page(tmp_path):
    r = TestClient(create_app(store=Store(tmp_path))).get("/stage")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert "/matches" in r.text and "getCurrentTime" in r.text


def test_stage_tags_a_moment_like_the_main_page(tmp_path):
    page = TestClient(create_app(store=Store(tmp_path))).get("/stage").text
    assert "momentTag(m)" in page and '"Goal"' in page  # "28:29 · Goal", not "Shot · 28:29"
    assert "${m.type} · ${m.clock}" not in page


def test_stage_without_video_paces_lines_on_its_own_clock(tmp_path):
    page = TestClient(create_app(store=Store(tmp_path))).get("/stage").text
    assert "commentary on its own clock" in page and "return pace();" in page
    assert "lines show as they arrive" not in page  # the old no-video mode raced through the match
