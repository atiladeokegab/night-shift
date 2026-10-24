"""Proof-panel numbers, computed from the store only."""

# USD per 1M tokens (input, output), list price
PRICES = {"claude-haiku-4-5": (1.00, 5.00), "claude-sonnet-5-5": (2.00, 10.00)}
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


def stats(store) -> dict:
    lines = store.all("lines")
    fixes = store.all("fixes")
    first = [ln["first_word_ms"] for ln in lines if ln.get("first_word_ms") is not None]
    total = [ln["latency_ms"] for ln in lines if ln.get("latency_ms") is not None]
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
    }
