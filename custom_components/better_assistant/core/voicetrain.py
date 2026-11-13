"""Pure helpers for voice training (experimental): the phrases, the training conversation, the
"pending capture" slot that ties a training prompt to the next recording, WAV files and where clips
are saved. No Home Assistant imports: callers pass plain values (and the time).

Nothing here recognises voices yet. It only collects labelled recordings for a later test.

How a recording is matched to a training prompt: Home Assistant runs speech-to-text before the
conversation agent and doesn't tell the speech-to-text engine which speaker the audio came from. So
when the agent asks for a phrase it "arms" one slot, and the next audio stream (within ~30 seconds)
takes it. That assumes one training session at a time in the house; a second speaker talking in
those seconds would be saved under the wrong label."""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from datetime import datetime

PHRASES = [
    "What's the weather like today",
    "Turn on the living room lamps",
    "Set a timer for ten minutes",
    "What's on my calendar tomorrow",
    "Remind me to take out the trash at seven",
    "How did I sleep last night",
    "What time is it in Tokyo",
    "Add milk to the shopping list",
]

SLOT_SECONDS = 30.0          # a training prompt waits this long for its recording
SESSION_SECONDS = 180.0      # a training conversation left alone this long is forgotten
MAX_CLIP_SECONDS = 30.0      # never keep more audio than this from one stream
TRAIN, TEST = "train", "test"

TYPED_ONLY = "Voice training only works from a voice speaker."
TURNED_OFF = ("Voice training is turned off. Turn it on in the Better Assistant settings, under "
              "Voice training.")


def _clean(text: str) -> str:
    text = (text or "").lower().replace("’", "'")
    text = re.sub(r"[^a-z0-9' ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# ------------------------------------------------------------------ what was said
_SELF = re.compile(r"^(?:please )?(?:(?:start )?voice training|(?:train|learn) my voice)(?: please)?$")
_OTHER = re.compile(r"^(?:please )?(?:train|learn) (.+?)(?:'s| s|s')? voice(?: please)?$")
_STOP = re.compile(r"^(?:please )?(?:stop|cancel|end|quit|exit)(?: (?:the )?(?:voice )?training)?(?: please)?$")


def parse_start(text: str) -> tuple[bool, str | None] | None:
    """None when it isn't a request to train; (True, None) for "train my voice"; (True, "rob") for
    "train Rob's voice"."""
    t = _clean(text)
    if _SELF.match(t):
        return True, None
    m = _OTHER.match(t)
    if m and m.group(1) not in ("my", "me", "the"):
        return True, m.group(1).strip()
    return None


def is_stop(text: str) -> bool:
    return bool(_STOP.match(_clean(text)))


def is_stop_training(text: str) -> bool:
    """"stop voice training" (not a bare "stop"): answered even when no training is running."""
    t = _clean(text)
    return bool(_STOP.match(t)) and "training" in t


def too_short(text: str) -> bool:
    """Nothing usable heard: empty, or a single short word."""
    words = _clean(text).replace("'", "").split()
    return len(words) < 2 and len("".join(words)) < 4


# ------------------------------------------------------------------ the training conversation
NOTHING_HEARD = "(nothing heard)"   # what speech-to-text passes on mid-training instead of no text
MAX_REASKS = 2               # asked again this many times, then the phrase is skipped
_NUM = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
        "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12"}


def prompt(index: int) -> str:
    """The first phrase is introduced; after that only the phrase itself is said."""
    return f"Please say: {PHRASES[index]}." if index == 0 else f"{PHRASES[index]}."


def _words(text: str) -> list[str]:
    text = re.sub(r"(\d+):00\b", r"\1", (text or "").lower())        # "7:00" -> "7"
    return [_NUM.get(w, w) for w in _clean(text).replace("'", "").split()]


def is_echo(last_said: str, heard: str) -> bool:
    """Heard only words from what we just said, and not the whole phrase: the speaker started
    listening before it finished talking and caught the end of its own reply."""
    got = _words(heard)
    return bool(got) and set(got) <= set(_words(last_said))


def matches_phrase(phrase: str, heard: str) -> bool:
    """Heard is the phrase: most of its words, without a lot of other talk (the TV, someone else)."""
    want, got = _words(phrase), _words(heard)
    if not want or not got:
        return False
    found = sum(1 for w in set(want) if w in got) / len(set(want))
    return found >= 0.66 and len(got) <= len(want) * 1.5 + 2


@dataclass
class Session:
    """One person's training run, kept per conversation."""
    person: str                 # person entity id
    name: str                   # first name, for speech
    index: int = 0              # which phrase we are waiting for
    reasks: int = 0             # times the current phrase was asked again
    saved: int = 0              # recordings the speech-to-text side actually wrote
    token: str = ""             # ties recordings to this session
    last_said: str = ""         # the last reply, to spot the speaker hearing itself
    until: float = 0.0          # forgotten after this (time.time())
    phone: str | None = None    # notify service showing the phrases; the speaker stays silent
    satellite: str | None = None
    device_id: str | None = None
    silent: bool = False        # the speaker says nothing (phrases on a phone or the dashboard)
    results: list[str] = field(default_factory=list)   # per phrase: "said" / "skipped" (in order)
    hint: str = ""              # the last "try again" message, for the screen
    borrowed: tuple[str, str | None, bool] | None = None   # (pipeline id, its speech-to-text, prefer local
                                                            # intents) to put back after training


