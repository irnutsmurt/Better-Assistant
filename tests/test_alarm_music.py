"""Waking up to music: the wording ("wake me up to Taylor Swift at 7"), the wake-up music setting, and
ringing through Music Assistant with the tone as a fallback when the music doesn't start."""
import asyncio
import types

import pytest

from core.features import DEFAULT_MUSIC, TONE, alarm_change, split_alarm_music
from core.intents import recognize


@pytest.mark.parametrize("text,expected", [
    ("to taylor swift at 7", ("at 7", "taylor swift")),
    ("up to the beatles tomorrow at 6:30", ("tomorrow at 6:30", "the beatles")),
    ("7 with my morning playlist", ("7", "my morning playlist")),
    ("for 7 playing jazz", ("for 7", "jazz")),
    ("with jazz at 7", ("at 7", "jazz")),
    ("for 7 with jazz in the kitchen", ("for 7 in the kitchen", "jazz")),
    ("for 7 with queen everywhere", ("for 7 everywhere", "queen")),
    ("at 7 with music", ("at 7", DEFAULT_MUSIC)),
    ("for 7 with the normal tone", ("for 7", TONE)),
    ("for 7 in the kitchen", ("for 7 in the kitchen", None)),
    ("at 7 to go to work", ("at 7 to go to work", None)),
])
def test_what_to_wake_up_to(text, expected):
    assert split_alarm_music(text) == expected


@pytest.mark.parametrize("text,intent,slots", [
    ("wake me up to Taylor Swift at 7", "AlarmSet", {"text": "to Taylor Swift at 7"}),
    ("set an alarm for 7 with jazz", "AlarmSet", {"text": "7 with jazz"}),
    ("set a music alarm for 7", "AlarmSet", {"text": "7", "music": "default"}),
    ("change my wake-up music to my morning playlist", "AlarmMusic", {"text": "my morning playlist"}),
    ("change my alarm sound to the beatles", "AlarmMusic", {"text": "the beatles"}),
    ("make my alarm play taylor swift", "AlarmMusic", {"text": "taylor swift"}),
    ("what music does my alarm play", "AlarmMusic", {"query": "yes"}),
])
def test_music_alarm_sentences(text, intent, slots):
    m = recognize(text, ["rob"])
    assert m and (m.intent, m.slots) == (intent, slots)


def test_change_my_alarm_to_play():
    assert alarm_change("to play jazz") == ("music", "jazz", None)


# ------------------------------------------------------------------ inside Home Assistant
@pytest.fixture
async def hass(tmp_path):
    pytest.importorskip("homeassistant")
    from homeassistant import bootstrap, config_entries, loader
    from homeassistant.core import HomeAssistant
    h = HomeAssistant(str(tmp_path))
    loader.async_setup(h)
    h.config_entries = config_entries.ConfigEntries(h, {})
    await bootstrap.async_load_base_functionality(h)
    yield h
    await h.async_stop(force=True)


SAT = "assist_satellite.living"
MA = "media_player.living_music"
TONE_PLAYER = "media_player.living_voice"


def skills(hass, music_option="", starts=True):
    """Skills with one voice speaker, its Music Assistant player and a fake Music Assistant."""
    from custom_components.better_assistant.skills import Skills
    s = Skills.__new__(Skills)
    s.hass = hass
    s.entry = types.SimpleNamespace(options={"alarm_music": music_option})
    s.store = types.SimpleNamespace(detected={"satellites": [{"entity_id": SAT, "here_player": MA}]},
                                    data={"alarms": {}}, changed=lambda: None)
    s._own_contexts, s._timers, s._snooze_count, s._ring_music = set(), {}, {}, {}
    s._ringing, s._ring_targets, s._ring_meta = {}, {}, {}
    s.media_player_for = lambda sat: TONE_PLAYER
    s.calls = []
    hass.states.async_set(MA, "idle")

    async def play_media(call):
        s.calls.append(("play_media", dict(call.data)))
        if starts:
            hass.states.async_set(MA, "playing")

    async def media(call):
        s.calls.append((call.service, dict(call.data)))
        if call.service in ("media_stop", "media_pause"):
            hass.states.async_set(MA, "idle", context=call.context)

    hass.services.async_register("music_assistant", "play_media", play_media)
    for svc in ("media_play", "media_stop", "media_pause", "play_media"):
        hass.services.async_register("media_player", svc, media)
    return s


async def test_which_music_an_alarm_plays(hass):
    s = skills(hass, music_option="my morning playlist")
    assert s._wake_music(None) == "my morning playlist"            # the setting
    assert s._wake_music("jazz") == "jazz"                         # this alarm's own
    assert s._wake_music(TONE) is None
    assert s._wake_music(DEFAULT_MUSIC) == "my morning playlist"
    s.entry.options["alarm_music"] = ""
    assert s._wake_music(None) is None                             # nothing set: the tone
    assert s._wake_music(DEFAULT_MUSIC) == ""                      # "with music": what played last
    assert s._say_music("jazz") == " It will play jazz."


async def test_music_rings_and_stops_when_paused(hass):
    from homeassistant.core import Context
    s = skills(hass)
    task = asyncio.ensure_future(s._ring_with_music("k", [MA], "my morning playlist", [SAT]))
    for _ in range(50):
        await asyncio.sleep(0.01)
        if s.calls:
            break
    name, data = s.calls[0]
    assert name == "play_media" and data["media_id"] == "morning" and data["media_type"] == "playlist"
    assert data["radio_mode"] is False and s._ring_music["k"] == [MA]
    s._own_contexts.clear()
    # someone says "stop" (Home Assistant pauses the player) after it has settled
    real = hass.loop.time
    hass.loop.time = lambda: real() + 10
    try:
        await hass.services.async_call("media_player", "media_pause", {"entity_id": MA}, blocking=True,
                                       context=Context())
        assert await asyncio.wait_for(task, 2) is True
    finally:
        hass.loop.time = real
    assert "k" not in s._ring_music
    assert ("media_stop", {"entity_id": [MA]}) in s.calls


async def test_falls_back_to_the_tone_when_music_doesnt_start(hass, monkeypatch):
    s = skills(hass, starts=False)
    real_sleep = asyncio.sleep
    monkeypatch.setattr(asyncio, "sleep", lambda *_: real_sleep(0))
    assert await s._ring_with_music("k", [MA], "jazz", [SAT]) is False
    assert s.calls[0][1]["radio_mode"] is True and "k" not in s._ring_music
    assert s.calls[-1] == ("media_stop", {"entity_id": [MA]})


async def test_set_an_alarm_with_music(hass):
    s = skills(hass)
    s._place_targets = lambda place, ui: ([SAT], None)
    s.speaker_person = s.satellite_for = lambda ui: None
    s._schedule_alarm = lambda key: None
    s._where = lambda targets: "on the living room speaker"
    s._alarms = lambda: s.store.data["alarms"]
    reply = await s._h_alarm_set({"text": "to taylor swift at 7 am"}, None)
    alarm = next(iter(s.store.data["alarms"].values()))
    assert (alarm["hour"], alarm["music"]) == (7, "taylor swift")
    assert reply.endswith("on the living room speaker. It will play taylor swift.")
    s.store.data["alarms"].clear()
    await s._h_alarm_set({"text": "7"}, None)
    assert "music" not in next(iter(s.store.data["alarms"].values()))
