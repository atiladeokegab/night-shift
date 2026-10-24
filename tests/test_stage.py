from pathlib import Path

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
    assert "the commentary runs on its own clock" in page and "return pace();" in page
    assert "lines show as they arrive" not in page  # the old no-video mode raced through the match


def test_stage_matches_the_app_and_hides_empty_pieces(tmp_path):
    page = TestClient(create_app(store=Store(tmp_path))).get("/stage").text
    assert '<link rel="icon" type="image/svg+xml" href="/favicon.svg">' in page
    assert (Path(__file__).parents[1] / "web" / "public" / "favicon.svg").is_file()
    assert '<span class="wordmark">Touchline.</span>' in page
    assert "#score:empty, #sync:empty, .panel.lines:has(.log:empty)" in page
    # The sync text wraps on a phone, so its pill drops the full round.
    assert ".sync { border-radius: 12px; line-height: 1.3; text-wrap: balance; }" in page


def test_stage_starts_each_video_at_its_video_start(tmp_path):
    # From 0, Jordan waited 6:08 and Kobe 8:10 for the first line on /stage (#57).
    page = TestClient(create_app(store=Store(tmp_path))).get("/stage").text
    assert "loadVideo(plays(m) ? m.youtube_id : null, m.video_start);" in page
    assert "rel: 0, start }" in page  # the first match: the player's own start
    assert "loadVideoById({ videoId: id, startSeconds: start })" in page  # every later one


def test_stage_shows_a_poster_and_a_link_for_an_embed_blocked_video(tmp_path):
    # Hamilton, Messi v Mbappe and Spain v England are blocked by their owners (#18).
    page = TestClient(create_app(store=Store(tmp_path))).get("/stage").text
    assert "const plays = (m) => !!m.youtube_id && m.embed !== false;" in page
    assert "if (!plays(match) || ytFailed) return paced.push(line);" in page  # its own clock
    assert '<img id="still" alt="" hidden>' in page
    assert "i.ytimg.com/vi/${encodeURIComponent(m.youtube_id)}/hqdefault.jpg" in page
    assert 'replaceChildren("Commentary only ", tail)' in page and 'tail.append("· ", link)' in page
