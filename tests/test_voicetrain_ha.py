"""Voice training (experimental) inside a bare Home Assistant core: the speech-to-text pass-through
(answer unchanged, a WAV only while recording is wanted), the training conversation through the
agent's trainer, and the settings page. Skipped when Home Assistant isn't installed."""
import json
import time
import types
import wave

import pytest

pytest.importorskip("homeassistant")

from homeassistant import bootstrap, config_entries, loader  # noqa: E402
from homeassistant.components import stt  # noqa: E402
from homeassistant.components.conversation import ConversationInput  # noqa: E402
from homeassistant.core import Context, HomeAssistant  # noqa: E402

from custom_components.better_assistant import BetterAssistantRuntimeData, voice_training  # noqa: E402
from custom_components.better_assistant.config_flow import BetterAssistantOptionsFlow  # noqa: E402
from custom_components.better_assistant.core.voicetrain import PHRASES, TURNED_OFF, CaptureSlot  # noqa: E402
from custom_components.better_assistant.skills import Skills  # noqa: E402
from custom_components.better_assistant.store import BetterAssistantStore  # noqa: E402
from custom_components.better_assistant.stt import PassThroughSTT  # noqa: E402
from custom_components.better_assistant.voice_training import VoiceTrainer, hub, voice_root  # noqa: E402

META = stt.SpeechMetadata(language="en", format=stt.AudioFormats.WAV, codec=stt.AudioCodecs.PCM,
                          bit_rate=stt.AudioBitRates.BITRATE_16, sample_rate=stt.AudioSampleRates.SAMPLERATE_16000,
                          channel=stt.AudioChannels.CHANNEL_MONO)


@pytest.fixture
async def hass(tmp_path):
    h = HomeAssistant(str(tmp_path))
    loader.async_setup(h)
    h.config_entries = config_entries.ConfigEntries(h, {})
    await bootstrap.async_load_base_functionality(h)
    yield h
    await h.async_stop(force=True)


class FakeEngine(stt.SpeechToTextEntity):
    """The 'real' engine underneath: reads all audio, answers with a fixed result."""
    supported_languages = ["en", "de"]
    supported_formats = [stt.AudioFormats.WAV]
    supported_codecs = [stt.AudioCodecs.PCM]
    supported_bit_rates = [stt.AudioBitRates.BITRATE_16]
    supported_sample_rates = [stt.AudioSampleRates.SAMPLERATE_16000]
    supported_channels = [stt.AudioChannels.CHANNEL_MONO]

    def __init__(self, result):
        self.result, self.heard = result, b""

    async def async_process_audio_stream(self, metadata, stream):
        async for chunk in stream:
            self.heard += chunk
        return self.result


def make_entry(hass, **options):
    entry = types.SimpleNamespace(entry_id="e1", options={"voice_stt_engine": "stt.fake", **options}, data={})
    entry.async_create_background_task = lambda h, coro, name: h.async_create_background_task(coro, name)
    return entry


@pytest.fixture
def engine(hass, monkeypatch):
    def make(result):
        fake = FakeEngine(result)
        fake.hass, fake.entity_id = hass, "stt.fake"
        fake.async_write_ha_state = lambda: None
        monkeypatch.setattr(stt, "async_get_speech_to_text_engine",
                            lambda _h, eid: fake if eid == "stt.fake" else None)
        hass.states.async_set("stt.fake", "unknown")
        return fake
    return make


async def run_stt(hass, entry, chunks):
    ent = PassThroughSTT(entry)
    ent.hass, ent.entity_id = hass, "stt.better_assistant_speech_to_text"

    async def stream():
        for c in chunks:
            yield c

    result = await ent.async_process_audio_stream(META, stream())
    await hass.async_block_till_done(wait_background_tasks=True)
    return ent, result


def wavs(hass):
    return sorted(voice_root(hass).rglob("*.wav"))


AUDIO = [b"\x01\x00" * 800, b"\x02\x00" * 800]
OK = stt.SpeechResult("Turn on the living room lamps", stt.SpeechResultState.SUCCESS)


async def test_mirrors_the_engine_and_records_nothing_when_off(hass, engine):
    fake = engine(OK)
    ent, result = await run_stt(hass, make_entry(hass), AUDIO)
    assert result is OK and fake.heard == b"".join(AUDIO)
    assert ent.supported_languages == ["en", "de"] and ent.supported_sample_rates == [16000]
    assert ent.check_metadata(META)
    assert wavs(hass) == []


