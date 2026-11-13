"""Matches the agent's own sentences (sentences/*.yaml) with hassil. No Home Assistant imports;
hassil and PyYAML ship with Home Assistant's conversation integration."""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from hassil import Intents, TextSlotList, recognize_best

SENTENCES = Path(__file__).resolve().parent.parent / "sentences"
TIMER_INTENTS = {"HassStartTimer", "HassIncreaseTimer", "HassDecreaseTimer"}

# Which settings-page feature switch each intent belongs to (by name prefix).
INTENT_FEATURE = {"Music": "music", "Calendar": "calendar", "Room": "rooms_lights", "Delayed": "rooms_lights",
                  "Light": "rooms_lights", "Climate": "thermostat", "Outside": "cameras_outside",
                  "Camera": "cameras_outside", "Tv": "tv", "Bed": "bed", "Health": "health",
                  "Battery": "health", "Guest": "guest_mode", "Night": "night_mode", "Broadcast": "broadcast"}

# Lists filled at run time from the house (names of areas, speakers, apps, ...). Every one is always
# passed (a placeholder when empty) so hassil never sees a missing list.
DYNAMIC_LISTS = ("person", "area", "music_target", "calendar", "light_target", "place", "camera", "tv",
                 "tv_source", "tv_app", "bed_preset", "climate_mode", "climate_preset", "battery_thing",
                 "help_topic")
_EMPTY = "\u0000"


def feature_of(intent: str) -> str | None:
    return next((f for prefix, f in INTENT_FEATURE.items() if intent.startswith(prefix)), None)


@dataclass
class Match:
    intent: str
    slots: dict[str, Any]


def _load_files(language: str) -> dict[str, Any]:
    merged: dict[str, Any] = {"language": language, "intents": {}, "lists": {}}
    for path in sorted(SENTENCES.glob(f"*{language}.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        merged["intents"].update(data.get("intents") or {})
        merged["lists"].update(data.get("lists") or {})
    return merged


@lru_cache(maxsize=4)
def _raw(language: str) -> dict[str, Any]:
    return _load_files(language)


@lru_cache(maxsize=16)
def load(language: str = "en", disabled: frozenset[str] = frozenset()) -> Intents:
    """Parsed sentence templates without the intents of switched-off features (blocking file read
    on first use: call once from an executor)."""
    raw = _raw(language)
    intents = {k: v for k, v in raw["intents"].items() if feature_of(k) not in disabled}
    return Intents.from_dict({**raw, "intents": intents})


def recognize(text: str, people: list[str] | tuple[str, ...] = (), language: str = "en",
              lists: dict[str, list[str] | dict[str, str]] | None = None,
              disabled: set[str] | frozenset[str] = frozenset()) -> Match | None:
    """lists: name -> spoken values, or {spoken: value}."""
    t = re.sub(r"\s+", " ", text.strip().strip(".!?")).strip()
    if not t:
        return None
    given = dict(lists or {})
    if people:
        given["person"] = list(people)
    slot_lists = {}
    for name in DYNAMIC_LISTS:
        values = given.get(name) or [_EMPTY]
        if isinstance(values, dict):
            slot_lists[name] = TextSlotList.from_tuples([(k, v) for k, v in values.items()] or [(_EMPTY, _EMPTY)])
        else:
            slot_lists[name] = TextSlotList.from_strings([v for v in values if v] or [_EMPTY])
    result = recognize_best(t, load(language, frozenset(disabled)), slot_lists=slot_lists)
    if result is None:
        return None
    slots = {k: v.value for k, v in result.entities.items()}
    for k, v in list(slots.items()):
        if isinstance(v, str):
            slots[k] = v.strip(" ,.")
        elif isinstance(v, float) and v.is_integer():
            slots[k] = int(v)
    if result.intent.name == "MessageLeave" and "person" not in slots:
        m = re.match(r"^for (\S+(?: \S+)?) (?:that|saying) (.+)$", slots.get("text", ""), re.I)
        if m:                                             # "leave a message for <someone unknown> that ..."
            return Match("UnknownPerson", {"name": m.group(1), "text": m.group(2)})
    return Match(result.intent.name, slots)
