"""Voice training (experimental): the training conversation on a voice speaker, saving recordings to
/config/better_assistant/voice, counting and deleting them, and pointing pipelines at the
pass-through speech-to-text entity. Nothing recognises voices yet; this only collects labelled clips
for a later voice-match test. Off by default: nothing is recorded until it is turned on.

Recordings never leave the machine: they are plain files under the config folder."""
from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .const import DOMAIN, OPT_VT_ENABLED, OPT_VT_ORIGINALS, OPT_VT_RECORD_TEST, OPT_VT_STT
from .core.voicetrain import (
    PHRASES,
    SESSION_SECONDS,
    TEST,
    TRAIN,
    TURNED_OFF,
    TYPED_ONLY,
    CaptureHub,
    CaptureSlot,
    Session,
    clip_name,
    duration,
    intro,
    is_stop_training,
    parse_start,
    person_slug,
    pick_underlying,
    pipeline_plan,
    step,
    wav_bytes,
)

_LOGGER = logging.getLogger(__name__)
VOICE_DIR = ("better_assistant", "voice")


def voice_root(hass: HomeAssistant) -> Path:
    return Path(hass.config.path(*VOICE_DIR))


# ------------------------------------------------------------------ files (run in the executor)
def write_clip(root: Path, label: str, person: str, pcm: bytes, sample_rate: int, info: dict[str, Any]) -> Path:
    """<root>/<label>/<person slug>/<UTC stamp>_<n>.wav plus a .json sidecar."""
    folder = root / label / person_slug(person)
    folder.mkdir(parents=True, exist_ok=True)
    n = len(list(folder.glob("*.wav"))) + 1
    base = folder / clip_name(dt_util.utcnow(), n)
    base.with_suffix(".wav").write_bytes(wav_bytes(pcm, sample_rate))
    meta = {**info, "person": person, "label": label, "duration_s": duration(len(pcm), sample_rate),
            "sample_rate": sample_rate}
    base.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return base.with_suffix(".wav")


def count_clips(root: Path) -> dict[tuple[str, str], int]:
    out: dict[tuple[str, str], int] = {}
    for label in (TRAIN, TEST):
        base = root / label
        if not base.is_dir():
            continue
        for person in base.iterdir():
            if person.is_dir() and (n := len(list(person.glob("*.wav")))):
                out[(label, person.name)] = n
    return out


def delete_clips(root: Path) -> None:
    if root.exists():
        shutil.rmtree(root)


# ------------------------------------------------------------------ helpers shared with stt.py
def hub(hass: HomeAssistant) -> CaptureHub:
    """One capture hub per Home Assistant run (survives option reloads)."""
    return hass.data.setdefault(f"{DOMAIN}_capture", CaptureHub())


@callback
def our_stt(hass: HomeAssistant, entry_id: str) -> str:
    return er.async_get(hass).async_get_entity_id("stt", DOMAIN, f"{entry_id}_stt") \
        or "stt.better_assistant_speech_to_text"


@callback
def stt_engines(hass: HomeAssistant) -> list[tuple[str, str]]:
    """(entity id, platform) of every speech-to-text entity."""
    reg = er.async_get(hass)
    out = []
    for state in hass.states.async_all("stt"):
        entry = reg.async_get(state.entity_id)
        out.append((state.entity_id, entry.platform if entry else ""))
    return out


@callback
def underlying_engine(hass: HomeAssistant, options: dict[str, Any]) -> str | None:
    chosen = options.get(OPT_VT_STT)
    if chosen and hass.states.get(chosen) is not None:
        return chosen
    return pick_underlying(stt_engines(hass), DOMAIN)


@callback
def guess_person(hass: HomeAssistant) -> str:
    """Best guess at who is talking without any context: the only person in the house, else unknown."""
    persons = hass.states.async_all("person")
    return persons[0].entity_id if len(persons) == 1 else "unknown"


