"""Device detection on a small fake house: two rooms, a voice satellite, a Music Assistant player,
a TV with a remote, a Frigate person sensor, a phone, a light-ish switch and a Zigbee router LED."""
import pytest

from core.discovery import Device, Entity, Person, Snapshot, classify


@pytest.fixture
def house():
    devices = {d.id: d for d in [
        Device("sat1", area_id="living", name="Voice box", model="Voice PE", manufacturer="Nabu Casa"),
        Device("ma1", area_id="living", name="Living speaker", model="Music Assistant player"),
        Device("tv1", area_id="living", name="Big screen", model="Smart TV", manufacturer="Acme"),
        Device("cam1", area_id="yard", name="Yard cam", model="Frigate camera"),
        Device("phone1", name="Alex Phone", model="Pixel 9", manufacturer="Google", user_id="u1"),
        Device("plug1", area_id="bedroom", name="Corner plug", model="Smart plug"),
        Device("router1", area_id="bedroom", name="Hallway repeater", model="Zigbee Router TS0207"),
        Device("cast1", area_id="living", name="Living TV", model="Chromecast with Google TV", manufacturer="Google"),
        Device("castgrp", name="Everywhere", model="Google Cast Group", manufacturer="Google"),
        Device("castspk", area_id="bedroom", name="Bedroom mini", model="Google Nest Mini", manufacturer="Google"),
        Device("bulb1", area_id="bedroom", name="Ceiling", model="Bulb"),
    ]}
    entities = [
        Entity("assist_satellite.voice_box", platform="esphome", device_id="sat1"),
        Entity("light.voice_box_led_ring", platform="esphome", device_id="sat1"),
        Entity("media_player.voice_box", platform="esphome", device_id="sat1"),
        Entity("media_player.living_speaker", platform="music_assistant", device_id="ma1"),
        Entity("media_player.big_screen", platform="webostv", device_id="tv1", device_class="tv",
               supported_features=2048 | 1),
        Entity("remote.big_screen", platform="webostv", device_id="tv1"),
        Entity("camera.yard", platform="frigate", device_id="cam1"),
        Entity("binary_sensor.yard_person_occupancy", platform="frigate", device_id="cam1", device_class="occupancy"),
        Entity("binary_sensor.bedroom_motion", platform="zha", device_id="plug1", device_class="motion"),
        Entity("device_tracker.alex_phone", platform="mobile_app", device_id="phone1"),
        Entity("sensor.alex_phone_battery_level", platform="mobile_app", device_id="phone1", device_class="battery"),
        Entity("switch.corner_lamp", platform="zha", device_id="plug1", name="Corner lamp"),
        Entity("switch.corner_plug_child_lock", platform="zha", device_id="plug1", name="Child lock",
               entity_category="config"),
        Entity("switch.coffee_maker", platform="zha", device_id="plug1", name="Coffee maker"),
        Entity("light.hallway_repeater_led", platform="zha", device_id="router1"),
        Entity("sensor.ceiling_battery", platform="zha", device_id="bulb1", device_class="battery"),
        Entity("light.ceiling", platform="zha", device_id="bulb1", available=False),
        Entity("media_player.living_tv", platform="cast", device_id="cast1"),
        Entity("media_player.everywhere", platform="cast", device_id="castgrp"),
        Entity("media_player.bedroom_mini", platform="cast", device_id="castspk"),
        Entity("climate.hall", platform="nest", area_id="living"),
        Entity("calendar.holidays", platform="holiday"),
        Entity("calendar.family", platform="google", supported_features=1 | 2),
        Entity("todo.shopping", platform="shopping_list"),
    ]
    return Snapshot(
        entities=entities, devices=devices,
        areas={"living": "Living Room", "bedroom": "Bedroom", "yard": "Back Yard"},
        people=[Person("person.alex", user_id="u1", device_trackers=["device_tracker.alex_phone"]),
                Person("person.sam", user_id="u2")],
        notify_services=["mobile_app_alex_phone"])


def test_satellite_and_here_player(house):
    house.entities.append(Entity("media_player.voice_box_ma", platform="music_assistant", device_id="sat1"))
    d = classify(house)
    assert d["satellites"] == [{"entity_id": "assist_satellite.voice_box", "device_id": "sat1",
                                "area_id": "living", "here_player": "media_player.voice_box_ma",
                                "media_player": "media_player.voice_box", "led": "light.voice_box_led_ring"}]
    assert {"entity_id": "media_player.living_speaker", "area_id": "living"} in d["music_players"]


def test_here_player_falls_back_to_same_area(house):
    assert classify(house)["satellites"][0]["here_player"] == "media_player.living_speaker"
    house.devices["ma1"].area_id = "bedroom"
    assert classify(house)["satellites"][0]["here_player"] is None


