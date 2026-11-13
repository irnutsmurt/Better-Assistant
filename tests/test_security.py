"""Voice passphrase: matching, the one-shot form, the lockout schedule and replies."""
import pytest

from core.intents import recognize
from core.security import (RESET_AFTER, Attempts, lockout_seconds, matches, normalize, say_not_heard,
                           say_oneshot_help, say_wait, say_wrong, split_oneshot)

SECRET = "Purple Monkey, dishwasher!"


@pytest.mark.parametrize("spoken,ok", [
    ("purple monkey dishwasher", True), ("PURPLE-MONKEY dishwasher.", True), ("purplemonkeydishwasher", True),
    ("purple monkey", False), ("purple monkey dishwashers", False), ("", False),
])
def test_matching_ignores_case_spaces_and_punctuation(spoken, ok):
    assert matches(spoken, SECRET) is ok


def test_empty_secret_never_matches():
    assert not matches("", "") and not matches("anything", "")
    assert normalize("A b, C!") == "abc"


@pytest.mark.parametrize("text,command,phrase", [
    ("open the garage door, passphrase purple monkey", "open the garage door", "purple monkey"),
    ("open the garage door passphrase is purple monkey", "open the garage door", "purple monkey"),
    ("turn off guest mode, password: purple monkey.", "turn off guest mode", "purple monkey"),
    ("open the garage door", "open the garage door", None),
])
def test_split_oneshot(text, command, phrase):
    assert split_oneshot(text) == (command, phrase)


def test_lockout_schedule():
    assert [lockout_seconds(n) for n in range(1, 9)] == [0, 0, 30, 60, 120, 180, 240, 300]


def test_attempts_lock_reset_and_expiry():
    a = Attempts()
    assert a.failed(1000) == 0 and a.failed(1001) == 0
    assert a.failed(1002) == 30 and a.locked_for(1010) == 22
    assert a.failed(1040) == 60 and a.failed(1200) == 120
    a.succeeded()
    assert a.misses == 0 and a.locked_for(1201) == 0
    a.failed(5000)
    a.failed(5000 + RESET_AFTER + 1)                 # 6 hours without a miss: counting starts again
    assert a.misses == 1
    assert Attempts.from_dict(a.to_dict()) == a


def test_replies_never_contain_the_passphrase():
    replies = [say_wrong("the garage door stays closed", 30), say_not_heard("guest mode stays on"),
               say_oneshot_help("open the garage door"), say_wait(90), say_wait(30)]
    for r in replies:
        assert normalize(SECRET) not in normalize(r)
    assert say_not_heard("the garage door stays closed") == \
        "I didn't catch the passphrase, so the garage door stays closed."
    assert say_wrong("guest mode stays on", 60) == ("That's not the passphrase, so guest mode stays on. "
                                                    "Too many wrong tries. Voice unlocking is paused for 1 minute.")


DOORS = {"door": {"garage door": "cover.garage_door", "front door": "lock.front_door",
                  "front door lock": "lock.front_door"},
         "tv_app": {"netflix": "com.netflix.ninja"}}


@pytest.mark.parametrize("text,intent,door", [
    ("open the garage door", "DoorOpen", "cover.garage_door"), ("unlock the front door", "DoorOpen", "lock.front_door"),
    ("lock the front door lock", "DoorClose", "lock.front_door"), ("close the garage door", "DoorClose", "cover.garage_door"),
    ("is the garage door open", "DoorStatus", "cover.garage_door"),
])
def test_door_sentences(text, intent, door):
    r = recognize(text, [], lists=DOORS)
    assert (r.intent, r.slots["door"]) == (intent, door)


def test_door_sentence_negatives():
    assert recognize("open netflix", [], lists=DOORS).intent == "TvApp"
    assert recognize("open the garage door", [], lists={}) is None     # no protected doors: Home Assistant's own
    assert recognize("open the window", [], lists=DOORS) is None


def test_guests_left():
    assert recognize("the guests left", []).intent == "GuestOff"
    assert recognize("turn off guest mode", []).intent == "GuestOff"
