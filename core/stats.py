"""Proof-panel numbers, computed from the store only."""

# USD per 1M tokens (input, output), list price
PRICES = {"claude-haiku-4-5": (1.00, 5.00), "claude-sonnet-5-5": (2.00, 10.00)}
# USD per 1k characters: ElevenLabs API Starter ($6 for 75k v3); flash half (checked 2026-10-24)
VOICE_PRICES = {
    "eleven_v3": 0.08,
    "eleven_multilingual_v2": 0.08,
    "eleven_flash_v2_5": 0.04,
    "eleven_turbo_v2_5": 0.04,
}
# Mubit's minimum kept examples before it trains the adapter
ADAPTER_NEEDED = 25


def _pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(p * (len(ordered) - 1)))]


def _cost(line: dict) -> float | None:
    price = PRICES.get(line.get("model"))
    if price is None:
        return None
    return (line.get("tokens_in", 0) * price[0] + line.get("tokens_out", 0) * price[1]) / 1e6


def _adapter(store) -> dict:
    # eval/record_adapter.py appends {status, kept?, agree?, total?} from Mubit's console
    latest = (store.all("adapter") or [{}])[-1]
    return {
        "status": latest.get("status", "not_trained"),
        # a stored line doesn't prove Mubit kept it: unknown until a console count is recorded
        "kept": latest.get("kept"),
        "needed": ADAPTER_NEEDED,
        "agree": latest.get("agree"),
        "total": latest.get("total"),
        # the app can't call the adapter, so its cost per line isn't measurable
        "cost_measurable": False,
    }


def _speaker(lines: list[dict]) -> dict:
    first = [ln["first_word_ms"] for ln in lines if ln.get("first_word_ms") is not None]
    costs = [c for c in map(_cost, lines) if c is not None]
    return {
        # one string, not a list: a `stats` event carries no brackets (a TTS tag must never show)
        "model": ", ".join(sorted({ln["model"] for ln in lines if ln.get("model")})),
        "lines": len(lines),
        "first_word_ms_p50": _pct(first, 0.5),
        "first_word_ms_p95": _pct(first, 0.95),
        "cost_per_line_usd": sum(costs) / len(costs) if costs else None,
    }


def _per_match(store, lines: list[dict], voice: list[dict]) -> dict:
    """Mean spend of a full replay (one played from kick-off, #174): its lines' and answers' model
    cost plus its voice characters. A part is None when any of it has no known price."""
    matches = {r["replay_id"] for r in store.all("replays")}
    said = [x for x in lines + store.all("answers") if x.get("replay_id") in matches]
    model = [_cost(x) for x in said]
    spoken = [v for v in voice if v.get("replay_id") in matches]
    prices = [VOICE_PRICES.get(v.get("model")) for v in spoken]
    n = len(matches)
    model_usd = sum(model) / n if n and None not in model else None
    voice_usd = None  # no voice record: browser speech, or nothing measured to say it costs 0
    if spoken and None not in prices:
        voice_usd = sum(v["chars"] * p / 1000 for v, p in zip(spoken, prices, strict=True)) / n
    both = model_usd is not None and voice_usd is not None
    return {
        "matches_measured": n,
        "cost_per_match_usd": model_usd + voice_usd if both else None,
        "model_cost_per_match_usd": model_usd,
        "voice_cost_per_match_usd": voice_usd,
    }


def stats(store) -> dict:
    lines = store.all("lines")
    fixes = store.all("fixes")
    # a stat line between moments is the analyst's; a line with no speaker predates #130: the lead
    analyst = [ln for ln in lines if ln.get("speaker") == "analyst"]
    lead = [ln for ln in lines if ln.get("speaker") != "analyst"]
    since = (store.all("adapter") or [{}])[-1].get("created_at", "")
    # only a fix Mubit recorded for training counts; one stored before #161 carries no flag
    # an auto fix is the number check's (#162), not a person's: `fixes_auto`, never "your fixes"
    recorded = [f for f in fixes if f.get("recorded") is True and not f.get("auto")]
    first = [ln["first_word_ms"] for ln in lines if ln.get("first_word_ms") is not None]
    total = [ln["latency_ms"] for ln in lines if ln.get("latency_ms") is not None]
    voice = store.all("voice")
    costs = [c for c in map(_cost, lines) if c is not None]
    return {
        "lines": len(lines),
        "fixes": len(fixes),
        "mubit_requests": len({r for ln in lines for r in ln.get("mubit_request_ids", [])}),
        "first_word_ms_p50": _pct(first, 0.5),
        "first_word_ms_p95": _pct(first, 0.95),
        "latency_ms_p50": _pct(total, 0.5),
        "latency_ms_p95": _pct(total, 0.95),
        "tokens_in": sum(ln.get("tokens_in", 0) for ln in lines),
        "tokens_out": sum(ln.get("tokens_out", 0) for ln in lines),
        "cost_per_line_usd": sum(costs) / len(costs) if costs else None,
        "adapter": _adapter(store),
        "by_speaker": {"lead": _speaker(lead), "analyst": _speaker(analyst)},
        "fixes_recorded": len(recorded),
        # fixes recorded since the latest adapter record: the corrections toward the next one
        "fixes_toward_next": sum(f.get("created_at", "") > since for f in recorded),
        "fixes_auto": sum(bool(f.get("auto")) for f in fixes),
        "voice_chars": sum(v.get("chars", 0) for v in voice),
        **_per_match(store, lines, voice),
    }
