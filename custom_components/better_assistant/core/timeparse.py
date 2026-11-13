"""Spoken time and date parsing, plus a simple world clock.

    parse("tomorrow at 3", now)          -> (datetime 15:00 tomorrow, "once")
    parse("every weekday at 6:45", now)  -> (next weekday 06:45, "weekdays")
    world_clock("tokyo", now)            -> "It's 3 PM tomorrow in Tokyo, 14 hours ahead of us."

Spoken times: "in 20 minutes", "in an hour and a half", "at 7", "6:30 a.m.", "7 pm tomorrow", "noon",
"tonight at 8", "monday at 9", "every weekday at 6:45", "november 20th at 3", "the 20th", "11/28".
With no AM/PM, a time means the next time that clock time comes round ("7" at 6:28 PM is 7 PM),
for alarms too. When a day or date is given, 1-6 o'clock means PM for reminders and AM for alarms. Pure Python, no Home Assistant imports.
"""
from __future__ import annotations

import datetime as dt
import re
from zoneinfo import ZoneInfo

WORDNUM = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve "
                                      "thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}
WORDNUM.update({"thirty": 30, "forty": 40, "forty five": 45, "fifty": 50, "sixty": 60, "ninety": 90,
                "a": 1, "an": 1, "a couple": 2, "a couple of": 2, "a few": 3, "half an": 0.5, "a half": 0.5})
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]
MON_RE = r"(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec)\.?"
ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
            "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14,
            "fifteenth": 15, "sixteenth": 16, "seventeenth": 17, "eighteenth": 18, "nineteenth": 19,
            "twentieth": 20, "thirtieth": 30, "thirty first": 31}

CITIES = {"tokyo": "Asia/Tokyo", "japan": "Asia/Tokyo", "london": "Europe/London", "england": "Europe/London",
          "uk": "Europe/London", "paris": "Europe/Paris", "france": "Europe/Paris", "berlin": "Europe/Berlin",
          "germany": "Europe/Berlin", "rome": "Europe/Rome", "italy": "Europe/Rome", "madrid": "Europe/Madrid",
          "spain": "Europe/Madrid", "dublin": "Europe/Dublin", "ireland": "Europe/Dublin",
          "amsterdam": "Europe/Amsterdam", "moscow": "Europe/Moscow", "dubai": "Asia/Dubai",
          "india": "Asia/Kolkata", "mumbai": "Asia/Kolkata", "delhi": "Asia/Kolkata", "beijing": "Asia/Shanghai",
          "china": "Asia/Shanghai", "shanghai": "Asia/Shanghai", "hong kong": "Asia/Hong_Kong",
          "singapore": "Asia/Singapore", "seoul": "Asia/Seoul", "korea": "Asia/Seoul", "manila": "Asia/Manila",
          "philippines": "Asia/Manila", "sydney": "Australia/Sydney", "australia": "Australia/Sydney",
          "melbourne": "Australia/Melbourne", "auckland": "Pacific/Auckland", "new zealand": "Pacific/Auckland",
          "hawaii": "Pacific/Honolulu", "honolulu": "Pacific/Honolulu", "alaska": "America/Anchorage",
          "los angeles": "America/Los_Angeles", "california": "America/Los_Angeles",
          "seattle": "America/Los_Angeles", "san francisco": "America/Los_Angeles",
          "las vegas": "America/Los_Angeles", "denver": "America/Denver", "phoenix": "America/Phoenix",
          "arizona": "America/Phoenix", "chicago": "America/Chicago", "texas": "America/Chicago",
          "dallas": "America/Chicago", "houston": "America/Chicago", "new york": "America/New_York",
          "florida": "America/New_York", "miami": "America/New_York", "boston": "America/New_York",
          "atlanta": "America/New_York", "toronto": "America/Toronto", "vancouver": "America/Vancouver",
          "mexico city": "America/Mexico_City", "mexico": "America/Mexico_City", "sao paulo": "America/Sao_Paulo",
          "brazil": "America/Sao_Paulo", "cairo": "Africa/Cairo", "egypt": "Africa/Cairo",
          "johannesburg": "Africa/Johannesburg", "south africa": "Africa/Johannesburg", "nairobi": "Africa/Nairobi",
          "kenya": "Africa/Nairobi", "israel": "Asia/Jerusalem", "jerusalem": "Asia/Jerusalem",
          "bangkok": "Asia/Bangkok", "thailand": "Asia/Bangkok", "vietnam": "Asia/Ho_Chi_Minh",
          "taiwan": "Asia/Taipei", "jakarta": "Asia/Jakarta"}


