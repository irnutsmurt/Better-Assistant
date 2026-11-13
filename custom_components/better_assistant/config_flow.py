"""Config flow (API key) and options flow (the settings page, as a menu of sections)."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    AreaSelector,
    AreaSelectorConfig,
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
    TimeSelector,
)

from .const import (
    AREA,
    CONF_API_KEY,
    DEFAULTS,
    DEVICE_SECTIONS,
    EXTRA_FIELDS,
    FEATURE_DEFAULT_OFF,
    FEATURE_SECTIONS,
    DOMAIN,
    OPT_COMPOUND,
    OPT_COUNTRY,
    OPT_FEATURES,
    OPT_SECURITY,
    OPT_MAX_PARTS,
    OPT_MONTHLY_CAP,
    OPT_OVERRIDES,
    OPT_QUESTION_GUARD,
    OPT_SETTINGS,
    OPT_SNOOZE,
    OPT_ALARM_SPEAKER,
    OPT_SNOOZE_ENABLED,
    OPT_SNOOZE_LIMIT,
    OPT_SPEAK_SOURCE,
    OPT_VOICE_PENDING,
    OPT_WEB_SEARCH,
    PLACEHOLDER_SECTIONS,
    TITLE,
)
from .core.features import snooze_from_page
from .core.search import CannotConnect, InvalidAuth, validate_key
from .discovery import async_detect, detected_value, effective_section
from .voice_flow import VoiceSetupMixin

_LOGGER = logging.getLogger(__name__)

KEY_SCHEMA = vol.Schema({
    vol.Optional(CONF_API_KEY): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
})


async def _check_key(flow: ConfigFlow, key: str) -> str | None:
    """Error code for the form, or None when the key works."""
    try:
        await validate_key(async_get_clientsession(flow.hass), key)
    except InvalidAuth:
        return "invalid_auth"
    except CannotConnect:
        return "cannot_connect"
    except Exception:  # noqa: BLE001 - never let the form crash
        _LOGGER.exception("Unexpected error checking the API key")  # the key itself is never logged
        return "unknown"
    return None


class BetterAssistantConfigFlow(VoiceSetupMixin, ConfigFlow, domain=DOMAIN):
    VERSION = 1
    _key = ""

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return BetterAssistantOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        errors: dict[str, str] = {}
        if user_input is not None:
            key = (user_input.get(CONF_API_KEY) or "").strip()
            if key and (err := await _check_key(self, key)):
                errors["base"] = err
            else:
                self._key = key
                return await self.async_step_voice_setup()
        return self.async_show_form(step_id="user", data_schema=KEY_SCHEMA, errors=errors)

    def _voice_entry_id(self) -> str | None:
        return None

    def _voice_finish(self, pending: dict[str, Any] | None) -> ConfigFlowResult:
        return self.async_create_entry(title=TITLE, data={CONF_API_KEY: self._key},
                                       options={OPT_VOICE_PENDING: pending} if pending else {})

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Change or remove the API key."""
        errors: dict[str, str] = {}
        if user_input is not None:
            key = (user_input.get(CONF_API_KEY) or "").strip()
            if key and (err := await _check_key(self, key)):
                errors["base"] = err
            else:
                return self.async_update_reload_and_abort(
                    self._get_reconfigure_entry(), data_updates={CONF_API_KEY: key})
        return self.async_show_form(step_id="reconfigure", data_schema=KEY_SCHEMA, errors=errors)


def _entity_selector(domain: str | list[str], multiple: bool):
    if domain == AREA:
        return AreaSelector(AreaSelectorConfig(multiple=multiple))
    return EntitySelector(EntitySelectorConfig(domain=domain, multiple=multiple))