# ------------------------------------------------------------------ pipelines
@callback
def pipelines(hass: HomeAssistant) -> list[tuple[str, str, str | None]]:
    """(id, name, stt engine) of every Assist pipeline."""
    try:
        from homeassistant.components import assist_pipeline  # noqa: PLC0415
        return [(p.id, p.name, p.stt_engine) for p in assist_pipeline.async_get_pipelines(hass)]
    except Exception:  # noqa: BLE001 - assist_pipeline not loaded
        return []


async def async_switch_pipelines(hass: HomeAssistant, entry_id: str, options: dict[str, Any],
                                 chosen: list[str]) -> dict[str, str | None]:
    """Point the chosen pipelines at the pass-through and put the others back. Returns the
    pipeline -> original engine map to remember."""
    from homeassistant.components import assist_pipeline  # noqa: PLC0415
    ours = our_stt(hass, entry_id)
    found = {pid: engine for pid, _n, engine in pipelines(hass)}
    changes, kept = pipeline_plan(chosen, dict(options.get(OPT_VT_ORIGINALS) or {}), found, ours,
                                  bool(options.get(OPT_VT_ENABLED)), underlying_engine(hass, options))
    for pid, engine in changes.items():
        pipeline = assist_pipeline.async_get_pipeline(hass, pid)
        try:
            await assist_pipeline.async_update_pipeline(hass, pipeline, stt_engine=engine)
        except Exception:  # noqa: BLE001 - leave that one as it is
            _LOGGER.warning("Voice training: could not change the speech-to-text of %s", pipeline.name,
                            exc_info=True)
            if engine == ours:
                kept.pop(pid, None)
    return kept


# ------------------------------------------------------------------ the training conversation
class VoiceTrainer:
    """Per config entry. Sessions are kept per conversation id (a speaker's follow-up turns share it)."""

    def __init__(self, hass: HomeAssistant, entry) -> None:
        self.hass, self.entry = hass, entry
        self._sessions: dict[str, Session] = {}

    def _enabled(self) -> bool:
        return bool(self.entry.options.get(OPT_VT_ENABLED))

    @staticmethod
    def _is_voice(user_input) -> bool:
        return bool(user_input.device_id or getattr(user_input, "satellite_id", None))

    def active(self, conversation_id: str | None) -> Session | None:
        session = self._sessions.get(conversation_id or "")
        if session and session.until < time.time():
            self._sessions.pop(conversation_id, None)
            hub(self.hass).disarm(session.token)
            return None
        return session

    def _arm(self, session: Session, user_input) -> None:
        session.until = time.time() + SESSION_SECONDS
        hub(self.hass).arm(CaptureSlot(person=session.person, label=TRAIN, phrase=PHRASES[session.index],
                                       token=session.token, satellite=getattr(user_input, "satellite_id", None),
                                       device_id=user_input.device_id), time.time())

    async def async_handle(self, text: str, user_input, conversation_id: str, skills) -> tuple[str, bool] | None:
        """(speech, keep listening) when this turn belongs to voice training, else None."""
        session = self.active(conversation_id)
        if session:
            session.saved = hub(self.hass).saved_for(session.token)
            result = step(session, text)
            session.last_said = result.reply
            if result.done:
                self._sessions.pop(conversation_id, None)
                hub(self.hass).disarm(session.token)
                hub(self.hass).saved.pop(session.token, None)
            else:
                self._arm(session, user_input)
            return result.reply, not result.done
        if is_stop_training(text):
            return "Voice training isn't running.", False
        start = parse_start(text)
        if not start:
            return None
        if not self._enabled():
            return TURNED_OFF, False
        if not self._is_voice(user_input):
            return TYPED_ONLY, False
        _ok, name = start
        if name:
            person, problem = skills.resolve(name)
            if not person:
                return problem, False
        else:
            person = skills.speaker_person(user_input)
            if not person:
                people = skills.people_list()
                example = people[0][1].split()[0] if people else "Rob"
                return f"Tell me who you are first: say 'train {example}'s voice'.", False
        session = Session(person=person, name=skills.person_name(person), token=uuid4().hex)
        self._sessions[conversation_id] = session
        self._arm(session, user_input)
        session.last_said = intro(session.name)
        return session.last_said, True
