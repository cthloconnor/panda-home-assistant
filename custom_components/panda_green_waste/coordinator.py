"""Coordinator for Panda Green Waste data."""

from __future__ import annotations

from datetime import timedelta
import logging

from aiohttp import ClientError
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import PandaGreenWasteAuthError, PandaGreenWasteClient, PandaGreenWasteError, PandaPortalData
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class PandaGreenWasteCoordinator(DataUpdateCoordinator[PandaPortalData]):
    """Fetch and cache Panda service data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: PandaGreenWasteClient) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=_as_timedelta(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
        )
        self.entry = entry
        self.client = client

    async def _async_update_data(self) -> PandaPortalData:
        try:
            return await self.client.async_get_data()
        except PandaGreenWasteAuthError as err:
            raise UpdateFailed(f"Authentication failed: {err}") from err
        except (ClientError, PandaGreenWasteError, ValueError) as err:
            raise UpdateFailed(f"Error communicating with Panda portal: {err}") from err


def _as_timedelta(value: timedelta | int) -> timedelta:
    if isinstance(value, timedelta):
        return value
    return timedelta(seconds=value)
