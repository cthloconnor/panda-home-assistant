"""Constants for the Panda Green Waste integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "panda_green_waste"

CONF_PASSWORD = "password"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_USERNAME = "username"

DEFAULT_NAME = "Panda Green Waste"
DEFAULT_SCAN_INTERVAL = timedelta(hours=6)

DATA_CLIENT = "client"
DATA_COORDINATOR = "coordinator"

SERVICE_BOOK_PICKUP = "book_pickup"
SERVICE_REFRESH = "refresh"
NOTIFICATION_ID_PREFIX = "panda_green_waste_last_booking"

CALENDAR_PATH = "/calendar"
SERVICE_SUMMARY_PATH = "/service-summary"
PRODUCTS_PATH = "/products"
LOGIN_PATH = "/umbraco/Surface/Login/CustomerLogin"

ENTRY_LIMIT = 25

PICKUP_TYPES = (
    "Mixed Packaging",
    "MSW Municipal Mixed",
    "Glass",
    "140L Food Wasre BIN",
)

DEFAULT_ACCESS_START_TIME = "09:00"
DEFAULT_ACCESS_END_TIME = "23:00"
DEFAULT_SERVICE_OPTION = "Call Out"
DEFAULT_ORDER_OPTION = "Order"