def test_tv_with_remote_and_inputs(house):
    tvs = classify(house)["tvs"]
    assert tvs == [{"entity_id": "media_player.big_screen", "area_id": "living",
                    "remote": "remote.big_screen", "inputs": True}]


def test_cast_groups_and_tv_targets(house):
    d = classify(house)
    assert d["broadcast_targets"] == ["media_player.everywhere"]
    assert d["camera_cast_targets"] == ["media_player.living_tv"]
    house.entities = [e for e in house.entities if e.entity_id != "media_player.everywhere"]
    assert classify(house)["broadcast_targets"] == ["media_player.bedroom_mini"]   # no group: all speakers


def test_outside_prefers_frigate_and_skips_indoor(house):
    out = classify(house)["outside_sensors"]
    assert out == [{"entity_id": "binary_sensor.yard_person_occupancy", "group": "yard", "area_id": "yard"}]
    house.entities = [e for e in house.entities if e.platform != "frigate"]
    assert classify(house)["outside_sensors"] == []                # bedroom motion is indoors


def test_phone_mapped_to_person(house):
    assert classify(house)["phones"] == [
        {"service": "notify.mobile_app_alex_phone", "device_id": "phone1", "person": "person.alex"}]


def test_phone_falls_back_to_user(house):
    house.people[0].device_trackers = []
    assert classify(house)["phones"][0]["person"] == "person.alex"


def test_lights_exclude_router_led_ring_and_config(house):
    lights = {l["entity_id"] for l in classify(house)["lights"]}
    assert lights == {"switch.corner_lamp", "light.ceiling"}


def test_rooms(house):
    rooms = classify(house)["rooms"]
    assert rooms["bedroom"]["lights"] == ["switch.corner_lamp", "light.ceiling"]
    assert rooms["bedroom"]["fans"] == []
    assert "media_player.voice_box" not in rooms["living"]["media_players"]          # satellite's own player
    assert "media_player.everywhere" not in sum((r["media_players"] for r in rooms.values()), [])
    assert "yard" not in rooms


def test_misc(house):
    d = classify(house)
    assert d["thermostats"] == [{"entity_id": "climate.hall", "area_id": "living"}]
    assert d["calendars"] == ["calendar.holidays", "calendar.family"]
    assert d["write_calendar"] == "calendar.family"
    assert d["todo_lists"] == ["todo.shopping"]
    assert d["people"] == ["person.alex", "person.sam"]
    assert d["cameras"] == ["camera.yard"]
    assert {b["entity_id"]: b["personal"] for b in d["batteries"]} == {
        "sensor.alex_phone_battery_level": True, "sensor.ceiling_battery": False}
    assert d["unavailable"] == {"bulb1": ["light.ceiling"]}
    assert {k: d["bed"][k] for k in ("firmness", "presets", "presence")} == {"firmness": [], "presets": [], "presence": []}


def test_sleepiq_bed(house):
    house.entities += [Entity("number.bed_left_firmness", platform="sleepiq"),
                       Entity("select.bed_foundation_preset", platform="sleepiq"),
                       Entity("binary_sensor.bed_left_is_in_bed", platform="sleepiq")]
    bed = classify(house)["bed"]
    assert {k: bed[k] for k in ("firmness", "presets", "presence")} == {
        "firmness": ["number.bed_left_firmness"], "presets": ["select.bed_foundation_preset"],
        "presence": ["binary_sensor.bed_left_is_in_bed"]}


def test_outdoor_areas_guess_and_override(house):
    assert classify(house)["outdoor_areas"] == ["yard"]
    house.entities = [e for e in house.entities if e.platform != "frigate"]
    d = classify(house, outdoor_areas=["bedroom"])                 # user says the bedroom counts
    assert d["outdoor_areas"] == ["bedroom"]
    assert [s["entity_id"] for s in d["outside_sensors"]] == ["binary_sensor.bedroom_motion"]


def test_rooms_take_plugs_and_fans_but_never_network_gear(house):
    house.entities += [
        Entity("switch.tv_plug", platform="zha", device_id="plug1", name="TV plug", device_class="outlet"),
        Entity("switch.router_plug", platform="zha", device_id="plug1", name="Router plug", device_class="outlet"),
        Entity("fan.bedroom_fan", platform="zha", device_id="plug1", name="Bedroom fan"),
        Entity("fan.living_fan", platform="tuya", area_id="living", name="Ceiling fan"),
        Entity("fan.fan_child_lock", platform="zha", device_id="plug1", name="Child lock", entity_category="config"),
        Entity("fan.rack_fan", platform="zha", area_id="bedroom", name="Network rack fan"),
    ]
    d = classify(house)
    lights = {l["entity_id"] for l in d["lights"]}
    assert "switch.tv_plug" in lights
    assert "switch.router_plug" not in lights and "switch.coffee_maker" not in lights
    assert d["rooms"]["bedroom"]["fans"] == ["fan.bedroom_fan"]           # device area; not the config or rack fan
    assert d["rooms"]["living"]["fans"] == ["fan.living_fan"]             # entity area


