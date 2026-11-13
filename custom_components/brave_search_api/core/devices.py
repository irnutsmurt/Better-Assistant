"""Pure helpers for rooms and lights, climate, TV, beds, the health report, outside activity, night
mode and help. No Home Assistant imports: callers pass plain values."""
from __future__ import annotations

import datetime as dt
import re

# ------------------------------------------------------------------ lights
def step_brightness(current: int | None, step_pct: int, up: bool) -> int:
    """New brightness percent after one dim/brighten step (current is 0-255 or None = off)."""
    pct = round((current or 0) * 100 / 255)
    return max(1, min(100, pct + (step_pct if up else -step_pct)))


def step_kelvin(current: int | None, step: int, warmer: bool, low: int = 2000, high: int = 6500) -> int:
    """Warmer = lower kelvin."""
    k = current or (low + high) // 2
    return max(low, min(high, k - step if warmer else k + step))


# ------------------------------------------------------------------ climate
MODE_WORDS = {"heat": ["heat", "heating", "the heat"], "cool": ["cool", "cooling", "ac", "a c", "air conditioning",
                                                                 "the ac", "the air conditioning", "air conditioner"],
              "heat_cool": ["heat and cool", "heat cool", "auto heat cool"], "auto": ["auto", "automatic"],
              "off": ["off"], "dry": ["dry", "dehumidify"], "fan_only": ["fan", "fan only", "the fan"]}


def climate_mode_words(hvac_modes: list[str]) -> dict[str, str]:
    """Spoken word -> hvac mode, only for modes this thermostat supports."""
    out = {}
    for mode in hvac_modes or []:
        for word in MODE_WORDS.get(mode, [mode.replace("_", " ")]):
            out[word] = mode
    return out


def preset_words(presets: list[str]) -> dict[str, str]:
    out = {}
    for p in presets or []:
        spoken = p.replace("_", " ").lower()
        out[spoken] = p
        out[spoken.removesuffix(" mode")] = p
    return out


def adjust_target(attrs: dict, delta: float) -> dict:
    """Service data for climate.set_temperature moving the set point(s) by delta."""
    lo, hi = attrs.get("min_temp"), attrs.get("max_temp")

    def clamp(v):
        v = round(v * 2) / 2
        if lo is not None:
            v = max(lo, v)
        if hi is not None:
            v = min(hi, v)
        return v

    if attrs.get("temperature") is not None:
        return {"temperature": clamp(attrs["temperature"] + delta)}
    if attrs.get("target_temp_low") is not None and attrs.get("target_temp_high") is not None:
        return {"target_temp_low": clamp(attrs["target_temp_low"] + delta),
                "target_temp_high": clamp(attrs["target_temp_high"] + delta)}
    return {}


def _deg(v) -> str:
    return f"{v:g}" if isinstance(v, (int, float)) else str(v)


def say_climate(name: str, state: str, attrs: dict, unit: str = "°") -> str:
    mode = state.replace("_", " ")
    if state == "off":
        return f"The {name} is off."
    action = attrs.get("hvac_action")
    if attrs.get("temperature") is not None:
        target = f"set to {_deg(attrs['temperature'])} degrees"
    elif attrs.get("target_temp_low") is not None:
        target = f"set between {_deg(attrs['target_temp_low'])} and {_deg(attrs['target_temp_high'])} degrees"
    else:
        target = "on"
    now = f" It's {_deg(attrs['current_temperature'])} degrees inside." if attrs.get("current_temperature") is not None else ""
    doing = {"heating": " It's heating right now.", "cooling": " It's cooling right now.",
             "idle": " It's idle right now.", "off": ""}.get(action or "", "")
    preset = f", {attrs['preset_mode'].replace('_', ' ')} preset" if attrs.get("preset_mode") not in (None, "none") else ""
    return f"The {name} is in {mode} mode{preset}, {target}.{doing}{now}"


def is_heating_answer(state: str, attrs: dict, what: str) -> str:
    action = attrs.get("hvac_action")
    if what == "heat":
        on = action == "heating" or (action is None and state in ("heat",))
        return "Yes, the heat is on." if on else (
            "The heat is set but not running right now." if state in ("heat", "heat_cool", "auto") else
            "No, the heat is off.")
    on = action == "cooling" or (action is None and state == "cool")
    return "Yes, the air conditioning is on." if on else (
        "The cooling is set but not running right now." if state in ("cool", "heat_cool", "auto") else
        "No, the air conditioning is off.")


