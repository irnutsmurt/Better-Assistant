"""What an alarm can wake you with: the choices shown in a drop-down (the app and the options page), so
nobody has to type a name and get it wrong. Saying it still works ("wake me up to Taylor Swift at 7").

Values (stored in the wake-up music setting, and per alarm):
  ""                      the alarm sound (the speaker's own alarm on a Voice PE, else the bundled tone). The
                          only choice a Voice PE stops on a plain "stop": its firmware listens for that word
                          only while its own alarm rings. Music needs the wake word first, or the button.
  "last"                  whatever played last on that speaker (Music Assistant resumes it)
  "ma:<type>:<uri>|<name>" an item in your Music Assistant library: a playlist, a favourite artist (as a
                          radio of music like them) or a favourite radio station
  anything else           a request said by voice ("jazz"), searched when the alarm rings"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

LAST = "last"
MA = "ma:"
LIBRARY = [("playlist", False), ("artist", True), ("radio", True)]     # (media type, favourites only)


def ma_value(media_type: str, uri: str, name: str) -> str:
    return f"{MA}{media_type}:{uri}|{name}"


def parse_ma(value: str | None) -> tuple[str, str, str] | None:
    """'ma:playlist:library://playlist/9|Liked Music' -> ('playlist', 'library://playlist/9', 'Liked Music')."""
    if not value or not value.startswith(MA):
        return None
    media_type, _, rest = value[len(MA):].partition(":")
    uri, _, name = rest.rpartition("|") if "|" in rest else (rest, "", "")
    return (media_type, uri, name) if media_type and uri else None


def describe(value: str | None) -> str:
    """How a reply says it: "the alarm sound", "your Liked Music playlist", "music like Queen"."""
    if not value:
        return "the alarm sound"
    if value == LAST:
        return "whatever played last"
    ma = parse_ma(value)
    if ma:
        media_type, _uri, name = ma
        return {"playlist": f"your {name} playlist", "artist": f"music like {name}"}.get(media_type, name)
    return value


def label(value: str | None) -> str:
    """How the drop-down shows it."""
    if not value:
        return "Alarm sound (just say \"stop\")"
    if value == LAST:
        return "Whatever played last"
    ma = parse_ma(value)
    if ma:
        media_type, _uri, name = ma
        return {"playlist": f"Playlist: {name}", "artist": f"Music like {name}", "radio": f"Radio: {name}"}.get(
            media_type, name)
    return f"{value} (asked for by voice)"


async def async_choices(hass: HomeAssistant, current: str | None = None) -> list[dict[str, str]]:
    """[{value, label}] for a drop-down: the alarm sound, then (with Music Assistant) whatever played last,
    your playlists, favourite artists and favourite radio. The current value is always included."""
    values: list[str] = [""]
    entry = next((e for e in hass.config_entries.async_entries("music_assistant")
                  if e.state is ConfigEntryState.LOADED), None)
    if entry and hass.services.has_service("music_assistant", "get_library"):
        values.append(LAST)
        for media_type, favourite in LIBRARY:
            data: dict[str, Any] = {"config_entry_id": entry.entry_id, "media_type": media_type, "order_by": "name"}
            if favourite:
                data["favorite"] = True
            try:
                res = await hass.services.async_call("music_assistant", "get_library", data, blocking=True,
                                                     return_response=True)
            except Exception:  # noqa: BLE001 - a library that can't be read just isn't offered
                _LOGGER.debug("Couldn't read the Music Assistant %s library", media_type, exc_info=True)
                continue
            for item in (res or {}).get("items") or []:
                if item.get("uri") and item.get("name"):
                    values.append(ma_value(media_type, item["uri"], item["name"]))
    if current and current not in values:
        values.append(current)
    return [{"value": v, "label": label(v)} for v in values]
