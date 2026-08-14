"""Speed Insights request building and response normalization.

Everything specific to ``POST /v2/observability/query`` lives here: the metric
ids, the published targets, this surface's dimension names, the JSON body, and
the shape of whatever comes back. The modules underneath (``http``, ``odata``,
``timerange``, ``render``) know none of it.

Why a POST
----------
Vercel exposes no GET equivalent for an observability query, and Speed Insights
has no dedicated query API of its own: the query travels in a request body.
That is still a read. Nothing is created or mutated, and the toggle endpoints
that would enable or disable the feature are absent from the operation
allowlist in :mod:`vercel_insights.http` entirely.

How much of this is pinned down
-------------------------------
The published OpenAPI document declares ``scope``, ``granularity`` and the
whole 200 response body as bare objects with no inner properties, so their
exact shapes are inferred from documented CLI behaviour rather than read from a
schema. Every such inference is marked ASSUMPTION below. The consequences are
contained: a request field that turns out to be spelled differently fails with
the API's own 400 message, and :func:`normalize` probes for each plausible
response shape and reports a clear ``invalid_response`` error rather than
raising on a payload it did not expect.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypeGuard

from . import OTHERS_LABEL, ApiError, ConfigError
from .http import PreparedRequest, default_headers, operation_url
from .render import (
    DATA_POINTS_METRIC,
    UNIT_COUNT,
    UNIT_MS,
    UNIT_SCORE,
    Result,
    Row,
)
from .timerange import to_api_timestamp

#: The operation keys this surface uses. Both are keys into
#: ``http.OPERATIONS``, never a method and never a host.
OPERATION = "observability_query"
SCHEMA_OPERATION = "observability_schema"

#: The value used as ``Result.dataset`` for everything from this surface.
DATASET = "speed-insights"

#: Every Speed Insights metric id starts with this.
METRIC_PREFIX = "vercel.speed_insights"

#: Where Real Experience Score actually lives.
DASHBOARD_DOCS_URL = "https://vercel.com/docs/speed-insights/metrics"

#: Vercel's published "good" target per web vital, in the metric's own unit:
#: milliseconds for LCP, INP, FCP and TTFB, and a unitless score for CLS.
#: Vercel publishes no boundary above these, which is why the renderer's
#: verdict is two tier. Transcribed from docs/api-notes.md.
TARGETS: dict[str, float] = {
    "lcp": 2500.0,
    "inp": 200.0,
    "cls": 0.1,
    "fcp": 1800.0,
    "ttfb": 800.0,
}


@dataclass(frozen=True)
class Metric:
    """One queryable metric: its id, how to name it, and how to read it."""

    id: str
    short: str
    label: str
    unit: str
    target: float | None
    #: For a data point count metric, the short name of the vital it counts.
    counts_for: str | None = None

    @property
    def is_count(self) -> bool:
        """True for one of the ``*_count`` data point count metrics."""
        return self.counts_for is not None

    @property
    def count_id(self) -> str:
        """The id of the metric counting the data points behind this one."""
        if self.is_count:
            return self.id
        return f"{METRIC_PREFIX}.{self.short}_count"

    def column(self, aggregation: str) -> str:
        """The column name a result uses for this metric under ``aggregation``."""
        return f"{aggregation.replace('/', '_')}_{self.short}"


#: The five web vitals, verbatim from docs/api-notes.md: short name, the tail
#: of the metric id, the human label, and the unit the value is measured in.
_VITALS: tuple[tuple[str, str, str, str], ...] = (
    ("lcp", "lcp_ms", "Largest Contentful Paint", UNIT_MS),
    ("inp", "inp_ms", "Interaction to Next Paint", UNIT_MS),
    ("cls", "cls", "Cumulative Layout Shift", UNIT_SCORE),
    ("fcp", "fcp_ms", "First Contentful Paint", UNIT_MS),
    ("ttfb", "ttfb_ms", "Time to First Byte", UNIT_MS),
)

#: The five vitals in display order, which is the order the vitals preset uses.
VITAL_ORDER: tuple[str, ...] = tuple(short for short, _tail, _label, _unit in _VITALS)


def _build_metrics() -> dict[str, Metric]:
    """The ten queryable metric ids: five values and five data point counts."""
    metrics: dict[str, Metric] = {}
    for short, tail, label, unit in _VITALS:
        metric_id = f"{METRIC_PREFIX}.{tail}"
        metrics[metric_id] = Metric(
            id=metric_id,
            short=short,
            label=label,
            unit=unit,
            target=TARGETS[short],
        )
    for short, _tail, label, _unit in _VITALS:
        count_id = f"{METRIC_PREFIX}.{short}_count"
        metrics[count_id] = Metric(
            id=count_id,
            short=f"{short}_count",
            label=f"{label} data points",
            # A count of measurements is a count, whatever the metric behind it
            # is measured in, and no target is published for one.
            unit=UNIT_COUNT,
            target=None,
            counts_for=short,
        )
    return metrics


#: Every metric this client can query, keyed by its full id. Nothing else is
#: reachable: :func:`validate_metric` refuses anything not in here.
METRICS: dict[str, Metric] = _build_metrics()

#: Dimensions confirmed in Vercel's worked Speed Insights CLI examples. Note
#: the snake_case: this API spells dimensions differently from Web Analytics,
#: and a dimension name is not portable between the two surfaces.
SPEED_DIMENSIONS: tuple[str, ...] = (
    "route",
    "request_path",
    "device_type",
    "country",
    "project_id",
    "environment",
)

#: Web Analytics spellings, mapped to what to use here instead. ``None`` means
#: the dimension has no Speed Insights counterpart at all.
WEB_ANALYTICS_DIMENSIONS: dict[str, str | None] = {
    "requestPath": "request_path",
    "deviceType": "device_type",
    "projectId": "project_id",
    "referrerHostname": None,
    "osName": None,
    "browserName": None,
    "utmSource": None,
    "utmMedium": None,
    "utmCampaign": None,
    "utmContent": None,
    "utmTerm": None,
    "eventName": None,
    "eventData": None,
    "flags": None,
}

#: Percentiles the CLI documents, and the one the dashboard defaults to.
PERCENTILES: tuple[int, ...] = (75, 90, 95, 99)
DEFAULT_PERCENTILE = 75
DEFAULT_AGGREGATION = f"p{DEFAULT_PERCENTILE}"

#: The aggregation the data point count preset uses: counts do add up.
COUNT_AGGREGATION = "sum"

#: Aggregations whose rows can be summed. Everything else, percentiles above
#: all, produces a table with no totals row: the P75 of six countries has no
#: meaningful sum.
ADDITIVE_AGGREGATIONS: frozenset[str] = frozenset({"sum", "count"})

#: Documented aggregation spellings, used only to make an error message useful.
KNOWN_AGGREGATIONS: tuple[str, ...] = (
    "sum",
    "count",
    "min",
    "max",
    "p75",
    "p90",
    "p95",
    "p99",
)

#: An aggregation is a bare name, optionally qualified by one dimension, as in
#: ``unique/visitor_id``. Anything else is refused rather than put in the body.
_AGGREGATION_RE = re.compile(r"^[a-z][a-z0-9_]*(/[A-Za-z0-9_]+)?$")

#: ``orderBy`` is a rollup column, not a dimension. The CLI exposes two.
ORDER_BY_VALUES: tuple[str, ...] = ("count", "value")
ORDER_DIRECTIONS: tuple[str, ...] = ("desc", "asc")
DEFAULT_ORDER_BY = "count"
DEFAULT_ORDER_DIRECTION = "desc"

MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_LIMIT = 10
#: The observability API documents no maximum for ``groupBy``. This client
#: keeps the Web Analytics ceiling rather than inventing a higher one, so a
#: grouping that is refused on one surface is refused on both.
MAX_GROUP_BY = 2


# ---------------------------------------------------------------------------
# Metric validation
# ---------------------------------------------------------------------------


def _alias_key(name: str) -> str:
    """Fold a metric name to letters and digits, for forgiving lookups."""
    return re.sub(r"[^a-z0-9]", "", name.strip().lower())


def _build_aliases() -> dict[str, str]:
    """Every accepted spelling of a metric, mapped to its canonical id."""
    aliases: dict[str, str] = {}
    for metric in METRICS.values():
        candidates = [metric.id, metric.short, metric.id.split(".")[-1], metric.label]
        if not metric.is_count:
            candidates.append(f"{metric.short}_value")
        for candidate in candidates:
            aliases[_alias_key(candidate)] = metric.id
    return aliases


#: Accepted metric spellings. ``lcp``, ``lcp_ms``, ``LCP``, the full id and the
#: human label all name the same metric, and the ``*_count`` forms name its
#: data point count.
METRIC_ALIASES: dict[str, str] = _build_aliases()

#: Every way a user might reasonably ask for Real Experience Score. It is not
#: queryable, and asking for it must fail loudly rather than quietly returning
#: some other metric.
_RES_ALIASES: frozenset[str] = frozenset(
    {
        "res",
        "realexperiencescore",
        "realexperience",
        "experiencescore",
        "vercelspeedinsightsres",
        "vercelspeedinsightsrealexperiencescore",
        "realexperiencescoreres",
    }
)

METRIC_HELP = ", ".join(VITAL_ORDER)


def validate_metric(name: str) -> Metric:
    """Resolve a metric name, or refuse it with a message that names the fix.

    Accepts the short name (``lcp``), the id tail (``lcp_ms``), the full id
    (``vercel.speed_insights.lcp_ms``), the human label, and the ``*_count``
    forms of each, in any case and with any punctuation between words.

    Args:
        name: The metric as the user wrote it.

    Returns:
        The :class:`Metric` record, which carries the id that goes on the wire.

    Raises:
        ConfigError: When the name is empty, names Real Experience Score, or
            matches no metric. The last case suggests the closest name.
    """
    raw = name.strip()
    if not raw:
        raise ConfigError(
            f"--metric is empty; pass one of {METRIC_HELP}, or add --data-points "
            "to query the number of measurements behind one of them"
        )

    key = _alias_key(raw)
    if key in _RES_ALIASES:
        raise ConfigError(
            f"--metric {raw!r}: Real Experience Score is not queryable. Vercel "
            "states plainly that it is not available through the query API this "
            "tool uses, so there is nothing to request and this client will not "
            "substitute another metric for it. Read it on the Speed Insights tab "
            f"of your project dashboard ({DASHBOARD_DOCS_URL}), or query one of "
            f"the five metrics it is derived from: {METRIC_HELP}"
        )

    metric_id = METRIC_ALIASES.get(key)
    if metric_id is not None:
        return METRICS[metric_id]

    suggestions = difflib.get_close_matches(key, sorted(METRIC_ALIASES), n=1, cutoff=0.6)
    hint = ""
    if suggestions:
        suggested = METRICS[METRIC_ALIASES[suggestions[0]]]
        hint = f" Did you mean {suggested.short!r}?"
    raise ConfigError(
        f"unknown metric {raw!r}.{hint} The Speed Insights metrics are "
        f"{METRIC_HELP}; add --data-points for the number of measurements "
        f"behind one of them, or pass a full id such as {METRIC_PREFIX}.lcp_ms"
    )


def metric_for(short: str, *, data_points: bool = False) -> Metric:
    """The metric record for a short name, optionally its data point count."""
    metric = validate_metric(short)
    if data_points and not metric.is_count:
        return METRICS[metric.count_id]
    return metric


# ---------------------------------------------------------------------------
# Dimension, aggregation and limit validation
# ---------------------------------------------------------------------------


def validate_dimension(dimension: str) -> str:
    """Validate one grouping dimension against this surface's vocabulary.

    A Web Analytics spelling gets its own message rather than a generic one:
    the two surfaces genuinely disagree about the name of the same thing, and
    telling the user which spelling belongs where is the whole fix.

    Raises:
        ConfigError: With the offending value and the fix.
    """
    name = dimension.strip()
    if not name:
        raise ConfigError(
            "empty grouping dimension; pass a name such as --group-by route"
        )
    if name in SPEED_DIMENSIONS:
        return name

    if name in WEB_ANALYTICS_DIMENSIONS:
        equivalent = WEB_ANALYTICS_DIMENSIONS[name]
        if equivalent is not None:
            raise ConfigError(
                f"{name!r} is the Web Analytics spelling; the Speed Insights API "
                f"uses snake_case, so group by {equivalent!r} instead"
            )
        raise ConfigError(
            f"{name!r} is a Web Analytics dimension and has no Speed Insights "
            f"equivalent; this surface groups by {', '.join(SPEED_DIMENSIONS)}, "
            f"so use one of those, or run a Web Analytics preset to group by "
            f"{name!r}"
        )

    suggestions = difflib.get_close_matches(name, SPEED_DIMENSIONS, n=1, cutoff=0.6)
    hint = f" Did you mean {suggestions[0]!r}?" if suggestions else ""
    raise ConfigError(
        f"unknown Speed Insights dimension {name!r}.{hint} This surface groups "
        f"by {', '.join(SPEED_DIMENSIONS)}"
    )


def validate_group_by(dimensions: Sequence[str]) -> list[str]:
    """Validate a whole grouping: each dimension, repeats, and the count.

    Raises:
        ConfigError: On an unknown dimension, a repeat, or more than
            :data:`MAX_GROUP_BY` dimensions.
    """
    validated = [validate_dimension(dimension) for dimension in dimensions]

    seen: set[str] = set()
    for dimension in validated:
        if dimension in seen:
            raise ConfigError(
                f"dimension {dimension!r} is grouped by twice; remove the repeat"
            )
        seen.add(dimension)

    if len(validated) > MAX_GROUP_BY:
        raise ConfigError(
            f"grouping by {len(validated)} dimensions ({', '.join(validated)}) "
            f"exceeds the {MAX_GROUP_BY} this client allows; drop "
            f"{len(validated) - MAX_GROUP_BY} of them. Time buckets are not part "
            "of the grouping on this surface, so --granularity does not count"
        )
    return validated


def validate_aggregation(aggregation: str) -> str:
    """Check an ``--aggregation`` value before it goes into the request body.

    The value is a passthrough, since the schema endpoint is the real authority
    on which aggregations a metric supports, so an undocumented but legal name
    is accepted. What is refused is anything that is not a bare name, with or
    without a single dimension qualifier such as ``unique/visitor_id``.

    Raises:
        ConfigError: When the value cannot be an aggregation name.
    """
    value = aggregation.strip()
    if not value:
        raise ConfigError(
            f"--aggregation is empty; pass a name such as {DEFAULT_AGGREGATION}, "
            f"or one of {', '.join(KNOWN_AGGREGATIONS)}"
        )
    if not _AGGREGATION_RE.match(value):
        raise ConfigError(
            f"--aggregation {aggregation!r} is not an aggregation name; pass a "
            f"bare name such as {', '.join(KNOWN_AGGREGATIONS)}, optionally "
            "qualified by one dimension as in unique/visitor_id"
        )
    return value


def validate_percentile(percentile: int) -> str:
    """Turn ``--percentile`` into an aggregation name, or refuse it.

    Raises:
        ConfigError: When the percentile is not one of the four documented.
    """
    if percentile not in PERCENTILES:
        raise ConfigError(
            f"--percentile {percentile} is not one Vercel computes; the "
            f"percentiles are {', '.join(str(value) for value in PERCENTILES)}, "
            f"so pass one of those (the dashboard uses {DEFAULT_PERCENTILE}), or "
            "pass --aggregation for a non percentile aggregation such as max"
        )
    return f"p{percentile}"


def validate_limit(limit: int) -> int:
    """Check ``--limit`` against the bounds this client enforces.

    Raises:
        ConfigError: When outside ``1..100``.
    """
    if limit < MIN_LIMIT or limit > MAX_LIMIT:
        raise ConfigError(
            f"--limit {limit} is outside the bounds of {MIN_LIMIT} to {MAX_LIMIT}; "
            "pick a value in that range. On this surface the limit is the maximum "
            "number of grouped results per time bucket"
        )
    return limit


# ---------------------------------------------------------------------------
# Request building
# ---------------------------------------------------------------------------


def build_scope(
    *,
    project: str | None,
    all_projects: bool = False,
    team: str | None = None,
    team_slug: str | None = None,
) -> dict[str, Any]:
    """Build the ``scope`` object for a query body.

    ASSUMPTION. The OpenAPI document declares ``scope`` as a bare object, so
    its inner shape is inferred from what ``vercel metrics`` exposes: a project
    selection (``--project``, defaulting to the linked project), an every
    project selection (``--all``), and the ambient team. Hence a discriminated
    object with a ``type`` of ``project`` or ``owner``. The team is carried as
    a query parameter instead, which is the convention every other endpoint in
    this REST API follows.

    Raises:
        ConfigError: When neither a project nor ``--all`` was supplied.
    """
    if all_projects:
        return {"type": "owner"}
    if not project:
        raise ConfigError(
            "no project configured; pass --project with a project id or name, "
            "set VERCEL_PROJECT_ID in the environment, or pass --all to query "
            "every project in the team"
        )
    scope: dict[str, Any] = {"type": "project", "projectId": project}
    if team:
        scope["teamId"] = team
    elif team_slug:
        scope["slug"] = team_slug
    return scope


def build_granularity(interval: str) -> dict[str, Any]:
    """Build the ``granularity`` object for a query body.

    ASSUMPTION. The OpenAPI document declares ``granularity`` as a bare object
    too. The values ``1h``, ``1d`` and ``1mo`` are documented verbatim by the
    CLI; the key they sit under is not, and ``interval`` is this client's best
    reading of it. Omitting granularity entirely, which is what every preset
    but the trend does, makes the server choose a bucket size for the range.
    """
    return {"interval": interval}


def build_request(
    *,
    metric: Metric,
    since: datetime,
    until: datetime,
    project: str | None = None,
    all_projects: bool = False,
    aggregation: str = DEFAULT_AGGREGATION,
    group_by: Sequence[str] = (),
    filter_expr: str | None = None,
    limit: int | None = None,
    order_by: str | None = None,
    order_direction: str | None = None,
    granularity: str | None = None,
    bucket_timezone: str | None = None,
    team: str | None = None,
    team_slug: str | None = None,
    token: str | None = None,
) -> PreparedRequest:
    """Build the request that answers one Speed Insights query. Pure: no I/O.

    The URL and the method come from the ``observability_query`` entry of the
    operation allowlist, so neither is written down here. The token, when
    supplied, goes into the ``Authorization`` header and nowhere else: never
    into the body, which is why a dry run can print the body in full.

    Every optional field the caller did not ask for is left out of the body
    rather than sent as null, so the server applies its own default and the
    printed body says exactly what was requested and nothing more.

    Args:
        metric: The metric record to query, from :func:`validate_metric`.
        since: Start of the window, aware.
        until: End of the window, aware.
        project: Project id or name; omitted when ``all_projects`` is set.
        all_projects: Query every project in the team instead of one.
        aggregation: For example ``p75`` or ``sum``.
        group_by: Validated dimensions to group by.
        filter_expr: A combined OData expression, or ``None``.
        limit: Maximum grouped results per time bucket.
        order_by: ``count`` or ``value``; grouped queries only.
        order_direction: ``asc`` or ``desc``; grouped queries only.
        granularity: A bucket size already spelled for this surface (``1d``).
        bucket_timezone: IANA zone aligning calendar buckets.
        team: Team id, sent as a query parameter.
        team_slug: Team slug, sent as the ``slug`` query parameter.
        token: Access token for the ``Authorization`` header.

    Returns:
        The :class:`PreparedRequest` describing exactly one allowlisted call.
    """
    body: dict[str, Any] = {
        "metric": metric.id,
        "scope": build_scope(
            project=project,
            all_projects=all_projects,
            team=team,
            team_slug=team_slug,
        ),
        "aggregation": aggregation,
    }
    dimensions = list(group_by)
    if dimensions:
        body["groupBy"] = dimensions
    if filter_expr:
        body["filter"] = filter_expr
    if limit is not None:
        body["limit"] = limit
    if order_by:
        body["orderBy"] = order_by
    if order_direction:
        body["orderDirection"] = order_direction
    if granularity:
        body["granularity"] = build_granularity(granularity)
    body["startTime"] = to_api_timestamp(since)
    body["endTime"] = to_api_timestamp(until)
    if bucket_timezone:
        body["bucketTimezone"] = bucket_timezone

    params: list[tuple[str, str]] = []
    if team:
        params.append(("teamId", team))
    if team_slug:
        params.append(("slug", team_slug))

    return PreparedRequest(
        operation=OPERATION,
        url=operation_url(OPERATION),
        params=params,
        headers=default_headers(token),
        json_body=body,
    )


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

#: Keys a metric result might arrive under. Probed in this order, and the
#: first one present wins. None of this is pinned by the OpenAPI document.
_ROOT_KEYS: tuple[str, ...] = (
    "data",
    "result",
    "results",
    "series",
    "timeSeries",
    "buckets",
    "rows",
    "groups",
    "values",
    "points",
)

#: Keys the value of one row might arrive under, most specific first. The
#: metric id and the aggregation name are tried ahead of these.
_VALUE_KEYS: tuple[str, ...] = ("value", "result", "total", "aggregate", "y")

#: Keys a data point count might arrive under. The metric's own ``*_count`` id
#: is tried ahead of these.
_POINT_KEYS: tuple[str, ...] = (
    "dataPoints",
    "data_points",
    "sampleCount",
    "samples",
    "count",
    "n",
)

#: Keys carrying a bucket start, in preference order.
_TIME_KEYS: tuple[str, ...] = (
    "timestamp",
    "startTime",
    "start",
    "bucketStart",
    "time",
    "date",
    "ts",
)

#: Fields that describe the query rather than answer it. They are never a group
#: label, and never a metric value either: a response carrying nothing but an
#: envelope has no value in it, and reading ``{"version": 1}`` as a P75 of 1 ms
#: would print a confidently formatted wrong figure.
_ENVELOPE_KEYS: frozenset[str] = frozenset(
    {"version", "query", "metric", "scope", "aggregation", "granularity", "unit"}
)

#: Envelope keys that are never a group label.
_RESERVED_KEYS: frozenset[str] = frozenset(
    _ENVELOPE_KEYS
    | set(_ROOT_KEYS)
    | set(_VALUE_KEYS)
    | set(_POINT_KEYS)
    | set(_TIME_KEYS)
)

_MAX_UNWRAP_DEPTH = 3


def _is_number(value: Any) -> TypeGuard[float]:
    """True for a real JSON number. Booleans are not numbers for our purposes."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _stringify(value: Any) -> str:
    """Render a group label value that may be a string, number, bool or null."""
    if value is None:
        return "(none)"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value or "(empty)"
    return str(value)


