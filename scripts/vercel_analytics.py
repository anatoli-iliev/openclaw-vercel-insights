#!/usr/bin/env python3
"""Read-only command line client for the Vercel Web Analytics API.

This script answers the everyday questions about a Vercel project's traffic:
how many page views and visitors it had, which pages and referrers drove them,
where the visitors came from, and how custom events break down.

Read-only guarantee
-------------------
The Vercel Web Analytics API is a query API and this script uses nothing else.
There is exactly one HTTP call site in this file and it is ``session.get``.
No other verb is reachable from any code path, no request body is ever built,
and the access token is only ever placed in the ``Authorization`` header, never
in a URL, a query parameter, a log line, an exception, or any rendered output.

Usage
-----
    export VERCEL_TOKEN=...          # a Vercel access token
    export VERCEL_PROJECT_ID=prj_... # project id or project name

    python3 vercel_analytics.py                        # 7 day overview
    python3 vercel_analytics.py top-pages --since 30d  # a single table
    python3 vercel_analytics.py events --event-property plan --json

Run ``--list-presets`` for the full preset table and ``--help`` for every flag.
Add ``--dry-run`` to print the exact request that would be sent without sending
anything; it works even with no token configured.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Imports and constants
# ---------------------------------------------------------------------------
import argparse
import csv
import difflib
import io
import json
import math
import os
import random
import re
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Protocol, TextIO, TypeGuard
from urllib.parse import urlencode

import requests

VERSION = "0.1.0"

BASE_URL = "https://api.vercel.com/v1/query/web-analytics"

DOCS_TOKEN_URL = "https://vercel.com/docs/rest-api#creating-an-access-token"

#: The two datasets this API exposes.
DATASETS: tuple[str, ...] = ("visits", "events")

#: Time buckets. At most one may appear in a single grouping.
TIME_GRANULARITIES: tuple[str, ...] = ("hour", "day", "week", "month", "year")

#: Plain dimensions accepted by both datasets.
PLAIN_DIMENSIONS: tuple[str, ...] = (
    "country",
    "deviceType",
    "environment",
    "requestPath",
    "referrerHostname",
    "osName",
    "browserName",
    "route",
    "utmSource",
    "utmMedium",
    "utmCampaign",
    "utmContent",
    "utmTerm",
)

#: JSON dimensions, mapped to the datasets that accept them. Used bare they
#: group by key name; used as ``base/key`` they group by that key's value.
JSON_DIMENSIONS: dict[str, tuple[str, ...]] = {
    "flags": ("visits", "events"),
    "eventData": ("events",),
}

VISIT_DIMENSIONS: tuple[str, ...] = TIME_GRANULARITIES + PLAIN_DIMENSIONS + ("flags",)

EVENT_DIMENSIONS: tuple[str, ...] = (
    TIME_GRANULARITIES + PLAIN_DIMENSIONS + ("eventName", "flags", "eventData")
)

#: Metric keys each dataset returns, primary metric first.
DATASET_METRICS: dict[str, tuple[str, ...]] = {
    "visits": ("pageviews", "visitors"),
    "events": ("count", "visitors"),
}

#: Every metric key this client recognises while parsing rows.
KNOWN_METRICS: frozenset[str] = frozenset(
    name for names in DATASET_METRICS.values() for name in names
)

MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_LIMIT = 10
MAX_GROUP_BY = 2

#: Rows collapsed by the API once ``limit`` is exceeded arrive under this label.
OTHERS_LABEL = "Others"

DEFAULT_SINCE = "7d"
DEFAULT_UNTIL = "now"
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 3

#: Statuses worth retrying. Any other 5xx is retried too; no other 4xx ever is.
RETRYABLE_STATUSES: frozenset[int] = frozenset({429, 500, 502, 503, 504})

BACKOFF_BASE_SECONDS = 0.5
MAX_SLEEP_SECONDS = 60.0

#: The reporting window guaranteed by the most generous plan tier.
MAX_REPORTING_WINDOW = timedelta(days=730)

#: Number of table rows the overview preset shows per section.
OVERVIEW_TABLE_LIMIT = 5

REDACTED_BEARER = "Bearer <redacted>"
REDACTED = "<redacted>"
_SENSITIVE_HEADERS = frozenset({"authorization", "proxy-authorization", "cookie"})

#: Unix milliseconds outside this range cannot become a :class:`datetime`.
MIN_UNIX_MS = -62135596800000  # 0001-01-01T00:00:00Z
MAX_UNIX_MS = 253402300799999  # 9999-12-31T23:59:59.999Z

_RELATIVE_RE = re.compile(r"^(\d+)\s*([mhdw])$", re.IGNORECASE)
_UNIX_MS_RE = re.compile(r"^\d{11,}$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: One segment of a JSON dimension key, per the OpenAPI schema
#: ``^(flags)(/([0-9A-Za-z_]+|'([^']|'')*'))+$``: either bare word characters,
#: or a single quoted string whose embedded quotes are doubled.
_BARE_JSON_KEY_RE = re.compile(r"^[0-9A-Za-z_]+$")
_QUOTED_JSON_KEY_RE = re.compile(r"^'(?:[^']|'')*'$")

JSON_KEY_HELP = (
    "each key segment must be either bare letters, digits and underscores "
    "(flags/beta_banner) or a single quoted string with every embedded quote "
    "doubled (eventData/'sign-up', eventData/'it''s')"
)

_RELATIVE_UNITS: dict[str, str] = {
    "m": "minutes",
    "h": "hours",
    "d": "days",
    "w": "weeks",
}

TIME_HELP = (
    "accepted forms: a relative offset such as 30m, 24h, 7d or 4w; "
    "now, today or yesterday; an ISO date such as 2026-08-01; an ISO datetime "
    "such as 2026-08-01T12:00:00Z; or Unix milliseconds (11 or more digits)"
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ConfigError(Exception):
    """A configuration or usage problem detected before any network call.

    Every ``ConfigError`` message names the offending value and the fix, and is
    reported to the user as a single line with exit code 2.
    """


class ApiError(Exception):
    """The API returned an error, or the network failed after every retry.

    ``message`` holds Vercel's ``error.message`` verbatim whenever the response
    carried one. The rendered string prefixes it with the HTTP status and the
    API error code, and notes the attempt count when retries were used up.
    """

    def __init__(
        self,
        status: int | None,
        code: str | None,
        message: str,
        *,
        attempts: int = 1,
    ) -> None:
        self.status = status
        self.code = code
        self.message = message
        self.attempts = attempts
        super().__init__(self._render())

    def _render(self) -> str:
        prefix = f"HTTP {self.status}" if self.status is not None else "Network error"
        if self.code:
            prefix = f"{prefix} ({self.code})"
        text = f"{prefix}: {self.message}"
        if self.attempts > 1:
            text = f"{text} [gave up after {self.attempts} attempts]"
        return text

    def __str__(self) -> str:
        return self._render()


class RateLimitError(ApiError):
    """A ``rate_limited`` response. ``limit`` holds Vercel's limit object."""

    def __init__(
        self,
        status: int | None,
        code: str | None,
        message: str,
        *,
        attempts: int = 1,
        limit: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(status, code, message, attempts=attempts)
        self.limit: Mapping[str, Any] = dict(limit or {})


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, repr=False)
class PreparedRequest:
    """Everything needed to issue one GET, and nothing else.

    ``params`` is an ordered list of pairs rather than a mapping because ``by``
    may legitimately appear twice. ``headers`` is the only place a credential
    ever lives, and the generated ``repr`` is suppressed so that printing one of
    these cannot leak it: :meth:`__repr__` renders headers through
    :func:`redact_headers`, which makes the guarantee structural rather than a
    promise that no caller ever prints the object.
    """

    method: str
    url: str
    params: list[tuple[str, str]]
    headers: dict[str, str]

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(method={self.method!r}, url={self.url!r}, "
            f"params={self.params!r}, headers={redact_headers(self.headers)!r})"
        )


@dataclass(frozen=True)
class Row:
    """One result row: its group labels, its metrics, and an optional bucket.

    ``labels`` holds one cell per non-time grouping dimension, in the order the
    dimensions were requested, so a two dimension grouping keeps both values.
    ``key`` is the convenience accessor for the common single label case.
    """

    labels: tuple[str | None, ...] = ()
    metrics: dict[str, float] = field(default_factory=dict)
    timestamp: str | None = None
    #: True for the bucket the API uses to collapse limit overflow. This is a
    #: field rather than a comparison against ``key`` because a time-only
    #: grouping carries the overflow marker on the timestamp instead.
    is_others: bool = False

    @property
    def key(self) -> str | None:
        """The first group label, or ``None`` when the row carries none."""
        return self.labels[0] if self.labels else None


@dataclass(frozen=True)
class Result:
    """A parsed response: rows plus the context needed to render them."""

    rows: list[Row]
    is_count: bool
    dataset: str
    group_by: list[str]
    query: dict[str, Any]
    metric_names: list[str]

    @property
    def primary_metric(self) -> str:
        """The metric used for sorting context and share-of-total percentages."""
        if self.metric_names:
            return self.metric_names[0]
        return DATASET_METRICS[self.dataset][0]

    @property
    def group_dimensions(self) -> list[str]:
        """Every non-time dimension the rows are labelled by, in request order.

        There is one label cell per entry here on every row, so a grouping such
        as ``eventName`` plus ``eventData/plan`` keeps both values instead of
        collapsing onto the first one.
        """
        return [dim for dim in self.group_by if dim not in TIME_GRANULARITIES]

    @property
    def group_dimension(self) -> str | None:
        """The first non-time dimension, if there is one."""
        dimensions = self.group_dimensions
        return dimensions[0] if dimensions else None

    @property
    def granularity(self) -> str | None:
        """The time granularity in the grouping, if there is one."""
        for dimension in self.group_by:
            if dimension in TIME_GRANULARITIES:
                return dimension
        return None

    def totals(self) -> dict[str, float]:
        """Sum every metric across every row, including the ``Others`` bucket."""
        totals: dict[str, float] = {name: 0 for name in self.metric_names}
        for row in self.rows:
            for name in self.metric_names:
                totals[name] += row.metrics.get(name, 0)
        return totals