# ------------------------------------------------------------------ TV
APP_PACKAGES = {
    "netflix": "com.netflix.ninja", "youtube": "com.google.android.youtube.tv",
    "youtube tv": "com.google.android.youtube.tvunplugged", "youtube music": "com.google.android.youtube.tvmusic",
    "disney plus": "com.disney.disneyplus", "disney": "com.disney.disneyplus",
    "prime video": "com.amazon.amazonvideo.livingroom", "amazon prime": "com.amazon.amazonvideo.livingroom",
    "amazon prime video": "com.amazon.amazonvideo.livingroom", "hulu": "com.hulu.livingroomplus",
    "max": "com.wbd.stream", "hbo max": "com.wbd.stream", "hbo": "com.wbd.stream", "plex": "com.plexapp.android",
    "spotify": "com.spotify.tv.android", "apple tv": "com.apple.atve.androidtv.appletv",
    "paramount plus": "com.cbs.ott", "peacock": "com.peacocktv.peacockandroid", "twitch": "tv.twitch.android.app",
    "jellyfin": "org.jellyfin.androidtv", "kodi": "org.xbmc.kodi", "pluto tv": "tv.pluto.android",
    "tubi": "com.tubitv", "crunchyroll": "com.crunchyroll.crunchyroid", "emby": "tv.emby.embyatv",
    "sling": "com.sling", "sling tv": "com.sling", "espn": "com.espn.score_center",
    "google play movies": "com.google.android.videos", "live channels": "com.google.android.tv",
}
GAME_WORDS = re.compile(r"playstation|ps\s?\d|xbox|nintendo|switch|console|game|steam", re.I)


def source_words(source_list: list[str]) -> dict[str, str]:
    """Spoken name -> source. 'HDMI 4' / 'hdmi4' / 'HDMI 2 - PlayStation 5' -> 'playstation 5',
    'playstation', and 'game' for the first console-looking input."""
    out: dict[str, str] = {}
    game = None
    for src in source_list or []:
        low = src.lower().strip()
        out.setdefault(low, src)
        for part in re.split(r"\s*[-–:|/]\s*|\s*\(\s*|\s*\)\s*", low):
            part = part.strip()
            if part:
                out.setdefault(part, src)
                bare = re.sub(r"\s*\d+$", "", part).strip()        # "playstation 5" -> "playstation"
                if bare and bare not in ("hdmi", "input", "av", "usb", "component", "composite", "dp", "displayport"):
                    out.setdefault(bare, src)
        m = re.search(r"hdmi\s*(\d)", low)
        if m:
            out.setdefault(f"hdmi {m.group(1)}", src)
            out.setdefault(f"hdmi{m.group(1)}", src)
            out.setdefault(f"input {m.group(1)}", src)
        if game is None and GAME_WORDS.search(low):
            game = src
    if game:
        for w in ("game", "games", "the game", "the console", "console", "gaming"):
            out.setdefault(w, game)
    return {k: v for k, v in out.items() if k and len(k) > 1}


def app_words(activity_list: list[str] | None) -> dict[str, str]:
    """Spoken app -> activity for remote.turn_on. The remote's own activity list wins when it has one."""
    if activity_list:
        out = {}
        for a in activity_list:
            out[a.lower()] = a
            short = a.split(".")[-1].lower() if "." in a and " " not in a else a.lower()
            out.setdefault(short, a)
        for name, pkg in APP_PACKAGES.items():
            if pkg in activity_list:
                out.setdefault(name, pkg)
        return out
    return dict(APP_PACKAGES)


# ------------------------------------------------------------------ beds
def round_to_step(value: float, step: float, lo: float, hi: float) -> float:
    step = step or 1
    v = round(round((value - lo) / step) * step + lo, 4)
    return max(lo, min(hi, v))


def side_of(name: str) -> str | None:
    n = name.lower()
    return "left" if re.search(r"\bleft\b", n) else "right" if re.search(r"\bright\b", n) else None


def sleeper_matches(entity_name: str, first_name: str) -> bool:
    return bool(first_name) and re.search(rf"\b{re.escape(first_name.lower())}\b", entity_name.lower()) is not None


# ------------------------------------------------------------------ health report
def battery_name(friendly: str) -> str:
    """'Kitchen sensor Battery level' -> 'kitchen sensor'."""
    n = re.sub(r"\b(battery|batteries|level|percentage|percent|charge|state)\b", " ", friendly.lower())
    return re.sub(r"\s+", " ", n).strip()