def _find_root(payload: Mapping[str, Any]) -> Any:
    """The part of the payload that actually carries the result.

    The envelope is not pinned down, so every plausible container key is
    probed in turn and the payload itself is the last resort, which is what
    makes a bare ``{"value": 1234}`` parse as well as a wrapped one.
    """
    for key in _ROOT_KEYS:
        if key in payload and payload[key] is not None:
            return payload[key]
    return payload


def _unwrap(node: Any, depth: int = 0) -> Any:
    """Follow a chain of single key containers down to the real payload."""
    if depth >= _MAX_UNWRAP_DEPTH or not isinstance(node, Mapping):
        return node
    for key in _ROOT_KEYS:
        if key in node and node[key] is not None:
            return _unwrap(node[key], depth + 1)
    return node


def _lookup(entry: Mapping[str, Any], names: Sequence[str]) -> tuple[str, float] | None:
    """The first numeric field among ``names``, with the key it came from."""
    for name in names:
        value = entry.get(name)
        if _is_number(value):
            return name, float(value)
    return None


def _value_keys(metric: Metric, aggregation: str) -> tuple[str, ...]:
    """Every key the value of one row might sit under, most specific first."""
    return (
        metric.id,
        metric.id.split(".")[-1],
        aggregation,
        aggregation.split("/")[0],
        *_VALUE_KEYS,
        metric.short,
    )


