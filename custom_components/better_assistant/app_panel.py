"""The Better Assistant app in the sidebar: Home (what's set up and what needs fixing), Alarms &
reminders, and Settings.

Websocket commands:
  better_assistant/app/subscribe  -> the whole app view now and after every change
  better_assistant/app/alarm      -> add / change / delete / stop an alarm (anyone in the household)
  better_assistant/app/item       -> delete a reminder, note or message (anyone)
  better_assistant/app/settings   -> change options (administrators)
  better_assistant/app/fix        -> one-tap fixes from Home (administrators)
Option changes that aren't read live reload the integration; the page keeps its subscription because
updates go through a dispatcher signal sent again once Better Assistant is back."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.components import frontend, panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send

from .const import (
    CONF_API_KEY, DEFAULTS, DOMAIN, FEATURE_DEFAULT_OFF, FEATURE_SECTIONS, OPT_ALARM_MUSIC, OPT_ALARM_SPEAKER,
    OPT_COMPOUND, OPT_FEATURES, OPT_MAX_PARTS, OPT_MONTHLY_CAP, OPT_QUESTION_GUARD, OPT_SNOOZE,
    OPT_SNOOZE_ENABLED, OPT_SNOOZE_LIMIT, OPT_SPEAK_SOURCE, OPT_WEB_SEARCH,
)

PANEL_PATH = "better-assistant"
PANEL_URL = "/better_assistant/app-panel.js"
PANEL_ELEMENT = "better-assistant-app"
PANEL_FILE = Path(__file__).parent / "www" / "app-panel.js"
SIGNAL_APP = f"{DOMAIN}_app_changed"
REPEATS = ["once", "daily", "weekdays", "weekends"]

FEATURE_NAMES = {
    "music": ("Music", "Play music through Music Assistant"),
    "calendar": ("Calendar", "Read and add calendar events"),
    "rooms_lights": ("Rooms & lights", "Turn rooms and lights on and off"),
    "thermostat": ("Thermostat", "Warmer, cooler, heat and cooling"),
    "cameras_outside": ("Cameras & outside", "Who's outside, and cameras on a TV"),
    "tv": ("TV", "What's on, inputs and apps"),
    "bed": ("Bed", "Sleep Number bed positions and sleep"),
    "health": ("Health report", "Offline devices and low batteries"),
    "guest_mode": ("Guest mode", "Keep private things private for visitors"),
    "night_mode": ("Night mode", "Quieter speakers and dimmer lights at night"),
    "broadcast": ("Broadcast", "Announce something on every speaker"),
}
TRY = {                                   # feature -> things to try saying (None = always)
    None: ["Set an alarm for 7", "Remind me to take out the trash at 8", "Take a note that the wifi password is on the fridge",
           "What can you do?"],
    "music": ["Play jazz in the kitchen"],
    "calendar": ["What's on my calendar tomorrow?"],
    "rooms_lights": ["What lights are on?", "Turn off the living room"],
    "thermostat": ["Make it 2 degrees warmer"],
    "tv": ["What's playing on the TV?"],
    "cameras_outside": ["Is anyone outside?"],
    "health": ["Is anything wrong?"],
    "broadcast": ["Tell everyone that dinner's ready"],
}


def _entry(hass: HomeAssistant):
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        if entry.runtime_data.skills:
            return entry
    return None


@callback
def async_app_changed(hass: HomeAssistant) -> None:
    """Tell open app pages to redraw."""
    async_dispatcher_send(hass, SIGNAL_APP)


async def async_setup_panel(hass: HomeAssistant) -> None:
    """Serve the page, register the commands once per run and add "Better Assistant" to the sidebar.
    The page stays registered across reloads (a settings change reloads the integration)."""
    if not hass.data.get(f"{DOMAIN}_app_panel"):
        hass.data[f"{DOMAIN}_app_panel"] = True
        await hass.http.async_register_static_paths([StaticPathConfig(PANEL_URL, str(PANEL_FILE), False)])
        for command in (ws_app_subscribe, ws_app_alarm, ws_app_item, ws_app_settings, ws_app_fix):
            websocket_api.async_register_command(hass, command)
    if PANEL_PATH not in hass.data.get(frontend.DATA_PANELS, {}):
        # a new address whenever the script changes, so the app never keeps an old copy
        digest = await hass.async_add_executor_job(lambda: hashlib.sha256(PANEL_FILE.read_bytes()).hexdigest()[:12])
        await panel_custom.async_register_panel(
            hass, frontend_url_path=PANEL_PATH, webcomponent_name=PANEL_ELEMENT, module_url=f"{PANEL_URL}?v={digest}",
            sidebar_title="Better Assistant", sidebar_icon="mdi:account-voice", require_admin=False,
            embed_iframe=False)
    async_app_changed(hass)


@callback
def async_remove_panel(hass: HomeAssistant) -> None:
    if PANEL_PATH in hass.data.get(frontend.DATA_PANELS, {}):
        frontend.async_remove_panel(hass, PANEL_PATH)


# ------------------------------------------------------------------ the view
def _opt(entry, key: str) -> Any:
    return entry.options.get(key, DEFAULTS.get(key))


def _person_of(hass: HomeAssistant, user) -> str | None:
    return next((st.entity_id for st in hass.states.async_all("person")
                 if user and st.attributes.get("user_id") == user.id), None)


def _pipelines(hass: HomeAssistant) -> list:
    try:
        from homeassistant.components import assist_pipeline  # noqa: PLC0415
        return list(assist_pipeline.async_get_pipelines(hass))
    except Exception:  # noqa: BLE001 - assist_pipeline not loaded
        return []


def _preferred(hass: HomeAssistant):
    try:
        from homeassistant.components import assist_pipeline  # noqa: PLC0415
        return assist_pipeline.async_get_pipeline(hass)
    except Exception:  # noqa: BLE001
        return None


def _pipeline_select(hass: HomeAssistant, satellite: str) -> str | None:
    """The speaker's "Assistant" select (its options are "preferred" plus every pipeline name)."""
    ents = er.async_get(hass)
    reg = ents.async_get(satellite)
    if not reg or not reg.device_id:
        return None
    for e in er.async_entries_for_device(ents, reg.device_id):
        st = hass.states.get(e.entity_id) if e.domain == "select" else None
        if st and "preferred" in (st.attributes.get("options") or []):
            return e.entity_id
    return None