def find_battery(spoken: str, batteries: dict[str, str]) -> str | None:
    """Forgiving match: spoken words (minus 'the', 'battery', 'yet', 'now', 'level') against battery names.
    batteries: spoken name -> entity id."""
    s = re.sub(r"\b(the|my|our|battery|batteries|level|yet|now|currently|left|at|on|of|percentage|charge)\b", " ",
               spoken.lower())
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return None
    if s in batteries:
        return batteries[s]
    words = set(s.split())
    best, score = None, 0
    for name, eid in batteries.items():
        overlap = len(words & set(name.split()))
        if overlap > score:
            best, score = eid, overlap
    return best


def say_health(unavailable: dict[str, list[str]], device_names: dict[str, str], low: list[tuple[str, int]],
               vacuum_errors: list[str], updates: int) -> str:
    parts = []
    if unavailable:
        names = [device_names.get(k, k) for k in unavailable]
        parts.append(f"{len(names)} device{'s are' if len(names) != 1 else ' is'} offline: " + _join(names[:6]) +
                     (f", and {len(names) - 6} more" if len(names) > 6 else ""))
    if low:
        parts.append("Low batteries: " + _join([f"{n} at {p} percent" for n, p in low[:6]]))
    for v in vacuum_errors:
        parts.append(f"The {v} has an error")
    if updates:
        parts.append(f"{updates} update{'s are' if updates != 1 else ' is'} waiting")
    if not parts:
        return "Everything looks fine. All devices are online and no batteries are low."
    return ". ".join(parts) + "."


def say_batteries(levels: list[tuple[str, int]], threshold: int, only_low: bool) -> str:
    levels = sorted(levels, key=lambda x: x[1])
    if only_low:
        low = [x for x in levels if x[1] < threshold]
        if not low:
            return f"No batteries are below {threshold} percent."
        return "Low batteries: " + _join([f"{n} at {p} percent" for n, p in low]) + "."
    if not levels:
        return "I didn't find any battery sensors."
    return "Batteries: " + _join([f"{n} {p} percent" for n, p in levels[:12]]) + "."


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1] if items else ""


# ------------------------------------------------------------------ outside
def say_ago(seconds: float) -> str:
    s = int(seconds)
    if s < 90:
        return "just now"
    if s < 3600:
        return f"{round(s / 60)} minutes ago"
    if s < 86400:
        h = round(s / 3600)
        return f"{h} hour{'s' if h != 1 else ''} ago"
    d = round(s / 86400)
    return f"{d} day{'s' if d != 1 else ''} ago"


def say_outside(place: str, active: bool, last_seconds: float | None, what: str = "person") -> str:
    where = "outside" if place == "outside" else f"at the {place}"
    if active:
        return f"Yes, there's someone {where} right now." if what == "person" else f"Yes, there's motion {where} right now."
    if last_seconds is None:
        return f"No, nobody's {where}." if what == "person" else f"No motion {where}."
    if what == "person":
        return f"No one's {where} right now. The last person was seen {say_ago(last_seconds)}."
    return f"No motion {where} right now. The last motion was {say_ago(last_seconds)}."


# ------------------------------------------------------------------ night mode
def in_window(now: dt.time, start: dt.time, end: dt.time) -> bool:
    """True inside [start, end), handling windows that cross midnight (22:00-07:00)."""
    if start == end:
        return False
    if start < end:
        return start <= now < end
    return now >= start or now < end


# ------------------------------------------------------------------ help
HELP = {
    "search": "answer questions by looking them up on the web",
    "local": "do spelling, maths, unit conversions, holiday dates and world clocks",
    "reminders": "set reminders by time or when you get home or leave a place",
    "alarms": "set alarms on any voice speaker, with snooze",
    "timers": "set named timers",
    "notes": "take notes and remember where you put things",
    "messages": "leave messages for people in the house",
    "music": "play music on any Music Assistant speaker",
    "calendar": "read your calendar and add events",
    "rooms_lights": "turn whole rooms on and off, dim lights and run commands later",
    "thermostat": "change and check the thermostat",
    "cameras_outside": "tell you if anyone's outside and show cameras on a TV",
    "tv": "switch TV inputs and open apps",
    "bed": "set the bed and read sleep numbers",
    "health": "check for offline devices, low batteries and updates",
    "guest_mode": "turn guest mode on and off",
    "night_mode": "turn night mode on and off",
    "broadcast": "broadcast a message to every speaker",
}
HELP_TOPICS = {"music": "music", "songs": "music", "calendar": "calendar", "appointments": "calendar",
               "lights": "rooms_lights", "rooms": "rooms_lights", "the thermostat": "thermostat",
               "thermostat": "thermostat", "heating": "thermostat", "the heat": "thermostat",
               "cameras": "cameras_outside", "outside": "cameras_outside", "the tv": "tv", "tv": "tv",
               "the bed": "bed", "bed": "bed", "batteries": "health", "devices": "health",
               "guest mode": "guest_mode", "night mode": "night_mode", "broadcast": "broadcast",
               "broadcasts": "broadcast", "reminders": "reminders", "alarms": "alarms", "timers": "timers",
               "notes": "notes", "messages": "messages", "search": "search", "questions": "search"}


