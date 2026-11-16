"""Keyword understanding: the last step before "Sorry, I didn't catch that", for requests no sentence
pattern matches, as broken grammar often doesn't ("for tomorrow alarm delete", "battery is finish
which one"). Pure Python, no Home Assistant imports; the words live in sentences/keywords_<lang>.yaml so
another language needs only that file.

A rule names the concepts a request must contain ("alarm" + "remove" -> AlarmCancel), concepts that rule
it out, and where its slots come from. The best-scoring rule wins; a tie between two intents is no
answer (better "didn't catch that" than the wrong thing). Doors, locks and guest mode are never in the
rules: those need the request said properly."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .normalize import tidy
from .timeparse import words_to_digits

SENTENCES = Path(__file__).resolve().parent.parent / "sentences"
# list name -> the slot it fills ("@tv_source" fills "source")
LIST_SLOT = {"area": "area", "light_target": "light_target", "music_target": "music_target", "tv": "tv",
             "tv_source": "source", "tv_app": "app", "camera": "camera", "place": "place",
             "bed_preset": "preset", "climate_mode": "mode", "climate_preset": "preset",
             "battery_thing": "thing", "calendar": "calendar", "cal_range": "range", "person": "person"}
_NUMBER = re.compile(r"\b(\d{1,3})\b")
_TIME = re.compile(r"\b\d{1,2}(?:[:.]\d{2})?\s?(?:am|pm)?\b|\b(?:noon|midnight)\b", re.I)


@dataclass
class Rule:
    intent: str
    need: list[str]
    avoid: list[str] = field(default_factory=list)
    slots: dict[str, Any] = field(default_factory=dict)
    priority: int = 0


@dataclass
class Language:
    concepts: dict[str, re.Pattern]
    rules: list[Rule]
    skip: re.Pattern | None
    filler: re.Pattern | None


def _words(words: list[str]) -> re.Pattern:
    """Whole words or phrases, each also with a plural 's' ("alarm" finds "alarms")."""
    if any(not isinstance(w, str) for w in words):        # YAML reads a bare on / off / yes / no as true/false
        raise ValueError(f"quote these words in the keyword file: {[w for w in words if not isinstance(w, str)]}")
    alts = []
    for w in sorted(words, key=len, reverse=True):
        w = re.escape(w.lower()).replace(r"\ ", r"\s+")
        alts.append(w if not w[-1].isalpha() else w + "(?:s|es)?")
    return re.compile(r"(?<![\w'])(?:" + "|".join(alts) + r")(?![\w'])", re.I)


@lru_cache(maxsize=4)
def language(lang: str = "en") -> Language | None:
    path = SENTENCES / f"keywords_{lang}.yaml"
    if not path.exists():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    concepts = {name: _words(words) for name, words in (data.get("concepts") or {}).items()}
    rules = [Rule(intent=r["intent"], need=list(r.get("need") or []), avoid=list(r.get("avoid") or []),
                  slots=dict(r.get("slots") or {}), priority=int(r.get("priority") or 0))
             for r in data.get("rules") or []]
    skip = _words(data["skip"]) if data.get("skip") else None
    filler = _words(data["filler"]) if data.get("filler") else None
    return Language(concepts, rules, skip, filler)


def _find_list(text: str, values: Any) -> tuple[str, str] | None:
    """The longest list entry said in the text -> (spoken words, value)."""
    items = values.items() if isinstance(values, dict) else ((v, v) for v in values or [])
    best = None
    for spoken, value in items:
        if not spoken or spoken == "\u0000":
            continue
        if re.search(rf"(?<![\w']){re.escape(spoken.lower())}(?![\w'])", text) and (best is None or len(spoken) > len(best[0])):
            best = (spoken.lower(), value)
    return best


def understand(text: str, lists: dict[str, Any], intents: set[str] | None = None,
               lang: str = "en") -> tuple[str, dict[str, Any]] | None:
    """(intent, slots) for a request the sentence patterns missed, or None.
    lists: the run-time lists (area, tv_source, ...) plus the sentence files' fixed ones (cal_range).
    intents: the intents allowed (switched-off features left out)."""
    lng = language(lang)
    if lng is None:
        return None
    t = tidy(text).lower()
    if not t or (lng.skip and lng.skip.search(t)):
        return None                                      # "how do I set an alarm on my phone"
    digits = words_to_digits(t)
    found_lists = {name: hit for name, values in lists.items() if (hit := _find_list(t, values))}

    def has(need: str) -> bool:
        if need == "#number":
            return bool(_NUMBER.search(digits))
        if need == "#time":
            return bool(_TIME.search(digits))
        if need.startswith("@"):
            return need[1:] in found_lists
        if need.startswith("!"):                         # a concept that must be absent
            return not has(need[1:])
        pat = lng.concepts.get(need)
        return bool(pat and pat.search(t))

    scored: list[tuple[int, int, Rule]] = []
    for rule in lng.rules:
        if intents is not None and rule.intent not in intents:
            continue
        if not all(has(n) for n in rule.need) or any(has(a) for a in rule.avoid):
            continue
        score = sum(2 if n.startswith(("@", "#")) else 1 for n in rule.need if not n.startswith("!"))
        scored.append((score, rule.priority, rule))
    if not scored:
        return None
    scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
    best = scored[0]
    if any(s[2].intent != best[2].intent and (s[0], s[1]) == (best[0], best[1]) for s in scored[1:]):
        return None                                      # two different readings: don't guess
    rule = best[2]
    return rule.intent, _slots(rule, t, digits, found_lists, lng)


def _rest(t: str, rule: Rule, found_lists: dict, lng: Language) -> str:
    """The request without its keywords, list names and filler: what's left is the slot text
    ("alarm earlier half hour" -> "earlier half hour"; "where my passport i put" -> "passport")."""
    out = t
    for need in rule.need:
        pat = lng.concepts.get(need)
        if pat:
            out = pat.sub(" ", out)
    for spoken, _value in found_lists.values():
        out = re.sub(rf"(?<![\w']){re.escape(spoken)}(?![\w'])", " ", out)
    if lng.filler:
        out = lng.filler.sub(" ", out)
    return re.sub(r"\s+", " ", out).strip(" ,.?!")


def _slots(rule: Rule, t: str, digits: str, found_lists: dict, lng: Language) -> dict[str, Any]:
    slots: dict[str, Any] = {}
    for name, source in rule.slots.items():
        if not isinstance(source, str) or not source.startswith(("@", "#", "$")):
            slots[name] = source                         # a fixed value
        elif source == "#number":
            m = _NUMBER.search(digits)
            if m:
                slots[name] = int(m.group(1))
        elif source == "$text":
            slots[name] = t
        elif source == "$rest":
            slots[name] = _rest(t, rule, found_lists, lng)
        elif source.startswith("@") and source[1:] in found_lists:
            slots[name] = found_lists[source[1:]][1]
    for name, (_spoken, value) in found_lists.items():  # lists the rule needs fill their usual slot
        if f"@{name}" in rule.need and LIST_SLOT.get(name) and LIST_SLOT[name] not in slots:
            slots[LIST_SLOT[name]] = value
    return slots
