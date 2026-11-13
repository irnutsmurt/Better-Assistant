"""Small answers that need no search: coin flip, dice, pick a number, "what did you hear",
and spotting "what time is it in <place>". Pure Python, no Home Assistant imports."""
from __future__ import annotations

import random
import re

from .router import num

DIE_WORDS = r"(?:an? |one |two |three |four |five |six |\d+ )?(?:(?:\d+|six|eight|ten|twelve|twenty)[- ]sided )?(?:dice|die|d\d+)"
COIN = re.compile(r"^(?:can you |could you |please |will you )?(?:flip|toss) (?:a |the )?coin\b|^heads or tails\b", re.I)
DICE = re.compile(rf"^(?:can you |could you |please |will you )?(?:roll|throw) ({DIE_WORDS})\b", re.I)
PICK = re.compile(r"^(?:can you |could you |please )?(?:pick|choose|give me|think of) a (?:random )?number"
                  r"(?: (?:between|from) (\S+) (?:and|to) (\S+))?\W*$", re.I)
HEARD = re.compile(r"^(?:hey |so |um |okay |ok )?(?:what did (?:you (?:just )?hear|i (?:just )?say)|"
                   r"what was (?:that|the last thing i said)|what did you think i said)\b", re.I)
TIME_IN = re.compile(r"^(?:what(?:'s| is) the time|what time is it|what(?:'s| is) the local time) (?:right now |now )?in (.+?)\W*$", re.I)

_DIE_COUNT = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}


def is_what_did_you_hear(q: str) -> bool:
    return bool(HEARD.search(q.strip()))


def time_in_place(q: str) -> str | None:
    """'what time is it in tokyo' -> 'tokyo' (None when the sentence isn't that question)."""
    m = TIME_IN.match(q.strip())
    return m.group(1) if m else None


def fun_answer(q: str, rng: random.Random | None = None) -> str | None:
    rng = rng or random.Random()
    q = q.strip().strip("?.! ").lower()
    if COIN.search(q):
        return f"It's {rng.choice(['heads', 'tails'])}."
    m = DICE.search(q)
    if m:
        spec = m.group(1).split()
        count = _DIE_COUNT.get(spec[0], int(spec[0]) if spec[0].isdigit() else 1) if spec else 1
        count = max(1, min(count, 6))
        sides = 6
        s = re.search(r"(\d+|eight|ten|twelve|twenty)[- ]sided|d(\d+)", m.group(1))
        if s:
            sides = int(s.group(2) or num(s.group(1)) or 6)
        sides = max(2, min(sides, 100))
        rolls = [rng.randint(1, sides) for _ in range(count)]
        if count == 1:
            return f"You rolled a {rolls[0]}."
        return f"You rolled {', '.join(map(str, rolls[:-1]))} and {rolls[-1]}, for a total of {sum(rolls)}."
    m = PICK.search(q)
    if m:
        lo, hi = 1, 10
        if m.group(1):
            a, b = num(m.group(1)), num(m.group(2))
            if a is None or b is None:
                return None
            lo, hi = sorted((int(a), int(b)))
        return f"I pick {rng.randint(lo, hi)}."
    return None
