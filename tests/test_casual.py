"""How real people ask: ~1000 everyday, terse, misheard (speech-to-text) and non-native requests, written
without looking at the sentence patterns (tests/data/phrasings.jsonl). This checks the agent's own
matching only (Home Assistant's built-in sentences run first on a real speaker and catch more), so the
floors below are what this matcher reaches on its own; they only ever go up."""
import collections
import json
from pathlib import Path

from core.intents import recognize

ROWS = [json.loads(line) for line in (Path(__file__).parent / "data" / "phrasings.jsonl").read_text().splitlines() if line]
AREAS = ["kitchen", "living room", "bedroom", "garage", "kids room", "office"]
LISTS = {
    "area": AREAS,
    "light_target": {**{a: f"area:{a}" for a in AREAS}, **{f"{a} lights": f"area:{a}" for a in AREAS},
                     **{f"{a} light": f"area:{a}" for a in AREAS}, "porch light": "light.porch", "lamp": "light.lamp"},
    "music_target": {**{a: f"area:{a}" for a in AREAS}, "everywhere": "all"},
    "calendar": {"family": "calendar.family", "work": "calendar.work"},
    "place": {"front door": "front door", "driveway": "driveway", "backyard": "backyard", "porch": "porch"},
    "camera": {"front door": "camera.front", "driveway": "camera.drive", "doorbell": "camera.front"},
    "tv": {"tv": "media_player.tv", "living room tv": "media_player.tv", "bedroom tv": "media_player.btv"},
    "tv_source": {"hdmi 1": "HDMI 1", "hdmi 2": "HDMI 2", "playstation": "HDMI 2"},
    "tv_app": {"netflix": "Netflix", "youtube": "YouTube", "hulu": "Hulu", "disney plus": "Disney+"},
    "bed_preset": {"read": "read", "reading": "read", "flat": "flat", "zero g": "zero_g", "snore": "snore"},
    "climate_mode": {"heat": "heat", "cool": "cool", "off": "off", "auto": "heat_cool"},
    "climate_preset": {"eco": "eco", "away": "away", "home": "home"},
    "battery_thing": {"front door lock": "sensor.lock", "smoke detector": "sensor.smoke", "remote": "sensor.remote"},
    "help_topic": {"alarms": "alarms", "music": "music", "timers": "timers"},
    "door": {"garage door": "cover.garage", "garage": "cover.garage"},
}
# intents a real speaker hands to Home Assistant's built-ins, and a feature that doesn't exist yet
SKIP = {"TimedCommand", "DelayedCommand", "RoomOn", "RoomOff"}
FLOOR = {"casual": 0.75, "stt": 0.79, "nonnative": 0.53, "terse": 0.57}


def test_people_are_understood():
    ok = collections.Counter()
    total = collections.Counter()
    for row in ROWS:
        if row["intent"] in SKIP or row["intent"] == "NONE":
            continue
        m = recognize(row["text"], ["sam", "alex", "rob"], lists=LISTS)
        total[row["style"]] += 1
        ok[row["style"]] += bool(m and m.intent == row["intent"])
    rates = {s: ok[s] / total[s] for s in total}
    assert all(rates[s] >= FLOOR[s] for s in FLOOR), rates


def test_everyday_questions_are_left_alone():
    """General questions and near misses ("how do I set an alarm on my iphone") never become commands."""
    allowed = {"remind me what the capital of france is"}       # a reminder is a fair reading of that one
    hits = [(r["text"], m.intent) for r in ROWS if r["intent"] == "NONE" and r["text"] not in allowed
            and (m := recognize(r["text"], ["sam", "alex", "rob"], lists=LISTS))]
    assert hits == []
