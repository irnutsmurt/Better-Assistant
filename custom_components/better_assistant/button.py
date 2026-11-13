"""The Start voice training button: the phone shows the phrases and the speaker listens without a
wake word. Only there while voice training is on."""
from __future__ import annotations

from homeassistant.components import persistent_notification
from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BetterAssistantConfigEntry
from .const import DOMAIN, OPT_VT_ENABLED
from .core.voicetrain import ACTION_SKIP, ACTION_STOP
from .sensor import device_info


async def async_setup_entry(hass: HomeAssistant, entry: BetterAssistantConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    if entry.options.get(OPT_VT_ENABLED):
        async_add_entities([StartTrainingButton(entry), TrainingActionButton(entry, ACTION_SKIP, "skip_phrase",
                                                                               "mdi:skip-next"),
                            TrainingActionButton(entry, ACTION_STOP, "stop_voice_training", "mdi:stop")])


class StartTrainingButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "start_voice_training"
    _attr_icon = "mdi:account-voice"

    def __init__(self, entry: BetterAssistantConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_start_voice_training"
        self._attr_device_info = device_info(entry)

    async def async_press(self) -> None:
        data = self._entry.runtime_data
        user_id = self._context.user_id if self._context else None
        problem = await data.trainer.async_start_from_phone(data.skills, user_id) \
            if data.trainer and data.skills else "Better Assistant isn't ready yet."
        if problem:
            persistent_notification.async_create(self.hass, problem, title="Voice training",
                                                 notification_id=f"{DOMAIN}_voice_training")


class TrainingActionButton(ButtonEntity):
    """Skip phrase / Stop voice training, for the dashboard."""
    _attr_has_entity_name = True

    def __init__(self, entry: BetterAssistantConfigEntry, action: str, key: str, icon: str) -> None:
        self._entry, self._action = entry, action
        self._attr_translation_key = key
        self._attr_icon = icon
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = device_info(entry)

    async def async_press(self) -> None:
        data = self._entry.runtime_data
        if data.trainer and data.skills:
            await data.trainer.async_phone_action(self._action, data.skills)
