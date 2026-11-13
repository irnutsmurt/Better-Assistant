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

from .const import ALARM_URL, DOMAIN, HISTORY_SIZE, OPT_SNOOZE, OPT_SNOOZE_ENABLED, OPT_SNOOZE_LIMIT
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
    return True


async def _async_register_tone(hass: HomeAssistant) -> None:
    """Serve the bundled alarm tone once per Home Assistant run."""
    if hass.data.get(f"{DOMAIN}_tone"):
        return
    hass.data[f"{DOMAIN}_tone"] = True
    path = str(Path(__file__).parent / "www" / "alarm.mp3")
    await hass.http.async_register_static_paths([StaticPathConfig(ALARM_URL, path, True)])


async def _async_update_listener(hass: HomeAssistant, entry: BetterAssistantConfigEntry) -> None:
    """Reload on option changes, except snooze length and limit (read live, so a ringing alarm survives)."""
    old = {k: v for k, v in entry.runtime_data.options.items() if k not in (OPT_SNOOZE, OPT_SNOOZE_ENABLED, OPT_SNOOZE_LIMIT)}
    new = {k: v for k, v in entry.options.items() if k not in (OPT_SNOOZE, OPT_SNOOZE_ENABLED, OPT_SNOOZE_LIMIT)}
    entry.runtime_data.options = dict(entry.options)
    if old != new:
        await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: BetterAssistantConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.store.async_flush()
    return unloaded
