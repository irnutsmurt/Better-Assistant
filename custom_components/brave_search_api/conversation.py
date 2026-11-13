"""Conversation agent. Pipeline for each sentence that reaches it:

  "what did you hear" -> own sentences (reminders, alarms, notes, messages, stopwatch, timer
  wordings; matched with hassil) -> compound commands -> local answers -> question / command guards -> web search

Use it as the agent of an Assist pipeline with "prefer handling commands locally" on, so Home
Assistant's own commands run first and only the leftovers come here."""
from __future__ import annotations

import dataclasses
import logging
import re

from homeassistant.components import conversation
from homeassistant.components.homeassistant.exposed_entities import async_should_expose
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, entity_registry as er, intent
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import BraveConfigEntry
from .const import (
    CONF_API_KEY,
    DEFAULTS,
    HA_AGENT_ID,
    OPT_COMPOUND,
    OPT_COUNTRY,
    OPT_MAX_PARTS,
    OPT_MONTHLY_CAP,
    OPT_QUESTION_GUARD,
    OPT_SPEAK_SOURCE,
    OPT_WEB_SEARCH,
)
from .core import search
from .core.extras import fun_answer, is_what_did_you_hear, time_in_place
from .core.guards import is_question, looks_like_command, plan_compound
from .core.router import local_answer
from .core.timeparse import world_clock
from .sensor import device_info

_LOGGER = logging.getLogger(__name__)

DIDNT_CATCH = "Sorry, I didn't catch that."
NOT_UNDERSTOOD = "Sorry, I didn't understand that."
FAILURES = {
    "cap": "I've used up this month's searches, so I can't look that up until next month.",
    "empty": "I couldn't find a clear answer to that.",
    "auth": "The Brave Search API key was refused. Please check it in the integration settings.",
}


async def async_setup_entry(hass: HomeAssistant, entry: BraveConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    async_add_entities([BraveSearchAgent(entry)])


class BraveSearchAgent(conversation.ConversationEntity):
    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = conversation.ConversationEntityFeature(0)

    def __init__(self, entry: BraveConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = entry.entry_id
        self._attr_device_info = device_info(entry)

    @property
    def supported_languages(self) -> str:
        return "*"

    def _opt(self, key: str):
        return self._entry.options.get(key, DEFAULTS[key])

    def _home_names(self) -> set[str]:
        """Names and aliases of exposed entities and of areas, lower-case."""
        names: set[str] = set()
        ents = er.async_get(self.hass)
        for state in self.hass.states.async_all():
            if not async_should_expose(self.hass, conversation.DOMAIN, state.entity_id):
                continue
            names.add(state.name.lower())
            reg = ents.async_get(state.entity_id)
            if reg:
                names.update(a.lower() for a in reg.aliases if isinstance(a, str))
        for area in ar.async_get(self.hass).async_list_areas():
            names.add(area.name.lower())
            names.update(a.lower() for a in area.aliases)
        return {n for n in names if len(n) > 2}

    # ----------------------------------------------------------- compound commands
    async def _run_local(self, text: str, user_input: conversation.ConversationInput) -> tuple[bool, str]:
        """One sentence through Home Assistant's own agent (intents + sentence triggers)."""
        result = await conversation.async_converse(
            self.hass, text, None, user_input.context, user_input.language,
            agent_id=HA_AGENT_ID, device_id=user_input.device_id,
            satellite_id=getattr(user_input, "satellite_id", None))
        r = result.response
        ok = r.response_type != intent.IntentResponseType.ERROR
        speech = (r.speech or {}).get("plain", {}).get("speech", "") if ok else ""
        return ok, speech

    async def _matches(self, text: str, user_input: conversation.ConversationInput) -> bool | None:
        """Dry run with Home Assistant's own matcher: True/False, or None when that isn't available."""
        try:
            from homeassistant.components.conversation.agent_manager import get_agent_manager
            agent = get_agent_manager(self.hass).default_agent
            found = await agent.async_debug_recognize(dataclasses.replace(user_input, text=text))
            return bool(found and found.get("match"))
        except Exception:  # noqa: BLE001 - internal API moved: fall back to just trying
            _LOGGER.debug("Compound dry run unavailable; running parts without it", exc_info=True)
            return None

    async def _compound(self, text: str, user_input: conversation.ConversationInput) -> str | None:
        """Run 'A and B then C' as separate commands, but only if every part is a real command."""
        plan = plan_compound(text, self._home_names(), int(self._opt(OPT_MAX_PARTS)))
        if not plan:
            return None
        checks = [await self._matches(part, user_input) for part in plan]
        if False in checks:
            return None                                      # not a list of commands
        spoken: list[str] = []
        for part in plan:
            ok, speech = await self._run_local(part, user_input)
            if not ok:
                done = ". ".join(spoken)
                return (done + ". " if done else "") + f"But I didn't understand: {part}."
            if speech:
                spoken.append(speech.rstrip("."))
        return ". ".join(spoken) + "." if spoken else "Done."

    # ----------------------------------------------------------- answers
    def _local(self, text: str) -> str | None:
        place = time_in_place(text)
        if place:
            return world_clock(place, dt_util.now()) or f"Sorry, I don't know the time zone for {place}."
        return fun_answer(text) or local_answer(text, dt_util.now().date())

    async def _web(self, text: str) -> str:
        key = self._entry.data.get(CONF_API_KEY)
        if not key or not self._opt(OPT_WEB_SEARCH):
            return "Web search is turned off, so I can't look that up."
        store = self._entry.runtime_data.store
        cap = int(self._opt(OPT_MONTHLY_CAP))
        res = await search.answer(
            async_get_clientsession(self.hass), key, text, lambda: store.async_take_slot(cap),
            country=self._opt(OPT_COUNTRY), speak_source=self._opt(OPT_SPEAK_SOURCE))
        if res.get("ok"):
            return res["answer"]
        return FAILURES.get(res.get("reason"), "Sorry, I couldn't reach Brave Search right now.")

    async def _respond(self, text: str, user_input: conversation.ConversationInput) -> tuple[str, bool]:
        """(speech, is_error)."""
        heard = self._entry.runtime_data.heard
        if is_what_did_you_hear(text):
            return (f'I heard: "{heard[-1]}".' if heard else "I haven't heard anything else yet."), False
        heard.append(text)
        skills = self._entry.runtime_data.skills
        match = skills.recognize(text) if skills else None
        if match:                                            # the integration's own sentences
            return await skills.async_handle(match, text, user_input), False
        if self._opt(OPT_COMPOUND):
            done = await self._compound(text, user_input)
            if done:
                return done, False
        local = self._local(text)
        if local:
            return local, False
        if self._opt(OPT_QUESTION_GUARD) and not is_question(text):
            return DIDNT_CATCH, True
        if looks_like_command(text, self._home_names()):
            return NOT_UNDERSTOOD, True
        return await self._web(text), False

    async def _async_handle_message(self, user_input: conversation.ConversationInput,
                                    chat_log: conversation.ChatLog) -> conversation.ConversationResult:
        text = re.sub(r"\s+", " ", user_input.text or "").strip()
        response = intent.IntentResponse(language=user_input.language)
        speech, is_error = await self._respond(text, user_input) if text else (DIDNT_CATCH, True)
        if is_error:
            response.async_set_error(intent.IntentResponseErrorCode.NO_INTENT_MATCH, speech)
        else:
            response.async_set_speech(speech)
        chat_log.async_add_assistant_content_without_tools(
            conversation.AssistantContent(agent_id=self.entity_id, content=speech))
        return conversation.ConversationResult(response=response, conversation_id=chat_log.conversation_id)
