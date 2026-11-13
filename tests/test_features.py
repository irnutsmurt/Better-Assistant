import datetime as dt

import pytest

from core.features import (best_note, flip_pronouns, next_alarm, note_from, parse_reminder, say_alarm,
                           say_duration)

NOW = dt.datetime(2026, 11, 12, 10, 0)


@pytest.mark.parametrize("text,task,at", [
    ("to call mom at 5", "call mom", dt.datetime(2026, 11, 12, 17, 0)),
    ("to call mom tomorrow at 3", "call mom", dt.datetime(2026, 11, 13, 15, 0)),
    ("at 5 to call mom", "call mom", dt.datetime(2026, 11, 12, 17, 0)),
    ("to go to the market at 5", "go to the market", dt.datetime(2026, 11, 12, 17, 0)),
    ("to take the bins out on monday at 7", "take the bins out", dt.datetime(2026, 11, 16, 7, 0)),
    ("tomorrow morning to take the bins out", "take the bins out", dt.datetime(2026, 11, 13, 9, 0)),
    ("to call grandma tonight", "call grandma", dt.datetime(2026, 11, 12, 20, 0)),
    ("to pay rent on the 20th", "pay rent", dt.datetime(2026, 11, 20, 9, 0)),
    ("to stretch in 20 minutes", "stretch", dt.datetime(2026, 11, 12, 10, 20)),
])
def test_time_reminders(text, task, at):
    r = parse_reminder(text, NOW)
    assert (r.kind, r.task, r.at) == ("time", task, at)


def test_repeating_reminder():
    r = parse_reminder("to water the plants every day at 8 am", NOW)
    assert (r.task, r.repeat, r.at) == ("water the plants", "daily", dt.datetime(2026, 11, 13, 8, 0))


@pytest.mark.parametrize("text,kind,place,task", [
    ("to buy milk when I get home", "arrive", "home", "buy milk"),
    ("to feed the cat when she gets home", "arrive", "home", "feed the cat"),
    ("to lock up when I leave", "leave", "home", "lock up"),
    ("to lock up when I leave home", "leave", "home", "lock up"),
    ("to buy milk when I leave work", "leave", "work", "buy milk"),
    ("to buy bread when I get to the store", "arrive", "store", "buy bread"),
    ("to call the plumber when I arrive at the office", "arrive", "office", "call the plumber"),
])
def test_place_reminders(text, kind, place, task):
    r = parse_reminder(text, NOW)
    assert (r.kind, r.place, r.task) == (kind, place, task)


def test_no_time():
    assert parse_reminder("to call mom", NOW).kind == "none"


def test_pronoun_flip():
    assert flip_pronouns("I put my keys in the drawer") == "you put your keys in the drawer"
    assert flip_pronouns("the blue one is mine, I'm sure") == "the blue one is yours, you're sure"


def test_notes():
    notes = ["I put the car on level 3", "I put my keys in the drawer", "the wifi password is on the fridge"]
    assert best_note("my keys", notes) == "I put my keys in the drawer"
    assert best_note("the car", notes) == "I put the car on level 3"
    assert best_note("my passport", notes) is None
    assert note_from("the keys in the drawer", "put") == "I put the keys in the drawer"


def test_alarm_next_and_phrasing():
    fri = dt.datetime(2026, 11, 13, 7, 0)
    assert next_alarm(7, 0, "weekdays", fri) == dt.datetime(2026, 11, 16, 7, 0)
    assert next_alarm(7, 0, "weekends", NOW) == dt.datetime(2026, 11, 14, 7, 0)
    assert next_alarm(11, 0, "once", NOW) == dt.datetime(2026, 11, 12, 11, 0)
    assert say_alarm(dt.datetime(2026, 11, 13, 6, 45), "weekdays", NOW) == "every weekday at 6:45 AM"
    assert say_alarm(dt.datetime(2026, 11, 13, 7, 0), "once", NOW) == "tomorrow at 7 AM"


def test_durations():
    assert say_duration(3725) == "1 hour, 2 minutes and 5 seconds"
    assert say_duration(61) == "1 minute and 1 second"
    assert say_duration(0.2) == "0 seconds"


PEOPLE = [("person.sam_smith", "Sam Smith", []), ("person.sam_lee", "Sam Lee", ["Sammy"]),
          ("person.alex", "Alex Jordan", ["Grandpa"])]


def test_resolve_person():
    from core.features import resolve_person
    assert resolve_person("alex", PEOPLE) == ("person.alex", None)
    assert resolve_person("GRANDPA", PEOPLE) == ("person.alex", None)
    assert resolve_person("sammy", PEOPLE) == ("person.sam_lee", None)
    assert resolve_person("Sam Lee", PEOPLE) == ("person.sam_lee", None)
    assert resolve_person("sam", PEOPLE) == (None, "Did you mean Sam Smith or Sam Lee?")
    assert resolve_person("bob", PEOPLE) == (None, None)
