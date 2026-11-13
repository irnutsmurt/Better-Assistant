"""Constants for the Brave Search API integration."""
from __future__ import annotations

DOMAIN = "brave_search_api"
TITLE = "Brave Search API"

CONF_API_KEY = "api_key"

# Options (entry.options). Section values the user changed live under OPT_OVERRIDES[section].
OPT_WEB_SEARCH = "web_search"
OPT_MONTHLY_CAP = "monthly_cap"
OPT_COUNTRY = "country"
OPT_SPEAK_SOURCE = "speak_source"
OPT_QUESTION_GUARD = "question_guard"
OPT_COMPOUND = "compound_commands"
OPT_MAX_PARTS = "max_compound_parts"
OPT_OVERRIDES = "overrides"
OPT_SNOOZE = "snooze_minutes"
OPT_SNOOZE_LIMIT = "snooze_limit"          # None = unlimited, 0 = no snoozing, n = n per alarm

DEFAULTS = {
    OPT_WEB_SEARCH: True,
    OPT_MONTHLY_CAP: 300,
    OPT_COUNTRY: "us",
    OPT_SPEAK_SOURCE: True,
    OPT_QUESTION_GUARD: True,
    OPT_COMPOUND: True,
    OPT_MAX_PARTS: 4,
    OPT_SNOOZE: 5,
    OPT_SNOOZE_LIMIT: None,
}

STORAGE_VERSION = 1
HISTORY_SIZE = 5
HA_AGENT_ID = "conversation.home_assistant"

AREA = "area"  # pseudo-domain: an area picker instead of an entity picker

# Device sections shown pre-filled from detection. The user's edits are stored as overrides.
DEVICE_SECTIONS: dict[str, dict[str, tuple[str, str, bool]]] = {
    # section -> field -> (detected key, entity domain, multiple)
    "voice_speakers": {"satellites": ("satellites", "assist_satellite", True)},
    "music": {"music_players": ("music_players", "media_player", True),
              "broadcast_targets": ("broadcast_targets", "media_player", True)},
    "calendar": {"calendars": ("calendars", "calendar", True),
                 "write_calendar": ("write_calendar", "calendar", False)},
    "reminders_notes": {"todo_lists": ("todo_lists", "todo", True),
                        "people": ("people", "person", True)},
    "cameras_outside": {"cameras": ("cameras", "camera", True),
                        "camera_cast_targets": ("camera_cast_targets", "media_player", True),
                        "outside_sensors": ("outside_sensors", "binary_sensor", True),
                        "outdoor_areas": ("outdoor_areas", AREA, True)},
    "thermostat": {"thermostats": ("thermostats", "climate", True)},
    "tv": {"tvs": ("tvs", "media_player", True)},
    "bed": {"bed_firmness": ("bed.firmness", "number", True),
            "bed_presets": ("bed.presets", "select", True)},
    "rooms_lights": {"lights": ("lights", ["light", "switch"], True)},
}
SETTINGS_SECTIONS = ["web_search", "behaviour", "alarms"]
PLACEHOLDER_SECTIONS = ["night_mode", "guest_mode"]

# The integration's own to-do lists: key -> name.
LISTS = {"reminders": "Reminders", "notes": "Notes", "messages": "Messages"}

ALARM_URL = "/brave_search_api/alarm.mp3"
RING_MINUTES = 10
