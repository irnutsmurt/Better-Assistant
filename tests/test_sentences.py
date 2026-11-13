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


def test_unknown_person_is_not_for_someone_else():
    assert m("remind bob to feed the cat")[0] is None
