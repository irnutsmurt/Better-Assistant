"""Calendar phrasing: reading a spoken event ("dentist tomorrow at 3"), the date ranges people ask
about, and reading events back. Pure Python, no Home Assistant imports."""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from .features import TIME_MARKERS
from .timeparse import DAYS, clean, fmt_time, parse, pull_date

EVENT_HOURS = 1
DAY_WORDS = re.compile(r"\b(today|tonight|tomorrow|day after tomorrow|monday|tuesday|wednesday|thursday|friday|"
                       r"saturday|sunday)\b", re.I)
CLOCK = re.compile(r"\d|\bnoon\b|\bmidnight\b|\bmidday\b", re.I)


@dataclass
class EventRequest:
    title: str
    start: dt.datetime | dt.date
    end: dt.datetime | dt.date
    all_day: bool


def _date_only(when: str, now: dt.datetime) -> dt.date | None:
    t = clean(when)
    d, _rest = pull_date(t, now)
    if d:
        return d
    if "day after tomorrow" in t:
        return (now + dt.timedelta(days=2)).date()
    if "tomorrow" in t:
        return (now + dt.timedelta(days=1)).date()
    if re.search(r"\b(today|tonight)\b", t):
        return now.date()
    wd = next((i for i, day in enumerate(DAYS) if re.search(rf"\b{day}\b", t)), None)
    if wd is not None:
        days = (wd - now.weekday()) % 7
        if re.search(r"\bnext\b", t) and days == 0:
            days = 7
        return (now + dt.timedelta(days=days)).date()
    return None


def _when(when: str, now: dt.datetime):
    """(start, all_day) or None."""
    if CLOCK.search(clean(when)):
        at, _repeat = parse(when, now)                # a day/date with 1-6 o'clock means PM (events)
        if at:
            return at, False
    day = _date_only(when, now)
    return (day, True) if day else None


def parse_event(text: str, now: dt.datetime) -> EventRequest | None:
    """'dentist tomorrow at 3' -> Dentist, tomorrow 15:00-16:00. 'mom's birthday on june 3rd' -> all
    day. Time words are taken out of the title. None when no day or time was said."""
    t = re.sub(r"\s+", " ", text.strip(" ,.?!"))
    found = None
    if TIME_MARKERS.match(t):                                  # "tomorrow at 3, dentist"
        words = t.split()
        cands = [(cut, got) for cut in range(1, len(words)) if (got := _when(" ".join(words[:cut]), now))]
        timed = [c for c in cands if not c[1][1]]
        pick = max(timed, key=lambda c: c[0]) if timed else (min(cands, key=lambda c: c[0]) if cands else None)
        if pick:                                               # longest clock time, else shortest date
            found = (" ".join(words[pick[0]:]), pick[1])
    else:                                                      # "dentist tomorrow at 3"
        for mk in TIME_MARKERS.finditer(t):
            got = _when(t[mk.start():], now)
            if got:
                found = (t[:mk.start()], got)
                break
    if not found:
        return None
    title, (start, all_day) = found
    title = re.sub(r"\s+(?:on|at|for|from|this|next|the)$", "", title.strip(" ,"), flags=re.I).strip(" ,")
    title = re.sub(r"^(?:for|to|,)\s+", "", title, flags=re.I).strip()
    if not title:
        return None
    title = title[:1].upper() + title[1:]
    if all_day:
        return EventRequest(title, start, start + dt.timedelta(days=1), True)
    return EventRequest(title, start, start + dt.timedelta(hours=EVENT_HOURS), False)


def day_range(phrase: str, now: dt.datetime) -> tuple[dt.datetime, dt.datetime, str]:
    """'today' / 'tomorrow' / 'this week' / 'this weekend' / 'next week' -> (start, end, spoken)."""
    p = (phrase or "today").lower().strip()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if p in ("tomorrow",):
        return midnight + dt.timedelta(days=1), midnight + dt.timedelta(days=2), "tomorrow"
    if p in ("this week", "the week"):
        return now, midnight + dt.timedelta(days=7 - now.weekday()), "this week"
    if p in ("this weekend", "the weekend", "weekend"):
        sat = midnight + dt.timedelta(days=(5 - now.weekday()) % 7)
        start = max(now, sat) if now.weekday() >= 5 else sat
        sun_end = midnight + dt.timedelta(days=(6 - now.weekday()) % 7 + 1)
        return start, sun_end, "this weekend"
    if p in ("next week",):
        monday = midnight + dt.timedelta(days=7 - now.weekday())
        return monday, monday + dt.timedelta(days=7), "next week"
    return now, midnight + dt.timedelta(days=1), "today"


def _as_dt(value) -> tuple[dt.datetime | dt.date, bool]:
    if isinstance(value, dt.datetime):
        return value, False
    if isinstance(value, dt.date):
        return value, True
    s = str(value)
    if len(s) == 10:
        return dt.date.fromisoformat(s), True
    return dt.datetime.fromisoformat(s), False


def say_events(events: list[dict], spoken_range: str, now: dt.datetime, limit: int = 6) -> str:
    """events: [{"summary", "start"}] (ISO strings, dates or datetimes)."""
    if not events:
        return f"There's nothing on your calendar {spoken_range}."
    def key(item):
        (start, all_day), _summary = item
        return dt.datetime.combine(start, dt.time()) if all_day else start.replace(tzinfo=None)

    items = sorted(((_as_dt(e["start"]), e.get("summary") or "an event") for e in events), key=key)
    multi_day = spoken_range not in ("today", "tomorrow")
    said = []
    for (start, all_day), summary in items[:limit]:
        day = ""
        if not all_day:
            start = start.replace(tzinfo=None)
        if multi_day:
            d = start if all_day else start.date()
            day = "Today" if d == now.date() else "Tomorrow" if d == now.date() + dt.timedelta(days=1) else \
                d.strftime("%A")
        if all_day:
            said.append(f"{day + ', ' if day else ''}all day: {summary}")
        else:
            said.append(f"{day + ' ' if day else ''}at {fmt_time(start)}: {summary}".strip())
    head = f"You have {len(items)} thing{'s' if len(items) != 1 else ''} {spoken_range}. "
    more = f" And {len(items) - limit} more." if len(items) > limit else ""
    return head + ". ".join(s[:1].upper() + s[1:] for s in said) + "." + more


def say_next(event: dict | None, now: dt.datetime) -> str:
    if not event:
        return "You don't have anything coming up on your calendar."
    start, all_day = _as_dt(event["start"])
    summary = event.get("summary") or "an event"
    if all_day:
        days = (start - now.date()).days
        when = "today" if days == 0 else "tomorrow" if days == 1 else start.strftime("%A, %B ") + str(start.day)
        return f"Your next event is {summary}, {when}, all day."
    local = start.replace(tzinfo=None)
    days = (local.date() - now.date()).days
    when = ("today" if days == 0 else "tomorrow" if days == 1 else
            local.strftime("%A") if days < 7 else local.strftime("%A, %B ") + str(local.day))
    return f"Your next event is {summary}, {when} at {fmt_time(local)}."