async def test_training_slot_writes_wav_and_sidecar(hass, engine):
    engine(OK)
    hass.states.async_set("person.rob", "home", {"friendly_name": "Rob"})
    hub(hass).arm(CaptureSlot(person="person.rob", label="train", phrase=PHRASES[1], token="tok",
                              satellite="assist_satellite.kitchen", device_id="dev1"), time.time())
    _ent, result = await run_stt(hass, make_entry(hass, voice_training=True), AUDIO)
    assert result is OK
    [path] = wavs(hass)
    assert path.parent.name == "rob" and path.parent.parent.name == "train" and path.stem.endswith("_1")
    with wave.open(str(path)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (1, 2, 16000, 1600)
    meta = json.loads(path.with_suffix(".json").read_text())
    assert meta["person"] == "person.rob" and meta["label"] == "train"
    assert meta["transcript"] == OK.text and meta["prompt"] == PHRASES[1]
    assert meta["satellite"] == "assist_satellite.kitchen" and meta["device_id"] == "dev1"
    assert meta["duration_s"] == 0.1 and "pipeline" in meta
    assert hub(hass).saved_for("tok") == 1 and hub(hass).slot is None


async def test_everyday_requests_are_test_clips(hass, engine):
    engine(OK)
    hass.states.async_set("person.a", "home")
    hass.states.async_set("person.b", "home")
    await run_stt(hass, make_entry(hass, voice_training=True, voice_record_test=True), AUDIO)
    [path] = wavs(hass)
    assert path.parent.name == "unknown" and path.parent.parent.name == "test"


async def test_engine_error_is_returned_unchanged_and_nothing_saved(hass, engine):
    bad = stt.SpeechResult(None, stt.SpeechResultState.ERROR)
    engine(bad)
    hub(hass).arm(CaptureSlot(person="person.rob", label="train", token="t"), time.time())
    _ent, result = await run_stt(hass, make_entry(hass, voice_training=True, voice_record_test=True), AUDIO)
    assert result is bad and wavs(hass) == []


async def test_stop_and_mumbles_are_not_saved(hass, engine):
    engine(stt.SpeechResult("stop voice training", stt.SpeechResultState.SUCCESS))
    await run_stt(hass, make_entry(hass, voice_training=True, voice_record_test=True), AUDIO)
    assert wavs(hass) == []


async def test_capture_failure_never_breaks_stt(hass, engine, monkeypatch):
    engine(OK)
    from custom_components.better_assistant import stt as passthrough
    monkeypatch.setattr(passthrough, "write_clip", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    hub(hass).arm(CaptureSlot(person="person.rob", label="train", token="t2"), time.time())
    _ent, result = await run_stt(hass, make_entry(hass, voice_training=True), AUDIO)
    assert result is OK and wavs(hass) == [] and hub(hass).saved_for("t2") == 0


# --- the training conversation ---

@pytest.fixture
async def house(hass):
    hass.states.async_set("person.rob", "home", {"friendly_name": "Rob Smith", "user_id": "u1"})
    hass.states.async_set("person.sam", "home", {"friendly_name": "Sam"})
    entry = types.SimpleNamespace(entry_id="x", options={"voice_training": True, "voice_training_phone": False}, data={})
    store = BetterAssistantStore(hass, "x")
    await store.async_load()
    entry.runtime_data = BetterAssistantRuntimeData(store=store)
    skills = Skills(hass, entry)
    await skills.async_start()
    trainer = VoiceTrainer(hass, entry)
    yield types.SimpleNamespace(hass=hass, skills=skills, trainer=trainer, entry=entry)
    skills.async_stop()


def ui(text, voice=True, user=None):
    return ConversationInput(text=text, context=Context(user_id=user), conversation_id="c1",
                             device_id="dev1" if voice else None, satellite_id=None, language="en",
                             agent_id="conversation.x")


async def turn(h, text, voice=True, user=None):
    return await h.trainer.async_handle(text, ui(text, voice, user), "c1", h.skills)


async def test_training_runs_eight_phrases(house):
    speech, keep = await turn(house, "train Rob's voice")
    assert keep and speech.startswith("Okay, let's train Rob's voice") and PHRASES[0] in speech
    capture = hub(house.hass)
    for i, phrase in enumerate(PHRASES):
        slot = capture.take(time.time())                   # what the speech-to-text side would do
        assert slot.person == "person.rob" and slot.phrase == phrase and slot.label == "train"
        capture.note_saved(slot.token)
        speech, keep = await turn(house, phrase)
        if i < len(PHRASES) - 1:
            assert keep and speech == f"{PHRASES[i + 1]}."
    assert not keep and speech == "Done. I saved 8 samples of Rob's voice."
    assert house.trainer.active("c1") is None and capture.slot is None
    assert await turn(house, "turn on the lamp") is None    # back to normal commands


async def test_command_words_during_training_are_not_run(house):
    await turn(house, "train my voice", user="u1")          # signed-in user -> Rob
    speech, keep = await turn(house, "Turn on the living room lamps")
    assert keep and speech.startswith("That didn't sound like the phrase. Try again:")


async def test_reask_and_cancel(house):
    await turn(house, "learn Sam's voice")
    speech, keep = await turn(house, "")
    assert keep and speech == f"I didn't catch that. Try again: {PHRASES[0]}."
    speech, keep = await turn(house, "cancel")
    assert not keep and speech == "Okay, I stopped voice training."
    assert hub(house.hass).slot is None


async def test_refusals(house):
    speech, keep = await turn(house, "train my voice")      # two people, no signed-in user
    assert not keep and speech == "Tell me who you are first: say 'train Rob's voice'."
    assert (await turn(house, "train Rob's voice", voice=False))[0] == "Voice training only works from a voice speaker."
    assert "no one named Zed" in (await turn(house, "train Zed's voice"))[0]
    assert (await turn(house, "stop voice training"))[0] == "Voice training isn't running."
    house.entry.options = {}
    assert (await turn(house, "train Rob's voice"))[0].startswith("Voice training is turned off")


# --- the settings page ---

async def test_options_flow(hass, monkeypatch):
    switched = []

    async def switch(_h, entry_id, options, chosen):
        switched.append((options["voice_training"], chosen))
        return {"p1": "stt.cloud"}
    monkeypatch.setattr(voice_training, "async_switch_pipelines", switch)
    monkeypatch.setattr(voice_training, "pipelines", lambda _h: [("p1", "Better Assistant", "stt.cloud")])
    folder = voice_root(hass) / "train" / "rob"
    folder.mkdir(parents=True)
    (folder / "a.wav").write_bytes(b"")
    entry = types.SimpleNamespace(entry_id="e1", options={"web_search": False}, data={})
    flow = BetterAssistantOptionsFlow()
    flow.hass, flow.handler, flow.flow_id = hass, "e1", "o1"
    monkeypatch.setattr(BetterAssistantOptionsFlow, "config_entry", property(lambda _s: entry))
    assert "voice_training" in (await flow.async_step_init())["menu_options"]
    form = await flow.async_step_voice_training()
    assert form["description_placeholders"]["counts"] == "rob: 1 training"
    keys = [str(k) for k in form["data_schema"].schema]
    assert keys == ["voice_training", "voice_record_test", "voice_training_phone", "voice_training_satellite",
                    "voice_stt_engine", "pipelines",
                    "delete_recordings"]
    defaults = {str(k): k.default() for k in form["data_schema"].schema if callable(getattr(k, "default", None))}
    assert defaults["voice_training"] is False and defaults["voice_record_test"] is False
    result = await flow.async_step_voice_training({"voice_training": True, "voice_record_test": False,
                                                   "pipelines": ["p1"], "delete_recordings": True})
    assert result["type"] == "create_entry"
    assert result["data"] == {"web_search": False, "voice_training": True, "voice_record_test": False, "voice_training_phone": True,
                                 "voice_training_satellite": None,
                              "voice_stt_engine": None, "voice_stt_originals": {"p1": "stt.cloud"}}
    assert switched == [(True, ["p1"])] and not voice_root(hass).exists()


async def test_phone_mode_speaker_stays_silent(house, monkeypatch):
    house.entry.options["voice_training_phone"] = True
    sent = []

    async def fake_notify(call):
        sent.append(call.data)
    house.hass.services.async_register("notify", "mobile_app_robs_phone", fake_notify)
    monkeypatch.setattr(house.skills, "phone_for", lambda p: "notify.mobile_app_robs_phone" if p == "person.rob" else None)
    speech, keep = await turn(house, "train Rob's voice")
    assert keep and speech == "Check your phone."
    assert "1 of 8" in sent[-1]["message"] and PHRASES[0] in sent[-1]["message"]
    assert sent[-1]["data"]["tag"] == "better_assistant_voice_training"
    capture = hub(house.hass)
    for i, phrase in enumerate(PHRASES):
        capture.note_saved(capture.take(time.time()).token)
        speech, keep = await turn(house, phrase)
        assert speech == ""                                  # nothing for the speaker's mic to hear
        if i < len(PHRASES) - 1:
            assert keep and f"{i + 2} of 8" in sent[-1]["message"] and PHRASES[i + 1] in sent[-1]["message"]
    assert not keep and sent[-1]["message"] == "Done. I saved 8 samples of Rob's voice."


async def test_phone_mode_without_a_phone_reads_aloud(house):
    house.entry.options["voice_training_phone"] = True
    speech, keep = await turn(house, "train Sam's voice")
    assert keep and speech.startswith("I couldn't find your phone, so I'll read the phrases out.")
    speech, keep = await turn(house, PHRASES[0])
    assert speech == f"{PHRASES[1]}."


async def test_start_button_then_skip_and_stop(house):
    started = []

    async def fake_start(call):
        started.append(call.data)
    house.hass.services.async_register("assist_satellite", "start_conversation", fake_start)
    house.hass.states.async_set("assist_satellite.kitchen", "idle")
    t = house.trainer
    assert t.view["status"] == "idle"

    assert await t.async_start_from_phone(house.skills, "nobody") is not None
    assert await t.async_start_from_phone(house.skills, "u1") is None
    assert started[-1]["entity_id"] == "assist_satellite.kitchen" and not started[-1]["preannounce"]
    assert t.view["status"] == "training" and t.view["current"] == 1 and t.view["name"] == "Rob"
    assert [p["state"] for p in t.view["phrases"]][:2] == ["current", "waiting"]
    slot = hub(house.hass).take(time.time())
    assert slot.person == "person.rob" and slot.phrase == PHRASES[0] and slot.satellite == "assist_satellite.kitchen"

    # the speaker's first turn claims the session; the speaker says nothing, the screen moves on
    inp = ConversationInput(text=PHRASES[0], context=Context(), conversation_id="c9", device_id="dev1",
                            satellite_id="assist_satellite.kitchen", language="en", agent_id="conversation.x")
    assert await t.async_handle(PHRASES[0], inp, "c9", house.skills) == ("", True)
    assert [p["state"] for p in t.view["phrases"]][:3] == ["said", "current", "waiting"]

    speech, _ = await t.async_handle("something else entirely about the news today", inp, "c9", house.skills)
    assert speech == "" and t.view["hint"] == "That didn't sound like the phrase. Try again."

    await t.async_phone_action("BETTER_ASSISTANT_VT_SKIP", house.skills)
    assert [p["state"] for p in t.view["phrases"]][:3] == ["said", "skipped", "current"]
    assert hub(house.hass).slot.phrase == PHRASES[2] and t.view["hint"] == ""
    await t.async_phone_action("BETTER_ASSISTANT_VT_STOP", house.skills)
    assert t.view["status"] == "stopped" and t.active("c9") is None and hub(house.hass).slot is None


async def test_start_from_phone_needs_training_on(house):
    house.entry.options["voice_training"] = False
    assert await house.trainer.async_start_from_phone(house.skills, "u1") == TURNED_OFF


async def test_voice_page_commands(house, monkeypatch):
    from custom_components.better_assistant import voice_panel
    monkeypatch.setattr(voice_panel, "_trainer_and_skills", lambda hass: (house.trainer, house.skills))
    started = []

    async def fake_start(call):
        started.append(call.data)
    house.hass.services.async_register("assist_satellite", "start_conversation", fake_start)
    house.hass.states.async_set("assist_satellite.kitchen", "idle")

    class Conn:
        def __init__(self):
            self.sent, self.results, self.subscriptions = [], [], {}
            self.user = types.SimpleNamespace(id="u1")
        def send_message(self, m): self.sent.append(m)
        def send_result(self, i, r=None): self.results.append((i, r))
        def send_error(self, i, code, text): self.results.append((i, code))

    conn = Conn()
    voice_panel.ws_subscribe(house.hass, conn, {"id": 1, "type": "better_assistant/voice_training/subscribe"})
    assert conn.sent[-1]["event"]["status"] == "idle" and 1 in conn.subscriptions
    voice_panel.ws_action(house.hass, conn, {"id": 2, "type": "x", "action": "start"})   # runs as a task
    await house.hass.async_block_till_done()
    assert started and conn.sent[-1]["event"]["status"] == "training"
    assert conn.sent[-1]["event"]["phrases"][0]["state"] == "current"
    voice_panel.ws_action(house.hass, conn, {"id": 3, "type": "x", "action": "stop"})
    await house.hass.async_block_till_done()
    assert conn.sent[-1]["event"]["status"] == "stopped"
    conn.subscriptions[1]()                                    # unsubscribe
