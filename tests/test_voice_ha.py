"""Voice setup inside a bare Home Assistant core: what's detected, the Supervisor add-on path with a
fake AddonManager, the Docker path, the pipeline and speaker selects, and the flow steps (first
setup and the settings menu). Failures must end in a summary, never a broken setup. Skipped when
Home Assistant isn't installed."""
import enum
import sys
import types

import pytest

pytest.importorskip("homeassistant")

from homeassistant import bootstrap, config_entries, loader  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.helpers import device_registry as dr, entity_registry as er  # noqa: E402

from custom_components.better_assistant import _async_voice_pending  # noqa: E402
from custom_components.better_assistant import voice_flow, voice_setup  # noqa: E402
from custom_components.better_assistant.config_flow import (  # noqa: E402
    BetterAssistantConfigFlow,
    BetterAssistantOptionsFlow,
)
from custom_components.better_assistant.const import DOMAIN, OPT_VOICE_PENDING  # noqa: E402
from custom_components.better_assistant.core.voice import INITIAL_PROMPT, Plan, Report  # noqa: E402
from custom_components.better_assistant.voice_setup import VoiceSetup  # noqa: E402


@pytest.fixture
async def hass(tmp_path):
    h = HomeAssistant(str(tmp_path))
    loader.async_setup(h)
    h.config_entries = config_entries.ConfigEntries(h, {})
    await bootstrap.async_load_base_functionality(h)
    yield h
    await h.async_stop(force=True)


# --- a stand-in for homeassistant.components.hassio.addon_manager (needs the Supervisor client) ---

class AddonState(enum.Enum):
    INSTALLING = "installing"
    NOT_INSTALLED = "not_installed"
    NOT_RUNNING = "not_running"
    RUNNING = "running"


class FakeManager:
    def __init__(self, uri, state=AddonState.NOT_INSTALLED, options=None, fail=None):
        self.uri, self.state, self.options, self.fail, self.calls = uri, state, dict(options or {}), fail, []

    async def async_get_addon_info(self):
        return types.SimpleNamespace(state=self.state, options=dict(self.options))

    async def async_install_addon(self):
        self.calls.append("install")
        if self.fail == "install":
            raise RuntimeError("store unavailable")
        self.state = AddonState.NOT_RUNNING

    async def async_set_addon_options(self, config):
        self.calls.append(("options", config))
        self.options = config

    async def async_start_addon(self):
        self.calls.append("start")
        self.state = AddonState.RUNNING

    async def async_restart_addon(self):
        self.calls.append("restart")

    async def async_get_addon_discovery_info(self):
        return {"uri": self.uri}


@pytest.fixture
def supervisor(monkeypatch):
    """Fake Supervisor: add-on managers per slug, and Wyoming entries that appear when added."""
    pkg = types.ModuleType("homeassistant.components.hassio")
    mod = types.ModuleType("homeassistant.components.hassio.addon_manager")
    mod.AddonState = AddonState
    pkg.addon_manager = mod
    monkeypatch.setitem(sys.modules, "homeassistant.components.hassio", pkg)
    monkeypatch.setitem(sys.modules, "homeassistant.components.hassio.addon_manager", mod)
    managers = {"core_whisper": FakeManager("tcp://core-whisper:10300", options={"model": "tiny-int8", "language": "en", "beam_size": 1,
                                                     "initial_prompt": ""}),
                "core_piper": FakeManager("tcp://core-piper:10200")}
    monkeypatch.setattr(voice_setup, "addon_manager", lambda _h, slug: managers[slug])
    monkeypatch.setattr(voice_setup, "is_supervisor", lambda _h: True)
    wyoming = {}
    monkeypatch.setattr(voice_setup, "wyoming_entity", lambda _h, domain: wyoming.get(domain))

    async def add(self, host, port, quiet=False):
        wyoming["stt" if port == 10300 else "tts"] = "stt.faster_whisper" if port == 10300 else "tts.piper"
        self.report.done.append(f"Added Wyoming at {host}:{port}")
        return True

    async def no_discovery(self, name):
        return False

    monkeypatch.setattr(VoiceSetup, "async_add_wyoming", add)
    monkeypatch.setattr(VoiceSetup, "_async_finish_discovery", no_discovery)
    return types.SimpleNamespace(managers=managers, wyoming=wyoming)


async def nosleep(_s):
    return None


