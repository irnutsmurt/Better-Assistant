"""Upgrading from a voice beta inside a bare Home Assistant core: every assistant goes back to its own
speech-to-text, the beta's entities and settings go, and one that can't be fixed gets a notification.
Skipped when Home Assistant isn't installed."""
import types

import pytest

pytest.importorskip("homeassistant")
pytest.importorskip("homeassistant.components.assist_pipeline")

from homeassistant import bootstrap, config_entries, loader  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.helpers import entity_registry as er  # noqa: E402

from custom_components.better_assistant.migrate import async_retire_voice, strip_voice_options  # noqa: E402

WHISPER = "stt.faster_whisper"
CLOUD = "stt.home_assistant_cloud"


@pytest.fixture
async def hass(tmp_path, monkeypatch):
    h = HomeAssistant(str(tmp_path))
    loader.async_setup(h)
    h.config_entries = config_entries.ConfigEntries(h, {})
    await bootstrap.async_load_base_functionality(h)
    from homeassistant.components.assist_pipeline import pipeline as ap

    async def first_pipeline(_hass, collection):
        return await collection.async_create_item(_pipeline("Home Assistant", None))
    monkeypatch.setattr(ap, "_async_create_default_pipeline", first_pipeline)
    await ap.async_setup_pipeline_store(h)
    yield h
    await h.async_stop(force=True)


def _pipeline(name, stt, prefer_local=True):
    return {"conversation_engine": "conversation.better_assistant", "conversation_language": "en", "language": "en",
            "name": name, "stt_engine": stt, "stt_language": "en", "tts_engine": None, "tts_language": None,
            "tts_voice": None, "wake_word_entity": None, "wake_word_id": None, "prefer_local_intents": prefer_local}


async def _setup(hass, engines=(WHISPER, CLOUD)):
    """Our config entry, the beta's leftover entities, and the house's real engines."""
    entry = config_entries.ConfigEntry(
        version=1, minor_version=1, domain="better_assistant", title="Better Assistant", data={}, source="user",
        options={}, unique_id=None, discovery_keys={}, subentries_data=None)
    hass.config_entries._entries[entry.entry_id] = entry
    reg = er.async_get(hass)
    eid = entry.entry_id
    main = reg.async_get_or_create("stt", "better_assistant", f"{eid}_stt", config_entry=entry,
                                   suggested_object_id="better_assistant_speech_to_text").entity_id
    via = reg.async_get_or_create("stt", "better_assistant", f"{eid}_stt_via_{WHISPER}", config_entry=entry,
                                  suggested_object_id="better_assistant_via_faster_whisper").entity_id
    button = reg.async_get_or_create("button", "better_assistant", f"{eid}_start_voice_training",
                                     config_entry=entry).entity_id
    trained = reg.async_get_or_create("sensor", "better_assistant", f"{eid}_voice_training",
                                      config_entry=entry).entity_id
    searches = reg.async_get_or_create("sensor", "better_assistant", f"{eid}_searches_this_month",
                                       config_entry=entry).entity_id
    for engine in engines:
        if engine == WHISPER:
            reg.async_get_or_create("stt", "wyoming", "whisper", suggested_object_id="faster_whisper")
        hass.states.async_set(engine, "unknown")
    from custom_components.better_assistant.store import BetterAssistantStore
    store = BetterAssistantStore(hass, eid)
    await store.async_load()
    entry.runtime_data = types.SimpleNamespace(store=store)
    return entry, store, {"main": main, "via": via, "button": button, "trained": trained, "searches": searches}


async def _make(hass, name, stt, prefer_local=True):
    from homeassistant.components.assist_pipeline import pipeline as ap
    store = hass.data[ap.KEY_ASSIST_PIPELINE].pipeline_store
    return (await store.async_create_item(_pipeline(name, stt, prefer_local))).id


def _get(hass, pid):
    from homeassistant.components import assist_pipeline
    return assist_pipeline.async_get_pipeline(hass, pid)


async def test_every_assistant_goes_back_to_its_own_speech_to_text(hass):
    entry, store, ents = await _setup(hass)
    switched = await _make(hass, "Switched by voice training", ents["main"])     # its original is recorded
    covered = await _make(hass, "Covered by voice match", ents["via"], prefer_local=False)
    guessed = await _make(hass, "No record", ents["main"])                       # the engine it passed to
    untouched = await _make(hass, "Never touched", WHISPER)
    store.data["vm_covered"] = {covered: WHISPER}
    store.data["vt_borrowed"] = {covered: [ents["via"], True]}                   # training cut short
    options = {"voice_training": True, "voice_match": True, "voice_stt_originals": {switched: WHISPER}}

    await async_retire_voice(hass, entry, options)

    assert _get(hass, switched).stt_engine == WHISPER
    assert (_get(hass, covered).stt_engine, _get(hass, covered).prefer_local_intents) == (WHISPER, True)
    assert _get(hass, guessed).stt_engine == CLOUD                                # Cloud first, as the pass-through did
    assert _get(hass, untouched).stt_engine == WHISPER
    reg = er.async_get(hass)
    for gone in ("main", "via", "button", "trained"):
        assert reg.async_get(ents[gone]) is None
    assert reg.async_get(ents["searches"]) is not None                           # not the beta's
    assert "vm_covered" not in store.data and "vt_borrowed" not in store.data


async def test_the_wrapped_engine_is_read_from_the_pass_through_name(hass):
    entry, _store, ents = await _setup(hass)
    pid = await _make(hass, "Living room", ents["via"])                           # nothing recorded at all
    await async_retire_voice(hass, entry, {})
    assert _get(hass, pid).stt_engine == WHISPER


async def test_no_engine_to_go_back_to_leaves_a_notification(hass):
    entry, store, ents = await _setup(hass, engines=())
    pid = await _make(hass, "Kitchen", ents["main"])
    await async_retire_voice(hass, entry, {})
    assert _get(hass, pid).stt_engine == ents["main"]                             # left as it was, for the user
    from homeassistant.components import persistent_notification
    notes = persistent_notification._async_get_or_create_notifications(hass)
    assert any("Kitchen" in n["message"] for n in notes.values())
    assert er.async_get(hass).async_get(ents["main"]) is not None                 # kept until it's fixed


async def test_nothing_to_do_without_a_voice_beta(hass):
    entry, store, ents = await _setup(hass)
    reg = er.async_get(hass)
    for key in ("main", "via", "button", "trained"):
        reg.async_remove(ents[key])
    pid = await _make(hass, "Plain", WHISPER)
    await async_retire_voice(hass, entry, {})
    assert _get(hass, pid).stt_engine == WHISPER and reg.async_get(ents["searches"]) is not None


def test_voice_settings_are_forgotten():
    kept = strip_voice_options({"voice_training": True, "voice_match": True, "voice_stt_originals": {},
                                "voice_stt_engine": "stt.x", "voice_training_phone": True, "snooze_minutes": 5,
                                "voice_pending": {"stt": "x"}})
    assert kept == {"snooze_minutes": 5, "voice_pending": {"stt": "x"}}          # voice setup isn't voice match