@dataclass(frozen=True)
class Preset:
    """A named bundle of defaults. Any explicit flag overrides a preset value."""

    name: str
    dataset: str
    group_by: tuple[str, ...]
    limit: int | None
    description: str
    calls: int = 1

    @property
    def endpoint(self) -> str:
        """The endpoint this preset hits, for display purposes."""
        endpoint = select_endpoint(list(self.group_by))
        if self.calls > 1:
            return f"{self.calls} x {endpoint}"
        return endpoint


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------

PRESETS: dict[str, Preset] = {
    "overview": Preset(
        name="overview",
        dataset="visits",
        group_by=("day",),
        limit=OVERVIEW_TABLE_LIMIT,
        description="Totals, a daily trend, top pages and top referrers",
        calls=3,
    ),
    "trend": Preset(
        name="trend",
        dataset="visits",
        group_by=("day",),
        limit=MAX_LIMIT,
        description="Page views over time (change buckets with --granularity)",
    ),
    "top-pages": Preset(
        name="top-pages",
        dataset="visits",
        group_by=("requestPath",),
        limit=DEFAULT_LIMIT,
        description="Most viewed URL paths",
    ),
    "top-routes": Preset(
        name="top-routes",
        dataset="visits",
        group_by=("route",),
        limit=DEFAULT_LIMIT,
        description="Most viewed framework routes, for example /blog/[slug]",
    ),
    "referrers": Preset(
        name="referrers",
        dataset="visits",
        group_by=("referrerHostname",),
        limit=DEFAULT_LIMIT,
        description="Where the traffic came from",
    ),
    "countries": Preset(
        name="countries",
        dataset="visits",
        group_by=("country",),
        limit=DEFAULT_LIMIT,
        description="Traffic by country",
    ),
    "devices": Preset(
        name="devices",
        dataset="visits",
        group_by=("deviceType",),
        limit=DEFAULT_LIMIT,
        description="Traffic by device type",
    ),
    "browsers": Preset(
        name="browsers",
        dataset="visits",
        group_by=("browserName",),
        limit=DEFAULT_LIMIT,
        description="Traffic by browser",
    ),
    "operating-systems": Preset(
        name="operating-systems",
        dataset="visits",
        group_by=("osName",),
        limit=DEFAULT_LIMIT,
        description="Traffic by operating system",
    ),
    "campaigns": Preset(
        name="campaigns",
        dataset="visits",
        group_by=("utmCampaign",),
        limit=DEFAULT_LIMIT,
        description="Traffic by utm_campaign (needs Web Analytics Plus)",
    ),
    "events": Preset(
        name="events",
        dataset="events",
        group_by=("eventName",),
        limit=DEFAULT_LIMIT,
        description="Custom events, plus --event-property NAME to break one out",
    ),
    "total": Preset(
        name="total",
        dataset="visits",
        group_by=(),
        limit=None,
        description="One ungrouped total from the count endpoint",
    ),
}

DEFAULT_PRESET = "overview"


# ---------------------------------------------------------------------------
# Time parsing
# ---------------------------------------------------------------------------


