"""Draw Touchline's C4 diagrams, levels 1 to 4, as PNGs beside this file.

    uv run --with graphviz==0.20.3 python docs/architecture/c4.py

Needs Graphviz's `dot` on PATH. Every box names the file it stands for; docs/ARCHITECTURE.md
explains each one.
"""

from pathlib import Path

import graphviz

HERE = Path(__file__).resolve().parent

PERSON, SYSTEM, CONTAINER, COMPONENT, CODE, EXTERNAL, STORE = (
    "#08427B",
    "#1168BD",
    "#438DD5",
    "#85BBF0",
    "#DCEBFA",
    "#8C8C8C",
    "#2E7D32",
)


def graph(name: str, title: str) -> graphviz.Digraph:
    g = graphviz.Digraph(name, format="png")
    g.attr(rankdir="LR", label=title, labelloc="t", fontsize="22", fontname="Helvetica", dpi="110")
    g.attr("node", shape="box", style="rounded,filled", fontname="Helvetica", fontsize="11")
    g.attr("edge", fontname="Helvetica", fontsize="9", color="#555555")
    return g


def box(g, key: str, name: str, kind: str, text: str, fill: str, shape="box") -> None:
    font = "white" if fill in (PERSON, SYSTEM, CONTAINER, EXTERNAL, STORE) else "black"
    text = text.replace("|", "<br/>")
    label = f"<<b>{name}</b><br/><font point-size='9'>[{kind}]</font><br/><br/>{text}>"
    g.node(key, label, fillcolor=fill, fontcolor=font, shape=shape, margin="0.2,0.1")


def context() -> graphviz.Digraph:
    g = graph("c4_context", "Level 1: System context - Touchline")
    box(
        g,
        "fan",
        "Fan",
        "Person",
        "Blind or low-vision sports fan.|Hears every key moment|called, asks questions",
        PERSON,
        "ellipse",
    )
    box(
        g,
        "producer",
        "Producer",
        "Person",
        "Fixes a wrong line;|holds the producer token",
        PERSON,
        "ellipse",
    )
    box(
        g,
        "tl",
        "Touchline",
        "Software system",
        "Replays a real match as|spoken commentary, every number|compared with the event data",
        SYSTEM,
    )
    box(
        g,
        "claude",
        "Anthropic Claude",
        "External: model",
        "claude-haiku-4-5 (lead lines),|claude-sonnet-5-5 (analyst,|Line check, Score check)",
        EXTERNAL,
    )
    box(
        g,
        "mubit",
        "Mubit",
        "External: Anthropic-compatible proxy",
        "api.mubit.ai/anthropic: every model|call goes through it;|records examples per task",
        EXTERNAL,
    )
    box(
        g,
        "eleven",
        "ElevenLabs",
        "External: text to speech",
        "eleven_v3 voice per role and sport;|conversational agent for Talk",
        EXTERNAL,
    )
    box(
        g,
        "yt",
        "YouTube",
        "External: IFrame player",
        "Muted highlights; its clock|decides when a line plays",
        EXTERNAL,
    )
    box(
        g,
        "data",
        "Open sports data",
        "External: offline sources",
        "StatsBomb open data (football),|Cricsheet (cricket),|NBA play-by-play, OpenF1",
        EXTERNAL,
    )
    g.edge("fan", "tl", "watches, listens, asks (HTTPS)")
    g.edge("producer", "tl", "fixes a line (token)")
    g.edge("tl", "mubit", "every model call (HTTPS)")
    g.edge("mubit", "claude", "forwards the call")
    g.edge("tl", "eleven", "one clip per line")
    g.edge("fan", "yt", "plays highlights in the page")
    g.edge("data", "tl", "fetched offline into data/sample and data/packs", style="dashed")
    return g