def test_health_false_positives_regression(house):
    """A working light group, a working helper switch, our own entities and leftovers are never
    'offline'; a device counts only when all of its actionable entities are down."""
    house.devices["pihole"] = Device("pihole", name="Pi-hole")
    house.devices["cast9"] = Device("cast9", name="Den Chromecast")
    house.devices["board"] = Device("board", name="rtl_433 board")
    house.devices["ours"] = Device("ours", name="Brave Search API")
    house.entities += [
        Entity("light.lounge_lamps", platform="group", name="Lounge lamps"),                      # group helper, on
        Entity("switch.pihole_blocking_both", platform="template", name="Pi-hole blocking (both)"),
        Entity("switch.pihole_blocking_a", platform="pi_hole", device_id="pihole", available=False),
        Entity("switch.pihole_blocking_b", platform="pi_hole", device_id="pihole"),               # still up
        Entity("media_player.den_chromecast", platform="cast", device_id="cast9", available=False),
        Entity("switch.board_relay", platform="mqtt", device_id="board", available=False),
        Entity("switch.better_assistant_night_mode", platform="better_assistant", device_id="ours",
               available=False, restored=True),
        Entity("switch.old_thing", platform="zha", available=False, restored=True),
        Entity("light.hidden_lamp", platform="zha", available=False, hidden=True),
    ]
    d = classify(house)
    assert set(d["unavailable"]) == {"bulb1", "cast9", "board"}
    assert d["unavailable_names"]["cast9"] == "Den Chromecast"
    assert d["unavailable_names"]["board"] == "rtl_433 board"


def test_sleepiq_sleepers(house):
    house.people.append(Person("person.robin_example", name="Robin Example"))
    bed = "sleepnumber_testbed"
    for eid in [f"sensor.{bed}_robin_sleep_score", f"sensor.{bed}_robin_sleep_duration",
                f"sensor.{bed}_robin_heart_rate_average", f"sensor.{bed}_robin_sleepnumber",
                f"number.{bed}_robin_firmness", f"number.{bed}_left_head_position",
                f"select.{bed}_foundation_preset_left", f"select.{bed}_foundation_preset_right",
                f"binary_sensor.{bed}_robin_is_in_bed", f"sensor.{bed}_casey_sleep_score"]:
        house.entities.append(Entity(eid, platform="sleepiq"))
    b = classify(house)["bed"]
    assert b["sleepers"]["person.robin_example"] == {
        "score": f"sensor.{bed}_robin_sleep_score", "duration": f"sensor.{bed}_robin_sleep_duration",
        "heart_rate": f"sensor.{bed}_robin_heart_rate_average", "sleep_number": f"sensor.{bed}_robin_sleepnumber",
        "firmness": f"number.{bed}_robin_firmness", "in_bed": f"binary_sensor.{bed}_robin_is_in_bed"}
    assert "person.casey" not in b["sleepers"]                     # no such person in the house
    assert b["sleepers"]["name:casey"] == {"score": f"sensor.{bed}_casey_sleep_score"}   # kept for a side pick
    assert b["sides"]["left"] == {"actuators": [f"number.{bed}_left_head_position"],
                                  "presets": [f"select.{bed}_foundation_preset_left"]}
    assert b["sides"]["right"]["presets"] == [f"select.{bed}_foundation_preset_right"]
    assert f"number.{bed}_robin_firmness" in b["firmness"] and f"number.{bed}_left_head_position" in b["actuators"]


def test_sleepiq_kind_prefers_translation_key(house):
    house.people.append(Person("person.robin_example", name="Robin Example"))
    house.entities.append(Entity("sensor.sleepnumber_testbed_robin_score_2", platform="sleepiq",
                                 translation_key="sleep_score", unique_id="abc_robin_sleep_score"))
    assert classify(house)["bed"]["sleepers"]["person.robin_example"]["score"] == \
        "sensor.sleepnumber_testbed_robin_score_2"


def test_phone_before_watch_with_the_same_login(house):
    # a watch signed in as the same user, found first: the phone still wins
    house.devices = {"watch1": Device("watch1", name="Pixel Watch 4", model="Pixel Watch 4", user_id="u1"),
                          **house.devices}
    house.entities.append(Entity("sensor.watch_battery", platform="mobile_app", device_id="watch1"))
    house.notify_services.append("mobile_app_pixel_watch_4")
    phones = classify(house)["phones"]
    assert [p["service"] for p in phones] == ["notify.mobile_app_alex_phone", "notify.mobile_app_pixel_watch_4"]
    assert all(p["person"] == "person.alex" for p in phones)