def parse_time_value(value: str, now: datetime) -> datetime:
    """Turn one ``--since`` or ``--until`` token into an aware UTC datetime.

    Args:
        value: The raw token, for example ``7d``, ``today`` or ``2026-08-01``.
        now: The reference instant relative offsets are measured back from.

    Returns:
        The resolved instant, always timezone aware and in UTC.

    Raises:
        ConfigError: If the token matches none of the documented forms.
    """
    raw = value.strip()
    if not raw:
        raise ConfigError(f"empty time value: {TIME_HELP}")

    reference = now.astimezone(timezone.utc)
    lowered = raw.lower()

    if lowered == "now":
        return reference
    if lowered == "today":
        return reference.replace(hour=0, minute=0, second=0, microsecond=0)
    if lowered == "yesterday":
        midnight = reference.replace(hour=0, minute=0, second=0, microsecond=0)
        return midnight - timedelta(days=1)

    relative = _RELATIVE_RE.match(lowered)
    if relative:
        amount = int(relative.group(1))
        unit = _RELATIVE_UNITS[relative.group(2).lower()]
        return reference - timedelta(**{unit: amount})

    if _UNIX_MS_RE.match(raw):
        return _from_unix_ms(raw)

    if raw.isdigit():
        raise ConfigError(
            f"time value {raw!r} looks like Unix seconds; this option wants Unix "
            f"milliseconds (11 or more digits), so try {raw}000, or use an ISO "
            "date such as 2026-08-01"
        )

    if _ISO_DATE_RE.match(raw):
        try:
            return datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError as exc:
            raise ConfigError(f"time value {raw!r} is not a real date: {exc}") from exc

    candidate = raw[:-1] + "+00:00" if raw.endswith(("Z", "z")) else raw
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ConfigError(f"unrecognised time value {raw!r}: {TIME_HELP}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _from_unix_ms(raw: str) -> datetime:
    """Convert a Unix millisecond string to an aware UTC datetime.

    A value large enough to fall outside the year 1 to year 9999 range that
    :class:`datetime` can represent raises ``ValueError``, ``OverflowError`` or
    ``OSError`` depending on the platform. All three become a ``ConfigError``
    naming the accepted range, so no traceback ever reaches the user.

    Raises:
        ConfigError: When the value is outside the representable range.
    """
    try:
        milliseconds = int(raw)
    except ValueError as exc:  # pragma: no cover - the regex admits digits only
        raise ConfigError(f"time value {raw!r} is not an integer") from exc
    if MIN_UNIX_MS <= milliseconds <= MAX_UNIX_MS:
        try:
            return datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            pass
    raise ConfigError(
        f"time value {raw!r} is Unix milliseconds outside the representable "
        f"range of {MIN_UNIX_MS} to {MAX_UNIX_MS} (0001-01-01T00:00:00Z to "
        "9999-12-31T23:59:59Z); check the value has not been given in "
        "microseconds or nanoseconds, or use an ISO date such as 2026-08-01"
    )


def resolve_range(since: str, until: str, now: datetime) -> tuple[datetime, datetime]:
    """Resolve both time tokens and check that they describe a real window.

    Args:
        since: The ``--since`` token.
        until: The ``--until`` token.
        now: The reference instant for relative offsets.

    Returns:
        A ``(since, until)`` pair of aware UTC datetimes, strictly ordered.

    Raises:
        ConfigError: If either token is unparseable, or ``since`` is not
            strictly earlier than ``until``.
    """
    start = parse_time_value(since, now)
    end = parse_time_value(until, now)
    if start >= end:
        raise ConfigError(
            f"--since must be strictly earlier than --until, but --since {since!r} "
            f"resolves to {to_api_timestamp(start)} and --until {until!r} resolves "
            f"to {to_api_timestamp(end)}; widen the window, for example "
            "--since 7d --until now"
        )
    return start, end


def to_api_timestamp(dt: datetime) -> str:
    """Render an aware datetime as the UTC ISO-8601 string the API accepts."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def reporting_window_warning(since: datetime, now: datetime) -> str | None:
    """Return a warning when ``since`` predates the longest reporting window.

    The plan tier is not discoverable from this API, so an old ``--since`` is a
    warning rather than an error: the query stays legal and may return data.
    """
    if now.astimezone(timezone.utc) - since.astimezone(timezone.utc) > (
        MAX_REPORTING_WINDOW
    ):
        return (
            f"--since resolves to {to_api_timestamp(since)}, which is more than 24 "
            "months ago; the guaranteed reporting window is 1 month on Hobby, 12 "
            "months on Pro and 24 months on Enterprise, so older buckets may come "
            "back empty"
        )
    return None


def format_timestamp(value: str, granularity: str | None) -> str:
    """Render an API row timestamp at a sensible precision for its bucket."""
    candidate = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    if granularity == "hour":
        return parsed.strftime("%Y-%m-%d %H:%M")
    if granularity == "month":
        return parsed.strftime("%Y-%m")
    if granularity == "year":
        return parsed.strftime("%Y")
    if granularity in ("day", "week"):
        return parsed.strftime("%Y-%m-%d")
    return parsed.strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------------------
# OData construction
# ---------------------------------------------------------------------------


def quote_odata(value: str) -> str:
    """Wrap a value in single quotes, doubling any quote it already contains."""
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def build_clause(dimension: str, value: str) -> str:
    """Build one filter clause for a dimension and a user supplied value.

    A comma separated value becomes an ``in (...)`` clause; anything else
    becomes an ``eq`` clause. Only operators the API documents are ever emitted.

    Raises:
        ConfigError: If the value is empty, or is only commas.
    """
    parts = [part.strip() for part in value.split(",")]
    parts = [part for part in parts if part]
    if not parts:
        raise ConfigError(
            f"filter value for {dimension} is empty; pass a value such as "
            f"{dimension}=example, or a comma separated list for a set"
        )
    if len(parts) == 1:
        return f"{dimension} eq {quote_odata(parts[0])}"
    joined = ", ".join(quote_odata(part) for part in parts)
    return f"{dimension} in ({joined})"


def _has_top_level_or(clause: str) -> bool:
    """True when ``clause`` contains an ``or`` outside quotes and parentheses."""
    depth = 0
    in_quote = False
    index = 0
    length = len(clause)
    while index < length:
        char = clause[index]
        if in_quote:
            if char == "'":
                if index + 1 < length and clause[index + 1] == "'":
                    index += 2
                    continue
                in_quote = False
        elif char == "'":
            in_quote = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif depth == 0 and clause[index : index + 2].lower() == "or":
            before = clause[index - 1] if index > 0 else " "
            after = clause[index + 2] if index + 2 < length else " "
            if not _is_word_char(before) and not _is_word_char(after):
                return True
        index += 1
    return False


def _is_word_char(char: str) -> bool:
    return char.isalnum() or char == "_"


def combine_filters(clauses: Sequence[str]) -> str | None:
    """Join filter clauses with ``and``, protecting any top-level ``or``.

    Args:
        clauses: Individual OData clauses, in the order they should appear.

    Returns:
        The combined expression, or ``None`` when there is nothing to filter on.
    """
    cleaned = [clause.strip() for clause in clauses if clause and clause.strip()]
    if not cleaned:
        return None
    protected = [
        f"({clause})" if _has_top_level_or(clause) else clause for clause in cleaned
    ]
    return " and ".join(protected)


def _split_json_key_segments(key: str) -> list[str] | None:
    """Split a JSON dimension key into its OData segments, honouring quotes.

    ``a/b`` is two segments, while ``'a/b'`` is one, because a slash inside a
    quoted segment is part of the key name rather than a separator.

    Returns:
        The segments, or ``None`` when a single quote is left unbalanced.
    """
    segments: list[str] = []
    current: list[str] = []
    index = 0
    length = len(key)
    in_quote = False
    while index < length:
        char = key[index]
        if in_quote:
            if char == "'":
                if index + 1 < length and key[index + 1] == "'":
                    current.append("''")
                    index += 2
                    continue
                in_quote = False
            current.append(char)
        elif char == "'":
            in_quote = True
            current.append(char)
        elif char == "/":
            segments.append("".join(current))
            current = []
        else:
            current.append(char)
        index += 1
    if in_quote:
        return None
    segments.append("".join(current))
    return segments


def _is_valid_key_segment(segment: str) -> bool:
    """True for a segment the OpenAPI schema for ``by`` accepts.

    Bare segments are word characters only; anything else has to be a single
    quoted string with its embedded quotes doubled. An empty quoted segment is
    rejected because it names no key at all.
    """
    if _BARE_JSON_KEY_RE.match(segment):
        return True
    return bool(_QUOTED_JSON_KEY_RE.match(segment)) and segment != "''"


def _key_path_is_valid(key: str) -> bool:
    """True when every segment of a JSON dimension key is well formed."""
    segments = _split_json_key_segments(key)
    if segments is None:
        return False
    return bool(segments) and all(_is_valid_key_segment(seg) for seg in segments)


def json_dimension(base: str, key: str) -> str:
    """Compose a JSON dimension such as ``eventData/plan``, quoting when needed.

    A key that is already valid OData is passed through unchanged. A plain name
    carrying punctuation is quoted here rather than being left to the user. A
    key that is neither is rejected: accepting it verbatim because it merely
    looks quoted is how extra OData gets injected into ``by`` and ``filter``.

    Raises:
        ConfigError: If the key is empty, or cannot be made into a legal key.
    """
    name = key.strip()
    if not name:
        raise ConfigError(
            f"{base} needs a key, for example {base}/plan; an empty key groups by "
            "nothing"
        )
    if _key_path_is_valid(name):
        return f"{base}/{name}"
    if "'" in name or "/" in name:
        raise ConfigError(
            f"{base} key {name!r} is not a legal OData key: {JSON_KEY_HELP}"
        )
    return f"{base}/{quote_odata(name)}"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def dimensions_for(dataset: str) -> tuple[str, ...]:
    """Every grouping dimension name valid on ``dataset``."""
    return EVENT_DIMENSIONS if dataset == "events" else VISIT_DIMENSIONS


def validate_dimension(dimension: str, dataset: str) -> str:
    """Validate one grouping dimension against a dataset.

    Handles the JSON dimensions (``flags``, ``eventData``) including their
    ``base/key`` form and the quoting rule for keys with punctuation.

    Args:
        dimension: The dimension as the user wrote it.
        dataset: Either ``visits`` or ``events``.

    Returns:
        The dimension, unchanged, when it is valid.

    Raises:
        ConfigError: With the offending value and the fix.
    """
    name = dimension.strip()
    if not name:
        raise ConfigError(
            "empty grouping dimension; pass a name such as --group-by requestPath"
        )

    if "/" in name:
        base, _, key = name.partition("/")
        if base not in JSON_DIMENSIONS:
            raise ConfigError(
                f"unknown JSON dimension {base!r} in {name!r}; the JSON dimensions "
                f"are {', '.join(sorted(JSON_DIMENSIONS))}"
            )
        if dataset not in JSON_DIMENSIONS[base]:
            raise ConfigError(
                f"{name!r} is only available on the events dataset; add "
                "--dataset events (or use the events preset)"
            )
        if not key:
            raise ConfigError(
                f"{name!r} is missing a key; use {base}/<key>, for example "
                f"{base}/plan, or drop the slash to group by key name"
            )
        segments = _split_json_key_segments(key)
        if segments is None:
            raise ConfigError(
                f"{name!r} leaves a single quote unbalanced in its key; "
                f"{JSON_KEY_HELP}"
            )
        for segment in segments:
            if _is_valid_key_segment(segment):
                continue
            if segment == "''" or not segment:
                raise ConfigError(
                    f"{name!r} has an empty key segment; use {base}/plan"
                )
            if "'" in segment:
                raise ConfigError(
                    f"{name!r} has a key segment {segment!r} that is not a legal "
                    f"quoted string; {JSON_KEY_HELP}"
                )
            raise ConfigError(
                f"{name!r} has a key with characters outside letters, digits and "
                f"underscores; single quote it as {base}/{quote_odata(segment)}"
            )
        return name

    valid = dimensions_for(dataset)
    if name in valid:
        return name

    other = EVENT_DIMENSIONS if dataset == "visits" else VISIT_DIMENSIONS
    if name in other:
        raise ConfigError(
            f"{name!r} is only available on the events dataset; add --dataset "
            "events (or use the events preset)"
        )

    suggestions = difflib.get_close_matches(name, valid, n=1, cutoff=0.6)
    hint = f" Did you mean {suggestions[0]!r}?" if suggestions else ""
    raise ConfigError(
        f"unknown dimension {name!r} for the {dataset} dataset.{hint} "
        f"Valid dimensions: {', '.join(valid)}, plus flags/<name>"
        + (", eventData/<property>" if dataset == "events" else "")
    )


def validate_group_by(dimensions: Sequence[str], dataset: str) -> list[str]:
    """Validate a whole grouping: each dimension, the count, and the time rule.

    Args:
        dimensions: The grouping in request order.
        dataset: Either ``visits`` or ``events``.

    Returns:
        The validated grouping as a list.

    Raises:
        ConfigError: On an unknown dimension, a repeat, more than one time
            granularity, or more than :data:`MAX_GROUP_BY` dimensions.
    """
    validated = [validate_dimension(dimension, dataset) for dimension in dimensions]

    seen: set[str] = set()
    for dimension in validated:
        if dimension in seen:
            raise ConfigError(
                f"dimension {dimension!r} is grouped by twice; remove the repeat "
                "(--granularity also adds a time dimension)"
            )
        seen.add(dimension)

    granularities = [dim for dim in validated if dim in TIME_GRANULARITIES]
    if len(granularities) > 1:
        raise ConfigError(
            "a query may use at most one time granularity, but this one uses "
            f"{', '.join(granularities)}; the granularities are "
            f"{', '.join(TIME_GRANULARITIES)}, so keep one of them"
        )

    if len(validated) > MAX_GROUP_BY:
        raise ConfigError(
            f"grouping by {len(validated)} dimensions ({', '.join(validated)}) "
            f"exceeds the API maximum of {MAX_GROUP_BY}; drop "
            f"{len(validated) - MAX_GROUP_BY} of them"
        )

    return validated


def select_endpoint(group_by: Sequence[str]) -> str:
    """Pick the endpoint for a grouping: ``aggregate`` when there is one."""
    return "aggregate" if list(group_by) else "count"


def validate_limit(limit: int) -> int:
    """Check ``--limit`` against the API bounds.

    Raises:
        ConfigError: When outside ``1..100``, explaining the overflow bucket.
    """
    if limit < MIN_LIMIT or limit > MAX_LIMIT:
        raise ConfigError(
            f"--limit {limit} is outside the API bounds of {MIN_LIMIT} to "
            f"{MAX_LIMIT}; pick a value in that range, and note that groups past "
            f"the limit are not dropped, they roll into a single {OTHERS_LABEL!r} row"
        )
    return limit


def validate_timeout(timeout: float) -> float:
    """Check ``--timeout`` before it reaches the socket layer.

    ``argparse`` happily accepts ``0``, a negative number, ``nan`` and ``inf``
    (``1e400`` parses to ``inf``), each of which makes urllib3 raise deep inside
    the request. They are caught here instead, as a plain configuration error.

    Raises:
        ConfigError: When the value is not a finite number above zero.
    """
    value = float(timeout)
    if math.isnan(value) or math.isinf(value):
        raise ConfigError(
            f"--timeout {timeout!r} is not a finite number of seconds; pass a "
            f"real value such as --timeout {DEFAULT_TIMEOUT}"
        )
    if value <= 0:
        raise ConfigError(
            f"--timeout {value:g} must be greater than 0 seconds, since a "
            "zero or negative timeout can never allow a request to finish; "
            f"pass a value such as --timeout {DEFAULT_TIMEOUT}"
        )
    return value


def _bad_token_reason(token: str) -> str | None:
    """Describe why ``token`` cannot be an HTTP header value, or ``None``.

    The description never contains any part of the token itself: only its
    length, the offending position, and the class of character found there.
    """
    if token != token.strip(" "):
        side = "leading" if token[:1] == " " else "trailing"
        return f"a {side} space"
    for index, char in enumerate(token, start=1):
        code = ord(char)
        if char in "\r\n":
            name = "a carriage return" if char == "\r" else "a line feed"
            return f"{name} at position {index}"
        if code < 0x20 or code == 0x7F:
            return f"a control character (U+{code:04X}) at position {index}"
        if code > 0x7F:
            return f"a non-ASCII character (U+{code:04X}) at position {index}"
    return None


def validate_token(token: str) -> str:
    """Reject a credential that cannot safely become a header value.

    A token carrying a carriage return or line feed is a header injection
    vector, and the exception ``requests`` raises for one embeds the offending
    value, which would print the credential to stderr. Catching it here, before
    a request object exists, means that exception can never be raised.

    The error names the length and the character class only, never the value.

    Raises:
        ConfigError: When the token is empty or not printable ASCII.
    """
    if not token:
        raise ConfigError(
            "the access token is empty; pass --token or set VERCEL_TOKEN "
            f"(create one at {DOCS_TOKEN_URL})"
        )
    reason = _bad_token_reason(token)
    if reason is not None:
        raise ConfigError(
            f"the access token is not usable as an HTTP header value: the "
            f"{len(token)} character value contains {reason}. A Vercel token is "
            "printable ASCII with no spaces, so re-copy it (a stray newline from "
            f"a shell here-doc or a copy and paste is the usual cause; create a "
            f"fresh one at {DOCS_TOKEN_URL}). The token itself is not shown."
        )
    return token


# ---------------------------------------------------------------------------
# Request building
# ---------------------------------------------------------------------------


def build_request(
    *,
    dataset: str,
    project: str,
    since: datetime,
    until: datetime,
    group_by: Sequence[str] = (),
    limit: int | None = None,
    filter_expr: str | None = None,
    team: str | None = None,
    team_slug: str | None = None,
    token: str | None = None,
) -> PreparedRequest:
    """Build the GET that answers one query. Pure: it performs no I/O.

    The token, when supplied, goes into the ``Authorization`` header and
    nowhere else. ``limit`` is only meaningful on the aggregate endpoints, so it
    is dropped for count queries rather than silently sent and ignored.

    Args:
        dataset: ``visits`` or ``events``.
        project: Project id or project name.
        since: Start of the window, aware.
        until: End of the window, aware.
        group_by: Validated grouping; empty selects the count endpoint.
        limit: Maximum number of groups, aggregate only.
        filter_expr: A combined OData expression, or ``None``.
        team: Team id, mutually exclusive with ``team_slug``.
        team_slug: Team slug, sent as ``slug``.
        token: Access token for the ``Authorization`` header.

    Returns:
        The :class:`PreparedRequest` describing exactly one GET.
    """
    dimensions = list(group_by)
    endpoint = select_endpoint(dimensions)
    url = f"{BASE_URL}/{dataset}/{endpoint}"

    params: list[tuple[str, str]] = [("projectId", project)]
    for dimension in dimensions:
        params.append(("by", dimension))
    params.append(("since", to_api_timestamp(since)))
    params.append(("until", to_api_timestamp(until)))
    if endpoint == "aggregate" and limit is not None:
        params.append(("limit", str(limit)))
    if filter_expr:
        params.append(("filter", filter_expr))
    if team:
        params.append(("teamId", team))
    if team_slug:
        params.append(("slug", team_slug))

    headers = {
        "Accept": "application/json",
        "User-Agent": f"vercel-analytics-skill/{VERSION}",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    return PreparedRequest(method="GET", url=url, params=params, headers=headers)


def redact_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Copy headers with every credential replaced by a fixed placeholder.

    This is the only way headers are ever rendered, in dry runs, verbose
    diagnostics and error paths alike.
    """
    safe: dict[str, str] = {}
    for name, value in headers.items():
        if name.lower() in _SENSITIVE_HEADERS:
            safe[name] = REDACTED_BEARER if value.startswith("Bearer ") else REDACTED
        else:
            safe[name] = value
    return safe


def _credential_values(headers: Mapping[str, str]) -> list[str]:
    """Every secret string present in ``headers``, longest first.

    Both the whole header value and the bare bearer credential are returned, so
    a message that quotes either form is scrubbed. Longest first matters: it
    keeps ``Bearer <token>`` from being partially replaced.
    """
    values: set[str] = set()
    for name, value in headers.items():
        if name.lower() not in _SENSITIVE_HEADERS or not value:
            continue
        values.add(value)
        if value.startswith("Bearer "):
            bearer = value[len("Bearer ") :].strip()
            if bearer:
                values.add(bearer)
    return sorted(values, key=len, reverse=True)


def scrub_credentials(text: str, headers: Mapping[str, str]) -> str:
    """Replace every credential from ``headers`` with a fixed placeholder.

    :func:`redact_headers` protects headers that this module renders itself.
    This protects the other direction: text produced elsewhere, above all an
    exception message from ``requests``. ``InvalidHeader``, for one, embeds the
    offending header value verbatim, so any message on its way into an
    :class:`ApiError` goes through here first. Structuring it this way means a
    future exception type cannot reinstate the leak.
    """
    scrubbed = text
    for secret in _credential_values(headers):
        scrubbed = scrubbed.replace(secret, REDACTED)
    return scrubbed


def format_dry_run(request: PreparedRequest) -> str:
    """Render a request for ``--dry-run``: complete, readable, credential free."""
    safe_headers = redact_headers(request.headers)
    safe_headers.setdefault("Authorization", REDACTED_BEARER)

    lines: list[str] = [f"{request.method} {request.url}", "", "Query parameters:"]
    if request.params:
        width = max(len(name) for name, _ in request.params)
        for name, value in request.params:
            lines.append(f"  {name.ljust(width)}  {value}")
    else:
        lines.append("  (none)")

    lines.extend(["", "Headers:"])
    header_width = max(len(name) for name in safe_headers)
    for name in sorted(safe_headers):
        lines.append(f"  {name.ljust(header_width)}  {safe_headers[name]}")

    lines.extend(
        [
            "",
            "Encoded URL (never contains the token):",
            f"  {request.url}?{urlencode(request.params)}",
            "",
            "Nothing was sent. No credential is printed above.",
        ]
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


class ResponseLike(Protocol):
    """The slice of a response this module reads."""

    @property
    def status_code(self) -> int: ...

    @property
    def headers(self) -> Mapping[str, str]: ...

    @property
    def text(self) -> str: ...


class SessionLike(Protocol):
    """The single HTTP capability this module needs: an injectable GET."""

    def get(
        self,
        url: str,
        *,
        params: list[tuple[str, str]] | None = ...,
        headers: dict[str, str] | None = ...,
        timeout: float | None = ...,
    ) -> Any: ...


def _default_jitter() -> float:
    """Randomised padding added to a computed retry delay."""
    return random.uniform(0.0, 0.25)


def retry_delay(
    attempt: int,
    response: ResponseLike | None,
    body: Mapping[str, Any] | None,
    now: float,
) -> float:
    """Decide how long to wait before retry number ``attempt`` (0 based).

    Preference order: the ``Retry-After`` header, then ``error.limit.resetMs``,
    then ``error.limit.reset``, then exponential backoff from
    :data:`BACKOFF_BASE_SECONDS`, doubling each attempt. Any single wait is
    capped at :data:`MAX_SLEEP_SECONDS`. Jitter is added by :func:`execute` so
    that this function stays pure and testable.

    Args:
        attempt: Zero based index of the attempt that just failed.
        response: The failed response, or ``None`` for a network level failure.
        body: The parsed error envelope, when there was one.
        now: Current Unix time in seconds, injected for determinism.

    Returns:
        Seconds to sleep, never negative and never above the cap.
    """
    if response is not None:
        header = response.headers.get("Retry-After")
        seconds = _parse_retry_after(header, now)
        if seconds is not None and seconds > 0:
            return min(seconds, MAX_SLEEP_SECONDS)

    limit = _error_field(body, "limit")
    if isinstance(limit, Mapping):
        reset_ms = limit.get("resetMs")
        if isinstance(reset_ms, (int, float)) and not isinstance(reset_ms, bool):
            delay = float(reset_ms) / 1000.0 - now
            if delay > 0:
                return min(delay, MAX_SLEEP_SECONDS)
        reset = limit.get("reset")
        if isinstance(reset, (int, float)) and not isinstance(reset, bool):
            delay = float(reset) - now
            if delay > 0:
                return min(delay, MAX_SLEEP_SECONDS)

    backoff = BACKOFF_BASE_SECONDS * float(2**attempt)
    return min(backoff, MAX_SLEEP_SECONDS)


def _parse_retry_after(header: str | None, now: float) -> float | None:
    """Read a ``Retry-After`` header in either delay-seconds or HTTP-date form."""
    if not header:
        return None
    text = header.strip()
    try:
        return float(text)
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.timestamp() - now


def _error_field(body: Mapping[str, Any] | None, name: str) -> Any:
    """Read one field out of the ``{"error": {...}}`` envelope, defensively."""
    if not isinstance(body, Mapping):
        return None
    error = body.get("error")
    if not isinstance(error, Mapping):
        return None
    return error.get(name)


def _parse_body(text: str) -> dict[str, Any] | None:
    """Parse a response body, returning ``None`` when it is not a JSON object."""
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except ValueError:
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def _api_error(
    status: int,
    body: Mapping[str, Any] | None,
    text: str,
    attempts: int,
    scrub: Callable[[str], str],
) -> ApiError:
    """Build the exception for a failed response, keeping Vercel's wording."""
    code = _error_field(body, "code")
    message = _error_field(body, "message")
    code_text = code if isinstance(code, str) else None
    if isinstance(message, str) and message:
        message_text = message
    else:
        snippet = text.strip().replace("\n", " ")[:300]
        message_text = snippet or "the API returned no error message"
    message_text = scrub(message_text)
    if status == 429 or code_text == "rate_limited":
        limit = _error_field(body, "limit")
        return RateLimitError(
            status,
            code_text or "rate_limited",
            message_text,
            attempts=attempts,
            limit=limit if isinstance(limit, Mapping) else None,
        )
    return ApiError(status, code_text, message_text, attempts=attempts)


def _is_retryable(status: int) -> bool:
    """Retry 429 and any 5xx. Never any other 4xx."""
    return status in RETRYABLE_STATUSES or status >= 500


def execute(
    request: PreparedRequest,
    session: SessionLike,
    sleep: Callable[[float], None] = time.sleep,
    jitter: Callable[[], float] = _default_jitter,
    max_retries: int = DEFAULT_MAX_RETRIES,
    timeout: float = DEFAULT_TIMEOUT,
    *,
    now: Callable[[], float] = time.time,
    on_retry: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Perform the request, retrying only what is safe to retry.

    This is the one and only HTTP call site in the module, and it is a GET.
    ``sleep``, ``jitter`` and ``now`` are injected so retry behaviour is
    deterministic under test.

    Args:
        request: The prepared GET.
        session: Anything exposing a compatible ``get``.
        sleep: Blocking sleep, injected.
        jitter: Returns extra seconds to add to each delay, injected.
        max_retries: Retries after the first attempt; 0 disables retrying.
        timeout: Per attempt timeout in seconds.
        now: Returns current Unix time in seconds, injected.
        on_retry: Optional callback receiving a one line reason per retry.

    Returns:
        The parsed JSON response object.

    Raises:
        ApiError: On a non-retryable failure, or once retries are exhausted.
        RateLimitError: When the failure is a rate limit.
    """
    attempts = max(0, max_retries) + 1

    def safe(text: str) -> str:
        """Every string that reaches an ApiError from here passes through this."""
        return scrub_credentials(text, request.headers)

    for attempt in range(attempts):
        is_last = attempt == attempts - 1
        response: Any = None
        try:
            response = session.get(
                request.url,
                params=request.params,
                headers=request.headers,
                timeout=timeout,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            reason = safe(f"{type(exc).__name__}: {exc}")
            if is_last:
                raise ApiError(
                    None,
                    "network_error",
                    f"could not reach {request.url}: {reason}",
                    attempts=attempts,
                ) from exc
            delay = _delay_with_jitter(retry_delay(attempt, None, None, now()), jitter)
            if on_retry:
                on_retry(f"{reason}; retrying in {delay:.2f}s")
            sleep(delay)
            continue
        except requests.RequestException as exc:
            raise ApiError(
                None,
                "request_failed",
                safe(f"request to {request.url} failed: {type(exc).__name__}: {exc}"),
                attempts=attempt + 1,
            ) from exc

        status = int(response.status_code)
        text = str(response.text)
        body = _parse_body(text)

        if 200 <= status < 300:
            if body is None:
                raise ApiError(
                    status,
                    "invalid_response",
                    safe("the response was not a JSON object"),
                    attempts=attempt + 1,
                )
            return body

        if _is_retryable(status) and not is_last:
            delay = _delay_with_jitter(
                retry_delay(attempt, response, body, now()), jitter
            )
            if on_retry:
                on_retry(f"HTTP {status}; retrying in {delay:.2f}s")
            sleep(delay)
            continue

        raise _api_error(
            status,
            body,
            text,
            attempt + 1 if not is_last else attempts,
            safe,
        )

    raise ApiError(None, "no_attempt", "no request was attempted", attempts=attempts)


def _delay_with_jitter(delay: float, jitter: Callable[[], float]) -> float:
    """Add injected jitter to a delay and keep it inside the sleep cap."""
    return max(0.0, min(delay + jitter(), MAX_SLEEP_SECONDS))


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def _stringify(value: Any) -> str:
    """Render a group label value that may be a string, number, bool or null."""
    if value is None:
        return "(none)"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value or "(empty)"
    return str(value)


def _is_number(value: Any) -> TypeGuard[float]:
    """True for a real JSON number. Booleans are not numbers for our purposes."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def normalize(
    payload: Mapping[str, Any],
    dataset: str,
    group_by: Sequence[str],
    *,
    status: int = 200,
) -> Result:
    """Turn a raw response into a :class:`Result`.

    Parsing is deliberately permissive. The published JSON Schema marks roughly
    300 row fields as required, which is a generation artifact of a shared
    internal row type rather than a description of real responses, so this
    reads the metric keys it knows, treats the remaining string valued key as
    the group label, and requires nothing else.

    Grouping by a JSON dimension is the one trap that needs care: asking for
    ``eventData/plan`` returns rows keyed ``eventData``, and ``flags/x`` returns
    rows keyed ``flags``, so the base key is mapped back onto the dimension the
    caller actually asked for. That remap runs for every grouped dimension, so
    a two dimension grouping keeps both labels.

    Only the top level shape is strict. Which endpoint answered is decided by
    the requested grouping alone, never by the shape that came back, so a body
    that does not match its endpoint is an error rather than something quietly
    reinterpreted as a different kind of result.

    Args:
        payload: The decoded response body.
        dataset: ``visits`` or ``events``, which decides the metric names.
        group_by: The grouping that was requested.
        status: The HTTP status the body arrived with, used in the error when
            the shape is wrong. Only 2xx bodies ever reach this function.

    Returns:
        A :class:`Result` ready to format.

    Raises:
        ApiError: When ``data`` is not the shape the chosen endpoint must
            return: a mapping for count, a list of rows for aggregate.
    """
    dimensions = list(group_by)
    query = payload.get("query")
    query_block: dict[str, Any] = dict(query) if isinstance(query, Mapping) else {}
    data = payload.get("data")

    preferred = DATASET_METRICS.get(dataset, DATASET_METRICS["visits"])
    label_dimensions = [dim for dim in dimensions if dim not in TIME_GRANULARITIES]

    if select_endpoint(dimensions) == "count":
        if not isinstance(data, Mapping):
            raise ApiError(status, "invalid_response", _shape_error("count", data))
        metrics, names = _extract_metrics(data, preferred, skip=set())
        return Result(
            rows=[Row(metrics=metrics)],
            is_count=True,
            dataset=dataset,
            group_by=dimensions,
            query=query_block,
            metric_names=names,
        )

    if not isinstance(data, list):
        raise ApiError(status, "invalid_response", _shape_error("aggregate", data))

    rows: list[Row] = []
    metric_names: list[str] = []
    for entry in data:
        if not isinstance(entry, Mapping):
            continue
        row, names = _normalize_row(entry, preferred, label_dimensions)
        rows.append(row)
        for name in names:
            if name not in metric_names:
                metric_names.append(name)

    if not metric_names:
        metric_names = list(preferred)

    return Result(
        rows=rows,
        is_count=False,
        dataset=dataset,
        group_by=dimensions,
        query=query_block,
        metric_names=metric_names,
    )


def _shape_error(endpoint: str, data: Any) -> str:
    """Describe a top level ``data`` that is not what the endpoint must return.

    Only the shape is named, never the content, so nothing from the response
    body is echoed back out.
    """
    expected = (
        "a JSON object of metrics"
        if endpoint == "count"
        else "a JSON array of grouped rows"
    )
    if data is None:
        found = "it was missing or null"
    else:
        found = f"it was a {type(data).__name__}"
    return (
        f"the {endpoint} response should carry {expected} under 'data', but "
        f"{found}; the request succeeded, so this is a response the client "
        "cannot interpret rather than an empty result"
    )


def _fallback_label_key(entry: Mapping[str, Any], consumed: set[str]) -> str | None:
    """The first unclaimed string valued field that is not a metric.

    Defensive only: it labels a row whose grouping key came back under a name
    this client did not ask for, which the docs warn can happen.
    """
    for name, value in entry.items():
        if name == "timestamp" or name in KNOWN_METRICS or name in consumed:
            continue
        if isinstance(value, str):
            return name
    return None


def _normalize_row(
    entry: Mapping[str, Any],
    preferred: Sequence[str],
    label_dimensions: Sequence[str],
) -> tuple[Row, list[str]]:
    """Turn one raw row into a :class:`Row` plus the metric names it carried.

    One label cell is produced per grouped dimension. Each dimension claims the
    field named after it, or after its JSON base (``eventData/plan`` arrives as
    ``eventData``); whatever is still unlabelled afterwards falls back to any
    remaining string field, so nothing is silently dropped.
    """
    raw_timestamp = entry.get("timestamp")
    timestamp = raw_timestamp if isinstance(raw_timestamp, str) else None

    consumed: set[str] = set()
    claimed: list[str | None] = []
    for dimension in label_dimensions:
        chosen: str | None = None
        for candidate in (dimension, dimension.split("/", 1)[0]):
            if candidate in entry and candidate not in consumed:
                chosen = candidate
                break
        if chosen is not None:
            consumed.add(chosen)
        claimed.append(chosen)

    for index, chosen in enumerate(claimed):
        if chosen is not None:
            continue
        fallback = _fallback_label_key(entry, consumed)
        if fallback is not None:
            consumed.add(fallback)
        claimed[index] = fallback

    labels = tuple(
        _stringify(entry[name]) if name is not None else None for name in claimed
    )

    metrics, names = _extract_metrics(entry, preferred, skip={"timestamp"} | consumed)
    is_others = OTHERS_LABEL in labels or timestamp == OTHERS_LABEL
    return (
        Row(labels=labels, metrics=metrics, timestamp=timestamp, is_others=is_others),
        names,
    )


def _extract_metrics(
    entry: Mapping[str, Any],
    preferred: Sequence[str],
    skip: set[str],
) -> tuple[dict[str, float], list[str]]:
    """Pull numeric metrics out of a row, known names first, extras after."""
    metrics: dict[str, float] = {}
    names: list[str] = []
    for name in preferred:
        value = entry.get(name)
        if _is_number(value):
            metrics[name] = value
            names.append(name)
    for name, value in entry.items():
        if name in skip or name in metrics or not _is_number(value):
            continue
        metrics[name] = value
        names.append(name)
    return metrics, names


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Style:
    """How output is decorated: colour, and whether non-ASCII glyphs are safe."""

    color: bool = False
    unicode: bool = True

    def bold(self, text: str) -> str:
        return f"\033[1m{text}\033[0m" if self.color else text

    def dim(self, text: str) -> str:
        return f"\033[2m{text}\033[0m" if self.color else text

    def accent(self, text: str) -> str:
        return f"\033[36m{text}\033[0m" if self.color else text

    @property
    def ellipsis(self) -> str:
        return "…" if self.unicode else "..."

    @property
    def bar(self) -> str:
        return "█" if self.unicode else "#"


PLAIN_STYLE = Style()


def _format_number(value: float) -> str:
    """Thousands separated, with decimals only when the value really has them."""
    if isinstance(value, int) or float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.2f}"


def _truncate(text: str, width: int, style: Style) -> str:
    """Shorten a label to ``width`` characters, marking the cut."""
    if width <= 0 or len(text) <= width:
        return text
    marker = style.ellipsis
    if width <= len(marker):
        return text[:width]
    return text[: width - len(marker)] + marker


def _pad(text: str, width: int, align: str) -> str:
    return text.rjust(width) if align == "right" else text.ljust(width)


def _render_grid(
    headers: Sequence[str],
    aligns: Sequence[str],
    body: Sequence[Sequence[str]],
    footer: Sequence[str] | None,
    style: Style,
) -> list[str]:
    """Lay out an aligned text grid with a rule under the head and the footer."""
    widths = [len(head) for head in headers]
    for row in list(body) + ([list(footer)] if footer else []):
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    def line(cells: Sequence[str]) -> str:
        return "  ".join(
            _pad(cell, widths[index], aligns[index]) for index, cell in enumerate(cells)
        ).rstrip()

    rule = "  ".join("-" * width for width in widths)
    lines = [style.bold(line(headers)), style.dim(rule)]
    lines.extend(line(row) for row in body)
    if footer:
        lines.append(style.dim(rule))
        lines.append(style.bold(line(footer)))
    return lines


def _label_headers(result: Result, has_time: bool) -> list[str]:
    """One column heading per grouped dimension, named as it was requested.

    A grouping with no non-time dimension needs no label column at all when the
    timestamp already identifies the row; without a timestamp column there is
    still one generic column so the rows are not left anonymous.
    """
    dimensions = result.group_dimensions
    if dimensions:
        return list(dimensions)
    return [] if has_time else ["group"]


def _label_cells(row: Row, count: int) -> list[str]:
    """The label cells for one row, padded to ``count`` columns.

    A missing label reads as ``(none)``, except on the overflow bucket, which
    always says so: it must never render as a blank cell.
    """
    cells: list[str] = []
    for index in range(count):
        label = row.labels[index] if index < len(row.labels) else None
        if label is None:
            label = OTHERS_LABEL if row.is_others else "(none)"
        cells.append(label)
    return cells


def _range_line(time_range: tuple[datetime, datetime]) -> str:
    since, until = time_range
    return f"Range: {to_api_timestamp(since)} to {to_api_timestamp(until)} (UTC)"


def format_table(
    result: Result,
    *,
    time_range: tuple[datetime, datetime] | None = None,
    filter_expr: str | None = None,
    limit: int | None = None,
    style: Style = PLAIN_STYLE,
    max_label_width: int = 48,
    title: str | None = None,
    show_context: bool = True,
) -> str:
    """Render a result as aligned text.

    Grouped results get one row per group, metric columns right aligned with
    thousands separators, a share of total column for the primary metric, and a
    totals row. Count results get a small labelled block instead, since there is
    nothing to group. An ``Others`` row is annotated below the table so it reads
    as the limit overflow bucket rather than a real group value.

    Args:
        result: The parsed result.
        time_range: The resolved window, shown as context.
        filter_expr: The active OData filter, shown as context.
        limit: The limit that was sent, used in the ``Others`` note.
        style: Colour and glyph settings.
        max_label_width: Longer labels are truncated with an ellipsis.
        title: Optional heading, used by the overview report.
        show_context: Print the range and filter lines above the table.

    Returns:
        The rendered block, without a trailing newline.
    """
    lines: list[str] = []
    if title:
        lines.append(style.bold(title))
    if show_context:
        if time_range:
            lines.append(style.dim(_range_line(time_range)))
        if filter_expr:
            lines.append(style.dim(f"Filter: {filter_expr}"))
        if lines:
            lines.append("")

    if result.is_count:
        lines.extend(_format_count_block(result, style))
        return "\n".join(lines)

    totals = result.totals()
    primary = result.primary_metric
    primary_total = totals.get(primary, 0)

    granularity = result.granularity
    has_time = granularity is not None and any(row.timestamp for row in result.rows)
    label_headers = _label_headers(result, has_time)

    headers: list[str] = []
    aligns: list[str] = []
    if has_time:
        headers.append(granularity or "time")
        aligns.append("left")
    headers.extend(label_headers)
    aligns.extend("left" for _ in label_headers)
    for name in result.metric_names:
        headers.append(name)
        aligns.append("right")
    headers.append(f"% {primary}")
    aligns.append("right")

    body: list[list[str]] = []
    has_others = any(row.is_others for row in result.rows)
    for row in result.rows:
        cells: list[str] = []
        if has_time:
            cells.append(format_timestamp(row.timestamp or "", granularity))
        cells.extend(
            _truncate(label, max_label_width, style)
            for label in _label_cells(row, len(label_headers))
        )
        for name in result.metric_names:
            cells.append(_format_number(row.metrics.get(name, 0)))
        share = (row.metrics.get(primary, 0) / primary_total * 100) if primary_total else 0.0
        cells.append(f"{share:.1f}%")
        body.append(cells)

    footer: list[str] = ["TOTAL"]
    footer.extend("" for _ in range(len(label_headers) + (1 if has_time else 0) - 1))
    for name in result.metric_names:
        footer.append(_format_number(totals.get(name, 0)))
    footer.append("100.0%" if primary_total else "0.0%")

    lines.extend(_render_grid(headers, aligns, body, footer, style))

    if has_others:
        bound = f"--limit {limit}" if limit is not None else "the limit"
        lines.append("")
        lines.append(
            style.dim(
                f"{OTHERS_LABEL} is not a real value: it is every group beyond "
                f"{bound}, collapsed by the API into one bucket."
            )
        )
    return "\n".join(lines)


def _format_count_block(result: Result, style: Style) -> list[str]:
    """Render an ungrouped count as a small labelled block."""
    row = result.rows[0] if result.rows else Row()
    names = result.metric_names or list(DATASET_METRICS[result.dataset])
    width = max(len(name) for name in names)
    values = [_format_number(row.metrics.get(name, 0)) for name in names]
    value_width = max(len(value) for value in values)
    return [
        f"  {name.ljust(width)}  {value.rjust(value_width)}"
        for name, value in zip(names, values)
    ]


def _result_document(
    result: Result,
    payload: Mapping[str, Any] | None,
    time_range: tuple[datetime, datetime] | None,
) -> dict[str, Any]:
    """Build the JSON document for one result."""
    document: dict[str, Any] = {
        "query": result.query,
        "range": (
            {
                "since": to_api_timestamp(time_range[0]),
                "until": to_api_timestamp(time_range[1]),
            }
            if time_range
            else None
        ),
        "dataset": result.dataset,
        "groupBy": result.group_by,
        "isCount": result.is_count,
        "metrics": result.metric_names,
        "rows": [
            {
                "key": row.key,
                "groups": dict(zip(result.group_dimensions, row.labels)),
                "timestamp": row.timestamp,
                "metrics": row.metrics,
            }
            for row in result.rows
        ],
        "totals": result.totals(),
    }
    document["raw"] = payload
    return document


def format_json(
    result: Result,
    payload: Mapping[str, Any] | None = None,
    *,
    time_range: tuple[datetime, datetime] | None = None,
) -> str:
    """Render a result as JSON, with the untouched API payload under ``raw``."""
    return json.dumps(_result_document(result, payload, time_range), indent=2)


def format_csv(result: Result) -> str:
    """Render a result as CSV, quoted by :mod:`csv` so labels stay safe."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    names = result.metric_names

    if result.is_count:
        writer.writerow(names)
        row = result.rows[0] if result.rows else Row()
        writer.writerow([row.metrics.get(name, 0) for name in names])
        return buffer.getvalue()

    granularity = result.granularity
    has_time = granularity is not None and any(row.timestamp for row in result.rows)
    label_headers = _label_headers(result, has_time)

    header: list[str] = []
    if has_time:
        header.append(granularity or "time")
    header.extend(label_headers)
    header.extend(names)
    writer.writerow(header)

    for row in result.rows:
        cells: list[Any] = []
        if has_time:
            cells.append(format_timestamp(row.timestamp or "", granularity))
        cells.extend(_label_cells(row, len(label_headers)))
        cells.extend(row.metrics.get(name, 0) for name in names)
        writer.writerow(cells)
    return buffer.getvalue()


def _sparkline_rows(result: Result, style: Style, width: int = 24) -> list[str]:
    """A compact per bucket breakdown for the overview report."""
    primary = result.primary_metric
    values = [row.metrics.get(primary, 0) for row in result.rows]
    peak = max(values) if values else 0
    label_width = max(
        (len(format_timestamp(row.timestamp or "", result.granularity))
         for row in result.rows),
        default=0,
    )
    value_width = max((len(_format_number(value)) for value in values), default=0)
    lines: list[str] = []
    for row, value in zip(result.rows, values):
        label = format_timestamp(row.timestamp or "", result.granularity)
        filled = round((value / peak) * width) if peak else 0
        bar = style.bar * filled
        lines.append(
            f"  {label.ljust(label_width)}  {_format_number(value).rjust(value_width)}"
            f"  {style.accent(bar)}"
        )
    return lines


def render_overview(
    results: Sequence[Result],
    *,
    project: str,
    time_range: tuple[datetime, datetime],
    filter_expr: str | None = None,
    limit: int = OVERVIEW_TABLE_LIMIT,
    style: Style = PLAIN_STYLE,
) -> str:
    """Compose the three overview results into one immediately useful report.

    Args:
        results: The daily result, the top pages result and the top referrers
            result, in that order.
        project: Project id or name, shown in the heading.
        time_range: The resolved window.
        filter_expr: The active OData filter, if any.
        limit: The row limit used for the two tables.
        style: Colour and glyph settings.

    Returns:
        The rendered report, without a trailing newline.
    """
    daily, pages, referrers = results[0], results[1], results[2]

    lines = [
        style.bold(f"Vercel Web Analytics: {project}"),
        style.dim(_range_line(time_range)),
    ]
    if filter_expr:
        lines.append(style.dim(f"Filter: {filter_expr}"))
    lines.append("")

    totals = daily.totals()
    names = daily.metric_names or list(DATASET_METRICS[daily.dataset])
    width = max(len(name) for name in names)
    values = [_format_number(totals.get(name, 0)) for name in names]
    value_width = max(len(value) for value in values)
    for name, value in zip(names, values):
        lines.append(f"  {style.bold(name.ljust(width))}  {value.rjust(value_width)}")
    if "visitors" in names:
        lines.append(
            style.dim(
                "  visitors is a sum of the buckets below, so someone who came on "
                "two days counts twice;"
            )
        )
        lines.append(
            style.dim("  run the total preset for distinct visitors over the window")
        )

    lines.append("")
    lines.append(style.bold(f"By {daily.granularity or 'day'}"))
    if daily.rows:
        lines.extend(_sparkline_rows(daily, style))
    else:
        lines.append(style.dim("  no data in this window"))

    for title, result in (("Top pages", pages), ("Top referrers", referrers)):
        lines.append("")
        if result.rows:
            lines.append(
                format_table(
                    result,
                    limit=limit,
                    style=style,
                    title=f"{title} (top {limit})",
                    show_context=False,
                    max_label_width=56,
                )
            )
        else:
            lines.append(style.bold(title))
            lines.append(style.dim("  no data in this window"))

    return "\n".join(lines)


def format_presets(style: Style = PLAIN_STYLE) -> str:
    """Render the preset table for ``--list-presets``."""
    headers = ["preset", "dataset", "endpoint", "grouping", "limit", "what it shows"]
    aligns = ["left", "left", "left", "left", "right", "left"]
    body: list[list[str]] = []
    for preset in PRESETS.values():
        name = preset.name + (" (default)" if preset.name == DEFAULT_PRESET else "")
        grouping = ", ".join(preset.group_by) if preset.group_by else "none"
        if preset.name == "overview":
            grouping = "day, requestPath, referrerHostname"
        if preset.name == "events":
            grouping = "eventName [+ eventData/<property>]"
        body.append(
            [
                name,
                preset.dataset,
                preset.endpoint,
                grouping,
                str(preset.limit) if preset.limit is not None else "n/a",
                preset.description,
            ]
        )
    lines = [style.bold("Presets"), ""]
    lines.extend(_render_grid(headers, aligns, body, None, style))
    lines.append("")
    lines.append(
        style.dim(
            "Any explicit flag overrides a preset value. Groups beyond the limit "
            f"roll into a single {OTHERS_LABEL!r} row rather than being dropped."
        )
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

EPILOG = """\
examples:
  # Last 7 days at a glance for the configured project
  vercel_analytics.py

  # Top 20 pages over the last 30 days, US traffic only
  vercel_analytics.py top-pages --limit 20 --since 30d --country US

  # Daily page view trend for one framework route, as CSV
  vercel_analytics.py trend --route '/blog/[slug]' --since 4w --csv

  # Custom events broken down by the "plan" event property
  vercel_analytics.py events --event-property plan --since 30d --json

  # Show exactly what would be requested, and send nothing
  vercel_analytics.py referrers --since 2026-01-01 --until 2026-02-01 --dry-run

environment:
  VERCEL_TOKEN       access token, used only in the Authorization header
  VERCEL_PROJECT_ID  project id or project name
  VERCEL_TEAM_ID     team id, for team owned projects
  VERCEL_TEAM_SLUG   team slug, an alternative to the team id
  NO_COLOR           set to any value to disable colour

exit codes:
  0 success, including an empty result set
  1 the API returned an error, or the network failed after retries
  2 configuration or usage error
  130 interrupted
"""


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser. The help text doubles as the reference docs."""
    parser = argparse.ArgumentParser(
        prog="vercel_analytics.py",
        description=(
            "Query the Vercel Web Analytics API from the command line. "
            "Read only: every request is a GET, and the access token is sent "
            "only in the Authorization header."
        ),
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "preset",
        nargs="?",
        choices=sorted(PRESETS),
        default=None,
        help=(
            f"what to report; defaults to {DEFAULT_PRESET}. "
            "Run --list-presets for the full table"
        ),
    )

    config = parser.add_argument_group("configuration")
    config.add_argument(
        "--token",
        metavar="TOKEN",
        help="Vercel access token; defaults to $VERCEL_TOKEN. Not needed for --dry-run",
    )
    config.add_argument(
        "--project",
        metavar="ID_OR_NAME",
        help="project id or project name; defaults to $VERCEL_PROJECT_ID",
    )
    config.add_argument(
        "--team",
        metavar="TEAM_ID",
        help="team id for a team owned project; defaults to $VERCEL_TEAM_ID",
    )
    config.add_argument(
        "--team-slug",
        metavar="SLUG",
        help="team slug instead of a team id; defaults to $VERCEL_TEAM_SLUG",
    )

    shape = parser.add_argument_group("query shape")
    shape.add_argument(
        "--dataset",
        choices=DATASETS,
        default=None,
        help="which dataset to query; the preset picks one by default",
    )
    shape.add_argument(
        "--group-by",
        "--dimension",
        dest="group_by",
        metavar="DIMENSION",
        action="append",
        help=(
            "group rows by a dimension; repeatable up to 2. Visits accept: "
            + ", ".join(VISIT_DIMENSIONS)
            + ". Events also accept eventName and eventData/<property>. "
            "flags/<name> works on both"
        ),
    )
    shape.add_argument(
        "--granularity",
        choices=TIME_GRANULARITIES,
        default=None,
        help="add a time bucket to the grouping, replacing the preset's bucket",
    )
    shape.add_argument(
        "--since",
        metavar="WHEN",
        default=DEFAULT_SINCE,
        help=f"start of the window (default: {DEFAULT_SINCE}); {TIME_HELP}",
    )
    shape.add_argument(
        "--until",
        metavar="WHEN",
        default=DEFAULT_UNTIL,
        help=f"end of the window (default: {DEFAULT_UNTIL}); same forms as --since",
    )
    shape.add_argument(
        "--limit",
        metavar="N",
        type=int,
        default=None,
        help=(
            f"maximum number of groups, {MIN_LIMIT} to {MAX_LIMIT} "
            f"(preset default, usually {DEFAULT_LIMIT}); the rest roll into "
            f"one {OTHERS_LABEL!r} row"
        ),
    )
    shape.add_argument(
        "--event-property",
        metavar="NAME",
        default=None,
        help="break custom events down by this event property (events dataset)",
    )

    filters = parser.add_argument_group(
        "filters",
        "Each flag adds one OData clause; all clauses are joined with 'and'. "
        "A comma separated value becomes an 'in (...)' set.",
    )
    filters.add_argument("--path", metavar="PATH", help="requestPath, exact URL path")
    filters.add_argument("--route", metavar="ROUTE", help="route, framework pattern")
    filters.add_argument("--country", metavar="CODE", help="country, ISO code")
    filters.add_argument("--device", metavar="TYPE", help="deviceType")
    filters.add_argument("--browser", metavar="NAME", help="browserName")
    filters.add_argument("--os", metavar="NAME", dest="os_name", help="osName")
    filters.add_argument("--referrer", metavar="HOST", help="referrerHostname")
    filters.add_argument("--utm-source", metavar="VALUE", help="utmSource")
    filters.add_argument("--utm-medium", metavar="VALUE", help="utmMedium")
    filters.add_argument("--utm-campaign", metavar="VALUE", help="utmCampaign")
    filters.add_argument(
        "--event-name", metavar="NAME", help="eventName (events dataset only)"
    )
    filters.add_argument(
        "--flag",
        metavar="NAME=VALUE",
        action="append",
        help="feature flag clause, for example --flag beta_banner=true; repeatable",
    )
    filters.add_argument(
        "--environment",
        choices=("production", "preview"),
        default=None,
        help="environment; aggregate queries default to production",
    )
    filters.add_argument(
        "--filter",
        metavar="ODATA",
        action="append",
        dest="raw_filters",
        help="raw OData clause, appended verbatim; repeatable",
    )

    output = parser.add_argument_group("output and behaviour")
    output.add_argument(
        "--json", action="store_true", help="machine readable JSON output"
    )
    output.add_argument("--csv", action="store_true", help="CSV output")
    output.add_argument(
        "--dry-run",
        action="store_true",
        help="print the request that would be sent and send nothing; needs no token",
    )
    output.add_argument(
        "--timeout",
        metavar="SECONDS",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"per request timeout (default: {DEFAULT_TIMEOUT})",
    )
    output.add_argument(
        "--max-retries",
        metavar="N",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        help=(
            f"retries after the first attempt (default: {DEFAULT_MAX_RETRIES}); "
            "only 429 and 5xx responses and network failures are retried"
        ),
    )
    output.add_argument(
        "--no-color", action="store_true", help="disable colour; NO_COLOR works too"
    )
    output.add_argument(
        "--verbose", action="store_true", help="diagnostics on stderr, never the token"
    )
    output.add_argument(
        "--list-presets", action="store_true", help="print the preset table and exit"
    )
    output.add_argument(
        "--version", action="store_true", help="print the version and exit"
    )
    return parser


@dataclass
class Settings:
    """Everything one run needs, after flags, env and preset have been merged."""

    preset: Preset
    dataset: str
    project: str
    token: str | None
    team: str | None
    team_slug: str | None
    group_by: list[str]
    limit: int | None
    filter_expr: str | None
    time_range: tuple[datetime, datetime]
    timeout: float = DEFAULT_TIMEOUT
    warnings: list[str] = field(default_factory=list)


def _env_value(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name)
    return value.strip() or None if value else None


def _resolve_filters(args: argparse.Namespace, dataset: str) -> str | None:
    """Turn every filter flag into one combined OData expression."""
    pairs: list[tuple[str, str | None]] = [
        ("requestPath", args.path),
        ("route", args.route),
        ("country", args.country),
        ("deviceType", args.device),
        ("browserName", args.browser),
        ("osName", args.os_name),
        ("referrerHostname", args.referrer),
        ("utmSource", args.utm_source),
        ("utmMedium", args.utm_medium),
        ("utmCampaign", args.utm_campaign),
        ("environment", args.environment),
    ]

    clauses: list[str] = []
    for dimension, value in pairs:
        if value:
            clauses.append(build_clause(dimension, value))

    if args.event_name:
        if dataset != "events":
            raise ConfigError(
                f"--event-name {args.event_name!r} only exists on the events "
                "dataset; add --dataset events (or use the events preset)"
            )
        clauses.append(build_clause("eventName", args.event_name))

    for raw_flag in args.flag or []:
        name, separator, value = str(raw_flag).partition("=")
        if not separator or not name.strip():
            raise ConfigError(
                f"--flag {raw_flag!r} is not in NAME=VALUE form; write it as "
                "--flag beta_banner=true"
            )
        clauses.append(build_clause(json_dimension("flags", name), value.strip()))

    for raw in args.raw_filters or []:
        text = str(raw).strip()
        if text:
            clauses.append(text)

    return combine_filters(clauses)


def _resolve_group_by(args: argparse.Namespace, preset: Preset) -> list[str]:
    """Merge the preset grouping with --group-by, --granularity and the sugar."""
    explicit = [dim for dim in (args.group_by or []) if dim]
    if explicit:
        group_by = list(explicit)
    else:
        group_by = list(preset.group_by)

    if args.granularity:
        if not explicit:
            group_by = [dim for dim in group_by if dim not in TIME_GRANULARITIES]
        group_by.append(args.granularity)

    if args.event_property:
        group_by.append(json_dimension("eventData", args.event_property))

    return group_by


def _resolve_settings(args: argparse.Namespace, env: Mapping[str, str]) -> Settings:
    """Apply every validation rule, in order, before anything touches the network."""
    preset = PRESETS[args.preset or DEFAULT_PRESET]

    if args.json and args.csv:
        raise ConfigError(
            "--json and --csv are mutually exclusive; pick one output format"
        )

    dataset = args.dataset or preset.dataset

    project = args.project or _env_value(env, "VERCEL_PROJECT_ID")
    if not project:
        raise ConfigError(
            "no project configured; pass --project with a project id or name, "
            "or set VERCEL_PROJECT_ID in the environment"
        )

    token = args.token or _env_value(env, "VERCEL_TOKEN")
    if not token and not args.dry_run:
        raise ConfigError(
            "no access token configured; pass --token or set VERCEL_TOKEN "
            f"(create one at {DOCS_TOKEN_URL}). Use --dry-run to build the "
            "request without a token"
        )
    if token:
        token = validate_token(token)

    timeout = validate_timeout(args.timeout)

    team = args.team or _env_value(env, "VERCEL_TEAM_ID")
    team_slug = args.team_slug or _env_value(env, "VERCEL_TEAM_SLUG")
    if team and team_slug:
        raise ConfigError(
            f"--team ({team}) and --team-slug ({team_slug}) are mutually "
            "exclusive; keep one of them, and check VERCEL_TEAM_ID and "
            "VERCEL_TEAM_SLUG in case the environment supplies the other"
        )

    if preset.name == "overview" and (args.group_by or args.event_property):
        raise ConfigError(
            "the overview preset issues its own three queries, so --group-by and "
            "--event-property have no meaning there; use trend, top-pages, "
            "referrers or another preset to control the grouping"
        )

    if preset.name == "overview" and args.csv:
        raise ConfigError(
            "--csv needs a single table, but the overview preset issues three "
            "queries; use trend, top-pages or referrers with --csv instead"
        )

    group_by = validate_group_by(_resolve_group_by(args, preset), dataset)

    limit = args.limit if args.limit is not None else preset.limit
    if limit is not None:
        limit = validate_limit(limit)

    if args.environment == "preview" and select_endpoint(group_by) == "count":
        raise ConfigError(
            "--environment preview cannot be used with a count query: the count "
            "endpoints report production traffic only. Add --group-by day (or "
            "any other dimension) so the aggregate endpoint is used instead"
        )

    filter_expr = _resolve_filters(args, dataset)

    now = datetime.now(timezone.utc)
    time_range = resolve_range(args.since, args.until, now)

    warnings: list[str] = []
    warning = reporting_window_warning(time_range[0], now)
    if warning:
        warnings.append(warning)

    return Settings(
        preset=preset,
        dataset=dataset,
        project=project,
        token=token,
        team=team,
        team_slug=team_slug,
        group_by=group_by,
        limit=limit,
        filter_expr=filter_expr,
        time_range=time_range,
        timeout=timeout,
        warnings=warnings,
    )


def _plan_requests(settings: Settings, args: argparse.Namespace) -> list[PreparedRequest]:
    """Build every request a run needs: one, or three for the overview."""
    common: dict[str, Any] = {
        "dataset": settings.dataset,
        "project": settings.project,
        "since": settings.time_range[0],
        "until": settings.time_range[1],
        "filter_expr": settings.filter_expr,
        "team": settings.team,
        "team_slug": settings.team_slug,
        "token": settings.token,
    }

    if settings.preset.name != "overview":
        return [
            build_request(group_by=settings.group_by, limit=settings.limit, **common)
        ]

    table_limit = settings.limit if settings.limit is not None else OVERVIEW_TABLE_LIMIT
    granularity = args.granularity or "day"
    return [
        build_request(group_by=[granularity], limit=MAX_LIMIT, **common),
        build_request(group_by=["requestPath"], limit=table_limit, **common),
        build_request(group_by=["referrerHostname"], limit=table_limit, **common),
    ]


def _is_empty(result: Result) -> bool:
    """True when there is nothing worth tabulating: no rows, or a zero count."""
    if not result.rows:
        return True
    if result.is_count:
        return not any(value for value in result.rows[0].metrics.values())
    return False


def _empty_message(settings: Settings, group_by: Sequence[str]) -> str:
    """The single line printed instead of an empty table."""
    since, until = settings.time_range
    grouping = f"grouped by {', '.join(group_by)}" if group_by else "ungrouped"
    filter_text = settings.filter_expr or "no filter"
    return (
        f"No {settings.dataset} data for project {settings.project} "
        f"({grouping}) between {to_api_timestamp(since)} and "
        f"{to_api_timestamp(until)} with {filter_text}. "
        "Try a wider --since, or relax the filter."
    )


def _run(
    args: argparse.Namespace,
    env: Mapping[str, str],
    out: TextIO,
    err: TextIO,
) -> int:
    """Resolve settings, issue the request or requests, and print the report."""
    style = _resolve_style(args, env, out)

    if args.version:
        print(f"vercel-analytics {VERSION}", file=out)
        return 0
    if args.list_presets:
        print(format_presets(style), file=out)
        return 0

    settings = _resolve_settings(args, env)
    for warning in settings.warnings:
        print(f"warning: {warning}", file=err)

    requests_to_send = _plan_requests(settings, args)

    if args.dry_run:
        for index, prepared in enumerate(requests_to_send):
            if index:
                print(file=out)
            print(format_dry_run(prepared), file=out)
        return 0

    if args.verbose:
        for prepared in requests_to_send:
            print(f"verbose: GET {prepared.url}", file=err)
            print(f"verbose: params {prepared.params}", file=err)
            print(f"verbose: headers {redact_headers(prepared.headers)}", file=err)

    def on_retry(reason: str) -> None:
        if args.verbose:
            print(f"verbose: {reason}", file=err)

    payloads: list[dict[str, Any]] = []
    session = requests.Session()
    try:
        for prepared in requests_to_send:
            payloads.append(
                execute(
                    prepared,
                    session,
                    max_retries=args.max_retries,
                    timeout=settings.timeout,
                    on_retry=on_retry,
                )
            )
    finally:
        session.close()

    if settings.preset.name == "overview":
        return _emit_overview(settings, args, payloads, style, out)
    return _emit_single(settings, args, payloads[0], style, out)


def _emit_single(
    settings: Settings,
    args: argparse.Namespace,
    payload: dict[str, Any],
    style: Style,
    out: TextIO,
) -> int:
    """Render one result in the requested format."""
    result = normalize(payload, settings.dataset, settings.group_by)

    if args.json:
        print(format_json(result, payload, time_range=settings.time_range), file=out)
        return 0
    if args.csv:
        print(format_csv(result), end="", file=out)
        return 0

    if _is_empty(result):
        print(_empty_message(settings, settings.group_by), file=out)
        return 0

    title = f"Vercel Web Analytics: {settings.project} ({settings.preset.name})"
    print(
        format_table(
            result,
            time_range=settings.time_range,
            filter_expr=settings.filter_expr,
            limit=settings.limit,
            style=style,
            title=title,
        ),
        file=out,
    )
    return 0


def _emit_overview(
    settings: Settings,
    args: argparse.Namespace,
    payloads: Sequence[dict[str, Any]],
    style: Style,
    out: TextIO,
) -> int:
    """Render the three overview results as one report, or as JSON."""
    granularity = args.granularity or "day"
    groupings = [[granularity], ["requestPath"], ["referrerHostname"]]
    results = [
        normalize(payload, settings.dataset, grouping)
        for payload, grouping in zip(payloads, groupings)
    ]

    if args.json:
        document = {
            "range": {
                "since": to_api_timestamp(settings.time_range[0]),
                "until": to_api_timestamp(settings.time_range[1]),
            },
            "sections": {
                name: _result_document(result, payload, settings.time_range)
                for name, result, payload in zip(
                    ("byGranularity", "topPages", "topReferrers"), results, payloads
                )
            },
        }
        print(json.dumps(document, indent=2), file=out)
        return 0

    if all(_is_empty(result) for result in results):
        print(_empty_message(settings, [granularity]), file=out)
        return 0

    print(
        render_overview(
            results,
            project=settings.project,
            time_range=settings.time_range,
            filter_expr=settings.filter_expr,
            limit=(
                settings.limit if settings.limit is not None else OVERVIEW_TABLE_LIMIT
            ),
            style=style,
        ),
        file=out,
    )
    return 0


def _resolve_style(
    args: argparse.Namespace, env: Mapping[str, str], out: TextIO
) -> Style:
    """Colour only on a TTY, with NO_COLOR unset and --no-color not passed."""
    color = True
    if args.no_color or env.get("NO_COLOR"):
        color = False
    else:
        isatty = getattr(out, "isatty", None)
        color = bool(isatty()) if callable(isatty) else False
    encoding = (getattr(out, "encoding", None) or "utf-8").lower()
    unicode_safe = "utf" in encoding
    return Style(color=color, unicode=unicode_safe)


def main(
    argv: Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
    *,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Entry point. Returns the process exit code and never raises for the user.

    Args:
        argv: Command line arguments without the program name.
        env: Environment mapping; defaults to :data:`os.environ`.
        out: Stream for report output; defaults to stdout.
        err: Stream for warnings and errors; defaults to stderr.

    Returns:
        0 on success (including an empty result set), 1 for an API or network
        failure, 2 for a configuration or usage error, 130 when interrupted.
    """
    stdout = out if out is not None else sys.stdout
    stderr = err if err is not None else sys.stderr
    environment = env if env is not None else os.environ

    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        return _run(args, environment, stdout, stderr)
    except ConfigError as exc:
        print(f"error: {exc}", file=stderr)
        return 2
    except RateLimitError as exc:
        print(f"error: {exc}", file=stderr)
        print(
            "hint: rate limits are per endpoint; wait for the reset above or "
            "raise --max-retries so the client waits for you",
            file=stderr,
        )
        return 1
    except ApiError as exc:
        print(f"error: {exc}", file=stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
