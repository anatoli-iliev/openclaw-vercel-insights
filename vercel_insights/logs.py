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

import re
from collections.abc import Mapping
from datetime import datetime

from . import ConfigError
from .http import PreparedRequest, default_headers, operation_url
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
