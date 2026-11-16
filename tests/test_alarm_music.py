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
    s._ringing, s._ring_targets, s._ring_meta, s._just_stopped, s._snoozed_until = {}, {}, {}, {}, {}
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
    assert s._wake_music(DEFAULT_MUSIC) == "last"                  # "with music": what played last
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


# ------------------------------------------------------------------ stopping the tone
async def _tone(hass):
    s = skills(hass)
    hass.states.async_set(SAT, "idle")
    hass.states.async_set(TONE_PLAYER, "idle")

    async def play(call):
        s.calls.append(("tone", dict(call.data)))
        hass.states.async_set(TONE_PLAYER, "playing", context=call.context)

    hass.services.async_register("media_player", "play_media", play)
    task = asyncio.ensure_future(s._ring_tone("k", [TONE_PLAYER], "http://x/alarm.mp3", [SAT]))
    for _ in range(100):
        await asyncio.sleep(0.01)
        if s.calls:
            break
    return s, task


async def test_the_speakers_own_stop_ends_the_alarm(hass):
    s, task = await _tone(hass)
    assert "announce" not in s.calls[0][1]                     # media, so the wake word still works
    hass.states.async_set(TONE_PLAYER, "idle")                 # "stop" said to the Voice PE itself
    await asyncio.wait_for(task, 4)
    assert len([c for c in s.calls if c[0] == "tone"]) == 1     # not played again


async def test_a_request_in_progress_doesnt_end_the_alarm(hass):
    s, task = await _tone(hass)
    hass.states.async_set(SAT, "listening")                     # wake word: the tone pauses for the request
    hass.states.async_set(TONE_PLAYER, "idle")
    await asyncio.sleep(2.5)
    assert not task.done() and len(s.calls) == 1                # still ringing, but quiet while it listens
    hass.states.async_set(SAT, "idle")
    await asyncio.sleep(1.5)
    assert len([c for c in s.calls if c[0] == "tone"]) == 2     # back on once the speaker is free
    task.cancel()


async def test_anything_said_while_ringing_stops_or_snoozes(hass):
    from homeassistant.components.conversation import ConversationInput
    from homeassistant.core import Context
    s = skills(hass)
    s.recognize = lambda text: recognize(text, ["rob"])
    s.satellite_for = lambda ui: SAT
    s._ring_targets["k"] = [SAT]
    s._ringing["k"] = object()
    said = []

    async def stop(slots, ui):
        said.append("stop")
        return "Alarm off."

    async def snooze(slots, ui):
        said.append(("snooze", slots.get("minutes")))
        return "Okay."

    s._h_alarm_stop, s._h_alarm_snooze = stop, snooze
    ui = ConversationInput(text="x", context=Context(), conversation_id="c", device_id="d", satellite_id=SAT,
                           language="en", agent_id="conversation.x")
    for text in ("Stop alarm.", "okay I'm up", "That's fast. Sorry, that too.", "snooze", "5 more minutes"):
        await s.ringing_reply(text, ui)
    assert said == ["stop", "stop", "stop", ("snooze", None), ("snooze", 5)]
    typed = ConversationInput(text="x", context=Context(), conversation_id="c", device_id=None, satellite_id=None,
                              language="en", agent_id="conversation.x")
    assert await s.ringing_reply("what's the weather", typed) is None   # the app isn't the ringing speaker
    s._ringing.clear()
    assert await s.ringing_reply("stop alarm", ui) is None


def test_stop_alarm_without_the():
    assert recognize("Stop alarm", ["rob"]).intent == "AlarmStop"
    assert recognize("turn the alarm off", ["rob"]).intent == "AlarmStop"


async def test_no_restart_right_after_the_speakers_own_stop(hass):
    """The tone went quiet (the Voice PE's own "stop"): it must not be played again while that's checked."""
    s, task = await _tone(hass)
    hass.states.async_set(TONE_PLAYER, "idle")
    await asyncio.sleep(1.2)                                       # the loop ticks every second
    assert len([c for c in s.calls if c[0] == "tone"]) == 1
    await asyncio.wait_for(task, 3)



# ------------------------------------------------------------------ the speaker's own timer alarm, and snooze
async def test_rings_with_the_speakers_own_timer_and_stops_on_the_speaker(hass):
    """A Voice PE rings its own timer sound (its on-device "stop" works for that); the alarm is over when
    the speaker goes quiet, and "snooze" still works for a minute after."""
    from unittest.mock import patch
    s = skills(hass)
    hass.states.async_set(SAT, "idle")
    hass.states.async_set(TONE_PLAYER, "idle")
    s._timer_device = lambda sat: "device-1"
    s._ring_targets["k"] = [SAT]
    started = []

    async def start_timer(hass_, platform, intent_type, slots, **kw):
        started.append((intent_type, slots, kw["device_id"]))
        hass.loop.call_later(0.2, lambda: hass.states.async_set(TONE_PLAYER, "playing"))

    with patch("custom_components.better_assistant.skills.intent.async_handle", start_timer):
        task = asyncio.ensure_future(s._ring_native("k", [SAT]))
        await asyncio.sleep(1.2)
        assert started == [("HassStartTimer", {"seconds": {"value": 1}, "name": {"value": "alarm"}}, "device-1")]
        assert not task.done()                                     # ringing
        hass.states.async_set(TONE_PLAYER, "idle")                 # "stop", said to the speaker
        assert await asyncio.wait_for(task, 4) is True
    assert s._just_stopped_for(SAT) == ["k"]
    s.snooze_default, s.snooze_limit = (lambda: 5), (lambda: None)
    s._stop_ringing = lambda key: None
    assert "5" in s._snooze(s._just_stopped_for(SAT), None) and f"snooze:k" in s._timers
    assert s._just_stopped_for(SAT) == []
    s._timers.pop("snooze:k")()


