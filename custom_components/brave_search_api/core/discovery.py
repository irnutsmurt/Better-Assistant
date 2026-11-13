"""Automatic device detection: turns a plain snapshot of the Home Assistant registries into a
suggested setup (voice speakers, music players, TVs, lights per room, ...).

Classification uses domain, device_class, integration platform, supported_features, entity_category
and area. Names are never used to pick a specific device; the only text hints are generic words
("light", "lamp" for switches; "router", "coordinator" for Zigbee radio LEDs; outdoor area words).

Pure Python, no Home Assistant imports: the integration's `discovery.py` builds the Snapshot.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Feature bits (copied so this module needs no Home Assistant import).
CALENDAR_CREATE_EVENT = 1          # CalendarEntityFeature.CREATE_EVENT
MEDIA_SELECT_SOURCE = 2048         # MediaPlayerEntityFeature.SELECT_SOURCE

ACTIONABLE = {"light", "switch", "media_player", "climate", "lock", "cover", "fan", "camera", "vacuum",
              "assist_satellite", "remote", "valve", "humidifier", "water_heater", "siren"}
OUTSIDE_CLASSES = {"motion", "occupancy", "presence"}
LIGHTISH = re.compile(r"\b(light|lights|lamp|lamps|sconce|chandelier|lantern|bulb)\b", re.I)
RADIO_HW = re.compile(r"router|coordinator|dongle|repeater|extender", re.I)
# Plugs that power network gear are never part of a room.
NETWORK_GEAR = re.compile(r"\b(router|modem|mesh|access point|wi-?fi|network|nas|server|firewall|gateway|"
                          r"internet|ont|switch(?:es)? rack|rack|ups|poe)\b", re.I)
TV_MODEL = re.compile(r"chromecast|google tv|android tv|\btv\b", re.I)
CAST_GROUP_MODEL = re.compile(r"cast group", re.I)
PERSONAL_MODEL = re.compile(r"phone|watch|pixel|galaxy|ipad|tablet", re.I)
OUTDOOR_AREA = re.compile(r"\b(outside|outdoors?|yard|front|back|porch|patio|deck|driveway|garden|drive|"
                          r"street|lawn|side|exterior|gate|parking|carport)\b", re.I)


@dataclass
class Device:
    id: str
    area_id: str | None = None
    name: str = ""
    model: str = ""
    manufacturer: str = ""
    user_id: str | None = None           # mobile_app: the Home Assistant user the app is signed in as


@dataclass
class Entity:
    entity_id: str
    platform: str = ""
    device_id: str | None = None
    area_id: str | None = None           # the entity's own area (overrides the device's)
    device_class: str | None = None
    supported_features: int = 0
    entity_category: str | None = None
    name: str = ""
    available: bool = True

    @property
    def domain(self) -> str:
        return self.entity_id.split(".", 1)[0]


@dataclass
class Person:
    entity_id: str
    user_id: str | None = None
    device_trackers: list[str] = field(default_factory=list)


@dataclass
class Snapshot:
    entities: list[Entity] = field(default_factory=list)
    devices: dict[str, Device] = field(default_factory=dict)
    areas: dict[str, str] = field(default_factory=dict)        # area_id -> area name
    people: list[Person] = field(default_factory=list)
    notify_services: list[str] = field(default_factory=list)   # e.g. "mobile_app_<slug>"


def slugify(text: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", text.lower())).strip("_")


class _House:
    def __init__(self, snap: Snapshot) -> None:
        self.snap = snap
        self.outdoor: set[str] = set()
        self.by_device: dict[str, list[Entity]] = {}
        for e in snap.entities:
            if e.device_id:
                self.by_device.setdefault(e.device_id, []).append(e)

    def device(self, e: Entity) -> Device | None:
        return self.snap.devices.get(e.device_id or "")

    def area(self, e: Entity) -> str | None:
        if e.area_id:
            return e.area_id
        d = self.device(e)
        return d.area_id if d else None

    def model(self, e: Entity) -> str:
        d = self.device(e)
        return f"{d.manufacturer} {d.model}" if d else ""

    def of(self, domain: str, platform: str | None = None) -> list[Entity]:
        return [e for e in self.snap.entities if e.domain == domain and (platform is None or e.platform == platform)]

    def is_outdoor_area(self, area_id: str | None) -> bool:
        return bool(area_id and area_id in self.outdoor)


def _is_tv(h: _House, e: Entity) -> bool:
    return e.device_class == "tv" or bool(TV_MODEL.search(h.model(e)))


def _is_cast_group(h: _House, e: Entity) -> bool:
    return bool(CAST_GROUP_MODEL.search(h.model(e)))


def guess_outdoor_areas(areas: dict[str, str]) -> list[str]:
    """Areas whose name sounds outdoors (yard, porch, driveway...): the default the user can change."""
    return [a for a, name in areas.items() if OUTDOOR_AREA.search(name)]


def classify(snap: Snapshot, outdoor_areas: list[str] | None = None) -> dict[str, Any]:
    """Suggested setup as plain JSON-able data. `outdoor_areas` overrides the area-name guess."""
    h = _House(snap)
    h.outdoor = set(guess_outdoor_areas(snap.areas) if outdoor_areas is None else outdoor_areas)
    out: dict[str, Any] = {"outdoor_areas": sorted(h.outdoor)}

    # Voice speakers, and the Music Assistant player on the same device ("here").
    ma_players = h.of("media_player", "music_assistant")
    satellites = []
    satellite_devices = set()
    for s in h.of("assist_satellite"):
        here = next((p.entity_id for p in ma_players if s.device_id and p.device_id == s.device_id), None)
        own = h.by_device.get(s.device_id or "", [])
        here = here or next((p.entity_id for p in ma_players if h.area(p) and h.area(p) == h.area(s)), None)
        satellites.append({"entity_id": s.entity_id, "device_id": s.device_id, "area_id": h.area(s),
                           "here_player": here,
                           "media_player": next((e.entity_id for e in own if e.domain == "media_player"), None),
                           "led": next((e.entity_id for e in own if e.domain == "light"), None)})
        if s.device_id:
            satellite_devices.add(s.device_id)
    out["satellites"] = satellites
    out["music_players"] = [{"entity_id": p.entity_id, "area_id": h.area(p)} for p in ma_players]

    # Cast: groups for broadcast, TVs for showing cameras.
    cast = h.of("media_player", "cast")
    groups = [e.entity_id for e in cast if _is_cast_group(h, e)]
    speakers = [e.entity_id for e in cast if not _is_cast_group(h, e) and not _is_tv(h, e)]
    out["broadcast_targets"] = groups or speakers
    out["camera_cast_targets"] = [e.entity_id for e in cast if not _is_cast_group(h, e) and _is_tv(h, e)]

    out["thermostats"] = [{"entity_id": e.entity_id, "area_id": h.area(e)} for e in h.of("climate")]

    cals = h.of("calendar")
    out["calendars"] = [e.entity_id for e in cals]
    out["write_calendar"] = next((e.entity_id for e in cals if e.supported_features & CALENDAR_CREATE_EVENT), None)
    out["todo_lists"] = [e.entity_id for e in h.of("todo")]
    out["people"] = [p.entity_id for p in snap.people]
    out["cameras"] = [e.entity_id for e in h.of("camera")]
    out["phones"] = _phones(h)
    out["outside_sensors"] = _outside(h)

    # TVs, with a remote on the same device (apps) and whether inputs can be picked.
    tvs = []
    for e in h.of("media_player"):
        if e.device_class != "tv":
            continue
        remote = next((r.entity_id for r in h.by_device.get(e.device_id or "", []) if r.domain == "remote"), None)
        tvs.append({"entity_id": e.entity_id, "area_id": h.area(e), "remote": remote,
                    "inputs": bool(e.supported_features & MEDIA_SELECT_SOURCE)})
    out["tvs"] = tvs

    lights = _lights(h, satellite_devices)
    out["lights"] = lights
    rooms: dict[str, dict[str, list[str]]] = {}

    def room(area_id):
        return rooms.setdefault(area_id, {"lights": [], "fans": [], "media_players": []})

    for l in lights:
        if l["area_id"]:
            room(l["area_id"])["lights"].append(l["entity_id"])
    for e in h.of("fan"):
        dev = h.device(e)
        if e.entity_category or e.device_id in satellite_devices or \
                NETWORK_GEAR.search(f"{e.name} {dev.name if dev else ''}"):
            continue
        if h.area(e):
            room(h.area(e))["fans"].append(e.entity_id)
    for e in h.of("media_player"):
        a = h.area(e)
        if a and e.device_id not in satellite_devices and not _is_cast_group(h, e):
            room(a)["media_players"].append(e.entity_id)
    out["rooms"] = rooms

    out["batteries"] = [
        {"entity_id": e.entity_id, "personal": e.platform == "mobile_app" or bool(PERSONAL_MODEL.search(h.model(e)))}
        for e in h.of("sensor") if e.device_class == "battery"]

    unavailable: dict[str, list[str]] = {}
    for e in snap.entities:
        if not e.available and e.domain in ACTIONABLE and e.entity_category is None:
            unavailable.setdefault(e.device_id or e.entity_id, []).append(e.entity_id)
    out["unavailable"] = unavailable

    bed = [e for e in snap.entities if e.platform == "sleepiq"]
    firm = re.compile(r"firmness|sleep.?number", re.I)
    out["bed"] = {"firmness": [e.entity_id for e in bed if e.domain == "number" and firm.search(e.entity_id + " " + e.name)],
                  "actuators": [e.entity_id for e in bed if e.domain == "number" and not firm.search(e.entity_id + " " + e.name)],
                  "presets": [e.entity_id for e in bed if e.domain == "select"],
                  "presence": [e.entity_id for e in bed if e.domain == "binary_sensor"],
                  "sensors": [e.entity_id for e in bed if e.domain == "sensor"],
                  "left_person": None, "right_person": None}
    out["locks"] = [e.entity_id for e in h.of("lock")]
    out["garage_doors"] = [e.entity_id for e in h.of("cover") if e.device_class in ("garage", "gate")]
    out["protected"] = out["locks"] + out["garage_doors"]
    out["tts_engine"] = next((e.entity_id for e in h.of("tts")), None)
    out["broadcast_players"] = []
    out["vacuums"] = [e.entity_id for e in h.of("vacuum")]
    return out


def _phones(h: _House) -> list[dict[str, Any]]:
    services = set(h.snap.notify_services)
    owner_by_tracker = {t: p.entity_id for p in h.snap.people for t in p.device_trackers}
    person_by_user = {p.user_id: p.entity_id for p in h.snap.people if p.user_id}
    phones = []
    for dev in h.snap.devices.values():
        ents = h.by_device.get(dev.id, [])
        if not any(e.platform == "mobile_app" for e in ents):
            continue
        service = f"mobile_app_{slugify(dev.name)}"
        if service not in services:
            continue
        person = next((owner_by_tracker[e.entity_id] for e in ents
                       if e.domain == "device_tracker" and e.entity_id in owner_by_tracker), None)
        if person is None and dev.user_id:
            person = person_by_user.get(dev.user_id)       # same signed-in user as a person
        phones.append({"service": f"notify.{service}", "device_id": dev.id, "person": person})
    return phones


def _outside(h: _House) -> list[dict[str, Any]]:
    sensors = [e for e in h.of("binary_sensor") if e.device_class in OUTSIDE_CLASSES]
    frigate = [e for e in sensors if e.platform == "frigate" and e.entity_id.endswith("_person_occupancy")]
    chosen = frigate or sensors
    result = []
    for e in chosen:
        area = h.area(e)
        if area and not h.is_outdoor_area(area):
            continue                                       # indoor rooms are not "outside"
        if not area and e.platform != "frigate":
            continue                                       # unplaced generic motion: can't tell
        group = e.entity_id.split(".", 1)[1].removesuffix("_person_occupancy") if e.platform == "frigate" else area
        result.append({"entity_id": e.entity_id, "group": group, "area_id": area})
    return result


def _lights(h: _House, satellite_devices: set[str]) -> list[dict[str, Any]]:
    out = []
    for e in h.snap.entities:
        if e.domain not in ("light", "switch") or e.entity_category in ("config", "diagnostic"):
            continue
        dev = h.device(e)
        if dev and RADIO_HW.search(f"{dev.model} {dev.name}"):
            continue                                       # Zigbee router / coordinator status LEDs
        if e.device_id in satellite_devices:
            continue                                       # voice satellite LED rings
        names = f"{e.name} {dev.name if dev else ''}"
        if e.domain == "switch":
            if NETWORK_GEAR.search(names):
                continue                                   # never the router plug
            if not LIGHTISH.search(names) and e.device_class != "outlet":
                continue                                   # light-like switches and plugs only
        out.append({"entity_id": e.entity_id, "area_id": h.area(e)})
    return out
