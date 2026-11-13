"""Voice training (experimental), pure parts: what starts and stops it, the phrase-by-phrase
conversation, the pending capture slot, WAV files, clip names and which pipelines get switched."""
import struct
from datetime import datetime

import pytest

from core.voicetrain import (
    PHRASES,
    CaptureHub,
    CaptureSlot,
    Session,
    clip_name,
    count_text,
    duration,
    intro,
    is_stop,
    is_stop_training,
    parse_start,
    person_slug,
    pick_underlying,
    pipeline_plan,
    step,
    too_short,
    wav_bytes,
    wav_header,
)


@pytest.mark.parametrize("text,expected", [
    ("train my voice", (True, None)),
    ("Learn my voice.", (True, None)),
    ("voice training", (True, None)),
    ("start voice training please", (True, None)),
    ("train Rob's voice", (True, "rob")),
    ("Train Rob’s voice", (True, "rob")),
    ("learn sam s voice", (True, "sam")),
    ("train the dog", None),
    ("train my dog", None),
    ("what's the weather", None),
    ("stop voice training", None),
])
def test_parse_start(text, expected):
    assert parse_start(text) == expected


def test_stop_words():
    assert is_stop("stop voice training") and is_stop("Cancel.") and is_stop("stop")
    assert not is_stop("stop the music") and not is_stop("Turn on the living room lamps")
    assert is_stop_training("stop voice training") and not is_stop_training("cancel")


def test_too_short():
    assert too_short("") and too_short("uh") and too_short("  .  ")
    assert not too_short("What's the weather like today") and not too_short("Tokyo")


def test_full_session_eight_phrases():
    s = Session(person="person.rob", name="Rob", token="t")
    assert intro("Rob").endswith(f"Please say: {PHRASES[0]}.")
    for i in range(1, len(PHRASES)):
        s.saved = i
        r = step(s, PHRASES[i - 1])
        assert (r.reply, r.done, r.arm) == (f"{PHRASES[i]}.", False, True)
        assert s.index == i
    s.saved = 8
    r = step(s, PHRASES[-1])
    assert r.done and not r.arm and r.reply == "Done. I saved 8 samples of Rob's voice."


def test_reask_twice_then_skip():
    s = Session(person="person.rob", name="Rob")
    r = step(s, "uh")
    assert r.reply == f"I didn't catch that. Try again: {PHRASES[0]}." and s.index == 0 and r.arm
    r = step(s, "Turn on the living room lamps")       # a different sentence: asked again
    assert r.reply == f"That didn't sound like the phrase. Try again: {PHRASES[0]}." and s.index == 0
    r = step(s, "")                                   # asked twice already: skip it
    assert r.reply == f"Let's skip that one. {PHRASES[1]}." and s.index == 1
    r = step(s, "")                                   # the new phrase gets its own re-asks
    assert r.reply.startswith("I didn't catch that.") and s.index == 1


def test_matches_phrase():
    from core.voicetrain import matches_phrase
    assert matches_phrase("Set a timer for ten minutes", "Set a timer for 10 minutes.")
    assert matches_phrase("Remind me to take out the trash at seven", "Remind me to take out the trash at 7:00.")
    assert matches_phrase("What's the weather like today", "whats the weather today")
    # clip 1 from the first real session: the TV / someone else talking
    assert not matches_phrase("What's the weather like today",
                              "Thinking next time somethings. I asked for A2 appraisal. Safe stop voice came on the final.")
    assert not matches_phrase("What's the weather like today", "What's the weather like today and also tell me "
                              "about the news and the traffic on the way to work")
    assert not matches_phrase("How did I sleep last night", "")


def test_cancel_reports_what_was_kept():
    s = Session(person="person.rob", name="Rob", saved=0)
    r = step(s, "cancel")
    assert r.done and not r.arm and r.reply == "Okay, I stopped voice training."
    s = Session(person="person.rob", name="Rob", saved=3, index=3)
    assert step(s, "stop voice training").reply == "Okay, I stopped voice training. I kept 3 samples."


def test_finish_without_recordings_explains():
    s = Session(person="person.rob", name="Rob", index=len(PHRASES) - 1)
    r = step(s, PHRASES[-1])
    assert r.done and "Better Assistant speech-to-text" in r.reply


def test_slot_is_taken_once_and_expires():
    hub = CaptureHub()
    hub.arm(CaptureSlot(person="person.rob", label="train", token="a"), now=100.0)
    assert hub.take(129.0).token == "a"
    assert hub.take(129.0) is None                    # used up
    hub.arm(CaptureSlot(person="person.rob", label="train", token="b"), now=100.0)
    assert hub.take(131.0) is None and hub.slot is None   # expired, and cleared
    hub.arm(CaptureSlot(person="p", label="train", token="c"), now=0.0)
    hub.disarm("other")
    assert hub.slot is not None
    hub.disarm("c")
    assert hub.slot is None
    hub.note_saved("c"), hub.note_saved("c"), hub.note_saved("")
    assert hub.saved_for("c") == 2 and hub.saved_for("") == 0