async def test_falls_back_to_the_tone_when_the_speaker_doesnt_ring(hass):
    from unittest.mock import patch
    s = skills(hass)
    hass.states.async_set(TONE_PLAYER, "idle")
    s._timer_device = lambda sat: "device-1"

    async def start_timer(*a, **kw):
        pass

    real_sleep = asyncio.sleep
    with patch("custom_components.better_assistant.skills.intent.async_handle", start_timer), \
            patch("custom_components.better_assistant.skills.asyncio.sleep", lambda *_: real_sleep(0)):
        assert await s._ring_native("k", [SAT]) is False


# ------------------------------------------------------------------ picking the sound from a list
def test_sound_values():
    pytest.importorskip("homeassistant")
    from custom_components.better_assistant.alarm_sounds import describe, label, ma_value, parse_ma
    v = ma_value("playlist", "library://playlist/9", "Liked Music (YouTube Music)")
    assert parse_ma(v) == ("playlist", "library://playlist/9", "Liked Music (YouTube Music)")
    assert label(v) == "Playlist: Liked Music (YouTube Music)" and describe(v) == "your Liked Music (YouTube Music) playlist"
    assert label("") == 'Alarm sound (just say "stop")' and label("last") == "Whatever played last"
    assert describe(ma_value("artist", "spotify://artist/1", "Queen")) == "music like Queen"
    assert label("jazz") == "jazz (asked for by voice)" and parse_ma("jazz") is None


async def test_choices_come_from_the_music_assistant_library(hass):
    from homeassistant.config_entries import ConfigEntry, ConfigEntryState
    from custom_components.better_assistant.alarm_sounds import async_choices
    assert await async_choices(hass) == [{"value": "", "label": 'Alarm sound (just say "stop")'}]   # no Music Assistant
    entry = ConfigEntry(version=1, minor_version=1, domain="music_assistant", title="MA", data={}, source="user",
                        options={}, unique_id=None, discovery_keys={}, subentries_data=None)
    hass.config_entries._entries[entry.entry_id] = entry
    entry._async_set_state(hass, ConfigEntryState.LOADED, None)
    library = {"playlist": [{"uri": "library://playlist/9", "name": "Liked Music"}],
               "artist": [{"uri": "spotify://artist/1", "name": "Queen"}], "radio": []}

    async def get_library(call):
        return {"items": library[call.data["media_type"]]}

    from homeassistant.core import SupportsResponse
    hass.services.async_register("music_assistant", "get_library", get_library, supports_response=SupportsResponse.ONLY)
    got = await async_choices(hass, "jazz")
    assert [c["label"] for c in got] == ['Alarm sound (just say "stop")', "Whatever played last", "Playlist: Liked Music",
                                         "Music like Queen", "jazz (asked for by voice)"]


async def test_a_picked_playlist_plays_exactly_that(hass):
    s = skills(hass)
    task = asyncio.ensure_future(s._ring_with_music("k", [MA], "ma:playlist:library://playlist/9|Liked Music", [SAT]))
    for _ in range(50):
        await asyncio.sleep(0.01)
        if s.calls:
            break
    name, data = s.calls[0]
    assert (data["media_id"], data["media_type"], data["radio_mode"]) == ("library://playlist/9", "playlist", False)
    task.cancel()



async def test_music_alarms_start_quiet_and_put_the_volume_back(hass, monkeypatch):
    from custom_components.better_assistant import skills as skills_module
    monkeypatch.setattr(skills_module, "RAMP_SECONDS", 0.24)
    s = skills(hass)
    hass.states.async_set(MA, "idle", {"volume_level": 0.8})
    volumes = []

    async def volume_set(call):
        volumes.append(call.data["volume_level"])

    hass.services.async_register("media_player", "volume_set", volume_set)
    task = asyncio.ensure_future(s._ring_with_music("k", [MA], "jazz", [SAT]))
    await asyncio.sleep(0.6)
    assert volumes[0] == 0.2 and volumes[-1] == 0.8                # a quarter, then up to the usual 80%
    assert volumes == sorted(volumes)
    task.cancel()
    await asyncio.sleep(0.05)
    assert volumes[-1] == 0.8                                       # left as it was
