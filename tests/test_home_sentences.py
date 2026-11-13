"""Stage 3 sentences: each feature's phrases, and the near-misses that must reach Home Assistant's
built-ins or another feature instead."""
import pytest

from core.intents import recognize

LISTS = {
    "area": ["kitchen", "living room"],
    "music_target": {"kitchen speaker": "media_player.kitchen", "kitchen": "area:kitchen",
                     "living room": "area:living"},
    "calendar": {"family": "calendar.family", "work": "calendar.work"},
    "light_target": {"kitchen": "area:kitchen", "kitchen lights": "area:kitchen", "desk lamp": "light.desk_lamp"},
    "place": {"driveway": "driveway", "backyard": "backyard"},
    "camera": {"driveway": "camera.driveway", "front door": "camera.front_door"},
    "tv": {"living room tv": "media_player.living_tv", "bedroom tv": "media_player.bedroom_tv"},
    "tv_source": {"hdmi 2": "HDMI 2", "playstation": "HDMI 2", "game": "HDMI 2"},
    "tv_app": {"netflix": "com.netflix.ninja", "youtube": "com.google.android.youtube.tv"},
    "bed_preset": {"flat": "Flat", "read": "Read"},
    "climate_mode": {"heat": "heat", "cool": "cool", "auto": "auto", "off": "off"},
    "climate_preset": {"eco": "eco", "away": "away"},
    "battery_thing": {"kitchen sensor": "sensor.kitchen_battery", "front door lock": "sensor.lock_battery"},
    "help_topic": {"music": "music", "the tv": "tv"},
}
PEOPLE = ["sam", "alex"]


def m(text, disabled=frozenset()):
    r = recognize(text, PEOPLE, lists=LISTS, disabled=disabled)
    return (r.intent, r.slots) if r else (None, {})


@pytest.mark.parametrize("text,intent,slots", [
    # music
    ("play music by Queen in the kitchen", "MusicPlay", {"query": "music by Queen", "music_target": "area:kitchen"}),
    ("play jazz on the kitchen speaker", "MusicPlay", {"query": "jazz", "music_target": "media_player.kitchen"}),
    ("play jazz everywhere", "MusicPlay", {"query": "jazz", "music_target": "all"}),
    ("play my workout playlist", "MusicPlay", {"query": "my workout playlist"}),
    ("what's playing", "MusicNowPlaying", {}), ("turn it up", "MusicLouder", {}), ("quieter", "MusicQuieter", {}),
    ("stop the music", "MusicStop", {}), ("move the music to the living room", "MusicMove", {"music_target": "area:living"}),
    ("stop the music in 30 minutes", "MusicSleep", {"minutes": 30}),
    ("turn off the music in an hour", "MusicSleep", {"minutes": 60}),
    # calendar
    ("what's on my calendar tomorrow", "CalendarList", {"range": "tomorrow"}),
    ("what's on my calendar this weekend", "CalendarList", {"range": "this weekend"}),
    ("what do i have today", "CalendarList", {"range": "today"}),
    ("when's my next appointment", "CalendarNext", {}),
    ("add dentist to my calendar tomorrow at 3", "CalendarAdd", {"text": "dentist", "when": "tomorrow at 3"}),
    ("add team lunch to the work calendar friday at noon", "CalendarAdd",
     {"text": "team lunch", "calendar": "calendar.work", "when": "friday at noon"}),
    # rooms and lights
    ("turn off the kitchen", "RoomOff", {"area": "kitchen"}), ("turn the living room on", "RoomOn", {"area": "living room"}),
    ("turn off the fan in 10 minutes", "DelayedCommand", {"verb": "off", "thing": "the fan", "amount": 10, "unit": "minutes"}),
    ("turn the porch light on in an hour", "DelayedCommand", {"verb": "on", "thing": "the porch light", "amount": 1, "unit": "hours"}),
    ("turn on the heater for 30 minutes", "TimedCommand", {"thing": "the heater", "amount": 30, "unit": "minutes"}),
    ("dim the kitchen by 30 percent", "LightDim", {"light_target": "area:kitchen", "percent": 30}),
    ("dim the desk lamp", "LightDim", {"light_target": "light.desk_lamp"}),
    ("brighten the kitchen lights", "LightBrighten", {"light_target": "area:kitchen"}),
    ("make the kitchen warmer", "LightWarmer", {"light_target": "area:kitchen"}),
    ("make the desk lamp cooler", "LightCooler", {"light_target": "light.desk_lamp"}),
    # climate
    ("make it 2 degrees warmer", "ClimateWarmer", {"degrees": 2}), ("i'm cold", "ClimateWarmer", {}),
    ("make it cooler", "ClimateCooler", {}), ("turn down the heat", "ClimateCooler", {}),
    ("what's the thermostat set to", "ClimateQuery", {}), ("is the heat on", "ClimateIsOn", {"what": "heat"}),
    ("is the ac on", "ClimateIsOn", {"what": "cool"}), ("turn on the heat", "ClimateMode", {"mode": "heat"}),
    ("switch to cooling", "ClimateMode", {"mode": "cool"}), ("set the thermostat to auto", "ClimateMode", {"mode": "auto"}),
    ("turn off the thermostat", "ClimateMode", {"mode": "off"}), ("eco mode", "ClimatePreset", {"preset": "eco"}),
    # outside and cameras
    ("is anyone outside", "OutsideAnyone", {"place": "outside"}),
    ("is anyone at the driveway", "OutsideAnyone", {"place": "driveway"}),
    ("any motion in the backyard", "OutsideMotion", {"place": "backyard"}),
    ("show the driveway camera on the living room tv", "CameraShow",
     {"camera": "camera.driveway", "tv": "media_player.living_tv"}),
    ("show the front door camera", "CameraShow", {"camera": "camera.front_door"}),
    ("close the camera", "CameraClose", {}),
    # TV
    ("switch the tv to hdmi 2", "TvSource", {"source": "HDMI 2"}), ("switch to the playstation", "TvSource", {"source": "HDMI 2"}),
    ("what's on the living room tv right now", "TvWhatsOn", {"tv": "media_player.living_tv"}),
    ("what's playing on the tv", "TvWhatsOn", {}),
    ("what's playing on the bedroom tv", "TvWhatsOn", {"tv": "media_player.bedroom_tv"}), ("is the tv on", "TvWhatsOn", {}),
    ("what lights are on in the house right now", "RoomWhichLights", {}),
    ("what lights are on the house right now", "RoomWhichLights", {}),    # Whisper dropped "in"
    ("which lights are still on", "RoomWhichLights", {}), ("did I leave any lights on", "RoomWhichLights", {}),
    ("are any lights on in the kitchen", "RoomWhichLights", {"area": "kitchen"}),
    ("open netflix", "TvApp", {"app": "com.netflix.ninja"}), ("launch youtube on the tv", "TvApp", {"app": "com.google.android.youtube.tv"}),
    # bed
    ("set the bed to flat", "BedPreset", {"preset": "Flat"}), ("set my side to read", "BedPreset", {"preset": "Read", "who": "me"}),
    ("set sam's side to flat", "BedPreset", {"person": "sam", "preset": "Flat"}),
    ("raise my side", "BedRaise", {"who": "me"}), ("flatten the bed", "BedFlatten", {"who": "all"}),
    ("set my sleep number to 45", "BedNumber", {"number": 45, "who": "me"}),
    ("what's our sleep number", "BedQuery", {"who": "all"}), ("how did sam sleep", "BedSleep", {"person": "sam"}),
    # health
    ("is anything wrong", "HealthReport", {}), ("are any devices offline", "HealthReport", {}),
    ("house status", "HealthReport", {}), ("which batteries are low", "BatteryLow", {}),
    ("status of all batteries", "BatteryAll", {}),
    ("what's the kitchen sensor battery", "BatteryOne", {"thing": "sensor.kitchen_battery"}),
    ("what's the front door lock battery level", "BatteryOne", {"thing": "sensor.lock_battery"}),
    ("what's the kitchen sensor battery yet", "BatteryOne", {"thing": "sensor.kitchen_battery"}),
    ("what's the battery on my phone", "BatteryPhone", {}),
    # modes, broadcast, help
    ("turn on guest mode", "GuestOn", {}), ("guest mode off", "GuestOff", {}), ("is guest mode on", "GuestQuery", {}),
    ("turn on night mode", "NightOn", {}), ("disable night mode", "NightOff", {}),
    ("tell everyone that dinner is ready", "BroadcastMessage", {"message": "dinner is ready"}),
    ("announce the car is here", "BroadcastMessage", {"message": "the car is here"}),
    ("what can you do", "Help", {}), ("what can you do with music", "Help", {"topic": "music"}),
])
def test_feature_sentences(text, intent, slots):
    got, got_slots = m(text)
    assert got == intent, (text, got, got_slots)
    for k, v in slots.items():
        assert got_slots.get(k) == v, (text, k, got_slots)


