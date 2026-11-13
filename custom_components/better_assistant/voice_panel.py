"""The Voice training page in the sidebar: shown while voice training is on, nothing to set up.

The page talks to Better Assistant over two websocket commands, so it doesn't depend on entity ids:
  better_assistant/voice_training/subscribe  -> the training view now and after every change
  better_assistant/voice_training/action     -> start / skip / stop (start uses the signed-in user)"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import voluptuous as vol
from aiohttp import web

from homeassistant.components import frontend, panel_custom, websocket_api
from homeassistant.components.http import HomeAssistantView, StaticPathConfig
from homeassistant.components.http.auth import async_sign_path
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN, OPT_VM_ENABLED
from .core.voicetrain import ACTION_SKIP, ACTION_STOP, TEST, TRAIN

PANEL_PATH = "better-assistant-voice"
PANEL_URL = "/better_assistant/voice-panel.js"
PANEL_ELEMENT = "better-assistant-voice-panel"


CLIP_URL = "/api/better_assistant/voice_clip/{}"


def _entry(hass: HomeAssistant):
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        if entry.runtime_data.trainer and entry.runtime_data.skills:
            return entry
    return None


def _trainer_and_skills(hass: HomeAssistant):
    entry = _entry(hass)
    return (entry.runtime_data.trainer, entry.runtime_data.skills) if entry else (None, None)


def _names(hass: HomeAssistant) -> dict[str, str]:
    return {st.entity_id: st.name for st in hass.states.async_all("person")}


def _person_of(hass: HomeAssistant, user) -> str | None:
    return next((st.entity_id for st in hass.states.async_all("person")
                 if user and st.attributes.get("user_id") == user.id), None)


def _may_see(hass: HomeAssistant, user, meta: dict) -> bool:
    """Admins see every clip; others their own and anything not yet anyone's."""
    if user is None:
        return False
    if user.is_admin:
        return True
    mine = _person_of(hass, user)
    people = {meta.get("person"), (meta.get("match") or {}).get("person")}
    return bool(mine and mine in people) or meta.get("person") in (None, "unknown")


def _view(hass: HomeAssistant) -> dict:
    entry = _entry(hass)
    if entry is None:
        return {"status": "idle", "phrases": [], "match": {"status": "off"}}
    data = entry.runtime_data
    match = data.matcher.summary(_names(hass)) if data.matcher else {"status": "off"}
    return {**data.trainer.view, "match": match, "match_on": bool(entry.options.get(OPT_VM_ENABLED))}


async def async_setup_panel(hass: HomeAssistant) -> None:
    """Serve the page's script and register the commands once per run, then add the sidebar page."""
    if not hass.data.get(f"{DOMAIN}_voice_panel"):
        hass.data[f"{DOMAIN}_voice_panel"] = True
        path = str(Path(__file__).parent / "www" / "voice-panel.js")
        await hass.http.async_register_static_paths([StaticPathConfig(PANEL_URL, path, False)])
        websocket_api.async_register_command(hass, ws_subscribe)
        websocket_api.async_register_command(hass, ws_action)
        websocket_api.async_register_command(hass, ws_clips)
        websocket_api.async_register_command(hass, ws_clip_action)
        hass.http.register_view(VoiceClipView())
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
    entry = _entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_ready", "Better Assistant isn't running.")
        return

    @callback
    def send() -> None:
        connection.send_message(websocket_api.event_message(msg["id"], _view(hass)))

    unsubs = [entry.runtime_data.trainer.add_listener(send)]
    if entry.runtime_data.matcher:
        unsubs.append(entry.runtime_data.matcher.add_listener(send))
    connection.subscriptions[msg["id"]] = lambda: [u() for u in unsubs]
    connection.send_result(msg["id"])
    send()


@websocket_api.websocket_command({vol.Required("type"): "better_assistant/voice_training/action",
                                  vol.Required("action"): vol.In(["start", "skip", "stop", "match_on", "match_off"])})
@websocket_api.async_response
async def ws_action(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    entry = _entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_ready", "Better Assistant isn't running.")
        return
    trainer, skills = entry.runtime_data.trainer, entry.runtime_data.skills
    problem = None
    if msg["action"] == "start":
        problem = await trainer.async_start_from_phone(skills, connection.user.id if connection.user else None)
    elif msg["action"] in ("match_on", "match_off"):
        if not connection.user or not connection.user.is_admin:
            connection.send_error(msg["id"], "unauthorized", "Only an administrator can turn voice match on or off.")
            return
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, OPT_VM_ENABLED: msg["action"] == "match_on"})
    else:
        await trainer.async_phone_action(ACTION_SKIP if msg["action"] == "skip" else ACTION_STOP, skills)
    connection.send_result(msg["id"], {"problem": problem})