def say_help(enabled: list[str], topic: str | None = None) -> str:
    if topic:
        key = HELP_TOPICS.get(topic.lower(), topic.lower())
        if key not in enabled:
            return "That's turned off right now. You can switch it on in the integration's settings." \
                if key in HELP else "I'm not sure about that one."
        return f"I can {HELP[key]}. Try: {EXAMPLES[key]}."
    things = [HELP[k] for k in HELP if k in enabled]
    return "I can " + _join(things or ["answer questions"]) + ". Ask \"what can you do with music\" for more."


EXAMPLES = {
    "search": "\"how tall is Mount Everest\"", "local": "\"what's 15 percent of 80\" or \"what time is it in Tokyo\"",
    "reminders": "\"remind me to call the dentist tomorrow at 3\"", "alarms": "\"set an alarm for 7 in the bedroom\"",
    "timers": "\"set a pizza timer for 20 minutes\"", "notes": "\"remember I put the passports in the drawer\"",
    "messages": "\"leave a message for Sam that dinner is ready\"", "music": "\"play music by Queen in the kitchen\"",
    "calendar": "\"what's on my calendar tomorrow\" or \"add dentist to my calendar Friday at 3\"",
    "rooms_lights": "\"turn off the living room\", \"dim the kitchen\" or \"turn off the fan in 10 minutes\"",
    "thermostat": "\"make it 2 degrees warmer\" or \"is the heat on\"",
    "cameras_outside": "\"is anyone outside\" or \"show the driveway camera on the TV\"",
    "tv": "\"switch the TV to HDMI 2\" or \"open Netflix\"", "bed": "\"set the bed to flat\"",
    "health": "\"is anything wrong\" or \"which batteries are low\"", "guest_mode": "\"turn on guest mode\"",
    "night_mode": "\"turn on night mode\"", "broadcast": "\"tell everyone that dinner is ready\"",
}


# ------------------------------------------------------------------ guest mode exposure
def exposure_record(conversation_settings: dict, default: bool) -> dict:
    """What to put back later: an explicit Assist setting, or 'it was on the default'."""
    if "should_expose" in (conversation_settings or {}):
        return {"explicit": True, "value": bool(conversation_settings["should_expose"])}
    return {"explicit": False, "default": bool(default)}


def restore_action(record: dict) -> tuple[str, bool | None]:
    """('set', value) to write the old explicit setting back, or ('clear', default) to remove ours."""
    if record.get("explicit"):
        return "set", bool(record.get("value"))
    return "clear", bool(record.get("default", False))


def _hours_minutes(value: float, unit: str | None) -> str:
    unit = (unit or "min").lower()
    minutes = value * 60 if unit in ("h", "hr", "hrs", "hours") else value / 60 if unit in ("s", "sec") else value
    h, m = divmod(int(round(minutes)), 60)
    parts = [f"{h} hour{'s' if h != 1 else ''}"] if h else []
    if m or not parts:
        parts.append(f"{m} minute{'s' if m != 1 else ''}")
    return " and ".join(parts)


def say_sleep(name: str, duration=None, score=None, heart_rate=None, speaker_is_sleeper: bool = False) -> str:
    """duration/score/heart_rate: (state string, unit) or None."""
    who = "You" if speaker_is_sleeper else name
    parts = []
    if duration:
        try:
            parts.append(f"{who} slept {_hours_minutes(float(duration[0]), duration[1])}")
        except ValueError:
            pass
    if score:
        parts.append(("with a sleep score of " if parts else f"{who} had a sleep score of ") + f"{float(score[0]):g}")
    text = " ".join(parts) + "." if parts else f"I don't have last night's sleep for {name.lower() if who == 'You' else name}."
    if heart_rate:
        try:
            text += f" Average heart rate {float(heart_rate[0]):g}."
        except ValueError:
            pass
    return text
