import datetime as dt

import pytest

from core.calendar import day_range, parse_event, say_events, say_next
from core.devices import (adjust_target, app_words, battery_name, climate_mode_words, find_battery, in_window,
                          is_heating_answer, preset_words, round_to_step, say_batteries, say_climate, say_health,
                          say_help, say_outside, side_of, sleeper_matches, source_words, step_brightness, step_kelvin)
from core.music import is_news, parse_music_query

NOW = dt.datetime(2026, 11, 12, 18, 28)        # a Thursday evening


# ---------------------------------------------------------------- music
@pytest.mark.parametrize("query,name,kind,radio", [
    ("music by Queen", "Queen", "artist", False), ("songs by the Beatles", "the Beatles", "artist", False),
    ("my workout playlist", "workout", "playlist", False), ("the playlist chill vibes", "chill vibes", "playlist", False),
    ("the album Abbey Road", "Abbey Road", "album", False), ("music like Adele", "Adele", "artist", True),
    ("Adele radio", "Adele", "artist", True), ("the song Bohemian Rhapsody", "Bohemian Rhapsody", "track", False),
    ("jazz", "jazz", None, False), ("some music", "", None, False),
])
def test_music_query(query, name, kind, radio):
    r = parse_music_query(query)
    assert (r.name, r.media_type, r.radio) == (name, kind, radio)


@pytest.mark.parametrize("query,news", [("the news", True), ("the BBC headlines", True), ("my podcast", True),
                                        ("news radio", True), ("jazz", False), ("music by Queen", False)])
def test_news_goes_to_builtins(query, news):
    assert is_news(query) is news


# ---------------------------------------------------------------- calendar
@pytest.mark.parametrize("text,title,start,all_day", [
    ("dentist tomorrow at 3", "Dentist", dt.datetime(2026, 11, 13, 15, 0), False),     # 1-6 with a day = PM
    ("tomorrow at 3 dentist", "Dentist", dt.datetime(2026, 11, 13, 15, 0), False),
    ("dentist tomorrow at 3 am", "Dentist", dt.datetime(2026, 11, 13, 3, 0), False),
    ("team lunch friday at noon", "Team lunch", dt.datetime(2026, 11, 13, 12, 0), False),
    ("haircut on the 20th at 10 am", "Haircut", dt.datetime(2026, 11, 20, 10, 0), False),
    ("mom's birthday on june 3rd", "Mom's birthday", dt.date(2027, 6, 3), True),
    ("book club next tuesday", "Book club", dt.date(2026, 11, 17), True),
    ("on friday team lunch", "Team lunch", dt.date(2026, 11, 13), True),
])
def test_parse_event(text, title, start, all_day):
    ev = parse_event(text, NOW)
    assert (ev.title, ev.start, ev.all_day) == (title, start, all_day)
    assert ev.end - ev.start == (dt.timedelta(days=1) if all_day else dt.timedelta(hours=1))


def test_parse_event_needs_a_time():
    assert parse_event("party", NOW) is None


def test_day_ranges():
    assert day_range("tomorrow", NOW)[:2] == (dt.datetime(2026, 11, 13), dt.datetime(2026, 11, 14))
    assert day_range("this weekend", NOW)[:2] == (dt.datetime(2026, 11, 14), dt.datetime(2026, 11, 16))
    assert day_range("next week", NOW)[:2] == (dt.datetime(2026, 11, 16), dt.datetime(2026, 11, 23))
    assert day_range("today", NOW)[2] == "today"


def test_say_events():
    events = [{"summary": "Holiday", "start": "2026-11-14"}, {"summary": "Dentist", "start": "2026-11-13T15:00:00"}]
    assert say_events(events, "this week", NOW) == \
        "You have 2 things this week. Tomorrow at 3 PM: Dentist. Saturday, all day: Holiday."
    assert say_events([], "today", NOW) == "There's nothing on your calendar today."
    assert say_next({"summary": "Dentist", "start": "2026-11-13T15:00:00-06:00"}, NOW) == \
        "Your next event is Dentist, tomorrow at 3 PM."


# ---------------------------------------------------------------- lights and climate
def test_light_steps():
    assert step_brightness(128, 20, False) == 30
    assert step_brightness(None, 20, True) == 20
    assert step_kelvin(3000, 500, True) == 2500 and step_kelvin(6400, 500, False) == 6500