# --- detection ---

async def test_plan_keeps_existing_engines_from_any_provider(hass):
    hass.states.async_set("stt.home_assistant_cloud", "unknown")
    hass.states.async_set("tts.piper", "unknown")
    plan = await voice_setup.async_plan(hass)
    assert plan.stt == "stt.home_assistant_cloud" and plan.tts == "tts.piper"
    assert plan.nothing_to_install and not plan.supervisor


async def test_plan_ignores_unavailable_engines(hass):
    hass.states.async_set("stt.old_whisper", "unavailable")
    plan = await voice_setup.async_plan(hass)
    assert plan.need_stt and plan.need_tts


async def test_plan_notes_installed_addons(hass, supervisor):
    supervisor.managers["core_piper"].state = AddonState.NOT_RUNNING
    plan = await voice_setup.async_plan(hass)
    assert plan.supervisor and plan.piper_installed and not plan.whisper_installed


# --- Supervisor path ---

async def test_install_both_addons_and_wyoming(hass, supervisor):
    vs = VoiceSetup(hass, sleep=nosleep, wait=10)
    await vs.async_install(Plan(stt=None, tts=None, supervisor=True), "base-int8")
    whisper = supervisor.managers["core_whisper"].calls
    assert whisper[0] == "install" and whisper[-1] == "start"
    opts = next(c[1] for c in whisper if isinstance(c, tuple))
    assert opts["model"] == "base-int8" and opts["initial_prompt"] == INITIAL_PROMPT and opts["beam_size"] == 1
    assert supervisor.managers["core_piper"].calls == ["install", "start"]
    assert (vs.stt, vs.tts) == ("stt.faster_whisper", "tts.piper")
    assert not vs.report.manual


async def test_install_skips_what_exists(hass, supervisor):
    vs = VoiceSetup(hass, sleep=nosleep, wait=10)
    await vs.async_install(Plan(stt="stt.home_assistant_cloud", tts=None, supervisor=True), "base-int8")
    assert supervisor.managers["core_whisper"].calls == []
    assert vs.stt == "stt.home_assistant_cloud" and vs.tts == "tts.piper"


async def test_running_whisper_is_restarted_after_option_change(hass, supervisor):
    supervisor.managers["core_whisper"].state = AddonState.RUNNING
    vs = VoiceSetup(hass, sleep=nosleep, wait=10)
    await vs.async_install(Plan(stt=None, tts="tts.x", supervisor=True), "base-int8")
    calls = supervisor.managers["core_whisper"].calls
    assert "install" not in calls and "restart" in calls and "start" not in calls


async def test_failed_install_is_reported_not_raised(hass, supervisor):
    supervisor.managers["core_whisper"].fail = "install"
    vs = VoiceSetup(hass, sleep=nosleep, wait=10)
    await vs.async_install(Plan(stt=None, tts=None, supervisor=True), "base-int8")
    assert vs.stt is None and vs.tts == "tts.piper"
    assert any("Whisper" in m and "store unavailable" in m for m in vs.report.manual)


async def test_wyoming_that_never_appears_is_reported(hass, supervisor, monkeypatch):
    async def refuse(self, host, port, quiet=False):
        return False
    monkeypatch.setattr(VoiceSetup, "async_add_wyoming", refuse)
    vs = VoiceSetup(hass, sleep=nosleep, wait=10)
    await vs.async_install(Plan(stt=None, tts="tts.x", supervisor=True), "base-int8")
    assert vs.stt is None and any("Wyoming" in m for m in vs.report.manual)


async def test_discovery_flow_is_confirmed(hass, monkeypatch):
    configured = []

    class Flows:
        def async_progress_by_handler(self, handler):
            return [{"flow_id": "a", "step_id": "hassio_confirm", "context": {"title_placeholders": {"name": "Piper"}}},
                    {"flow_id": "b", "step_id": "hassio_confirm",
                     "context": {"title_placeholders": {"name": "Whisper"}}}]

        async def async_configure(self, flow_id, data):
            configured.append(flow_id)
            return {"type": "create_entry"}

    monkeypatch.setattr(hass.config_entries, "flow", Flows())
    vs = VoiceSetup(hass)
    assert await vs._async_finish_discovery("Whisper")
    assert configured == ["b"] and vs.report.done == ["Added the Whisper Wyoming integration"]


# --- Docker / Core path ---