def words_to_digits(t):
    for w in sorted(ORDINALS, key=len, reverse=True):         # only "the 20th"/"november 20th", not "30 seconds"
        t = re.sub(rf"\b(the |{MON_RE} ){w}\b", lambda m: f"{m.group(1)}{ORDINALS[w]}th", t)
    t = re.sub(r"\b(twenty|thirty|forty|fifty)[ -](one|two|three|four|five|six|seven|eight|nine)\b",
               lambda m: str(WORDNUM[m.group(1)] + WORDNUM[m.group(2)]), t)
    for w in sorted(WORDNUM, key=len, reverse=True):
        if w in ("a", "an"):
            continue
        t = re.sub(rf"\b{w}\b", str(WORDNUM[w]), t)
    return t


def clean(t):
    t = t.lower().strip(" .?!")
    t = re.sub(r"\bin (a|an) (hour|minute)", r"in 1 \2", t)
    t = re.sub(r"\b(a )?half (an )?hour\b", "30 minutes", t)
    t = re.sub(r"\b(hours?) and a half\b", r"\1 and 30 minutes", t)
    t = re.sub(r"\b([ap])\.?\s?m\.?", r"\1m", t)          # a.m. / p. m. -> am / pm
    t = t.replace("o'clock", "").replace("oclock", "")
    t = re.sub(r"\s+", " ", t)
    t = words_to_digits(t).strip()
    # half past 6 / quarter past 6 / quarter to 7 / 20 past 6 / 10 to 7  ->  6:30, 6:15, 6:45, 6:20, 6:50
    t = re.sub(r"\b(half|quarter|\d{1,2})(?: minutes?)? past (\d{1,2})\b",
               lambda m: f"{m.group(2)}:{ {'half': 30, 'quarter': 15}.get(m.group(1)) or int(m.group(1)):02d}", t)
    t = re.sub(r"\b(quarter|\d{1,2})(?: minutes?)? (?:to|till|til) (\d{1,2})\b",
               lambda m: f"{(int(m.group(2)) - 1) % 12 or 12}:{60 - ({'quarter': 15}.get(m.group(1)) or int(m.group(1))):02d}", t)
    return t


def fmt_time(d):
    return (f"{d.hour % 12 or 12}:{d.minute:02d} " + ("AM" if d.hour < 12 else "PM")).replace(":00 ", " ")


def say_when(d, now):
    days = (d.date() - now.date()).days
    if days == 0:
        day = "today" if d.hour < 17 else "tonight"
    elif days == 1:
        day = "tomorrow"
    elif days < 7:
        day = d.strftime("%A")
    else:
        day = d.strftime("%A, %B ") + str(d.day)
    return f"{day} at {fmt_time(d)}"


def pull_date(t, now):
    """'november 20th' / '20th of november' / 'the 20th' / '11/20' -> (date or None, text without it)."""
    pats = [rf"\b(?:on )?{MON_RE} (\d{{1,2}})(?:st|nd|rd|th)?\b",
            rf"\b(?:on )?(?:the )?(\d{{1,2}})(?:st|nd|rd|th)? of {MON_RE}",
            r"\b(?:on )?the (\d{1,2})(?:st|nd|rd|th)\b",
            r"\b(?:on )?(\d{1,2})/(\d{1,2})\b"]
    for i, p in enumerate(pats):
        m = re.search(p, t)
        if not m:
            continue
        g = m.groups()
        try:
            if i == 0:
                mon, day = next(k for k, n in enumerate(MONTHS) if n.startswith(g[0][:3])) + 1, int(g[1])
            elif i == 1:
                mon, day = next(k for k, n in enumerate(MONTHS) if n.startswith(g[1][:3])) + 1, int(g[0])
            elif i == 2:
                mon, day = now.month, int(g[0])
                if day < now.day:
                    mon = mon % 12 + 1
            else:
                mon, day = int(g[0]), int(g[1])
            d = dt.date(now.year, mon, day)
            if d < now.date():
                d = dt.date(now.year + 1, mon, day)
        except (ValueError, StopIteration):
            continue
        return d, (t[:m.start()] + " " + t[m.end():]).strip()
    return None, t


