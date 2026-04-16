"""Config flow for Panda Green Waste."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from aiohttp import ClientError
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .client import PandaGreenWasteAuthError, PandaGreenWasteClient
from .const import (
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_SITE_ID,
    CONF_SITE_NAME,
    CONF_USERNAME,
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SITE_ID,
    DEFAULT_SITE_NAME,
    DOMAIN,
)


async def _validate_input(hass, user_input: dict[str, Any]) -> dict[str, Any]:
    client = PandaGreenWasteClient(
        session=async_create_clientsession(hass),
        username=user_input[CONF_USERNAME],
        password=user_input[CONF_PASSWORD],
        site_id=user_input[CONF_SITE_ID],
        site_name=user_input[CONF_SITE_NAME],
    )
    await client.async_login()
    return {"title": user_input[CONF_NAME]}


class PandaGreenWasteConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Panda Green Waste."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_USERNAME].strip().casefold())
            self._abort_if_unique_id_configured()
            try:
                info = await _validate_input(self.hass, user_input)
            except PandaGreenWasteAuthError:
                errors["base"] = "invalid_auth"
            except ClientError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=info["title"],
                    data={
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_SITE_ID: user_input[CONF_SITE_ID],
                        CONF_SITE_NAME: user_input[CONF_SITE_NAME],
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Required(CONF_SITE_ID, default=DEFAULT_SITE_ID): str,
                vol.Required(CONF_SITE_NAME, default=DEFAULT_SITE_NAME): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return PandaGreenWasteOptionsFlow(config_entry)


class PandaGreenWasteOptionsFlow(config_entries.OptionsFlow):
    """Manage Panda Green Waste options."""

    def __init__(self, config_entry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            user_input[CONF_SCAN_INTERVAL] = timedelta(seconds=user_input[CONF_SCAN_INTERVAL])
            return self.async_create_entry(title="", data=user_input)

        scan_interval = self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        if isinstance(scan_interval, int):
            scan_interval = timedelta(seconds=scan_interval)

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=int(scan_interval.total_seconds()),
                ): vol.All(vol.Coerce(int), vol.Range(min=300, max=43200)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
