"""Upgrading from a voice beta (voice training / voice match live only in beta releases now).

Those betas put a speech-to-text pass-through ("Better Assistant speech-to-text", and one "Better
Assistant via <engine>" per engine) in front of the assistants' own engines. This release has no
pass-through, so each assistant is put back on the engine it used before, the leftover entities are
removed from the registry, and the beta's settings are forgotten. Recordings and the downloaded model
under /config/better_assistant are left alone (they're the user's; the README says how to delete them)."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# the voice beta's settings (option keys) and storage fields
VOICE_OPTIONS = ("voice_training", "voice_record_test", "voice_training_phone", "voice_training_satellite",
                 "voice_stt_engine", "voice_match", "voice_stt_originals")
VOICE_STORE = ("vt_borrowed", "vm_covered")
# unique id endings of the beta's buttons and sensor
VOICE_ENTITIES = ("_start_voice_training", "_skip_phrase", "_stop_voice_training", "_voice_training")


def strip_voice_options(options: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in options.items() if k not in VOICE_OPTIONS}


def _fallback(hass: HomeAssistant, chosen: str | None, ours: set[str]) -> str | None:
    """The engine the main pass-through wrapped: the one picked in its settings, else (as it did)
    Home Assistant Cloud, then a Wyoming engine (Whisper), then any other."""
    if chosen and chosen not in ours and hass.states.get(chosen) is not None:
        return chosen
    reg = er.async_get(hass)
    others = [(s.entity_id, (reg.async_get(s.entity_id) or None)) for s in hass.states.async_all("stt")
              if s.entity_id not in ours]
    for entity_id, _e in others:
        if entity_id == "stt.home_assistant_cloud":
            return entity_id
    for entity_id, e in others:
        if e and e.platform == "wyoming":
            return entity_id
    return others[0][0] if others else None


async def async_retire_voice(hass: HomeAssistant, entry, options: dict[str, Any]) -> None:
    """Put every assistant back on its own speech-to-text and remove the beta's leftovers."""
    reg = er.async_get(hass)
    leftovers = [e for e in reg.entities.values() if e.config_entry_id == entry.entry_id and (
        e.domain == "stt" or (e.domain in ("button", "sensor") and e.unique_id.endswith(VOICE_ENTITIES)))]
    store = entry.runtime_data.store
    if not leftovers and not any(store.data.get(k) for k in VOICE_STORE):
        return
    ours = {e.entity_id: e.unique_id for e in leftovers if e.domain == "stt"}
    try:
        from homeassistant.components import assist_pipeline  # noqa: PLC0415
        pipelines = list(assist_pipeline.async_get_pipelines(hass))
    except Exception:  # noqa: BLE001 - assist_pipeline not loaded: nothing points at us
        pipelines = []
    borrowed: dict[str, list] = dict(store.data.get("vt_borrowed") or {})
    covered: dict[str, str] = dict(store.data.get("vm_covered") or {})
    originals: dict[str, str | None] = dict(options.get("voice_stt_originals") or {})
    fallback = _fallback(hass, options.get("voice_stt_engine"), set(ours))
    stuck: list[str] = []
    via = f"{entry.entry_id}_stt_via_"
    for pipeline in pipelines:
        engine, prefer_local = pipeline.stt_engine, pipeline.prefer_local_intents
        if pipeline.id in borrowed:                       # a training session cut short by a restart
            engine, prefer_local = borrowed[pipeline.id][0], bool(borrowed[pipeline.id][1])
        if engine in ours and pipeline.id in covered:     # voice match had it listen through a pass-through
            engine = covered[pipeline.id]
        if engine in ours:
            uid = ours[engine]
            if uid.startswith(via):                       # "Better Assistant via <engine>": that engine
                engine = uid[len(via):]
            elif originals.get(pipeline.id) and originals[pipeline.id] not in ours:
                engine = originals[pipeline.id]           # what it had before voice training switched it
            else:
                engine = fallback                         # the engine the pass-through was passing to
        if engine in ours or not engine or (hass.states.get(engine) is None and reg.async_get(engine) is None):
            if pipeline.stt_engine in ours:
                stuck.append(pipeline.name)
            continue
        if (engine, prefer_local) == (pipeline.stt_engine, pipeline.prefer_local_intents):
            continue
        try:
            await assist_pipeline.async_update_pipeline(hass, pipeline, stt_engine=engine,
                                                        prefer_local_intents=prefer_local)
            _LOGGER.info("Put the %s assistant back on %s", pipeline.name, engine)
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Couldn't put the %s assistant back on %s", pipeline.name, engine, exc_info=True)
            stuck.append(pipeline.name)
    if stuck:
        _LOGGER.warning("Pick a speech-to-text engine for: %s", ", ".join(stuck))
        from homeassistant.components import persistent_notification  # noqa: PLC0415
        persistent_notification.async_create(
            hass, "Better Assistant no longer has its own speech-to-text (that was part of the voice "
                  "recognition beta). Pick a speech-to-text engine for these assistants in Settings > Voice "
                  "assistants: " + ", ".join(stuck) + ".",
            title="Better Assistant: speech-to-text", notification_id=f"{DOMAIN}_stt_retired")
    else:
        for e in leftovers:
            reg.async_remove(e.entity_id)
    for key in VOICE_STORE:
        store.data.pop(key, None)
    store.changed()
    await store.async_flush()