def _sole_number(entry: Mapping[str, Any], used: set[str]) -> tuple[str, float] | None:
    """The only numeric field left, when a row carries exactly one.

    Last resort for a row whose value arrived under a name none of the probes
    predicted. One candidate is unambiguous; two or more is not, so nothing is
    guessed in that case. An envelope field is never a candidate, however alone
    it stands: a payload that carried only a schema version carried no value.
    """
    candidates = [
        (name, float(value))
        for name, value in entry.items()
        if name not in used and name not in _ENVELOPE_KEYS and _is_number(value)
    ]
    return candidates[0] if len(candidates) == 1 else None


def _labels_from(
    entry: Mapping[str, Any], dimensions: Sequence[str], used: set[str]
) -> tuple[str | None, ...]:
    """One label per grouped dimension, claimed by name then by fallback."""
    claimed: list[str | None] = []
    for dimension in dimensions:
        chosen: str | None = None
        if dimension in entry and dimension not in used:
            chosen = dimension
        if chosen is not None:
            used.add(chosen)
        claimed.append(chosen)

    for index, chosen in enumerate(claimed):
        if chosen is not None:
            continue
        for name, value in entry.items():
            if name in used or name in _RESERVED_KEYS or not isinstance(value, str):
                continue
            used.add(name)
            claimed[index] = name
            break

    return tuple(
        _stringify(entry[name]) if name is not None else None for name in claimed
    )