class BetterAssistantOptionsFlow(VoiceSetupMixin, OptionsFlow):
    """Menu of sections. Device sections are pre-filled from automatic detection; what the user
    submits is stored as an override, so re-detecting never wipes their choices."""

    def _opt(self, key: str) -> Any:
        return self.config_entry.options.get(key, DEFAULTS.get(key))

    def _voice_entry_id(self) -> str | None:
        return self.config_entry.entry_id

    def _voice_finish(self, pending: dict[str, Any] | None) -> ConfigFlowResult:
        return self._save({})

    def _save(self, values: dict[str, Any]) -> ConfigFlowResult:
        return self.async_create_entry(data={**self.config_entry.options, **values})

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=[
            "web_search", "behaviour", "alarms", "security", *DEVICE_SECTIONS, *PLACEHOLDER_SECTIONS,
            "voice_setup", "redetect"])

    async def async_step_web_search(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            user_input[OPT_COUNTRY] = (user_input.get(OPT_COUNTRY) or "us").strip().lower()[:2]
            return self._save(user_input)
        schema = vol.Schema({
            vol.Required(OPT_WEB_SEARCH, default=self._opt(OPT_WEB_SEARCH)): BooleanSelector(),
            vol.Required(OPT_MONTHLY_CAP, default=self._opt(OPT_MONTHLY_CAP)): NumberSelector(
                NumberSelectorConfig(min=0, max=100000, step=1, mode=NumberSelectorMode.BOX)),
            vol.Required(OPT_COUNTRY, default=self._opt(OPT_COUNTRY)): TextSelector(),
            vol.Required(OPT_SPEAK_SOURCE, default=self._opt(OPT_SPEAK_SOURCE)): BooleanSelector(),
        })
        has_key = bool(self.config_entry.data.get(CONF_API_KEY))
        return self.async_show_form(step_id="web_search", data_schema=schema, description_placeholders={
            "key_state": "set" if has_key else "not set (web search is off until you add one: "
                                               "Settings > Devices & services > Better Assistant > Reconfigure)"})

    async def async_step_behaviour(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            user_input[OPT_MAX_PARTS] = int(user_input[OPT_MAX_PARTS])
            return self._save(user_input)
        schema = vol.Schema({
            vol.Required(OPT_QUESTION_GUARD, default=self._opt(OPT_QUESTION_GUARD)): BooleanSelector(),
            vol.Required(OPT_COMPOUND, default=self._opt(OPT_COMPOUND)): BooleanSelector(),
            vol.Required(OPT_MAX_PARTS, default=self._opt(OPT_MAX_PARTS)): NumberSelector(
                NumberSelectorConfig(min=2, max=4, step=1, mode=NumberSelectorMode.SLIDER)),
        })
        return self.async_show_form(step_id="behaviour", data_schema=schema)

    async def async_step_security(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Voice passphrase. The passphrase is never shown back: leave the field empty to keep it."""
        current = dict(self.config_entry.options.get(OPT_SECURITY) or {})
        if user_input is not None:
            new = (user_input.get("passphrase") or "").strip()
            secret = "" if user_input.get("clear_passphrase") else (new or current.get("passphrase", ""))
            return self._save({OPT_SECURITY: {
                "passphrase": secret,
                "require_doors": bool(user_input.get("require_doors", True)),
                "require_guest": bool(user_input.get("require_guest", True)),
                "owner": user_input.get("owner") or None}})
        schema = vol.Schema({
            vol.Optional("passphrase"): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
            vol.Required("clear_passphrase", default=False): BooleanSelector(),
            vol.Required("require_doors", default=current.get("require_doors", True)): BooleanSelector(),
            vol.Required("require_guest", default=current.get("require_guest", True)): BooleanSelector(),
            vol.Optional("owner", description={"suggested_value": current.get("owner")}):
                EntitySelector(EntitySelectorConfig(domain="person")),
        })
        return self.async_show_form(step_id="security", data_schema=schema, description_placeholders={
            "passphrase_state": "set" if current.get("passphrase") else "not set"})

    def _speaker_options(self) -> list[SelectOptionDict]:
        """'All voice speakers' plus every voice satellite (assist_satellite only)."""
        opts = [SelectOptionDict(value="all", label="All voice speakers")]
        for state in sorted(self.hass.states.async_all("assist_satellite"), key=lambda s: s.name.lower()):
            opts.append(SelectOptionDict(value=state.entity_id, label=state.name))
        return opts

    async def async_step_alarms(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            enabled, limit = snooze_from_page(user_input.get(OPT_SNOOZE_ENABLED, True),
                                              user_input.get(OPT_SNOOZE_LIMIT))   # 0 = snoozing off
            return self._save({OPT_SNOOZE: int(user_input[OPT_SNOOZE]), OPT_SNOOZE_ENABLED: enabled,
                               OPT_SNOOZE_LIMIT: limit,
                               OPT_ALARM_SPEAKER: user_input.get(OPT_ALARM_SPEAKER) or None})
        schema = vol.Schema({
            vol.Required(OPT_SNOOZE, default=self._opt(OPT_SNOOZE)): NumberSelector(
                NumberSelectorConfig(min=1, max=30, step=1, unit_of_measurement="min",
                                     mode=NumberSelectorMode.SLIDER)),
            vol.Required(OPT_SNOOZE_ENABLED, default=self._opt(OPT_SNOOZE_ENABLED)): BooleanSelector(),
            vol.Optional(OPT_SNOOZE_LIMIT, description={"suggested_value": self._opt(OPT_SNOOZE_LIMIT)}):
                NumberSelector(NumberSelectorConfig(min=0, max=10, step=1, mode=NumberSelectorMode.BOX)),
            # empty = the speaker you asked from
            vol.Optional(OPT_ALARM_SPEAKER, description={"suggested_value": self._opt(OPT_ALARM_SPEAKER)}):
                SelectSelector(SelectSelectorConfig(options=self._speaker_options(), mode=SelectSelectorMode.DROPDOWN)),
        })
        return self.async_show_form(step_id="alarms", data_schema=schema)

    async def _device_section(self, section: str, user_input: dict[str, Any] | None) -> ConfigFlowResult:
        if user_input is not None:
            # Keep only fields that differ from detection, so a later re-detect still updates the rest.
            overrides = dict(self.config_entry.options.get(OPT_OVERRIDES) or {})
            detected = self.config_entry.runtime_data.store.detected
            changed = {}
            for f, (path, _d, multi) in DEVICE_SECTIONS[section].items():
                value = user_input.get(f, [] if multi else None)
                if value != detected_value(detected, path, multi):
                    changed[f] = value
            overrides[section] = changed
            if section == "cameras_outside" and "outdoor_areas" in changed:
                # outdoor areas decide which sensors count as outside: detect again with them
                store = self.config_entry.runtime_data.store
                await store.async_set_detected(
                    async_detect(self.hass, {OPT_OVERRIDES: overrides}))
            save: dict[str, Any] = {OPT_OVERRIDES: overrides}
            if section in FEATURE_SECTIONS:
                save[OPT_FEATURES] = {**(self.config_entry.options.get(OPT_FEATURES) or {}),
                                      section: bool(user_input.get("enabled", True))}
            if section in EXTRA_FIELDS:
                settings = dict(self.config_entry.options.get(OPT_SETTINGS) or {})
                settings[section] = {k: user_input.get(k, default) for k, (_kind, default, _c)
                                     in EXTRA_FIELDS[section].items()}
                save[OPT_SETTINGS] = settings
            return self._save(save)
        detected = self.config_entry.runtime_data.store.detected
        current = effective_section(dict(self.config_entry.options), detected, section)
        fields: dict[Any, Any] = {}
        if section in FEATURE_SECTIONS:
            on = (self.config_entry.options.get(OPT_FEATURES) or {}).get(section, section not in FEATURE_DEFAULT_OFF)
            fields[vol.Required("enabled", default=on)] = BooleanSelector()
        stored = (self.config_entry.options.get(OPT_SETTINGS) or {}).get(section) or {}
        for key, (kind, default, cfg) in EXTRA_FIELDS.get(section, {}).items():
            value = stored.get(key, default)
            if kind == "time":
                fields[vol.Required(key, default=value)] = TimeSelector()
            elif kind == "bool":
                fields[vol.Required(key, default=bool(value))] = BooleanSelector()
            else:
                extra = {"unit_of_measurement": cfg["unit"]} if cfg.get("unit") else {}
                fields[vol.Required(key, default=value)] = NumberSelector(NumberSelectorConfig(
                    min=cfg.get("min", 0), max=cfg.get("max", 100), step=cfg.get("step", 1),
                    mode=NumberSelectorMode.BOX, **extra))
        for name, (_path, domain, multiple) in DEVICE_SECTIONS[section].items():
            value = current.get(name)
            key = vol.Optional(name, description={"suggested_value": value}) if value not in (None, []) \
                else vol.Optional(name)
            fields[key] = _entity_selector(domain, multiple)
        return self.async_show_form(step_id=section, data_schema=vol.Schema(fields))

    async def async_step_redetect(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            await self.config_entry.runtime_data.store.async_set_detected(
                async_detect(self.hass, dict(self.config_entry.options)))
            return await self.async_step_init()
        return self.async_show_form(step_id="redetect", data_schema=vol.Schema({}))


def _make_section_step(section: str):
    async def step(self: BetterAssistantOptionsFlow, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._device_section(section, user_input)
    step.__name__ = f"async_step_{section}"
    return step


for _section in DEVICE_SECTIONS:
    setattr(BetterAssistantOptionsFlow, f"async_step_{_section}", _make_section_step(_section))
