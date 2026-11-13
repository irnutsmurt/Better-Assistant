"""Pure helpers for reminders, notes, messages, alarms and the stopwatch: parsing what was said and
phrasing what to say back. No Home Assistant imports."""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from .timeparse import fmt_time, parse, say_when

# ------------------------------------------------------------------ reminders
TIME_MARKERS = re.compile(
    r"\b(in|at|on|by|tomorrow|tonight|today|this|next|every|daily|noon|midnight|the day after|the \d|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|january|february|march|april|may|june|"
    r"july|august|september|october|november|december|\d{1,2}(?::\d{2})?\s?(?:am|pm|a\.m\.|p\.m\.))\b", re.I)
LEAD = re.compile(r"^(?:to|that|about|i need to|i have to|i've got to)\s+", re.I)
PLACE = re.compile(
    r"^(?P<task>.+?)\s+when\s+(?:i|he|she|they|we|you|\w+)\s+"
    r"(?P<verb>gets? back home|gets? home|gets? back|comes? home|arrives? home|"
    r"gets? to|arrives? at|reach(?:es)?|leaves?|gets? out of)\b\s*(?P<place>.*?)\W*$", re.I)


@dataclass
class ReminderRequest:
    task: str
    kind: str = "time"               # "time" | "arrive" | "leave" | "none" (no time said)
    at: dt.datetime | None = None
    repeat: str = "once"
    place: str | None = None         # "home" or the spoken place name, for arrive/leave


def _task(text: str) -> str:
    return LEAD.sub("", text.strip(" ,.")).strip(" ,.")


def _parse_when(when: str, now: dt.datetime):
    """parse(), but a day without a clock time gets a sensible one ("tomorrow morning" -> 9 AM)."""
    at, repeat = parse(when, now)
    if at or not re.search(r"\b(today|tonight|tomorrow|morning|afternoon|evening|monday|tuesday|wednesday|"
                           r"thursday|friday|saturday|sunday|the \d+(?:st|nd|rd|th)|\d+/\d+|january|february|march|april|may|june|"
                           r"july|august|september|october|november|december)\b", when, re.I):
        return at, repeat
    default = ("at 8 pm" if re.search(r"tonight|evening", when, re.I) else
               "at 2 pm" if re.search(r"afternoon", when, re.I) else "at 9 am")
    return parse(f"{when} {default}", now)


def parse_reminder(text: str, now: dt.datetime) -> ReminderRequest:
    """'to call mom tomorrow at 5' / 'at 5 to call mom' / 'to buy milk when I leave work'."""
    t = re.sub(r"\s+", " ", text.strip(" ,.?!"))
    m = PLACE.match(LEAD.sub("", t))
    if m:
        verb, place = m.group("verb").lower(), m.group("place").strip().removeprefix("the ").strip()
        if "home" in verb or verb.startswith(("get back", "gets back")):
            return ReminderRequest(_task(m.group("task")), "arrive", place="home")
        if verb.startswith("leave"):
            return ReminderRequest(_task(m.group("task")), "leave", place=place or "home")
        if verb.startswith("get out"):
            return ReminderRequest(_task(m.group("task")), "leave", place=place or "home")
        if place in ("home", "the house", "house"):
            return ReminderRequest(_task(m.group("task")), "arrive", place="home")
        return ReminderRequest(_task(m.group("task")), "arrive", place=place or None)
    # time first: "at 5 to call mom", "tomorrow morning that the bins go out"
    lead = re.match(r"^(?P<when>.+?)\s+(?:to|that|about)\s+(?P<task>.+)$", t, re.I)
    if lead and not LEAD.match(t) and TIME_MARKERS.match(lead.group("when")):
        at, repeat = _parse_when(lead.group("when"), now)
        if at:
            return ReminderRequest(_task(lead.group("task")), "time", at, repeat)
    body = LEAD.sub("", t)
    for mk in TIME_MARKERS.finditer(body):
        if mk.start() == 0:
            continue
        at, repeat = _parse_when(body[mk.start():], now)
        if at:
            return ReminderRequest(_task(body[:mk.start()]), "time", at, repeat)
    return ReminderRequest(_task(body), "none")


