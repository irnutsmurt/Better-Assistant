"""Gets a house with nothing set up to a working voice assistant: Whisper and Piper (add-ons on a
Supervisor install, the user's own containers otherwise), their Wyoming entries, a "Better Assistant"
pipeline and the voice speakers switched to it. Every step is best effort: a failure is written to
the report and the next step still runs. Home Assistant parts that may be missing (Supervisor
client, Wyoming, Assist pipeline) are imported only when used."""
from __future__ import annotations

import asyncio
import logging
import os
import platform
from urllib.parse import urlparse

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .core.voice import (
    PIPELINE_NAME,
    PIPER_SLUG,
    WHISPER_SLUG,
    Plan,
    Report,
    is_speaker,
    pick_engine,
    pick_language,
    whisper_model,
    whisper_options,
)

_LOGGER = logging.getLogger(__name__)
WAIT_SECONDS = 240           # first Whisper start downloads its model; give it a few minutes
POLL = 5.0
SUPERVISOR_TRIES = 36          # x POLL: up to 3 minutes while Supervisor finishes starting

ADDONS = {WHISPER_SLUG: ("Whisper", "stt"), PIPER_SLUG: ("Piper", "tts")}


def is_supervisor(hass: HomeAssistant) -> bool:
    try:
        from homeassistant.helpers.hassio import is_hassio  # noqa: PLC0415
    except ImportError:                                      # older cores: only in the component
        return "hassio" in hass.config.components
    return is_hassio(hass)


def _hardware() -> tuple[str, int, int]:
    """(arch, total RAM in bytes, cpu count). Runs in the executor."""
    ram = 0
    try:
        with open("/proc/meminfo", encoding="ascii") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    ram = int(line.split()[1]) * 1024
                    break
    except OSError:
        pass
    return platform.machine(), ram, os.cpu_count() or 1


async def async_choose_model(hass: HomeAssistant) -> str:
    return whisper_model(*await hass.async_add_executor_job(_hardware))


def addon_manager(hass: HomeAssistant, slug: str):
    """One AddonManager per add-on per run of Home Assistant (it tracks its own tasks)."""
    from homeassistant.components.hassio.addon_manager import AddonManager  # noqa: PLC0415
    managers = hass.data.setdefault(f"{DOMAIN}_addons", {})
    if slug not in managers:
        managers[slug] = AddonManager(hass, _LOGGER, ADDONS[slug][0], slug)
    return managers[slug]


@callback
def engines(hass: HomeAssistant, domain: str) -> list[tuple[str, str]]:
    """(entity_id, platform) of every working speech entity of a domain, any provider."""
    reg = er.async_get(hass)
    out = []
    for state in hass.states.async_all(domain):
        if state.state == "unavailable":
            continue
        entry = reg.async_get(state.entity_id)
        out.append((state.entity_id, entry.platform if entry else ""))
    return out


@callback
def wyoming_entity(hass: HomeAssistant, domain: str) -> str | None:
    """An stt/tts entity belonging to a Wyoming config entry, if one exists."""
    reg = er.async_get(hass)
    for entry in hass.config_entries.async_entries("wyoming"):
        for ent in er.async_entries_for_config_entry(reg, entry.entry_id):
            if ent.domain == domain and not ent.disabled_by:
                return ent.entity_id
    return None


async def async_plan(hass: HomeAssistant) -> Plan:
    plan = Plan(stt=pick_engine(engines(hass, "stt")), tts=pick_engine(engines(hass, "tts")),
                supervisor=is_supervisor(hass))
    if plan.supervisor:
        for slug in (WHISPER_SLUG, PIPER_SLUG):
            try:
                from homeassistant.components.hassio.addon_manager import AddonState  # noqa: PLC0415
                info = await addon_manager(hass, slug).async_get_addon_info()
                installed = info.state is not AddonState.NOT_INSTALLED
            except Exception:  # noqa: BLE001 - treat as not installed; install will report the problem
                _LOGGER.debug("Could not read %s add-on info", slug, exc_info=True)
                installed = False
            setattr(plan, "whisper_installed" if slug == WHISPER_SLUG else "piper_installed", installed)
    return plan