def test_wav_header_and_bytes():
    header = wav_header(32000, 16000)
    assert len(header) == 44
    riff, size, wave, fmt, fmt_len, pcm, ch, rate, byte_rate, block, bits, data, data_len = \
        struct.unpack("<4sI4s4sIHHIIHH4sI", header)
    assert (riff, wave, fmt, data) == (b"RIFF", b"WAVE", b"fmt ", b"data")
    assert (size, fmt_len, pcm, ch, rate, byte_rate, block, bits, data_len) == \
        (36 + 32000, 16, 1, 1, 16000, 32000, 2, 16, 32000)
    out = wav_bytes(b"\x01\x02\x03", 16000)           # odd byte dropped: whole samples only
    assert len(out) == 46 and out[-2:] == b"\x01\x02" and struct.unpack("<I", out[40:44])[0] == 2
    assert duration(32000, 16000) == 1.0


def test_wav_is_readable_by_the_wave_module(tmp_path):
    import wave
    path = tmp_path / "a.wav"
    path.write_bytes(wav_bytes(b"\x00\x00" * 8000, 16000))
    with wave.open(str(path)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (1, 2, 16000, 8000)


def test_names_and_counts():
    assert person_slug("person.rob_smith") == "rob_smith"
    assert person_slug(None) == person_slug("unknown") == "unknown"
    assert clip_name(datetime(2026, 11, 13, 7, 15, 2), 3) == "20261113T071502Z_3"
    assert count_text({}) == "none yet"
    assert count_text({("train", "rob"): 8, ("test", "rob"): 2, ("test", "unknown"): 1}) == \
        "rob: 8 training, 2 test; unknown: 1 test"


def test_pick_underlying():
    own = "better_assistant"
    assert pick_underlying([("stt.better_assistant_speech_to_text", own), ("stt.faster_whisper", "wyoming"),
                            ("stt.home_assistant_cloud", "cloud")], own) == "stt.home_assistant_cloud"
    assert pick_underlying([("stt.x", "other"), ("stt.faster_whisper", "wyoming")], own) == "stt.faster_whisper"
    assert pick_underlying([("stt.x", "other")], own) == "stt.x"
    assert pick_underlying([("stt.better_assistant_speech_to_text", own)], own) is None


def test_pipeline_plan_switch_and_restore():
    ours = "stt.ba"
    current = {"p1": "stt.cloud", "p2": "stt.whisper", "p3": ours}
    changes, kept = pipeline_plan(["p1"], {}, current, ours, True, fallback="stt.cloud")
    assert changes == {"p1": ours, "p3": "stt.cloud"} and kept == {"p1": "stt.cloud"}
    current = {"p1": ours, "p2": "stt.whisper"}
    changes, kept = pipeline_plan(["p1", "p2"], {"p1": "stt.cloud"}, current, ours, True)
    assert changes == {"p2": ours} and kept == {"p1": "stt.cloud", "p2": "stt.whisper"}
    current = {"p1": ours, "p2": ours}
    changes, kept = pipeline_plan(["p1", "p2"], kept, current, ours, False)    # feature off: all back
    assert changes == {"p1": "stt.cloud", "p2": "stt.whisper"} and kept == {}
    changes, kept = pipeline_plan([], {"gone": "stt.cloud"}, {}, ours, True)
    assert changes == {} and kept == {}


def test_echo_of_own_reply_gets_a_short_go_ahead():
    from core.voicetrain import NOTHING_HEARD
    s = Session(person="person.rob", name="Rob", index=1,
                last_said=f"That didn't sound like the phrase. Try again: {PHRASES[1]}.")
    r = step(s, "Deep shade of blue.")                 # the speaker heard the end of its own reply
    assert r.reply == "Go ahead." and r.arm and s.index == 1
    s.last_said = r.reply
    r = step(s, NOTHING_HEARD)                        # sound but no words: asked again, not ended
    assert r.reply == f"I didn't catch that. Try again: {PHRASES[1]}." and not r.done
    s.last_said = r.reply
    r = step(s, PHRASES[1])
    assert r.reply == f"{PHRASES[2]}." and s.index == 2


def test_clipped_start_counts_when_the_speaker_is_silent():
    from core.voicetrain import matches_phrase
    # what the speaker really recorded after its ding (the first words lost)
    assert matches_phrase("How did I sleep last night", "Sleep last night.", tail_ok=True)
    assert matches_phrase("Remind me to take out the trash at seven", "Take out the trash at 7.", tail_ok=True)
    assert matches_phrase("What's on my calendar tomorrow", "Let's on my calendar tomorrow.")
    assert not matches_phrase("Remind me to take out the trash at seven", "7.", tail_ok=True)
    assert not matches_phrase("How did I sleep last night", "Sleep last night.")          # speaker talks: no
    assert not matches_phrase("How did I sleep last night", "Last night the game was great", tail_ok=True)