def intro(name: str) -> str:
    return (f"Okay, let's train {name}'s voice. I'll ask for {len(PHRASES)} short phrases; say stop "
            f"voice training at any time. {prompt(0)}")


PHONE_TAG = "better_assistant_voice_training"   # one notification, replaced phrase by phrase
PHONE_TITLE = "Voice training"
PHONE_START = "Check your phone."
SPOKEN_INTRO = ("We're going to have you repeat some phrases on the screen. When you hear the ding, start "
                "saying the highlighted phrase.")
ACTION_STOP = "BETTER_ASSISTANT_VT_STOP"      # notification buttons
ACTION_SKIP = "BETTER_ASSISTANT_VT_SKIP"
PENDING_SECONDS = 60.0                        # a start from the phone waits this long for the speaker


def skip(session: Session) -> Step:
    """The Skip button on the phone: on to the next phrase."""
    session.results.append("skipped")
    session.hint = ""
    session.index += 1
    session.reasks = 0
    if session.index >= len(PHRASES):
        return Step(finish_text(session), True, False)
    return Step(prompt(session.index), False, True)


def view(session: Session | None, status: str) -> dict:
    """What the Voice training sensor shows: status plus every phrase as said / skipped / current /
    waiting."""
    phrases = []
    for i, text in enumerate(PHRASES):
        if session and i < len(session.results):
            state = session.results[i]
        elif session and status == "training" and i == session.index:
            state = "current"
        else:
            state = "waiting"
        phrases.append({"text": text, "state": state})
    return {"status": status, "person": session.person if session else None,
            "name": session.name if session else None, "current": session.index + 1 if session else 0,
            "total": len(PHRASES), "saved": session.saved if session else 0,
            "hint": session.hint if session else "", "phrases": phrases}


def stop(session: Session) -> Step:
    return step(session, "stop")
NO_PHONE = "I couldn't find your phone, so I'll read the phrases out. "


def phone_text(session: Session, reply: str) -> str:
    """What the phone shows for a reply: the phrase to say, with progress."""
    if session.index >= len(PHRASES):
        return reply
    lead = reply.removesuffix(f"{PHRASES[session.index]}.").removesuffix("Please say: ").strip()
    head = f"{session.index + 1} of {len(PHRASES)}. Say to the speaker:"
    tail = "(Say \"stop voice training\" to stop.)"
    return "\n".join(x for x in (lead, head, f"\u201c{PHRASES[session.index]}\u201d", tail) if x)


def finish_text(session: Session) -> str:
    if session.saved == 0:
        return ("Done, but I couldn't save any recordings. Set your voice assistant's speech-to-text to "
                "Better Assistant speech-to-text in the Better Assistant settings, under Voice training.")
    plural = "sample" if session.saved == 1 else "samples"
    return f"Done. I saved {session.saved} {plural} of {session.name}'s voice."


@dataclass
class Step:
    reply: str
    done: bool          # the session is over
    arm: bool           # wait for another recording (of PHRASES[session.index])


def step(session: Session, heard: str) -> Step:
    """The user's turn while training: it is the repeat of the current phrase, never a command."""
    if is_stop(heard):
        if session.saved:
            return Step(f"Okay, I stopped voice training. I kept {session.saved} "
                        f"{'sample' if session.saved == 1 else 'samples'}.", True, False)
        return Step("Okay, I stopped voice training.", True, False)
    if not matches_phrase(PHRASES[session.index], heard):
        if session.reasks < MAX_REASKS:
            session.reasks += 1
            if is_echo(session.last_said, heard):
                return Step("Go ahead.", False, True)          # short, so there's little to hear again
            lead = "I didn't catch that." if too_short(heard) or heard == NOTHING_HEARD \
                else "That didn't sound like the phrase."
            session.hint = f"{lead} Try again."
            return Step(f"{lead} Try again: {PHRASES[session.index]}.", False, True)
        lead = "Let's skip that one."
        session.results.append("skipped")
    else:
        lead = ""
        session.results.append("said")
    session.index += 1
    session.reasks = 0
    session.hint = ""
    if session.index >= len(PHRASES):
        return Step(finish_text(session), True, False)
    return Step(f"{lead} {prompt(session.index)}".strip(), False, True)


# ------------------------------------------------------------------ the pending capture slot
@dataclass
class CaptureSlot:
    person: str                 # person entity id or "unknown"
    label: str                  # TRAIN or TEST
    phrase: str | None = None
    token: str = ""
    satellite: str | None = None
    device_id: str | None = None
    silent: bool = False        # the speaker says nothing (phrases on a phone or the dashboard)
    results: list[str] = field(default_factory=list)   # per phrase: "said" / "skipped" (in order)
    hint: str = ""              # the last "try again" message, for the screen
    borrowed: tuple[str, str | None, bool] | None = None   # (pipeline id, its speech-to-text, prefer local
                                                            # intents) to put back after training
    until: float = 0.0