def containers() -> graphviz.Digraph:
    g = graph("c4_container", "Level 2: Containers - Touchline on Google Cloud")
    box(g, "fan", "Fan or producer", "Person", "Browser", PERSON, "ellipse")
    with g.subgraph(name="cluster_run") as run:
        run.attr(
            label="Cloud Run service night-shift (europe-west1, min 1, max 1 instance)",
            style="dashed",
            fontname="Helvetica",
        )
        box(
            run,
            "web",
            "Web app",
            "Container: React 19, Vite",
            "web/src, built to web/dist,|served by the API at /",
            CONTAINER,
        )
        box(
            run,
            "api",
            "API server",
            "Container: FastAPI, Python 3.12",
            "core/app.py create_app():|/replays, SSE, /ask,|/lines/{id}/fix, /stats, /review",
            CONTAINER,
        )
        box(
            run,
            "graph",
            "Player graph",
            "Embedded SurrealDB",
            "core/graph.py: in memory from data/packs;|data/graph surrealkv for seasons",
            STORE,
            "cylinder",
        )
        box(
            run,
            "files",
            "Bundled data",
            "JSON files in the image",
            "data/sample (moments), data/packs,|data/video (YouTube maps)",
            STORE,
            "cylinder",
        )
    box(
        g,
        "gcs",
        "State store",
        "Cloud Storage: JSON lines",
        "gs://STATE_BUCKET/SERVICE: lines, fixes,|answers, linechecks, clips (core/store.py)",
        STORE,
        "cylinder",
    )
    box(
        g,
        "secrets",
        "Secret Manager",
        "GCP",
        "mubit-api-key, elevenlabs-api-key,|producer-token, converse-llm-secret",
        EXTERNAL,
    )
    box(
        g,
        "build",
        "Cloud Build + Artifact Registry",
        "GCP",
        "gcloud run deploy --source .|builds the Dockerfile",
        EXTERNAL,
    )
    box(
        g,
        "pre",
        "Precompute script",
        "Container: Python CLI",
        "scripts/precompute.py: plays each match|once with the token, saves lines and clips",
        CONTAINER,
    )
    box(
        g,
        "eval",
        "Eval scripts",
        "Container: Python CLIs",
        "eval/: Line check and Score check|held-out evals, seeding",
        CONTAINER,
    )
    box(g, "mubit", "Mubit, then Claude", "External", "every model call", EXTERNAL)
    box(g, "eleven", "ElevenLabs", "External", "eleven_v3 clips", EXTERNAL)
    box(g, "yt", "YouTube", "External", "highlights player", EXTERNAL)
    g.edge("fan", "web", "HTTPS")
    g.edge("web", "api", "JSON; SSE stream")
    g.edge("web", "yt", "IFrame API")
    g.edge("api", "files", "moments, packs")
    g.edge("api", "graph", "Follow, /teams")
    g.edge("api", "gcs", "append / read (generation check)")
    g.edge("api", "mubit", "HTTPS")
    g.edge("api", "eleven", "HTTPS")
    g.edge("secrets", "api", "mounted as env vars", style="dashed")
    g.edge("build", "api", "image", style="dashed")
    g.edge("pre", "api", "POST /replays with token", style="dashed")
    g.edge("eval", "mubit", "seed and test examples", style="dashed")
    return g


