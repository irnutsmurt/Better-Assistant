import random

from core.extras import fun_answer, is_what_did_you_hear, time_in_place
from core.guards import is_question, looks_like_command, plan_compound

NAMES = {"kitchen", "porch light", "desk lamp"}


def test_fun():
    rng = random.Random(1)
    assert fun_answer("flip a coin", rng) in ("It's heads.", "It's tails.")
    assert fun_answer("Roll a die", rng).startswith("You rolled a ")
    assert "total of" in fun_answer("roll two dice", rng)
    n = int(fun_answer("pick a number between 1 and 3", rng).split()[-1].rstrip("."))
    assert 1 <= n <= 3
    assert fun_answer("what is a coin", rng) is None


def test_what_did_you_hear():
    assert is_what_did_you_hear("What did you hear?")
    assert is_what_did_you_hear("what did I say")
    assert not is_what_did_you_hear("what did you have for lunch")


def test_time_in_place():
    assert time_in_place("What time is it in Tokyo?") == "Tokyo"
    assert time_in_place("what time is it") is None


def test_question_guard():
    assert is_question("how tall is everest")
    assert is_question("the moon is far away?")
    assert not is_question("lamp on in the hall")


def test_command_guard():
    assert looks_like_command("turn on the desk lamp please", NAMES)
    assert looks_like_command("is the porch light on right now", NAMES)
    assert looks_like_command("lamp on", NAMES)
    assert not looks_like_command("how tall is mount everest", NAMES)


def test_compound_plan():
    assert plan_compound("turn on the desk lamp and the porch light then play jazz", NAMES) == [
        "turn on the desk lamp", "turn on the porch light", "play jazz"]
    assert plan_compound("turn off porch light and desk lamp", NAMES) == [
        "turn off porch light", "turn off desk lamp"]
    assert plan_compound("a and b and c and d and e", NAMES) is None          # more than 4 parts
    assert plan_compound("a and b and c", NAMES, max_parts=2) is None
    assert plan_compound("what is rock and roll", NAMES) == ["what is rock", "roll"]   # dry run rejects later
    assert plan_compound("how tall is everest", NAMES) is None
