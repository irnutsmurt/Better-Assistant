"""The Voice training page in the sidebar: shown while voice training is on, nothing to set up.

The page talks to Better Assistant over two websocket commands, so it doesn't depend on entity ids:
  better_assistant/voice_training/subscribe  -> the training view now and after every change
  better_assistant/voice_training/action     -> start / skip / stop (start uses the signed-in user)"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.components import frontend, panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN
from .core.voicetrain import ACTION_SKIP, ACTION_STOP

PANEL_PATH = "better-assistant-voice"
PANEL_URL = "/better_assistant/voice-panel.js"
PANEL_ELEMENT = "better-assistant-voice-panel"


def _trainer_and_skills(hass: HomeAssistant):
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        data = entry.runtime_data
        if data.trainer and data.skills:
            return data.trainer, data.skills
    return None, None


async def async_setup_panel(hass: HomeAssistant) -> None:
    """Serve the page's script and register the commands once per run, then add the sidebar page."""
    if not hass.data.get(f"{DOMAIN}_voice_panel"):
        hass.data[f"{DOMAIN}_voice_panel"] = True
        path = str(Path(__file__).parent / "www" / "voice-panel.js")
        await hass.http.async_register_static_paths([StaticPathConfig(PANEL_URL, path, False)])
        websocket_api.async_register_command(hass, ws_subscribe)
        websocket_api.async_register_command(hass, ws_action)
    if PANEL_PATH not in hass.data.get(frontend.DATA_PANELS, {}):
        await panel_custom.async_register_panel(
            hass, frontend_url_path=PANEL_PATH, webcomponent_name=PANEL_ELEMENT, module_url=PANEL_URL,
            sidebar_title="Voice training", sidebar_icon="mdi:account-voice", require_admin=False,
            embed_iframe=False)


@callback
def async_remove_panel(hass: HomeAssistant) -> None:
    if PANEL_PATH in hass.data.get(frontend.DATA_PANELS, {}):
        frontend.async_remove_panel(hass, PANEL_PATH)


@websocket_api.websocket_command({vol.Required("type"): "better_assistant/voice_training/subscribe"})
@callback
def ws_subscribe(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    trainer, _skills = _trainer_and_skills(hass)
    if trainer is None:
        connection.send_error(msg["id"], "not_ready", "Better Assistant isn't running.")
        return

    @callback
    def send() -> None:
        connection.send_message(websocket_api.event_message(msg["id"], trainer.view))

    connection.subscriptions[msg["id"]] = trainer.add_listener(send)
    connection.send_result(msg["id"])
    send()


@websocket_api.websocket_command({vol.Required("type"): "better_assistant/voice_training/action",
                                  vol.Required("action"): vol.In(["start", "skip", "stop"])})
@websocket_api.async_response
async def ws_action(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    trainer, skills = _trainer_and_skills(hass)
    if trainer is None:
        connection.send_error(msg["id"], "not_ready", "Better Assistant isn't running.")
        return
    problem = None
    if msg["action"] == "start":
        problem = await trainer.async_start_from_phone(skills, connection.user.id if connection.user else None)
    else:
        await trainer.async_phone_action(ACTION_SKIP if msg["action"] == "skip" else ACTION_STOP, skills)
    connection.send_result(msg["id"], {"problem": problem})
