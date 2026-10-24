# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright==1.64.1"]
# ///
"""Film capture (#215): records each shot of the demo film as its own 1280x720 video of the
live site, so the lead only has to narrate. Kept out of the app; the videos go to the hub, never
into the repo.

    uv run demo/capture/film.py              # every shot, into ~/hub/projects/night-shift/film
    uv run demo/capture/film.py 03-ask --base http://localhost:8000

Prod stays read-only: every request to /lines/<id>/fix is aborted, and the Fix shot cancels its
sheet. Playwright records no sound, so the commentary clips the page plays are logged and laid
back onto each video with ffmpeg (NN-name.mp4). The YouTube player's own sound is never in it.
Headless Chromium draws no cursor.
"""

import argparse
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

BASE = "https://night-shift-5zvig7nbvq-ew.a.run.app"
OUT = Path.home() / "hub/projects/night-shift/film"
SIZE = {"width": 1280, "height": 720}
# The stored Jordan idx 30 lines call the Bulls ahead; the layup only cut Utah's lead to one.
# "How did Messi score?" got a wrong answer at 105:41 on 24 Oct; the status line is checked (#186).
QUESTION = "Where are we?"
JORDAN_FIX = (
    "Michael Jordan with the layup! The Bulls cut it to one, "
    "Utah still lead 86 to 85 with 37 seconds left."
)

# Every commentary clip the page starts or stops, by its URL, so its sound goes back on the video.
HOOK = """
for (const [name, fn] of [['play', '__filmPlay'], ['pause', '__filmStop']]) {
  const orig = HTMLMediaElement.prototype[name]
  HTMLMediaElement.prototype[name] = function (...a) {
    if (this.tagName === 'AUDIO' && this.src) window[fn]?.(this.src)
    return orig.apply(this, a)
  }
}
"""


# A line this replay called carries its timing; lines from earlier replays are in the log already.
CALLED = ".log li:not(.qa):has(.num[title])"


def first_line(page: Page) -> None:
    page.locator(CALLED).first.wait_for(timeout=90_000)


def glide(page: Page, dy: int, steps: int = 12, pause: float = 0.25) -> None:
    for _ in range(steps):
        page.mouse.wheel(0, dy / steps)
        page.wait_for_timeout(pause * 1000)


def wsl(page: Page, base: str) -> None:
    page.goto(f"{base}/?match=3913122&at=0")
    first_line(page)
    page.wait_for_timeout(40_000)


def final_extra_time(page: Page, base: str) -> None:
    page.goto(f"{base}/?match=3869685&at=45")
    first_line(page)
    page.wait_for_timeout(30_000)


def ask(page: Page, base: str) -> None:
    page.goto(f"{base}/?match=3869685&at=45")
    first_line(page)
    page.wait_for_timeout(6000)
    page.locator("#ask-q").click()
    page.wait_for_timeout(800)
    page.keyboard.type(QUESTION, delay=90)
    page.wait_for_timeout(800)
    page.keyboard.press("Enter")
    page.locator(".log li.qa:not(.off)", has_text=QUESTION).wait_for(timeout=60_000)
    page.wait_for_timeout(12_000)


def fix_queue(page: Page, base: str) -> None:
    page.goto(f"{base}/#review")
    page.wait_for_timeout(4000)
    glide(page, 1500, steps=24, pause=0.35)
    page.wait_for_timeout(3000)


def fix_jordan(page: Page, base: str) -> None:
    page.goto(f"{base}/#review")
    card = page.locator(".queue li.flag", has_text="Chicago Bulls take the lead").first
    card.wait_for()
    page.wait_for_timeout(2500)
    card.evaluate("e => e.scrollIntoView({ behavior: 'smooth', block: 'center' })")
    page.wait_for_timeout(3500)
    card.get_by_role("button", name="Fix the line").click()
    box = page.locator("#fix-text")
    box.wait_for()
    page.wait_for_timeout(1500)
    box.press("ControlOrMeta+a")
    page.keyboard.type(JORDAN_FIX, delay=45)
    page.wait_for_timeout(1000)
    page.get_by_role("radio", name="Wrong score").check()
    page.wait_for_timeout(4000)
    page.get_by_role("button", name="Cancel").click()  # never Send fix: prod is read-only here
    page.wait_for_timeout(2000)


def proof(page: Page, base: str) -> None:
    page.goto(f"{base}/?match=3869685&at=45")
    first_line(page)
    page.wait_for_timeout(5000)
    page.locator("section[aria-label=Proof]").evaluate(
        "e => e.scrollIntoView({ behavior: 'smooth', block: 'center' })"
    )
    page.wait_for_timeout(12_000)


