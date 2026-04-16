"""Client for the Panda Green Waste portal."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from html import unescape
from html.parser import HTMLParser
import logging
import re
from typing import Any
from urllib.parse import urljoin

from aiohttp import ClientResponseError, ClientSession

from .const import (
    CALENDAR_PATH,
    CALENDAR_EVENTS_PATH,
    CREATE_SERVICE_JOBS_PATH,
    DEFAULT_ACCESS_END_TIME,
    DEFAULT_ACCESS_START_TIME,
    ENTRY_LIMIT,
    LOGIN_PATH,
    PRODUCTS_PATH,
    SERVICE_JOB_DETAILS_PATH,
    SERVICE_SUMMARY_PATH,
    UPDATE_DEFAULT_SITE_PATH,
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

_PICKUP_TARGETS: dict[str, dict[str, str]] = {
    "mixed packaging": {
        "label": "Mixed Packaging",
        "site_order_id": "17310",
        "container_type_id": "105",
    },
    "msw municipal mixed": {
        "label": "MSW Municipal Mixed",
        "site_order_id": "17311",
        "container_type_id": "105",
    },
    "glass": {
        "label": "Glass",
        "site_order_id": "451296",
        "container_type_id": "3",
    },
    "140l food wasre bin": {
        "label": "140L Food Wasre BIN",
        "site_order_id": "478523",
        "container_type_id": "358",
    },
}

_ACCESS_DAYS_ALL_WEEK = "1,2,3,4,5,6,7"

_BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
}


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


class _FormExtractor(HTMLParser):
    """Extract ordered form fields without dropping duplicate MVC field names."""

    def __init__(self) -> None:
        super().__init__()
        self.forms: list[dict[str, Any]] = []
        self._current_form: dict[str, Any] | None = None
        self._current_textarea_name: str | None = None
        self._current_textarea_chunks: list[str] = []
        self._current_select_name: str | None = None
        self._current_select_value: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key: value for key, value in attrs if key}
        tag_name = tag.lower()
        if tag_name == "form":
            self._current_form = {
                "attrs": attr_map,
                "fields": [],
            }
            return

        if self._current_form is None:
            return

        if tag_name == "input":
            field_type = (attr_map.get("type") or "text").casefold()
            name = attr_map.get("name")
            if name and field_type not in {"button", "submit", "reset", "image"}:
                self._current_form["fields"].append((name, attr_map.get("value") or ""))
            return

        if tag_name == "textarea":
            self._current_textarea_name = attr_map.get("name")
            self._current_textarea_chunks = []
            return

        if tag_name == "select":
            self._current_select_name = attr_map.get("name")
            self._current_select_value = ""
            return

        if tag_name == "option" and self._current_select_name:
            if "selected" in attr_map or attr_map.get("selected") is not None:
                self._current_select_value = attr_map.get("value") or ""

    def handle_data(self, data: str) -> None:
        if self._current_textarea_name:
            self._current_textarea_chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag_name = tag.lower()
        if tag_name == "textarea" and self._current_form and self._current_textarea_name:
            self._current_form["fields"].append(
                (self._current_textarea_name, "".join(self._current_textarea_chunks))
            )
            self._current_textarea_name = None
            self._current_textarea_chunks = []
            return

        if tag_name == "select" and self._current_form and self._current_select_name:
            self._current_form["fields"].append((self._current_select_name, self._current_select_value or ""))
            self._current_select_name = None
            self._current_select_value = None
            return

        if tag_name == "form" and self._current_form is not None:
            self.forms.append(self._current_form)
            self._current_form = None


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

    def __init__(
        self,
        session: ClientSession,
        username: str,
        password: str,
        site_id: str | None = None,
        site_name: str | None = None,
    ) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._site_id = site_id
        self._site_name = site_name
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
        calendar_entries = await self._fetch_calendar_entries()
        if not calendar_entries:
            calendar_entries = self._parse_calendar_entries(calendar_html)
        return PandaPortalData(
            calendar_entries=calendar_entries,
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
        """Create a pickup by following the portal's Service Summary workflow."""
        await self._ensure_login()
        await self._set_default_site()
        await self._prime_service_summary()

        target = self._pickup_target(pickup_type)
        create_path = (
            "/service-summary/create-service-jobs"
            f"?siteOrderId={target['site_order_id']}"
            "&actionId=9&actionName=Lift&serviceId=4"
            f"&containerTypeId={target['container_type_id']}"
            "&liftQuantity=1"
        )
        create_html = await self._fetch_text(
            create_path,
            retry_on_auth=True,
            headers={"Referer": urljoin(self._base_url, SERVICE_SUMMARY_PATH + "/")},
        )
        create_form = self._extract_form_fields(
            create_html,
            form_name="CreateServiceJob",
            required_fields=("SiteOrderId", "ActionId", "ContainerTypeId"),
        )
        if not create_form:
            page_text = self._clean_text(create_html)[:300] or "empty response"
            raise PandaGreenWasteError(
                f"Panda did not return a create-service form for {target['label']}. Page said: {page_text}"
            )

        create_form = self._mark_first_service_product_selected(create_form)
        if payload:
            create_form.extend((key, "" if value is None else str(value)) for key, value in payload.items())

        async with self._session.post(
            urljoin(self._base_url, CREATE_SERVICE_JOBS_PATH),
            data=create_form,
            headers={"Referer": urljoin(self._base_url, create_path)},
        ) as response:
            details_html = await response.text()
            response.raise_for_status()

        if self._looks_logged_out(details_html):
            self._logged_in = False
            raise PandaGreenWasteAuthError("Panda session expired while creating the pickup.")
        if "service job details" not in self._clean_text(details_html).casefold():
            raise PandaGreenWasteError("Panda did not open the final Service Job Details step.")

        details_form = self._extract_form_fields(
            details_html,
            form_name="ServiceJobDetailsSubmit",
            required_fields=("__RequestVerificationToken", "SelectedServiceProductPriceId", "SiteOrderId"),
        )
        if not details_form:
            raise PandaGreenWasteError("Panda did not return the final Service Job Details form.")

        details_form = self._apply_access_times(
            details_form,
            access_start_time=access_start_time,
            access_end_time=access_end_time,
        )
        details_form.append(("SkipsButton", "Finish"))

        async with self._session.post(
            urljoin(self._base_url, SERVICE_JOB_DETAILS_PATH),
            data=details_form,
            headers={"Referer": urljoin(self._base_url, SERVICE_JOB_DETAILS_PATH)},
        ) as response:
            final_html = await response.text()
            response.raise_for_status()

        final_text = self._clean_text(final_html)
        lowered_final = final_text.casefold()
        validation_failed = any(
            marker in lowered_final
            for marker in (
                "field is required",
                "select at least one day",
                "validation-summary-errors",
                "access start time must",
                "access end time must",
                "account is invalid",
            )
        )
        final_booking_confirmed = (
            not validation_failed
            and "service job details" not in lowered_final
            and "service summary" in lowered_final
        )
        return {
            "ok": True,
            "status": response.status,
            "pickup_type": target["label"],
            "site_order_id": target["site_order_id"],
            "access_start_time": access_start_time,
            "access_end_time": access_end_time,
            "contains_session_expired": "session-expired" in lowered_final,
            "validation_failed": validation_failed,
            "final_booking_confirmed": final_booking_confirmed,
            "message": "Panda final Finish step completed." if final_booking_confirmed else final_text[:500],
        }

    @staticmethod
    def _pickup_target(pickup_type: str) -> dict[str, str]:
        target = _PICKUP_TARGETS.get(pickup_type.casefold())
        if not target:
            raise PandaGreenWasteError(f"Unsupported Panda pickup type: {pickup_type}")
        return target

    async def _ensure_login(self) -> None:
        if not self._logged_in:
            await self.async_login()

    async def _fetch_pages(self) -> tuple[str, str, str]:
        calendar_html = await self._fetch_text(CALENDAR_PATH, retry_on_auth=True)
        summary_html = await self._fetch_text(SERVICE_SUMMARY_PATH, retry_on_auth=True)
        products_html = await self._fetch_text(PRODUCTS_PATH, retry_on_auth=True)
        return calendar_html, summary_html, products_html

    async def _prime_service_summary(self) -> None:
        """Open the same portal pages the browser visits before the create form."""
        await self._fetch_text("/dashboard", retry_on_auth=True)
        await self._fetch_text(SERVICE_SUMMARY_PATH + "/", retry_on_auth=True)

    async def _fetch_calendar_entries(self) -> list[PandaCalendarEntry]:
        if not self._site_id or not self._site_name:
            return []

        await self._set_default_site()
        start = datetime.now(UTC).date().replace(day=1)
        end = start + timedelta(days=62)
        payload = {
            "Start": f"{start.isoformat()}T00:00:00.000Z",
            "End": f"{end.isoformat()}T00:00:00.000Z",
            "SiteId": str(self._site_id),
            "SiteIdString": self._site_name,
        }
        async with self._session.post(
            urljoin(self._base_url, CALENDAR_EVENTS_PATH),
            json=payload,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "X-Requested-With": "XMLHttpRequest",
                "departmentId": "0",
                "Referer": urljoin(self._base_url, CALENDAR_PATH),
            },
        ) as response:
            text = await response.text()
            response.raise_for_status()

        if not text.strip():
            return []

        try:
            import json

            data = json.loads(text)
        except ValueError:
            _LOGGER.debug("Panda calendar events endpoint returned non-JSON content")
            return []

        entries: list[PandaCalendarEntry] = []
        for row in data:
            if not row.get("ShowActivityEvent", True):
                continue
            start_value = row.get("start")
            title = row.get("title")
            if not start_value or not title:
                continue
            start_dt = self._parse_date(str(start_value))
            if not start_dt:
                continue
            entries.append(
                PandaCalendarEntry(
                    subject=str(title),
                    start=start_dt,
                    raw=row,
                )
            )
        entries.sort(key=lambda item: item.start)
        return entries[:ENTRY_LIMIT]

    async def _set_default_site(self) -> None:
        if not self._site_id:
            return
        async with self._session.post(
            urljoin(self._base_url, UPDATE_DEFAULT_SITE_PATH),
            json={"selectedCustomerSiteId": int(self._site_id)},
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": urljoin(self._base_url, "/dashboard"),
            },
        ) as response:
            response.raise_for_status()

    async def _fetch_text(
        self,
        path: str,
        retry_on_auth: bool = False,
        headers: dict[str, str] | None = None,
    ) -> str:
        request_headers = dict(_BROWSER_HEADERS)
        if headers:
            request_headers.update(headers)
        async with self._session.get(urljoin(self._base_url, path), headers=request_headers) as response:
            text = await response.text()
            try:
                response.raise_for_status()
            except ClientResponseError as err:
                raise PandaGreenWasteError(f"Failed to fetch {path}: {err.status}") from err

        if retry_on_auth and self._looks_logged_out(text):
            _LOGGER.debug("Portal returned logged-out markup for %s, retrying after login", path)
            self._logged_in = False
            await self.async_login()
            return await self._fetch_text(path, retry_on_auth=False, headers=headers)

        return text

    @staticmethod
    def _looks_logged_out(html: str) -> bool:
        lowered = html.lower()
        return "window.location.href = window.location.origin + \"/session-expired\"" in lowered

    def _parse_calendar_entries(self, html: str) -> list[PandaCalendarEntry]:
        entries: list[PandaCalendarEntry] = []
        today = datetime.now(UTC).date()

        for table_id in ("CollectionHistoryTable", "TicketHistoryTable"):
            headers, rows = self._extract_table(html, table_id)
            if not rows:
                continue
            for row in rows:
                entry = self._row_to_entry(headers, row)
                if entry and entry.start.astimezone(UTC).date() >= today:
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

    @staticmethod
    def _extract_form_fields(
        html: str,
        form_name: str | None = None,
        required_fields: tuple[str, ...] = (),
    ) -> list[tuple[str, str]]:
        parser = _FormExtractor()
        parser.feed(html)
        fallback: list[tuple[str, str]] = []
        for form in parser.forms:
            attrs = form["attrs"]
            fields = list(form["fields"])
            if form_name is None or attrs.get("name") == form_name or attrs.get("id") == form_name:
                return fields
            field_names = {key for key, _value in fields}
            if required_fields and all(required in field_names for required in required_fields):
                fallback = fields
        return fallback

    @staticmethod
    def _mark_first_service_product_selected(fields: list[tuple[str, str]]) -> list[tuple[str, str]]:
        """Mirror clicking the first product row before the portal posts to details."""
        selected_seen = False
        marked: list[tuple[str, str]] = []
        for key, value in fields:
            if key.endswith(".IsSelected"):
                if selected_seen:
                    marked.append((key, "False"))
                else:
                    marked.append((key, "True"))
                    selected_seen = True
                continue
            marked.append((key, value))
        return marked

    @staticmethod
    def _apply_access_times(
        fields: list[tuple[str, str]],
        access_start_time: str,
        access_end_time: str,
    ) -> list[tuple[str, str]]:
        """Add the access-time collection generated by Panda's Knockout view model."""
        skip_names = {
            "AccessTime.Id",
            "AccessTime.ParentId",
            "AccessTime.AccessStartTime",
            "AccessTime.AccessEndTime",
            "AccessTime.AccessContact",
            "AccessTime.AccessNotes",
        }
        cleaned = [(key, value) for key, value in fields if key not in skip_names]
        cleaned.extend(
            (
                ("AccessTimes[0].Id", "0"),
                ("AccessTimes[0].InEditMode", "false"),
                ("AccessTimes[0].IsDeleted", "false"),
                ("AccessTimes[0].AccessStartTime", access_start_time),
                ("AccessTimes[0].AccessEndTime", access_end_time),
                ("AccessTimes[0].AccessContact", ""),
                ("AccessTimes[0].AccessNotes", ""),
                ("AccessTimes[0].accessDaysString", _ACCESS_DAYS_ALL_WEEK),
            )
        )
        return cleaned

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
