"""Passphrase behaviour inside a real (bare) Home Assistant core: doors, guest mode, the switch bypass,
lockouts, hiding from Assist and restoring exactly. Skipped when Home Assistant isn't installed."""
import types

import pytest

pytest.importorskip("homeassistant")

from homeassistant import bootstrap, config_entries, loader  # noqa: E402
from homeassistant.components.conversation import ConversationInput  # noqa: E402
from homeassistant.components.homeassistant.exposed_entities import (  # noqa: E402
    DATA_EXPOSED_ENTITIES,
    ExposedEntities,
    async_expose_entity,
    async_get_entity_settings,
)
from homeassistant.core import Context, HomeAssistant  # noqa: E402
from homeassistant.helpers import entity_registry as er  # noqa: E402

from custom_components.better_assistant import BetterAssistantRuntimeData  # noqa: E402
from custom_components.better_assistant.core.security import normalize  # noqa: E402
from custom_components.better_assistant.skills import Skills  # noqa: E402
from custom_components.better_assistant.store import BetterAssistantStore  # noqa: E402

SECRET = "purple monkey dishwasher"
GARAGE, LOCK = "cover.garage_door", "lock.front_door"


@pytest.fixture
async def house(tmp_path):
    hass = HomeAssistant(str(tmp_path))
    loader.async_setup(hass)
    hass.config_entries = config_entries.ConfigEntries(hass, {})
    await bootstrap.async_load_base_functionality(hass)
    exposed = ExposedEntities(hass)
    await exposed.async_initialize()
    hass.data[DATA_EXPOSED_ENTITIES] = exposed
    ents = er.async_get(hass)
    ents.async_get_or_create("cover", "demo", "garage", suggested_object_id="garage_door")
    ents.async_get_or_create("lock", "demo", "front", suggested_object_id="front_door")
    hass.states.async_set(GARAGE, "closed", {"friendly_name": "Garage door", "device_class": "garage"})
    hass.states.async_set(LOCK, "locked", {"friendly_name": "Front door"})
    hass.states.async_set("person.owner", "home", {"friendly_name": "Owner", "user_id": "u1"})
    async_expose_entity(hass, "conversation", GARAGE, True)          # explicit; the lock stays on the default
    calls = []

    async def record(call):
        calls.append((call.domain, call.service, dict(call.data)))

    for domain, service in (("cover", "open_cover"), ("cover", "close_cover"), ("lock", "unlock"), ("lock", "lock"),
                            ("notify", "mobile_app_owner")):
        hass.services.async_register(domain, service, record)
    entry = types.SimpleNamespace(entry_id="x", options={}, data={})
    store = BetterAssistantStore(hass, "x")
    await store.async_load()
    store.data["detected"] = {"protected": [LOCK, GARAGE], "satellites": [{"entity_id": "assist_satellite.hall"}],
                              "phones": [{"service": "notify.mobile_app_owner", "person": "person.owner",
                                          "device_id": "d1"}]}
    entry.runtime_data = BetterAssistantRuntimeData(store=store)
    skills = Skills(hass, entry)
    await skills.async_start()
    yield types.SimpleNamespace(hass=hass, skills=skills, entry=entry, calls=calls)
    skills.async_stop()
    await hass.async_stop(force=True)


def ui(text, satellite=None):
    return ConversationInput(text=text, context=Context(user_id="u1"), conversation_id=None,
                             device_id="dev1" if satellite else None, satellite_id=satellite, language="en",
                             agent_id="conversation.x")


async def say(h, text, satellite=None):
    h.skills.followup = False
    if h.skills.has_pending(ui(text, satellite)):
        return await h.skills.answer_pending(text, ui(text, satellite))
    match = h.skills.recognize(text)
    assert match, text
    reply = await h.skills.async_handle(match, text, ui(text, satellite))
    assert normalize(SECRET) not in normalize(reply)                   # never repeated back
    return reply


