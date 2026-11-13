"""Sentence picking and phrasing, with canned LLM Context payloads (no network)."""
import pytest

from core import search
from core.search import best_answer, compose, dictionary_word, spoken


def payload(*pages):
    """pages: (url, [snippets]) -> LLM Context-shaped JSON."""
    return {"grounding": {"generic": [{"url": u, "snippets": s} for u, s in pages]},
            "sources": {u: {"hostname": u.split("/")[2]} for u, _ in pages}}


def test_prefers_real_definition_sentence():
    data = payload(("https://www.example.org/space", [
        "Black holes are among the strangest things astronomers have ever studied in space. "
        "A black hole is a region of spacetime where gravity is so strong that nothing can escape it."]))
    answer, host = best_answer("what is a black hole", data)
    assert answer.startswith("A black hole is a region of spacetime")
    assert host == "example.org"


def test_dependent_sentence_is_penalised():
    data = payload(("https://www.vethelp.example/grapes", [
        "Other dogs can eat grapes and raisins for years without showing any problems at all. "
        "Grapes and raisins are toxic to dogs and can cause sudden kidney failure."]))
    answer, _ = best_answer("can dogs eat grapes", data)
    assert answer.startswith("Grapes and raisins are toxic")


def test_json_and_metadata_are_filtered():
    data = payload(("https://example.com/a", [
        '{"@type": "Article", "headline": "Can dogs eat grapes? Dogs eat grapes facts"}\n'
        "Sign up for our newsletter to learn whether dogs can eat grapes safely.\n"
        "Veterinarians agree that grapes are dangerous for dogs to eat in any amount."]))
    answer, _ = best_answer("can dogs eat grapes", data)
    assert answer == "Veterinarians agree that grapes are dangerous for dogs to eat in any amount."


def test_nothing_relevant_returns_empty():
    data = payload(("https://example.com/a", ["Cookie settings. All rights reserved by the publisher here."]))
    assert best_answer("how tall is mount everest", data) == ("", "")


def test_spoken_source_phrasing():
    assert spoken("The maximum daily dose is 4,000 mg.", "webmd.com") == \
        "From webmd dot com, the maximum daily dose is 4,000 mg."
    assert spoken("NASA says it is far.", "nasa.gov") == "From nasa dot gov, NASA says it is far."
    assert spoken("Hello there.", "") == "Hello there."


def test_compose_with_and_without_source():
    data = payload(("https://www.webmd.com/drugs/tylenol", [
        "The maximum daily dose of Tylenol for healthy adults is 4,000 mg in a day."]))
    q = "what is the maximum dose of tylenol in a day"
    text, _ = compose(q, data, "drugs", ["drugs.com"])
    assert text.startswith("From webmd dot com, the maximum daily dose of Tylenol")
    text, _ = compose(q, data, "drugs", ["drugs.com"], speak_source=False)
    assert text.startswith("The maximum daily dose")


def test_merriam_webster_definition():
    data = payload(("https://www.merriam-webster.com/dictionary/ubiquitous", [
        "The meaning of UBIQUITOUS is existing or being everywhere at the same time : constantly encountered. "
        "How to use ubiquitous in a sentence."]))
    word = dictionary_word("what does ubiquitous mean")
    assert word == "ubiquitous"
    text, is_def = compose("what does ubiquitous mean", data, "definition", (), word)
    assert is_def
    assert text == ("From merriam-webster dot com, ubiquitous means existing or being everywhere "
                    "at the same time, constantly encountered.")


class FakeResponse:
    def __init__(self, status, data):
        self.status, self._data = status, data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self, content_type=None):
        return self._data


class FakeSession:
    def __init__(self, status=200, data=None):
        self.status, self.data, self.calls = status, data or {}, []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(params)
        return FakeResponse(self.status, self.data)


def slots(n):
    left = [n]

    async def take():
        if left[0] <= 0:
            return False
        left[0] -= 1
        return True
    return take


async def test_answer_end_to_end():
    data = payload(("https://www.example.org/everest", [
        "Mount Everest is 29,032 feet tall, the highest mountain above sea level on Earth."]))
    session = FakeSession(data=data)
    res = await search.answer(session, "k", "how tall is mount everest", slots(5), country="gb")
    assert res["ok"] and res["answer"].startswith("From example dot org, mount Everest is 29,032 feet")
    assert session.calls[0]["country"] == "gb" and "goggles" not in session.calls[0]


async def test_answer_routes_with_goggle():
    session = FakeSession(data=payload())
    await search.answer(session, "k", "can dogs eat grapes", slots(5))
    assert "$boost=3,site=aspca.org" in session.calls[0]["goggles"]


async def test_answer_cap_and_auth():
    assert (await search.answer(FakeSession(), "k", "how tall is everest", slots(0)))["reason"] == "cap"
    assert (await search.answer(FakeSession(status=401), "k", "how tall is everest", slots(1)))["reason"] == "auth"
    assert (await search.answer(FakeSession(status=500), "k", "how tall is everest", slots(1)))["reason"] == "error"
    assert (await search.answer(FakeSession(data=payload()), "k", "how tall is everest", slots(1)))["reason"] == "empty"
