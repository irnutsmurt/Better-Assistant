"""The integration's own to-do lists: Reminders, Notes and Messages (stored with the integration)."""
from __future__ import annotations

from homeassistant.components.todo import TodoItem, TodoItemStatus, TodoListEntity, TodoListEntityFeature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import BraveConfigEntry
from .const import LISTS
from .sensor import device_info


async def async_setup_entry(hass: HomeAssistant, entry: BraveConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    async_add_entities([BraveTodoList(entry, key, name) for key, name in LISTS.items()])


class BraveTodoList(TodoListEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM | TodoListEntityFeature.SET_DUE_DATETIME_ON_ITEM
        | TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM)

    def __init__(self, entry: BraveConfigEntry, key: str, name: str) -> None:
        self._key = key
        self._store = entry.runtime_data.store
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = device_info(entry)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._store.async_add_listener(self._changed))

    @callback
    def _changed(self) -> None:
        self.async_write_ha_state()

    @property
    def todo_items(self) -> list[TodoItem]:
        out = []
        for i in self._store.items(self._key):
            due = (dt_util.parse_datetime(i["due"]) or dt_util.parse_date(i["due"])) if i.get("due") else None
            out.append(TodoItem(summary=i["summary"], uid=i["uid"], status=TodoItemStatus(i["status"]),
                                due=due, description=i.get("description")))
        return out

    async def async_create_todo_item(self, item: TodoItem) -> None:
        due = item.due.isoformat() if item.due else None
        self._store.add_item(self._key, item.summary or "", due, item.description)

    async def async_update_todo_item(self, item: TodoItem) -> None:
        self._store.update_item(self._key, item.uid, summary=item.summary,
                                status=(item.status or TodoItemStatus.NEEDS_ACTION).value,
                                due=item.due.isoformat() if item.due else None, description=item.description)

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        self._store.remove_items(self._key, uids)
