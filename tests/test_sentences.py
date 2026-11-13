"""The agent's own sentences (hassil) and the extra timer wordings, including near-misses that must
fall through to Home Assistant's built-ins or to other steps."""
import pytest

from core.intents import recognize

PEOPLE = ["sam", "alex"]


def m(text):
    r = recognize(text, PEOPLE)
    return (r.intent, r.slots) if r else (None, {})


@pytest.mark.parametrize("text,intent,slots", [
    # timers (Home Assistant built-in intents, extra wordings)
    ("set a pizza timer for 20 minutes", "HassStartTimer", {"name": "pizza", "minutes": 20}),
    ("set a 20 minute pizza timer", "HassStartTimer", {"name": "pizza", "minutes": 20}),
    ("start the egg timer for 2 hours", "HassStartTimer", {"name": "egg", "hours": 2}),
    ("add a minute to the timer", "HassIncreaseTimer", {"minutes": 1}),
    ("add 30 seconds to the timer", "HassIncreaseTimer", {"seconds": 30}),
    ("give the pizza timer 5 more minutes", "HassIncreaseTimer", {"name": "pizza", "minutes": 5}),
    ("add 5 more minutes", "HassIncreaseTimer", {"minutes": 5}),
    ("subtract 30 seconds from the timer", "HassDecreaseTimer", {"seconds": 30}),
    ("take off 2 minutes", "HassDecreaseTimer", {"minutes": 2}),
    ("take a minute off the timer", "HassDecreaseTimer", {"minutes": 1}),
    # reminders
    ("Remind me to call the dentist tomorrow at 3.", "ReminderAdd", {"text": "to call the dentist tomorrow at 3"}),
    ("remind me to buy milk when I get home", "ReminderAdd", {"text": "to buy milk when I get home"}),
    ("remind me to buy bread when I get to the store", "ReminderAdd", {"text": "to buy bread when I get to the store"}),
    ("remind Sam to feed the cat when she gets home", "ReminderAddFor", {"person": "sam", "text": "to feed the cat when she gets home"}),
    ("what are my reminders", "ReminderList", {}),
    ("do I have any reminders", "ReminderList", {}),
    ("cancel my reminders", "ReminderCancelAll", {}),
    ("cancel the reminder to call mom", "ReminderCancel", {"text": "call mom"}),
    # alarms
    ("set an alarm for 7", "AlarmSet", {"text": "7"}),
    ("set an alarm for every weekday at 6:45", "AlarmSet", {"text": "every weekday at 6:45"}),
    ("wake me up at 6:30", "AlarmSet", {"text": "at 6:30"}),
    ("what time is my alarm", "AlarmQuery", {}),
    ("cancel my alarm", "AlarmCancel", {}),
    ("snooze", "AlarmSnooze", {}),
    ("stop the alarm", "AlarmStop", {}),
    # notes
    ("take a note that the wifi password is on the fridge", "NoteAdd", {"text": "the wifi password is on the fridge"}),
    ("remember that the car is on level 3", "NoteAdd", {"text": "the car is on level 3"}),
    ("remember where I put the passports in the top drawer", "NoteAdd", {"text": "the passports in the top drawer", "put": "put"}),
    ("where did I put my keys", "NoteFind", {"text": "my keys"}),
    ("read my notes", "NoteRead", {}),
    ("clear my notes", "NoteClear", {}),
    # messages
    ("leave a message for Alex that dinner is in the oven", "MessageLeave", {"person": "alex", "text": "dinner is in the oven"}),
    ("leave a note that the dog has been fed", "MessageLeave", {"text": "the dog has been fed"}),
    ("any messages?", "MessageRead", {}),
    # stopwatch
    ("start the stopwatch", "StopwatchStart", {}),
    ("how long has the stopwatch been running", "StopwatchRead", {}),
    ("stop the stopwatch", "StopwatchStop", {}),
])
def test_matches(text, intent, slots):
    got_intent, got_slots = m(text)
    assert got_intent == intent
    for k, v in slots.items():
        assert str(got_slots.get(k)).lower() == str(v).lower(), (k, got_slots)


