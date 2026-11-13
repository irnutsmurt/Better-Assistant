"""Persistent per-entry data: monthly search count and the last device detection."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN, LISTS, STORAGE_VERSION


class BraveStore:
    """Wraps homeassistant.helpers.storage.Store (saved under .storage, not in /config)."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}")
        self.data: dict[str, Any] = {}
        self._listeners: list[Callable[[], None]] = []

    async def async_load(self) -> None:
        self.data = await self._store.async_load() or {}
        self.data.setdefault("usage", {"month": "", "count": 0})
        self.data.setdefault("detected", {})
        self.data.setdefault("lists", {})
        for key in LISTS:
            self.data["lists"].setdefault(key, [])
        self.data.setdefault("reminders", {})       # todo uid -> reminder details
        self.data.setdefault("alarms", {})          # satellite entity id -> alarm

    @staticmethod
    def _month() -> str:
        return dt_util.now().strftime("%Y-%m")

    @property
    def count(self) -> int:
        usage = self.data["usage"]
        return usage["count"] if usage.get("month") == self._month() else 0

    @property
    def month(self) -> str:
        return self._month()

    async def async_take_slot(self, cap: int) -> bool:
        """Count one search; False (and nothing counted) once this month's cap is reached."""
        month = self._month()
        usage = self.data["usage"]
        if usage.get("month") != month:
            usage.update(month=month, count=0)
        if usage["count"] >= cap:
            return False
        usage["count"] += 1
        self._store.async_delay_save(lambda: self.data, 5)
        self._notify()
        return True

    @property
    def detected(self) -> dict[str, Any]:
        return self.data["detected"]

    async def async_set_detected(self, detected: dict[str, Any]) -> None:
        self.data["detected"] = detected
        await self._store.async_save(self.data)

    # ------------------------------------------------------------ todo lists
    def items(self, key: str) -> list[dict[str, Any]]:
        return self.data["lists"][key]

    def find(self, key: str, uid: str) -> dict[str, Any] | None:
        return next((i for i in self.items(key) if i["uid"] == uid), None)

    @callback
    def add_item(self, key: str, summary: str, due: str | None = None, description: str | None = None) -> str:
        uid = uuid4().hex
        self.items(key).append({"uid": uid, "summary": summary, "status": "needs_action",
                                "due": due, "description": description})
        self.changed()
        return uid

    @callback
    def update_item(self, key: str, uid: str, **changes: Any) -> None:
        item = self.find(key, uid)
        if item:
            item.update(changes)
            self.changed()

    @callback
    def remove_items(self, key: str, uids: set[str] | list[str]) -> None:
        uids = set(uids)
        self.data["lists"][key] = [i for i in self.items(key) if i["uid"] not in uids]
        self.changed()

    @callback
    def changed(self) -> None:
        """Save soon and tell listeners (sensor, todo lists, scheduler)."""
        self._store.async_delay_save(lambda: self.data, 2)
        self._notify()

    async def async_flush(self) -> None:
        await self._store.async_save(self.data)

    @callback
    def async_add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb)

    def _notify(self) -> None:
        for cb in list(self._listeners):
            cb()