async def test_connect_adds_given_hosts(hass, supervisor):
    vs = VoiceSetup(hass, sleep=nosleep)
    await vs.async_connect(Plan(stt=None, tts=None, supervisor=False), ("10.0.0.5", 10300), None)
    assert vs.stt == "stt.faster_whisper" and vs.tts is None
    assert any("text-to-speech" in m for m in vs.report.manual)


# --- pipeline and speakers ---

def _speaker(hass, name, platform="esphome", with_select=True, translation_key="pipeline"):
    devs, ents = dr.async_get(hass), er.async_get(hass)
    entry = config_entries.ConfigEntry(
        data={}, discovery_keys={}, domain=platform, minor_version=1, options={}, source="user",
        subentries_data=None, title=name, unique_id=None, version=1)
    hass.config_entries._entries[entry.entry_id] = entry
    dev = devs.async_get_or_create(config_entry_id=entry.entry_id, identifiers={(platform, name)}, name=name)
    sat = ents.async_get_or_create("assist_satellite", platform, f"{name}-sat", device_id=dev.id,
                                   suggested_object_id=name)
    hass.states.async_set(sat.entity_id, "idle", {"friendly_name": name.title()})
    if with_select:
        ents.async_get_or_create("select", platform, f"{name}-pipeline", device_id=dev.id,
                                 suggested_object_id=f"{name}_assistant", translation_key=translation_key)
    return sat.entity_id


async def test_satellites_skip_cast(hass):
    kitchen = _speaker(hass, "kitchen")
    _speaker(hass, "nest", platform="cast")
    assert voice_setup.satellites(hass) == [(kitchen, "Kitchen")]


async def test_point_speakers_sets_select_or_reports(hass):
    kitchen = _speaker(hass, "kitchen")
    hall = _speaker(hass, "hall", with_select=False)
    calls = []

    async def record(call):
        calls.append(dict(call.data))
    hass.services.async_register("select", "select_option", record)
    report = Report()
    await voice_setup.async_point_speakers(hass, [kitchen, hall], "Better Assistant", report)
    assert calls == [{"entity_id": "select.kitchen_assistant", "option": "Better Assistant"}]
    assert any("Kitchen" in d for d in report.done) and any("Hall" in m for m in report.manual)


async def test_apply_without_our_agent_reports(hass):
    report = Report()
    await voice_setup.async_apply(hass, "nope", "stt.a", "tts.a", True, [], report)
    assert report.manual and not report.done


async def test_apply_survives_pipeline_failure(hass, monkeypatch):
    er.async_get(hass).async_get_or_create("conversation", DOMAIN, "e1")

    async def boom(*_a):
        raise RuntimeError("store not loaded")
    monkeypatch.setattr(voice_setup, "async_pipeline", boom)
    report = Report()
    await voice_setup.async_apply(hass, "e1", "stt.a", "tts.a", True, ["assist_satellite.x"], report)
    assert any("store not loaded" in m for m in report.manual)


async def test_real_pipeline_store_create_then_update(hass, monkeypatch):
    pytest.importorskip("homeassistant.components.assist_pipeline")
    from homeassistant.components import assist_pipeline
    from homeassistant.components.assist_pipeline import pipeline as ap

    async def first_pipeline(_hass, collection):                # stands in for the stock "Home Assistant" one
        return await collection.async_create_item({
            "conversation_engine": "conversation.home_assistant", "conversation_language": "en", "language": "en",
            "name": "Home Assistant", "stt_engine": None, "stt_language": None, "tts_engine": None,
            "tts_language": None, "tts_voice": None, "wake_word_entity": None, "wake_word_id": None})
    monkeypatch.setattr(ap, "_async_create_default_pipeline", first_pipeline)
    await ap.async_setup_pipeline_store(hass)
    report = Report()
    name = await voice_setup.async_pipeline(hass, "conversation.better_assistant", "stt.w", "tts.p", True, report)
    store = hass.data[ap.KEY_ASSIST_PIPELINE].pipeline_store
    made = [p for p in assist_pipeline.async_get_pipelines(hass) if p.name == name]
    assert len(made) == 1 and made[0].conversation_engine == "conversation.better_assistant"
    assert made[0].stt_engine == "stt.w" and made[0].prefer_local_intents
    assert store.async_get_preferred_item() == made[0].id
    await voice_setup.async_pipeline(hass, "conversation.better_assistant", "stt.w2", "tts.p", False, report)
    again = [p for p in assist_pipeline.async_get_pipelines(hass) if p.name == name]
    assert len(again) == 1 and again[0].stt_engine == "stt.w2" and again[0].id == made[0].id
    assert report.done[0].startswith("Created") and any(d.startswith("Updated") for d in report.done)


