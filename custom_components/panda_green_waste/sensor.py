"""Sensor platform for Panda Green Waste."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, timedelta
from typing import Callable

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .client import PandaCalendarEntry, PandaPortalData
from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import PandaGreenWasteCoordinator


@dataclass(frozen=True, kw_only=True)
class PandaSensorDescription(SensorEntityDescription):
    """Describe a Panda sensor."""

    value_fn: Callable[[PandaPortalData], str | int | None]
    attributes_fn: Callable[[PandaPortalData], dict] | None = None


def _friendly_subject(subject: str) -> str:
    return (
        subject.replace("RTSC4413266", "MSW Municipal Mixed")
        .replace("RTSC4413265", "Mixed Packaging")
        .strip()
    )


def _local_date(entry: PandaCalendarEntry):
    return dt_util.as_local(entry.start).date()


def _today_entries(data: PandaPortalData) -> list[PandaCalendarEntry]:
    today = dt_util.now().date()
    return [entry for entry in data.calendar_entries if _local_date(entry) == today]


def _next_10_day_entries(data: PandaPortalData) -> list[PandaCalendarEntry]:
    today = dt_util.now().date()
    cutoff = today + timedelta(days=9)
    return [entry for entry in data.calendar_entries if today <= _local_date(entry) <= cutoff]


def _grouped_10_day_summary(data: PandaPortalData) -> str:
    entries = _next_10_day_entries(data)
    if not entries:
        return "No Panda calendar entries in the next 10 days."

    today = dt_util.now().date()
    chunks: list[str] = []
    for offset in range(10):
        day = today + timedelta(days=offset)
        route_visits: list[str] = []
        lift_events: list[str] = []
        for entry in entries:
            if _local_date(entry) != day:
                continue
            friendly = _friendly_subject(entry.subject)
            if friendly.startswith("Route Visit:"):
                route_visits.append(friendly.replace("Route Visit:", "", 1).strip())
            elif friendly.startswith("Lift Event:"):
                lift_events.append(friendly.replace("Lift Event:", "", 1).strip())

        if route_visits or lift_events:
            lines = [day.strftime("%d/%m/%Y")]
            if route_visits:
                lines.append(f"Route Visit: {', '.join(route_visits)}")
            if lift_events:
                lines.append(f"Lift Event: {', '.join(lift_events)}")
            chunks.append("\n".join(lines))

    return "\n\n".join(chunks) if chunks else "No Panda calendar entries in the next 10 days."


def _serialize_entry(entry: PandaCalendarEntry) -> dict:
    return {
        "subject": entry.subject,
        "friendly_subject": _friendly_subject(entry.subject),
        "start": entry.start.astimezone(UTC).isoformat(),
        "end": entry.end.astimezone(UTC).isoformat() if entry.end else None,
        "status": entry.status,
        "date": _local_date(entry).strftime("%d/%m/%Y"),
        "raw": entry.raw,
    }


SENSORS: tuple[PandaSensorDescription, ...] = (
    PandaSensorDescription(
        key="next_collection",
        translation_key="next_collection",
        icon="mdi:trash-can-outline",
        value_fn=lambda data: data.calendar_entries[0].start.astimezone(UTC).isoformat()
        if data.calendar_entries
        else None,
        attributes_fn=lambda data: {
            "subject": data.calendar_entries[0].subject if data.calendar_entries else None,
            "status": data.calendar_entries[0].status if data.calendar_entries else None,
            "entries": [
                {
                    "subject": entry.subject,
                    "start": entry.start.astimezone(UTC).isoformat(),
                    "status": entry.status,
                }
                for entry in data.calendar_entries
            ],
        },
    ),
    PandaSensorDescription(
        key="upcoming_services",
        translation_key="upcoming_services",
        icon="mdi:calendar-clock",
        value_fn=lambda data: len(data.calendar_entries),
        attributes_fn=lambda data: {
            "entries": [_serialize_entry(entry) for entry in data.calendar_entries],
            "available_services": data.available_services,
        },
    ),
    PandaSensorDescription(
        key="today_services",
        translation_key="today_services",
        icon="mdi:calendar-today",
        value_fn=lambda data: len(_today_entries(data)),
        attributes_fn=lambda data: {
            "entries": [_serialize_entry(entry) for entry in _today_entries(data)],
            "subjects": [_friendly_subject(entry.subject) for entry in _today_entries(data)],
            "statuses": [entry.status for entry in _today_entries(data) if entry.status],
            "count": len(_today_entries(data)),
        },
    ),
    PandaSensorDescription(
        key="calendar_next_10_days",
        translation_key="calendar_next_10_days",
        icon="mdi:calendar-range",
        value_fn=lambda data: len(_next_10_day_entries(data)),
        attributes_fn=lambda data: {
            "summary": _grouped_10_day_summary(data),
            "entries": [_serialize_entry(entry) for entry in _next_10_day_entries(data)],
        },
    ),
    PandaSensorDescription(
        key="service_summary_field_count",
        translation_key="service_summary_field_count",
        icon="mdi:file-document-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: len(data.service_summary_fields),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    async_add_entities(PandaSensor(coordinator, entry, description) for description in SENSORS)


class PandaSensor(SensorEntity):
    """Representation of a Panda sensor."""

    entity_description: PandaSensorDescription

    def __init__(
        self,
        coordinator: PandaGreenWasteCoordinator,
        entry: ConfigEntry,
        description: PandaSensorDescription,
    ) -> None:
        self.coordinator = coordinator
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_name = f"{entry.title} {description.key.replace('_', ' ')}"

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.coordinator.async_add_listener(self.async_write_ha_state))

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def native_value(self):
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self):
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.coordinator.data)
