"""Constants for the Better Assistant integration."""
from __future__ import annotations

DOMAIN = "better_assistant"
TITLE = "Better Assistant"

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
OPT_ALARM_SPEAKER = "alarm_speaker"        # None = the speaker asked from, "all", or a satellite entity id
OPT_SNOOZE_ENABLED = "snooze_enabled"      # False: no snoozing at all
OPT_SNOOZE_LIMIT = "snooze_limit"          # 1-10 snoozes per alarm, or None for unlimited

DEFAULTS = {
    OPT_WEB_SEARCH: True,
    OPT_MONTHLY_CAP: 300,
    OPT_COUNTRY: "us",
    OPT_SPEAK_SOURCE: True,
    OPT_QUESTION_GUARD: True,
    OPT_COMPOUND: True,
    OPT_MAX_PARTS: 4,
    OPT_SNOOZE: 5,
    OPT_SNOOZE_ENABLED: True,
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
            "bed_presets": ("bed.presets", "select", True),
            "bed_left_person": ("bed.left_person", "person", False),
            "bed_right_person": ("bed.right_person", "person", False)},
    "rooms_lights": {"lights": ("lights", ["light", "switch"], True)},
    "health": {},
    "guest_mode": {"protected": ("protected", ["lock", "cover"], True)},
    "night_mode": {},
    "broadcast": {"broadcast_players": ("broadcast_players", "media_player", True),
                  "broadcast_tts": ("tts_engine", "tts", False)},
}
SETTINGS_SECTIONS = ["web_search", "behaviour", "alarms"]
PLACEHOLDER_SECTIONS: list[str] = []

# Features with an on/off switch on their settings page (all on by default).
FEATURE_SECTIONS = ["music", "calendar", "rooms_lights", "thermostat", "cameras_outside", "tv", "bed",
                    "health", "guest_mode", "night_mode", "broadcast"]
OPT_SECURITY = "security"            # options[OPT_SECURITY] = {passphrase, require_doors, require_guest, owner}
OPT_FEATURES = "features"            # options[OPT_FEATURES][section] = bool
FEATURE_DEFAULT_OFF = {"night_mode"}  # opt-in: don't change anyone's speakers on the first night
OPT_SETTINGS = "settings"            # options[OPT_SETTINGS][section][key] = value

# Extra (non-device) settings per section: key -> (kind, default, extra config).
EXTRA_FIELDS: dict[str, dict[str, tuple[str, object, dict]]] = {
    "health": {"battery_threshold": ("number", 20, {"min": 5, "max": 50, "unit": "%"})},
    "night_mode": {"night_start": ("time", "22:00:00", {}), "night_end": ("time", "07:00:00", {}),
                   "night_volume": ("number", 0.2, {"min": 0.0, "max": 1.0, "step": 0.05}),
                   "night_led": ("number", 10, {"min": 0, "max": 100, "unit": "%"})},
    "rooms_lights": {"include_fans": ("bool", True, {}),
                     "dim_step": ("number", 20, {"min": 5, "max": 50, "unit": "%"}),
                     "kelvin_step": ("number", 500, {"min": 100, "max": 2000, "unit": "K"})},
    "thermostat": {"degree_step": ("number", 2, {"min": 1, "max": 5})},
}

# The integration's own to-do lists: key -> name.
LISTS = {"reminders": "Reminders", "notes": "Notes", "messages": "Messages"}

ALARM_URL = "/better_assistant/alarm.mp3"
RING_MINUTES = 10