def flip_pronouns(text: str) -> str:
    """'I put my keys in the drawer' -> 'you put your keys in the drawer'."""
    swaps = {"i": "you", "i'm": "you're", "im": "you're", "i've": "you've", "i'll": "you'll", "i'd": "you'd",
             "me": "you", "my": "your", "mine": "yours", "myself": "yourself"}
    out = []
    for w in re.findall(r"\S+|\s+", text):
        core = re.match(r"^([\"'(]*)([\w']+)([^\w']*)$", w)
        if core and core.group(2).lower() in swaps:
            rep = swaps[core.group(2).lower()]
            out.append(core.group(1) + rep + core.group(3))
        else:
            out.append(w)
    return "".join(out)


def sentence(text: str) -> str:
    text = text.strip()
    if not text:
        return text
    text = text[:1].upper() + text[1:]
    return text if text[-1] in ".!?" else text + "."


# ------------------------------------------------------------------ notes
NOTE_STOP = set("a an the of to in on at is are was were my your i you it its where did put leave left "
                "have has and or for with".split())


def _words(t: str) -> set[str]:
    return {w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w
            for w in re.findall(r"[a-z0-9]+", t.lower()) if w not in NOTE_STOP}


def best_note(query: str, notes: list[str]) -> str | None:
    """The note sharing the most words with the query (newest wins ties), or None."""
    q = _words(query)
    best, score = None, 0
    for note in notes:
        s = len(q & _words(note))
        if s and s >= score:
            best, score = note, s
    return best


def note_from(text: str, put: str | None) -> str:
    """'remember I put the keys in the drawer' -> 'I put the keys in the drawer'."""
    text = text.strip(" ,.")
    return f"I {put} {text}" if put else text


# ------------------------------------------------------------------ alarms
def next_alarm(hour: int, minute: int, repeat: str, after: dt.datetime) -> dt.datetime:
    cand = after.replace(hour=hour, minute=minute, second=0, microsecond=0)
    for _ in range(9):
        if cand > after and (repeat in ("once", "daily") or
                             (repeat == "weekdays" and cand.weekday() < 5) or
                             (repeat == "weekends" and cand.weekday() >= 5)):
            return cand
        cand += dt.timedelta(days=1)
    return cand


def say_alarm(at: dt.datetime, repeat: str, now: dt.datetime) -> str:
    if repeat == "daily":
        return f"every day at {fmt_time(at)}"
    if repeat == "weekdays":
        return f"every weekday at {fmt_time(at)}"
    if repeat == "weekends":
        return f"every weekend day at {fmt_time(at)}"
    return say_when(at, now)


# ------------------------------------------------------------------ stopwatch
def say_duration(seconds: float) -> str:
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    parts = [f"{n} {u}{'s' if n != 1 else ''}" for n, u in ((h, "hour"), (m, "minute"), (s, "second")) if n]
    if not parts:
        return "0 seconds"
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


@dataclass
class Stopwatch:
    started: dt.datetime | None = None
    laps: list[float] = field(default_factory=list)


# ------------------------------------------------------------------ people
def name_index(people: list[tuple[str, str, list[str]]]) -> dict[str, list[str]]:
    """[(entity_id, full name, aliases)] -> spoken name (lower-case) -> person entity ids.
    Full name, first name and every alias are all ways to say someone."""
    index: dict[str, list[str]] = {}
    for entity_id, full, aliases in people:
        for n in {full, full.split()[0] if full.split() else full, *aliases}:
            n = (n or "").strip().lower()
            if n and entity_id not in index.setdefault(n, []):
                index[n].append(entity_id)
    return index


