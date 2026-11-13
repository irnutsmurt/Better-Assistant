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
                                "area_id": "living", "here_player": "media_player.voice_box_ma"}]
    assert {"entity_id": "media_player.living_speaker", "area_id": "living"} in d["music_players"]


def test_no_here_player_without_shared_device(house):
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
    assert d["bed"] == {"firmness": [], "presets": [], "presence": []}


def test_sleepiq_bed(house):
    house.entities += [Entity("number.bed_left_firmness", platform="sleepiq"),
                       Entity("select.bed_foundation_preset", platform="sleepiq"),
                       Entity("binary_sensor.bed_left_is_in_bed", platform="sleepiq")]
    assert classify(house)["bed"] == {"firmness": ["number.bed_left_firmness"],
                                      "presets": ["select.bed_foundation_preset"],
                                      "presence": ["binary_sensor.bed_left_is_in_bed"]}


def test_outdoor_areas_guess_and_override(house):
    assert classify(house)["outdoor_areas"] == ["yard"]
    house.entities = [e for e in house.entities if e.platform != "frigate"]
    d = classify(house, outdoor_areas=["bedroom"])                 # user says the bedroom counts
    assert d["outdoor_areas"] == ["bedroom"]
    assert [s["entity_id"] for s in d["outside_sensors"]] == ["binary_sensor.bedroom_motion"]
