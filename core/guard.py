"""The live site's budget guard (#244): replays generating new lines at once, replay starts and Asks
per client an hour, and a daily cap on model + voice spend. Over a limit a replay plays the lines
already stored for its match, with no model call, or the route answers 429. 0 turns a limit off."""

import math
import os
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

from core.stats import VOICE_PRICES, _cost

HOUR_S = 3600.0
SPEND_TTL_S = 30.0  # today's spend is read from the whole store: at most once this often
OFF_TODAY = "Commentator is off air for today"


def client_ip(request) -> str:
    # shortcut: the first X-Forwarded-For hop (Cloud Run's front end) can be forged to dodge the
    # rate limit; the daily cap still holds. Cloud Armor or a trusted hop if that is abused.
    hop = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return hop or (request.client.host if request.client else "")


class Limiter:
    """At most `per_hour` hits a key in any rolling hour; 0 is no limit."""

    def __init__(self, per_hour: int, clock=time.time):
        self.per_hour = per_hour
        self.clock = clock
        self.hits: dict[str, deque] = defaultdict(deque)

    def hit(self, key: str) -> int:
        """0 and the hit is counted, else the seconds until the key may try again."""
        if not self.per_hour:
            return 0
        now, hits = self.clock(), self.hits[key]
        while hits and hits[0] <= now - HOUR_S:
            hits.popleft()
        if len(hits) >= self.per_hour:
            return max(1, math.ceil(hits[0] + HOUR_S - now))
        hits.append(now)
        return 0


def spent(store, day: str) -> float:
    """Model + voice USD of the lines and answers created on `day` (UTC, YYYY-MM-DD), priced as
    /stats prices them. A voice record has no time: it counts on its line's day."""
    said = [
        x for x in store.all("lines") + store.all("answers") if x.get("created_at", "")[:10] == day
    ]
    ids = {x.get("line_id") for x in said}
    model = sum(_cost(x) or 0.0 for x in said)
    voice = sum(
        v.get("chars", 0) * VOICE_PRICES.get(v.get("model"), 0.0) / 1000
        for v in store.all("voice")
        if v.get("line_id") in ids
    )
    return model + voice


def cached_commentator(store, match_id: str):
    """A commentate that gives each moment's stored line back, marked `cached` so run_replay never
    stores it again, or None for a moment with none and for every stat line: no model call. None:
    nothing stored."""
    said = {
        ln["moment_idx"]: ln
        for ln in store.all("lines")
        if ln.get("match_id") == match_id
        and ln.get("speaker", "lead") == "lead"
        and "reply" not in ln
        and "open" not in ln
        and ln.get("text")
    }
    if not said:
        return None

    def commentate(moment: dict, history: list[dict]) -> dict | None:
        ln = said.get(moment["idx"])
        if ln is None or moment.get("type") == "Stat":
            return None
        # this replay's video time, if any, not the stored one
        return {**{k: v for k, v in ln.items() if k != "video_t"}, "cached": True}

    return commentate


class Guard:
    def __init__(self, env=os.environ, clock=time.time):
        self.clock = clock
        self.max_live = int(env.get("MAX_LIVE_REPLAYS") or 4)
        self.replays = Limiter(int(env.get("REPLAYS_PER_HOUR") or 10), clock)
        self.asks = Limiter(int(env.get("ASKS_PER_HOUR") or 20), clock)
        self.budget = float(env.get("DAILY_BUDGET_USD") or 25)
        self._spent: tuple[str, float, float] | None = None  # (day, read at, USD)

    def now(self) -> datetime:
        return datetime.fromtimestamp(self.clock(), UTC)

    def spent_today(self, store) -> float:
        day, now = self.now().date().isoformat(), self.clock()
        if self._spent is None or self._spent[0] != day or now - self._spent[1] >= SPEND_TTL_S:
            self._spent = (day, now, spent(store, day))
        return self._spent[2]

    def off_air(self, store) -> bool:
        return bool(self.budget) and self.spent_today(store) >= self.budget

    def until_tomorrow(self) -> int:
        now = self.now()
        midnight = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), UTC)
        return max(1, int((midnight - now).total_seconds()))

    def busy(self, live: int) -> bool:
        return bool(self.max_live) and live >= self.max_live

    def stats(self, store) -> dict:
        return {
            "daily_budget_usd": self.budget or None,
            "spent_today_usd": round(self.spent_today(store), 4),
            "off_air": self.off_air(store),
        }
