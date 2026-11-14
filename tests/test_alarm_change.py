"""Changing an alarm that's already set: "change my alarm from 9 to 9:50", "push it back 10 minutes",
speech-to-text's "9.50", and moving it to another speaker with the same words."""
import datetime as dt
import types

import pytest

from core.features import alarm_change, retime, says_half_of_day
from core.intents import recognize
from core.timeparse import parse

NOW = dt.datetime(2026, 11, 14, 8, 6)            # a Saturday morning


@pytest.mark.parametrize("text,expected", [
    ("Set an alarm for 9.50.", dt.datetime(2026, 11, 14, 9, 50)),
    ("9.50am", dt.datetime(2026, 11, 14, 9, 50)),
    ("at 9.05 pm", dt.datetime(2026, 11, 14, 21, 5)),
])
def test_speech_to_text_dots_are_clock_times(text, expected):
    assert parse(text, NOW, alarm=True)[0] == expected


def test_decimal_durations_still_work():
    assert parse("in 1.50 hours", NOW)[0] == NOW + dt.timedelta(minutes=90)


@pytest.mark.parametrize("text,expected", [
    ("to 9:50", ("time", "9:50", None)),
    ("to from 9am to 9.50", ("time", "9.50", "9am")),            # what the speaker actually heard
    ("from 9 am to 9:50 am", ("time", "9:50 am", "9 am")),
    ("for 9:50 instead", ("time", "9:50", None)),
    ("to nine fifty please", ("time", "9 50", None)),
    ("to tomorrow at 7", ("time", "tomorrow at 7", None)),
    ("10 minutes later", ("shift", 10, None)),
    ("back 10 minutes", ("shift", 10, None)),
    ("back by ten minutes", ("shift", 10, None)),
    ("half an hour earlier", ("shift", -30, None)),
    ("an hour later", ("shift", 60, None)),
    ("up 15 minutes", ("shift", -15, None)),
    ("to the kitchen", ("place", "the kitchen", None)),
    ("to ring everywhere", ("place", "everywhere", None)),
    ("from the kitchen to the bedroom", ("place", "the bedroom", None)),
    ("", (None, None, None)),
])
def test_what_a_change_asks_for(text, expected):
    assert alarm_change(text) == expected


def test_retime_keeps_the_alarms_day_and_half():
    tomorrow_7am = dt.datetime(2026, 11, 15, 7, 0)
    assert retime(tomorrow_7am, 7, 30, NOW, True) == dt.datetime(2026, 11, 15, 7, 30)
    nine_am = dt.datetime(2026, 11, 14, 9, 0)
    assert retime(nine_am, 9, 50, NOW, True) == dt.datetime(2026, 11, 14, 9, 50)
    assert retime(nine_am, 8, 0, dt.datetime(2026, 11, 14, 8, 30), True) == dt.datetime(2026, 11, 14, 20, 0)
    assert says_half_of_day("9:50 am") and says_half_of_day("tomorrow at 7") and not says_half_of_day("9:50")


@pytest.mark.parametrize("text,intent", [
    ("change my alarm to 9:50", "AlarmChange"),
    ("Change alarm to from 9am to 9.50", "AlarmChange"),
    ("can you change the alarm from 9 to 9:50", "AlarmChange"),
    ("move my alarm to 9:50", "AlarmChange"),
    ("push my alarm back 10 minutes", "AlarmChange"),
    ("make my alarm 10 minutes later", "AlarmChange"),
    ("change the time of my alarm to 7", "AlarmChange"),
    ("change my 9 am alarm to 9:50", "AlarmChange"),
    ("reschedule my alarm for 6:30 tomorrow", "AlarmChange"),
    ("move my alarm to the kitchen", "AlarmChange"),
    ("set an alarm for 9.50", "AlarmSet"),
])
def test_change_sentences(text, intent):
    match = recognize(text, ["rob"])
    assert match and match.intent == intent


# ------------------------------------------------------------------ the handler
class _Store:
    def __init__(self):
        self.data = {"alarms": {}}

    def changed(self):
        pass


def _skills(alarms):
    pytest.importorskip("homeassistant")
    from custom_components.better_assistant.skills import Skills
    s = Skills.__new__(Skills)
    s.hass, s.store = None, _Store()
    s.store.data["alarms"] = alarms
    s._snooze_count, s._timers = {}, {}
    s._alarms = lambda: s.store.data["alarms"]
    s._mine = lambda ui: dict(s.store.data["alarms"])
    s.satellite_for = lambda ui: "assist_satellite.kitchen"
    s._schedule_alarm = lambda key: None
    return s


def _alarm(hour, minute, repeat="once", days=0):
    pytest.importorskip("homeassistant")
    from homeassistant.util import dt as dt_util
    now = dt_util.now()
    at = (now + dt.timedelta(days=days or 1)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    return {"targets": ["assist_satellite.kitchen"], "hour": hour, "minute": minute, "repeat": repeat,
            "next": at.isoformat()}


async def test_change_an_alarm_to_a_new_time():
    s = _skills({"assist_satellite.kitchen": _alarm(9, 0)})
    reply = await s._h_alarm_change({"text": "to from 9am to 9.50"}, None)
    a = s.store.data["alarms"]["assist_satellite.kitchen"]
    assert (a["hour"], a["minute"]) == (9, 50) and "9:50 AM" in reply


async def test_push_an_alarm_back_and_keep_it_repeating():
    s = _skills({"assist_satellite.kitchen": _alarm(6, 45, "weekdays")})
    reply = await s._h_alarm_change({"text": "back 15 minutes"}, None)
    a = s.store.data["alarms"]["assist_satellite.kitchen"]
    assert (a["hour"], a["minute"], a["repeat"]) == (7, 0, "weekdays")
    assert reply == "Okay, your alarm is now set for every weekday at 7 AM."


async def test_pick_the_alarm_by_its_old_time():
    s = _skills({"assist_satellite.kitchen": _alarm(7, 0),
                       "assist_satellite.bedroom": _alarm(9, 0)})
    s.satellite_for = lambda ui: None
    await s._h_alarm_change({"text": "from 9 to 9:30"}, None)
    assert s.store.data["alarms"]["assist_satellite.bedroom"]["minute"] == 30
    assert s.store.data["alarms"]["assist_satellite.kitchen"]["minute"] == 0
    reply = await s._h_alarm_change({"text": "to 8"}, None)
    assert reply.startswith("You have more than one alarm")


async def test_no_alarm_yet():
    s = _skills({})
    assert await s._h_alarm_change({"text": "10 minutes later"}, None) == "You don't have an alarm set."