def test_climate():
    assert climate_mode_words(["heat", "off"]) == {"heat": "heat", "heating": "heat", "the heat": "heat", "off": "off"}
    assert preset_words(["eco", "away_mode"])["away"] == "away_mode"
    assert adjust_target({"temperature": 70, "max_temp": 71}, 2) == {"temperature": 71}
    assert adjust_target({"target_temp_low": 68, "target_temp_high": 74}, -1) == \
        {"target_temp_low": 67, "target_temp_high": 73}
    assert say_climate("thermostat", "heat", {"temperature": 70, "hvac_action": "heating", "current_temperature": 68}) == \
        "The thermostat is in heat mode, set to 70 degrees. It's heating right now. It's 68 degrees inside."
    assert is_heating_answer("heat", {"hvac_action": "idle"}, "heat") == "The heat is set but not running right now."
    assert is_heating_answer("off", {}, "cool") == "No, the air conditioning is off."


# ---------------------------------------------------------------- TV
def test_tv_sources_and_apps():
    words = source_words(["HDMI 1", "HDMI 2 - PlayStation 5", "Live TV", "HDMI4"])
    assert words["hdmi 2"] == words["playstation"] == words["game"] == "HDMI 2 - PlayStation 5"
    assert words["hdmi 4"] == "HDMI4" and words["live tv"] == "Live TV"
    assert "hdmi" not in words                         # a bare "hdmi" would be a guess
    assert app_words(None)["netflix"] == "com.netflix.ninja"
    own = app_words(["Netflix", "com.google.android.youtube.tv"])
    assert own["netflix"] == "Netflix" and own["youtube"] == "com.google.android.youtube.tv"


# ---------------------------------------------------------------- bed, health, outside, night, help
def test_bed_helpers():
    assert round_to_step(37, 5, 5, 100) == 35 and round_to_step(120, 5, 5, 100) == 100
    assert side_of("SleepNumber Bed Foundation Preset Right") == "right" and side_of("Bed Firmness") is None
    assert sleeper_matches("SleepNumber Bed Sam Firmness", "Sam") and not sleeper_matches("Samantha Firmness", "Sam")


def test_batteries_and_health():
    assert battery_name("Kitchen sensor Battery level") == "kitchen sensor"
    names = {"kitchen sensor": "s.k", "front door lock": "s.f"}
    assert find_battery("the kitchen sensor battery yet", names) == "s.k"
    assert find_battery("front door", names) == "s.f" and find_battery("", names) is None
    assert say_batteries([("kitchen sensor", 15), ("lock", 80)], 20, True) == "Low batteries: kitchen sensor at 15 percent."
    assert say_batteries([("lock", 80)], 20, True) == "No batteries are below 20 percent."
    report = say_health({"dev1": ["light.a"]}, {"dev1": "Porch bulb"}, [("lock", 10)], ["robot"], 2)
    assert report == ("1 device is offline: Porch bulb. Low batteries: lock at 10 percent. The robot has an error. "
                      "2 updates are waiting.")
    assert say_health({}, {}, [], [], 0).startswith("Everything looks fine")


def test_outside():
    assert say_outside("driveway", True, None) == "Yes, there's someone at the driveway right now."
    assert say_outside("outside", False, 600) == "No one's outside right now. The last person was seen 10 minutes ago."
    assert say_outside("backyard", False, 7200, "motion") == \
        "No motion at the backyard right now. The last motion was 2 hours ago."


def test_night_window():
    assert in_window(dt.time(23), dt.time(22), dt.time(7)) and in_window(dt.time(6, 59), dt.time(22), dt.time(7))
    assert not in_window(dt.time(7), dt.time(22), dt.time(7)) and not in_window(dt.time(12), dt.time(22), dt.time(7))
    assert in_window(dt.time(14), dt.time(13), dt.time(15))


def test_help_only_lists_enabled_features():
    text = say_help(["local", "music"])
    assert "play music" in text and "TV" not in text
    assert say_help(["music"], "the tv").startswith("That's turned off")
    assert say_help(["music"], "music").startswith("I can play music")


def test_guest_exposure_restores_exactly():
    from core.devices import exposure_record, restore_action
    explicit_on = exposure_record({"should_expose": True}, False)
    explicit_off = exposure_record({"should_expose": False}, True)
    default_on = exposure_record({}, True)
    default_off = exposure_record({"other": 1}, False)
    assert restore_action(explicit_on) == ("set", True)
    assert restore_action(explicit_off) == ("set", False)
    assert restore_action(default_on) == ("clear", True)          # back to the default, not an explicit True
    assert restore_action(default_off) == ("clear", False)
    assert default_on == {"explicit": False, "default": True}     # plain data, saved with the integration


def test_say_sleep():
    from core.devices import say_sleep
    assert say_sleep("Robin", ("452", "min"), ("81", None), ("56", "bpm"), True) == \
        "You slept 7 hours and 32 minutes with a sleep score of 81. Average heart rate 56."
    assert say_sleep("Robin", ("7.5", "h"), None) == "Robin slept 7 hours and 30 minutes."
    assert say_sleep("Robin", None, ("70", None)) == "Robin had a sleep score of 70."
