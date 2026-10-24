"""The capture film may add a demo-only producer token only on the app's own top-level page."""

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

FILM = Path(__file__).resolve().parents[1] / "demo" / "capture" / "film.py"
DUMMY = "dummy-token'\"\\\n\u2028'; window.pwned = true; //"


class _Page:
    def __init__(self):
        self.video = self

    def path(self):
        return "unused.webm"


class _Context:
    def __init__(self):
        self.scripts = []
        self.routes = []
        self.page = _Page()

    def route(self, pattern, handler):
        self.routes.append((pattern, handler))

    def add_init_script(self, script):
        self.scripts.append(script)

    def expose_function(self, *_args):
        pass

    def on(self, *_args):
        pass

    def new_page(self):
        return self.page

    def close(self):
        pass


class _Browser:
    def __init__(self):
        self.context = _Context()

    def new_context(self, **_kwargs):
        return self.context


def _film(monkeypatch):
    # The capture script is standalone and declares Playwright as a script dependency. Stub only
    # its import surface so these unit tests do not need to install or launch a browser.
    playwright = ModuleType("playwright")
    sync_api = ModuleType("playwright.sync_api")
    sync_api.Error = RuntimeError
    sync_api.Page = object
    sync_api.sync_playwright = lambda: None
    playwright.sync_api = sync_api
    monkeypatch.setitem(sys.modules, "playwright", playwright)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)
    spec = importlib.util.spec_from_file_location("film_capture_under_test", FILM)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _shoot(monkeypatch, tmp_path, *, save_fix, base="https://night-shift.example"):
    film = _film(monkeypatch)
    browser = _Browser()
    monkeypatch.setitem(film.SHOTS, "test", lambda _page, _base: None)
    monkeypatch.setattr(film, "SAVE_FIX", save_fix)
    monkeypatch.setenv("PRODUCER_TOKEN", DUMMY)
    monkeypatch.setattr(film, "mix", lambda *_args: None)
    monkeypatch.setattr(film.shutil, "move", lambda *_args: None)
    film.shoot(browser, "test", base, tmp_path, tmp_path)
    return film, browser.context


def test_default_capture_still_aborts_fix_and_never_injects_token(monkeypatch, tmp_path):
    _film_module, ctx = _shoot(monkeypatch, tmp_path, save_fix=False)
    assert len(ctx.routes) == 1 and ctx.routes[0][0] == "**/lines/*/fix"

    class Route:
        aborted = False

        def abort(self):
            self.aborted = True

    route = Route()
    ctx.routes[0][1](route)
    assert route.aborted
    assert not any("producer-token" in script for script in ctx.scripts)


def _run_init_script(source, *, page_origin, top_origin, top_is_page):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable; browser init-script execution cases cannot run")
    runner = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const { URL } = require('node:url');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const page = { location: { origin: input.pageOrigin } };
const top = { location: { origin: input.topOrigin } };
page.top = input.topIsPage ? page : top;
const writes = [];
const localStorage = { setItem: (key, value) => writes.push([key, value]) };
page.localStorage = localStorage;
vm.runInNewContext(input.source, { window: page, location: page.location, localStorage, URL });
process.stdout.write(JSON.stringify({ writes, pwned: Boolean(page.pwned) }));
"""
    result = subprocess.run(
        [node, "-e", runner],
        input=json.dumps(
            {
                "source": source,
                "pageOrigin": page_origin,
                "topOrigin": top_origin,
                "topIsPage": top_is_page,
            }
        ),
        text=True,
        capture_output=True,
        check=True,
        timeout=5,
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize(
    "base, page_origin, top_origin, top_is_page, writes",
    [
        (
            "https://night-shift.example",
            "https://night-shift.example",
            "https://night-shift.example",
            True,
            True,
        ),
        (
            "https://night-shift.example",
            "https://elsewhere.example",
            "https://elsewhere.example",
            True,
            False,
        ),
        (
            "https://night-shift.example",
            "https://night-shift.example",
            "https://elsewhere.example",
            False,
            False,
        ),
        (
            "https://night-shift.example",
            "https://elsewhere.example",
            "https://night-shift.example",
            False,
            False,
        ),
        (
            "https://night-shift.example",
            "https://night-shift.example",
            "https://night-shift.example",
            False,
            False,
        ),
        (
            "https://night-shift.example:443/demo/path?shot=1",
            "https://night-shift.example",
            "https://night-shift.example",
            True,
            True,
        ),
        (
            'https://night-shift.example/demo?quote="&slash=\\',
            "https://night-shift.example",
            "https://night-shift.example",
            True,
            True,
        ),
    ],
)
def test_save_fix_token_script_runs_only_on_matching_top_level_app_origin(
    monkeypatch, tmp_path, base, page_origin, top_origin, top_is_page, writes
):
    _film_module, ctx = _shoot(monkeypatch, tmp_path, save_fix=True, base=base)
    token_script = next(script for script in ctx.scripts if "producer-token" in script)
    result = _run_init_script(
        token_script,
        page_origin=page_origin,
        top_origin=top_origin,
        top_is_page=top_is_page,
    )
    assert result["writes"] == ([["producer-token", DUMMY]] if writes else [])
    assert not result["pwned"]


def test_save_fix_token_is_data_not_executable_javascript(monkeypatch, tmp_path):
    _film_module, ctx = _shoot(monkeypatch, tmp_path, save_fix=True)
    token_script = next(script for script in ctx.scripts if "producer-token" in script)
    result = _run_init_script(
        token_script,
        page_origin="https://night-shift.example",
        top_origin="https://night-shift.example",
        top_is_page=True,
    )
    assert result["writes"] == [["producer-token", DUMMY]]
    assert not result["pwned"]
