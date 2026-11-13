"""Builds a registry snapshot for core.discovery and merges detected defaults with user overrides."""
from __future__ import annotations

from typing import Any

from homeassistant.const import ATTR_DEVICE_CLASS, ATTR_SUPPORTED_FEATURES, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er

from .const import DEVICE_SECTIONS, OPT_OVERRIDES
from .core.discovery import Device, Entity, Person, Snapshot, classify


@callback
def async_snapshot(hass: HomeAssistant) -> Snapshot:
    """Plain copy of the registries and states (runs in the event loop; no I/O)."""
    ents = er.async_get(hass)
    devs = dr.async_get(hass)
    snap = Snapshot()
    snap.areas = {a.id: a.name for a in ar.async_get(hass).async_list_areas()}

    mobile_users = {e.entry_id: e.data.get("user_id") for e in hass.config_entries.async_entries("mobile_app")}
    for d in devs.devices.values():
        user = next((mobile_users[c] for c in d.config_entries if c in mobile_users), None)
        snap.devices[d.id] = Device(id=d.id, area_id=d.area_id, name=d.name_by_user or d.name or "",
                                    model=d.model or "", manufacturer=d.manufacturer or "", user_id=user)

    seen = set()
    for entry in ents.entities.values():
        if entry.disabled_by:
            continue
        state = hass.states.get(entry.entity_id)
        attrs = state.attributes if state else {}
        snap.entities.append(Entity(
            entity_id=entry.entity_id, platform=entry.platform, device_id=entry.device_id,
            area_id=entry.area_id,
            device_class=entry.device_class or entry.original_device_class or attrs.get(ATTR_DEVICE_CLASS),
            supported_features=int(attrs.get(ATTR_SUPPORTED_FEATURES, entry.supported_features or 0) or 0),
            entity_category=entry.entity_category.value if entry.entity_category else None,
            name=(state.name if state else entry.name or entry.original_name or "") or "",
            available=not state or state.state != STATE_UNAVAILABLE))
        seen.add(entry.entity_id)
    for state in hass.states.async_all():                    # entities without a unique id
        if state.entity_id in seen:
            continue
        snap.entities.append(Entity(
            entity_id=state.entity_id, device_class=state.attributes.get(ATTR_DEVICE_CLASS),
            supported_features=int(state.attributes.get(ATTR_SUPPORTED_FEATURES, 0) or 0),
            name=state.name, available=state.state != STATE_UNAVAILABLE))

    for state in hass.states.async_all("person"):
        snap.people.append(Person(entity_id=state.entity_id, user_id=state.attributes.get("user_id"),
                                  device_trackers=list(state.attributes.get("device_trackers") or [])))
    snap.notify_services = [s for s in hass.services.async_services_for_domain("notify") if s.startswith("mobile_app_")]
    return snap


@callback
def async_detect(hass: HomeAssistant, options: dict[str, Any] | None = None) -> dict[str, Any]:
    """Detect devices; the user's chosen outdoor areas (if any) replace the area-name guess."""
    chosen = ((options or {}).get(OPT_OVERRIDES) or {}).get("cameras_outside", {}).get("outdoor_areas")
    return classify(async_snapshot(hass), chosen)


def detected_value(detected: dict[str, Any], path: str, multiple: bool) -> Any:
    """Entity id(s) under a dotted path of the detection result."""
    value: Any = detected
    for part in path.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    items = value if isinstance(value, list) else ([value] if value else [])
    ids = [i["entity_id"] if isinstance(i, dict) else i for i in items]
    ids = [i for i in ids if isinstance(i, str)]
    return ids if multiple else (ids[0] if ids else None)


def effective_section(options: dict[str, Any], detected: dict[str, Any], section: str) -> dict[str, Any]:
    """Detected defaults for a section with the user's overrides on top."""
    values = {f: detected_value(detected, path, multi) for f, (path, _d, multi) in DEVICE_SECTIONS[section].items()}
    values.update((options.get(OPT_OVERRIDES) or {}).get(section) or {})
    return values