@pytest.mark.parametrize("text", [
    "turn off the kitchen lights",            # built-in area + domain
    "turn off the lamp",                      # built-in entity name
    "turn on the light in the kitchen",       # not a delay: no time unit
    "set a timer for 10 minutes",             # built-in timer
    "add milk to the shopping list",          # built-in to-do
    "where is my phone",                      # not notes, not batteries
    "open the garage door",                   # built-in cover, not an app
    "is anyone home",                         # not outside
    "set the temperature to 70",              # built-in climate
    "what's the weather",
    "turn up the volume",                     # built-in volume
    "show me the weather",                    # not a camera
])
def test_left_for_builtins(text):
    assert m(text)[0] is None, m(text)


@pytest.mark.parametrize("text,intent", [
    ("turn off the music in 30 minutes", "MusicSleep"),            # not a delayed command
    ("give the pizza timer 5 more minutes", "HassIncreaseTimer"),  # not snooze, not music
    ("5 more minutes", "AlarmSnooze"),
    ("start the stopwatch", "StopwatchStart"),                     # not a TV app
    ("make it warmer", "ClimateWarmer"),                           # not a light
    ("turn on night mode", "NightOn"),                             # not a thermostat preset
    ("remind me to call mom at 5", "ReminderAdd"),
])
def test_features_dont_steal_each_other(text, intent):
    assert m(text)[0] == intent


def test_switched_off_feature_falls_through():
    assert m("play jazz", disabled=frozenset({"music"}))[0] is None
    assert m("turn off the kitchen", disabled=frozenset({"rooms_lights"}))[0] is None
    assert m("what's on my calendar", disabled=frozenset({"music"}))[0] == "CalendarList"


def test_empty_house_lists_never_match():
    r = recognize("turn off the kitchen", [], lists={})
    assert r is None or r.intent != "RoomOff"