SHOTS = {
    "01-wsl": wsl,
    "02-final-extra-time": final_extra_time,
    "03-ask": ask,
    "04-fix-queue": fix_queue,
    "05-fix-jordan": fix_jordan,
    "06-proof": proof,
}


def mix(video: Path, clips: list[tuple[bytes, float, float | None]], out: Path, work: Path) -> None:
    """The silent recording plus each clip at its start offset, cut where the page stopped it."""
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video)]
    filters, labels = [], []
    for i, (body, start, stop) in enumerate(clips):
        clip = work / f"{out.stem}-{i}.mp3"
        clip.write_bytes(body)
        cmd += ["-i", str(clip)]
        cut = f"atrim=0:{stop - start:.3f}," if stop else ""
        filters.append(f"[{i + 1}:a]{cut}adelay={int(start * 1000)}:all=1[a{i}]")
        labels.append(f"[a{i}]")
    if clips:
        filters.append(f"{''.join(labels)}amix=inputs={len(clips)}:normalize=0[a]")
        cmd += ["-filter_complex", ";".join(filters), "-map", "0:v", "-map", "[a]", "-c:a", "aac"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", str(out)]
    subprocess.run(cmd, check=True)


def shoot(browser, name: str, base: str, out: Path, work: Path) -> None:
    ctx = browser.new_context(viewport=SIZE, record_video_dir=str(work), record_video_size=SIZE)
    ctx.route("**/lines/*/fix", lambda route: route.abort())
    events: list[tuple[str, str, float]] = []
    ctx.expose_function("__filmPlay", lambda src: events.append(("play", src, time.time())))
    ctx.expose_function("__filmStop", lambda src: events.append(("stop", src, time.time())))
    ctx.add_init_script(HOOK)
    audio: dict[str, object] = {}
    ctx.on("response", lambda r: "/audio" in r.url and r.ok and audio.setdefault(r.url, r))
    page = ctx.new_page()
    t0 = time.time()
    try:
        SHOTS[name](page, base)
    finally:
        bodies = {url: r.body() for url, r in audio.items()}
        ctx.close()
    clips, missing = [], 0
    for kind, src, t in events:
        if kind == "play" and src in bodies:
            stop = next((s for k, u, s in events if k == "stop" and u == src and s > t), None)
            clips.append((bodies[src], t - t0, stop and stop - t0))
        elif kind == "play":
            missing += 1
    webm = Path(page.video.path())
    mp4 = out / f"{name}.mp4"
    mix(webm, clips, mp4, work)
    shutil.move(webm, out / f"{name}.webm")
    lost = f", {missing} not captured" if missing else ""
    print(f"{name}: {mp4} ({len(clips)} commentary clips{lost})")


def contact_sheet(videos: list[Path], out: Path, work: Path) -> Path:
    """One frame from two thirds of the way into each shot on disk, labelled, three across."""
    for i, v in enumerate(videos):
        length = float(
            subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "csv=p=0",
                    str(v),
                ],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        )
        label = (
            f"drawtext=text='{v.stem}':fontcolor=white:fontsize=28"
            ":box=1:boxcolor=black@0.6:boxborderw=8:x=16:y=16"
        )
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-ss",
                f"{length * 2 / 3:.2f}",
                "-i",
                str(v),
                "-frames:v",
                "1",
                "-vf",
                f"scale=640:360,{label}",
                str(work / f"frame-{i:02d}.png"),
            ],
            check=True,
        )
    sheet = out / "contact-sheet.png"
    rows = (len(videos) + 2) // 3
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-framerate",
            "1",
            "-i",
            str(work / "frame-%02d.png"),
            "-vf",
            f"tile=3x{rows}:padding=8:color=black",
            "-frames:v",
            "1",
            str(sheet),
        ],
        check=True,
    )
    return sheet


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("shots", nargs="*", help=f"shots to record (default: all): {', '.join(SHOTS)}")
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    if unknown := set(a.shots) - set(SHOTS):
        ap.error(f"unknown shots: {', '.join(sorted(unknown))}")
    a.out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
        browser = p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
        for name in a.shots or SHOTS:
            shoot(browser, name, a.base.rstrip("/"), a.out, Path(tmp))
        browser.close()
        print(
            "contact sheet:",
            contact_sheet(sorted(a.out.glob("[0-9][0-9]-*.mp4")), a.out, Path(tmp)),
        )


if __name__ == "__main__":
    main()