# ------------------------------------------------------------------ the Recordings tab
def _when(stem: str) -> str | None:
    try:
        return datetime.strptime(stem.split("_")[0], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat()
    except ValueError:
        return None


@websocket_api.websocket_command({vol.Required("type"): "better_assistant/voice/clips",
                                  vol.Optional("limit", default=100): vol.All(int, vol.Range(1, 500))})
@websocket_api.async_response
async def ws_clips(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    from . import voice_match as vmf  # noqa: PLC0415
    root = vmf.voice_dir(hass)

    def read() -> list[tuple[str, str, dict]]:
        return [(vmf.clip_id(w, root), w.parent.parent.name, vmf.read_meta(w)) for w in vmf.list_clips(root)]

    names = _names(hass)
    sats = {st.entity_id: st.name for st in hass.states.async_all("assist_satellite")}
    out = []
    for cid, label, meta in await hass.async_add_executor_job(read):
        if not _may_see(hass, connection.user, meta):
            continue
        match = meta.get("match") or {}
        out.append({
            "id": cid, "label": label, "when": _when(cid.split("~")[-1]),
            "person": meta.get("person"), "name": names.get(meta.get("person"), None),
            "confirmed": meta.get("confirmed"), "transcript": meta.get("transcript"), "prompt": meta.get("prompt"),
            "speaker": sats.get(meta.get("satellite")), "seconds": meta.get("duration_s"),
            "match": {"person": match.get("person"), "name": names.get(match.get("person")),
                      "score": match.get("score")} if match else None,
            "url": async_sign_path(hass, CLIP_URL.format(cid), timedelta(minutes=30),
                                   refresh_token_id=connection.refresh_token_id),
        })
        if len(out) >= msg["limit"]:
            break
    people = [{"person": p, "name": n} for p, n in sorted(names.items(), key=lambda x: x[1])
              if connection.user.is_admin or p == _person_of(hass, connection.user)]
    connection.send_result(msg["id"], {"clips": out, "people": people, "admin": connection.user.is_admin})


@websocket_api.websocket_command({vol.Required("type"): "better_assistant/voice/clip_action",
                                  vol.Required("action"): vol.In(["assign", "delete", "delete_person"]),
                                  vol.Optional("clip"): str, vol.Optional("person"): str})
@websocket_api.async_response
async def ws_clip_action(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """assign a clip to a person (or "other"), delete a clip, or delete everything of one person."""
    from . import voice_match as vmf  # noqa: PLC0415
    entry, user = _entry(hass), connection.user
    root = vmf.voice_dir(hass)
    person = msg.get("person")
    if person and person != vmf.OTHER and person not in _names(hass):
        connection.send_error(msg["id"], "unknown_person", "There's no such person.")
        return
    if person and person != vmf.OTHER and not user.is_admin and person != _person_of(hass, user):
        connection.send_error(msg["id"], "unauthorized", "You can only label recordings as yourself.")
        return

    def act() -> str | None:
        if msg["action"] == "delete_person":
            if not person or person == vmf.OTHER:
                return "Pick a person."
            for w in vmf.list_clips(root):
                if vmf.read_meta(w).get("person") == person:
                    vmf.delete_clip(w)
            return None
        wav = vmf.clip_path(root, msg.get("clip", ""))
        if wav is None:
            return "That recording is gone."
        meta = vmf.read_meta(wav)
        if not _may_see(hass, user, meta):
            return "You can't change that recording."
        if msg["action"] == "delete":
            vmf.delete_clip(wav)
            return None
        if not person:
            return "Pick a person."
        label = wav.parent.parent.name
        new_label = vmf.OTHER if person == vmf.OTHER else (TRAIN if label == TRAIN else TEST)
        meta.update(person=person, confirmed=person)
        vmf.write_meta(wav, meta)
        vmf.move_clip(root, wav, new_label, person)
        return None

    problem = await hass.async_add_executor_job(act)
    if problem:
        connection.send_error(msg["id"], "failed", problem)
        return
    if entry and entry.runtime_data.matcher:
        await entry.runtime_data.matcher.async_rebuild()
    connection.send_result(msg["id"], {})


class VoiceClipView(HomeAssistantView):
    """Plays one recording (signed link from the Recordings tab; same visibility rules)."""
    url = "/api/better_assistant/voice_clip/{clip_id}"
    name = "api:better_assistant:voice_clip"
    requires_auth = True

    async def get(self, request: web.Request, clip_id: str) -> web.StreamResponse:
        from . import voice_match as vmf  # noqa: PLC0415
        hass = request.app["hass"]
        wav = await hass.async_add_executor_job(vmf.clip_path, vmf.voice_dir(hass), clip_id)
        if wav is None:
            return web.Response(status=404)
        meta = await hass.async_add_executor_job(vmf.read_meta, wav)
        if not _may_see(hass, request.get("hass_user"), meta):
            return web.Response(status=403)
        return web.FileResponse(wav, headers={"Content-Type": "audio/wav", "Cache-Control": "no-store"})