@dataclass
class CaptureHub:
    """The one armed slot plus how many clips each training session got saved."""
    slot: CaptureSlot | None = None
    saved: dict[str, int] = field(default_factory=dict)
    engine: str | None = None   # while training borrows a pipeline: the speech-to-text it normally uses

    def arm(self, slot: CaptureSlot, now: float, seconds: float = SLOT_SECONDS) -> None:
        slot.until = now + seconds
        self.slot = slot

    def take(self, now: float) -> CaptureSlot | None:
        """The armed slot, if still fresh; the slot is used up either way."""
        slot, self.slot = self.slot, None
        return slot if slot and slot.until >= now else None

    def disarm(self, token: str | None = None) -> None:
        if self.slot and (token is None or self.slot.token == token):
            self.slot = None

    def note_saved(self, token: str) -> None:
        if token:
            self.saved[token] = self.saved.get(token, 0) + 1

    def saved_for(self, token: str) -> int:
        return self.saved.get(token, 0)


# ------------------------------------------------------------------ files
def wav_header(data_len: int, sample_rate: int, channels: int = 1, bits: int = 16) -> bytes:
    """The 44-byte RIFF/WAVE header for raw PCM."""
    block = channels * bits // 8
    return struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + data_len, b"WAVE", b"fmt ", 16, 1, channels,
                       sample_rate, sample_rate * block, block, bits, b"data", data_len)


def wav_bytes(pcm: bytes, sample_rate: int, channels: int = 1, bits: int = 16) -> bytes:
    block = channels * bits // 8
    pcm = pcm[: len(pcm) - len(pcm) % block]               # whole samples only
    return wav_header(len(pcm), sample_rate, channels, bits) + pcm


def duration(pcm_len: int, sample_rate: int, channels: int = 1, bits: int = 16) -> float:
    rate = sample_rate * channels * bits // 8
    return round(pcm_len / rate, 3) if rate else 0.0


def max_bytes(sample_rate: int, channels: int = 1, bits: int = 16) -> int:
    return int(MAX_CLIP_SECONDS * sample_rate * channels * bits // 8)


def person_slug(person: str | None) -> str:
    """"person.rob_smith" -> "rob_smith"; anything unknown -> "unknown"."""
    if not person or person == "unknown":
        return "unknown"
    slug = re.sub(r"[^a-z0-9_]+", "_", person.split(".", 1)[-1].lower()).strip("_")
    return slug or "unknown"


def clip_name(when: datetime, n: int) -> str:
    """UTC time stamp plus a counter: 20261113T071502Z_3."""
    return f"{when.strftime('%Y%m%dT%H%M%SZ')}_{n}"


def count_text(counts: dict[tuple[str, str], int]) -> str:
    """{(label, person slug): clips} -> "rob: 8 training, 3 test; unknown: 1 test"."""
    if not counts:
        return "none yet"
    people = sorted({p for _l, p in counts})
    parts = []
    for p in people:
        bits = [f"{counts[(label, p)]} {'training' if label == TRAIN else 'test'}"
                for label in (TRAIN, TEST) if counts.get((label, p))]
        parts.append(f"{p}: {', '.join(bits)}")
    return "; ".join(parts)


def pick_underlying(engines: list[tuple[str, str]], own_domain: str) -> str | None:
    """Default engine to wrap from [(entity id, platform)]: never our own; Home Assistant Cloud
    first, then Wyoming, then whatever is first."""
    others = [(e, p) for e, p in engines if p != own_domain]
    for e, _p in others:
        if e == "stt.home_assistant_cloud":
            return e
    for e, p in others:
        if p == "wyoming":
            return e
    return others[0][0] if others else None


def pipeline_plan(chosen: list[str], originals: dict[str, str | None], current: dict[str, str | None],
                  ours: str, enabled: bool, fallback: str | None = None) -> tuple[dict[str, str | None], dict[str, str | None]]:
    """Which pipelines to switch. `chosen`: pipeline ids ticked; `originals`: pipelines we switched
    before -> their engine then; `current`: pipeline id -> its engine now.
    Returns ({pipeline id: new stt engine}, new originals). Feature off = put every one back.
    A pipeline that already used ours (switched by hand) goes back to `fallback` when unticked."""
    wanted = set(chosen) if enabled else set()
    changes: dict[str, str | None] = {}
    kept: dict[str, str | None] = {}
    originals = {**{p: fallback for p, e in current.items() if e == ours}, **originals}
    for pid, original in originals.items():
        if pid not in current:
            continue                                        # pipeline deleted: forget it
        if pid in wanted:
            kept[pid] = original
        elif current[pid] == ours:
            changes[pid] = original                         # unticked: switch back
    for pid in wanted:
        if pid in kept or pid not in current:
            continue
        kept[pid] = current[pid]
        changes[pid] = ours
    return changes, kept
