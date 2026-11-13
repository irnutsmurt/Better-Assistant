"""Detection runs when the integration is added to a running Home Assistant, after start-up otherwise,
and again after registry changes. Skipped when Home Assistant isn't installed."""
import asyncio
import types

import pytest

pytest.importorskip("homeassistant")

from homeassistant import bootstrap, config_entries, loader  # noqa: E402
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED  # noqa: E402
from homeassistant.core import CoreState, HomeAssistant  # noqa: E402
from homeassistant.helpers import entity_registry as er  # noqa: E402

from custom_components.better_assistant.autodetect import AutoDetect  # noqa: E402
from custom_components.better_assistant.store import BetterAssistantStore  # noqa: E402


@pytest.fixture
async def hass(tmp_path):
    h = HomeAssistant(str(tmp_path))
    loader.async_setup(h)
    h.config_entries = config_entries.ConfigEntries(h, {})
    await bootstrap.async_load_base_functionality(h)
    h.states.async_set("person.robin", "home", {"friendly_name": "Robin"})
    yield h
    await h.async_stop(force=True)


async def make(hass, cooldown=0.05):
    store = BetterAssistantStore(hass, "x")
    await store.async_load()
    calls = []
    auto = AutoDetect(hass, types.SimpleNamespace(options={}), store, on_change=lambda: calls.append(1),
                      cooldown=cooldown)
    return store, auto, calls


async def test_runs_now_when_added_to_a_running_home_assistant(hass):
    hass.set_state(CoreState.running)
    store, auto, calls = await make(hass)
    await auto.async_start()
    assert store.detected.get("people") == ["person.robin"] and calls == [1]
    auto.async_stop()


async def test_waits_for_start_up_otherwise(hass):
    hass.set_state(CoreState.starting)
    store, auto, calls = await make(hass)
    await auto.async_start()
    assert not store.detected
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()
    assert store.detected.get("people") == ["person.robin"]
    auto.async_stop()


async def test_registry_changes_redetect_but_exposure_changes_do_not(hass):
    hass.set_state(CoreState.running)
    store, auto, calls = await make(hass)
    await auto.async_start()
    ents = er.async_get(hass)
    entry = ents.async_get_or_create("light", "demo", "lamp1", suggested_object_id="desk_lamp")
    hass.states.async_set("light.desk_lamp", "on", {"friendly_name": "Desk lamp"})
    await asyncio.sleep(0.2)
    await hass.async_block_till_done()
    assert "light.desk_lamp" in {l["entity_id"] for l in store.detected["lights"]}
    before = len(calls)
    ents.async_update_entity_options(entry.entity_id, "conversation", {"should_expose": False})
    await asyncio.sleep(0.2)
    await hass.async_block_till_done()
    assert len(calls) == before                      # Assist exposure only: no re-detect
    auto.async_stop()
