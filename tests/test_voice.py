"""Voice setup decisions: Whisper model per hardware, which add-on options to touch, engine and
language choice, and the confirmation/summary text."""
from core.voice import (
    GB,
    INITIAL_PROMPT,
    Plan,
    Report,
    docker_text,
    download_text,
    is_speaker,
    pick_engine,
    pick_language,
    whisper_model,
    whisper_options,
)


def test_pi3_and_small_arm_boards_get_tiny():
    assert whisper_model("aarch64", 1 * GB, 4) == "tiny-int8"
    assert whisper_model("armv7l", 1 * GB, 4) == "tiny-int8"
    assert whisper_model("aarch64", 2 * GB, 4) == "tiny-int8"


def test_pi4_and_pi5_with_4gb_or_more_get_base_int8():
    assert whisper_model("aarch64", int(3.8 * GB), 4) == "base-int8"   # a 4 GB Pi reports ~3.8
    assert whisper_model("aarch64", 8 * GB, 4) == "base-int8"


def test_x86_gets_base_en_or_small_on_big_machines():
    assert whisper_model("x86_64", 4 * GB, 4) == "base.en"
    assert whisper_model("x86_64", 16 * GB, 4) == "base.en"            # RAM alone isn't enough
    assert whisper_model("x86_64", int(7.7 * GB), 8) == "small-int8"
    assert whisper_model("x86_64", 32 * GB, 16) == "small-int8"


def test_low_ram_x86_gets_tiny():
    assert whisper_model("x86_64", 2 * GB, 8) == "tiny-int8"
    assert whisper_model("", 0, 1) == "tiny-int8"                      # nothing known: play safe


def test_whisper_options_only_sets_keys_the_addon_has():
    current = {"model": "tiny-int8", "language": "en", "beam_size": 1}
    assert whisper_options(current, "base-int8") == {"model": "base-int8"}
    with_prompt = {**current, "initial_prompt": ""}
    assert whisper_options(with_prompt, "base-int8") == {"model": "base-int8", "initial_prompt": INITIAL_PROMPT}
    assert whisper_options({}, "base-int8") == {}
    assert whisper_options({"model": "base-int8", "language": "en"}, "base-int8") == {}


def test_pick_engine_prefers_wyoming_then_cloud():
    assert pick_engine([]) is None
    assert pick_engine([("stt.x", "other"), ("stt.home_assistant_cloud", "cloud")]) == "stt.home_assistant_cloud"
    assert pick_engine([("stt.home_assistant_cloud", "cloud"), ("stt.faster_whisper", "wyoming")]) \
        == "stt.faster_whisper"
    assert pick_engine([("tts.b", "x"), ("tts.a", "y")]) == "tts.a"


def test_pick_language():
    assert pick_language(None) == "en"
    assert pick_language(["de", "en"]) == "en"
    assert pick_language(["en_GB", "en_US"]) == "en_US"
    assert pick_language(["en-GB"]) == "en-GB"
    assert pick_language(["en_AU", "de_DE"]) == "en_AU"
    assert pick_language(["de_DE"]) == "en"


def test_cast_and_google_are_not_voice_speakers():
    assert is_speaker("esphome") and is_speaker("wyoming") and is_speaker(None)
    assert not is_speaker("cast") and not is_speaker("google_assistant_sdk")


def test_plan_and_download_text():
    plan = Plan(stt=None, tts="tts.home_assistant_cloud", supervisor=True)
    assert plan.need_stt and not plan.need_tts and not plan.nothing_to_install
    text = download_text(plan, "base-int8")
    assert "Whisper" in text and "base-int8" in text and "Piper" not in text
    plan.whisper_installed = True
    assert "already installed" in download_text(plan, "base-int8")
    assert Plan(stt="stt.a", tts="tts.a", supervisor=False).nothing_to_install
    assert "Nothing" in download_text(Plan(stt="stt.a", tts="tts.a", supervisor=True), "tiny-int8")


def test_docker_text_uses_model_and_ports():
    text = docker_text("tiny-int8")
    assert "--model tiny-int8" in text and "10300:10300" in text and "10200:10200" in text
    assert "rhasspy/wyoming-whisper" in text and "rhasspy/wyoming-piper" in text


def test_report_text():
    r = Report()
    assert r.text() == "Done:\n- nothing"
    r.done.append("Installed Whisper")
    r.manual.append("Add Piper")
    assert "Installed Whisper" in r.text() and "Still to do by hand:\n- Add Piper" in r.text()
