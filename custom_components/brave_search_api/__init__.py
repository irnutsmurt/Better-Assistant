"""Brave Search API: a Home Assistant conversation agent that answers questions from the Brave
Search API (no AI writes the answer), answers simple questions locally, and runs compound commands
through Home Assistant's own agent. Unofficial community integration."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.start import async_at_started

from .const import HISTORY_SIZE
from .discovery import async_detect
from .store import BraveStore

PLATFORMS = [Platform.CONVERSATION, Platform.SENSOR]


@dataclass
class BraveRuntimeData:
    store: BraveStore
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
    entry.runtime_data = BraveRuntimeData(store=store)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: BraveConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: BraveConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.store.async_flush()
    return unloaded
