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
def load(language: str = "en") -> Intents:
    """Parsed sentence templates (blocking file read: call once from an executor)."""
    return Intents.from_dict(_load_files(language))


def recognize(text: str, people: list[str] | tuple[str, ...] = (), language: str = "en") -> Match | None:
    t = re.sub(r"\s+", " ", text.strip().strip(".!?")).strip()
    if not t:
        return None
    slot_lists = {"person": TextSlotList.from_strings(list(people))} if people else {
        "person": TextSlotList.from_strings(["\u0000"])}
    result = recognize_best(t, load(language), slot_lists=slot_lists)
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