# --- flows ---

def _config_flow(hass):
    flow = BetterAssistantConfigFlow()
    flow.hass, flow.handler, flow.flow_id = hass, DOMAIN, "f1"
    flow.context = {"source": "user"}
    return flow


async def _drive_progress(flow, result, step):
    """Mocked tasks often finish at once (eager tasks): then the step goes straight to progress_done."""
    if result["type"] == "progress":
        await flow._voice_task
        return await getattr(flow, f"async_step_{step}")()
    return result


async def test_config_flow_skip_creates_entry_without_voice(hass):
    flow = _config_flow(hass)
    result = await flow.async_step_user({})
    assert result["type"] == "menu" and result["menu_options"] == ["voice_auto", "voice_skip"]
    result = await flow.async_step_voice_skip()
    assert result["type"] == "create_entry" and result["options"] == {}


async def test_config_flow_docker_path_leaves_pending_pipeline(hass, monkeypatch):
    async def connect(self, plan, whisper, piper):
        self.stt, self.tts = "stt.faster_whisper", "tts.piper"
    monkeypatch.setattr(VoiceSetup, "async_connect", connect)
    monkeypatch.setattr(voice_setup, "is_supervisor", lambda _h: False)
    _speaker(hass, "kitchen")
    flow = _config_flow(hass)
    await flow.async_step_user({})
    result = await flow.async_step_voice_auto()
    assert result["step_id"] == "voice_manual" and "wyoming-whisper" in result["description_placeholders"]["commands"]
    result = await flow.async_step_voice_manual({"whisper_host": "10.0.0.5", "whisper_port": 10300,
                                                 "piper_host": "10.0.0.5", "piper_port": 10200})
    assert flow._manual == (("10.0.0.5", 10300), ("10.0.0.5", 10200))
    result = await _drive_progress(flow, result, "voice_connect")
    assert result["type"] == "progress_done" and result["step_id"] == "voice_pipeline"
    result = await flow.async_step_voice_pipeline()
    assert result["step_id"] == "voice_pipeline"
    result = await flow.async_step_voice_pipeline({"preferred": True, "satellites": ["assist_satellite.kitchen"]})
    assert result["step_id"] == "voice_summary"
    result = await flow.async_step_voice_summary({})
    assert result["type"] == "create_entry"
    assert result["options"][OPT_VOICE_PENDING] == {"stt": "stt.faster_whisper", "tts": "tts.piper",
                                                    "preferred": True, "satellites": ["assist_satellite.kitchen"]}


async def test_config_flow_supervisor_path_confirms_then_installs(hass, supervisor):
    flow = _config_flow(hass)
    await flow.async_step_user({})
    result = await flow.async_step_voice_auto()
    assert result["step_id"] == "voice_confirm" and "Whisper add-on" in result["description_placeholders"]["downloads"]
    flow._voice = VoiceSetup(hass, sleep=nosleep, wait=10)
    result = await flow.async_step_voice_confirm({})
    result = await _drive_progress(flow, result, "voice_install")
    assert result["type"] == "progress_done"
    assert (flow._voice.stt, flow._voice.tts) == ("stt.faster_whisper", "tts.piper")


async def test_config_flow_existing_engines_go_straight_to_pipeline(hass):
    hass.states.async_set("stt.home_assistant_cloud", "unknown")
    hass.states.async_set("tts.home_assistant_cloud", "unknown")
    flow = _config_flow(hass)
    await flow.async_step_user({})
    result = await flow.async_step_voice_auto()
    assert result["step_id"] == "voice_pipeline"
    assert result["description_placeholders"]["stt"] == "stt.home_assistant_cloud"


async def test_detection_failure_ends_in_summary_and_entry(hass, monkeypatch):
    async def boom(_h):
        raise RuntimeError("no registry")
    monkeypatch.setattr(voice_flow, "async_plan", boom)
    flow = _config_flow(hass)
    await flow.async_step_user({})
    result = await flow.async_step_voice_auto()
    assert result["step_id"] == "voice_summary" and "no registry" in result["description_placeholders"]["summary"]
    assert (await flow.async_step_voice_summary({}))["type"] == "create_entry"


