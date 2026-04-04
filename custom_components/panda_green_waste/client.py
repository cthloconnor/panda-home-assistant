"""Client for the Panda Green Waste portal."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from html import unescape
from html.parser import HTMLParser
import logging
import re
from typing import Any
from urllib.parse import urljoin

from aiohttp import ClientResponseError, ClientSession

from .const import (
    CALENDAR_PATH,
    DEFAULT_ACCESS_END_TIME,
    DEFAULT_ACCESS_START_TIME,
    DEFAULT_ORDER_OPTION,
    DEFAULT_SERVICE_OPTION,
    ENTRY_LIMIT,
    LOGIN_PATH,
    PRODUCTS_PATH,
    SERVICE_SUMMARY_PATH,
)

_LOGGER = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<script\b[^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL)
_TABLE_RE = re.compile(
    r'<table\b[^>]*id="(?P<id>[^"]+)"[^>]*>(?P<body>.*?)</table>',
    re.IGNORECASE | re.DOTALL,
)
_ROW_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_CELL_RE = re.compile(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", re.IGNORECASE | re.DOTALL)
_WHITESPACE_RE = re.compile(r"\s+")

_DATE_FORMATS = (
    "%d/%m/%Y",
    "%d/%m/%Y %H:%M",
    "%Y-%m-%d",
    "%Y-%m-%d %H:%M",
    "%d-%m-%Y",
)


class PandaGreenWasteError(Exception):
    """Base integration error."""


class PandaGreenWasteAuthError(PandaGreenWasteError):
    """Authentication failed."""


class _InputExtractor(HTMLParser):
    """Extract input values from HTML."""

    def __init__(self) -> None:
        super().__init__()
        self.values: dict[str, str] = {}
        self._current_select_name: str | None = None
        self._selected_option_value: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        tag_name = tag.lower()
        if tag_name == "input":
            name = attr_map.get("name") or attr_map.get("id")
            if not name:
                return
            self.values[name] = attr_map.get("value") or ""
            return
        if tag_name == "textarea":
            name = attr_map.get("name") or attr_map.get("id")
            if name and name not in self.values:
                self.values[name] = attr_map.get("value") or ""
            return
        if tag_name == "select":
            self._current_select_name = attr_map.get("name") or attr_map.get("id")
            self._selected_option_value = None
            if self._current_select_name and self._current_select_name not in self.values:
                self.values[self._current_select_name] = ""
            return
        if tag_name == "option" and self._current_select_name:
            is_selected = "selected" in attr_map or attr_map.get("selected") is not None
            option_value = attr_map.get("value") or ""
            if is_selected:
                self.values[self._current_select_name] = option_value
                self._selected_option_value = option_value

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "select":
            self._current_select_name = None
            self._selected_option_value = None


@dataclass(slots=True)
class PandaCalendarEntry:
    """Normalized future service item."""

    subject: str
    start: datetime
    end: datetime | None = None
    status: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PandaPortalData:
    """Cached integration data."""

    calendar_entries: list[PandaCalendarEntry] = field(default_factory=list)
    service_summary_fields: dict[str, str] = field(default_factory=dict)
    available_services: list[str] = field(default_factory=list)

    def today_entries(self, target_date: date | None = None) -> list[PandaCalendarEntry]:
        """Return entries that fall on the target date."""
        if target_date is None:
            target_date = datetime.now(UTC).date()
        return [entry for entry in self.calendar_entries if entry.start.astimezone(UTC).date() == target_date]


class PandaGreenWasteClient:
    """Thin client for the AMCS customer portal."""

    def __init__(self, session: ClientSession, username: str, password: str) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._base_url = "https://pandagreenwaste-portal.amcsplatform.com"
        self._logged_in = False

    async def async_login(self) -> None:
        """Authenticate against the portal."""
        payload = {
            "UserName": self._username,
            "Password": self._password,
            "PaymentSummaryURL": "",
            "ClientTimeOffset": 0,
        }
        async with self._session.post(
            urljoin(self._base_url, LOGIN_PATH),
            json=payload,
            headers={"Referer": self._base_url + "/"},
        ) as response:
            response.raise_for_status()
            body = await response.json(content_type=None)

        status = str(body.get("Response") or "")
        if not status or status in {"-1", "RecyNoCompany", "RMOInvalidUser"}:
            raise PandaGreenWasteAuthError(f"Login failed with portal response {status!r}")
        if status == "Enable Account Selection":
            raise PandaGreenWasteAuthError("Portal requested account selection, which is not yet supported.")

        self._logged_in = True
        _LOGGER.debug("Panda login succeeded with response %s", status)

    async def async_get_data(self) -> PandaPortalData:
        """Fetch and normalize service data."""
        await self._ensure_login()
        calendar_html, summary_html, products_html = await self._fetch_pages()
        return PandaPortalData(
            calendar_entries=self._parse_calendar_entries(calendar_html),
            service_summary_fields=self._extract_inputs(summary_html),
            available_services=self._parse_available_services(products_html),
        )

    async def async_book_pickup(
        self,
        pickup_type: str,
        access_start_time: str = DEFAULT_ACCESS_START_TIME,
        access_end_time: str = DEFAULT_ACCESS_END_TIME,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Submit the current service summary form with pickup defaults."""
        await self._ensure_login()
        summary_html = await self._fetch_text(SERVICE_SUMMARY_PATH)
        form_data = self._extract_inputs(summary_html)
        applied_keys = self._apply_pickup_defaults(
            form_data=form_data,
            pickup_type=pickup_type,
            access_start_time=access_start_time,
            access_end_time=access_end_time,
        )
        if payload:
            form_data.update({key: "" if value is None else str(value) for key, value in payload.items()})

        async with self._session.post(
            urljoin(self._base_url, SERVICE_SUMMARY_PATH),
            data=form_data,
            headers={"Referer": urljoin(self._base_url, SERVICE_SUMMARY_PATH)},
        ) as response:
            text = await response.text()
            response.raise_for_status()

        return {
            "ok": True,
            "status": response.status,
            "contains_confirmation": "confirmed" in text.lower() or "success" in text.lower(),
            "contains_session_expired": "session-expired" in text.lower(),
            "pickup_type": pickup_type,
            "applied_keys": sorted(applied_keys),
        }

    def _apply_pickup_defaults(
        self,
        form_data: dict[str, str],
        pickup_type: str,
        access_start_time: str,
        access_end_time: str,
    ) -> set[str]:
        applied_keys: set[str] = set()

        semantic_values = {
            "pickup_type": pickup_type,
            "service_option": DEFAULT_SERVICE_OPTION,
            "order_option": DEFAULT_ORDER_OPTION,
            "access_start_time": access_start_time,
            "access_end_time": access_end_time,
        }

        candidate_matches = {
            "pickup_type": (
                "mixed packaging",
                "msw municipal mixed",
                "glass",
                "140l food wasre bin",
                "pickup_type",
                "service_type",
                "material",
                "waste_stream",
            ),
            "service_option": ("service", "serviceoption", "service_option", "services"),
            "order_option": ("order", "action", "requesttype", "request_type"),
            "access_start_time": ("accessstarttime", "access_start_time", "access start", "accessfrom", "starttime"),
            "access_end_time": ("accessendtime", "access_end_time", "access end", "accessto", "endtime"),
        }

        lowered_keys = {key: key.casefold() for key in form_data}
        for semantic_name, fragments in candidate_matches.items():
            value = semantic_values[semantic_name]
            for original_key, lowered_key in lowered_keys.items():
                if any(fragment in lowered_key for fragment in fragments):
                    form_data[original_key] = value
                    applied_keys.add(original_key)

        fallback_values = {
            "PickupType": pickup_type,
            "ServiceType": pickup_type,
            "SelectedService": DEFAULT_SERVICE_OPTION,
            "Service": DEFAULT_SERVICE_OPTION,
            "OrderType": DEFAULT_ORDER_OPTION,
            "RequestType": DEFAULT_ORDER_OPTION,
            "AccessStartTime": access_start_time,
            "AccessEndTime": access_end_time,
        }
        for key, value in fallback_values.items():
            if key not in form_data:
                form_data[key] = value
            applied_keys.add(key)

        return applied_keys

    async def _ensure_login(self) -> None:
        if not self._logged_in:
            await self.async_login()

    async def _fetch_pages(self) -> tuple[str, str, str]:
        calendar_html = await self._fetch_text(CALENDAR_PATH, retry_on_auth=True)
        summary_html = await self._fetch_text(SERVICE_SUMMARY_PATH, retry_on_auth=True)
        products_html = await self._fetch_text(PRODUCTS_PATH, retry_on_auth=True)
        return calendar_html, summary_html, products_html

    async def _fetch_text(self, path: str, retry_on_auth: bool = False) -> str:
        async with self._session.get(urljoin(self._base_url, path)) as response:
            text = await response.text()
            try:
                response.raise_for_status()
            except ClientResponseError as err:
                raise PandaGreenWasteError(f"Failed to fetch {path}: {err.status}") from err

        if retry_on_auth and self._looks_logged_out(text):
            _LOGGER.debug("Portal returned logged-out markup for %s, retrying after login", path)
            self._logged_in = False
            await self.async_login()
            return await self._fetch_text(path, retry_on_auth=False)

        return text

    @staticmethod
    def _looks_logged_out(html: str) -> bool:
        lowered = html.lower()
        return "window.location.href = window.location.origin + \"/session-expired\"" in lowered

    def _parse_calendar_entries(self, html: str) -> list[PandaCalendarEntry]:
        entries: list[PandaCalendarEntry] = []

        for table_id in ("CollectionHistoryTable", "TicketHistoryTable"):
            headers, rows = self._extract_table(html, table_id)
            if not rows:
                continue
            for row in rows:
                entry = self._row_to_entry(headers, row)
                if entry and entry.start >= datetime.now(UTC):
                    entries.append(entry)

        if not entries:
            entries.extend(self._parse_script_events(html))

        entries.sort(key=lambda item: item.start)
        return entries[:ENTRY_LIMIT]

    def _parse_available_services(self, html: str) -> list[str]:
        matches = re.findall(
            r'block-banners__item-title[^>]*>(.*?)<',
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        services = [self._clean_text(match) for match in matches]
        return [service for service in services if service]

    def _parse_script_events(self, html: str) -> list[PandaCalendarEntry]:
        entries: list[PandaCalendarEntry] = []
        for script_body in _SCRIPT_RE.findall(html):
            for match in re.finditer(r"\{[^{}]*(title|subject)[^{}]*(start|date)[^{}]*\}", script_body, re.IGNORECASE):
                snippet = match.group(0)
                subject_match = re.search(r'"(?:title|subject)"\s*:\s*"([^"]+)"', snippet, re.IGNORECASE)
                start_match = re.search(r'"(?:start|date)"\s*:\s*"([^"]+)"', snippet, re.IGNORECASE)
                if not subject_match or not start_match:
                    continue
                start = self._parse_date(start_match.group(1))
                if not start:
                    continue
                entries.append(
                    PandaCalendarEntry(
                        subject=unescape(subject_match.group(1)),
                        start=start,
                        raw={"source": "script"},
                    )
                )
        return entries

    @staticmethod
    def _extract_inputs(html: str) -> dict[str, str]:
        parser = _InputExtractor()
        parser.feed(html)
        return parser.values

    def _extract_table(self, html: str, table_id: str) -> tuple[list[str], list[list[str]]]:
        for match in _TABLE_RE.finditer(html):
            if match.group("id") != table_id:
                continue
            rows = _ROW_RE.findall(match.group("body"))
            cleaned_rows = [[self._clean_text(cell) for cell in _CELL_RE.findall(row)] for row in rows]
            cleaned_rows = [row for row in cleaned_rows if any(cell for cell in row)]
            if not cleaned_rows:
                return [], []
            headers = cleaned_rows[0]
            return headers, cleaned_rows[1:]
        return [], []

    def _row_to_entry(self, headers: list[str], row: list[str]) -> PandaCalendarEntry | None:
        data = {headers[index]: row[index] for index in range(min(len(headers), len(row)))}
        if not data:
            return None

        subject = self._first_value(data, ("Subject", "Service", "Description", "Ticket Type", "Order Type"))
        date_text = self._first_value(
            data,
            ("Collection Date", "Date", "Requested Date", "Delivery Date", "Start Date"),
        )
        if not subject or not date_text:
            return None

        start = self._parse_date(date_text)
        if not start:
            return None

        return PandaCalendarEntry(
            subject=subject,
            start=start,
            status=self._first_value(data, ("Status", "Ticket Status")),
            raw=data,
        )

    def _parse_date(self, value: str) -> datetime | None:
        cleaned = value.strip()
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(cleaned, fmt).replace(tzinfo=UTC)
            except ValueError:
                continue

        try:
            parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    @staticmethod
    def _first_value(data: dict[str, str], keys: tuple[str, ...]) -> str | None:
        normalized = {key.casefold(): value for key, value in data.items()}
        for key in keys:
            value = normalized.get(key.casefold())
            if value:
                return value
        return None

    @staticmethod
    def _clean_text(value: str) -> str:
        no_tags = _TAG_RE.sub(" ", value)
        return _WHITESPACE_RE.sub(" ", unescape(no_tags)).strip()


__all__ = [
    "PandaCalendarEntry",
    "PandaGreenWasteAuthError",
    "PandaGreenWasteClient",
    "PandaGreenWasteError",
    "PandaPortalData",
]
