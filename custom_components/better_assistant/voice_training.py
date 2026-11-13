"""Voice training (experimental): the training conversation on a voice speaker, saving recordings to
/config/better_assistant/voice, counting and deleting them, and pointing pipelines at the
pass-through speech-to-text entity. Nothing recognises voices yet; this only collects labelled clips
for a later voice-match test. Off by default: nothing is recorded until it is turned on.

Recordings never leave the machine: they are plain files under the config folder."""
from __future__ import annotations

import asyncio
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

from .const import (DOMAIN, OPT_VT_ENABLED, OPT_VT_ORIGINALS, OPT_VT_PHONE, OPT_VT_RECORD_TEST,
                    OPT_VT_SATELLITE, OPT_VT_STT)
from .core.voicetrain import (
    SPOKEN_INTRO,
    view,
    ACTION_SKIP,
    ACTION_STOP,
    PENDING_SECONDS,
    skip,
    stop,
    NO_PHONE,
    PHONE_START,
    PHONE_TAG,
    PHONE_TITLE,
    phone_text,
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


# the speaker's own "listening" chime, played to open the mic without a wake word
PREANNOUNCE_URL = "/api/assist_satellite/static/preannounce.mp3"
PANEL_LINK = "/better-assistant-voice"            # voice_panel.PANEL_PATH


# ------------------------------------------------------------------ the training conversation
class VoiceTrainer:
    """Per config entry. Sessions are kept per conversation id (a speaker's follow-up turns share it)."""

    def __init__(self, hass: HomeAssistant, entry) -> None:
        self.hass, self.entry = hass, entry
        self._sessions: dict[str, Session] = {}
        self._pending: dict[str, Session] = {}         # satellite -> a session started from the phone
        self.view: dict = view(None, "idle")            # what the Voice training sensor shows
        self._listeners: list = []

    def add_listener(self, listener) -> callable:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def _publish(self, session: Session | None, status: str) -> None:
        if session is not None:
            session.saved = hub(self.hass).saved_for(session.token) or session.saved
        self.view = view(session, status)
        for listener in list(self._listeners):
            listener()

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

    def _arm(self, session: Session, user_input=None) -> None:
        if user_input is not None:
            session.satellite = getattr(user_input, "satellite_id", None) or session.satellite
            session.device_id = user_input.device_id or session.device_id
        session.until = time.time() + SESSION_SECONDS
        hub(self.hass).arm(CaptureSlot(person=session.person, label=TRAIN, phrase=PHRASES[session.index],
                                       token=session.token, satellite=session.satellite,
                                       device_id=session.device_id), time.time())

    def _claim(self, conversation_id: str, user_input) -> Session | None:
        """The first turn from a speaker that the phone started training on."""
        sat = getattr(user_input, "satellite_id", None)
        session = self._pending.pop(sat, None) if sat else None
        if session and session.until >= time.time():
            self._sessions[conversation_id] = session
            return session
        return None

    def _end(self, session: Session, status: str = "done") -> None:
        self._publish(session, status)
        session.until = 0.0                            # over: later replies don't publish "training"
        if session.borrowed:
            borrowed, session.borrowed = session.borrowed, None
            self.entry.async_create_background_task(self.hass, self._give_back(borrowed),
                                                    "better_assistant_voice_give_back")
        for key, s in list(self._sessions.items()):
            if s is session:
                self._sessions.pop(key, None)
        for key, s in list(self._pending.items()):
            if s is session:
                self._pending.pop(key, None)
        hub(self.hass).disarm(session.token)
        hub(self.hass).saved.pop(session.token, None)

    async def _borrow(self, session: Session) -> None:
        """Record on whatever assistant the speaker uses: point that pipeline's speech-to-text at the
        pass-through for the session (the pass-through hands audio on to the pipeline's own engine)."""
        from homeassistant.components import assist_pipeline  # noqa: PLC0415
        from .voice_setup import pipeline_select  # noqa: PLC0415
        try:
            select = pipeline_select(self.hass, session.satellite) if session.satellite else None
            state = self.hass.states.get(select) if select else None
            name = state.state if state else None
            found = [pid for pid, n, _e in pipelines(self.hass) if n == name] if name else []
            pipeline = assist_pipeline.async_get_pipeline(self.hass, found[0] if found else None)
            ours = our_stt(self.hass, self.entry.entry_id)
            store = self.entry.runtime_data.store
            saved = store.data["vt_borrowed"].get(pipeline.id)
            # a session cut short by a restart left it switched: its real settings are the saved ones
            engine, prefer_local = (saved[0], bool(saved[1])) if saved else \
                (pipeline.stt_engine, pipeline.prefer_local_intents)
            if engine == ours and not prefer_local:
                return
            if engine != ours:
                hub(self.hass).engine = engine
            session.borrowed = (pipeline.id, engine, prefer_local)
            store.data["vt_borrowed"][pipeline.id] = [engine, prefer_local]
            await store.async_flush()                  # put back after a restart, too
            # Home Assistant's own commands go first when local intents are preferred, so "set a timer
            # for ten minutes" would set a timer instead of reaching the trainer
            await assist_pipeline.async_update_pipeline(self.hass, pipeline, stt_engine=ours,
                                                        prefer_local_intents=False)
        except Exception:  # noqa: BLE001 - train anyway; the clip just isn't saved
            _LOGGER.warning("Voice training: couldn't record on this speaker's assistant", exc_info=True)

    async def _give_back(self, borrowed: tuple[str, str | None, bool]) -> None:
        from homeassistant.components import assist_pipeline  # noqa: PLC0415
        pid, engine, prefer_local = borrowed
        hub(self.hass).engine = None
        try:
            pipeline = assist_pipeline.async_get_pipeline(self.hass, pid)
            await assist_pipeline.async_update_pipeline(self.hass, pipeline, stt_engine=engine,
                                                        prefer_local_intents=prefer_local)
            store = self.entry.runtime_data.store
            store.data["vt_borrowed"].pop(pid, None)
            store.changed()
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Voice training: couldn't put back the speech-to-text of %s", pid, exc_info=True)

    async def _listen(self, satellite: str) -> str | None:
        """Make the speaker play its listening chime and listen, without a wake word. None when it did."""
        problem = None
        for attempt in range(4):                       # it may still be finishing the last turn
            try:
                await self.hass.services.async_call(
                    "assist_satellite", "start_conversation",
                    {"entity_id": satellite, "start_media_id": PREANNOUNCE_URL, "preannounce": False},
                    blocking=True)
                return None
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Voice training: %s couldn't start listening (try %s): %r", satellite, attempt + 1, err)
                problem = str(err) or type(err).__name__
                await asyncio.sleep(1.0)
        _LOGGER.warning("Voice training: %s couldn't start listening: %s", satellite, problem)
        return problem

    def _wait_for_ding(self, conversation_id: str, session: Session) -> None:
        """This turn ends; the next phrase comes in the conversation the ding starts."""
        self._sessions.pop(conversation_id, None)
        session.until = time.time() + PENDING_SECONDS
        self._pending[session.satellite] = session
        self.entry.async_create_background_task(self.hass, self._relisten(session), "better_assistant_voice_relisten")

    async def _relisten(self, session: Session) -> None:
        """After the turn the speaker stops listening; when it is quiet again, ding and listen."""
        await asyncio.sleep(0.4)
        for _ in range(60):                            # up to ~30 s for it to finish talking
            state = self.hass.states.get(session.satellite)
            if state is None or state.state == "idle":
                break
            await asyncio.sleep(0.5)
        if session.until and await self._listen(session.satellite):
            self._end(session, "stopped")

    async def async_give_back_leftovers(self) -> None:
        """At startup: put back any assistant a session switched before Home Assistant restarted."""
        for pid, (engine, prefer_local) in list(self.entry.runtime_data.store.data["vt_borrowed"].items()):
            await self._give_back((pid, engine, bool(prefer_local)))

    def default_satellite(self, skills) -> str | None:
        chosen = self.entry.options.get(OPT_VT_SATELLITE)
        if chosen and self.hass.states.get(chosen):
            return chosen
        sats = [s for s in skills.satellites() if self.hass.states.get(s)] or \
            [s.entity_id for s in self.hass.states.async_all("assist_satellite")]
        return sats[0] if sats else None

    async def async_start_from_phone(self, skills, user_id: str | None, satellite: str | None = None) -> str | None:
        """The Start voice training button: the phone shows the phrases and the speaker listens without
        a wake word. None when started, else why not (for a notification)."""
        if not self._enabled():
            return TURNED_OFF
        person = next((st.entity_id for st in self.hass.states.async_all("person")
                       if user_id and st.attributes.get("user_id") == user_id), None)
        if not person:
            return "I couldn't tell who pressed the button. Link your user to a person in Settings > People."
        satellite = satellite or self.default_satellite(skills)
        if not satellite:
            return "There's no voice speaker to train on."
        for s in list(self._sessions.values()) + list(self._pending.values()):
            if s.person == person:
                self._end(s)
        session = Session(person=person, name=skills.person_name(person), token=uuid4().hex, silent=True,
                          satellite=satellite)
        self._arm(session)
        session.until = time.time() + PENDING_SECONDS
        self._pending[satellite] = session
        self._publish(session, "training")
        await self._borrow(session)
        try:                                           # the instructions, once; then the ding
            await self.hass.services.async_call(
                "assist_satellite", "announce",
                {"entity_id": satellite, "message": SPOKEN_INTRO, "preannounce": False}, blocking=True)
        except Exception:  # noqa: BLE001 - the screen says it too
            _LOGGER.debug("Voice training: couldn't say the instructions", exc_info=True)
        problem = await self._listen(satellite)
        if problem:
            self._end(session, "stopped")
            return f"The speaker couldn't start listening ({problem})."
        return None

    async def async_phone_action(self, action: str, skills) -> None:
        """Stop / Skip pressed on the training notification."""
        if action not in (ACTION_STOP, ACTION_SKIP):
            return
        sessions = list(self._sessions.values()) + list(self._pending.values())
        if not sessions:
            return
        session = sessions[-1]
        session.saved = hub(self.hass).saved_for(session.token)
        result = stop(session) if action == ACTION_STOP else skip(session)
        if result.done:
            self._end(session, "stopped" if action == ACTION_STOP else "done")
        else:
            self._arm(session)
        await self._say(session, skills, result.reply)

    async def async_handle(self, text: str, user_input, conversation_id: str, skills) -> tuple[str, bool] | None:
        """(speech, keep listening) when this turn belongs to voice training, else None."""
        session = self.active(conversation_id) or self._claim(conversation_id, user_input)
        if session:
            session.saved = hub(self.hass).saved_for(session.token)
            result = step(session, text)
            if result.done:
                self._end(session, "done" if session.index >= len(PHRASES) else "stopped")
            else:
                self._arm(session, user_input)
            speech = await self._say(session, skills, result.reply)
            if not result.done and session.silent and session.satellite:
                # nothing said, so the speaker won't keep listening by itself: open it again
                self._wait_for_ding(conversation_id, session)
                return speech, False
            return speech, not result.done
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
        self._publish(session, "training")
        await self._borrow(session)
        if self.entry.options.get(OPT_VT_PHONE, True):
            session.phone = skills.phone_for(person)
            session.silent = bool(session.phone)
            if session.phone:
                await self._say(session, skills, intro(session.name))
                spoken = f"{PHONE_START} {SPOKEN_INTRO}"
                session.last_said = spoken
                if session.satellite:                  # speak the instructions, then the ding
                    self._wait_for_ding(conversation_id, session)
                    return spoken, False
                return spoken, True
            session.last_said = NO_PHONE + intro(session.name)
            return session.last_said, True
        session.last_said = intro(session.name)
        return session.last_said, True

    async def _say(self, session: Session, skills, reply: str) -> str:
        """Speaker mode: the reply is spoken. Phone mode: it goes to the phone and the speaker says
        nothing, so there is nothing for its microphone to pick up."""
        if session.index < len(PHRASES) and session.until:
            self._publish(session, "training")
        if not session.phone:
            if session.silent:
                session.last_said = ""
                return ""
            session.last_said = reply
            return reply
        await skills.notify(session.person, PHONE_TITLE, phone_text(session, reply),
                            {"tag": PHONE_TAG, "push": {"interruption-level": "time-sensitive"},
                             "clickAction": PANEL_LINK, "url": PANEL_LINK,       # tap: the Voice training page
                             "actions": [] if session.index >= len(PHRASES) else
                             [{"action": ACTION_SKIP, "title": "Skip"}, {"action": ACTION_STOP, "title": "Stop"}]})
        session.last_said = ""
        return ""