class VoiceSetup:
    """Runs the steps and keeps the report. `sleep` is swappable so tests don't wait."""

    def __init__(self, hass: HomeAssistant, sleep=asyncio.sleep, wait: float = WAIT_SECONDS) -> None:
        self.hass, self._sleep, self._wait = hass, sleep, wait
        self.report = Report()
        self.stt: str | None = None
        self.tts: str | None = None

    async def async_install(self, plan: Plan, model: str) -> None:
        """Supervisor path: install, configure and start whichever add-ons are needed, then make sure
        Wyoming has picked them up."""
        self.stt, self.tts = plan.stt, plan.tts
        for slug, need in ((WHISPER_SLUG, plan.need_stt), (PIPER_SLUG, plan.need_tts)):
            if not need:
                continue
            name, domain = ADDONS[slug]
            try:
                await self._async_addon(slug, model)
            except Exception as err:  # noqa: BLE001 - report and carry on
                _LOGGER.warning("Voice setup: %s add-on failed: %s", name, err)
                self.report.manual.append(f"Install and start the {name} add-on (Settings > Add-ons): {err}")
                continue
            entity = await self._async_wyoming_for_addon(slug)
            self._found(domain, entity, name)

    async def _retry(self, call, *args):
        """Supervisor refuses work for a while after a restart ("not ready, try again later")."""
        for attempt in range(SUPERVISOR_TRIES):
            try:
                return await call(*args)
            except Exception as err:  # noqa: BLE001 - AddonError and friends
                if "not ready" not in str(err).lower() or attempt == SUPERVISOR_TRIES - 1:
                    raise
                _LOGGER.debug("Supervisor busy, retrying: %s", err)
                await self._sleep(POLL)

    async def _async_addon(self, slug: str, model: str) -> None:
        from homeassistant.components.hassio.addon_manager import AddonState  # noqa: PLC0415
        name = ADDONS[slug][0]
        mgr = addon_manager(self.hass, slug)
        info = await mgr.async_get_addon_info()
        if info.state is AddonState.NOT_INSTALLED:
            await self._retry(mgr.async_install_addon)
            self.report.done.append(f"Installed the {name} add-on")
            info = await mgr.async_get_addon_info()
        if slug == WHISPER_SLUG and (changes := whisper_options(info.options, model)):
            try:
                await self._retry(mgr.async_set_addon_options, {**info.options, **changes})
            except Exception:  # noqa: BLE001 - an add-on version without initial_prompt: drop it
                if "initial_prompt" not in changes:
                    raise
                changes.pop("initial_prompt")
                await self._retry(mgr.async_set_addon_options, {**info.options, **changes})
            self.report.done.append("Set Whisper to " + ", ".join(f"{k} {v!r}" for k, v in changes.items()))
            if info.state is AddonState.RUNNING:             # new options apply on restart
                await self._retry(mgr.async_restart_addon)
                self.report.done.append("Restarted the Whisper add-on")
        if info.state is not AddonState.RUNNING:
            await self._retry(mgr.async_start_addon)
            self.report.done.append(f"Started the {name} add-on")

    async def _async_wyoming_for_addon(self, slug: str) -> str | None:
        """Finish Supervisor's discovery flow for the add-on, or add Wyoming from the add-on's
        discovery address, then wait for the entity. Retries while the add-on starts up."""
        name, domain = ADDONS[slug]
        loops = max(1, int(self._wait / POLL))
        for _ in range(loops):
            if entity := wyoming_entity(self.hass, domain):
                return entity
            try:
                if not await self._async_finish_discovery(name):
                    uri = urlparse((await addon_manager(self.hass, slug).async_get_addon_discovery_info())["uri"])
                    await self.async_add_wyoming(uri.hostname, uri.port, quiet=True)
            except Exception:  # noqa: BLE001 - add-on still starting: try again shortly
                _LOGGER.debug("Wyoming not ready for %s yet", name, exc_info=True)
            await self._sleep(POLL)
        return wyoming_entity(self.hass, domain)

    async def _async_finish_discovery(self, name: str) -> bool:
        """Confirm a waiting Wyoming discovery flow for this add-on (the 'Discovered' card)."""
        flows = self.hass.config_entries.flow.async_progress_by_handler("wyoming")
        for flow in flows:
            label = str((flow.get("context") or {}).get("title_placeholders", {}).get("name", ""))
            if name.lower() in label.lower() and flow.get("step_id") == "hassio_confirm":
                result = await self.hass.config_entries.flow.async_configure(flow["flow_id"], {})
                if result.get("type") == "create_entry":
                    self.report.done.append(f"Added the {name} Wyoming integration")
                    return True
        return False

    async def async_add_wyoming(self, host: str, port: int, quiet: bool = False) -> bool:
        """Add a Wyoming entry by host and port (the integration's own user flow)."""
        flow = self.hass.config_entries.flow
        result = await flow.async_init("wyoming", context={"source": "user"})
        result = await flow.async_configure(result["flow_id"], {"host": host, "port": int(port)})
        if result.get("type") == "create_entry":
            self.report.done.append(f"Added Wyoming at {host}:{port}")
            return True
        if result.get("type") == "form":
            flow.async_abort(result["flow_id"])
        if not quiet:
            self.report.manual.append(f"Could not reach a Wyoming service at {host}:{port}")
        return False

    async def async_connect(self, plan: Plan, whisper: tuple[str, int] | None,
                            piper: tuple[str, int] | None) -> None:
        """Docker/Core path: add the user's own containers, then find the entities."""
        self.stt, self.tts = plan.stt, plan.tts
        for addr, domain, name in ((whisper, "stt", "Whisper"), (piper, "tts", "Piper")):
            if getattr(self, domain) is not None:
                continue
            entity = wyoming_entity(self.hass, domain)
            if entity is None and addr and addr[0]:
                try:
                    if await self.async_add_wyoming(*addr):
                        entity = await self._async_wait_entity(domain)
                except Exception as err:  # noqa: BLE001
                    self.report.manual.append(f"Add Wyoming for {name} at {addr[0]}:{addr[1]}: {err}")
            self._found(domain, entity, name)

    async def _async_wait_entity(self, domain: str) -> str | None:
        for _ in range(6):
            if entity := wyoming_entity(self.hass, domain):
                return entity
            await self._sleep(POLL / 2)
        return None

    def _found(self, domain: str, entity: str | None, name: str) -> None:
        if entity:
            setattr(self, domain, entity)
        else:
            what = "speech-to-text" if domain == "stt" else "text-to-speech"
            self.report.manual.append(f"No {what} engine from {name} yet: add it under Settings > Devices "
                                      f"& services > Wyoming Protocol, then pick it in the pipeline")


