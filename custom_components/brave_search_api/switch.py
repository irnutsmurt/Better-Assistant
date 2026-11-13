"""Guest mode and night mode switches."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BraveConfigEntry
from .sensor import device_info


async def async_setup_entry(hass: HomeAssistant, entry: BraveConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    skills = entry.runtime_data.skills
    entities = []
    if skills and skills.feature_on("guest_mode"):
        entities.append(ModeSwitch(entry, "guest", "guest_mode", "mdi:account-group"))
    if skills and skills.feature_on("night_mode"):
        entities.append(ModeSwitch(entry, "night", "night_mode", "mdi:weather-night"))
    async_add_entities(entities)


class ModeSwitch(SwitchEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: BraveConfigEntry, mode: str, key: str, icon: str) -> None:
        self._entry = entry
        self._mode = mode
        self._attr_translation_key = key
        self._attr_icon = icon
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = device_info(entry)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._entry.runtime_data.store.async_add_listener(self._changed))

    @callback
    def _changed(self) -> None:
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        return bool(self._entry.runtime_data.store.data.get("modes", {}).get(self._mode))

    async def _set(self, on: bool) -> None:
        skills = self._entry.runtime_data.skills
        await (skills.set_guest(on) if self._mode == "guest" else skills.set_night(on))
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)