def _row_from_entry(
    entry: Mapping[str, Any],
    metric: Metric,
    aggregation: str,
    dimensions: Sequence[str],
    timestamp: str | None,
) -> Row | None:
    """Turn one response object into a :class:`Row`, or ``None`` if it is not one.

    Returning ``None`` rather than raising is what keeps an unfamiliar entry
    from taking the whole response down: the caller decides whether no usable
    row at all is an error.
    """
    used: set[str] = set()
    own_timestamp = timestamp
    for key in _TIME_KEYS:
        candidate = entry.get(key)
        if isinstance(candidate, str) and candidate:
            own_timestamp = candidate
            used.add(key)
            break
        if _is_number(candidate):
            own_timestamp = _stringify(candidate)
            used.add(key)
            break

    labels = _labels_from(entry, dimensions, used)

    found = _lookup(entry, _value_keys(metric, aggregation))
    if found is None:
        found = _sole_number(entry, used | {DATA_POINTS_METRIC})
    if found is None:
        return None
    value_key, value = found
    used.add(value_key)

    metrics = {metric.column(aggregation): value}
    points = _lookup(entry, (metric.count_id, *_POINT_KEYS))
    if points is not None and points[0] != value_key:
        metrics[DATA_POINTS_METRIC] = points[1]

    return Row(
        labels=labels,
        metrics=metrics,
        timestamp=own_timestamp,
        is_others=OTHERS_LABEL in labels or own_timestamp == OTHERS_LABEL,
    )


