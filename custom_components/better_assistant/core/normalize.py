"""How people really talk, turned into what the sentence patterns expect. Pure Python, no Home Assistant
imports. Used when a request doesn't match as said:

    "hey um could you cancel my alarm please"  -> "cancel my alarm"
    "open the light in kitchen"                -> "turn on the light in kitchen"
    "music more loud"                          -> "music louder"

Only changes that can't turn one request into a different one belong here; wordings that need more
than a word swap go in the sentence files."""
from __future__ import annotations

import re

# Politeness and fillers at the start or end ("hey", "um", "could you please", "for me", "thanks").
_LEAD = re.compile(
    r"^(?:(?:hey|hi|hello|ok|okay|alright|all right|so|um+|uh+|erm|er|hmm+|well|yo|oh|please|just|actually|"
    r"go ahead and|(?:can|could|would|will) you(?: please)?(?: just)?|would you mind|(?:can|could|may) i ask you to|"
    r"i want you to|i need you to|i'd like you to|i would like you to|i want to|i'd like to|"
    r"do me a favou?r and|quick question)\b[ ,]*)+", re.I)
_TAIL = re.compile(
    r"(?:[ ,]+(?:please|pls|for me|thanks|thank you|thx|real quick|quickly|ok|okay|now|right now|"
    r"if you can|if you could|if possible|would you|could you|can you)\b)+$", re.I)

_LIGHTS = r"(?=.*\b(?:lights?|lamps?|bulbs?)\b)"
# (pattern, replacement): literal translations and casual forms with only one meaning here.
_REWRITES = [
    (re.compile(rf"^(?:open|put on|light up|switch on|on)\b{_LIGHTS}", re.I), "turn on"),     # "open the light"
    (re.compile(rf"^(?:close|shut|put off|switch off|off)\b{_LIGHTS}", re.I), "turn off"),    # "close the light"
    (re.compile(r"\bturn (?:the )?(lights?|lamps?) (on|off)\b", re.I), r"turn \2 the \1"),
    (re.compile(r"\b(?:more loud(?:er)?|loud more|more high|higher volume)\b", re.I), "louder"),
    (re.compile(r"\b(?:less loud|more quiet|more low|lower volume|more soft|softer)\b", re.I), "quieter"),
    (re.compile(r"\bwhich time\b", re.I), "what time"),
    (re.compile(r"\b(?:telephone|mobile phone|mobile|cell ?phone|smartphone)\b", re.I), "phone"),
    (re.compile(r"\b(?:air condition(?:er|ing)?|aircon|a\.c\.|a c)\b", re.I), "ac"),
    (re.compile(r"\bheating\b", re.I), "heat"),
    (re.compile(r"\bwanna\b", re.I), "want to"),
    (re.compile(r"\bgonna\b", re.I), "going to"),
]


def tidy(text: str) -> str:
    """The request without fillers and with common casual / non-native forms evened out."""
    t = re.sub(r"\s+", " ", text.strip()).strip(" .!?,")
    for _ in range(3):                                   # "okay um could you please ..."
        before = t
        t = _LEAD.sub("", t).strip(" ,")
        t = _TAIL.sub("", t).strip(" ,.!?")
        if t == before:
            break
    for pattern, repl in _REWRITES:
        t = pattern.sub(repl, t)
    return re.sub(r"\s+", " ", t).strip()


# --------------------------------------------------------------- the patterns themselves
_DET = r"(?:the|a|an|my|your|our)"
_DET_GROUP = re.compile(rf"\(\s*{_DET}(?:\s*\|\s*{_DET})*\s*\)")


def soften(template: str) -> str:
    """Make little words optional in a sentence pattern, so "remove alarm" matches "remove (the|my) alarm":
    a required group of only determiners becomes optional, and so does a lone 'the' / 'my' outside any
    brackets, unless a {slot} follows it."""
    # kept when a free-text slot follows: "set a {name} timer" must not read "a" as part of the name
    t = _DET_GROUP.sub(lambda m: m.group(0) if template[m.end():].startswith(" {")
                       else "[" + m.group(0)[1:-1] + "]", template)
    out, depth, i = [], 0, 0
    while i < len(t):
        ch = t[i]
        if ch in "([{<":
            depth += 1
        elif ch in ")]}>":
            depth -= 1
        if depth == 0 and (i == 0 or t[i - 1] == " "):
            m = re.match(rf"{_DET}(?= )", t[i:])
            if m and not t[i + len(m.group(0)):].startswith(" {"):
                out.append(f"[{m.group(0)}]")
                i += len(m.group(0))
                continue
        out.append(ch)
        i += 1
    return "".join(out)
