"""Sensor platform for Panda Green Waste."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import PandaPortalData
from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import PandaGreenWasteCoordinator


@dataclass(frozen=True, kw_only=True)
class PandaSensorDescription(SensorEntityDescription):
    """Describe a Panda sensor."""

    value_fn: Callable[[PandaPortalData], str | int | None]
    attributes_fn: Callable[[PandaPortalData], dict] | None = None


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
            "entries": [
                {
                    "subject": entry.subject,
                    "start": entry.start.astimezone(UTC).isoformat(),
                    "status": entry.status,
                }
                for entry in data.calendar_entries
            ],
            "available_services": data.available_services,
        },
    ),
    PandaSensorDescription(
        key="today_services",
        translation_key="today_services",
        icon="mdi:calendar-today",
        value_fn=lambda data: len(data.today_entries()),
        attributes_fn=lambda data: {
            "entries": [
                {
                    "subject": entry.subject,
                    "start": entry.start.astimezone(UTC).isoformat(),
                    "end": entry.end.astimezone(UTC).isoformat() if entry.end else None,
                    "status": entry.status,
                    "raw": entry.raw,
                }
                for entry in data.today_entries()
            ],
            "subjects": [entry.subject for entry in data.today_entries()],
            "statuses": [entry.status for entry in data.today_entries() if entry.status],
            "count": len(data.today_entries()),
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
