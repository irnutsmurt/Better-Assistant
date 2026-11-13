"""Stage 3 skills: music, calendar, rooms and lights, climate, outside and cameras, TV, bed, health
report, guest and night mode, broadcast and help. A mixin for Skills; every device comes from
detection plus the settings page."""
from __future__ import annotations

import datetime as dt
import logging
import re
from typing import TYPE_CHECKING, Any

from homeassistant.components import conversation
from homeassistant.components.homeassistant.exposed_entities import (
    DATA_EXPOSED_ENTITIES,
    async_expose_entity,
    async_get_entity_settings,
)
from homeassistant.core import callback
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er, intent
from homeassistant.helpers.event import async_call_later, async_track_time_change
from homeassistant.util import dt as dt_util

from .const import EXTRA_FIELDS, FEATURE_SECTIONS, HA_AGENT_ID, OPT_FEATURES, OPT_SETTINGS
from .core.calendar import day_range, parse_event, say_events, say_next
from .core.devices import (
    HELP_TOPICS,
    adjust_target,
    app_words,
    battery_name,
    climate_mode_words,
    exposure_record,
    in_window,
    is_heating_answer,
    preset_words,
    restore_action,
    round_to_step,
    say_batteries,
    say_climate,
    say_health,
    say_help,
    say_outside,
    side_of,
    sleeper_matches,
    source_words,
    step_kelvin,
)
from .core.music import is_news, parse_music_query, say_now_playing
from .core.timeparse import say_when

if TYPE_CHECKING:
    from .skills import Skills  # noqa: F401

_LOGGER = logging.getLogger(__name__)

GUEST_BLOCKED = {"CalendarList", "CalendarNext", "CalendarAdd", "NoteAdd", "NoteFind", "NoteRead", "NoteClear",
                 "ReminderList", "ReminderCancel", "ReminderCancelAll", "BedQuery", "BedSleep"}
GUEST_REPLY = "Sorry, that isn't available while guest mode is on."
DOMAINS_IN_ROOM_ON = ("light", "switch")          # plus fans when the setting is on


def async_get_should_expose_default(hass, entity_id: str) -> bool:
    """Whether Assist would expose this entity by default, without storing anything."""
    try:
        return bool(hass.data[DATA_EXPOSED_ENTITIES].async_get_should_expose("conversation", entity_id))
    except (KeyError, AttributeError):
        return False