def _nested_entries(entry: Mapping[str, Any]) -> list[Mapping[str, Any]] | None:
    """The grouped rows nested inside one time bucket, if there are any."""
    for key in _ROOT_KEYS:
        nested = entry.get(key)
        if isinstance(nested, list) and nested:
            rows = [item for item in nested if isinstance(item, Mapping)]
            if rows:
                return rows
    return None


def _rows_from_list(
    entries: Sequence[Any],
    metric: Metric,
    aggregation: str,
    dimensions: Sequence[str],
) -> tuple[list[Row], int]:
    """Parse a list of rows or time buckets. Returns the rows and how many failed."""
    rows: list[Row] = []
    skipped = 0
    for entry in entries:
        if not isinstance(entry, Mapping):
            skipped += 1
            continue
        nested = _nested_entries(entry)
        if nested is not None:
            timestamp = None
            for key in _TIME_KEYS:
                candidate = entry.get(key)
                if isinstance(candidate, str) and candidate:
                    timestamp = candidate
                    break
            for item in nested:
                row = _row_from_entry(item, metric, aggregation, dimensions, timestamp)
                if row is None:
                    skipped += 1
                else:
                    rows.append(row)
            continue
        row = _row_from_entry(entry, metric, aggregation, dimensions, None)
        if row is None:
            skipped += 1
        else:
            rows.append(row)
    return rows, skipped


