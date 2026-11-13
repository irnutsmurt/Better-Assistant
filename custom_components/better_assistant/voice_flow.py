"""The "Set up voice for me" steps, shared by the first-time setup and the settings menu. The config
flow can't make the pipeline itself (the conversation entity doesn't exist until the entry does), so
it hands the choices over as a pending request that __init__ carries out once the entry is set up."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .core.voice import PIPER_PORT, WHISPER_PORT, Plan, download_text, docker_text
from .voice_setup import VoiceSetup, async_apply, async_choose_model, async_plan, satellites

_LOGGER = logging.getLogger(__name__)


class VoiceSetupMixin:
    """Mixed into a ConfigFlow or OptionsFlow. The host flow provides `_voice_entry_id()` (None while
    the entry doesn't exist yet) and `_voice_finish(pending)`."""

    _plan: Plan | None = None
    _model: str = "base-int8"
    _voice: VoiceSetup | None = None
    _voice_task = None
    _pending: dict[str, Any] | None = None

    def _voice_entry_id(self) -> str | None:
        raise NotImplementedError

    def _voice_finish(self, pending: dict[str, Any] | None) -> ConfigFlowResult:
        raise NotImplementedError

    async def async_step_voice_setup(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="voice_setup", menu_options=["voice_auto", "voice_skip"])

    async def async_step_voice_skip(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self._voice_finish(None)

    async def async_step_voice_auto(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        self._voice = VoiceSetup(self.hass)
        try:
            self._plan = await async_plan(self.hass)
            self._model = await async_choose_model(self.hass)
        except Exception as err:  # noqa: BLE001 - a summary beats a broken setup
            _LOGGER.exception("Voice setup: detection failed")
            self._voice.report.manual.append(f"Set up speech engines by hand ({err})")
            return await self.async_step_voice_summary()
        plan = self._plan
        if plan.nothing_to_install:
            self._voice.stt, self._voice.tts = plan.stt, plan.tts
            self._voice.report.done.append(f"Kept your speech engines: {plan.stt} and {plan.tts}")
            return await self.async_step_voice_pipeline()
        if plan.supervisor:
            return await self.async_step_voice_confirm()
        return await self.async_step_voice_manual()

    async def async_step_voice_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return await self.async_step_voice_install()
        return self.async_show_form(step_id="voice_confirm", data_schema=vol.Schema({}), description_placeholders={
            "downloads": download_text(self._plan, self._model), "model": self._model})

    async def _progress(self, step_id: str, make) -> ConfigFlowResult:
        """Run a setup task behind a progress spinner, then go on to the pipeline step."""
        if self._voice_task is None:
            self._voice_task = self.hass.async_create_task(make())
        if not self._voice_task.done():
            return self.async_show_progress(step_id=step_id, progress_action=step_id,
                                            progress_task=self._voice_task)
        try:
            await self._voice_task
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Voice setup: %s failed", step_id)
            self._voice.report.manual.append(f"Finish the speech engines by hand ({err})")
        finally:
            self._voice_task = None
        return self.async_show_progress_done(next_step_id="voice_pipeline")

    async def async_step_voice_install(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._progress("voice_install", lambda: self._voice.async_install(self._plan, self._model))

    async def async_step_voice_manual(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        plan = self._plan
        if user_input is not None:
            def addr(prefix: str, port: int):
                host = (user_input.get(f"{prefix}_host") or "").strip()
                return (host, int(user_input.get(f"{prefix}_port") or port)) if host else None
            self._manual = (addr("whisper", WHISPER_PORT), addr("piper", PIPER_PORT))
            return await self.async_step_voice_connect()
        fields: dict[Any, Any] = {}
        port = NumberSelector(NumberSelectorConfig(min=1, max=65535, step=1, mode=NumberSelectorMode.BOX))
        if plan.need_stt:
            fields[vol.Optional("whisper_host")] = TextSelector()
            fields[vol.Optional("whisper_port", default=WHISPER_PORT)] = port
        if plan.need_tts:
            fields[vol.Optional("piper_host")] = TextSelector()
            fields[vol.Optional("piper_port", default=PIPER_PORT)] = port
        have = ", ".join(e for e in (plan.stt, plan.tts) if e) or "none"
        return self.async_show_form(step_id="voice_manual", data_schema=vol.Schema(fields),
                                    description_placeholders={"commands": docker_text(self._model),
                                                              "model": self._model, "have": have})

    async def async_step_voice_connect(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        whisper, piper = self._manual
        return await self._progress("voice_connect",
                                    lambda: self._voice.async_connect(self._plan, whisper, piper))

    async def async_step_voice_pipeline(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        voice = self._voice
        if user_input is not None:
            chosen = list(user_input.get("satellites") or [])
            preferred = bool(user_input.get("preferred", True))
            if (entry_id := self._voice_entry_id()) is not None:
                await async_apply(self.hass, entry_id, voice.stt, voice.tts, preferred, chosen, voice.report)
            else:
                self._pending = {"stt": voice.stt, "tts": voice.tts, "preferred": preferred, "satellites": chosen}
                voice.report.done.append('The "Better Assistant" voice assistant is created (and your speakers '
                                         'switched) as soon as you press Submit; a notification confirms it')
            return await self.async_step_voice_summary()
        fields: dict[Any, Any] = {vol.Required("preferred", default=True): BooleanSelector()}
        if sats := satellites(self.hass):
            fields[vol.Optional("satellites", default=[s[0] for s in sats])] = SelectSelector(SelectSelectorConfig(
                options=[SelectOptionDict(value=e, label=n) for e, n in sats], multiple=True,
                mode=SelectSelectorMode.LIST))
        return self.async_show_form(step_id="voice_pipeline", data_schema=vol.Schema(fields),
                                    description_placeholders={"stt": voice.stt or "none yet",
                                                              "tts": voice.tts or "none yet"})

    async def async_step_voice_summary(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self._voice_finish(self._pending)
        return self.async_show_form(step_id="voice_summary", data_schema=vol.Schema({}),
                                    description_placeholders={"summary": self._voice.report.text()})
