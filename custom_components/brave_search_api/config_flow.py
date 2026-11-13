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
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    AREA,
    CONF_API_KEY,
    DEFAULTS,
    DEVICE_SECTIONS,
    DOMAIN,
    OPT_COMPOUND,
    OPT_COUNTRY,
    OPT_MAX_PARTS,
    OPT_MONTHLY_CAP,
    OPT_OVERRIDES,
    OPT_QUESTION_GUARD,
    OPT_SNOOZE,
    OPT_SNOOZE_LIMIT,
    OPT_SPEAK_SOURCE,
    OPT_WEB_SEARCH,
    PLACEHOLDER_SECTIONS,
    TITLE,
)
from .core.search import CannotConnect, InvalidAuth, validate_key
from .discovery import async_detect, detected_value, effective_section

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


class BraveSearchApiConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return BraveSearchApiOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        errors: dict[str, str] = {}
        if user_input is not None:
            key = (user_input.get(CONF_API_KEY) or "").strip()
            if key and (err := await _check_key(self, key)):
                errors["base"] = err
            else:
                return self.async_create_entry(title=TITLE, data={CONF_API_KEY: key})
        return self.async_show_form(step_id="user", data_schema=KEY_SCHEMA, errors=errors)

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


class BraveSearchApiOptionsFlow(OptionsFlow):
    """Menu of sections. Device sections are pre-filled from automatic detection; what the user
    submits is stored as an override, so re-detecting never wipes their choices."""

    def _opt(self, key: str) -> Any:
        return self.config_entry.options.get(key, DEFAULTS.get(key))

    def _save(self, values: dict[str, Any]) -> ConfigFlowResult:
        return self.async_create_entry(data={**self.config_entry.options, **values})

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=[
            "web_search", "behaviour", "alarms", *DEVICE_SECTIONS, *PLACEHOLDER_SECTIONS, "redetect"])

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
                                               "Settings > Devices & services > Brave Search API > Reconfigure)"})

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

    async def async_step_alarms(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            per_alarm = int(user_input.get("snooze_limit", 0))
            limit = 0 if not user_input.get("allow_snooze", True) else (per_alarm or None)
            return self._save({OPT_SNOOZE: int(user_input[OPT_SNOOZE]), OPT_SNOOZE_LIMIT: limit})
        limit = self._opt(OPT_SNOOZE_LIMIT)
        schema = vol.Schema({
            vol.Required(OPT_SNOOZE, default=self._opt(OPT_SNOOZE)): NumberSelector(
                NumberSelectorConfig(min=1, max=30, step=1, unit_of_measurement="min",
                                     mode=NumberSelectorMode.SLIDER)),
            vol.Required("allow_snooze", default=limit != 0): BooleanSelector(),
            # 0 here means unlimited; "no snoozing" is the switch above
            vol.Required("snooze_limit", default=limit or 0): NumberSelector(
                NumberSelectorConfig(min=0, max=10, step=1, mode=NumberSelectorMode.SLIDER)),
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
            return self._save({OPT_OVERRIDES: overrides})
        detected = self.config_entry.runtime_data.store.detected
        current = effective_section(dict(self.config_entry.options), detected, section)
        fields: dict[Any, Any] = {}
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

    async def _placeholder(self, step: str, user_input: dict[str, Any] | None) -> ConfigFlowResult:
        if user_input is not None:
            return await self.async_step_init()
        return self.async_show_form(step_id=step, data_schema=vol.Schema({}))

    async def async_step_night_mode(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._placeholder("night_mode", user_input)

    async def async_step_guest_mode(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._placeholder("guest_mode", user_input)


def _make_section_step(section: str):
    async def step(self: BraveSearchApiOptionsFlow, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._device_section(section, user_input)
    step.__name__ = f"async_step_{section}"
    return step


for _section in DEVICE_SECTIONS:
    setattr(BraveSearchApiOptionsFlow, f"async_step_{_section}", _make_section_step(_section))