async def test_failed_task_still_reaches_pipeline_step(hass, monkeypatch):
    async def connect(self, *_a):
        raise RuntimeError("socket closed")
    monkeypatch.setattr(VoiceSetup, "async_connect", connect)
    monkeypatch.setattr(voice_setup, "is_supervisor", lambda _h: False)
    flow = _config_flow(hass)
    await flow.async_step_user({})
    await flow.async_step_voice_auto()
    result = await flow.async_step_voice_manual({})
    if result["type"] == "progress":
        with pytest.raises(RuntimeError):
            await flow._voice_task
        result = await flow.async_step_voice_connect()
    assert result["type"] == "progress_done" and any("socket closed" in m for m in flow._voice.report.manual)


async def test_options_flow_applies_directly(hass, monkeypatch):
    applied = []

    async def apply(_h, entry_id, stt, tts, preferred, chosen, report):
        applied.append((entry_id, stt, tts, preferred, chosen))
        report.done.append("Created")
    monkeypatch.setattr(voice_flow, "async_apply", apply)
    hass.states.async_set("stt.home_assistant_cloud", "unknown")
    hass.states.async_set("tts.home_assistant_cloud", "unknown")
    entry = types.SimpleNamespace(entry_id="e1", options={"web_search": False}, data={})
    flow = BetterAssistantOptionsFlow()
    flow.hass, flow.handler, flow.flow_id = hass, "e1", "o1"
    monkeypatch.setattr(BetterAssistantOptionsFlow, "config_entry", property(lambda _s: entry))
    assert "voice_setup" in (await flow.async_step_init())["menu_options"]
    await flow.async_step_voice_auto()
    result = await flow.async_step_voice_pipeline({"preferred": False})
    assert applied == [("e1", "stt.home_assistant_cloud", "tts.home_assistant_cloud", False, [])]
    result = await flow.async_step_voice_summary({})
    assert result["type"] == "create_entry" and result["data"] == {"web_search": False}


# --- the pending request carried out after first setup ---

async def test_pending_voice_setup_runs_once_and_notifies(hass, monkeypatch):
    applied, updated, notes = [], [], []

    async def apply(_h, entry_id, stt, tts, preferred, chosen, report):
        applied.append((entry_id, stt, chosen))
        report.done.append("Created")
    monkeypatch.setattr(voice_setup, "async_apply", apply)
    monkeypatch.setattr(hass.config_entries, "async_update_entry",
                        lambda entry, options: updated.append(options))
    from homeassistant.components import persistent_notification
    monkeypatch.setattr(persistent_notification, "async_create",
                        lambda _h, message, title, notification_id: notes.append(message))
    pending = {"stt": "stt.w", "tts": "tts.p", "preferred": True, "satellites": ["assist_satellite.k"]}
    entry = types.SimpleNamespace(entry_id="e1", options={OPT_VOICE_PENDING: pending, "x": 1},
                                  runtime_data=types.SimpleNamespace(options={OPT_VOICE_PENDING: pending, "x": 1}))
    await _async_voice_pending(hass, entry)
    assert applied == [("e1", "stt.w", ["assist_satellite.k"])]
    assert updated == [{"x": 1}] and entry.runtime_data.options == {"x": 1}
    assert notes and "Created" in notes[0]


async def test_slow_task_shows_progress_until_done(hass, monkeypatch):
    import asyncio
    gate = asyncio.Event()

    async def connect(self, *_a):
        await gate.wait()
        self.stt = "stt.faster_whisper"
    monkeypatch.setattr(VoiceSetup, "async_connect", connect)
    monkeypatch.setattr(voice_setup, "is_supervisor", lambda _h: False)
    flow = _config_flow(hass)
    await flow.async_step_user({})
    await flow.async_step_voice_auto()
    result = await flow.async_step_voice_manual({"whisper_host": "h"})
    assert result["type"] == "progress" and result["progress_action"] == "voice_connect"
    assert (await flow.async_step_voice_connect())["type"] == "progress"      # asked again while running
    gate.set()
    await flow._voice_task
    result = await flow.async_step_voice_connect()
    assert result["type"] == "progress_done" and flow._voice.stt == "stt.faster_whisper"
