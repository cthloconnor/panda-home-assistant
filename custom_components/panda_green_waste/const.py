"""Constants for the Panda Green Waste integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "panda_green_waste"

CONF_PASSWORD = "password"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_SITE_ID = "site_id"
CONF_SITE_NAME = "site_name"
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
CREATE_SERVICE_JOBS_PATH = "/umbraco/Surface/ServiceSummary/CreateServiceJobs"
SERVICE_JOB_DETAILS_PATH = "/service-summary/service-job-details"
PRODUCTS_PATH = "/products"
LOGIN_PATH = "/umbraco/Surface/Login/CustomerLogin"
UPDATE_DEFAULT_SITE_PATH = "/umbraco/Surface/Login/UpdateDefaultCustomerSite"
CALENDAR_EVENTS_PATH = "/umbraco/Surface/Calender/CalendarEventsResult"

ENTRY_LIMIT = 25

DEFAULT_SITE_ID = "6330"
DEFAULT_SITE_NAME = "BLARNEY VETERINARY CLINC"

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