@pytest.mark.parametrize("text", [
    "set a timer for 10 minutes",          # built-in, must not get a name of "a"
    "add 2 minutes to the timer",          # built-in
    "add milk to the shopping list",       # built-in to-do intent
    "where is my phone",                   # not a note search
    "what time is it",
    "turn off the kitchen lights",
    "what's the weather",
    "remind",
    "remember",
    "stop",                                # built-in media stop
])
def test_falls_through(text):
    assert m(text)[0] is None


@pytest.mark.parametrize("text,name", [
    ("remind bob to feed the cat", "bob"),
    ("Remind Bob that the bins go out tonight", "Bob"),
    ("leave a message for Bob that dinner is ready", "Bob"),
    ("leave a note for bob saying hi", "bob"),
])
def test_unknown_person(text, name):
    assert m(text) == ("UnknownPerson", {"name": name, "text": m(text)[1]["text"]})
    assert m(text)[1]["name"] == name


def test_known_people_and_me_still_win():
    assert m("remind SAM to feed the cat")[0] == "ReminderAddFor"
    assert m("remind me to feed the cat")[0] == "ReminderAdd"
    assert m("leave a message for alex that hi")[0] == "MessageLeave"
    assert m("leave a note that the dog is fed")[0] == "MessageLeave"


def test_aliases_are_matched_like_names():
    r = recognize("remind grandpa to take his pills at 8", ["sam", "grandpa"])
    assert r.intent == "ReminderAddFor" and r.slots["person"] == "grandpa"


@pytest.mark.parametrize("text,minutes", [
    ("snooze", None), ("snooze it", None), ("snooze the alarm", None),
    ("snooze for 10 minutes", 10), ("snooze it for ten minutes", 10),
    ("5 more minutes", 5), ("five more minutes", 5), ("give me 3 more minutes", 3),
    ("just 2 more minutes", 2), ("just a couple more minutes", 2), ("a few more minutes", 3),
    ("give me fifteen more minutes please", 15),
])
def test_snooze(text, minutes):
    intent, slots = m(text)
    assert intent == "AlarmSnooze"
    assert slots.get("minutes") == minutes


def test_snooze_settings():
    assert m("set the snooze to 10 minutes") == ("AlarmSnoozeSet", {"minutes": 10})
    assert m("change my snooze time to twenty minutes") == ("AlarmSnoozeSet", {"minutes": 20})
    assert m("how long is the snooze")[0] == "AlarmSnoozeQuery"


@pytest.mark.parametrize("text", ["give the pizza timer 5 more minutes", "add 5 more minutes",
                                  "add another 5 minutes", "give the timer 5 more minutes"])
def test_timer_phrases_beat_snooze(text):
    assert m(text)[0] == "HassIncreaseTimer"


@pytest.mark.parametrize("text", ["17 more minutes", "give me 45 more minutes", "lots more minutes"])
def test_snooze_numbers_are_explicit(text):
    assert m(text)[0] != "AlarmSnooze"


@pytest.mark.parametrize("text,minutes", [
    ("snooze for 45 minutes", 45), ("snooze for 17 minutes", 17), ("snooze it for twenty two minutes", 22),
])
def test_snooze_for_any_number(text, minutes):
    assert m(text) == ("AlarmSnooze", {"minutes": minutes})


def test_set_snooze_any_number():
    assert m("set the snooze to 45 minutes") == ("AlarmSnoozeSet", {"minutes": 45})
    assert m("set the snooze to 17 minutes") == ("AlarmSnoozeSet", {"minutes": 17})


@pytest.mark.parametrize("text,count", [
    ("limit snoozes to 3", 3), ("set the snooze limit to 3", 3), ("only allow 2 snoozes", 2),
    ("only allow one snooze", 1), ("limit snoozes to 15", 15), ("set the snooze limit to 0", 0),
    ("no snoozing", 0), ("turn off snoozing", 0),
])
def test_snooze_limit_set(text, count):
    assert m(text) == ("SnoozeLimitSet", {"count": count})


@pytest.mark.parametrize("text,intent", [
    ("no snooze limit", "SnoozeLimitClear"), ("unlimited snoozes", "SnoozeLimitClear"),
    ("remove the snooze limit", "SnoozeLimitClear"),
    ("how many snoozes do I get", "SnoozeLimitQuery"), ("what's the snooze limit", "SnoozeLimitQuery"),
])
def test_snooze_limit_other(text, intent):
    assert m(text)[0] == intent
