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


# ---------------------------------------------------------------- snooze rules
from core.features import (describe_snooze, effective_limit, snooze_decision, snooze_from_page,  # noqa: E402
                           snooze_length_reply, snooze_limit_reply)


def test_snooze_unlimited_and_cap():
    assert snooze_decision(None, 5, None, 7) == (5, "Okay, 5 more minutes.")
    assert snooze_decision(45, 5, None, 0) == (30, "Okay, 30 more minutes (the longest snooze is 30 minutes).")
    assert snooze_decision(1, 5, None, 0) == (1, "Okay, 1 more minute.")


def test_snooze_with_limit_counts_down_then_refuses():
    assert snooze_decision(None, 5, 2, 0) == (5, "Okay, 5 more minutes. You have 1 snooze left.")
    assert snooze_decision(None, 5, 2, 1) == (5, "Okay, 5 more minutes. That was your last snooze.")
    assert snooze_decision(None, 5, 2, 2) == (None, "That was your last snooze. Time to get up!")
    assert snooze_decision(None, 5, 3, 0)[1].endswith("You have 2 snoozes left.")


def test_no_snoozing_is_not_unlimited():
    assert snooze_decision(None, 5, 0, 0)[0] is None
    assert snooze_limit_reply(0) == (False, None, "Okay, no snoozing. The alarm will ring until you stop it.")
    assert snooze_limit_reply(None)[:2] == (True, None)
    assert effective_limit(False, 3) == 0 and effective_limit(True, None) is None and effective_limit(True, 3) == 3
    assert describe_snooze(None, 5) == "There's no snooze limit. Each snooze is 5 minutes."
    assert describe_snooze(0, 5).startswith("Snoozing is turned off")
    assert describe_snooze(3, 5) == "You can snooze 3 times per alarm, 5 minutes each."


def test_limit_and_length_caps():
    assert snooze_limit_reply(15) == (True, 10, "Okay, you can snooze 10 times per alarm (the most is 10).")
    assert snooze_limit_reply(1) == (True, 1, "Okay, you can snooze 1 time per alarm.")


def test_settings_page_snooze_fields():
    assert snooze_from_page(True, None) == (True, None)      # empty = no limit
    assert snooze_from_page(True, "") == (True, None)
    assert snooze_from_page(True, 3) == (True, 3)
    assert snooze_from_page(True, 0) == (False, None)        # 0 = snoozing off, limit cleared
    assert snooze_from_page(False, 4) == (False, 4)
    assert snooze_from_page(True, 25) == (True, 10)
    assert snooze_length_reply(45) == (30, "Okay, snooze is now 30 minutes (the longest snooze is 30 minutes).")
    assert snooze_length_reply(10) == (10, "Okay, snooze is now 10 minutes.")


# ---------------------------------------------------------------- alarm speakers
from core.features import ALL_SPEAKERS, resolve_speaker, say_where, split_alarm_place  # noqa: E402
from core.timeparse import parse  # noqa: E402

SPEAKERS = [
    {"entity_id": "assist_satellite.bed1", "name": "Bedroom speaker", "names": ["Bedroom speaker", "Voice PE 1"],
     "area": "Upstairs", "area_aliases": []},
    {"entity_id": "assist_satellite.bed2", "name": "Bedroom hub", "names": ["Bedroom hub"], "area": "Upstairs",
     "area_aliases": []},
    {"entity_id": "assist_satellite.kit", "name": "Kitchen speaker", "names": ["Kitchen speaker", "Chef"],
     "area": "Kitchen", "area_aliases": ["cookhouse"]},
]


@pytest.mark.parametrize("text,when,place", [
    ("7 in the kitchen", "7", "kitchen"),
    ("7 on the bedroom speaker", "7", "bedroom speaker"),
    ("7 on all speakers", "7", ALL_SPEAKERS),
    ("7 everywhere", "7", ALL_SPEAKERS),
    ("7 on every speaker", "7", ALL_SPEAKERS),
    ("at 6 in the kitchen", "at 6", "kitchen"),
    ("the kitchen for 7", "for 7", "kitchen"),
    ("everywhere for 7", "for 7", ALL_SPEAKERS),
    ("tomorrow at 7 in the bedroom", "tomorrow at 7", "bedroom"),
    ("7 in the morning", "7 in the morning", None),        # time words are not places
    ("6:30 on monday", "6:30 on monday", None),
    ("in 20 minutes", "in 20 minutes", None),
    ("every weekday at 6:45", "every weekday at 6:45", None),
    ("the 20th at 7", "the 20th at 7", None),
])
def test_split_alarm_place(text, when, place):
    assert split_alarm_place(text) == (when, place)


def test_speaker_phrase_is_stripped_before_time_parsing():
    now = dt.datetime(2026, 11, 12, 18, 28)
    when, place = split_alarm_place("7 in the kitchen")
    assert place == "kitchen" and parse(when, now, alarm=True)[0] == dt.datetime(2026, 11, 12, 19, 0)
    when, place = split_alarm_place("6 in the morning on the bedroom speaker")
    assert place == "bedroom speaker" and parse(when, now, alarm=True)[0] == dt.datetime(2026, 11, 13, 6, 0)


@pytest.mark.parametrize("spoken,expected", [
    ("the bedroom speaker", (["assist_satellite.bed1"], None)),
    ("bedroom hub", (["assist_satellite.bed2"], None)),
    ("voice pe 1", (["assist_satellite.bed1"], None)),          # device name
    ("chef", (["assist_satellite.kit"], None)),                  # alias
    ("kitchen", (["assist_satellite.kit"], None)),               # area
    ("cookhouse", (["assist_satellite.kit"], None)),             # area alias
    ("upstairs", (["assist_satellite.bed1", "assist_satellite.bed2"], None)),   # bare area: all its speakers
    ("bedroom", (None, "Did you mean the bedroom speaker or the bedroom hub?")),
    ("garage", (None, None)),
    ("all", (["assist_satellite.bed1", "assist_satellite.bed2", "assist_satellite.kit"], None)),
])
def test_resolve_speaker(spoken, expected):
    assert resolve_speaker(spoken, SPEAKERS) == expected


def test_say_where():
    names = {s["entity_id"]: s["name"] for s in SPEAKERS}
    assert say_where(ALL_SPEAKERS, names) == "on all speakers"
    assert say_where(["assist_satellite.bed1"], names) == "on the bedroom speaker"
    assert say_where(["assist_satellite.bed1", "assist_satellite.bed2"], names) == \
        "on the bedroom speaker and the bedroom hub"


def test_resolve_person_ignores_spaces_from_speech():
    from core.features import resolve_person
    people = [("person.supremehomegod", "supremehomegod", []), ("person.leila", "Leila", [])]
    assert resolve_person("supreme home god", people) == ("person.supremehomegod", None)
    assert resolve_person("Supreme-Home God", people) == ("person.supremehomegod", None)
    assert resolve_person("supreme", people) == (None, None)
