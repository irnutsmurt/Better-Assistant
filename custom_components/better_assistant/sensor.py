"""Sensor: Brave searches used this month (cap as an attribute)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BetterAssistantConfigEntry
from .const import DEFAULTS, DOMAIN, OPT_MONTHLY_CAP, OPT_VT_ENABLED, TITLE


def device_info(entry: BetterAssistantConfigEntry) -> DeviceInfo:
    return DeviceInfo(identifiers={(DOMAIN, entry.entry_id)}, name=TITLE, entry_type=DeviceEntryType.SERVICE)


async def async_setup_entry(hass: HomeAssistant, entry: BetterAssistantConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    entities: list[SensorEntity] = [SearchesThisMonthSensor(entry)]
    if entry.options.get(OPT_VT_ENABLED) and entry.runtime_data.trainer:
        entities.append(VoiceTrainingSensor(entry))
    async_add_entities(entities)


class SearchesThisMonthSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "searches_this_month"
    _attr_native_unit_of_measurement = "searches"
    _attr_icon = "mdi:magnify"
    _attr_should_poll = False

    def __init__(self, entry: BetterAssistantConfigEntry) -> None:
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


class VoiceTrainingSensor(SensorEntity):
    """Voice training progress for a dashboard: idle / training / done / stopped, with every phrase."""
    _attr_has_entity_name = True
    _attr_translation_key = "voice_training"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["idle", "training", "done", "stopped"]
    _attr_icon = "mdi:account-voice"
    _attr_should_poll = False

    def __init__(self, entry: BetterAssistantConfigEntry) -> None:
        self._trainer = entry.runtime_data.trainer
        self._attr_unique_id = f"{entry.entry_id}_voice_training"
        self._attr_device_info = device_info(entry)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._trainer.add_listener(self._changed))

    @callback
    def _changed(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        return self._trainer.view["status"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {k: v for k, v in self._trainer.view.items() if k != "status"}