def _rollup_rows(
    node: Mapping[str, Any], metric: Metric, aggregation: str
) -> list[Row] | None:
    """Parse a rollup keyed by dimension value, or ``None`` if it is not one.

    Both ``{"US": 640}`` and ``{"US": {"value": 640, "count": 30}}`` are read;
    a mapping carrying anything else under a non envelope key is not a rollup.
    """
    rows: list[Row] = []
    for key, value in node.items():
        if key in _RESERVED_KEYS:
            continue
        if _is_number(value):
            rows.append(
                Row(
                    labels=(_stringify(key),),
                    metrics={metric.column(aggregation): float(value)},
                    is_others=key == OTHERS_LABEL,
                )
            )
            continue
        if isinstance(value, Mapping):
            nested = _row_from_entry(value, metric, aggregation, (), None)
            if nested is None:
                return None
            rows.append(
                Row(
                    labels=(_stringify(key),),
                    metrics=nested.metrics,
                    timestamp=nested.timestamp,
                    is_others=key == OTHERS_LABEL,
                )
            )
            continue
        return None
    return rows or None


def _rows_from_mapping(
    node: Mapping[str, Any],
    metric: Metric,
    aggregation: str,
    dimensions: Sequence[str],
) -> list[Row] | None:
    """Parse a mapping: one metric value, or a rollup keyed by dimension value.

    Which reading is tried first depends on what was asked for, because a one
    entry mapping is genuinely ambiguous: ``{"US": 640}`` is a rollup when a
    grouping was requested and a stray value field when it was not.

    Returns ``None`` when the mapping is neither, which the caller reports as
    an unreadable response rather than as an empty one.
    """
    if dimensions:
        rollup = _rollup_rows(node, metric, aggregation)
        if rollup is not None:
            return rollup
        row = _row_from_entry(node, metric, aggregation, dimensions, None)
        return [row] if row is not None else None

    row = _row_from_entry(node, metric, aggregation, (), None)
    if row is not None:
        return [row]
    return _rollup_rows(node, metric, aggregation)


