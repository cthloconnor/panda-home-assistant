"""The Panda Green Waste integration."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.components import persistent_notification

from .client import PandaGreenWasteClient
from .const import (
    DEFAULT_ACCESS_END_TIME,
    DEFAULT_ACCESS_START_TIME,
    CONF_PASSWORD,
    CONF_USERNAME,
    DATA_CLIENT,
    DATA_COORDINATOR,
    DOMAIN,
    NOTIFICATION_ID_PREFIX,
    PICKUP_TYPES,
    SERVICE_BOOK_PICKUP,
    SERVICE_REFRESH,
)
from .coordinator import PandaGreenWasteCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "calendar"]

BOOK_PICKUP_SCHEMA = vol.Schema(
    {
        vol.Required("pickup_type"): vol.In(PICKUP_TYPES),
        vol.Optional("access_start_time", default=DEFAULT_ACCESS_START_TIME): str,
        vol.Optional("access_end_time", default=DEFAULT_ACCESS_END_TIME): str,
        vol.Optional("payload", default={}): dict,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Panda Green Waste from a config entry."""
    session = async_create_clientsession(hass)
    client = PandaGreenWasteClient(
        session=session,
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
    )
    coordinator = PandaGreenWasteCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        DATA_CLIENT: client,
        DATA_COORDINATOR: coordinator,
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Reload a config entry."""
    await async_unload_entry(hass, entry)
    return await async_setup_entry(hass, entry)


def _async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_REFRESH):
        return

    async def async_refresh(call: ServiceCall) -> None:
        for data in hass.data.get(DOMAIN, {}).values():
            await data[DATA_COORDINATOR].async_request_refresh()

    async def async_book_pickup(call: ServiceCall) -> None:
        pickup_type = call.data["pickup_type"]
        access_start_time = call.data["access_start_time"]
        access_end_time = call.data["access_end_time"]
        payload = call.data.get("payload") or {}
        for entry_id, data in hass.data.get(DOMAIN, {}).items():
            result = await data[DATA_CLIENT].async_book_pickup(
                pickup_type=pickup_type,
                access_start_time=access_start_time,
                access_end_time=access_end_time,
                payload=payload,
            )
            _LOGGER.info("Panda pickup submission result: %s", result)
            await data[DATA_COORDINATOR].async_request_refresh()
            persistent_notification.async_create(
                hass,
                title="Panda booking prepared",
                message=(
                    f"Collection: {pickup_type}\n"
                    f"Access window: {access_start_time} to {access_end_time}\n"
                    f"Portal confirmation detected: {'Yes' if result['contains_confirmation'] else 'No'}"
                ),
                notification_id=f"{NOTIFICATION_ID_PREFIX}_{entry_id}",
            )

    hass.services.async_register(DOMAIN, SERVICE_REFRESH, async_refresh)
    hass.services.async_register(
        DOMAIN,
        SERVICE_BOOK_PICKUP,
        async_book_pickup,
        schema=BOOK_PICKUP_SCHEMA,
    )