class HouseSkills:
    """Mixed into Skills (uses its hass, entry, store and helper methods)."""

    # ------------------------------------------------------------ settings and switches
    def feature_on(self, section: str) -> bool:
        return bool((self.entry.options.get(OPT_FEATURES) or {}).get(section, True))

    def disabled_features(self) -> frozenset[str]:
        return frozenset(s for s in FEATURE_SECTIONS if not self.feature_on(s))

    def setting(self, section: str, key: str):
        value = ((self.entry.options.get(OPT_SETTINGS) or {}).get(section) or {}).get(key)
        return EXTRA_FIELDS[section][key][1] if value is None else value

    def _modes(self) -> dict:
        return self.store.data.setdefault("modes", {"guest": False, "night": False, "night_saved": {},
                                                    "guest_saved": {}})

    def guest_on(self) -> bool:
        return bool(self._modes().get("guest"))

    def night_on(self) -> bool:
        return bool(self._modes().get("night"))

    # ------------------------------------------------------------ names for the recognizer
    def _area_name(self, area_id: str | None) -> str | None:
        area = ar.async_get(self.hass).async_get_area(area_id) if area_id else None
        return area.name if area else None

    def _area_names(self, area_id: str) -> list[str]:
        area = ar.async_get(self.hass).async_get_area(area_id)
        return [area.name.lower(), *[a.lower() for a in area.aliases]] if area else []

    def _friendly(self, entity_id: str) -> str:
        state = self.hass.states.get(entity_id)
        return state.name if state else entity_id.split(".", 1)[1].replace("_", " ")

    def _entity_area(self, entity_id: str) -> str | None:
        ents, devs = er.async_get(self.hass), dr.async_get(self.hass)
        reg = ents.async_get(entity_id)
        if not reg:
            return None
        if reg.area_id:
            return reg.area_id
        dev = devs.async_get(reg.device_id) if reg.device_id else None
        return dev.area_id if dev else None

    def _names_for(self, entity_id: str) -> list[str]:
        reg = er.async_get(self.hass).async_get(entity_id)
        names = [self._friendly(entity_id).lower()]
        if reg:
            names += [a.lower() for a in reg.aliases if isinstance(a, str)]
        return names

    def _rooms(self) -> dict[str, dict[str, list[str]]]:
        rooms = {a: {k: list(v) for k, v in r.items()} for a, r in (self.store.detected.get("rooms") or {}).items()}
        lights = self._section("rooms_lights").get("lights")
        if lights is not None:                                # the user's choice of lights wins
            for room in rooms.values():
                room["lights"] = [e for e in room.get("lights", []) if e in lights]
        return rooms

    def _ma_players(self) -> list[str]:
        return list(self._section("music").get("music_players") or [])

    def slot_lists(self) -> dict[str, Any]:
        lists: dict[str, Any] = {}
        rooms = self._rooms()
        lists["area"] = [n for area_id in rooms for n in self._area_names(area_id)]
        light_target: dict[str, str] = {}
        for area_id, room in rooms.items():
            if any(e.startswith("light.") for e in room.get("lights", [])):
                for n in self._area_names(area_id):
                    light_target[n] = f"area:{area_id}"
                    light_target[f"{n} lights"] = f"area:{area_id}"
                    light_target[f"{n} light"] = f"area:{area_id}"
        for eid in (self._section("rooms_lights").get("lights") or []):
            if eid.startswith("light."):
                for n in self._names_for(eid):
                    light_target.setdefault(n, eid)
        lists["light_target"] = light_target
        music: dict[str, str] = {}
        for eid in self._ma_players():
            for n in self._names_for(eid):
                music[n] = eid
            area = self._entity_area(eid)
            for n in (self._area_names(area) if area else []):
                music.setdefault(n, f"area:{area}")
        lists["music_target"] = music
        cals = {}
        for eid in self._section("calendar").get("calendars") or []:
            for n in self._names_for(eid):
                cals[n] = eid
                cals[re.sub(r"\s+calendar$", "", n)] = eid
        lists["calendar"] = cals
        lists["place"] = {name: name for name in self._outside_places()}
        cams = {}
        for eid in self._section("cameras_outside").get("cameras") or []:
            for n in self._names_for(eid):
                cams[re.sub(r"\s+camera$", "", n)] = eid
        lists["camera"] = cams
        tvs = {}
        for eid in (self._section("cameras_outside").get("camera_cast_targets") or []) + \
                (self._section("tv").get("tvs") or []):
            for n in self._names_for(eid):
                tvs[n] = eid
        lists["tv"] = tvs
        sources, apps = {}, {}
        for tv in self._section("tv").get("tvs") or []:
            state = self.hass.states.get(tv)
            sources.update(source_words((state.attributes.get("source_list") if state else None) or []))
            remote = self._tv_remote(tv)
            rstate = self.hass.states.get(remote) if remote else None
            apps.update(app_words((rstate.attributes.get("activity_list") if rstate else None) or None))
        lists["tv_source"] = sources
        lists["tv_app"] = apps if self._section("tv").get("tvs") else {}
        lists["bed_preset"] = self._bed_preset_words()
        modes, presets = {}, {}
        for eid in self._section("thermostat").get("thermostats") or []:
            state = self.hass.states.get(eid)
            if state:
                modes.update(climate_mode_words(state.attributes.get("hvac_modes") or []))
                presets.update({k: v for k, v in preset_words(state.attributes.get("preset_modes") or []).items()
                                if k not in ("none", "guest", "night", "guest mode", "night mode")})
        lists["climate_mode"], lists["climate_preset"] = modes, presets
        lists["battery_thing"] = {battery_name(self._friendly(e)): e for e in self._battery_entities()}
        lists["help_topic"] = dict(HELP_TOPICS)
        return lists

    # ------------------------------------------------------------ shared
    async def _ha_agent(self, text: str, user_input) -> tuple[bool, str]:
        result = await conversation.async_converse(
            self.hass, text, None, user_input.context, user_input.language, agent_id=HA_AGENT_ID,
            device_id=user_input.device_id, satellite_id=getattr(user_input, "satellite_id", None))
        r = result.response
        ok = r.response_type != intent.IntentResponseType.ERROR
        return ok, (r.speech or {}).get("plain", {}).get("speech", "")

    def _sat_area(self, user_input) -> str | None:
        sat = self.satellite_for(user_input)
        return self._entity_area(sat) if sat else None

    def _nearest(self, candidates: list[str], user_input) -> str | None:
        if not candidates:
            return None
        area = self._sat_area(user_input)
        return next((c for c in candidates if area and self._entity_area(c) == area), candidates[0])

    # ------------------------------------------------------------ music
    def _ma_ready(self) -> bool:
        return self.hass.services.has_service("music_assistant", "play_media")

    def _default_player(self, user_input) -> str | None:
        sat = self.satellite_for(user_input)
        for s in self.store.detected.get("satellites") or []:
            if s.get("entity_id") == sat and s.get("here_player") in self._ma_players():
                return s["here_player"]
        players = self._ma_players()
        area = self._sat_area(user_input)
        here = [p for p in players if area and self._entity_area(p) == area]
        if here:
            return here[0]
        return players[0] if len(players) == 1 else None

    def _music_targets(self, target: str | None, user_input) -> list[str]:
        if target == "all":
            return self._ma_players()
        if target and target.startswith("area:"):
            return [p for p in self._ma_players() if self._entity_area(p) == target[5:]]
        if target:
            return [target]
        p = self._default_player(user_input)
        return [p] if p else []

    def _playing(self, user_input) -> list[str]:
        players = [p for p in self._ma_players() if (s := self.hass.states.get(p)) and s.state == "playing"]
        near = self._default_player(user_input)
        return [near] if near in players else players

    async def _h_music_play(self, slots, user_input) -> str:
        query = slots.get("query", "")
        if is_news(query):                                   # news and podcasts: Home Assistant's own way
            ok, speech = await self._ha_agent(f"play {query}", user_input)
            return speech if ok and speech else "Sorry, I can't play that here."
        if not self._ma_ready():
            return "Music Assistant isn't set up, so I can't play music."
        targets = self._music_targets(slots.get("music_target"), user_input)
        if not targets:
            return "Which speaker? Say something like: play jazz in the kitchen."
        req = parse_music_query(query)
        if req is None or not req.name:
            await self._call("media_player", "media_play", {"entity_id": targets})
            return "Okay."
        data: dict[str, Any] = {"entity_id": targets, "media_id": req.name}
        if req.media_type:
            data["media_type"] = req.media_type
        if req.radio:
            data["radio_mode"] = True
        await self._call("music_assistant", "play_media", data)
        where = "everywhere" if slots.get("music_target") == "all" else \
            "on the " + " and the ".join(self._friendly(t).lower() for t in targets)
        what = {"artist": f"music by {req.name}", "album": f"the album {req.name}",
                "playlist": f"your {req.name} playlist", "track": req.name}.get(req.media_type or "", req.name)
        return f"Playing {'music like ' + req.name if req.radio else what} {where}."

    async def _h_music_now_playing(self, slots, user_input) -> str:
        playing = self._playing(user_input)
        if not playing:
            return "Nothing is playing right now."
        st = self.hass.states.get(playing[0])
        return say_now_playing(st.attributes.get("media_title"), st.attributes.get("media_artist"),
                               self._friendly(playing[0]))

    async def _volume(self, user_input, delta: float) -> str:
        playing = self._playing(user_input) or ([self._default_player(user_input)] if self._default_player(user_input) else [])
        if not playing:
            return "Nothing is playing right now."
        for p in playing:
            st = self.hass.states.get(p)
            vol = (st.attributes.get("volume_level") if st else None) or 0.3
            await self._call("media_player", "volume_set",
                             {"entity_id": p, "volume_level": round(max(0.0, min(1.0, vol + delta)), 2)})
        return "Okay."

    async def _h_music_louder(self, slots, user_input) -> str:
        return await self._volume(user_input, 0.1)

    async def _h_music_quieter(self, slots, user_input) -> str:
        return await self._volume(user_input, -0.1)

    async def _h_music_stop(self, slots, user_input) -> str:
        targets = self._music_targets(slots.get("music_target"), user_input) if slots.get("music_target") \
            else self._playing(user_input)
        if not targets:
            return "Nothing is playing right now."
        await self._call("media_player", "media_pause", {"entity_id": targets})
        return "Okay, music stopped."

    async def _h_music_move(self, slots, user_input) -> str:
        if not self._ma_ready():
            return "Music Assistant isn't set up, so I can't move the music."
        source = self._playing(user_input)
        targets = self._music_targets(slots.get("music_target"), user_input)
        if not source:
            return "Nothing is playing right now."
        if not targets or targets[0] == source[0]:
            return "It's already playing there."
        await self._call("music_assistant", "transfer_queue", {"entity_id": targets[0], "source_player": source[0]})
        return f"Okay, moving the music to the {self._friendly(targets[0]).lower()}."

    async def _h_music_sleep(self, slots, user_input) -> str:
        minutes = int(slots.get("minutes") or 0) or int(slots.get("hours") or 0) * 60
        playing = self._playing(user_input)
        if not playing:
            return "Nothing is playing right now."

        @callback
        def _stop(_now) -> None:
            self._timers.pop("music_sleep", None)
            self.hass.async_create_task(self._call("media_player", "media_pause", {"entity_id": playing}))

        if (old := self._timers.pop("music_sleep", None)):
            old()
        self._timers["music_sleep"] = async_call_later(self.hass, minutes * 60, _stop)
        return f"Okay, I'll stop the music in {minutes} minute{'s' if minutes != 1 else ''}."

    # ------------------------------------------------------------ calendar
    async def _events(self, start: dt.datetime, end: dt.datetime) -> list[dict]:
        cals = list(self._section("calendar").get("calendars") or [])
        if not cals:
            return []
        try:
            resp = await self.hass.services.async_call(
                "calendar", "get_events", {"entity_id": cals, "start_date_time": start.isoformat(),
                                           "end_date_time": end.isoformat()}, blocking=True, return_response=True)
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Could not read the calendars", exc_info=True)
            return []
        events = []
        for data in (resp or {}).values():
            for e in data.get("events") or []:
                start_v = e.get("start")
                if isinstance(start_v, str) and len(start_v) > 10:
                    start_v = dt_util.as_local(dt_util.parse_datetime(start_v)).replace(tzinfo=None).isoformat()
                events.append({"summary": e.get("summary"), "start": start_v})
        return events

    async def _h_calendar_list(self, slots, user_input) -> str:
        if not self._section("calendar").get("calendars"):
            return "There are no calendars set up for me to read."
        now = dt_util.now()
        start, end, spoken = day_range(slots.get("range") or "today", now)
        events = await self._events(start, end)
        return say_events(events, spoken, now.replace(tzinfo=None))

    async def _h_calendar_next(self, slots, user_input) -> str:
        now = dt_util.now()
        events = await self._events(now, now + dt.timedelta(days=60))

        def key(e):
            s = str(e["start"])
            return s if len(s) > 10 else s + "T00:00:00"

        events = sorted(events, key=key)
        return say_next(events[0] if events else None, now.replace(tzinfo=None))

    async def _h_calendar_add(self, slots, user_input) -> str:
        cal = slots.get("calendar") or self._section("calendar").get("write_calendar")
        if not cal:
            return "There's no calendar to add events to. Pick one in the integration's calendar settings."
        now = dt_util.now().replace(tzinfo=None)
        text = f"{slots.get('text', '')} {slots.get('when', '')}".strip()
        ev = parse_event(text, now)
        if not ev:
            return "When is it? Say something like: add dentist to my calendar tomorrow at 3."
        data: dict[str, Any] = {"entity_id": cal, "summary": ev.title}
        if ev.all_day:
            data.update(start_date=ev.start.isoformat(), end_date=ev.end.isoformat())
            when = "today" if ev.start == now.date() else "tomorrow" if ev.start == now.date() + dt.timedelta(days=1) \
                else ev.start.strftime("%A, %B ") + str(ev.start.day)
            when += ", all day"
        else:
            data.update(start_date_time=ev.start.isoformat(), end_date_time=ev.end.isoformat())
            when = say_when(ev.start, now)
        try:
            await self.hass.services.async_call("calendar", "create_event", data, blocking=True)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Could not add the event", exc_info=True)
            return f"Sorry, I couldn't add that to the calendar ({type(err).__name__})."
        return f"Okay, I added {ev.title} to the {self._friendly(cal).lower()} calendar for {when}."

    # ------------------------------------------------------------ rooms and lights
    async def _room(self, area_id: str, on: bool) -> str:
        room = self._rooms().get(area_id) or {}
        lights = [e for e in room.get("lights", []) if e.split(".", 1)[0] in DOMAINS_IN_ROOM_ON]
        if self.setting("rooms_lights", "include_fans"):
            lights += room.get("fans", [])
        name = self._area_name(area_id) or "room"
        if on:
            if not lights:
                return f"There are no lights in the {name.lower()}."
            await self._call("homeassistant", "turn_on", {"entity_id": lights})
            return f"Okay, the {name.lower()} is on."
        players = room.get("media_players", [])
        if lights:
            await self._call("homeassistant", "turn_off", {"entity_id": lights})
        for p in players:
            await self._call("media_player", "turn_off", {"entity_id": p})
        return f"Okay, the {name.lower()} is off."

    def _area_id(self, spoken: str) -> str | None:
        s = spoken.lower().strip()
        return next((a for a in self._rooms() if s in self._area_names(a)), None)

    async def _h_room_off(self, slots, user_input) -> str:
        area = self._area_id(slots.get("area", ""))
        return await self._room(area, False) if area else "I don't know that room."

    async def _h_room_on(self, slots, user_input) -> str:
        area = self._area_id(slots.get("area", ""))
        return await self._room(area, True) if area else "I don't know that room."

    async def _run_command(self, text: str, user_input) -> str:
        match = self.recognize(text)
        if match and match.intent in ("RoomOn", "RoomOff"):
            return await self.async_handle(match, text, user_input)
        ok, speech = await self._ha_agent(text, user_input)
        return speech if ok else ""

    def _later(self, seconds: float, text: str, user_input) -> None:
        key = f"later:{dt_util.now().timestamp()}:{text}"

        @callback
        def _go(_now) -> None:
            self._timers.pop(key, None)
            self.hass.async_create_task(self._run_command(text, user_input))

        self._timers[key] = async_call_later(self.hass, seconds, _go)

    @staticmethod
    def _seconds(slots) -> float:
        amount = float(slots.get("amount") or 1)
        return amount * {"seconds": 1, "minutes": 60, "hours": 3600}.get(slots.get("unit", "minutes"), 60)

    @staticmethod
    def _say_delay(slots) -> str:
        amount = slots.get("amount") or 1
        unit = slots.get("unit", "minutes")
        return f"{amount:g} {unit.rstrip('s') if float(amount) == 1 else unit}"

    async def _h_delayed_command(self, slots, user_input) -> str:
        thing = slots.get("thing", "").strip()
        verb = slots.get("verb", "off")
        self._later(self._seconds(slots), f"turn {verb} {thing}", user_input)
        return f"Okay, I'll turn {verb} {thing} in {self._say_delay(slots)}."

    async def _h_timed_command(self, slots, user_input) -> str:
        thing = slots.get("thing", "").strip()
        first = await self._run_command(f"turn on {thing}", user_input)
        if not first:
            return f"Sorry, I couldn't turn on {thing}."
        self._later(self._seconds(slots), f"turn off {thing}", user_input)
        return f"{first.rstrip('.')}. I'll turn it off in {self._say_delay(slots)}."

    def _lights_for(self, target: str) -> list[str]:
        if target.startswith("area:"):
            return [e for e in self._rooms().get(target[5:], {}).get("lights", []) if e.startswith("light.")]
        return [target]

    def _target_name(self, target: str) -> str:
        return (self._area_name(target[5:]) or "room").lower() + " lights" if target.startswith("area:") \
            else self._friendly(target).lower()

    async def _h_light_dim(self, slots, user_input, up: bool = False) -> str:
        target = slots.get("light_target", "")
        lights = self._lights_for(target)
        if not lights:
            return "I couldn't find those lights."
        step = int(slots.get("percent") or self.setting("rooms_lights", "dim_step"))
        await self._call("light", "turn_on", {"entity_id": lights, "brightness_step_pct": step if up else -step})
        return f"Okay, {'brightening' if up else 'dimming'} the {self._target_name(target)}."

    async def _h_light_brighten(self, slots, user_input) -> str:
        return await self._h_light_dim(slots, user_input, up=True)

    async def _kelvin(self, slots, warmer: bool) -> str:
        target = slots.get("light_target", "")
        done = 0
        for light in self._lights_for(target):
            st = self.hass.states.get(light)
            if not st or "color_temp" not in (st.attributes.get("supported_color_modes") or []):
                continue
            k = step_kelvin(st.attributes.get("color_temp_kelvin"), int(self.setting("rooms_lights", "kelvin_step")),
                            warmer, st.attributes.get("min_color_temp_kelvin") or 2000,
                            st.attributes.get("max_color_temp_kelvin") or 6500)
            await self._call("light", "turn_on", {"entity_id": light, "color_temp_kelvin": k})
            done += 1
        if not done:
            return f"The {self._target_name(target)} can't change colour temperature."
        return f"Okay, making the {self._target_name(target)} {'warmer' if warmer else 'cooler'}."

    async def _h_light_warmer(self, slots, user_input) -> str:
        return await self._kelvin(slots, True)

    async def _h_light_cooler(self, slots, user_input) -> str:
        return await self._kelvin(slots, False)

    # ------------------------------------------------------------ climate
    def _thermostat(self, user_input) -> str | None:
        return self._nearest(list(self._section("thermostat").get("thermostats") or []), user_input)

    async def _climate_step(self, slots, user_input, sign: int) -> str:
        eid = self._thermostat(user_input)
        st = self.hass.states.get(eid) if eid else None
        if not st:
            return "I couldn't find a thermostat."
        if st.state == "off":
            return f"The {self._friendly(eid).lower()} is off. Say \"turn on the heat\" first."
        delta = sign * float(slots.get("degrees") or self.setting("thermostat", "degree_step"))
        data = adjust_target(dict(st.attributes), delta)
        if not data:
            return "The thermostat doesn't have a temperature I can change."
        await self._call("climate", "set_temperature", {"entity_id": eid, **data})
        target = data.get("temperature")
        if target is not None:
            return f"Okay, the thermostat is now set to {target:g} degrees."
        return f"Okay, the thermostat is now set between {data['target_temp_low']:g} and {data['target_temp_high']:g} degrees."

    async def _h_climate_warmer(self, slots, user_input) -> str:
        return await self._climate_step(slots, user_input, 1)

    async def _h_climate_cooler(self, slots, user_input) -> str:
        return await self._climate_step(slots, user_input, -1)

    async def _h_climate_query(self, slots, user_input) -> str:
        eid = self._thermostat(user_input)
        st = self.hass.states.get(eid) if eid else None
        return say_climate(self._friendly(eid).lower(), st.state, dict(st.attributes)) if st else \
            "I couldn't find a thermostat."

    async def _h_climate_is_on(self, slots, user_input) -> str:
        eid = self._thermostat(user_input)
        st = self.hass.states.get(eid) if eid else None
        return is_heating_answer(st.state, dict(st.attributes), slots.get("what", "heat")) if st else \
            "I couldn't find a thermostat."

    async def _h_climate_mode(self, slots, user_input) -> str:
        eid = self._thermostat(user_input)
        st = self.hass.states.get(eid) if eid else None
        if not st:
            return "I couldn't find a thermostat."
        mode = slots.get("mode")
        if mode not in (st.attributes.get("hvac_modes") or []):
            word = str(mode).replace("_", " ")
            return f"The thermostat doesn't have {'an' if word[:1] in 'aeiou' else 'a'} {word} mode."
        await self._call("climate", "set_hvac_mode", {"entity_id": eid, "hvac_mode": mode})
        return "Okay, the thermostat is off." if mode == "off" else \
            f"Okay, the thermostat is set to {mode.replace('_', ' ')}."

    async def _h_climate_preset(self, slots, user_input) -> str:
        eid = self._thermostat(user_input)
        st = self.hass.states.get(eid) if eid else None
        preset = slots.get("preset")
        if not st or preset not in (st.attributes.get("preset_modes") or []):
            return "The thermostat doesn't have that mode."
        await self._call("climate", "set_preset_mode", {"entity_id": eid, "preset_mode": preset})
        return f"Okay, the thermostat is in {preset.replace('_', ' ')} mode."

    # ------------------------------------------------------------ outside and cameras
    def _outside_sensors(self) -> list[dict]:
        sensors = list(self.store.detected.get("outside_sensors") or [])
        chosen = self._section("cameras_outside").get("outside_sensors")
        if chosen is not None:
            sensors = [s for s in sensors if s["entity_id"] in chosen] + \
                [{"entity_id": e, "group": None, "area_id": self._entity_area(e)} for e in chosen
                 if e not in {s["entity_id"] for s in sensors}]
        outdoor = set(self._section("cameras_outside").get("outdoor_areas") or [])
        seen = {s["entity_id"] for s in sensors}
        for st in self.hass.states.async_all("binary_sensor"):     # outdoor motion sensors too
            if st.entity_id in seen or st.attributes.get("device_class") != "motion":
                continue
            area = self._entity_area(st.entity_id)
            if area and area in outdoor:
                sensors.append({"entity_id": st.entity_id, "group": None, "area_id": area, "motion": True})
        return sensors

    def _outside_places(self) -> list[str]:
        names = set()
        for s in self._outside_sensors():
            if s.get("group"):
                names.add(s["group"].replace("_", " ").lower())
            if s.get("area_id"):
                names.update(self._area_names(s["area_id"]))
        return sorted(names)

    def _place_sensors(self, place: str) -> list[dict]:
        sensors = self._outside_sensors()
        if place == "outside":
            return sensors
        p = place.lower()
        return [s for s in sensors if (s.get("group") or "").replace("_", " ").lower() == p
                or (s.get("area_id") and p in self._area_names(s["area_id"]))]

    def _outside_answer(self, place: str, motion: bool) -> str:
        sensors = self._place_sensors(place)
        if not sensors:
            return "I don't have any outdoor sensors for that."
        if not motion:                                         # people first, motion as a fallback
            people = [s for s in sensors if not s.get("motion")
                      and self.hass.states.get(s["entity_id"]) is not None
                      and self.hass.states.get(s["entity_id"]).attributes.get("device_class") != "motion"]
            if not people:
                motion = True                                  # only motion sensors: say it as motion
            sensors = people or sensors
        else:
            moving = [s for s in sensors if s.get("motion") or
                      (self.hass.states.get(s["entity_id"]) and
                       self.hass.states.get(s["entity_id"]).attributes.get("device_class") == "motion")]
            sensors = moving or sensors
        states = [st for s in sensors if (st := self.hass.states.get(s["entity_id"]))]
        active = any(st.state == "on" for st in states)
        offs = [st.last_changed for st in states if st.state == "off"]
        last = (dt_util.utcnow() - max(offs)).total_seconds() if offs else None
        return say_outside(place, active, last, "motion" if motion else "person")

    async def _h_outside_anyone(self, slots, user_input) -> str:
        return self._outside_answer(slots.get("place", "outside"), False)

    async def _h_outside_motion(self, slots, user_input) -> str:
        return self._outside_answer(slots.get("place", "outside"), True)

    async def _h_camera_show(self, slots, user_input) -> str:
        camera = slots.get("camera")
        tv = slots.get("tv") or self._nearest(list(self._section("cameras_outside").get("camera_cast_targets") or []),
                                              user_input)
        if not camera or not tv:
            return "I don't have a TV to show cameras on." if camera else "I don't know that camera."
        await self._call("camera", "play_stream", {"entity_id": camera, "media_player": tv, "format": "hls"})
        self._modes()["camera_tv"] = tv
        return f"Showing the {self._friendly(camera).lower()} on the {self._friendly(tv).lower()}."

    async def _h_camera_close(self, slots, user_input) -> str:
        tv = self._modes().get("camera_tv")
        if not tv:
            return "No camera is showing."
        await self._call("media_player", "media_stop", {"entity_id": tv})
        self._modes().pop("camera_tv", None)
        return "Okay, closed the camera."

    # ------------------------------------------------------------ TV
    def _tv_remote(self, tv: str) -> str | None:
        for t in self.store.detected.get("tvs") or []:
            if t.get("entity_id") == tv:
                return t.get("remote")
        return None

    def _tv_for(self, slots, user_input, need_source: str | None = None) -> str | None:
        tvs = list(self._section("tv").get("tvs") or [])
        if slots.get("tv") in tvs:
            return slots["tv"]
        if need_source:
            having = [t for t in tvs if need_source in ((s := self.hass.states.get(t)) and s.attributes.get("source_list") or [])]
            tvs = having or tvs
        return self._nearest(tvs, user_input)

    async def _h_tv_source(self, slots, user_input) -> str:
        source = slots.get("source")
        tv = self._tv_for(slots, user_input, source)
        if not tv:
            return "I couldn't find a TV."
        await self._call("media_player", "select_source", {"entity_id": tv, "source": source})
        return f"Okay, switching the {self._friendly(tv).lower()} to {source}."

    async def _h_tv_app(self, slots, user_input) -> str:
        app = slots.get("app")
        tv = self._tv_for(slots, user_input)
        if not tv:
            return "I couldn't find a TV."
        remote = self._tv_remote(tv)
        spoken = next((k for k, v in self.slot_lists()["tv_app"].items() if v == app and "." not in k), app)
        if remote:
            await self._call("remote", "turn_on", {"entity_id": remote, "activity": app})
        else:                                                  # no remote: the TV's own source list
            st = self.hass.states.get(tv)
            source = next((s for s in (st.attributes.get("source_list") if st else None) or []
                           if s.lower() in (spoken.lower(), str(app).lower())), None)
            if not source:
                return f"I can't open apps on the {self._friendly(tv).lower()}."
            await self._call("media_player", "select_source", {"entity_id": tv, "source": source})
        return f"Opening {spoken.title()} on the {self._friendly(tv).lower()}."

    # ------------------------------------------------------------ bed
    def _bed(self) -> dict:
        bed = dict(self.store.detected.get("bed") or {})
        section = self._section("bed")
        if section.get("bed_firmness") is not None:
            bed["firmness"] = section["bed_firmness"]
        if section.get("bed_presets") is not None:
            bed["presets"] = section["bed_presets"]
        bed["left_person"] = section.get("bed_left_person")
        bed["right_person"] = section.get("bed_right_person")
        return bed

    def _bed_preset_words(self) -> dict[str, str]:
        words = {}
        for eid in self._bed().get("presets") or []:
            st = self.hass.states.get(eid)
            for opt in (st.attributes.get("options") if st else None) or []:
                words[opt.lower()] = opt
        return words

    def _who(self, slots, user_input) -> tuple[str | None, str]:
        """(person entity or None for the whole bed, problem)."""
        if slots.get("who") == "all":
            return None, ""
        if slots.get("person"):
            person, problem = self.resolve(slots["person"])
            return person, problem
        person = self.speaker_person(user_input)
        return (person, "") if person else (None, "I don't know whose side that is. Say the person's name.")

    def _side(self, person: str | None) -> str | None:
        bed = self._bed()
        if person and person == bed.get("left_person"):
            return "left"
        if person and person == bed.get("right_person"):
            return "right"
        return None

    def _side_entities(self, kind: str, person: str | None) -> list[str]:
        ents = list(self._bed().get(kind) or [])
        if person is None:
            return ents
        first = self.person_name(person)
        named = [e for e in ents if sleeper_matches(self._friendly(e), first)]
        if named:
            return named
        side = self._side(person)
        sided = [e for e in ents if side and side_of(self._friendly(e)) == side]
        if sided:
            return sided
        return [e for e in ents if side_of(self._friendly(e)) is None]      # bed-wide controls

    async def _bed_preset(self, preset: str, person: str | None) -> bool:
        done = False
        for eid in self._side_entities("presets", person):
            st = self.hass.states.get(eid)
            options = (st.attributes.get("options") if st else None) or []
            match = next((o for o in options if o.lower() == preset.lower()), None)
            if match:
                await self._call("select", "select_option", {"entity_id": eid, "option": match})
                done = True
        return done

    async def _h_bed_preset(self, slots, user_input) -> str:
        person, problem = self._who(slots, user_input) if slots.get("who") or slots.get("person") else (None, "")
        if problem:
            return problem
        if not await self._bed_preset(slots.get("preset", ""), person):
            return "I couldn't set the bed to that."
        whose = f"{self.person_name(person)}'s side" if person else "the bed"
        return f"Okay, {whose} is set to {slots.get('preset', '').lower()}."

    async def _bed_move(self, slots, user_input, raise_: bool) -> str:
        person, problem = self._who(slots, user_input)
        if problem:
            return problem
        presets = self._bed_preset_words()
        wanted = ("read", "watch tv", "relax", "incline", "lounge") if raise_ else ("flat",)
        name = next((presets[w] for w in wanted if w in presets), None)
        if name and await self._bed_preset(name, person):
            pass
        else:
            acts = [e for e in self._side_entities("actuators", person) if "head" in e or not raise_]
            if not acts:
                return "I couldn't find a way to move the bed."
            for eid in acts:
                st = self.hass.states.get(eid)
                top = float(st.attributes.get("max", 100)) if st else 100.0
                await self._call("number", "set_value", {"entity_id": eid, "value": round(top * 0.45) if raise_ else 0})
        whose = f"{self.person_name(person)}'s side" if person else "the bed"
        return f"Okay, {'raising' if raise_ else 'flattening'} {whose}."

    async def _h_bed_raise(self, slots, user_input) -> str:
        return await self._bed_move(slots, user_input, True)

    async def _h_bed_flatten(self, slots, user_input) -> str:
        return await self._bed_move(slots, user_input, False)

    async def _h_bed_number(self, slots, user_input) -> str:
        person, problem = self._who(slots, user_input)
        if problem:
            return problem
        ents = self._side_entities("firmness", person)
        if len(ents) != 1:
            return "I couldn't tell which sleep number is yours. Set the bed sides in the integration settings."
        st = self.hass.states.get(ents[0])
        a = st.attributes if st else {}
        value = round_to_step(float(slots.get("number", 0)), float(a.get("step", 5)), float(a.get("min", 5)),
                              float(a.get("max", 100)))
        await self._call("number", "set_value", {"entity_id": ents[0], "value": value})
        return f"Okay, {self.person_name(person)}'s sleep number is set to {value:g}."

    async def _h_bed_query(self, slots, user_input) -> str:
        if slots.get("who") == "all":
            ents = self._bed().get("firmness") or []
        else:
            person, problem = self._who(slots, user_input)
            if problem:
                return problem
            ents = self._side_entities("firmness", person)
        said = []
        for eid in ents:
            st = self.hass.states.get(eid)
            if not st or st.state in ("unknown", "unavailable"):
                continue
            name = re.sub(r"(?i)\b(sleep ?number|firmness|bed)\b", "", self._friendly(eid)).strip() or "the bed"
            said.append(f"{name} is at {float(st.state):g}")
        return ("; ".join(said) + ".") if said else "I couldn't read the sleep numbers."

    async def _h_bed_sleep(self, slots, user_input) -> str:
        person, problem = self._who(slots, user_input)
        if problem:
            return problem
        first = self.person_name(person)
        for eid in self._bed().get("sensors") or []:
            if re.search(r"sleep.?score|sleep.?quality|sleepiq", eid) and sleeper_matches(self._friendly(eid), first):
                st = self.hass.states.get(eid)
                if st and st.state not in ("unknown", "unavailable"):
                    return f"{first}'s sleep score was {st.state}."
        return "I don't have sleep data from the bed."

    # ------------------------------------------------------------ health
    def _battery_entities(self, include_personal: bool = True) -> list[str]:
        out = []
        for b in self.store.detected.get("batteries") or []:
            if include_personal or not b.get("personal"):
                out.append(b["entity_id"])
        return out

    def _battery_levels(self, include_personal: bool) -> list[tuple[str, int]]:
        levels = []
        for eid in self._battery_entities(include_personal):
            st = self.hass.states.get(eid)
            try:
                levels.append((battery_name(st.name) or st.name, round(float(st.state))))
            except (AttributeError, TypeError, ValueError):
                continue
        return levels

    async def _h_health_report(self, slots, user_input) -> str:
        from .discovery import async_detect  # noqa: PLC0415
        detected = async_detect(self.hass, dict(self.entry.options))
        devs = dr.async_get(self.hass)
        names = {}
        for key in detected.get("unavailable") or {}:
            dev = devs.async_get(key)
            names[key] = (dev.name_by_user or dev.name) if dev else self._friendly(key)
        threshold = int(self.setting("health", "battery_threshold"))
        low = [x for x in self._battery_levels(False) if x[1] < threshold]
        vac = [self._friendly(s.entity_id).lower() for s in self.hass.states.async_all("vacuum") if s.state == "error"]
        updates = sum(1 for s in self.hass.states.async_all("update") if s.state == "on")
        return say_health(detected.get("unavailable") or {}, names, low, vac, updates)

    async def _h_battery_all(self, slots, user_input) -> str:
        return say_batteries(self._battery_levels(False), int(self.setting("health", "battery_threshold")), False)

    async def _h_battery_low(self, slots, user_input) -> str:
        return say_batteries(self._battery_levels(False), int(self.setting("health", "battery_threshold")), True)

    async def _h_battery_one(self, slots, user_input) -> str:
        st = self.hass.states.get(slots.get("thing", ""))
        if not st:
            return "I couldn't find that battery."
        try:
            return f"The {battery_name(st.name) or st.name} battery is at {round(float(st.state))} percent."
        except ValueError:
            return f"I can't read the {battery_name(st.name)} battery right now."

    async def _h_battery_phone(self, slots, user_input) -> str:
        person = self.speaker_person(user_input)
        devices = {p["device_id"] for p in self.store.detected.get("phones") or [] if p.get("person") == person}
        ents = er.async_get(self.hass)
        for eid in self._battery_entities(True):
            reg = ents.async_get(eid)
            if reg and reg.device_id in devices and (st := self.hass.states.get(eid)):
                try:
                    return f"Your phone's battery is at {round(float(st.state))} percent."
                except ValueError:
                    break
        return "I couldn't find your phone's battery."

    # ------------------------------------------------------------ guest mode
    async def set_guest(self, on: bool) -> None:
        modes = self._modes()
        if modes.get("guest") == on:
            return
        protected = list(self._section("guest_mode").get("protected") or [])
        if on:
            # Remember exactly what was there (an explicit setting, or the default), saved with the
            # integration so a restart during guest mode still puts it back.
            saved = {}
            for eid in protected:
                settings = async_get_entity_settings(self.hass, eid).get("conversation", {})
                default = async_get_should_expose_default(self.hass, eid)
                saved[eid] = exposure_record(dict(settings), default)
                async_expose_entity(self.hass, "conversation", eid, False)   # hidden from Assist
            modes["guest_saved"] = saved
        else:
            ents = er.async_get(self.hass)
            for eid, record in (modes.get("guest_saved") or {}).items():
                if not isinstance(record, dict):                  # saved by an older version
                    record = {"explicit": True, "value": bool(record)}
                action, value = restore_action(record)
                entry = ents.async_get(eid)
                if action == "clear" and entry is not None:       # back on the default: drop our setting
                    opts = {k: v for k, v in (entry.options.get("conversation") or {}).items()
                            if k != "should_expose"}
                    ents.async_update_entity_options(eid, "conversation", opts)
                else:
                    async_expose_entity(self.hass, "conversation", eid, bool(value))
            modes["guest_saved"] = {}
        modes["guest"] = on
        self.store.changed()

    async def _h_guest_on(self, slots, user_input) -> str:
        await self.set_guest(True)
        return "Guest mode is on. Calendars, notes, reminders and sleep data are private until you turn it off."

    async def _h_guest_off(self, slots, user_input) -> str:
        await self.set_guest(False)
        return "Guest mode is off."

    async def _h_guest_query(self, slots, user_input) -> str:
        return f"Guest mode is {'on' if self.guest_on() else 'off'}."

    # ------------------------------------------------------------ night mode
    def _night_targets(self) -> list[dict]:
        chosen = set(self.satellites())
        return [s for s in self.store.detected.get("satellites") or [] if not chosen or s["entity_id"] in chosen]

    async def set_night(self, on: bool) -> None:
        modes = self._modes()
        if modes.get("night") == on:
            return
        if on:
            saved: dict[str, Any] = {}
            volume = float(self.setting("night_mode", "night_volume"))
            led_pct = int(self.setting("night_mode", "night_led"))
            for s in self._night_targets():
                player, led = s.get("media_player"), s.get("led")
                if player and (st := self.hass.states.get(player)):
                    saved[player] = {"volume": st.attributes.get("volume_level")}
                    await self._call("media_player", "volume_set", {"entity_id": player, "volume_level": volume})
                if led and (st := self.hass.states.get(led)):
                    saved[led] = {"state": st.state, "brightness": st.attributes.get("brightness")}
                    if st.state == "on":
                        await self._call("light", "turn_on", {"entity_id": led, "brightness_pct": led_pct})
            modes["night_saved"] = saved
        else:
            for eid, old in (modes.get("night_saved") or {}).items():
                if eid.startswith("media_player.") and old.get("volume") is not None:
                    await self._call("media_player", "volume_set", {"entity_id": eid, "volume_level": old["volume"]})
                elif eid.startswith("light."):
                    if old.get("state") == "on" and old.get("brightness"):
                        await self._call("light", "turn_on", {"entity_id": eid, "brightness": old["brightness"]})
                    elif old.get("state") == "off":
                        await self._call("light", "turn_off", {"entity_id": eid})
            modes["night_saved"] = {}
        modes["night"] = on
        self.store.changed()

    def _parse_time(self, value: str) -> dt.time:
        try:
            return dt.time.fromisoformat(str(value))
        except ValueError:
            return dt.time(22, 0)

    def start_night_schedule(self) -> None:
        if not self.feature_on("night_mode"):
            return
        start = self._parse_time(self.setting("night_mode", "night_start"))
        end = self._parse_time(self.setting("night_mode", "night_end"))

        @callback
        def _start(_now) -> None:
            self.hass.async_create_task(self.set_night(True))

        @callback
        def _end(_now) -> None:
            self.hass.async_create_task(self.set_night(False))

        self._unsubs.append(async_track_time_change(self.hass, _start, start.hour, start.minute, start.second))
        self._unsubs.append(async_track_time_change(self.hass, _end, end.hour, end.minute, end.second))
        if in_window(dt_util.now().time(), start, end) and not self.night_on():
            self.hass.async_create_task(self.set_night(True))

    async def _h_night_on(self, slots, user_input) -> str:
        await self.set_night(True)
        return "Night mode is on."

    async def _h_night_off(self, slots, user_input) -> str:
        await self.set_night(False)
        return "Night mode is off."

    async def _h_night_query(self, slots, user_input) -> str:
        return f"Night mode is {'on' if self.night_on() else 'off'}."

    # ------------------------------------------------------------ broadcast and help
    async def _h_broadcast_message(self, slots, user_input) -> str:
        message = (slots.get("message") or "").strip(" ,.")
        if not message:
            return "What should I say?"
        me = self.satellite_for(user_input) if user_input.device_id or getattr(user_input, "satellite_id", None) \
            else None
        sats = [s for s in self.satellites() or [st.entity_id for st in self.hass.states.async_all("assist_satellite")]
                if s != me]
        section = self._section("broadcast")
        players = list(section.get("broadcast_players") or [])
        if not sats and not players:
            return "There are no other speakers to broadcast to."
        if sats:
            await self.announce(sats, message)
        tts = section.get("broadcast_tts")
        if players and tts:
            await self._call("tts", "speak", {"entity_id": tts, "media_player_entity_id": players, "message": message})
        return "Okay, I told everyone."

    def enabled_topics(self) -> list[str]:
        base = ["local", "reminders", "alarms", "timers", "notes", "messages"]
        if self.entry.data.get("api_key"):
            base.insert(0, "search")
        return base + [s for s in FEATURE_SECTIONS if self.feature_on(s)]

    async def _h_help(self, slots, user_input) -> str:
        return say_help(self.enabled_topics(), slots.get("topic"))

    # ------------------------------------------------------------ guard
    def guest_blocks(self, intent_name: str) -> bool:
        return self.guest_on() and intent_name in GUEST_BLOCKED
