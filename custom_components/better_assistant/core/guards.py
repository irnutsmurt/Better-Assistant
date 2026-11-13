"""Sentence guards and compound-command splitting. Pure Python, no Home Assistant imports."""
from __future__ import annotations

import re
from collections.abc import Iterable

MIN_WORDS = 4
# Sentences that start like a command are never searched, even when the device name was misheard.
COMMAND_START = re.compile(
    r"^(please )?(turn|switch|set|dim|brighten|open|close|lock|unlock|start|stop|pause|resume|play|skip|"
    r"shut|power|toggle|activate|raise|lower|increase|decrease|change|make|put|run|cancel|mute|unmute|volume)\b")
SHORT_OK = re.compile(r"^(spell|define|convert|how do you spell|what'?s \d|what is \d|\d)")
# Compound commands: "turn off the lamp and play the news" -> each part through Home Assistant's own agent.
SPLIT = re.compile(r"\s*(?:,\s*)?\b(?:and then|and also|and|then|after that)\b\s*", re.I)
VERB = re.compile(r"^((?:please )?(?:turn|switch) (?:on|off)|(?:please )?(?:open|close|lock|unlock|start|stop|pause|dim|brighten))\b", re.I)
# Only question-shaped sentences are searched; a misheard statement gets "didn't catch that".
QUESTION = re.compile(r"^(please |hey |so |um |uh |okay |ok )*(what|what's|whats|who|who's|whom|whose|when|when's|where|"
                      r"where's|why|how|how's|which|is|are|was|were|am|can|could|does|do|did|should|would|will|"
                      r"has|have|had|define|definition|meaning|spell|convert|look up|search|google|tell me|"
                      r"find out|give me|explain|i wonder|any idea)\b|\?\s*$", re.I)


# Questions about the state of the house never go to the web ("what lights are on the house right now"
# found the Empire State Building's lighting schedule).
HOUSE_STATE = re.compile(
    r"\b(lights?|lamps?|tv|television|doors?|locks?|garage|thermostat|fans?|blinds?|windows?)\b.*"
    r"\b(on|off|open|closed|locked|unlocked|playing|right now|left on)\b"
    r"|\b(on|playing|showing)\b.*\b(the|my|our) (tv|television|lights?|lamps?)\b"
    r"|\b(in|on|at) (the|my|our) (house|home)\b", re.I)


def about_the_house(text: str) -> bool:
    return bool(HOUSE_STATE.search(text))


def is_question(text: str) -> bool:
    return bool(QUESTION.search(text.strip()))


def looks_like_command(text: str, home_names: Iterable[str]) -> bool:
    """True for sentences that start like a command, are very short, or name a device or area."""
    t = " " + re.sub(r"[^a-z0-9' ]", " ", text.lower()) + " "
    if COMMAND_START.match(t.strip()):
        return True
    if len(t.split()) < MIN_WORDS and not SHORT_OK.match(t.strip()):
        return True
    return any(f" {n} " in t for n in home_names) or about_the_house(t)


def plan_compound(text: str, home_names: Iterable[str], max_parts: int = 4) -> list[str] | None:
    """'turn on the lamp and the porch light then play jazz' ->
    ['turn on the lamp', 'turn on the porch light', 'play jazz'], or None when it isn't a list.
    The verb is carried only onto a bare device name ("the ...", or a known device/area name)."""
    if not SPLIT.search(text):
        return None
    parts = [p.strip(" ,.") for p in SPLIT.split(text) if p and p.strip(" ,.")]
    if len(parts) < 2 or len(parts) > max_parts:
        return None
    names = [n.lower() for n in home_names]
    verb, plan = "", []
    for part in parts:
        m = VERB.match(part)
        if m:
            verb = m.group(1)
        elif verb and (re.match(r"^(the|my|our|all|both|that|those|these)\b", part, re.I)
                       or any(part.lower().startswith(n) for n in names)):
            part = f"{verb} {part}"
        plan.append(part)
    return plan