def our_agent(hass: HomeAssistant, entry_id: str) -> str | None:
    """This integration's conversation entity (its unique id is the entry id)."""
    return er.async_get(hass).async_get_entity_id("conversation", DOMAIN, entry_id)


def _languages(hass: HomeAssistant, domain: str, entity_id: str | None) -> list[str]:
    if not entity_id:
        return []
    try:
        if domain == "stt":
            from homeassistant.components import stt  # noqa: PLC0415
            ent = stt.async_get_speech_to_text_entity(hass, entity_id)
        else:
            from homeassistant.components.tts.helper import get_engine_instance  # noqa: PLC0415
            ent = get_engine_instance(hass, entity_id)
        return list(getattr(ent, "supported_languages", None) or [])
    except Exception:  # noqa: BLE001
        return []


async def async_pipeline(hass: HomeAssistant, agent: str, stt: str | None, tts: str | None,
                         preferred: bool, report: Report) -> str | None:
    """Create or update the "Better Assistant" pipeline; returns its name for the speaker selects."""
    from homeassistant.components import assist_pipeline  # noqa: PLC0415
    from homeassistant.components.assist_pipeline import pipeline as ap  # noqa: PLC0415
    store = hass.data[ap.KEY_ASSIST_PIPELINE].pipeline_store
    settings = {
        "conversation_engine": agent, "conversation_language": "en", "language": "en",
        "name": PIPELINE_NAME,
        "stt_engine": stt, "stt_language": pick_language(_languages(hass, "stt", stt)) if stt else None,
        "tts_engine": tts, "tts_language": pick_language(_languages(hass, "tts", tts)) if tts else None,
        "tts_voice": None, "wake_word_entity": None, "wake_word_id": None, "prefer_local_intents": True,
    }
    existing = next((p for p in assist_pipeline.async_get_pipelines(hass) if p.name == PIPELINE_NAME), None)
    if existing:
        if existing.tts_engine == tts:                     # same engine: keep the voice they picked
            settings.pop("tts_voice")
        await assist_pipeline.async_update_pipeline(hass, existing, **settings)
        pipeline_id = existing.id
        report.done.append(f'Updated the "{PIPELINE_NAME}" voice assistant')
    else:
        pipeline_id = (await store.async_create_item(settings)).id
        report.done.append(f'Created the "{PIPELINE_NAME}" voice assistant')
    if preferred:
        store.async_set_preferred_item(pipeline_id)
        report.done.append("Made it the preferred voice assistant")
    if not stt:
        report.manual.append("Pick a speech-to-text engine in the pipeline (Settings > Voice assistants)")
    return PIPELINE_NAME