def _shape_error(payload_type: str) -> str:
    """Describe a response this client cannot read, without echoing content."""
    return (
        "the Speed Insights query succeeded but returned a result this client "
        f"cannot read: {payload_type}. The observability API does not publish a "
        "response schema, so this client probes for a metric value, rollups "
        "keyed by dimension, and time buckets; none of those was present. Run "
        "with --json to see the untouched payload, and report the shape so the "
        "parser can learn it"
    )


def normalize(
    payload: Mapping[str, Any],
    *,
    metric: Metric,
    aggregation: str = DEFAULT_AGGREGATION,
    group_by: Sequence[str] = (),
    granularity: str | None = None,
    status: int = 200,
) -> Result:
    """Turn a raw observability response into a :class:`Result`.

    The 200 body is declared as a bare object in the OpenAPI document, so there
    is no single shape to parse. This probes, in order, for a wrapper key, a
    single metric value, rollups keyed by dimension value, a list of grouped
    rows, and a list of time buckets with rows nested inside them, and reads
    the value, the group labels and the data point count out of whichever it
    finds. Nothing is required: a field this client does not recognise is left
    alone, and a row it cannot read is skipped rather than raised on.

    An unreadable response is reported as an ``invalid_response``
    :class:`ApiError` naming what was expected, exactly as the Web Analytics
    normalizer does. A KeyError never reaches the caller.

    Args:
        payload: The decoded response body.
        metric: The metric that was queried.
        aggregation: The aggregation that was requested, used to name the
            value column and to decide whether the rows can be summed.
        group_by: The grouping that was requested.
        granularity: The bucket size that was requested, in this surface's
            spelling, or ``None`` when the server chose one.
        status: The HTTP status the body arrived with, used in the error when
            the shape is unreadable. Only 2xx bodies ever reach this function.

    Returns:
        A :class:`Result` ready to format.

    Raises:
        ApiError: When the response carries nothing this client can read.
    """
    dimensions = list(group_by)
    query = payload.get("query")
    query_block: dict[str, Any] = dict(query) if isinstance(query, Mapping) else {}

    root = _unwrap(_find_root(payload))

    rows: list[Row] | None
    if _is_number(root):
        rows = [Row(metrics={metric.column(aggregation): float(root)})]
    elif isinstance(root, list):
        # An empty list is an empty result, which is success. A non empty list
        # that yielded no readable row is not.
        parsed, _skipped = _rows_from_list(root, metric, aggregation, dimensions)
        rows = parsed if parsed or not root else None
    elif isinstance(root, Mapping):
        rows = _rows_from_mapping(root, metric, aggregation, dimensions)
    else:
        rows = None

    if rows is None:
        raise ApiError(status, "invalid_response", _shape_error(_describe(root)))

    value_column = metric.column(aggregation)
    metric_names = [value_column]
    if any(DATA_POINTS_METRIC in row.metrics for row in rows):
        metric_names.append(DATA_POINTS_METRIC)
        for row in rows:
            row.metrics.setdefault(DATA_POINTS_METRIC, 0.0)

    has_time = any(row.timestamp for row in rows)
    return Result(
        rows=rows,
        is_count=not dimensions and not has_time,
        dataset=DATASET,
        group_by=dimensions,
        query=query_block,
        metric_names=metric_names,
        fallback_metrics=(value_column,),
        metric=metric.id,
        metric_label=metric.label,
        unit=metric.unit,
        target=metric.target,
        time_bucket=granularity if has_time else None,
        additive=aggregation.split("/")[0] in ADDITIVE_AGGREGATIONS,
    )


def _describe(node: Any) -> str:
    """Name the shape of an unreadable response without quoting its content."""
    if node is None:
        return "it was missing or null"
    if isinstance(node, Mapping):
        return f"a JSON object with {len(node)} field(s)"
    if isinstance(node, list):
        return f"a JSON array of {len(node)} entry/entries"
    return f"a {type(node).__name__}"
