"""Better Assistant: a Google Assistant-style conversation agent for Home Assistant. Household skills
(timers, alarms, reminders, notes, calendar, music, rooms, bed, cameras, health) set up from detected
devices, compound commands through Home Assistant's own agent, and optional web answers from the
Brave Search API (no AI writes the answer). Unofficial community integration."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from homeassistant.components.http import StaticPathConfig

from .const import (ALARM_URL, DOMAIN, HISTORY_SIZE, OPT_ALARM_MUSIC, OPT_SNOOZE, OPT_SNOOZE_ENABLED, OPT_SNOOZE_LIMIT,
                    OPT_VOICE_PENDING)
from .autodetect import AutoDetect
from .store import BetterAssistantStore

if TYPE_CHECKING:
    from .skills import Skills

PLATFORMS = [Platform.CONVERSATION, Platform.SENSOR, Platform.SWITCH, Platform.TODO]


@dataclass
class BetterAssistantRuntimeData:
    store: BetterAssistantStore
    skills: Skills | None = None
    options: dict = field(default_factory=dict)        # options the entry was set up with
    heard: deque[str] = field(default_factory=lambda: deque(maxlen=HISTORY_SIZE))


type BetterAssistantConfigEntry = ConfigEntry[BetterAssistantRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: BetterAssistantConfigEntry) -> bool:
    store = BetterAssistantStore(hass, entry.entry_id)
    await store.async_load()
    from .migrate import async_retire_voice, strip_voice_options  # noqa: PLC0415 - leftovers of a voice beta

    before = dict(entry.options)                           # the voice settings say what to put back
    if (kept := strip_voice_options(before)) != before:
        hass.config_entries.async_update_entry(entry, options=kept)
    entry.runtime_data = BetterAssistantRuntimeData(store=store, options=dict(entry.options))
    await _async_register_tone(hass)
    from .skills import Skills  # noqa: PLC0415 - needs runtime_data set first

    skills = Skills(hass, entry)
    await skills.async_start()
    entry.runtime_data.skills = skills
    entry.async_on_unload(skills.async_stop)
    # Detection: now if Home Assistant is already running, else once it has started; again after
    # registry changes. Anything built from detection (hidden doors, lists) is refreshed after each run.
    auto = AutoDetect(hass, entry, store, on_change=skills.on_detected)
    await auto.async_start()
    entry.async_on_unload(auto.async_stop)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # a voice beta switched assistants to its speech-to-text pass-through: put them back, once started
    from homeassistant.helpers.start import async_at_started  # noqa: PLC0415

    async def _retire(_hass: HomeAssistant) -> None:
        await async_retire_voice(hass, entry, before)
    entry.async_on_unload(async_at_started(hass, _retire))
    from .app_panel import async_app_changed, async_setup_panel  # noqa: PLC0415 - the app in the sidebar

    entry.async_on_unload(store.async_add_listener(lambda: async_app_changed(hass)))
    await async_setup_panel(hass)
    if entry.options.get(OPT_VOICE_PENDING):
        entry.async_create_background_task(hass, _async_voice_pending(hass, entry), f"{DOMAIN}_voice_setup")
    return True


async def _async_voice_pending(hass: HomeAssistant, entry: BetterAssistantConfigEntry) -> None:
    """Finish voice setup chosen during first setup: make the pipeline (our conversation entity exists
    now), switch the chosen speakers, say what happened in a notification, then forget the request."""
    from homeassistant.components import persistent_notification  # noqa: PLC0415
    from .core.voice import Report  # noqa: PLC0415
    from .voice_setup import async_apply  # noqa: PLC0415

    pending = dict(entry.options.get(OPT_VOICE_PENDING) or {})
    report = Report()
    try:
        await async_apply(hass, entry.entry_id, pending.get("stt"), pending.get("tts"),
                          bool(pending.get("preferred", True)), list(pending.get("satellites") or []), report)
    except Exception as err:  # noqa: BLE001 - never break the integration over this
        report.manual.append(f"Create the voice assistant by hand in Settings > Voice assistants ({err})")
    entry.runtime_data.options.pop(OPT_VOICE_PENDING, None)   # so the update below doesn't reload
    hass.config_entries.async_update_entry(
        entry, options={k: v for k, v in entry.options.items() if k != OPT_VOICE_PENDING})
    persistent_notification.async_create(hass, report.text(), title="Better Assistant voice setup",
                                         notification_id=f"{DOMAIN}_voice_setup")


async def _async_register_tone(hass: HomeAssistant) -> None:
    """Serve the bundled alarm tone once per Home Assistant run."""
    if hass.data.get(f"{DOMAIN}_tone"):
        return
    hass.data[f"{DOMAIN}_tone"] = True
    path = str(Path(__file__).parent / "www" / "alarm-60s.mp3")
    await hass.http.async_register_static_paths([StaticPathConfig(ALARM_URL, path, True)])


async def _async_update_listener(hass: HomeAssistant, entry: BetterAssistantConfigEntry) -> None:
    """Reload on option changes, except the ones read live (so a ringing alarm survives)."""
    live = (OPT_SNOOZE, OPT_SNOOZE_ENABLED, OPT_SNOOZE_LIMIT, OPT_ALARM_MUSIC)
    old = {k: v for k, v in entry.runtime_data.options.items() if k not in live}
    new = {k: v for k, v in entry.options.items() if k not in live}
    entry.runtime_data.options = dict(entry.options)
    if old != new:
        await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_entry(hass: HomeAssistant, entry: BetterAssistantConfigEntry) -> None:
    """Better Assistant removed: take its app out of the sidebar (a reload keeps it there)."""
    from .app_panel import async_remove_panel  # noqa: PLC0415

    async_remove_panel(hass)


async def async_unload_entry(hass: HomeAssistant, entry: BetterAssistantConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.store.async_flush()
    return unloaded