def resolve_person(spoken: str, people: list[tuple[str, str, list[str]]]) -> tuple[str | None, str | None]:
    """(entity id, None) when one person matches; (None, question) when several do; (None, None) if none."""
    ids = name_index(people).get(spoken.strip().lower(), [])
    if len(ids) == 1:
        return ids[0], None
    if not ids:
        return None, None
    names = [full for eid, full, _ in people if eid in ids]
    return None, "Did you mean " + ", ".join(names[:-1]) + " or " + names[-1] + "?"


# ------------------------------------------------------------------ snooze rules
MAX_SNOOZE = 30
MAX_SNOOZE_LIMIT = 10


def _mins(n: int) -> str:
    return f"{n} minute{'s' if n != 1 else ''}"


def snooze_decision(requested: int | None, default: int, limit: int | None, used: int) -> tuple[int | None, str]:
    """(minutes to snooze or None to refuse, what to say). limit None = unlimited, 0 = no snoozing,
    n = n snoozes per alarm; `used` = snoozes already taken for this ringing alarm."""
    if limit == 0:
        return None, "Snoozing is turned off. Time to get up!"
    if limit is not None and used >= limit:
        return None, "That was your last snooze. Time to get up!"
    minutes = int(requested or default)
    capped = minutes > MAX_SNOOZE
    minutes = max(1, min(MAX_SNOOZE, minutes))
    reply = f"Okay, {minutes} more minute{'s' if minutes != 1 else ''}"
    reply += f" (the longest snooze is {MAX_SNOOZE} minutes)." if capped else "."
    if limit is not None:
        left = limit - used - 1
        reply += " That was your last snooze." if left == 0 else f" You have {left} snooze{'s' if left != 1 else ''} left."
    return minutes, reply


def snooze_length_reply(requested: int) -> tuple[int, str]:
    minutes = max(1, min(MAX_SNOOZE, int(requested)))
    note = f" (the longest snooze is {MAX_SNOOZE} minutes)" if requested > MAX_SNOOZE else ""
    return minutes, f"Okay, snooze is now {_mins(minutes)}{note}."


def snooze_limit_reply(requested: int | None) -> tuple[bool, int | None, str]:
    """Voice -> (snoozing enabled, limit or None for unlimited, reply).
    A number (0 turns snoozing off), or None for 'no snooze limit' / 'turn on snoozing'."""
    if requested is None:
        return True, None, "Okay, there's no snooze limit. You can snooze as often as you like."
    n = max(0, int(requested))
    if n == 0:
        return False, None, "Okay, no snoozing. The alarm will ring until you stop it."
    capped = n > MAX_SNOOZE_LIMIT
    n = min(n, MAX_SNOOZE_LIMIT)
    note = f" (the most is {MAX_SNOOZE_LIMIT})" if capped else ""
    return True, n, f"Okay, you can snooze {n} time{'s' if n != 1 else ''} per alarm{note}."


def effective_limit(enabled: bool, limit: int | None) -> int | None:
    """For snooze_decision: 0 when snoozing is off, else the limit (None = unlimited)."""
    return 0 if not enabled else (limit or None)


def describe_snooze(limit: int | None, default: int) -> str:
    if limit is None:
        return f"There's no snooze limit. Each snooze is {_mins(default)}."
    if limit == 0:
        return "Snoozing is turned off. The alarm rings until you stop it."
    return f"You can snooze {limit} time{'s' if limit != 1 else ''} per alarm, {_mins(default)} each."


def snooze_from_page(enabled: bool, raw_limit) -> tuple[bool, int | None]:
    """Settings page -> (snoozing enabled, limit). Empty = no limit; 0 turns snoozing off."""
    limit = None if raw_limit in (None, "") else max(0, min(MAX_SNOOZE_LIMIT, int(raw_limit)))
    if limit == 0:
        return False, None
    return bool(enabled), limit


