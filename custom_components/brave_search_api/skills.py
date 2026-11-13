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
from homeassistant.const import STATE_HOME
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er, intent
from homeassistant.helpers.event import async_track_point_in_time, async_track_state_change_event
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.util import dt as dt_util

from .const import ALARM_URL, RING_MINUTES, SNOOZE_MINUTES
from .core import intents as sentences
from .core.features import (
    Stopwatch,
    best_note,
    flip_pronouns,
    next_alarm,
    note_from,
    parse_reminder,
    say_alarm,
    say_duration,
    sentence,
)
from .core.intents import TIMER_INTENTS, Match
from .core.timeparse import parse, say_when
from .discovery import effective_section

_LOGGER = logging.getLogger(__name__)

HOW_TO_ADD_ZONE = ("I don't know a place called {place}. Add it as a zone in Settings, Areas, labels and "
                   "zones, Zones, then ask me again.")


class Skills:
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

    # ------------------------------------------------------------ lifecycle
    async def async_start(self) -> None:
        await self.hass.async_add_executor_job(sentences.load, "en")   # read sentence files off the loop
        self._unsubs.append(self.store.async_add_listener(self._reconcile))
        for uid in list(self.store.data["reminders"]):
            self._schedule_reminder(uid)
        for sat in list(self.store.data["alarms"]):
            self._schedule_alarm(sat)
        self._track_people()

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

    def people(self) -> dict[str, str]:
        """Spoken name (lower-case) -> person entity id."""
        out = {}
        for state in self.hass.states.async_all("person"):
            out[state.name.lower()] = state.entity_id
            out[state.name.split()[0].lower()] = state.entity_id
        return out

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
    async def _call(self, domain: str, service: str, data: dict[str, Any]) -> None:
        try:
            await self.hass.services.async_call(domain, service, data, blocking=True)
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
        return sentences.recognize(text, sorted({n for n in self.people()}, key=len, reverse=True))

    async def async_handle(self, match: Match, text: str, user_input: conversation.ConversationInput) -> str:
        if match.intent in TIMER_INTENTS:
            return await self._builtin_timer(match, text, user_input)
        handler = getattr(self, "_h_" + re.sub(r"(?<!^)([A-Z])", r"_\1", match.intent).lower())
        return await handler(match.slots, user_input)

    async def _builtin_timer(self, match: Match, text: str, user_input: conversation.ConversationInput) -> str:
        """Extra wordings for Home Assistant's own timers: hand the slots to the built-in intent."""
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
            elif (secs := (at - now).total_seconds()) < 3600:
                when = "in " + say_duration(max(secs, 1))
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
        who = f"I'll remind {self.person_name(person)}" if for_other else "OK, I'll remind you"
        return f"{who} to {flip_pronouns(req.task) if not for_other else req.task} {when}."

    async def _h_reminder_add_for(self, slots: dict, user_input) -> str:
        person = self.people().get((slots.get("person") or "").lower())
        if not person:
            return "Sorry, I don't know who that is."
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
    def _alarm_target(self, user_input) -> str | None:
        return self.satellite_for(user_input)

    async def _h_alarm_set(self, slots: dict, user_input) -> str:
        sat = self._alarm_target(user_input)
        if not sat:
            return "Alarms ring on a voice speaker. Please ask from the speaker you want it on."
        now = dt_util.now()
        at, repeat = parse(slots.get("text", ""), now.replace(tzinfo=None), alarm=True)
        if not at:
            return "Sorry, I didn't catch the time for the alarm."
        at = at.replace(tzinfo=now.tzinfo, second=0, microsecond=0)
        self.store.data["alarms"][sat] = {"hour": at.hour, "minute": at.minute, "repeat": repeat,
                                          "next": at.isoformat()}
        self.store.changed()
        self._schedule_alarm(sat)
        return f"Your alarm is set for {say_alarm(at.replace(tzinfo=None), repeat, now.replace(tzinfo=None))}."

    async def _h_alarm_query(self, slots: dict, user_input) -> str:
        sat = self._alarm_target(user_input)
        alarm = self.store.data["alarms"].get(sat or "")
        if not alarm:
            return "You don't have an alarm set."
        at = dt_util.parse_datetime(alarm["next"])
        now = dt_util.now()
        return f"Your alarm is set for {say_alarm(at.replace(tzinfo=None), alarm['repeat'], now.replace(tzinfo=None))}."

    async def _h_alarm_cancel(self, slots: dict, user_input) -> str:
        sat = self._alarm_target(user_input)
        if sat in self._ringing:
            return await self._h_alarm_stop(slots, user_input)
        if not sat or sat not in self.store.data["alarms"]:
            return "You don't have an alarm set."
        self.store.data["alarms"].pop(sat)
        self.store.changed()
        if (cancel := self._timers.pop(f"alarm:{sat}", None)):
            cancel()
        return "OK, your alarm is cancelled."

    async def _h_alarm_snooze(self, slots: dict, user_input) -> str:
        sat = self._alarm_target(user_input)
        if not sat or sat not in self._ringing:
            return "There's no alarm ringing."
        self._stop_ringing(sat)
        when = dt_util.now() + dt.timedelta(minutes=SNOOZE_MINUTES)

        @callback
        def _again(_now: dt.datetime) -> None:
            self._start_ringing(sat)

        self._timers[f"snooze:{sat}"] = async_track_point_in_time(self.hass, _again, when)
        return f"Snoozing for {SNOOZE_MINUTES} minutes."

    async def _h_alarm_stop(self, slots: dict, user_input) -> str:
        sat = self._alarm_target(user_input)
        if sat and (cancel := self._timers.pop(f"snooze:{sat}", None)):
            cancel()
            if sat not in self._ringing:
                return "OK, I've turned off the snoozed alarm."
        if not sat or sat not in self._ringing:
            return "There's no alarm ringing."
        self._stop_ringing(sat)
        return "Alarm off. Good morning!" if dt_util.now().hour < 12 else "Alarm off."

    @callback
    def _schedule_alarm(self, sat: str) -> None:
        if (cancel := self._timers.pop(f"alarm:{sat}", None)):
            cancel()
        alarm = self.store.data["alarms"].get(sat)
        if not alarm:
            return
        at = dt_util.parse_datetime(alarm["next"])
        now = dt_util.now()
        if at is None or at < now - dt.timedelta(minutes=RING_MINUTES):
            if alarm["repeat"] == "once":                     # missed while Home Assistant was off
                self.store.data["alarms"].pop(sat, None)
                self.store.changed()
                return
            at = next_alarm(alarm["hour"], alarm["minute"], alarm["repeat"], now)
            alarm["next"] = at.isoformat()
            self.store.changed()

        @callback
        def _fire(_now: dt.datetime) -> None:
            self._timers.pop(f"alarm:{sat}", None)
            self._start_ringing(sat)
            current = self.store.data["alarms"].get(sat)
            if not current:
                return
            if current["repeat"] == "once":
                self.store.data["alarms"].pop(sat, None)
            else:
                current["next"] = next_alarm(current["hour"], current["minute"], current["repeat"],
                                             dt_util.now()).isoformat()
                self._schedule_alarm(sat)
            self.store.changed()

        self._timers[f"alarm:{sat}"] = async_track_point_in_time(self.hass, _fire, max(at, now))

    @callback
    def _start_ringing(self, sat: str) -> None:
        self._timers.pop(f"snooze:{sat}", None)
        if sat in self._ringing:
            return
        self._ringing[sat] = self.hass.async_create_background_task(self._ring(sat), f"brave alarm {sat}")

    @callback
    def _stop_ringing(self, sat: str) -> None:
        task = self._ringing.pop(sat, None)
        if task:
            task.cancel()
        player = self.media_player_for(sat)
        if player:
            self.hass.async_create_task(self._call("media_player", "media_stop", {"entity_id": player}))

    async def _ring(self, sat: str) -> None:
        player = self.media_player_for(sat)
        try:
            base = get_url(self.hass, allow_external=False)
        except NoURLAvailableError:
            base = get_url(self.hass)
        try:
            if not player:
                await self.announce([sat], "Wake up! This is your alarm.")
                return
            end = dt_util.now() + dt.timedelta(minutes=RING_MINUTES)
            while dt_util.now() < end:
                await self._call("media_player", "play_media", {
                    "entity_id": player, "media_content_id": base + ALARM_URL,
                    "media_content_type": "music", "announce": True})
                await asyncio.sleep(4)
        finally:
            if self._ringing.get(sat) is asyncio.current_task():
                self._ringing.pop(sat, None)

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
        person = self.people().get((slots.get("person") or "").lower()) if slots.get("person") else None
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
