"""The Better Assistant app (sidebar page) inside a bare Home Assistant core: the view it draws, alarms
added, changed, stopped and deleted from it, reminders deleted, and settings (administrators only).
Skipped when Home Assistant isn't installed."""
import asyncio
import types

import pytest

pytest.importorskip("homeassistant")

from homeassistant import bootstrap, config_entries, loader  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402

from custom_components.better_assistant import app_panel  # noqa: E402

SAT = "assist_satellite.kitchen"


@pytest.fixture
async def hass(tmp_path):
    h = HomeAssistant(str(tmp_path))
    loader.async_setup(h)
    h.config_entries = config_entries.ConfigEntries(h, {})
    await bootstrap.async_load_base_functionality(h)
    h.states.async_set("person.rob", "home", {"friendly_name": "Rob", "user_id": "u-rob"})
    h.states.async_set(SAT, "idle", {"friendly_name": "Kitchen speaker"})
    yield h
    await h.async_stop(force=True)


async def app(hass, monkeypatch, options=None, data=None):
    """A loaded-looking entry with real Skills and a real store (nothing scheduled ever rings)."""
    from custom_components.better_assistant.skills import Skills
    from custom_components.better_assistant.store import BetterAssistantStore
    store = BetterAssistantStore(hass, "e")
    await store.async_load()
    entry = types.SimpleNamespace(entry_id="e", options=dict(options or {}), data=dict(data or {}),
                                  runtime_data=types.SimpleNamespace(store=store, matcher=None, trainer=None))
    skills = Skills(hass, entry)
    entry.runtime_data.skills = skills
    monkeypatch.setattr(skills, "_schedule_alarm", lambda key: None)

    def update(e, options):                                   # what async_update_entry does, minus the reload
        e.options = options
    monkeypatch.setattr(hass.config_entries, "async_update_entry", update, raising=False)
    monkeypatch.setattr(app_panel, "_entry", lambda h: entry)
    return entry


class Conn:
    def __init__(self, admin=True):
        self.user = types.SimpleNamespace(id="u-rob" if admin else "u-kid", is_admin=admin)
        self.out, self.err, self.events, self.subscriptions = None, None, [], {}

    def send_result(self, i, r=None): self.out = r if r is not None else {}
    def send_error(self, i, code, text): self.err = (code, text)
    def send_message(self, m): self.events.append(m)
    def async_handle_exception(self, msg, err): self.err = ("exception", repr(err))


async def call(hass, handler, conn, **msg):
    conn.out = conn.err = None
    handler(hass, conn, {"id": 1, **msg})
    for _ in range(100):
        if conn.out is not None or conn.err is not None:
            return conn
        await asyncio.sleep(0.01)
    return conn


async def test_the_view_shows_speakers_problems_and_try_saying(hass, monkeypatch):
    await app(hass, monkeypatch, options={"features": {"tv": False}}, data={})
    view = app_panel.app_view(hass, types.SimpleNamespace(is_admin=True))
    assert view["running"] and view["admin"]
    home = view["home"]
    assert [s["name"] for s in home["speakers"]] == ["Kitchen speaker"]
    assert not home["speakers"][0]["ours"]                          # no Better Assistant pipeline here
    texts = " ".join(a["text"] for a in home["attention"])
    assert "Kitchen speaker uses" in texts and "no Brave Search key" in texts
    assert "What's playing on the TV?" not in home["try"]            # TV switched off
    assert "Set an alarm for 7" in home["try"]
    feats = {f["key"]: f["on"] for f in view["settings"]["features"]}
    assert feats["tv"] is False and feats["music"] is True and feats["night_mode"] is False


async def test_subscribe_sends_the_view_and_again_on_changes(hass, monkeypatch):
    entry = await app(hass, monkeypatch)
    c = Conn()
    app_panel.ws_app_subscribe(hass, c, {"id": 5})
    assert c.events and c.events[-1]["event"]["running"]
    n = len(c.events)
    app_panel.async_app_changed(hass)
    await hass.async_block_till_done()
    assert len(c.events) == n + 1
    c.subscriptions[5]()                                             # unsubscribed: no more
    app_panel.async_app_changed(hass)
    await hass.async_block_till_done()
    assert len(c.events) == n + 1
    assert entry


async def test_add_change_stop_and_delete_an_alarm(hass, monkeypatch):
    entry = await app(hass, monkeypatch)
    skills = entry.runtime_data.skills
    c = Conn(admin=False)                                            # alarms are for everyone
    await call(hass, app_panel.ws_app_alarm, c, action="add", time="06:45", repeat="weekdays", targets=[SAT],
               music="jazz")
    key = c.out["key"]
    alarm = skills._alarms()[key]
    assert (alarm["hour"], alarm["minute"], alarm["repeat"], alarm["music"]) == (6, 45, "weekdays", "jazz")
    assert alarm["person"] == "person.rob" or alarm["person"] is None
    listed = skills.app_alarms()
    assert listed[0]["where"] == "Kitchen speaker" and "weekday" in listed[0]["said"]

    await call(hass, app_panel.ws_app_alarm, c, action="change", key=key, time="07:10", repeat="weekdays")
    alarm = skills._alarms()[key]
    assert (alarm["hour"], alarm["minute"], alarm["music"]) == (7, 10, "jazz")     # music kept

    await call(hass, app_panel.ws_app_alarm, c, action="change", key=key, time="07:10", targets="all", music="tone")
    assert key not in skills._alarms() and skills._alarms()["all"]["music"] == "tone"

    await call(hass, app_panel.ws_app_alarm, c, action="add", time="25:00")
    assert c.err[0] == "invalid_time"
    await call(hass, app_panel.ws_app_alarm, c, action="add", time="08:00", targets=["assist_satellite.nope"])
    assert c.err[0] == "unknown_speaker"

    skills._ringing["all"] = object()
    stopped = []
    monkeypatch.setattr(skills, "_stop_ringing", lambda k: stopped.append(k))
    await call(hass, app_panel.ws_app_alarm, c, action="stop", key="all")
    assert stopped == ["all"]

    await call(hass, app_panel.ws_app_alarm, c, action="delete", key="all")
    assert skills._alarms() == {}
    await call(hass, app_panel.ws_app_alarm, c, action="delete", key="all")
    assert c.err[0] == "not_found"


