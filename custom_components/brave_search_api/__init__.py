"""Brave Search API: a Home Assistant conversation agent that answers questions from the Brave
Search API (no AI writes the answer), answers simple questions locally, and runs compound commands
through Home Assistant's own agent. Unofficial community integration."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.start import async_at_started

from homeassistant.components.http import StaticPathConfig

from .const import ALARM_URL, DOMAIN, HISTORY_SIZE, OPT_SNOOZE
from .discovery import async_detect
from .store import BraveStore

if TYPE_CHECKING:
    from .skills import Skills

PLATFORMS = [Platform.CONVERSATION, Platform.SENSOR, Platform.TODO]


@dataclass
class BraveRuntimeData:
    store: BraveStore
    skills: Skills | None = None
    options: dict = field(default_factory=dict)        # options the entry was set up with
    heard: deque[str] = field(default_factory=lambda: deque(maxlen=HISTORY_SIZE))


type BraveConfigEntry = ConfigEntry[BraveRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: BraveConfigEntry) -> bool:
    store = BraveStore(hass, entry.entry_id)
    await store.async_load()
    if not store.detected:
        # First run: detect devices once everything else has loaded.
        async def _first_detect(hass: HomeAssistant) -> None:
            await store.async_set_detected(async_detect(hass, dict(entry.options)))

        entry.async_on_unload(async_at_started(hass, _first_detect))
    entry.runtime_data = BraveRuntimeData(store=store, options=dict(entry.options))
    await _async_register_tone(hass)
    from .skills import Skills  # noqa: PLC0415 - needs runtime_data set first

    skills = Skills(hass, entry)
    await skills.async_start()
    entry.runtime_data.skills = skills
    entry.async_on_unload(skills.async_stop)
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


async def _async_update_listener(hass: HomeAssistant, entry: BraveConfigEntry) -> None:
    """Reload on option changes, except the snooze length (read live, so a ringing alarm survives)."""
    old = {k: v for k, v in entry.runtime_data.options.items() if k != OPT_SNOOZE}
    new = {k: v for k, v in entry.options.items() if k != OPT_SNOOZE}
    entry.runtime_data.options = dict(entry.options)
    if old != new:
        await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: BraveConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.store.async_flush()
    return unloaded