def _our_pipeline(hass: HomeAssistant, agent: str | None):
    from .core.voice import PIPELINE_NAME  # noqa: PLC0415
    ours = [p for p in _pipelines(hass) if agent and p.conversation_engine == agent]
    return next((p for p in ours if p.name == PIPELINE_NAME), ours[0] if ours else None)


def _speakers(hass: HomeAssistant, entry, agent: str | None) -> list[dict[str, Any]]:
    skills = entry.runtime_data.skills
    out = []
    for info in skills.speakers_info():
        sat = info["entity_id"]
        select = _pipeline_select(hass, sat)
        chosen = hass.states.get(select).state if select and hass.states.get(select) else None
        if chosen == "preferred" or chosen is None:
            pipeline = _preferred(hass)
        else:
            pipeline = next((p for p in _pipelines(hass) if p.name == chosen), None)
        st = hass.states.get(sat)
        out.append({"entity_id": sat, "name": info["name"], "area": info["area"],
                    "online": bool(st and st.state not in ("unavailable", "unknown")),
                    "pipeline": pipeline.name if pipeline else None,
                    "ours": bool(pipeline and agent and pipeline.conversation_engine == agent),
                    "can_fix": bool(select)})
    return out


def _try(entry) -> list[str]:
    skills = entry.runtime_data.skills
    out = list(TRY[None][:2])
    for feature, phrases in TRY.items():
        if feature and skills.feature_on(feature):
            out += phrases
    if _opt(entry, OPT_WEB_SEARCH) and entry.data.get(CONF_API_KEY):
        out.append("How tall is Mount Everest?")
    return out + TRY[None][2:]


