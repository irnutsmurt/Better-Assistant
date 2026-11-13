"""Voice passphrase: matching, the lockout after wrong tries, the one-shot "…, passphrase <words>"
form, and replies that never contain the passphrase. Pure Python, no Home Assistant imports."""
from __future__ import annotations

import hmac
import re
from dataclasses import dataclass

RESET_AFTER = 6 * 3600                 # misses are forgotten after 6 hours without another miss
ONESHOT = re.compile(r"^(?P<command>.+?)[\s,;:.-]+(?:pass\s?phrase|password|pass\s?word|code word)"
                     r"(?:\s+is)?[\s,:;-]+(?P<phrase>.+?)\W*$", re.I)


def normalize(text: str) -> str:
    """Case, spaces and punctuation don't matter: 'Purple Monkey, dishwasher!' == 'purplemonkeydishwasher'."""
    return re.sub(r"[^0-9a-z]", "", (text or "").lower())


def matches(spoken: str, secret: str) -> bool:
    """Constant-time comparison of the normalized forms. An empty secret never matches."""
    a, b = normalize(spoken), normalize(secret)
    if not b:
        return False
    return hmac.compare_digest(a.encode(), b.encode())


def split_oneshot(text: str) -> tuple[str, str | None]:
    """'open the garage door, passphrase purple monkey' -> ('open the garage door', 'purple monkey')."""
    m = ONESHOT.match((text or "").strip())
    if not m:
        return text, None
    return m.group("command").strip(" ,"), m.group("phrase").strip()


def lockout_seconds(misses: int) -> int:
    """3rd miss: 30 s, 4th: 1 min, 5th: 2 min, then one more minute for each further miss."""
    if misses < 3:
        return 0
    if misses == 3:
        return 30
    if misses == 4:
        return 60
    return 120 + 60 * (misses - 5)


@dataclass
class Attempts:
    """Wrong tries, shared by every passphrase check. Times are plain seconds (e.g. time.time())."""
    misses: int = 0
    last_miss: float = 0.0
    locked_until: float = 0.0

    def _expire(self, now: float) -> None:
        if self.misses and now - self.last_miss >= RESET_AFTER:
            self.misses, self.locked_until = 0, 0.0

    def locked_for(self, now: float) -> int:
        """Seconds left before voice unlocking is allowed again (0 = allowed)."""
        self._expire(now)
        return max(0, int(round(self.locked_until - now)))

    def failed(self, now: float) -> int:
        """Record a wrong passphrase; returns the new lockout in seconds."""
        self._expire(now)
        self.misses += 1
        self.last_miss = now
        lock = lockout_seconds(self.misses)
        self.locked_until = now + lock if lock else 0.0
        return lock

    def succeeded(self) -> None:
        self.misses, self.last_miss, self.locked_until = 0, 0.0, 0.0

    def to_dict(self) -> dict:
        return {"misses": self.misses, "last_miss": self.last_miss, "locked_until": self.locked_until}

    @classmethod
    def from_dict(cls, data: dict | None) -> "Attempts":
        data = data or {}
        return cls(int(data.get("misses", 0)), float(data.get("last_miss", 0.0)), float(data.get("locked_until", 0.0)))


# ------------------------------------------------------------------ replies (never include the passphrase)
def say_wait(seconds: int) -> str:
    if seconds >= 60:
        m = round(seconds / 60)
        return f"Too many wrong tries. Voice unlocking is paused for {m} minute{'s' if m != 1 else ''}."
    return f"Too many wrong tries. Voice unlocking is paused for {seconds} seconds."


def say_wrong(what_stays: str, lock: int) -> str:
    base = f"That's not the passphrase, so {what_stays}."
    return base + (" " + say_wait(lock) if lock else "")


def say_not_heard(what_stays: str) -> str:
    return f"I didn't catch the passphrase, so {what_stays}."


def say_oneshot_help(command: str) -> str:
    return f"That needs the passphrase. Say: {command}, passphrase, then the words."