# ------------------------------------------------------------------ which speaker an alarm rings on
ALL_SPEAKERS = "all"
_ALL = r"(?:everywhere|all over the house|on all (?:the |my )?speakers|on every speaker|in every room|on all of them)"
_NOT_PLACE = re.compile(
    r"^(?:the )?(?:morning|afternoon|evening|night|weekdays?|weekends?|day|week|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|january|february|march|april|may|june|july|"
    r"august|september|october|november|december|tomorrow|today|tonight|\d|an? \w+ (?:hour|minute)|"
    r"(?:a|an|one|two|three|four|five|six|seven|eight|nine|ten|twenty|thirty|half|\d+) ?(?:hour|minute|min|hr|sec))", re.I)


def split_alarm_place(text: str) -> tuple[str, str | None]:
    """'7 in the kitchen' -> ('7', 'kitchen'); 'everywhere for 7' -> ('for 7', 'all');
    'the bedroom speaker at 6' -> ('at 6', 'bedroom speaker'). Time words ('in the morning', 'on monday',
    'in 20 minutes') are never taken as a place."""
    t = re.sub(r"\s+", " ", text.strip(" ,.?!"))
    m = re.search(rf"[ ,]+{_ALL}$", t, re.I) or re.match(rf"^{_ALL}[ ,]+", t, re.I)
    if m:
        return (t[:m.start()] if m.start() else t[m.end():]).strip(" ,"), ALL_SPEAKERS
    # the last " on/in ..." that isn't a time ("6 in the morning on the bedroom speaker")
    for m in reversed(list(re.finditer(r"[ ,]+(?:on|in) (?:the )?(?=[a-z])", t, re.I))):
        place = t[m.end():]
        if re.fullmatch(r"[a-z][\w' -]*", place, re.I) and not re.search(r"\b(?:on|in)\b", place, re.I):
            if not _NOT_PLACE.match(place):
                return t[:m.start()].strip(" ,"), place.strip().lower()
            break
    m = re.match(r"^(?:(?:on|in) )?(?:the )?(?P<place>[a-z][\w' -]*?)(?P<rest> (?:for|at) .+)$", t, re.I)
    if m and (t.lower().startswith(("on ", "in ", "the "))) and not _NOT_PLACE.match(m.group("place")):
        return m.group("rest").strip(), m.group("place").strip().lower()
    return t, None


def resolve_speaker(spoken: str, speakers: list[dict]) -> tuple[list[str] | None, str | None]:
    """Spoken place -> (satellite entity ids, None), (None, 'Did you mean ...?') or (None, None).
    speakers: [{"entity_id", "name", "names": [satellite/device names + aliases], "area": area name,
    "area_aliases": [...]}]. Exact satellite/device names and aliases first, then an area name (all of
    that area's satellites), then names that start with the spoken words."""
    full = spoken.strip().lower().removeprefix("the ").strip()
    p = re.sub(r"\s+(?:speaker|satellite|room)$", "", full).strip()
    if p == ALL_SPEAKERS:
        return [s["entity_id"] for s in speakers], None

    def low(n):
        return (n or "").strip().lower()

    exact = [s for s in speakers if any(low(n) == full for n in s["names"])]      # the whole name
    if len(exact) == 1:
        return [exact[0]["entity_id"]], None
    if not exact:
        area = [s for s in speakers if p and (low(s.get("area")) == p or p in map(low, s.get("area_aliases") or []))]
        if area:                                       # a bare area name: that area's speakers
            return [s["entity_id"] for s in area], None
        exact = [s for s in speakers if any(low(n) == p or low(n).startswith(p + " ") for n in s["names"])]
        if len(exact) == 1:
            return [exact[0]["entity_id"]], None
    if not exact:
        return None, None
    names = [f"the {s['name'].lower()}" for s in exact]
    return None, "Did you mean " + ", ".join(names[:-1]) + " or " + names[-1] + "?"


def say_where(targets, names: dict[str, str]) -> str:
    """'on the bedroom speaker' / 'on all speakers' / 'on the kitchen speaker and the den speaker'."""
    if targets == ALL_SPEAKERS:
        return "on all speakers"
    said = [f"the {names.get(t, t).lower()}" for t in targets]
    return "on " + (said[0] if len(said) == 1 else ", ".join(said[:-1]) + " and " + said[-1])