def configure(h, **security):
    h.entry.options = {"security": {"passphrase": SECRET, "owner": "person.owner", **security}}
    h.skills.apply_door_hiding()


def opened(h):
    return [c for c in h.calls if c[1] in ("open_cover", "unlock")]


def exposure(h, eid):
    return async_get_entity_settings(h.hass, eid).get("conversation", {}).get("should_expose", "default")


async def test_no_passphrase_opens_directly(house):
    assert await say(house, "open the garage door") == "Okay, opening the garage door."
    assert opened(house) and exposure(house, GARAGE) is True


async def test_oneshot_right_and_wrong(house):
    configure(house)
    assert exposure(house, GARAGE) is False and exposure(house, LOCK) is False     # hidden from Assist
    reply = await say(house, "open the garage door, passphrase purple monkey")
    assert reply == "That's not the passphrase, so the garage door stays closed." and not opened(house)
    reply = await say(house, "open the garage door, passphrase Purple-Monkey Dishwasher!")
    assert reply == "Okay, opening the garage door." and opened(house)
    notes = [c[2]["message"] for c in house.calls if c[0] == "notify"]
    assert len(notes) == 2 and all(normalize(SECRET) not in normalize(n) for n in notes)


async def test_satellite_asks_then_checks(house):
    configure(house)
    reply = await say(house, "unlock the front door", "assist_satellite.hall")
    assert reply == "What's the passphrase to open the front door?" and house.skills.followup
    assert await say(house, "", "assist_satellite.hall") == \
        "I didn't catch the passphrase, so the front door stays locked."
    await say(house, "unlock the front door", "assist_satellite.hall")
    assert await say(house, SECRET, "assist_satellite.hall") == "Okay, unlocking the front door."


async def test_app_explains_the_oneshot_form(house):
    configure(house)
    assert await say(house, "open the garage door") == \
        "That needs the passphrase. Say: open the garage door, passphrase, then the words."


async def test_lockout_after_three_misses(house):
    configure(house)
    for _ in range(2):
        await say(house, "open the garage door, passphrase wrong")
    reply = await say(house, "open the garage door, passphrase wrong")
    assert reply.endswith("Voice unlocking is paused for 30 seconds.")
    assert (await say(house, f"open the garage door, passphrase {SECRET}")).startswith("Too many wrong tries")
    assert not opened(house)


async def test_close_and_status_need_no_passphrase(house):
    configure(house)
    assert await say(house, "close the garage door") == "Okay, closing the garage door."
    assert await say(house, "is the front door locked") == "The front door is locked."


async def test_toggle_off_restores_exactly_and_opens_directly(house):
    configure(house)
    configure(house, require_doors=False)
    assert exposure(house, GARAGE) is True                 # its explicit setting is back
    assert exposure(house, LOCK) == "default"              # back on the default, not written as True/False
    assert await say(house, "open the garage door") == "Okay, opening the garage door."


async def test_guest_mode_needs_passphrase_but_the_switch_does_not(house):
    configure(house)
    await house.skills.set_guest(True)
    assert (await say(house, "turn off guest mode")).startswith("That needs the passphrase")
    assert await say(house, "the guests left, passphrase nope") == \
        "That's not the passphrase, so guest mode stays on."
    assert house.skills.guest_on()
    await house.skills.set_guest(False)                    # what the Guest mode switch does
    assert not house.skills.guest_on()
    assert exposure(house, GARAGE) is False                # still hidden: the door passphrase is on


async def test_guest_passphrase_toggle_off(house):
    configure(house, require_guest=False)
    await house.skills.set_guest(True)
    assert await say(house, "turn off guest mode") == "Guest mode is off."


async def test_guest_hiding_without_passphrase_restores_exactly(house):
    await house.skills.set_guest(True)
    assert exposure(house, GARAGE) is False
    await house.skills.set_guest(False)
    assert exposure(house, GARAGE) is True and exposure(house, LOCK) == "default"
