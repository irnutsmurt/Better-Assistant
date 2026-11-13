"""Sensor: Brave searches used this month (cap as an attribute)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BraveConfigEntry
from .const import DEFAULTS, DOMAIN, OPT_MONTHLY_CAP, TITLE


def device_info(entry: BraveConfigEntry) -> DeviceInfo:
    return DeviceInfo(identifiers={(DOMAIN, entry.entry_id)}, name=TITLE, entry_type=DeviceEntryType.SERVICE)


async def async_setup_entry(hass: HomeAssistant, entry: BraveConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    async_add_entities([SearchesThisMonthSensor(entry)])


class SearchesThisMonthSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "searches_this_month"
    _attr_native_unit_of_measurement = "searches"
    _attr_icon = "mdi:magnify"
    _attr_should_poll = False

    def __init__(self, entry: BraveConfigEntry) -> None:
        self._entry = entry
        self._store = entry.runtime_data.store
        self._attr_unique_id = f"{entry.entry_id}_searches_this_month"
        self._attr_device_info = device_info(entry)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._store.async_add_listener(self._changed))

    @callback
    def _changed(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> int:
        return self._store.count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        cap = int(self._entry.options.get(OPT_MONTHLY_CAP, DEFAULTS[OPT_MONTHLY_CAP]))
        return {"cap": cap, "remaining": max(cap - self._store.count, 0), "month": self._store.month}