def app_view(hass: HomeAssistant, user) -> dict[str, Any]:
    entry = _entry(hass)
    admin = bool(user and user.is_admin)
    if entry is None:
        return {"running": False, "admin": admin}
    from .discovery import effective_section  # noqa: PLC0415
    from .voice_setup import our_agent  # noqa: PLC0415
    data = entry.runtime_data
    skills, store = data.skills, data.store
    agent = our_agent(hass, entry.entry_id)
    speakers = _speakers(hass, entry, agent)
    calendars = [hass.states.get(c).name if hass.states.get(c) else c
                 for c in effective_section(dict(entry.options), store.detected, "calendar").get("calendars") or []]
    has_key = bool(entry.data.get(CONF_API_KEY))
    web_on = bool(_opt(entry, OPT_WEB_SEARCH))
    cap = int(_opt(entry, OPT_MONTHLY_CAP))
    music = skills._ma_ready()

    attention: list[dict[str, Any]] = []
    if not speakers:
        attention.append({"text": "No voice speakers found yet. Add one (like a Home Assistant Voice PE), "
                                  "and Better Assistant finds it on its own.", "link": "/config/integrations/dashboard"})
    for sp in speakers:
        if not sp["ours"]:
            fix = {"fix": "use_ours", "satellite": sp["entity_id"]} if sp["can_fix"] and _our_pipeline(hass, agent) \
                else None
            attention.append({"text": f"{sp['name']} uses the \"{sp['pipeline'] or 'default'}\" assistant, "
                                      "so it can't do Better Assistant's skills.",
                              "fix": fix, "fix_label": "Use Better Assistant",
                              "link": None if fix else "/config/voice-assistants/assistants"})
        elif not sp["online"]:
            attention.append({"text": f"{sp['name']} is offline.", "link": "/config/devices/dashboard"})
    if web_on and not has_key:
        attention.append({"text": "Web answers are on but there's no Brave Search key, so general questions "
                                  "can't be answered.",
                          "link": "/config/integrations/integration/better_assistant"})
    elif web_on and store.count >= cap:
        attention.append({"text": f"This month's {cap} web searches are used up. They start again next month.",
                          "goto": "settings"})

    feats = (entry.options.get(OPT_FEATURES) or {})
    snooze_limit = entry.options.get(OPT_SNOOZE_LIMIT)
    return {
        "running": True, "admin": admin,
        "home": {
            "speakers": speakers, "attention": attention, "music": music, "calendars": calendars,
            "search": {"on": web_on, "key": has_key, "count": store.count, "cap": cap},
            "try": _try(entry),
        },
        "alarms": skills.app_alarms(),
        "alarm_settings": {
            "snooze": int(_opt(entry, OPT_SNOOZE)), "snooze_enabled": bool(_opt(entry, OPT_SNOOZE_ENABLED)),
            "snooze_limit": snooze_limit, "speaker": entry.options.get(OPT_ALARM_SPEAKER) or "",
            "music": entry.options.get(OPT_ALARM_MUSIC) or "", "music_ready": music,
        },
        "speakers": [{"value": s["entity_id"], "label": s["name"]} for s in speakers],
        "sounds": _sounds(hass, entry),
        "reminders": skills.app_reminders(),
        "notes": [{"uid": i["uid"], "summary": i["summary"]} for i in store.items("notes") if i["status"] == "needs_action"],
        "messages": [{"uid": i["uid"], "summary": i["summary"]} for i in store.items("messages")
                     if i["status"] == "needs_action"],
        "settings": {
            "features": [{"key": f, "name": FEATURE_NAMES[f][0], "about": FEATURE_NAMES[f][1],
                          "on": bool(feats.get(f, f not in FEATURE_DEFAULT_OFF))} for f in FEATURE_SECTIONS],
            OPT_WEB_SEARCH: web_on, OPT_MONTHLY_CAP: cap, OPT_SPEAK_SOURCE: bool(_opt(entry, OPT_SPEAK_SOURCE)),
            OPT_QUESTION_GUARD: bool(_opt(entry, OPT_QUESTION_GUARD)), OPT_COMPOUND: bool(_opt(entry, OPT_COMPOUND)),
            OPT_MAX_PARTS: int(_opt(entry, OPT_MAX_PARTS)), "has_key": has_key,
        },
    }