def components() -> graphviz.Digraph:
    g = graph("c4_component", "Level 3: Components of the API server - the replay pipeline")
    box(
        g,
        "route",
        "POST /replays",
        "FastAPI route",
        "core/app.py: Guard picks live or|cached; starts run_replay",
        COMPONENT,
    )
    box(
        g,
        "guard",
        "Guard",
        "core/guard.py",
        "budget, live-replay cap,|per-IP limits",
        COMPONENT,
    )
    box(
        g,
        "feed",
        "Moments",
        "agent/feed.py, data/matches.py",
        "key moments, only up to|the one being called",
        COMPONENT,
    )
    box(
        g,
        "comm",
        "Commentator",
        "agent/commentator.py",
        "line_for(): one prompt, one tool|round, via MubitProvider",
        COMPONENT,
    )
    box(
        g,
        "check",
        "Number check",
        "core/insight.py checked()",
        "wrong_numbers() vs the|moment's data",
        COMPONENT,
    )
    box(g, "retry", "Retry once", "checked()", "second call if numbers wrong", COMPONENT)
    box(
        g,
        "fb",
        "Data fallback",
        "core/fallback.py",
        "fallback_text(): line built|from the event data",
        COMPONENT,
    )
    box(g, "store", "Stored line", "core/store.py", "store.append('lines')", STORE, "cylinder")
    box(
        g,
        "voice",
        "Voice",
        "core/voice.py Speaker",
        "ElevenLabs clip, saved|by save_clip()",
        COMPONENT,
    )
    box(
        g,
        "lc",
        "Line check",
        "agent/linecheck.py",
        "second_opinion(): off the|line's path; flags, never unsays",
        COMPONENT,
    )
    box(g, "review", "Review queue", "core/review.py", "GET /review", COMPONENT)
    box(g, "fix", "Producer fix", "POST /lines/{id}/fix", "token; review.wrong() first", COMPONENT)
    box(
        g,
        "train",
        "Training examples",
        "commentator.correct,|linecheck.teach, scorecheck.teach",
        "sent to Mubit on the|owner's key, recorded",
        COMPONENT,
    )
    box(
        g,
        "ask",
        "Ask",
        "POST /replays/{id}/ask",
        "checked_answer(): Claude|via Mubit, unrecorded",
        COMPONENT,
    )
    box(
        g,
        "stats",
        "/stats",
        "core/stats.py",
        "cost, latency, checks, fixes,|from the store only",
        COMPONENT,
    )
    g.edge("route", "guard")
    g.edge("route", "feed")
    g.edge("feed", "comm", "moment + history")
    g.edge("comm", "check", "line")
    g.edge("check", "store", "numbers match")
    g.edge("check", "retry", "wrong")
    g.edge("retry", "store", "retry matches")
    g.edge("retry", "fb", "still wrong")
    g.edge("fb", "store")
    g.edge("store", "voice", "SSE 'line', then clip")
    g.edge("store", "lc", "checked lines")
    g.edge("lc", "review")
    g.edge("review", "fix")
    g.edge("fix", "train")
    g.edge("retry", "train", "auto_fix()", style="dashed")
    g.edge("ask", "check", "same number rules", style="dashed")
    g.edge("store", "stats")
    return g


def code() -> graphviz.Digraph:
    g = graph("c4_code", "Level 4: Code - one replayed line")
    g.attr(rankdir="TB")
    items = [
        (
            "app",
            "create_app() / start_replay()",
            "core/app.py",
            "POST /replays: Guard.off_air, current_lines,|then asyncio task run_replay()",
        ),
        (
            "rr",
            "run_replay()",
            "core/replay.py",
            "for each mapped moment: publish 'moment',|call insight.checked, append, say()",
        ),
        ("rp", "Replay", "core/replay.py", "events list, publish(), SSE subscribers"),
        (
            "ck",
            "checked(commentate, moment, history)",
            "core/insight.py",
            "wrong_numbers(); retry once;|fallback_text() if still wrong",
        ),
        (
            "cm",
            "commentate() / line_for()",
            "agent/commentator.py",
            "build_request(header, past, fixes, seen)|_call(): at most one tool round",
        ),
        (
            "mp",
            "MubitProvider",
            "agent/commentator.py",
            "POST api.mubit.ai/anthropic/v1/messages;|record on/off; owner-key fallback on 402",
        ),
        (
            "fb",
            "fallback_text(header, m)",
            "core/fallback.py",
            "per sport: _football, _basketball,|_cricket, _f1",
        ),
        (
            "st",
            "Store / GcsStore",
            "core/store.py",
            "append(kind, row), all(kind),|save_clip(); open_store() by MODE",
        ),
        (
            "sp",
            "Speaker.prepare() / stream()",
            "core/voice.py",
            "one ElevenLabs job per line;|clip saved for replays",
        ),
        (
            "so",
            "second_opinion() / record_line() / auto_fix()",
            "core/replay.py",
            "background tasks after the line is said",
        ),
    ]
    for key, name, path, text in items:
        box(g, key, name, path, text, CODE)
    for a, b in [
        ("app", "rr"),
        ("rr", "rp"),
        ("rr", "ck"),
        ("ck", "cm"),
        ("cm", "mp"),
        ("ck", "fb"),
        ("rr", "st"),
        ("rr", "sp"),
        ("rr", "so"),
    ]:
        g.edge(a, b)
    return g


if __name__ == "__main__":
    for make in (context, containers, components, code):
        g = make()
        g.render(HERE / g.name, cleanup=True)
        print(HERE / f"{g.name}.png")
