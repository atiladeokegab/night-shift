"""The line said when the commentator's stays wrong (#195): one plain sentence per sport and event,
built only from the moment's data, with numbers as words so the voice says them as a commentator
would. Every one passes the number check on its own moment, and none is longer than 20 words."""

import re

UNITS = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen"
).split()
TENS = "twenty thirty forty fifty sixty seventy eighty ninety".split()
PLACES = (
    "first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth "
    "fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth twentieth"
).split()
EXTRAS = {"legbyes": "leg byes", "noballs": "no balls"}


def words(n: int) -> str:
    """0 to 999 as said: 86 is "eighty-six", 158 "one hundred and fifty-eight"."""
    if n >= 100:
        rest = n % 100
        return f"{UNITS[n // 100]} hundred" + (f" and {words(rest)}" if rest else "")
    if n < 20:
        return UNITS[n]
    return TENS[n // 10 - 2] + (f"-{UNITS[n % 10]}" if n % 10 else "")


def hoops(n: int) -> str:
    """A basketball score as said: 122 is "one twenty-two", 102 "one oh-two"."""
    r = n % 100
    if n < 100:
        return words(n)
    return f"{UNITS[n // 100]} " + (
        "hundred" if not r else f"oh-{UNITS[r]}" if r < 10 else words(r)
    )


def _said(text: str) -> str:
    return re.sub(r"\d+", lambda d: words(int(d[0])), text)


def _who(m: dict, role: str) -> str:
    return (m.get("players") or {}).get(role) or ""


def _score(header: dict, m: dict, say=words) -> str:
    """Who leads, or that it's level, and a shootout's tally: "Argentina lead two, one"."""
    s, so = m["score"], m["detail"].get("shootout")
    h, a = (so["home"], so["away"]) if so and s["home"] == s["away"] else (s["home"], s["away"])
    shootout = " the shootout" if so and s["home"] == s["away"] else ""
    if h == a:
        return f"Level at {say(h)} all{shootout and ' in the shootout'}." if h else "Goalless."
    side = "home" if h > a else "away"
    return f"{header[side]} lead{shootout} {say(max(h, a))}, {say(min(h, a))}."


def _nil(n: int) -> str:
    return words(n) if n else "nil"


def _football(header: dict, m: dict) -> list[str]:
    d, t, out = m["detail"], m["type"], m.get("outcome")
    who = _who(m, "shooter") or _who(m, "offender")
    yards = _said(d.get("where", "").split(",")[0])  # "from twelve yards", the shot's distance
    spot = d.get("shot_type") == "Penalty"
    score = _score(header, m, _nil)
    if t == "Shot":
        shot = f"{who}'s penalty" if spot else f"{who} shoots {yards}".strip()
        keeper = f" by {_who(m, 'keeper')}" if _who(m, "keeper") else ""
        said = {
            "Goal": f"{who} scores the penalty!" if spot else f"{who} scores {yards}".strip() + "!",
            "Saved": f"{shot}, saved{keeper}.",
            "Off T": f"{shot}, off target.",
            "Blocked": f"{shot}, blocked.",
            "Wayward": f"{shot}, well off target.",
        }.get(out, f"{shot}, {str(out).lower()}.")
    elif "card" in d:
        place = f" {d['where']}" if "where" in d else ""
        said = f"{who} is shown a {d['card'].lower()}{place}."
    elif t == "Substitution":
        hurt = "the injured " if out == "Injury" else ""
        said = f"{_who(m, 'on')} comes on for {hurt}{_who(m, 'off')}."
    elif t == "Injury Stoppage":
        said = f"Play stops for an injury to {_who(m, 'injured')}."
    elif t == "Full time":  # whoever leads at the end has won
        said, score = "Full time.", score.replace(" lead", " win", 1)
    else:
        said = f"{t}, {who}." if who else f"{t}."
    return [said, score]


def _basketball(header: dict, m: dict) -> list[str]:
    d, t, out, s = m["detail"], m["type"], m.get("outcome"), m["score"]
    who = _who(m, "shooter")
    kind = re.sub(r"\(.*?\)|\d+'|3PT", "", d.get("play", "")).split(None, 1)[1:]
    kind = " ".join(kind[0].split()).lower() if kind else "shot"
    if t == "Field goal":
        said = f"{who} hits a three" if out == "3 points" else f"{who} with the {kind}"
    elif t == "Free throw":
        said = f"{who} makes the {'technical ' * ('technical' in kind)}free throw"
    elif t == "Steal":
        said = f"{_who(m, 'stealer')} steals it from {_who(m, 'lost_by')}"
    elif t == "End of game":
        side = "home" if s["home"] > s["away"] else "away"
        won, lost = hoops(max(s["home"], s["away"])), hoops(min(s["home"], s["away"]))
        return [f"The final buzzer. {header[side]} win {won}, {lost}."]
    else:
        said = t
    if "milestone" in d:  # "Kobe Bryant has 81 points tonight": the points, not the name again
        said += f", {_said(d['milestone'].split(' has ', 1)[1])}"
    if s["home"] == s["away"]:
        return [f"{said}.", f"Tied at {hoops(s['home'])}."]
    return [f"{said}.", _score(header, m, hoops)]


def _cricket(header: dict, m: dict) -> list[str]:
    d, t, out, s = m["detail"], m["type"], m.get("outcome"), m["score"]
    bat, bowl = _who(m, "batter"), _who(m, "bowler")
    if t == "Wicket":
        how, fielder, gone = d.get("wicket_kind", out), _who(m, "fielder"), _who(m, "out")
        said = {
            "bowled": f"{gone} is bowled by {bowl}!",
            "lbw": f"{gone} is out lbw to {bowl}!",
            "caught": f"{gone} is caught by {fielder} off {bowl}!",
            "caught and bowled": f"{gone} is caught and bowled by {bowl}!",
            "run out": f"{gone} is run out!",
            "stumped": f"{gone} is stumped off {bowl}!",
        }.get(how, f"{gone} is out, {how}!")
    elif t == "Four":
        said = f"{bat} hits {bowl} for four!"
    elif t == "Six":
        said = f"{bat} hits {bowl} for six!"
    elif out == "dot ball":
        said = f"A dot ball from {bowl}."
    elif out == "wide":
        said = f"A wide from {bowl}."
    elif (extras := d.get("extras") or {}) and not d.get("runs_batter"):  # byes: not the batter's
        said = " and ".join(f"{words(n)} {EXTRAS.get(k, k)}" for k, n in extras.items()) + "."
        said = said[0].upper() + said[1:]
    else:  # "1 run", "2 runs": to the batter on strike
        said = f"{bat}, {_said(str(out))}."
    score = f"{m['team']} {words(s['runs'])} for {words(s['wickets'])}."
    if "chase" not in d:
        return [said, score]
    # "India need 16 runs from the last 5 balls" said shorter, as a commentator would
    chase = re.sub(r" runs? from the last (\d+)", r" from \1", d["chase"])
    return [said, f"{_said(chase)}.", score]


def _f1(header: dict, m: dict) -> list[str]:
    t, out, s = m["type"], m.get("outcome") or "", m["score"]
    driver = _who(m, "driver")
    if t == "Lights out":
        said = f"Lights out at the {header['stage'].split(',')[0]}! {_who(m, 'leader')} leads."
    elif t == "Lead change":
        pits = " in the pit stops" if "pit" in out else ""
        said = f"{driver} takes the lead from {_who(m, 'passed')}{pits}."
    elif t == "Overtake":
        place = re.match(r"P(\d+)", out)
        said = f"{driver} passes {_who(m, 'passed')}" + (
            f" for {PLACES[int(place[1]) - 1]} place." if place else "."
        )
    elif t == "Pit stop":
        said = f"{driver} {out}."
    elif t == "Last lap":
        said = f"{_who(m, 'leader')} starts the final lap in the lead."
    elif t == "Finish":
        return [f"{_who(m, 'winner')} takes the chequered flag and wins."]
    else:  # conditions, safety car, red flag: the outcome is the event, already in words
        said = f"{out[0].upper()}{out[1:]}." if out else f"{t}."
    return [said, f"Lap {words(s['lap'])} of {words(s['laps'])}."]


SPORTS = {"football": _football, "basketball": _basketball, "cricket": _cricket, "f1": _f1}
MAX_WORDS = 20


def fallback_text(header: dict, m: dict) -> str:
    """A line built only from the moment's data, said when the commentator's stays wrong: the
    event first, then what follows from it, dropped from the end until it fits 20 words."""
    parts = SPORTS[m["sport"]](header, m)
    while len(parts) > 1 and len(" ".join(parts).split()) > MAX_WORDS:
        parts.pop()
    return " ".join(parts)
