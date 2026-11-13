"""Reminders, alarms, notes, household messages, stopwatch and extra timer wordings.

Everything is built from detected devices and the options page: voice satellites announce, the
satellite's own media player rings alarms, people and their phones come from detection."""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import re
from collections.abc import Callable
from typing import Any

from homeassistant.components import conversation
from homeassistant.const import EVENT_CALL_SERVICE, STATE_HOME
from homeassistant.core import Context, Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er, intent
from homeassistant.helpers.event import async_track_point_in_time, async_track_state_change_event
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.util import dt as dt_util

from .const import ALARM_URL, DEFAULTS, OPT_ALARM_SPEAKER, OPT_SNOOZE, OPT_SNOOZE_ENABLED, OPT_SNOOZE_LIMIT, RING_MINUTES
from .core import intents as sentences
from .core.features import (
    ALL_SPEAKERS,
    Stopwatch,
    best_note,
    describe_snooze,
    effective_limit,
    flip_pronouns,
    next_alarm,
    note_from,
    parse_reminder,
    resolve_speaker,
    resolve_person,
    say_alarm,
    say_duration,
    say_where,
    snooze_decision,
    snooze_length_reply,
    snooze_limit_reply,
    split_alarm_place,
    sentence,
)
from .core.intents import TIMER_INTENTS, Match
from .core.timeparse import fmt_time, parse, say_when
from .discovery import effective_section
from .house import GUEST_REPLY, HouseSkills
from .security import SecuritySkills
from .core.security import split_oneshot

_LOGGER = logging.getLogger(__name__)

STOP_SERVICES = {"media_stop", "media_pause", "turn_off", "volume_mute", "clear_playlist"}
HOW_TO_ADD_ZONE = ("I don't know a place called {place}. Add it as a zone in Settings, Areas, labels and "
                   "zones, Zones, then ask me again.")