@callback
def satellites(hass: HomeAssistant) -> list[tuple[str, str]]:
    """(entity_id, name) of voice speakers (assist_satellite entities, never Cast or Google)."""
    reg = er.async_get(hass)
    out = []
    for state in hass.states.async_all("assist_satellite"):
        entry = reg.async_get(state.entity_id)
        if is_speaker(entry.platform if entry else None):
            out.append((state.entity_id, state.name))
    return sorted(out, key=lambda s: s[1].lower())


@callback
def pipeline_select(hass: HomeAssistant, satellite: str) -> str | None:
    """The 'Assistant' select on the satellite's device (translation key pipeline, else *_assistant)."""
    reg = er.async_get(hass)
    sat = reg.async_get(satellite)
    if sat is None or sat.device_id is None:
        return None
    selects = [e for e in er.async_entries_for_device(reg, sat.device_id) if e.domain == "select"]
    for e in selects:
        if e.translation_key == "pipeline":
            return e.entity_id
    return next((e.entity_id for e in selects if e.entity_id.endswith("_assistant")), None)


async def async_point_speakers(hass: HomeAssistant, chosen: list[str], option: str, report: Report) -> None:
    for sat in chosen:
        name = (hass.states.get(sat).name if hass.states.get(sat) else sat)
        select = pipeline_select(hass, sat)
        if not select:
            report.manual.append(f"Set {name}'s assistant to {option} on its device page")
            continue
        try:
            await hass.services.async_call("select", "select_option", {"entity_id": select, "option": option},
                                           blocking=True)
            report.done.append(f"Switched {name} to {option}")
        except Exception as err:  # noqa: BLE001
            report.manual.append(f"Set {name}'s assistant to {option} on its device page ({err})")


async def async_apply(hass: HomeAssistant, entry_id: str, stt: str | None, tts: str | None,
                      preferred: bool, chosen: list[str], report: Report) -> None:
    """Pipeline plus speakers. Never raises: problems land in the report."""
    agent = our_agent(hass, entry_id)
    if agent is None:
        report.manual.append("Set the pipeline's conversation agent to Better Assistant")
        return
    try:
        option = await async_pipeline(hass, agent, stt, tts, preferred, report)
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Voice setup: pipeline failed: %s", err)
        report.manual.append(f"Create a voice assistant in Settings > Voice assistants with Better Assistant "
                             f"as the conversation agent ({err})")
        return
    if option and chosen:
        await async_point_speakers(hass, chosen, option, report)
