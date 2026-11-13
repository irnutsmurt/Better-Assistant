import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from core.timeparse import parse, say_when, world_clock

NOW = dt.datetime(2026, 11, 12, 10, 0)          # a Thursday morning


def at(text, alarm=False):
    return parse(text, NOW, alarm)


EVENING = dt.datetime(2026, 11, 12, 18, 28)
EARLY = dt.datetime(2026, 11, 12, 6, 10)


@pytest.mark.parametrize("text,alarm,now,expected", [
    ("7", True, EVENING, dt.datetime(2026, 11, 12, 19, 0)),
    ("7", False, EVENING, dt.datetime(2026, 11, 12, 19, 0)),
    ("2", False, EVENING, dt.datetime(2026, 11, 13, 2, 0)),
    ("tomorrow at 3", False, EVENING, dt.datetime(2026, 11, 13, 15, 0)),
    ("tomorrow at 6", True, EVENING, dt.datetime(2026, 11, 13, 6, 0)),
    ("november 20th at 3", False, EVENING, dt.datetime(2026, 11, 20, 15, 0)),
    ("november 20th at 3 am", False, EVENING, dt.datetime(2026, 11, 20, 3, 0)),
    ("noon", False, EVENING, dt.datetime(2026, 11, 13, 12, 0)),
    ("midnight", False, EVENING, dt.datetime(2026, 11, 13, 0, 0)),
    ("every weekday at 6:45", False, EVENING, dt.datetime(2026, 11, 12, 18, 45)),
    ("2", False, EARLY, dt.datetime(2026, 11, 12, 14, 0)),
    ("every weekday at 6:45", True, EARLY, dt.datetime(2026, 11, 12, 6, 45)),
])
def test_next_occurrence_rule(text, alarm, now, expected):
    assert parse(text, now, alarm)[0] == expected


@pytest.mark.parametrize("text,expected", [
    ("tomorrow at 3", dt.datetime(2026, 11, 13, 15, 0)),
    ("11/28 at 6:30 pm", dt.datetime(2026, 11, 28, 18, 30)),
    ("in 20 minutes", NOW + dt.timedelta(minutes=20)),
    ("in an hour and a half", NOW + dt.timedelta(minutes=90)),
    ("at noon", dt.datetime(2026, 11, 12, 12, 0)),
    ("tonight at 8", dt.datetime(2026, 11, 12, 20, 0)),
    ("monday at 9", dt.datetime(2026, 11, 16, 9, 0)),
    ("friday at 2", dt.datetime(2026, 11, 13, 14, 0)),
    ("half past 6 tomorrow morning", dt.datetime(2026, 11, 13, 6, 30)),
    ("at 2", dt.datetime(2026, 11, 12, 14, 0)),
])
def test_reminder_times(text, expected):
    assert at(text)[0] == expected


def test_the_20th():
    assert at("the 20th at 9 am")[0] == dt.datetime(2026, 11, 20, 9, 0)
    assert at("the 5th at 9 am")[0] == dt.datetime(2026, 12, 5, 9, 0)      # past this month -> next month


def test_in_30_seconds():
    assert at("in 30 seconds")[0] == NOW + dt.timedelta(seconds=30)


def test_every_weekend_and_morning():
    assert at("every weekend at 9") == (dt.datetime(2026, 11, 14, 9, 0), "weekends")
    assert at("every morning at 7") == (dt.datetime(2026, 11, 13, 7, 0), "daily")
    assert at("every weekday at 6:45 am") == (dt.datetime(2026, 11, 13, 6, 45), "weekdays")


def test_market_is_not_march():
    assert at("go to the market at 5")[0] == dt.datetime(2026, 11, 12, 17, 0)


def test_no_time():
    assert at("buy milk")[0] is None


def test_say_when():
    assert say_when(dt.datetime(2026, 11, 13, 15, 0), NOW) == "tomorrow at 3 PM"
    assert say_when(dt.datetime(2026, 11, 12, 18, 30), NOW) == "tonight at 6:30 PM"


def test_world_clock_offsets():
    here = dt.datetime(2026, 11, 12, 20, 0, tzinfo=ZoneInfo("America/Chicago"))
    assert world_clock("tokyo", here) == "It's 11 AM tomorrow in Tokyo, 15 hours ahead of us."
    assert world_clock("London", here) == "It's 2 AM tomorrow in London, 6 hours ahead of us."
    assert world_clock("the los angeles", here) == "It's 6 PM in Los Angeles, 2 hours behind us."
    assert world_clock("india", here).endswith("11.5 hours ahead of us.")
    assert world_clock("dallas", here) == "It's 8 PM in Dallas, the same time as here."
    assert world_clock("atlantis", here) is None


@pytest.mark.parametrize("when,expected", [
    (dt.datetime(2026, 11, 12, 11, 30), "today at 11:30 AM"),
    (dt.datetime(2026, 11, 12, 21, 0), "tonight at 9 PM"),
    (dt.datetime(2026, 11, 13, 5, 0), "tomorrow at 5 AM"),
    (dt.datetime(2026, 11, 16, 7, 15), "Monday at 7:15 AM"),
    (dt.datetime(2026, 11, 28, 18, 30), "Saturday, November 28 at 6:30 PM"),
])
def test_confirmations_always_give_clock_time(when, expected):
    assert say_when(when, NOW) == expected