async def test_delete_a_reminder(hass, monkeypatch):
    entry = await app(hass, monkeypatch)
    store = entry.runtime_data.store
    uid = store.add_item("reminders", "call Mom", description="tomorrow")
    assert [r["summary"] for r in entry.runtime_data.skills.app_reminders()] == ["call Mom"]
    c = Conn(admin=False)
    await call(hass, app_panel.ws_app_item, c, list="reminders", uid=uid)
    assert c.err is None and store.items("reminders") == []
    await call(hass, app_panel.ws_app_item, c, list="reminders", uid=uid)
    assert c.err[0] == "not_found"


async def test_settings_are_for_administrators(hass, monkeypatch):
    entry = await app(hass, monkeypatch, options={"features": {"tv": True}, "snooze_limit": 3})
    c = Conn(admin=False)
    await call(hass, app_panel.ws_app_settings, c, values={"web_search": False})
    assert c.err[0] == "unauthorized" and "web_search" not in entry.options

    c = Conn()
    await call(hass, app_panel.ws_app_settings, c, values={"features": {"music": False}, "monthly_cap": "150",
                                                           "alarm_music": "  my morning playlist ", "snooze_minutes": 9})
    assert c.err is None
    assert entry.options["features"] == {"tv": True, "music": False}               # merged, not replaced
    assert entry.options["monthly_cap"] == 150 and entry.options["alarm_music"] == "my morning playlist"
    assert entry.options["snooze_minutes"] == 9

    await call(hass, app_panel.ws_app_settings, c, values={"snooze_limit": 0})       # 0 = snoozing off
    assert entry.options["snooze_enabled"] is False and entry.options["snooze_limit"] is None
    await call(hass, app_panel.ws_app_settings, c, values={"snooze_enabled": True, "snooze_limit": None})
    assert entry.options["snooze_enabled"] is True and entry.options["snooze_limit"] is None

    await call(hass, app_panel.ws_app_settings, c, values={"alarm_speaker": SAT})
    assert entry.options["alarm_speaker"] == SAT
    await call(hass, app_panel.ws_app_settings, c, values={"alarm_speaker": "assist_satellite.nope"})
    assert c.err[0] == "unknown_speaker"
    await call(hass, app_panel.ws_app_settings, c, values={"max_compound_parts": 9})
    assert c.err[0] == "invalid"
    await call(hass, app_panel.ws_app_settings, c, values={"features": {"not_a_feature": True}})
    assert c.err[0] == "invalid"
    await call(hass, app_panel.ws_app_settings, c, values={"voice_training": False})  # off: More settings only
    assert c.err[0] == "invalid"
    await call(hass, app_panel.ws_app_settings, c, values={"voice_training": True})
    assert entry.options["voice_training"] is True and entry.options["voice_training_phone"] is True


async def test_fix_points_a_speaker_at_better_assistant(hass, monkeypatch):
    await app(hass, monkeypatch)
    from homeassistant.helpers import device_registry as dr, entity_registry as er
    ce = config_entries.ConfigEntry(
        version=1, minor_version=1, domain="esphome", title="x", data={}, source="user", options={},
        unique_id="u", discovery_keys={}, subentries_data=None)
    hass.config_entries._entries[ce.entry_id] = ce
    dev = dr.async_get(hass).async_get_or_create(config_entry_id=ce.entry_id, identifiers={("esphome", "pe")})
    ents = er.async_get(hass)
    sat = ents.async_get_or_create("assist_satellite", "esphome", "sat", device_id=dev.id, config_entry=ce,
                                   suggested_object_id="den").entity_id
    ents.async_get_or_create("select", "esphome", "pipe", device_id=dev.id, config_entry=ce,
                             suggested_object_id="kitchen_assistant")
    hass.states.async_set("select.kitchen_assistant", "preferred",
                          {"options": ["preferred", "Home Assistant", "Better Assistant"]})
    assert app_panel._pipeline_select(hass, sat) == "select.kitchen_assistant"
    pipeline = types.SimpleNamespace(name="Better Assistant", conversation_engine="conversation.better_assistant")
    monkeypatch.setattr(app_panel, "_our_pipeline", lambda h, agent: pipeline)
    picked = []

    async def select_option(call_):
        picked.append(dict(call_.data))
    hass.services.async_register("select", "select_option", select_option)
    c = Conn(admin=False)
    await call(hass, app_panel.ws_app_fix, c, fix="use_ours", satellite=sat)
    assert c.err[0] == "unauthorized" and not picked
    c = Conn()
    await call(hass, app_panel.ws_app_fix, c, fix="use_ours", satellite=sat)
    assert c.err is None
    assert picked == [{"entity_id": "select.kitchen_assistant", "option": "Better Assistant"}]


async def test_not_running(hass, monkeypatch):
    monkeypatch.setattr(app_panel, "_entry", lambda h: None)
    assert app_panel.app_view(hass, None) == {"running": False, "admin": False}
    c = await call(hass, app_panel.ws_app_alarm, Conn(), action="delete", key="x")
    assert c.err[0] == "not_ready"
