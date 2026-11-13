"""Runs device detection when the integration starts and again (debounced) whenever the entity,
device or area registry changes, so new hardware shows up without pressing Re-detect."""
from __future__ import annotations

import logging
from collections.abc import Callable

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, Event, HomeAssistant, callback
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er
from homeassistant.helpers.debounce import Debouncer

from .const import DOMAIN
from .discovery import async_detect

_LOGGER = logging.getLogger(__name__)
COOLDOWN = 30


class AutoDetect:
    def __init__(self, hass: HomeAssistant, entry, store, on_change: Callable[[], None] | None = None,
                 cooldown: float = COOLDOWN) -> None:
        self.hass, self.entry, self.store, self.on_change = hass, entry, store, on_change
        self._unsubs: list[Callable[[], None]] = []
        self._debouncer = Debouncer(hass, _LOGGER, cooldown=cooldown, immediate=False, function=self.async_run)

    async def async_run(self) -> None:
        try:
            await self.store.async_set_detected(async_detect(self.hass, dict(self.entry.options)))
        except Exception:  # noqa: BLE001 - detection must never break the integration
            _LOGGER.exception("Device detection failed")
            return
        if self.on_change:
            self.on_change()

    async def async_start(self) -> None:
        """Detect now if Home Assistant is already running (the normal 'add integration' path),
        otherwise once it has started; then follow registry changes."""
        if self.hass.state is CoreState.running:
            await self.async_run()
        else:
            async def _started(_event: Event) -> None:
                await self.async_run()
            self._unsubs.append(self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _started))
        for event in (er.EVENT_ENTITY_REGISTRY_UPDATED, dr.EVENT_DEVICE_REGISTRY_UPDATED,
                      ar.EVENT_AREA_REGISTRY_UPDATED):
            self._unsubs.append(self.hass.bus.async_listen(event, self._registry_changed))

    @callback
    def _registry_changed(self, event: Event) -> None:
        data = event.data
        if data.get("action") == "update" and set(data.get("changes") or {}) <= {"options"}:
            return                                   # Assist exposure changes (ours included): nothing new
        entity_id = data.get("entity_id") or ""
        reg = er.async_get(self.hass).async_get(entity_id) if entity_id else None
        if reg is not None and reg.platform == DOMAIN:
            return                                   # our own entities
        self._debouncer.async_schedule_call()

    @callback
    def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        self._debouncer.async_cancel()