# ------------------------------------------------------------------ commands
@websocket_api.websocket_command({vol.Required("type"): "better_assistant/app/subscribe"})
@callback
def ws_app_subscribe(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    @callback
    def send() -> None:
        connection.send_message(websocket_api.event_message(msg["id"], app_view(hass, connection.user)))

    connection.subscriptions[msg["id"]] = async_dispatcher_connect(hass, SIGNAL_APP, send)
    connection.send_result(msg["id"])
    send()
    hass.async_create_task(_async_refresh_sounds(hass))       # the library may have changed since


async def _async_refresh_sounds(hass: HomeAssistant) -> None:
    """Read the Music Assistant library for the alarm sound drop-down, then update open pages."""
    from .alarm_sounds import async_choices  # noqa: PLC0415
    entry = _entry(hass)
    if entry is None:
        return
    choices = await async_choices(hass, entry.options.get(OPT_ALARM_MUSIC) or "")
    if choices != hass.data.get(f"{DOMAIN}_sounds"):
        hass.data[f"{DOMAIN}_sounds"] = choices
        async_dispatcher_send(hass, SIGNAL_APP)


def _sounds(hass: HomeAssistant, entry) -> list[dict[str, str]]:
    """The alarm sound choices last read from the library, always with the current setting in them."""
    from .alarm_sounds import label  # noqa: PLC0415
    choices = list(hass.data.get(f"{DOMAIN}_sounds") or [{"value": "", "label": label("")}])
    current = entry.options.get(OPT_ALARM_MUSIC) or ""
    if current and all(c["value"] != current for c in choices):
        choices.append({"value": current, "label": label(current)})
    return choices


def _not_running(connection, msg) -> None:
    connection.send_error(msg["id"], "not_ready", "Better Assistant isn't running.")


def _admin_only(connection, msg) -> bool:
    if connection.user and connection.user.is_admin:
        return False
    connection.send_error(msg["id"], "unauthorized", "Only an administrator can change this.")
    return True


def _hhmm(value: str) -> tuple[int, int]:
    hour, minute = (int(x) for x in str(value).split(":")[:2])
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise vol.Invalid("bad time")
    return hour, minute


@websocket_api.websocket_command({
    vol.Required("type"): "better_assistant/app/alarm",
    vol.Required("action"): vol.In(["add", "change", "delete", "stop"]),
    vol.Optional("key"): str,
    vol.Optional("time"): str,                               # "07:30"
    vol.Optional("repeat"): vol.In(REPEATS),
    vol.Optional("targets"): vol.Any("all", [str]),          # "all" or satellite ids
    vol.Optional("music"): vol.Any(None, str),                # None / "" = the wake-up music setting, "tone", or a request
})
@callback
def ws_app_alarm(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Alarms are household things: anyone signed in may manage them, like by voice."""
    entry = _entry(hass)
    if entry is None:
        return _not_running(connection, msg)
    skills = entry.runtime_data.skills
    action, key = msg["action"], msg.get("key")
    if action in ("change", "delete", "stop") and key not in skills._alarms() and \
            not (action == "stop" and (key in skills._ringing or f"snooze:{key}" in skills._timers)):
        return connection.send_error(msg["id"], "not_found", "That alarm is gone.")
    if action == "delete":
        skills.delete_alarm(key)
        return connection.send_result(msg["id"], {})
    if action == "stop":
        skills.app_stop_alarm(key)
        return connection.send_result(msg["id"], {})
    try:
        hour, minute = _hhmm(msg.get("time", ""))
    except (ValueError, vol.Invalid):
        return connection.send_error(msg["id"], "invalid_time", "Pick a time.")
    old = skills._alarms().get(key) if action == "change" else None
    targets = msg.get("targets") or (old["targets"] if old else None)
    if not targets:
        targets = [s["entity_id"] for s in skills.speakers_info()[:1]] or "all"
    known = {s["entity_id"] for s in skills.speakers_info()}
    if targets != "all":
        targets = sorted({t for t in targets if t in known})
        if not targets:
            return connection.send_error(msg["id"], "unknown_speaker", "Pick a speaker.")
    music = msg["music"] if "music" in msg else (old.get("music") if old else None)
    repeat = msg.get("repeat") or (old["repeat"] if old else "once")
    new = skills.app_set_alarm(targets, hour, minute, repeat, (music or "").strip() or None,
                               _person_of(hass, connection.user), old_key=key if old else None)
    connection.send_result(msg["id"], {"key": new})


@websocket_api.websocket_command({
    vol.Required("type"): "better_assistant/app/item",
    vol.Required("list"): vol.In(["reminders", "notes", "messages"]),
    vol.Required("uid"): str,
})
@callback
def ws_app_item(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    entry = _entry(hass)
    if entry is None:
        return _not_running(connection, msg)
    store = entry.runtime_data.store
    if not store.find(msg["list"], msg["uid"]):
        return connection.send_error(msg["id"], "not_found", "It's already gone.")
    store.remove_items(msg["list"], [msg["uid"]])            # a reminder's schedule goes with it
    connection.send_result(msg["id"], {})


SETTINGS_SCHEMA = vol.Schema({
    vol.Optional(OPT_FEATURES): {vol.In(FEATURE_SECTIONS): bool},
    vol.Optional(OPT_WEB_SEARCH): bool,
    vol.Optional(OPT_MONTHLY_CAP): vol.All(vol.Coerce(int), vol.Range(0, 100000)),
    vol.Optional(OPT_SPEAK_SOURCE): bool,
    vol.Optional(OPT_QUESTION_GUARD): bool,
    vol.Optional(OPT_COMPOUND): bool,
    vol.Optional(OPT_MAX_PARTS): vol.All(vol.Coerce(int), vol.Range(2, 4)),
    vol.Optional(OPT_SNOOZE): vol.All(vol.Coerce(int), vol.Range(1, 30)),
    vol.Optional(OPT_SNOOZE_ENABLED): bool,
    vol.Optional(OPT_SNOOZE_LIMIT): vol.Any(None, vol.All(vol.Coerce(int), vol.Range(0, 10))),
    vol.Optional(OPT_ALARM_SPEAKER): vol.Any(None, str),
    vol.Optional(OPT_ALARM_MUSIC): vol.All(str, vol.Length(max=500)),
})


@websocket_api.websocket_command({vol.Required("type"): "better_assistant/app/settings",
                                  vol.Required("values"): dict})
@callback
def ws_app_settings(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    entry = _entry(hass)
    if entry is None:
        return _not_running(connection, msg)
    if _admin_only(connection, msg):
        return None
    try:
        values = SETTINGS_SCHEMA(msg["values"])
    except vol.Invalid as err:
        return connection.send_error(msg["id"], "invalid", str(err))
    options = dict(entry.options)
    if OPT_FEATURES in values:
        options[OPT_FEATURES] = {**(options.get(OPT_FEATURES) or {}), **values.pop(OPT_FEATURES)}
    if OPT_ALARM_SPEAKER in values:
        speaker = values.pop(OPT_ALARM_SPEAKER) or None
        if speaker not in (None, "all") and speaker not in {s["entity_id"] for s in
                                                           entry.runtime_data.skills.speakers_info()}:
            return connection.send_error(msg["id"], "unknown_speaker", "That speaker isn't known.")
        options[OPT_ALARM_SPEAKER] = speaker
    if OPT_SNOOZE_ENABLED in values or OPT_SNOOZE_LIMIT in values:
        from .core.features import snooze_from_page  # noqa: PLC0415 - 0 means snoozing off, like the options page
        enabled, limit = snooze_from_page(values.pop(OPT_SNOOZE_ENABLED, _opt(entry, OPT_SNOOZE_ENABLED)),
                                          values.pop(OPT_SNOOZE_LIMIT, options.get(OPT_SNOOZE_LIMIT)))
        options.update({OPT_SNOOZE_ENABLED: enabled, OPT_SNOOZE_LIMIT: limit})
    if OPT_ALARM_MUSIC in values:
        values[OPT_ALARM_MUSIC] = values[OPT_ALARM_MUSIC].strip()
    options.update(values)
    hass.config_entries.async_update_entry(entry, options=options)
    async_app_changed(hass)                                   # live options: no reload to send it
    connection.send_result(msg["id"], {})


@websocket_api.websocket_command({vol.Required("type"): "better_assistant/app/fix",
                                  vol.Required("fix"): vol.In(["use_ours"]),
                                  vol.Required("satellite"): str})
@websocket_api.async_response
async def ws_app_fix(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """"Use Better Assistant" on a speaker: pick our assistant in its Assistant select."""
    entry = _entry(hass)
    if entry is None:
        return _not_running(connection, msg)
    if _admin_only(connection, msg):
        return None
    from .voice_setup import our_agent  # noqa: PLC0415
    select = _pipeline_select(hass, msg["satellite"])
    pipeline = _our_pipeline(hass, our_agent(hass, entry.entry_id))
    if not select or not pipeline:
        return connection.send_error(msg["id"], "cant_fix", "Set this one up in Settings > Voice assistants.")
    await hass.services.async_call("select", "select_option", {"entity_id": select, "option": pipeline.name},
                                   blocking=True)
    async_app_changed(hass)
    connection.send_result(msg["id"], {})