class Skills(HouseSkills, SecuritySkills):
    """Per config entry. Created in async_setup_entry, stopped on unload."""

    def __init__(self, hass: HomeAssistant, entry) -> None:
        self.hass = hass
        self.entry = entry
        self.store = entry.runtime_data.store
        self._unsubs: list[Callable[[], None]] = []
        self._timers: dict[str, Callable[[], None]] = {}      # reminder uid / "alarm:<sat>" -> cancel
        self._ringing: dict[str, asyncio.Task] = {}            # satellite -> ring loop
        self._stopwatches: dict[str, Stopwatch] = {}
        self._person_unsub: Callable[[], None] | None = None
        self._own_contexts: set[str] = set()
        self._snoozed_until: dict[str, dt.datetime] = {}
        self._snooze_count: dict[str, int] = {}              # alarm key -> snoozes taken while ringing
        self._ring_targets: dict[str, Any] = {}              # alarm key -> targets it is ringing on
        self._ring_meta: dict[str, dict] = {}
        self.followup = False                                # ask the speaker to keep listening

    # ------------------------------------------------------------ lifecycle
    async def async_start(self) -> None:
        await self.hass.async_add_executor_job(sentences.load, "en")   # read sentence files off the loop
        self._unsubs.append(self.store.async_add_listener(self._reconcile))
        for uid in list(self.store.data["reminders"]):
            self._schedule_reminder(uid)
        for key in list(self._alarms()):
            self._schedule_alarm(key)
        self._track_people()
        self.start_night_schedule()
        self.apply_door_hiding()

    @callback
    def on_detected(self) -> None:
        """Detection ran: refresh what was built from it at start-up."""
        self.apply_door_hiding()

    @callback
    def async_stop(self) -> None:
        for unsub in self._unsubs + list(self._timers.values()):
            unsub()
        if self._person_unsub:
            self._person_unsub()
        for task in self._ringing.values():
            task.cancel()
        self._unsubs.clear()
        self._timers.clear()
        self._ringing.clear()

    # ------------------------------------------------------------ house lookups
    def _detected(self) -> dict[str, Any]:
        return self.store.detected

    def _section(self, name: str) -> dict[str, Any]:
        return effective_section(dict(self.entry.options), self._detected(), name)

    def satellites(self) -> list[str]:
        return list(self._section("voice_speakers").get("satellites") or [])

    def people_list(self) -> list[tuple[str, str, list[str]]]:
        """[(person entity id, full name, aliases)]."""
        ents = er.async_get(self.hass)
        out = []
        for state in self.hass.states.async_all("person"):
            reg = ents.async_get(state.entity_id)
            aliases = [a for a in (reg.aliases if reg else ()) if isinstance(a, str) and a.strip()]
            out.append((state.entity_id, state.name, aliases))
        return out

    def people(self) -> dict[str, list[str]]:
        """Spoken name (lower-case) -> person entity ids."""
        from .core.features import name_index  # noqa: PLC0415
        return name_index(self.people_list())

    def resolve(self, spoken: str) -> tuple[str | None, str]:
        """(person, "") or (None, what to say)."""
        person, question = resolve_person(spoken, self.people_list())
        if person:
            return person, ""
        name = spoken.strip()
        return None, question or f"There's no one named {name[:1].upper() + name[1:]} in this home."

    def person_name(self, entity_id: str | None) -> str:
        state = self.hass.states.get(entity_id) if entity_id else None
        return state.name.split()[0] if state else "someone"

    def speaker_person(self, user_input: conversation.ConversationInput) -> str | None:
        """The person talking: from the signed-in user, or the only person in the house."""
        user_id = user_input.context.user_id if user_input.context else None
        persons = self.hass.states.async_all("person")
        if user_id:
            for state in persons:
                if state.attributes.get("user_id") == user_id:
                    return state.entity_id
        return persons[0].entity_id if len(persons) == 1 else None

    def satellite_for(self, user_input: conversation.ConversationInput) -> str | None:
        sat = getattr(user_input, "satellite_id", None)
        if sat:
            return sat
        if user_input.device_id:
            ents = er.async_get(self.hass)
            for e in er.async_entries_for_device(ents, user_input.device_id):
                if e.domain == "assist_satellite":
                    return e.entity_id
        sats = self.satellites()
        return sats[0] if len(sats) == 1 else None

    def media_player_for(self, satellite: str) -> str | None:
        ents = er.async_get(self.hass)
        entry = ents.async_get(satellite)
        if not entry or not entry.device_id:
            return None
        players = [e.entity_id for e in er.async_entries_for_device(ents, entry.device_id)
                   if e.domain == "media_player"]
        return players[0] if players else None

    def phone_for(self, person: str | None) -> str | None:
        for phone in self._detected().get("phones") or []:
            if person and phone.get("person") == person:
                return phone["service"]
        return None

    def is_home(self, person: str | None) -> bool:
        state = self.hass.states.get(person) if person else None
        return bool(state and state.state == STATE_HOME)

    def zone_for(self, place: str) -> tuple[str, str] | None:
        """Spoken place -> (zone entity id, the state a person has while in it)."""
        p = place.lower().strip()
        if p in ("home", "the house", "house"):
            return "zone.home", STATE_HOME
        for state in self.hass.states.async_all("zone"):
            name = state.name.lower()
            if p == name or p == state.entity_id.split(".", 1)[1].replace("_", " "):
                return state.entity_id, state.name
        for state in self.hass.states.async_all("zone"):
            if p in state.name.lower() or state.name.lower() in p:
                return state.entity_id, state.name
        return None

    # ------------------------------------------------------------ delivery
    async def _call(self, domain: str, service: str, data: dict[str, Any], context: Context | None = None) -> None:
        try:
            await self.hass.services.async_call(domain, service, data, blocking=True, context=context)
        except Exception:  # noqa: BLE001 - a missing speaker or phone must not stop the rest
            _LOGGER.warning("Could not call %s.%s", domain, service, exc_info=True)

    async def announce(self, satellites: list[str], message: str) -> None:
        await asyncio.gather(*(self._call("assist_satellite", "announce",
                                          {"entity_id": s, "message": message, "preannounce": True})
                               for s in satellites))

    async def notify(self, person: str | None, title: str, message: str) -> None:
        service = self.phone_for(person)
        if service:
            domain, name = service.split(".", 1)
            await self._call(domain, name, {"title": title, "message": message})

    # ------------------------------------------------------------ dispatch
    def recognize(self, text: str) -> Match | None:
        people = sorted({n for n in self.people()}, key=len, reverse=True)
        lists = self.slot_lists()
        command, phrase = split_oneshot(text)
        if phrase is not None:                             # "open the garage door, passphrase ..."
            match = sentences.recognize(command, people, lists=lists, disabled=self.disabled_features())
            if match and match.intent in ("DoorOpen", "GuestOff"):
                match.slots["passphrase"] = phrase
                return match
        return sentences.recognize(text, people, lists=lists, disabled=self.disabled_features())

    async def async_handle(self, match: Match, text: str, user_input: conversation.ConversationInput) -> str:
        if match.intent in TIMER_INTENTS:
            return await self._builtin_timer(match, text, user_input)
        if self.guest_blocks(match.intent):
            return GUEST_REPLY
        handler = getattr(self, "_h_" + re.sub(r"(?<!^)([A-Z])", r"_\1", match.intent).lower())
        return await handler(match.slots, user_input)

    async def _builtin_timer(self, match: Match, text: str, user_input: conversation.ConversationInput) -> str:
        """Extra wordings for Home Assistant's own timers: hand the slots to the built-in intent."""
        if not user_input.device_id:
            return "Timers run on a voice speaker. Please ask from the speaker you want the timer on."
        slots = {k: {"value": v} for k, v in match.slots.items()}
        try:
            response = await intent.async_handle(
                self.hass, "conversation", match.intent, slots, text_input=text, context=user_input.context,
                language=user_input.language, device_id=user_input.device_id,
                satellite_id=getattr(user_input, "satellite_id", None),
                conversation_agent_id=user_input.agent_id)
        except intent.IntentError as err:
            return str(err) or "Sorry, I couldn't do that with the timer."
        speech = (response.speech or {}).get("plain", {}).get("speech")
        return speech or "Done."

    async def _h_unknown_person(self, slots: dict, user_input) -> str:
        name = (slots.get("name") or "").strip(" ,.")
        return f"There's no one named {name[:1].upper() + name[1:]} in this home."

    # ------------------------------------------------------------ reminders
    async def _h_reminder_add(self, slots: dict, user_input, person: str | None = None) -> str:
        now = dt_util.now()
        req = parse_reminder(slots.get("text", ""), now.replace(tzinfo=None))
        for_other = person is not None
        person = person or self.speaker_person(user_input)
        if not req.task:
            return "What should I remind you about?"
        if req.kind == "none":
            return f"When should I remind {'them' if for_other else 'you'}? Say something like: remind me to {req.task} at 5."
        meta: dict[str, Any] = {"task": req.task, "kind": req.kind, "person": person, "repeat": req.repeat,
                                "for_other": for_other, "satellite": self.satellite_for(user_input)}
        if req.kind == "time":
            at = req.at.replace(tzinfo=now.tzinfo)
            meta["at"] = at.isoformat()
            when = say_when(req.at, now.replace(tzinfo=None))
            if req.repeat != "once":
                when = say_alarm(req.at, req.repeat, now.replace(tzinfo=None))
            due = at.isoformat()
        else:
            if req.place is None:
                return "Where should that be? Say something like: when I get to work."
            if not person:
                return ("I don't know who's asking, so I can't tell when you arrive. "
                        "Say: remind <name> to ... when they get home.")
            zone = self.zone_for(req.place)
            if not zone:
                return HOW_TO_ADD_ZONE.format(place=req.place)
            meta["zone"], meta["zone_state"] = zone
            verb = "get to" if req.kind == "arrive" else "leave"
            where = "home" if zone[1] == STATE_HOME else zone[1]
            if for_other:
                verb = "gets to" if req.kind == "arrive" else "leaves"
                when = f"when {self.person_name(person)} {verb} {where}".replace("gets to home", "gets home")
            else:
                when = f"when you {verb} {where}".replace("get to home", "get home")
            due = None
        summary = f"{self.person_name(person)}: {req.task}" if for_other else req.task
        uid = self.store.add_item("reminders", summary, due, when)
        self.store.data["reminders"][uid] = meta
        self.store.changed()
        self._schedule_reminder(uid)
        self._track_people()
        who = f"Okay, I'll remind {self.person_name(person)}" if for_other else "Okay, I'll remind you"
        return f"{who} to {flip_pronouns(req.task) if not for_other else req.task} {when}."

    async def _h_reminder_add_for(self, slots: dict, user_input) -> str:
        person, problem = self.resolve(slots.get("person") or "")
        if not person:
            return problem
        text = re.sub(r"\bwhen (he|she|they) (get|gets|come|comes) (back )?home\b", "when I get home",
                      slots.get("text", ""), flags=re.I)
        text = re.sub(r"\bwhen (he|she|they) (leave|leaves)\b", "when I leave", text, flags=re.I)
        return await self._h_reminder_add({"text": text}, user_input, person)

    def _open_reminders(self) -> list[dict[str, Any]]:
        return [i for i in self.store.items("reminders") if i["status"] == "needs_action"]

    async def _h_reminder_list(self, slots: dict, user_input) -> str:
        items = self._open_reminders()
        if not items:
            return "You don't have any reminders."
        now = dt_util.now()
        said = []
        for i in items[:6]:
            meta = self.store.data["reminders"].get(i["uid"], {})
            when = i.get("description") or ""
            if meta.get("kind") == "time" and meta.get("repeat", "once") == "once" and i.get("due"):
                due = dt_util.parse_datetime(i["due"])          # relative words are worked out now
                when = say_when(dt_util.as_local(due).replace(tzinfo=None), now.replace(tzinfo=None)) if due else when
            said.append(f"{i['summary']} {when}".strip())
        head = f"You have {len(items)} reminder{'s' if len(items) != 1 else ''}: "
        return head + "; ".join(flip_pronouns(s) for s in said) + "."

    async def _h_reminder_cancel_all(self, slots: dict, user_input) -> str:
        uids = [i["uid"] for i in self._open_reminders()]
        if not uids:
            return "You don't have any reminders."
        self.store.remove_items("reminders", uids)
        return f"OK, I cancelled {len(uids)} reminder{'s' if len(uids) != 1 else ''}."

    async def _h_reminder_cancel(self, slots: dict, user_input) -> str:
        items = self._open_reminders()
        best = best_note(slots.get("text", ""), [i["summary"] for i in items])
        if not best:
            return "I couldn't find a reminder like that."
        uid = next(i["uid"] for i in items if i["summary"] == best)
        self.store.remove_items("reminders", [uid])
        return f"OK, I cancelled the reminder to {flip_pronouns(best)}."

    @callback
    def _schedule_reminder(self, uid: str) -> None:
        if (cancel := self._timers.pop(uid, None)):
            cancel()
        meta = self.store.data["reminders"].get(uid)
        if not meta or meta["kind"] != "time" or meta.get("waiting_home"):
            return
        at = dt_util.parse_datetime(meta["at"])
        if at is None:
            return

        @callback
        def _fire(_now: dt.datetime) -> None:
            self._timers.pop(uid, None)
            self.hass.async_create_task(self._deliver(uid))

        self._timers[uid] = async_track_point_in_time(self.hass, _fire, max(at, dt_util.now()))

    async def _deliver(self, uid: str) -> None:
        meta = self.store.data["reminders"].get(uid)
        item = self.store.find("reminders", uid)
        if not meta or not item or item["status"] != "needs_action":
            return
        person = meta.get("person")
        if meta.get("for_other") and meta["kind"] == "time" and not self.is_home(person):
            meta["waiting_home"] = True                       # say it when they get home
            self.store.changed()
            self._track_people()
            return
        name = self.person_name(person)
        if meta.get("for_other"):
            message = f"{name}, here's a reminder: {meta['task']}."
            sats = self.satellites()
        else:
            message = f"Reminder: {flip_pronouns(meta['task'])}."
            sats = [meta["satellite"]] if meta.get("satellite") else self.satellites()
        if meta["kind"] == "time" or meta.get("zone") == "zone.home":
            await self.announce(sats, message)
        await self.notify(person, "Reminder", sentence(meta["task"]))
        if meta["kind"] == "time" and meta.get("repeat", "once") != "once":
            prev = dt_util.parse_datetime(meta["at"])
            nxt = next_alarm(prev.hour, prev.minute, meta["repeat"], dt_util.now())
            meta["at"] = nxt.isoformat()
            self.store.update_item("reminders", uid, due=nxt.isoformat())
            self._schedule_reminder(uid)
            return
        self.store.update_item("reminders", uid, status="completed")
        self.store.data["reminders"].pop(uid, None)
        self.store.changed()

    @callback
    def _track_people(self) -> None:
        """Follow the people that location reminders (or waiting reminders) are about."""
        if self._person_unsub:
            self._person_unsub()
            self._person_unsub = None
        people = {m.get("person") for m in self.store.data["reminders"].values()
                  if m.get("person") and (m["kind"] != "time" or m.get("waiting_home"))}
        if people:
            self._person_unsub = async_track_state_change_event(self.hass, list(people), self._person_moved)

    @callback
    def _person_moved(self, event: Event[EventStateChangedData]) -> None:
        old, new = event.data["old_state"], event.data["new_state"]
        if not old or not new or old.state == new.state:
            return
        for uid, meta in list(self.store.data["reminders"].items()):
            if meta.get("person") != event.data["entity_id"]:
                continue
            target = meta.get("zone_state")
            if (meta.get("waiting_home") and new.state == STATE_HOME) or \
                    (meta["kind"] == "arrive" and new.state == target) or \
                    (meta["kind"] == "leave" and old.state == target and new.state != target):
                meta.pop("waiting_home", None)
                self.hass.async_create_task(self._deliver(uid))

    @callback
    def _reconcile(self) -> None:
        """Drop reminder details when the item was deleted or ticked off in the to-do list."""
        live = {i["uid"] for i in self.store.items("reminders") if i["status"] == "needs_action"}
        for uid in [u for u in self.store.data["reminders"] if u not in live]:
            self.store.data["reminders"].pop(uid, None)
            if (cancel := self._timers.pop(uid, None)):
                cancel()

    # ------------------------------------------------------------ alarms
    # An alarm record: {"targets": "all" | [satellite ids], "hour", "minute", "repeat", "next",
    # "person", "origin": the satellite it was set from (None = app / typed chat)}.
    # Key: "all", or the satellite ids joined with "+". A speaker's new alarm replaces the alarm with
    # the same key; an "all" alarm is its own record and is only replaced by another "all" alarm.

    def speakers_info(self) -> list[dict]:
        """Voice satellites with every name they can be called by (for resolve_speaker)."""
        ents, devs, areas = er.async_get(self.hass), dr.async_get(self.hass), ar.async_get(self.hass)
        sats = self.satellites() or [s.entity_id for s in self.hass.states.async_all("assist_satellite")]
        out = []
        for sat in sats:
            state = self.hass.states.get(sat)
            reg = ents.async_get(sat)
            dev = devs.async_get(reg.device_id) if reg and reg.device_id else None
            area_id = (reg.area_id if reg else None) or (dev.area_id if dev else None)
            area = areas.async_get_area(area_id) if area_id else None
            names = [state.name if state else sat.split(".", 1)[1].replace("_", " ")]
            if dev:
                names += [n for n in (dev.name_by_user, dev.name) if n]
            if reg:
                names += [a for a in reg.aliases if isinstance(a, str)]
            out.append({"entity_id": sat, "name": names[0], "names": names,
                        "area": area.name if area else None, "area_aliases": list(area.aliases) if area else []})
        return out

    def _names(self) -> dict[str, str]:
        return {s["entity_id"]: s["name"] for s in self.speakers_info()}

    @staticmethod
    def _key(targets) -> str:
        return ALL_SPEAKERS if targets == ALL_SPEAKERS else "+".join(sorted(targets))

    def _alarms(self) -> dict[str, dict]:
        alarms = self.store.data["alarms"]
        for key in list(alarms):                       # records from before targets existed
            a = alarms[key]
            if "targets" not in a:
                a["targets"] = ALL_SPEAKERS if key == "app" else [key]
                a.setdefault("origin", None if key == "app" else key)
                alarms[self._key(a["targets"])] = alarms.pop(key)
        return alarms

    def _sats_of(self, targets) -> list[str]:
        if targets == ALL_SPEAKERS:
            return [s["entity_id"] for s in self.speakers_info()]
        return list(targets)

    def _rings_on(self, targets, sat: str | None) -> bool:
        return sat is None or targets == ALL_SPEAKERS or sat in targets

    def _default_targets(self, user_input):
        option = self.entry.options.get(OPT_ALARM_SPEAKER)
        if option:
            return ALL_SPEAKERS if option == ALL_SPEAKERS else [option]
        sat = self.satellite_for(user_input)
        return [sat] if sat else ALL_SPEAKERS

    def _where(self, targets) -> str:
        return say_where(targets, self._names())

    def _place_targets(self, place: str | None, user_input):
        """(targets, None) or (None, what to say)."""
        if place is None:
            return self._default_targets(user_input), None
        if place == ALL_SPEAKERS:
            return ALL_SPEAKERS, None
        ids, question = resolve_speaker(place, self.speakers_info())
        if ids:
            return ids, None
        return None, question or f"I couldn't find a voice speaker called {place}."

    async def _h_alarm_set(self, slots: dict, user_input) -> str:
        when_text, place = split_alarm_place(slots.get("text", ""))
        targets, problem = self._place_targets(place, user_input)
        if problem:
            return problem
        now = dt_util.now()
        at, repeat = parse(when_text, now.replace(tzinfo=None), alarm=True)
        if not at:
            return "Sorry, I didn't catch the time for the alarm."
        at = at.replace(tzinfo=now.tzinfo, second=0, microsecond=0)
        key = self._key(targets)
        alarms = self._alarms()
        replaced = key in alarms
        alarms[key] = {"targets": targets, "hour": at.hour, "minute": at.minute, "repeat": repeat,
                       "next": at.isoformat(), "person": self.speaker_person(user_input),
                       "origin": self.satellite_for(user_input)}
        self.store.changed()
        self._schedule_alarm(key)
        said = say_alarm(at.replace(tzinfo=None), repeat, now.replace(tzinfo=None))
        return f"Your alarm is set for {said} {self._where(targets)}." + (
            " That replaces the one that was there." if replaced else "")

    def _mine(self, user_input) -> dict[str, dict]:
        sat = self.satellite_for(user_input)
        return {k: a for k, a in self._alarms().items() if self._rings_on(a["targets"], sat)}

    async def _h_alarm_query(self, slots: dict, user_input) -> str:
        sat = self.satellite_for(user_input)
        now = dt_util.now()
        lines = []
        for key, until in self._snoozed_until.items():
            if f"snooze:{key}" in self._timers and self._rings_on(self._ring_targets.get(key, []), sat):
                lines.append(f"Your alarm is snoozed until {fmt_time(dt_util.as_local(until))}.")
        for alarm in self._mine(user_input).values():
            at = dt_util.parse_datetime(alarm["next"])
            said = say_alarm(dt_util.as_local(at).replace(tzinfo=None), alarm["repeat"], now.replace(tzinfo=None))
            lines.append(f"{said} {self._where(alarm['targets'])}")
        if not lines:
            return "You don't have an alarm set."
        snoozed = [x for x in lines if x.startswith("Your alarm is snoozed")]
        rest = [x for x in lines if x not in snoozed]
        if not rest:
            return " ".join(snoozed)
        body = (f"Your alarm is set for {rest[0]}." if len(rest) == 1 else
                f"You have {len(rest)} alarms: " + "; ".join(rest) + ".")
        return " ".join(snoozed + [body])

    async def _h_alarm_cancel(self, slots: dict, user_input) -> str:
        if self._ringing_for(user_input):
            return await self._h_alarm_stop(slots, user_input)
        mine = self._mine(user_input)
        if not mine:
            return "You don't have an alarm set."
        for key in mine:
            self._alarms().pop(key, None)
            self._snooze_count.pop(key, None)
            if (cancel := self._timers.pop(f"alarm:{key}", None)):
                cancel()
        self.store.changed()
        return "Okay, your alarm is cancelled." if len(mine) == 1 else f"Okay, I cancelled {len(mine)} alarms."

    async def _h_alarm_move(self, slots: dict, user_input) -> str:
        _rest, place = split_alarm_place("x " + (slots.get("text") or "").strip())
        if place is None:
            place = re.sub(r"^(?:to |on |in )?(?:the )?", "", (slots.get("text") or "").strip().lower()) or None
        if not place:
            return "Where should the alarm ring?"
        targets, problem = self._place_targets(place, user_input)
        if problem:
            return problem
        mine = self._mine(user_input)
        sat = self.satellite_for(user_input)
        if sat and sat in mine:
            old_key = sat
        elif len(mine) == 1:
            old_key = next(iter(mine))
        elif not mine:
            return "You don't have an alarm set."
        else:
            return "You have more than one alarm. Ask from the speaker whose alarm you want to move."
        alarms = self._alarms()
        alarm = alarms.pop(old_key)
        if (cancel := self._timers.pop(f"alarm:{old_key}", None)):
            cancel()
        alarm["targets"] = targets
        new_key = self._key(targets)
        replaced = new_key in alarms and new_key != old_key
        alarms[new_key] = alarm
        self.store.changed()
        self._schedule_alarm(new_key)
        return f"Okay, your alarm will ring {self._where(targets)}." + (
            " That replaces the alarm that was there." if replaced else "")

    def snooze_default(self) -> int:
        return int(self.entry.options.get(OPT_SNOOZE, DEFAULTS[OPT_SNOOZE]))

    def snooze_limit(self) -> int | None:
        """0 when snoozing is off, else the per-alarm limit (None = unlimited)."""
        opts = self.entry.options
        return effective_limit(opts.get(OPT_SNOOZE_ENABLED, DEFAULTS[OPT_SNOOZE_ENABLED]),
                               opts.get(OPT_SNOOZE_LIMIT, DEFAULTS[OPT_SNOOZE_LIMIT]))

    def _save_option(self, key: str, value, **more) -> None:
        self.hass.config_entries.async_update_entry(self.entry, options={**self.entry.options, key: value, **more})

    async def _h_alarm_snooze_set(self, slots: dict, user_input) -> str:
        minutes, reply = snooze_length_reply(int(slots.get("minutes") or self.snooze_default()))
        self._save_option(OPT_SNOOZE, minutes)
        return reply

    async def _h_snooze_limit_set(self, slots: dict, user_input) -> str:
        enabled, limit, reply = snooze_limit_reply(int(slots.get("count", 0)))
        if enabled:
            self._save_option(OPT_SNOOZE_LIMIT, limit, **{OPT_SNOOZE_ENABLED: True})
        else:
            self._save_option(OPT_SNOOZE_ENABLED, False)    # keep the limit for when it's turned back on
        return reply

    async def _h_snooze_limit_clear(self, slots: dict, user_input) -> str:
        enabled, limit, reply = snooze_limit_reply(None)
        self._save_option(OPT_SNOOZE_LIMIT, limit, **{OPT_SNOOZE_ENABLED: enabled})
        return reply

    async def _h_snooze_limit_query(self, slots: dict, user_input) -> str:
        return describe_snooze(self.snooze_limit(), self.snooze_default())

    async def _h_alarm_snooze_query(self, slots: dict, user_input) -> str:
        n = self.snooze_default()
        return f"Snooze is {n} minute{'s' if n != 1 else ''}."

    def _ringing_for(self, user_input) -> list[str]:
        """Ringing alarm keys that this speaker can stop or snooze (any of them from the app)."""
        sat = self.satellite_for(user_input)
        return [k for k in self._ringing if self._rings_on(self._ring_targets.get(k, []), sat)]

    async def _h_alarm_snooze(self, slots: dict, user_input) -> str:
        keys = self._ringing_for(user_input)
        if not keys:
            return "There's no alarm going off right now."
        reply = ""
        for key in keys:
            used = self._snooze_count.get(key, 0)
            minutes, reply = snooze_decision(slots.get("minutes"), self.snooze_default(), self.snooze_limit(), used)
            if minutes is None:
                return reply                                  # keeps ringing
            self._snooze_count[key] = used + 1
            self._stop_ringing(key)
            when = dt_util.now() + dt.timedelta(minutes=minutes)

            @callback
            def _again(_now: dt.datetime, key: str = key) -> None:
                self._start_ringing(key, fresh=False)

            self._timers[f"snooze:{key}"] = async_track_point_in_time(self.hass, _again, when)
            self._snoozed_until[key] = when
        return reply

    async def _h_alarm_stop(self, slots: dict, user_input) -> str:
        sat = self.satellite_for(user_input)
        snoozed = [k for k in list(self._snoozed_until)
                   if f"snooze:{k}" in self._timers and self._rings_on(self._ring_targets.get(k, []), sat)]
        ringing = self._ringing_for(user_input)
        for key in snoozed:
            if (cancel := self._timers.pop(f"snooze:{key}", None)):
                cancel()
            self._snooze_count.pop(key, None)
        if not ringing:
            return "OK, I've turned off the snoozed alarm." if snoozed else "There's no alarm going off right now."
        for key in ringing:
            self._snooze_count.pop(key, None)
            self._stop_ringing(key)
        return "Alarm off. Good morning!" if dt_util.now().hour < 12 else "Alarm off."

    @callback
    def _schedule_alarm(self, key: str) -> None:
        if (cancel := self._timers.pop(f"alarm:{key}", None)):
            cancel()
        alarm = self._alarms().get(key)
        if not alarm:
            return
        at = dt_util.parse_datetime(alarm["next"])
        now = dt_util.now()
        if at is None or at < now - dt.timedelta(minutes=RING_MINUTES):
            if alarm["repeat"] == "once":                     # missed while Home Assistant was off
                self._alarms().pop(key, None)
                self.store.changed()
                return
            at = next_alarm(alarm["hour"], alarm["minute"], alarm["repeat"], now)
            alarm["next"] = at.isoformat()
            self.store.changed()

        @callback
        def _fire(_now: dt.datetime) -> None:
            self._timers.pop(f"alarm:{key}", None)
            current = self._alarms().get(key)
            if not current:
                return
            self._ring_targets[key] = current["targets"]
            self._ring_meta[key] = {"person": current.get("person"), "origin": current.get("origin")}
            self._start_ringing(key)
            if current["repeat"] == "once":
                self._alarms().pop(key, None)
            else:
                current["next"] = next_alarm(current["hour"], current["minute"], current["repeat"],
                                             dt_util.now()).isoformat()
                self._schedule_alarm(key)
            self.store.changed()

        self._timers[f"alarm:{key}"] = async_track_point_in_time(self.hass, _fire, max(at, now))

    @callback
    def _start_ringing(self, key: str, fresh: bool = True) -> None:
        self._timers.pop(f"snooze:{key}", None)
        if fresh:
            self._snooze_count.pop(key, None)                # a new alarm, not the end of a snooze
        if key not in self._ring_targets:                    # e.g. started directly
            alarm = self._alarms().get(key)
            self._ring_targets[key] = alarm["targets"] if alarm else (ALL_SPEAKERS if key == ALL_SPEAKERS
                                                                     else key.split("+"))
        if key in self._ringing:
            return
        self._ringing[key] = self.hass.async_create_background_task(self._ring(key), f"brave alarm {key}")

    @callback
    def _stop_ringing(self, key: str) -> None:
        task = self._ringing.pop(key, None)
        if task:
            task.cancel()
        for sat in self._sats_of(self._ring_targets.get(key, [])):
            player = self.media_player_for(sat)
            if player:
                ctx = Context()
                self._own_contexts.add(ctx.id)
                self.hass.async_create_task(self._call("media_player", "media_stop", {"entity_id": player}, ctx))

    def _tone_url(self) -> str | None:
        for kwargs in ({"allow_external": False}, {}):
            try:
                return get_url(self.hass, **kwargs) + ALARM_URL
            except NoURLAvailableError:
                continue
        return None

    async def _ring(self, key: str) -> None:
        """Ring on every target speaker through its own media player until stopped, snoozed or
        10 minutes pass. A stop from outside on any of those players stops it everywhere."""
        targets = self._ring_targets.get(key, [])
        sats = self._sats_of(targets)
        meta = self._ring_meta.get(key, {})
        try:
            if meta.get("origin") is None:                   # set from the app: phone + notification too
                await self.notify(meta.get("person"), "Alarm", "Your alarm is going off.")
                await self._call("persistent_notification", "create", {
                    "title": "Alarm", "message": f"Alarm at {dt_util.now().strftime('%H:%M')}.",
                    "notification_id": "brave_search_api_alarm"})
            url = self._tone_url()
            players = {sat: self.media_player_for(sat) for sat in sats}
            silent = [sat for sat, player in players.items() if not player or not url]
            if silent:
                await self.announce(silent, "Wake up! This is your alarm.")
            players = [p for p in players.values() if p and url]
            if not players:
                await asyncio.sleep(RING_MINUTES * 60)       # still "ringing", so snooze / stop work
                return
            stopped = asyncio.Event()
            ours = self._own_contexts                         # our own replays and stops

            @callback
            def _service(event: Event) -> None:
                data = event.data
                if data.get("domain") != "media_player" or data.get("service") not in STOP_SERVICES:
                    return
                if event.context.id in ours:
                    return
                ids = (data.get("service_data") or {}).get("entity_id")
                ids = [ids] if isinstance(ids, str) else list(ids or [])
                if not ids or any(p in ids for p in players):  # stopped by someone else (e.g. "stop")
                    stopped.set()

            @callback
            def _state(event: Event[EventStateChangedData]) -> None:
                new = event.data["new_state"]
                if new and new.state in ("paused", "off") and new.context.id not in ours:
                    stopped.set()                             # the tone never pauses or turns off itself

            unsubs = [self.hass.bus.async_listen(EVENT_CALL_SERVICE, _service),
                      async_track_state_change_event(self.hass, players, _state)]
            try:
                end = dt_util.now() + dt.timedelta(minutes=RING_MINUTES)
                while dt_util.now() < end and not stopped.is_set():
                    if len(ours) > 500:
                        ours.clear()
                    calls = []
                    for player in players:
                        ctx = Context()
                        ours.add(ctx.id)
                        calls.append(self._call("media_player", "play_media", {
                            "entity_id": player, "media_content_id": url,
                            "media_content_type": "music", "announce": True}, ctx))
                    await asyncio.gather(*calls)
                    try:
                        await asyncio.wait_for(stopped.wait(), 4)
                    except TimeoutError:
                        pass
            finally:
                for unsub in unsubs:
                    unsub()
            if stopped.is_set():
                _LOGGER.debug("Alarm %s stopped from outside", key)
                for other in players:                         # stop it on the other speakers too
                    ctx = Context()
                    ours.add(ctx.id)
                    self.hass.async_create_task(self._call("media_player", "media_stop", {"entity_id": other}, ctx))
                if (cancel := self._timers.pop(f"snooze:{key}", None)):
                    cancel()
                self._snooze_count.pop(key, None)
        finally:
            if self._ringing.get(key) is asyncio.current_task():
                self._ringing.pop(key, None)

    # ------------------------------------------------------------ notes
    def _notes(self) -> list[dict[str, Any]]:
        return [i for i in self.store.items("notes") if i["status"] == "needs_action"]

    async def _h_note_add(self, slots: dict, user_input) -> str:
        note = note_from(slots.get("text", ""), slots.get("put"))
        if not note:
            return "What should I note down?"
        self.store.add_item("notes", note, description=dt_util.now().strftime("%Y-%m-%d %H:%M"))
        return f"Got it. {sentence(flip_pronouns(note))}" if slots.get("put") else "OK, I've noted that."

    async def _h_note_find(self, slots: dict, user_input) -> str:
        best = best_note(slots.get("text", ""), [i["summary"] for i in self._notes()])
        if not best:
            return "I don't have a note about that."
        return sentence(flip_pronouns(best))

    async def _h_note_read(self, slots: dict, user_input) -> str:
        notes = self._notes()
        if not notes:
            return "You don't have any notes."
        return f"You have {len(notes)} note{'s' if len(notes) != 1 else ''}. " + \
            " ".join(sentence(flip_pronouns(n["summary"])) for n in notes[-8:])

    async def _h_note_clear(self, slots: dict, user_input) -> str:
        notes = self._notes()
        self.store.remove_items("notes", [n["uid"] for n in notes])
        return "OK, I've cleared your notes." if notes else "You don't have any notes."

    # ------------------------------------------------------------ household messages
    async def _h_message_leave(self, slots: dict, user_input) -> str:
        text = (slots.get("text") or "").strip(" ,.")
        if not text:
            return "What's the message?"
        person = None
        if slots.get("person"):
            person, problem = self.resolve(slots["person"])
            if not person:
                return problem
        sender = self.speaker_person(user_input)
        summary = f"For {self.person_name(person)}: {text}" if person else text
        desc = ";".join(x for x in (f"for={person}" if person else "", f"from={sender}" if sender else "") if x)
        self.store.add_item("messages", summary, description=desc or None)
        return f"OK, I'll pass that on to {self.person_name(person)}." if person else "OK, I've left the message."

    async def _h_message_read(self, slots: dict, user_input) -> str:
        me = self.speaker_person(user_input)
        pending = [i for i in self.store.items("messages") if i["status"] == "needs_action"]
        mine = [i for i in pending if not i.get("description") or "for=" not in i["description"]
                or me is None or f"for={me}" in i["description"]]
        if not mine:
            return "No new messages."
        said = []
        for i in mine:
            sender = re.search(r"from=([\w.]+)", i.get("description") or "")
            who = f"From {self.person_name(sender.group(1))}: " if sender and sender.group(1) != me else ""
            said.append(who + sentence(re.sub(r"^For \w+: ", "", i["summary"])))
            self.store.update_item("messages", i["uid"], status="completed")
        n = len(mine)
        return f"You have {n} message{'s' if n != 1 else ''}. " + " ".join(said)

    # ------------------------------------------------------------ stopwatch
    def _sw_key(self, user_input) -> str:
        return self.satellite_for(user_input) or user_input.device_id or "default"

    async def _h_stopwatch_start(self, slots: dict, user_input) -> str:
        self._stopwatches[self._sw_key(user_input)] = Stopwatch(started=dt_util.now())
        return "Stopwatch started."

    async def _h_stopwatch_read(self, slots: dict, user_input) -> str:
        sw = self._stopwatches.get(self._sw_key(user_input))
        if not sw or not sw.started:
            return "The stopwatch isn't running."
        return sentence(say_duration((dt_util.now() - sw.started).total_seconds()))

    async def _h_stopwatch_stop(self, slots: dict, user_input) -> str:
        sw = self._stopwatches.pop(self._sw_key(user_input), None)
        if not sw or not sw.started:
            return "The stopwatch isn't running."
        return f"Stopwatch stopped at {say_duration((dt_util.now() - sw.started).total_seconds())}."
