"""Request logs request building and response normalization.

Everything specific to ``GET https://vercel.com/api/logs/request-logs`` lives
here: the level, source and status vocabularies, the parameter allowlist, the
shape of the rows it returns, its paging, and the local aggregation that turns
rows into a summary. The modules underneath (``http``, ``timerange``,
``render``) know none of it.

Two things make this surface unlike the other two, and both shape the code:

* **The API validates almost nothing.** An unknown ``level`` or ``source``
  answers ``200`` with zero rows, so a typo would read as "nothing is broken".
  Every vocabulary is therefore checked here, before a request exists.
* **``level`` matches application log lines, not responses.** A ``500`` that
  printed nothing carries no log line and no level, and a ``200`` whose handler
  logged a stack trace is not a ``5xx``. Neither filter alone answers "what
  broke", which is why the errors presets query both and merge.

See docs/api-notes.md for the live probes behind every claim here.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

from . import ApiError, ConfigError, sanitize_label, sanitize_message
from .http import PreparedRequest, default_headers, operation_url
from .render import (
    ERROR_LEVELS,
    LogEntry,
    LogLine,
    LogReport,
    LogSummary,
    MessageTally,
    RouteTally,
)
from .timerange import to_unix_ms

#: The operation key this surface uses. A key into ``http.OPERATIONS``, never a
#: method and never a host.
OPERATION = "request_logs"

#: Log levels the API filters on, in the order the help text lists them.
LEVELS: tuple[str, ...] = ("error", "warning", "info", "fatal")

#: Sources the API filters on.
SOURCES: tuple[str, ...] = (
    "serverless",
    "edge-function",
    "edge-middleware",
    "static",
)

#: Rows per page. Fixed by the API: the ``limit`` parameter is accepted and
#: ignored, which is why a row limit is enforced in this client instead.
PAGE_SIZE = 50

#: How many pages one call will ever fetch. A page took up to 6 seconds in
#: testing, so four pages is already 24 seconds against a 30 second per request
#: timeout. Raising this trades an answer for a hang.
MAX_PAGES = 4

MIN_LIMIT = 1
MAX_LIMIT = PAGE_SIZE * MAX_PAGES
DEFAULT_LIMIT = PAGE_SIZE

#: One ``statusCode`` item: three characters where the first is a digit and the
#: rest are digits or ``x``, or the literal ``None``. The API's own message
#: names exactly this rule, and is quoted in the error below.
_STATUS_ITEM_RE = re.compile(r"^[1-9][0-9x]{2}$")


def _split(value: str) -> list[str]:
    """Split a comma separated flag value, dropping surrounding whitespace."""
    return [item.strip() for item in value.split(",") if item.strip()]


def _validate_vocabulary(
    flag: str, noun: str, value: str, vocabulary: tuple[str, ...]
) -> str:
    """Validate a comma separated list against a fixed vocabulary.

    Shared by :func:`validate_levels` and :func:`validate_sources`, which
    differ only in the flag, the noun and the vocabulary: both need every
    accepted value named, and the same 200-with-zero-rows danger explained,
    so one message template serves both rather than two that could drift.

    Args:
        flag: The flag name, without its leading dashes, for example
            ``"level"``.
        noun: What one item of this vocabulary is called, for the message,
            for example ``"log level"``.
        value: One or more comma separated names, any case.
        vocabulary: Every value this API accepts for this flag.

    Returns:
        The lower-cased comma separated list to send.

    Raises:
        ConfigError: When the list is empty or names a value outside
            ``vocabulary``. The API answers an unknown value with HTTP 200
            and zero rows rather than an error, so an unchecked typo would
            read as "nothing is broken".
    """
    items = [item.lower() for item in _split(value)]
    unknown = [item for item in items if item not in vocabulary]
    if not items or unknown:
        offending = f"{unknown[0]!r}" if unknown else "an empty list"
        raise ConfigError(
            f"--{flag} {offending} is not a {noun} this API knows; it accepts "
            f"{', '.join(vocabulary)}, comma separated. This is checked here "
            "because the API answers an unknown value with HTTP 200 and zero "
            "rows rather than an error, which would read as 'nothing is broken'"
        )
    return ",".join(items)


def validate_levels(value: str) -> str:
    """Validate a ``--level`` list and return it as the API spells it.

    Args:
        value: One or more comma separated level names, any case.

    Returns:
        The lower-cased comma separated list to send.

    Raises:
        ConfigError: When the list is empty or names a level the API does not
            know. The API answers 200 with zero rows for an unknown level, so
            an unchecked typo would report a healthy site.
    """
    return _validate_vocabulary("level", "log level", value, LEVELS)


def validate_sources(value: str) -> str:
    """Validate a ``--source`` list and return it as the API spells it.

    Args:
        value: One or more comma separated source names, any case.

    Returns:
        The lower-cased comma separated list to send.

    Raises:
        ConfigError: When the list is empty or names an unknown source. Same
            reasoning as :func:`validate_levels`: an unknown value is answered
            with zero rows.
    """
    return _validate_vocabulary("source", "source", value, SOURCES)


def validate_status_code(value: str) -> str:
    """Validate a ``--status-code`` expression against the API's own rule.

    Args:
        value: Comma separated status codes, classes such as ``4xx``, or
            ``None`` for requests with no status recorded.

    Returns:
        The expression to send, lower-cased for classes and with ``None``
        spelled the way the API spells it.

    Raises:
        ConfigError: When an item matches neither form. The message quotes the
            API's own validation text, since that is the authority.
    """
    items = _split(value)
    normalized: list[str] = []
    for item in items:
        if item.lower() == "none":
            normalized.append("None")
            continue
        lowered = item.lower()
        if _STATUS_ITEM_RE.match(lowered):
            normalized.append(lowered)
            continue
        raise ConfigError(
            f"--status-code {item!r} is not a status this API accepts. It says: "
            '"statusCode must contain only comma-separated integers, status code '
            'classes like 4xx or 5xx, or \\"None\\"". So --status-code 500, '
            "--status-code 5xx, --status-code 4xx,5xx and --status-code None all "
            "work; a comparison such as >=500 does not"
        )
    if not normalized:
        raise ConfigError(
            "--status-code was empty; pass a status such as 500, a class such as "
            "4xx or 5xx, or None for requests with no status recorded"
        )
    return ",".join(normalized)


def validate_limit(limit: int) -> int:
    """Bound the number of log rows one run will report.

    Args:
        limit: The requested row count.

    Returns:
        The limit, unchanged, when it is in range.

    Raises:
        ConfigError: When it is outside :data:`MIN_LIMIT` to :data:`MAX_LIMIT`.
    """
    if MIN_LIMIT <= limit <= MAX_LIMIT:
        return limit
    raise ConfigError(
        f"--limit {limit} is out of range on a logs preset, which counts rows "
        f"rather than groups: pass {MIN_LIMIT} to {MAX_LIMIT}. The API pages "
        f"{PAGE_SIZE} rows at a time and ignores a limit of its own, so this "
        f"client stops after {MAX_PAGES} pages"
    )


# ---------------------------------------------------------------------------
# Request building
# ---------------------------------------------------------------------------

#: Every filter parameter this surface may send, in the order they are emitted.
#: This is a parameter allowlist as well as an ordering: a key outside it is a
#: ConfigError, so a caller cannot introduce a query parameter of its own.
FILTER_PARAMS: tuple[str, ...] = (
    "level",
    "statusCode",
    "source",
    "requestMethod",
    "requestPath",
    "route",
    "environment",
    "branch",
    "deploymentId",
    "requestId",
    "search",
)


def build_request(
    *,
    project: str,
    owner_id: str,
    since: datetime,
    until: datetime,
    page: int = 0,
    filters: Mapping[str, str] | None = None,
    token: str | None = None,
) -> PreparedRequest:
    """Build the request that fetches one page of request logs. Pure: no I/O.

    The URL comes from the ``request_logs`` entry of the operation allowlist, so
    neither the method nor the host is written down here. The token, when
    supplied, goes into the ``Authorization`` header and nowhere else.

    ``teamId`` is deliberately absent: this endpoint does not accept it, and
    ``ownerId`` is what scopes the call.

    Args:
        project: Project id or project name; both work on this endpoint.
        owner_id: Account that owns the project. Required by the API.
        since: Start of the window, aware.
        until: End of the window, aware.
        page: Zero based page index.
        filters: Wire-named filter values, keyed by :data:`FILTER_PARAMS`.
            Empty values are dropped rather than sent.
        token: Access token for the ``Authorization`` header.

    Returns:
        The :class:`PreparedRequest` describing exactly one allowlisted call.

    Raises:
        ConfigError: When ``filters`` carries a key outside
            :data:`FILTER_PARAMS`.
    """
    supplied = dict(filters or {})
    unknown = sorted(set(supplied) - set(FILTER_PARAMS))
    if unknown:
        raise ConfigError(
            f"{unknown[0]!r} is not a request logs filter; this surface sends "
            f"only {', '.join(FILTER_PARAMS)}"
        )

    params: list[tuple[str, str]] = [
        ("projectId", project),
        ("ownerId", owner_id),
        ("page", str(page)),
        ("startDate", to_unix_ms(since)),
        ("endDate", to_unix_ms(until)),
    ]
    for name in FILTER_PARAMS:
        value = supplied.get(name)
        if value:
            params.append((name, value))

    return PreparedRequest(
        operation=OPERATION,
        url=operation_url(OPERATION),
        params=params,
        headers=default_headers(token),
    )


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def _text(row: Mapping[str, Any], name: str) -> str:
    """One sanitized single-line string field, empty when absent."""
    value = row.get(name)
    if value is None or isinstance(value, (Mapping, list)):
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return sanitize_label(str(value))


def _number(row: Mapping[str, Any], name: str) -> float | None:
    """One numeric field, ``None`` when absent, non-numeric or not finite."""
    value = row.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(float(value)) else None


def _status(row: Mapping[str, Any]) -> int | None:
    """The HTTP status, ``None`` when the API recorded none.

    A status of 0 is how this API spells "no response was recorded", which is
    also what ``statusCode=None`` selects, so it is read as absent rather than
    as a status of zero.
    """
    value = _number(row, "statusCode")
    if value is None or value <= 0:
        return None
    return int(value)


def _timestamp(row: Mapping[str, Any]) -> datetime | None:
    """The row's instant, ``None`` when it is missing or unparseable.

    Values arrive as ISO-8601 with a trailing ``Z``, which
    ``datetime.fromisoformat`` cannot read before Python 3.11, so the offset is
    spelled out first.
    """
    raw = row.get("timestamp")
    if not isinstance(raw, str) or not raw:
        return None
    candidate = raw[:-1] + "+00:00" if raw.endswith(("Z", "z")) else raw
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _lines(row: Mapping[str, Any]) -> tuple[LogLine, ...]:
    """Every application log line on this request, sanitized.

    ASSUMPTION: the item shape is ``{level, message, messageTruncated}``, taken
    from the Vercel CLI's own mapping code. No probe ever saw one populated,
    because neither test project had logged an error, so anything unexpected is
    skipped rather than trusted. See docs/api-notes.md.
    """
    raw = row.get("logs")
    if not isinstance(raw, list):
        return ()
    lines: list[LogLine] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        message = item.get("message")
        level = item.get("level")
        lines.append(
            LogLine(
                level=sanitize_label(str(level)).lower() if level else "",
                message=sanitize_message(str(message)) if message else "",
                truncated=bool(item.get("messageTruncated")),
            )
        )
    return tuple(lines)


def _source(row: Mapping[str, Any]) -> str:
    """Where the request was served from, read off its first event."""
    events = row.get("events")
    if isinstance(events, list):
        for event in events:
            if isinstance(event, Mapping) and event.get("source"):
                return sanitize_label(str(event["source"]))
    return ""


def _region(row: Mapping[str, Any]) -> str:
    """The region that served the request, off its first event or the client."""
    events = row.get("events")
    if isinstance(events, list):
        for event in events:
            if isinstance(event, Mapping) and event.get("region"):
                return sanitize_label(str(event["region"]))
    return _text(row, "clientRegion")


def _entry(row: Mapping[str, Any]) -> LogEntry:
    """Turn one API row into a :class:`LogEntry`, sanitizing every string."""
    return LogEntry(
        request_id=_text(row, "requestId"),
        timestamp=_timestamp(row),
        status=_status(row),
        method=_text(row, "requestMethod"),
        path=_text(row, "requestPath"),
        route=_text(row, "route"),
        source=_source(row),
        environment=_text(row, "environment"),
        deployment_id=_text(row, "deploymentId"),
        duration_ms=_number(row, "requestDurationMs"),
        region=_region(row),
        error_code=_text(row, "errorCode"),
        branch=_text(row, "branch"),
        domain=_text(row, "domain"),
        trace_id=_text(row, "traceId"),
        crashed=bool(row.get("hasFunctionCrashed")),
        lines=_lines(row),
        raw=dict(row),
    )


def normalize(payload: Mapping[str, Any]) -> tuple[list[LogEntry], bool]:
    """Parse one page of request logs.

    Args:
        payload: The decoded response body.

    Returns:
        The page's entries in the order they arrived, and whether the API said
        more rows exist.

    Raises:
        ApiError: With code ``invalid_response`` when ``rows`` is present but is
            not a list of objects. Nothing is dropped silently: a shape this
            client cannot read is reported, because a quietly shortened list of
            errors is worse than an error message.
    """
    rows = payload.get("rows", [])
    if rows is None:
        rows = []
    if not isinstance(rows, list):
        raise ApiError(
            200,
            "invalid_response",
            "the request logs response carried 'rows' that was not a list; run "
            "with --json to see it",
        )
    entries: list[LogEntry] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ApiError(
                200,
                "invalid_response",
                "the request logs response carried a row that was not an "
                "object; run with --json to see it",
            )
        entries.append(_entry(row))
    return entries, bool(payload.get("hasMoreRows"))


# ---------------------------------------------------------------------------
# Paging, merging and error presets
# ---------------------------------------------------------------------------


def collect(
    call: Callable[[int], Mapping[str, Any]],
    *,
    limit: int,
    max_pages: int = MAX_PAGES,
) -> tuple[list[LogEntry], bool, int]:
    """Read pages until the row budget is met, and say whether more existed.

    The API pages :data:`PAGE_SIZE` rows at a time and ignores a ``limit`` of
    its own, so the budget is enforced here instead. Paging stops on whichever
    comes first: the budget being met, a page shorter than :data:`PAGE_SIZE`
    (the server has nothing else for this query, whatever ``hasMoreRows``
    claims), ``hasMoreRows`` being false, or ``max_pages`` being reached. The
    fetcher is injected so this loop is testable with no HTTP at all, and so
    this module still performs no I/O of its own.

    Args:
        call: Given a zero based page index, returns that page's payload.
        limit: How many rows the caller wants at most.
        max_pages: Hard ceiling on requests, defaulting to :data:`MAX_PAGES`.
            A page took up to six seconds against a live account, so the
            default is already 24 seconds against a 30 second per request
            timeout.

    Returns:
        The entries, never more than ``limit``; whether rows were left
        behind; and how many pages were read.

    Raises:
        ApiError: Whatever :func:`normalize` raises for an unreadable page.
    """
    entries: list[LogEntry] = []
    has_more = False
    short_page = False
    pages = 0
    for page in range(max(1, max_pages)):
        payload = call(page)
        pages = page + 1
        page_entries, has_more = normalize(payload)
        entries.extend(page_entries)
        short_page = len(page_entries) < PAGE_SIZE
        if len(entries) >= limit or short_page or not has_more:
            break
    # A short page means nothing else exists for this query, whatever
    # hasMoreRows claims, so it never counts toward truncation on its own:
    # only rows already in hand beyond the budget, or a credible hasMoreRows
    # off a full sized page, make this a truncated answer.
    truncated = len(entries) > limit or (has_more and not short_page)
    return entries[:limit], truncated, pages


def merge(
    groups: Sequence[Sequence[LogEntry]], *, limit: int
) -> tuple[list[LogEntry], bool]:
    """Combine the results of several calls into one honest, ordered list.

    One request can arrive from more than one call: the errors preset's two
    filter sets both match a 5xx that also logged a stack trace. Entries are
    therefore deduplicated by request id, and the copy carrying more log
    lines wins, since the other copy would render with an empty message.

    Ordering is applied here rather than trusted from the server, so "newest
    first" is a property of this client. A row with no timestamp sorts last,
    and the request id breaks ties, so the output is deterministic.

    Args:
        groups: One sequence of entries per call.
        limit: How many rows to keep.

    Returns:
        The merged entries, newest first and never more than ``limit``; and
        whether anything was dropped.
    """
    best: dict[str, LogEntry] = {}
    anonymous: list[LogEntry] = []
    for group in groups:
        for entry in group:
            if not entry.request_id:
                # Without an id there is nothing to deduplicate on, and
                # dropping it would hide a request. Keep it.
                anonymous.append(entry)
                continue
            previous = best.get(entry.request_id)
            if previous is None or len(entry.lines) > len(previous.lines):
                best[entry.request_id] = entry

    merged = list(best.values()) + anonymous
    epoch = datetime(1, 1, 1, tzinfo=timezone.utc)
    merged.sort(
        key=lambda entry: (entry.timestamp or epoch, entry.request_id),
        reverse=True,
    )
    return merged[:limit], len(merged) > limit


def _is_two_call(filters: Mapping[str, str]) -> bool:
    """Whether the errors preset's two-call merge rule applies to ``filters``.

    :func:`error_filter_sets` and :func:`build_report` both need to agree on
    this: the former decides whether to actually issue two calls, and the
    latter decides whether to caveat a truncated answer as "the most recent N
    of each kind" rather than a global top N. Stating the rule once here,
    rather than once in each, is what keeps them from drifting apart.

    Args:
        filters: The wire-named filters the user asked for.

    Returns:
        True when neither ``level`` nor ``statusCode`` was supplied, meaning
        the errors preset queries both and merges the results; false when an
        explicit ``--level`` or ``--status-code`` already narrowed the query
        to one call.
    """
    return not ({"level", "statusCode"} & set(filters))


def error_filter_sets(filters: Mapping[str, str]) -> list[dict[str, str]]:
    """The filter sets the errors preset queries with.

    Two calls, because ``level`` matches application log lines and
    ``statusCode`` matches responses, and an error can show up as either: a
    5xx that printed nothing is invisible to ``level``, and a 200 whose
    handler logged a stack trace is invisible to ``statusCode``. An explicit
    ``--level`` or ``--status-code`` collapses this to one call, the same "an
    explicit flag overrides a preset value" rule the rest of this tool
    follows.

    Args:
        filters: The wire-named filters the user asked for.

    Returns:
        One filter mapping when the user already narrowed by level or status;
        otherwise two, each a complete filter set for one call.
    """
    if not _is_two_call(filters):
        return [dict(filters)]
    return [
        {**filters, "statusCode": "5xx"},
        {**filters, "level": ",".join(ERROR_LEVELS)},
    ]


# ---------------------------------------------------------------------------
# Local aggregation
# ---------------------------------------------------------------------------

#: The message group for a request that failed without logging anything.
NO_LOG_LINE = "(no log line)"


def summarize(entries: Sequence[LogEntry]) -> LogSummary:
    """Tally a merged list of entries three ways, for the error-summary preset.

    Grouping is deliberately literal: statuses by their own number, routes by
    their pattern, messages by their exact text. Clustering messages by a
    guessed pattern would merge two different bugs into one row, which is a
    worse answer than three rows.

    Args:
        entries: The merged entries, in any order.

    Returns:
        The tallies, each ordered by count and then by name so the output is
        stable across runs. ``logged_only`` counts entries that are errors
        only because they logged an error or fatal line, and is meaningful
        only when ``entries`` has already been filtered down to errors.
    """
    status_counts: dict[str, int] = {}
    routes: dict[str, list[LogEntry]] = {}
    messages: dict[str, list[LogEntry]] = {}
    logged_only = 0

    for entry in entries:
        status = str(entry.status) if entry.status is not None else "(none)"
        status_counts[status] = status_counts.get(status, 0) + 1
        routes.setdefault(entry.label, []).append(entry)
        messages.setdefault(entry.headline or NO_LOG_LINE, []).append(entry)
        if (entry.status is None or entry.status < 500) and not entry.crashed:
            logged_only += 1

    def seen(group: Sequence[LogEntry]) -> tuple[datetime | None, datetime | None]:
        stamps = sorted(item.timestamp for item in group if item.timestamp is not None)
        return (stamps[0], stamps[-1]) if stamps else (None, None)

    def worst(group: Sequence[LogEntry]) -> int | None:
        found = [item.status for item in group if item.status is not None]
        return max(found) if found else None

    route_tallies: list[RouteTally] = []
    for route, group in sorted(
        routes.items(), key=lambda item: (-len(item[1]), item[0])
    ):
        first_seen, last_seen = seen(group)
        route_tallies.append(
            RouteTally(
                route=route,
                count=len(group),
                worst_status=worst(group),
                first_seen=first_seen,
                last_seen=last_seen,
            )
        )
    by_route = tuple(route_tallies)

    message_tallies: list[MessageTally] = []
    for message, group in sorted(
        messages.items(), key=lambda item: (-len(item[1]), item[0])
    ):
        first_seen, last_seen = seen(group)
        message_tallies.append(
            MessageTally(
                message=message,
                count=len(group),
                first_seen=first_seen,
                last_seen=last_seen,
            )
        )
    by_message = tuple(message_tallies)
    by_status = tuple(
        sorted(status_counts.items(), key=lambda item: (-item[1], item[0]))
    )
    return LogSummary(
        total=len(entries),
        by_status=by_status,
        by_route=by_route,
        by_message=by_message,
        logged_only=logged_only,
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

#: What the errors presets count, stated in the output so the reader is never
#: guessing. Both halves matter: see the module docstring.
ERROR_DEFINITION = (
    "Counted as an error: a 5xx response, a crashed function, or a request "
    "that logged an error or fatal line."
)

#: Read from https://vercel.com/docs/runtime-logs on 2026-08-17. Printed when a
#: query came back empty over a window longer than the shortest retention, so an
#: empty answer is never mistaken for a healthy one.
RETENTION_NOTE = (
    "Runtime log retention is 1 hour on Hobby, 1 day on Pro, 3 days on "
    "Enterprise and 30 days with Observability Plus, so an empty result over a "
    "longer window can mean the logs aged out rather than that nothing failed."
)

#: The shortest retention any plan has. Below this there is nothing to warn
#: about, and a warning on every empty answer trains the reader to ignore it.
SHORTEST_RETENTION = timedelta(hours=1)


def _window_prose(time_range: tuple[datetime, datetime]) -> str:
    """The window as a person says it: "30 minutes", "6 hours", "3 days"."""
    span = time_range[1] - time_range[0]
    minutes = int(round(span.total_seconds() / 60))
    if minutes < 60:
        return f"{minutes} minute{'' if minutes == 1 else 's'}"
    hours = span.total_seconds() / 3600
    if hours < 48:
        rounded = int(round(hours))
        return f"{rounded} hour{'' if rounded == 1 else 's'}"
    days = int(round(hours / 24))
    return f"{days} day{'' if days == 1 else 's'}"


def build_report(
    entries: Sequence[LogEntry],
    *,
    time_range: tuple[datetime, datetime],
    project_label: str,
    preset: str,
    filters: Mapping[str, str],
    truncated: bool,
    pages_fetched: int,
    requested_limit: int,
    counts_errors: bool,
) -> LogReport:
    """Wrap entries in everything needed to print them honestly.

    Every sentence the output adds beyond the table is composed here: what
    counted as an error, how many there were, what was left out, and what an
    empty answer does not prove. ``render.py`` only lays out what it is given.

    Args:
        entries: The merged entries, newest first.
        time_range: The resolved window.
        project_label: How to name what was queried.
        preset: The preset name, shown in the title.
        filters: The filters the user asked for, wire-named.
        truncated: Whether any call left rows behind.
        pages_fetched: How many requests were spent.
        requested_limit: The row budget that was in force.
        counts_errors: True for the presets that filter to failures.

    Returns:
        The report, ready to render in any format.
    """
    window = _window_prose(time_range)
    notes: list[str] = []
    hint: str | None = None

    if entries:
        summary = summarize(entries)
        noun = "error" if counts_errors else "request"
        plural = "" if summary.total == 1 else "s"
        breakdown = ", ".join(
            f"{count} x {status}" for status, count in summary.by_status
        )
        notes.append(f"{summary.total} {noun}{plural} in {window}: {breakdown}.")
        if len(summary.by_route) > 1:
            worst = summary.by_route[0]
            notes.append(f"Most affected route: {worst.route} ({worst.count}).")
        if counts_errors and summary.logged_only:
            notes.append(
                f"{summary.logged_only} of them returned a non-5xx status and "
                "count as errors only because they logged an error or fatal line."
            )
        hint = (
            "Add --expand for full messages, or --request-id to pull one request "
            "apart."
        )

    if truncated:
        notes.append(
            f"More rows matched than were shown: this is the most recent "
            f"{requested_limit}. Raise --limit (up to {MAX_LIMIT}) or narrow the "
            "window."
        )
        if counts_errors and _is_two_call(filters):
            notes.append(
                "Both filters were paging, so this is the most recent "
                f"{requested_limit} of each kind rather than a global top "
                f"{requested_limit}."
            )

    if not entries and time_range[1] - time_range[0] > SHORTEST_RETENTION:
        notes.append(RETENTION_NOTE)

    return LogReport(
        entries=list(entries),
        time_range=time_range,
        project_label=project_label,
        preset=preset,
        window_label=window,
        filters=dict(filters),
        truncated=truncated,
        pages_fetched=pages_fetched,
        requested_limit=requested_limit,
        header_note=ERROR_DEFINITION if counts_errors else None,
        notes=tuple(notes),
        hint=hint,
    )
