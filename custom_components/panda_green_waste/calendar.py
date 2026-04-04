"""Calendar platform for Panda Green Waste."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import PandaGreenWasteCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    async_add_entities([PandaCalendarEntity(coordinator, entry)])


class PandaCalendarEntity(CalendarEntity):
    """Calendar entity backed by Panda portal entries."""

    def __init__(self, coordinator: PandaGreenWasteCoordinator, entry: ConfigEntry) -> None:
        self.coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_calendar"
        self._attr_name = f"{entry.title} calendar"

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.coordinator.async_add_listener(self.async_write_ha_state))

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def event(self) -> CalendarEvent | None:
        entries = self.coordinator.data.calendar_entries
        if not entries:
            return None
        entry = entries[0]
        return CalendarEvent(
            summary=entry.subject,
            start=entry.start,
            end=entry.end or entry.start,
            description=entry.status or "",
        )

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        events: list[CalendarEvent] = []
        for entry in self.coordinator.data.calendar_entries:
            if start_date <= entry.start <= end_date:
                events.append(
                    CalendarEvent(
                        summary=entry.subject,
                        start=entry.start,
                        end=entry.end or entry.start,
                        description=entry.status or "",
                    )
                )
        return events
