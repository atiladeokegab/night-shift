from fastapi.testclient import TestClient

from core.app import create_app
from core.store import Store


def test_stage_serves_the_backup_page(tmp_path):
    r = TestClient(create_app(store=Store(tmp_path))).get("/stage")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert "/matches" in r.text and "getCurrentTime" in r.text