def parse(text, now, alarm=False):
    t = clean(text)
    repeat = "once"
    on_date, t = pull_date(t, now)
    if on_date:
        # a calendar date: read the clock time as if on that day ("at 3" -> 3 PM, like reminders)
        rest = re.sub(r"\b(today|tonight|tomorrow)\b", "", t)
        sub, _ = parse(rest, dt.datetime.combine(on_date, dt.time(0, 0)), alarm)
        if sub is None:
            return None, repeat
        if not alarm and 1 <= sub.hour <= 6 and not re.search(r"\b(am|morning)\b", rest):
            sub += dt.timedelta(hours=12)                  # a date given: "at 3" means 3 PM for an event
        return dt.datetime.combine(on_date, sub.time()), repeat
    m = re.search(r"\bevery (weekday|weekdays|week day|day|morning|weekend|weekend day)s?\b|\b(daily)\b", t)
    if m:
        k = m.group(1) or "day"
        repeat = "weekdays" if "week" in k and "end" not in k else "weekends" if "end" in k else "daily"
        t = (t[:m.start()] + t[m.end():]).strip()
        if k == "morning":
            t += " morning"                                # "every morning at 7" is an AM hint
    # relative: in 20 minutes / in 1 hour and 30 minutes / in 1.5 hours / in 0.5 hour
    m = re.search(r"\bin (\d+(?:\.\d+)?|\.5) ?(minute|min|hour|hr)s?(?: and (\d+(?:\.\d+)?) ?(minute|min)s?)?(?: and a half)?\b", t)
    if m:
        n = float(m.group(1))
        mins = n * 60 if m.group(2).startswith("h") else n
        if m.group(3):
            mins += float(m.group(3))
        if "and a half" in m.group(0):
            mins += 30 if m.group(2).startswith("h") else 0.5
        return now + dt.timedelta(minutes=round(mins)), repeat
    m = re.search(r"\bin (\d+(?:\.\d+)?) ?(second|sec)s?\b", t)
    if m:
        return now + dt.timedelta(seconds=float(m.group(1))), repeat
    # day words
    day_off = None
    if "day after tomorrow" in t:
        day_off = 2
    elif "tomorrow" in t:
        day_off = 1
    elif re.search(r"\b(today|tonight|this (morning|afternoon|evening))\b", t):
        day_off = 0
    wd = next((i for i, d in enumerate(DAYS) if re.search(rf"\b{d}\b", t)), None)
    pm_hint = bool(re.search(r"\b(tonight|evening|afternoon|pm)\b", t))
    am_hint = bool(re.search(r"\b(morning|am)\b", t))
    if re.search(r"\bnoon\b|\bmidday\b", t):
        h, mi, pm_hint = 12, 0, True
    elif re.search(r"\bmidnight\b", t):
        h, mi, day_off = 0, 0, (1 if day_off in (None, 0) else day_off)
    else:
        m = re.search(r"\b(\d{1,2})(?::(\d{2})|\s(\d{2})\b)?\s?(am|pm)?\b", re.sub(r"\b(today|tomorrow|tonight)\b", "", t))
        if not m:
            return None, repeat
        h, mi = int(m.group(1)), int(m.group(2) or m.group(3) or 0)
        if m.group(4) == "pm":
            pm_hint = True
        if m.group(4) == "am":
            am_hint = True
        if h > 23 or mi > 59:
            return None, repeat
        if h == 12 and am_hint:
            h = 0
        elif h < 12 and pm_hint:
            h += 12
    base = now.replace(second=0, microsecond=0)
    if (wd is not None or day_off is not None) and 1 <= h <= 6 and not am_hint and not pm_hint and not alarm:
        h += 12                                            # "tomorrow at 3" means 3 PM for a reminder or event
    if wd is not None:
        delta = (wd - now.weekday()) % 7
        cand = base.replace(hour=h, minute=mi) + dt.timedelta(days=delta)
        if cand <= now:
            cand += dt.timedelta(days=7)
        return cand, repeat
    if day_off is not None:
        cand = base.replace(hour=h, minute=mi) + dt.timedelta(days=day_off)
        if day_off == 0 and cand <= now and h < 12 and not am_hint:
            cand += dt.timedelta(hours=12)                 # "tonight at 8" said as 8 → 8 PM
        return cand, repeat
    # No AM/PM said: like Google, take the next time that clock time comes round (7 at 6:28 PM -> 7 PM).
    ambiguous = 1 <= h <= 12 and not am_hint and not pm_hint
    hours = [h % 12, h % 12 + 12] if ambiguous else [h % 24]
    if repeat == "weekdays":
        ok_day = lambda d: d.weekday() < 5
    elif repeat == "weekends":
        ok_day = lambda d: d.weekday() >= 5
    else:
        ok_day = lambda d: True
    cands = [base.replace(hour=hh, minute=mi) + dt.timedelta(days=k) for k in range(8) for hh in hours]
    return min(c for c in cands if c > now and ok_day(c)), repeat


def world_clock(place: str, now: dt.datetime | None = None) -> str | None:
    """Spoken local time in a city or country, or None when the place is unknown.

    `now` is an aware datetime for "here" (defaults to the system local time)."""
    p = re.sub(r"[^a-z ]", "", place.lower()).strip()
    p = re.sub(r"^(the|in) ", "", p)
    key = p if p in CITIES else next((c for c in sorted(CITIES, key=len, reverse=True)
                                      if re.search(rf"\b{c}\b", p)), None)
    if not key:
        return None
    here = now if now is not None and now.tzinfo else dt.datetime.now().astimezone()
    there = here.astimezone(ZoneInfo(CITIES[key]))
    diff = round((there.utcoffset() - here.utcoffset()).total_seconds() / 3600, 1)
    day = "" if there.date() == here.date() else (" tomorrow" if there.date() > here.date() else " yesterday")
    rel = "the same time as here" if diff == 0 else \
        f"{abs(diff):g} hour{'s' if abs(diff) != 1 else ''} {'ahead of' if diff > 0 else 'behind'} us"
    return f"It's {fmt_time(there)}{day} in {key.title()}, {rel}."
