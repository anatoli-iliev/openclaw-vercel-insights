"""Argument parsing, settings resolution and ``main()``.

Usage
-----
    export VERCEL_TOKEN=...          # a Vercel access token
    export VERCEL_PROJECT_ID=prj_... # project id or project name

    python3 -m vercel_insights                        # 7 day overview
    python3 -m vercel_insights top-pages --since 30d  # a single table
    python3 -m vercel_insights events --event-property plan --json
    python3 -m vercel_insights vitals                 # the five web vitals

Run ``--list-presets`` for the full preset table and ``--help`` for every flag.
Add ``--dry-run`` to print the exact request that would be sent without sending
anything; it works even with no token configured.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, TextIO

import requests

from . import (
    DOCS_TOKEN_URL,
    OTHERS_LABEL,
    VERSION,
    ApiError,
    ConfigError,
    RateLimitError,
)
from .budgets import BUDGET_EXCEEDED, any_failed, evaluate, parse_budgets
from .http import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT,
    PreparedRequest,
    execute,
    format_dry_run,
    redact_headers,
    validate_timeout,
    validate_token,
)
from .odata import build_clause, combine_filters, json_dimension
from .presets import DEFAULT_METRIC, DEFAULT_PRESET, PRESETS, Preset, format_presets
from .projects import (
    build_list_request as build_projects_request,
)
from .projects import (
    build_one_request as build_project_request,
)
from .projects import (
    extract_projects,
    format_projects,
    looks_like_project_id,
    owner_from_project,
    resolve_project_id,
)
from .render import (
    DATA_POINTS_METRIC,
    OVERVIEW_TABLE_LIMIT,
    Result,
    Style,
    _result_document,
    format_csv,
    format_json,
    format_table,
    format_value,
    render_overview,
    render_vitals,
)
from .speedinsights import (
    COUNT_AGGREGATION,
    DEFAULT_AGGREGATION,
    KNOWN_AGGREGATIONS,
    METRIC_HELP,
    ORDER_BY_VALUES,
    ORDER_DIRECTIONS,
    PERCENTILES,
    SPEED_DIMENSIONS,
    VITAL_ORDER,
    Metric,
    build_schema_request,
    format_schema,
    metric_for,
    validate_aggregation,
    validate_metric,
    validate_percentile,
    warn_if_not_project_id,
)
from .speedinsights import DATASET as SPEED_INSIGHTS_DATASET
from .speedinsights import (
    METRICS as KNOWN_METRICS,
)
from .speedinsights import OPERATION as OBSERVABILITY_QUERY
from .speedinsights import build_request as build_speed_request
from .speedinsights import normalize as normalize_speed
from .speedinsights import validate_group_by as validate_speed_group_by
from .speedinsights import validate_limit as validate_speed_limit
from .timerange import (
    ACCEPTED_GRANULARITIES,
    SPEED_INSIGHTS,
    TIME_GRANULARITIES,
    TIME_HELP,
    WEB_ANALYTICS,
    granularity_meaning,
    normalize_granularity,
    reporting_window_warning,
    resolve_range,
    to_api_timestamp,
)
from .webanalytics import (
    DATASETS,
    DEFAULT_LIMIT,
    MAX_LIMIT,
    MIN_LIMIT,
    VISIT_DIMENSIONS,
    build_request,
    normalize,
    select_endpoint,
    validate_group_by,
    validate_limit,
)

PROG = "vercel-insights"

DEFAULT_SINCE = "7d"
DEFAULT_UNTIL = "now"

EPILOG = f"""\
examples:
  # Last 7 days at a glance for the configured project
  {PROG}

  # Top 20 pages over the last 30 days, US traffic only
  {PROG} top-pages --limit 20 --since 30d --country US

  # Daily page view trend for one framework route, as CSV
  {PROG} trend --route '/blog/[slug]' --since 4w --csv

  # Custom events broken down by the "plan" event property
  {PROG} events --event-property plan --since 30d --json

  # Show exactly what would be requested, and send nothing
  {PROG} referrers --since 2026-01-01 --until 2026-02-01 --dry-run

  # The five web vitals at P75, against Vercel's published targets
  {PROG} vitals --since 7d

  # The slowest routes by P75 LCP, on mobile only
  {PROG} slowest-pages --device mobile --limit 20

  # Daily P75 INP for one route, production traffic only
  {PROG} vitals-trend --metric inp --route '/blog/[slug]' --environment production

environment:
  VERCEL_TOKEN       access token, used only in the Authorization header
  VERCEL_PROJECT_ID  project id or project name
  VERCEL_TEAM_ID     team id, for team owned projects
  VERCEL_TEAM_SLUG   team slug, an alternative to the team id
  VERCEL_OWNER_ID    account id owning the project (Speed Insights scope)
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
        prog=PROG,
        description=(
            "Query the Vercel Web Analytics and Speed Insights APIs from the "
            "command line. Read only: every request comes from a fixed operation "
            "allowlist, and the access token is sent only in the Authorization "
            "header."
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
    config.add_argument(
        "--budget",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help=(
            "fail with exit code 3 when a web vital exceeds VALUE, for example "
            "--budget lcp=2500 or --budget cls=0.1; repeatable, and intended "
            "for CI. A metric with no data does not fail"
        ),
    )
    config.add_argument(
        "--list-projects",
        action="store_true",
        help=(
            "list the account's projects with their ids, and whether each has "
            "Web Analytics and Speed Insights data; use it to find what to "
            "pass to --project"
        ),
    )
    config.add_argument(
        "--list-metrics",
        nargs="?",
        const="",
        metavar="PREFIX",
        help=(
            "ask the API which metrics this account can actually query, "
            "optionally filtered by a prefix such as vercel.speed_insights; "
            "this is the source of truth when a query is refused"
        ),
    )
    config.add_argument(
        "--owner-id",
        metavar="ID",
        help=(
            "account that owns the project, required by a Speed Insights scope; "
            "defaults to $VERCEL_OWNER_ID, then to the team, then to the "
            "personal account read from the API"
        ),
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
            "flags/<name> works on both. Speed Insights spells its dimensions "
            "in snake_case and accepts: " + ", ".join(SPEED_DIMENSIONS)
        ),
    )
    shape.add_argument(
        "--granularity",
        choices=ACCEPTED_GRANULARITIES,
        default=None,
        metavar="BUCKET",
        help=(
            "time bucket, replacing the preset's own: "
            + ", ".join(ACCEPTED_GRANULARITIES)
            + ". Both vocabularies are accepted and translated per API; week "
            "and year exist on Web Analytics only"
        ),
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

    speed = parser.add_argument_group(
        "speed insights",
        "Only meaningful with a Speed Insights preset (vitals, slowest-pages, "
        "fastest-pages, vitals-by-country, vitals-by-device, vitals-trend, "
        "data-points). That API answers for one metric per request.",
    )
    speed.add_argument(
        "--metric",
        metavar="NAME",
        default=None,
        help=(
            f"which web vital to report: {METRIC_HELP}. Real Experience Score "
            "is not queryable through any API; read it on the dashboard"
        ),
    )
    speed.add_argument(
        "--percentile",
        metavar="N",
        type=int,
        default=None,
        help=(
            "percentile to report, one of "
            + ", ".join(str(value) for value in PERCENTILES)
            + f" (default {DEFAULT_AGGREGATION[1:]}, as on the dashboard)"
        ),
    )
    speed.add_argument(
        "--aggregation",
        metavar="NAME",
        default=None,
        help=(
            "aggregation to request instead of a percentile, for example "
            + ", ".join(KNOWN_AGGREGATIONS)
        ),
    )
    speed.add_argument(
        "--order-by",
        dest="order_by",
        metavar="COLUMN",
        default=None,
        help=(
            "rollup column to order grouped results by: "
            + ", ".join(ORDER_BY_VALUES)
            + " (default count, so a group with few data points does not lead)"
        ),
    )
    speed.add_argument(
        "--order",
        metavar="DIRECTION",
        default=None,
        help="order grouped results " + " or ".join(ORDER_DIRECTIONS) + " (default desc)",
    )
    speed.add_argument(
        "--bucket-timezone",
        dest="bucket_timezone",
        metavar="IANA",
        default=None,
        help=(
            "IANA zone aligning daily and monthly buckets, for example "
            "Europe/Paris; timestamps stay UTC and sub-daily buckets ignore it"
        ),
    )
    speed.add_argument(
        "--all",
        dest="all_projects",
        action="store_true",
        help="query every project in the team; mutually exclusive with --project",
    )
    speed.add_argument(
        "--data-points",
        dest="data_points",
        action="store_true",
        help=(
            "report how many measurements were collected instead of the metric "
            "value; a percentile over few data points is not comparable to one "
            "over many"
        ),
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
            "only 408, 429 and 5xx responses and network failures are retried"
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
    #: Which API this run talks to, decided by the preset.
    surface: str = WEB_ANALYTICS
    #: Speed Insights only: the metrics to query, one request each. The vitals
    #: preset holds five; every other Speed Insights preset holds one.
    metrics: tuple[Metric, ...] = ()
    #: ``None`` for a metric outside the web vitals, where the server's own
    #: default is better than any guess this client could make.
    aggregation: str | None = DEFAULT_AGGREGATION
    all_projects: bool = False
    order_by: str | None = None
    order_direction: str | None = None
    granularity: str | None = None
    bucket_timezone: str | None = None
    #: Speed Insights only. A scope requires an ownerId, and for a team the
    #: team id IS the owner. For a personal account it is read once from the
    #: user endpoint at run time, because nothing else knows it.
    owner_id: str | None = None

    @property
    def aggregation_label(self) -> str:
        """What to call the value column when no aggregation was requested.

        The request omits the field so the server applies the metric's own
        default, but a column still needs a name, and "value" is honest where a
        specific aggregation was never asked for.
        """
        return self.aggregation or "value"

    @property
    def is_speed(self) -> bool:
        """True when this run queries the Speed Insights surface."""
        return self.surface == SPEED_INSIGHTS

    @property
    def project_label(self) -> str:
        """How to name what was queried, in a heading or an empty result line."""
        return self.project or "every project in the team"


def _env_value(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name)
    return value.strip() or None if value else None


#: Every filter shorthand, in the order its clause is emitted, with the
#: dimension it compiles to on each surface. The two APIs name the same thing
#: differently, so the spelling follows the surface the query is going to, and
#: ``None`` marks a shorthand that surface has no dimension for at all.
FILTER_SHORTHANDS: tuple[tuple[str, str, str | None], ...] = (
    ("--path", "requestPath", "request_path"),
    ("--route", "route", "route"),
    ("--country", "country", "country"),
    ("--device", "deviceType", "device_type"),
    ("--browser", "browserName", None),
    ("--os", "osName", None),
    ("--referrer", "referrerHostname", None),
    ("--utm-source", "utmSource", None),
    ("--utm-medium", "utmMedium", None),
    ("--utm-campaign", "utmCampaign", None),
    ("--environment", "environment", "environment"),
)


def _shorthand_values(args: argparse.Namespace) -> dict[str, str | None]:
    """What the user passed for each shorthand, keyed by the flag itself."""
    return {
        "--path": args.path,
        "--route": args.route,
        "--country": args.country,
        "--device": args.device,
        "--browser": args.browser,
        "--os": args.os_name,
        "--referrer": args.referrer,
        "--utm-source": args.utm_source,
        "--utm-medium": args.utm_medium,
        "--utm-campaign": args.utm_campaign,
        "--environment": args.environment,
    }


def _resolve_filters(
    args: argparse.Namespace, dataset: str, surface: str = WEB_ANALYTICS
) -> str | None:
    """Turn every filter flag into one combined OData expression.

    A shorthand compiles to the dimension name of the surface the query is
    actually going to, and a shorthand the active surface has no dimension for
    is a configuration error naming why, never a clause the API would reject.
    """
    speed = surface == SPEED_INSIGHTS
    values = _shorthand_values(args)

    clauses: list[str] = []
    for flag, web_name, speed_name in FILTER_SHORTHANDS:
        value = values[flag]
        if not value:
            continue
        dimension = speed_name if speed else web_name
        if dimension is None:
            raise ConfigError(
                f"{flag} {value!r} is a Web Analytics filter: Speed Insights "
                f"collects no {web_name} dimension, so it cannot filter on one. "
                f"That surface filters on {', '.join(SPEED_DIMENSIONS)}; drop "
                f"the flag, or run a Web Analytics preset instead"
            )
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
        group_by.append(normalize_granularity(args.granularity, WEB_ANALYTICS))

    if args.event_property:
        group_by.append(json_dimension("eventData", args.event_property))

    return group_by


#: The Speed Insights presets, named in the error that rejects a Speed
#: Insights option on the other surface.
SPEED_PRESET_NAMES = ", ".join(
    name for name, preset in PRESETS.items() if preset.is_speed
)

#: Options that only mean something on the Speed Insights surface, paired with
#: how to read whether the user actually passed one.
SPEED_ONLY_OPTIONS: tuple[tuple[str, str], ...] = (
    ("--metric", "metric"),
    ("--percentile", "percentile"),
    ("--aggregation", "aggregation"),
    ("--order-by", "order_by"),
    ("--order", "order"),
    ("--bucket-timezone", "bucket_timezone"),
    ("--all", "all_projects"),
    ("--data-points", "data_points"),
)

#: Options that only mean something on the Web Analytics surface. The filter
#: shorthands are handled by :data:`FILTER_SHORTHANDS`; these are the rest.
WEB_ONLY_OPTIONS: tuple[tuple[str, str, str], ...] = (
    ("--dataset", "dataset", "Speed Insights has no datasets: it queries one "
     "metric at a time, chosen with --metric"),
    ("--event-name", "event_name", "Speed Insights does not collect custom events"),
    ("--event-property", "event_property", "Speed Insights does not collect "
     "custom events, so it has no event properties to break out"),
    ("--flag", "flag", "Speed Insights does not collect feature flag values"),
)

#: A bucket timezone is an IANA zone name such as ``Europe/Paris`` or ``UTC``.
_TIMEZONE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+_-]*(/[A-Za-z0-9+_.-]+){0,2}$")


def _reject_cross_surface_options(args: argparse.Namespace, preset: Preset) -> None:
    """Rules 14, 15 and 22: an option used on the surface it does not belong to.

    Rule 14 first, because ``--dataset`` with ``--metric`` names a conflict
    between two options rather than between an option and a preset, and that
    is the more specific complaint.
    """
    if args.dataset and args.metric:
        raise ConfigError(
            f"--dataset {args.dataset!r} and --metric {args.metric!r} select "
            "different APIs and are mutually exclusive: --dataset queries Web "
            "Analytics page views or custom events, --metric queries a Speed "
            "Insights web vital. Keep one, and pick a preset for that surface"
        )

    if preset.is_speed:
        for flag, attribute, reason in WEB_ONLY_OPTIONS:
            value = getattr(args, attribute)
            if not value:
                continue
            raise ConfigError(
                f"{flag} has no meaning on the {preset.name} preset, which "
                f"queries Speed Insights: {reason}. Drop the flag, or run a Web "
                "Analytics preset such as top-pages"
            )
        return

    for flag, attribute in SPEED_ONLY_OPTIONS:
        value = getattr(args, attribute)
        if value is None or value is False:
            continue
        shown = f" {value!r}" if not isinstance(value, bool) else ""
        raise ConfigError(
            f"{flag}{shown} only applies to the Speed Insights surface, but the "
            f"{preset.name} preset queries Web Analytics. Run one of "
            f"{SPEED_PRESET_NAMES}, or drop the flag"
        )


def _resolve_aggregation(
    args: argparse.Namespace, preset: Preset, metrics: Sequence[Metric]
) -> str | None:
    """Resolve the aggregation from --aggregation, --percentile or the preset.

    A data point count is a count, so when the user asked for one without
    naming an aggregation it is summed rather than run through the percentile
    default: the 75th percentile of a number of measurements answers nothing.
    """
    if args.aggregation and args.percentile is not None:
        raise ConfigError(
            f"--aggregation {args.aggregation!r} and --percentile "
            f"{args.percentile} both set the aggregation; --percentile "
            f"{args.percentile} is shorthand for --aggregation p{args.percentile}, "
            "so pass one of them"
        )
    if args.aggregation:
        return validate_aggregation(args.aggregation)
    if args.percentile is not None:
        return validate_percentile(args.percentile)
    if preset.aggregation:
        return preset.aggregation
    if metrics and all(metric.is_count for metric in metrics):
        return COUNT_AGGREGATION
    if metrics and any(metric.id not in KNOWN_METRICS for metric in metrics):
        # Outside the web vitals this client does not know what the metric
        # measures, and the 75th percentile of a request count answers nothing.
        # Omitting the field lets the server apply the metric's own default,
        # which the schema publishes and this client would only be copying.
        return None
    return DEFAULT_AGGREGATION


def _resolve_metrics(args: argparse.Namespace, preset: Preset) -> tuple[Metric, ...]:
    """Which metric or metrics this run queries, one request each."""
    if preset.metric == "*":
        return tuple(
            metric_for(short, data_points=args.data_points) for short in VITAL_ORDER
        )
    name = args.metric or preset.metric or DEFAULT_METRIC
    return (metric_for(name, data_points=args.data_points or preset.data_points),)


def _resolve_speed_ordering(
    args: argparse.Namespace, preset: Preset, group_by: Sequence[str]
) -> tuple[str | None, str | None]:
    """Rule 20: ordering applies to grouped results, so refuse it without one."""
    if (args.order_by or args.order) and not group_by:
        flags = " and ".join(
            flag
            for flag, value in (("--order-by", args.order_by), ("--order", args.order))
            if value
        )
        raise ConfigError(
            f"{flags} orders the rows of a grouped query, but this one is not "
            "grouped, so there is nothing to order. Add --group-by "
            f"{SPEED_DIMENSIONS[0]} (or run slowest-pages, vitals-by-country or "
            "another grouped preset), or drop the flag"
        )

    order_by = args.order_by or preset.order_by
    if order_by is not None and order_by not in ORDER_BY_VALUES:
        raise ConfigError(
            f"--order-by {order_by!r} is not a rollup column; the columns are "
            f"{', '.join(ORDER_BY_VALUES)}, where count is the number of data "
            "points behind each group and value is the metric itself"
        )

    order = args.order or preset.order
    if order is not None and order not in ORDER_DIRECTIONS:
        raise ConfigError(
            f"--order {order!r} is not a direction; pass "
            f"{' or '.join(ORDER_DIRECTIONS)}"
        )
    return order_by, order


def _resolve_bucket_timezone(
    args: argparse.Namespace, granularity: str | None, warnings: list[str]
) -> str | None:
    """Rule 21: a sub-daily bucket ignores the zone, so warn rather than refuse."""
    zone: str | None = args.bucket_timezone
    if not zone:
        return None
    if not _TIMEZONE_RE.match(zone):
        raise ConfigError(
            f"--bucket-timezone {zone!r} is not an IANA zone name; pass one such "
            "as Europe/Paris, America/New_York or UTC"
        )
    if granularity is not None and granularity_meaning(granularity) == "hour":
        warnings.append(
            f"--bucket-timezone {zone} aligns calendar buckets only, so it has "
            f"no effect at --granularity {args.granularity}; it is still sent, "
            "and the API ignores it. Use a daily or monthly bucket to see it work"
        )
    return zone


def _resolve_settings(args: argparse.Namespace, env: Mapping[str, str]) -> Settings:
    """Apply every validation rule, in order, before anything touches the network."""
    preset_name = args.preset
    if preset_name is None and args.metric:
        # Naming a metric is unambiguous about intent, and the default preset
        # reports traffic, which is a different API entirely. Without this the
        # only way to query one of the other 90-odd metrics would be to pick an
        # unrelated speed preset first, which reads like a workaround because
        # it is one.
        preset_name = "metric"
    preset = PRESETS[preset_name or DEFAULT_PRESET]

    if args.json and args.csv:
        raise ConfigError(
            "--json and --csv are mutually exclusive; pick one output format"
        )

    _reject_cross_surface_options(args, preset)
    speed = preset.is_speed
    dataset = args.dataset or preset.dataset

    if args.all_projects and args.project:
        raise ConfigError(
            f"--all and --project {args.project!r} are mutually exclusive: --all "
            "queries every project in the team, --project queries one. Keep one "
            "of them"
        )

    project = args.project or _env_value(env, "VERCEL_PROJECT_ID")
    if args.all_projects:
        project = None
    if not project and not args.all_projects:
        # Raised as its own type so main() can answer the question the user
        # actually has ("which projects do I have?") instead of only telling
        # them a flag is missing. One account holds many projects, so that
        # list is the whole answer.
        raise MissingProject(
            "no project configured; pass --project with a project id or name, "
            "or set VERCEL_PROJECT_ID in the environment"
            + (", or pass --all to query every project in the team" if speed else "")
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
    # A team is its own owner, so a team id doubles as the ownerId a Speed
    # Insights scope requires. Only a personal account needs the lookup.
    # VERCEL_ORG_ID is Vercel's own name for the owning account, set by `vercel
    # link` and used across their tooling, so it is read before falling back to
    # the team. VERCEL_OWNER_ID is accepted too because it names what the API
    # field is actually called.
    owner_id = (
        args.owner_id
        or _env_value(env, "VERCEL_OWNER_ID")
        or _env_value(env, "VERCEL_ORG_ID")
        or team
    )
    if preset.surface == SPEED_INSIGHTS and team_slug and not owner_id:
        # A slug names a team but is not an account id, and scope.ownerId wants
        # an id. Falling through to the personal account lookup here would
        # silently answer for the wrong account rather than failing, which is
        # the worst outcome available.
        raise ConfigError(
            f"--team-slug {team_slug!r} cannot scope a Speed Insights query on "
            "its own: that surface needs the account id, and a slug is a name. "
            "Pass --team with the team id (Team Settings, General), or "
            "--owner-id. A slug still works for Web Analytics presets"
        )
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

    if preset.metric == "*" and args.group_by:
        raise ConfigError(
            f"the {preset.name} preset issues one query per web vital, so "
            "--group-by has no meaning there; use vitals-by-country, "
            "vitals-by-device or --group-by with another Speed Insights preset"
        )

    if preset.metric == "*" and args.csv:
        raise ConfigError(
            f"--csv needs a single table, but the {preset.name} preset issues one "
            "query per web vital; use vitals-trend, slowest-pages or another "
            "single query preset with --csv instead"
        )

    if preset.metric == "*" and args.metric:
        # Validate the name first, so that naming something unqueryable gets
        # the specific answer rather than the generic one: --metric res must
        # say that Real Experience Score cannot be queried at all, which is
        # true of every preset, before this says that this preset reports all
        # five anyway.
        validate_metric(args.metric)
        raise ConfigError(
            f"--metric {args.metric!r} has no meaning on the {preset.name} "
            f"preset: {preset.name} reports all five web vitals, one query "
            "each. Use vitals-trend, vitals-by-country, vitals-by-device or "
            "slowest-pages for a single metric"
        )

    warnings: list[str] = []
    metrics: tuple[Metric, ...] = ()
    aggregation: str | None = DEFAULT_AGGREGATION
    granularity: str | None = None
    order_by: str | None = None
    order_direction: str | None = None
    bucket_timezone: str | None = None

    if speed:
        metrics = _resolve_metrics(args, preset)
        aggregation = _resolve_aggregation(args, preset, metrics)
        known = all(metric.id in KNOWN_METRICS for metric in metrics)
        group_by = validate_speed_group_by(
            [dim for dim in (args.group_by or []) if dim] or list(preset.group_by),
            known_metric=known,
        )
        granularity = (
            normalize_granularity(args.granularity, SPEED_INSIGHTS)
            if args.granularity
            else preset.granularity
        )
        order_by, order_direction = _resolve_speed_ordering(args, preset, group_by)
        bucket_timezone = _resolve_bucket_timezone(args, granularity, warnings)
        limit = args.limit if args.limit is not None else preset.limit
        if limit is not None:
            limit = validate_speed_limit(limit)
        if not group_by:
            # The limit bounds grouped results per bucket, so an ungrouped
            # query has nothing to bound and the field is left out entirely.
            limit = None
    else:
        group_by = validate_group_by(_resolve_group_by(args, preset), dataset)
        limit = args.limit if args.limit is not None else preset.limit
        if limit is not None:
            limit = validate_limit(limit)
        if args.environment == "preview" and select_endpoint(group_by) == "count":
            raise ConfigError(
                "--environment preview cannot be used with a count query: the "
                "count endpoints report production traffic only. Add --group-by "
                "day (or any other dimension) so the aggregate endpoint is used "
                "instead"
            )

    filter_expr = _resolve_filters(args, dataset, preset.surface)

    now = datetime.now(timezone.utc)
    time_range = resolve_range(args.since, args.until, now)

    warning = reporting_window_warning(time_range[0], now)
    if warning:
        warnings.append(warning)

    if preset.surface == SPEED_INSIGHTS and not args.all_projects:
        # This surface scopes by projectIds, so a project name is likely to come
        # back empty rather than as an error, which is the worst kind of wrong.
        id_warning = warn_if_not_project_id(project or None)
        if id_warning:
            warnings.append(id_warning)

    return Settings(
        preset=preset,
        dataset=dataset,
        project=project or "",
        token=token,
        team=team,
        team_slug=team_slug,
        owner_id=owner_id,
        group_by=group_by,
        limit=limit,
        filter_expr=filter_expr,
        time_range=time_range,
        timeout=timeout,
        warnings=warnings,
        surface=preset.surface,
        metrics=metrics,
        aggregation=aggregation,
        all_projects=bool(args.all_projects),
        order_by=order_by,
        order_direction=order_direction,
        granularity=granularity,
        bucket_timezone=bucket_timezone,
    )


def _plan_speed_requests(settings: Settings) -> list[PreparedRequest]:
    """One Speed Insights request per metric: that API answers for one at a time."""
    common: dict[str, Any] = {
        "since": settings.time_range[0],
        "until": settings.time_range[1],
        "project": settings.project or None,
        "all_projects": settings.all_projects,
        "aggregation": settings.aggregation,
        "group_by": settings.group_by,
        "filter_expr": settings.filter_expr,
        "limit": settings.limit,
        "order_by": settings.order_by,
        "order_direction": settings.order_direction,
        "granularity": settings.granularity,
        "bucket_timezone": settings.bucket_timezone,
        "team": settings.team,
        "team_slug": settings.team_slug,
        "owner_id": settings.owner_id,
        "token": settings.token,
    }
    return [build_speed_request(metric=metric, **common) for metric in settings.metrics]


#: Shown in a dry run when the owner is not known without asking the API. A dry
#: run must send nothing, including the one GET that would resolve this.
OWNER_PLACEHOLDER = "<read from the project at run time>"


#: Appended to a 404 from the observability API. That surface scopes by account
#: (``scope.ownerId``), so a token bound to a single project has no account to
#: resolve and is refused. Web Analytics takes a ``projectId`` instead, which is
#: why a project scoped token can read traffic but not web vitals, and why the
#: bare API message is so misleading here.
OBSERVABILITY_SCOPE_HINT = (
    "This usually means the access token is scoped to a single project. "
    "Speed Insights is served by Vercel's observability API, which scopes by "
    "account rather than by project, so it needs a token with account (or "
    "team) scope. Web Analytics presets keep working with a project scoped "
    "token. Create an account scoped token at "
    "https://vercel.com/account/tokens, or confirm the scope of the current "
    "one with: npx vercel@latest metrics schema"
)


#: Appended to a Web Analytics 403 or 404 when no team was configured. Vercel's
#: own documentation is explicit: "For team projects, find the team's teamId or
#: slug and include one in each request. For projects owned by your personal
#: account, omit teamId and slug." So a team owned project queried without one
#: is refused, and the refusal does not say which of the two situations applies.
MISSING_TEAM_HINT = (
    "If this project belongs to a team rather than to your personal account, "
    "the request needs the team as well: pass --team with the team id (Team "
    "Settings, General) or set VERCEL_TEAM_ID. Vercel requires it on every "
    "request for a team owned project, and omitting it looks the same as not "
    "having access. Run --list-projects to see which projects this token can "
    "reach."
)


def _explain_missing_team(exc: ApiError, settings: Settings) -> ApiError:
    """Add the team hint to a Web Analytics refusal when no team was given.

    Only for 403 and 404, and only when nothing supplied a team. A refusal that
    might mean "wrong account" and might mean "no such project" is worth one
    sentence naming the commonest cause, but guessing at it when a team was
    already configured would send the reader the wrong way.
    """
    if exc.status not in (403, 404) or settings.team or settings.team_slug:
        return exc
    return ApiError(
        exc.status,
        exc.code,
        f"{exc.message}\n{MISSING_TEAM_HINT}",
        attempts=exc.attempts,
    )


def _explain_observability_404(exc: ApiError) -> ApiError:
    """Turn a bare observability 404 into something a user can act on.

    Vercel answers ``404 Observability Data not found.`` when a credential
    cannot reach that surface at all, which reads as "your project has no data"
    when it usually means "this token cannot ask". The distinction costs real
    debugging time, so it is spelled out rather than left to the API's wording.
    """
    if exc.status != 404:
        return exc
    return ApiError(
        exc.status,
        exc.code,
        f"{exc.message}\n{OBSERVABILITY_SCOPE_HINT}",
        attempts=exc.attempts,
    )


class MissingProject(ConfigError):
    """No project was named, and one account may hold many.

    Its own type only so the entry point can turn it into something useful: a
    list of the projects available, which is the answer to the question behind
    the error rather than a restatement of the error.
    """


def _with_project_list(
    exc: MissingProject, args: argparse.Namespace, env: Mapping[str, str]
) -> str:
    """The missing-project message, with the account's projects appended.

    Best effort by design: if the projects cannot be listed, for any reason,
    the original message stands. An error path is the worst place to raise a
    second error, and the first message is already correct on its own.
    """
    if args.dry_run:
        return str(exc)
    try:
        token, team, team_slug = _credentials(args, env)
        session = requests.Session()
        try:
            projects = _fetch_projects(
                session,
                token,
                team,
                team_slug,
                args.max_retries,
                validate_timeout(args.timeout),
            )
        finally:
            session.close()
    except Exception:
        return str(exc)
    if not projects:
        return str(exc)
    return f"{exc}\n\nThis account has:\n\n{format_projects(projects)}"


def _credentials(
    args: argparse.Namespace, env: Mapping[str, str]
) -> tuple[str | None, str | None, str | None]:
    """Token, team and team slug, from flags then environment."""
    token = args.token or _env_value(env, "VERCEL_TOKEN")
    if not token and not args.dry_run:
        raise ConfigError(
            "no access token configured; pass --token or set VERCEL_TOKEN "
            f"(create one at {DOCS_TOKEN_URL}). Use --dry-run to build the "
            "request without a token"
        )
    if token:
        token = validate_token(token)
    return (
        token,
        args.team or _env_value(env, "VERCEL_TEAM_ID"),
        args.team_slug or _env_value(env, "VERCEL_TEAM_SLUG"),
    )


def _fetch_projects(
    session: Any,
    token: str | None,
    team: str | None,
    team_slug: str | None,
    max_retries: int,
    timeout: float,
) -> list[dict[str, str]]:
    """Every project the account holds, or an empty list if it cannot be read."""
    prepared = build_projects_request(team=team, team_slug=team_slug, token=token)
    payload = execute(
        prepared, session, max_retries=max_retries, timeout=timeout
    )
    return extract_projects(payload)


def _run_list_projects(
    args: argparse.Namespace,
    env: Mapping[str, str],
    style: Style,
    out: TextIO,
    err: TextIO,
) -> int:
    """List the account's projects, so picking one does not need the dashboard.

    One account holds many projects and a query has to name exactly one, so
    this is the discovery step that everything else depends on. Every project
    is shown, including those collecting nothing: "enabled but empty" and "not
    enabled" both produce an empty query, and they need different fixes, so the
    difference is worth seeing.
    """
    token, team, team_slug = _credentials(args, env)
    prepared = build_projects_request(team=team, team_slug=team_slug, token=token)

    if args.dry_run:
        print(format_dry_run(prepared), file=out)
        return 0

    def on_retry(reason: str) -> None:
        if args.verbose:
            print(f"verbose: {reason}", file=err)

    session = requests.Session()
    try:
        payload = execute(
            prepared,
            session,
            max_retries=args.max_retries,
            timeout=validate_timeout(args.timeout),
            on_retry=on_retry,
        )
    finally:
        session.close()

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True), file=out)
        return 0
    print(style.bold("Projects"), file=out)
    print(file=out)
    print(format_projects(extract_projects(payload)), file=out)
    return 0


def _run_list_metrics(
    args: argparse.Namespace,
    env: Mapping[str, str],
    style: Style,
    out: TextIO,
    err: TextIO,
) -> int:
    """Ask the API which metrics this account can actually query.

    Vercel documents the schema as the source of truth for the metrics,
    dimensions and aggregations available to an account, which makes it the
    right thing to consult when a query is refused: it answers "does this metric
    exist for me" outright instead of by inference. It needs no project and no
    owner, only a token, so it works even when a query cannot be built at all.
    """
    token = args.token or _env_value(env, "VERCEL_TOKEN")
    team = args.team or _env_value(env, "VERCEL_TEAM_ID")
    team_slug = args.team_slug or _env_value(env, "VERCEL_TEAM_SLUG")
    if not token and not args.dry_run:
        raise ConfigError(
            "no access token configured; pass --token or set VERCEL_TOKEN "
            f"(create one at {DOCS_TOKEN_URL}). Use --dry-run to build the "
            "request without a token"
        )
    if token:
        token = validate_token(token)
    prepared = build_schema_request(team=team, team_slug=team_slug, token=token)

    if args.dry_run:
        print(format_dry_run(prepared), file=out)
        return 0

    def on_retry(reason: str) -> None:
        if args.verbose:
            print(f"verbose: {reason}", file=err)

    session = requests.Session()
    try:
        payload = execute(
            prepared,
            session,
            max_retries=args.max_retries,
            timeout=validate_timeout(args.timeout),
            on_retry=on_retry,
        )
    except ApiError as exc:
        raise _explain_observability_404(exc) from None
    finally:
        session.close()

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True), file=out)
        return 0
    prefix = args.list_metrics or None
    print(style.bold("Queryable metrics"), file=out)
    print(file=out)
    print(format_schema(payload, prefix), file=out)
    return 0


def _resolve_project_record(
    session: Any,
    settings: Settings,
    max_retries: int,
    on_retry: Callable[[str], None],
) -> tuple[str | None, str | None]:
    """Read one project record, returning its canonical id and owning account.

    Called for the Speed Insights surface when either piece is missing. Two
    things come from the one request, which is why they resolve together:

    * The **owner**, because a scope requires ``ownerId`` and only the API knows
      it for a personal account. The account endpoint is not equivalent: a team
      scoped token has no personal user and it answers 404 "User not found."
    * The **canonical project id**, because this surface scopes by
      ``projectIds`` and wants identifiers, while Web Analytics happily accepts
      a project name. Resolving the name here is what stops ``--project
      my-site`` working for traffic and silently returning nothing for speed.

    Returns:
        ``(project_id, owner_id)``, either of which may be ``None`` when the
        record did not carry it.

    Raises:
        ConfigError: When there is no project to ask about.
    """
    if not settings.project:
        raise ConfigError(
            "--all needs an owner named explicitly, because there is no single "
            "project to read one from; pass --owner-id, or --team (a team is "
            "its own owner), or set VERCEL_OWNER_ID"
        )
    prepared = build_project_request(
        settings.project,
        team=settings.team,
        team_slug=settings.team_slug,
        token=settings.token,
    )
    payload = execute(
        prepared,
        session,
        max_retries=max_retries,
        timeout=settings.timeout,
        on_retry=on_retry,
    )
    if not isinstance(payload, Mapping):
        raise ConfigError(
            f"the record for project {settings.project!r} was not a JSON "
            "object, so neither its id nor its owning account could be read; "
            "pass --owner-id and a prj_ identifier explicitly"
        )
    return resolve_project_id(payload, settings.project), owner_from_project(payload)


def _overview_granularity(settings: Settings) -> str:
    """The time bucket the overview's trend query groups by.

    Read off the resolved settings rather than off the raw flag, because the
    two vocabularies do not agree with the wire: ``--granularity 1d`` is a
    legal input that Web Analytics would reject verbatim, and by the time it
    reaches the settings it has already been translated to ``day`` and
    validated. The overview rejects ``--group-by``, so its grouping is exactly
    one time dimension and there is nothing else here to find.
    """
    for dimension in settings.group_by:
        if dimension in TIME_GRANULARITIES:
            return dimension
    return "day"


def _plan_requests(settings: Settings) -> list[PreparedRequest]:
    """Build every request a run needs: one, three for the overview, five for vitals."""
    if settings.is_speed:
        return _plan_speed_requests(settings)

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
    granularity = _overview_granularity(settings)
    return [
        build_request(group_by=[granularity], limit=MAX_LIMIT, **common),
        build_request(group_by=["requestPath"], limit=table_limit, **common),
        build_request(group_by=["referrerHostname"], limit=table_limit, **common),
    ]


def _is_empty(result: Result) -> bool:
    """True when there is nothing worth tabulating.

    No rows is empty on either surface. An ungrouped row needs the two surfaces
    told apart, because zero means opposite things on them:

    * Web Analytics counts. Zero page views by zero visitors is genuinely no
      data, and printing a table of zeroes says less than one line of prose.
    * Speed Insights values. A Cumulative Layout Shift of exactly ``0.0`` is a
      perfect score and a real measurement, and calling it "no data" would hide
      the best result the metric can have. So presence decides here, never
      truthiness: the value key is either in the row or it is not, and a data
      point count settles it when the value arrived under a name the parser
      recognised but the caller did not ask for.
    """
    if not result.rows:
        return True
    if not result.is_count:
        return False
    row = result.rows[0]
    if result.dataset == SPEED_INSIGHTS_DATASET:
        return not (
            result.primary_metric in row.metrics or DATA_POINTS_METRIC in row.metrics
        )
    return not any(value for value in row.metrics.values())


def _empty_message(settings: Settings, group_by: Sequence[str]) -> str:
    """The single line printed instead of an empty table."""
    since, until = settings.time_range
    grouping = f"grouped by {', '.join(group_by)}" if group_by else "ungrouped"
    filter_text = settings.filter_expr or "no filter"
    subject = settings.dataset
    if settings.is_speed and settings.metrics:
        subject = settings.metrics[0].id
    return (
        f"No {subject} data for project {settings.project_label} "
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
        print(f"{PROG} {VERSION}", file=out)
        return 0
    if args.list_presets:
        print(format_presets(style), file=out)
        return 0

    if args.list_projects:
        return _run_list_projects(args, env, style, out, err)

    if args.list_metrics is not None:
        return _run_list_metrics(args, env, style, out, err)

    settings = _resolve_settings(args, env)
    for warning in settings.warnings:
        print(f"warning: {warning}", file=err)

    # Speed Insights needs both an owner and a real project id. A name is legal
    # input and works as-is on Web Analytics, so it is only resolved here, where
    # scope.projectIds would otherwise be handed something it cannot match.
    needs_lookup = settings.is_speed and (
        not settings.owner_id
        or not (settings.all_projects or looks_like_project_id(settings.project))
    )

    if args.dry_run:
        # A dry run sends nothing, including the GET that would resolve the
        # owner, so the body shows a placeholder and says where it comes from.
        if needs_lookup and not settings.owner_id:
            settings.owner_id = OWNER_PLACEHOLDER
        for index, prepared in enumerate(_plan_requests(settings)):
            if index:
                print(file=out)
            print(format_dry_run(prepared), file=out)
        if needs_lookup and settings.owner_id == OWNER_PLACEHOLDER:
            print(
                f"\nscope.ownerId shows {OWNER_PLACEHOLDER} because no --team "
                "and no --owner-id were given. A real run reads it once from "
                "the project's own record (its accountId); pass --owner-id to "
                "skip that call.",
                file=out,
            )
        return 0

    def on_retry(reason: str) -> None:
        if args.verbose:
            print(f"verbose: {reason}", file=err)

    payloads: list[dict[str, Any]] = []
    session = requests.Session()
    try:
        if needs_lookup:
            project_id, owner_id = _resolve_project_record(
                session, settings, args.max_retries, on_retry
            )
            if not settings.owner_id and owner_id:
                settings.owner_id = owner_id
            if project_id:
                settings.project = project_id
            if args.verbose:
                print(
                    "verbose: resolved the project record "
                    f"(id={settings.project}, owner={settings.owner_id})",
                    file=err,
                )
            if not settings.owner_id:
                raise ConfigError(
                    f"project {settings.project!r} carried no owning account, "
                    "so a Speed Insights scope could not be built; pass "
                    "--owner-id explicitly, or set VERCEL_OWNER_ID"
                )

        requests_to_send = _plan_requests(settings)

        if args.verbose:
            for prepared in requests_to_send:
                print(f"verbose: {prepared.method} {prepared.url}", file=err)
                print(f"verbose: params {prepared.params}", file=err)
                print(f"verbose: headers {redact_headers(prepared.headers)}", file=err)

        for prepared in requests_to_send:
            try:
                answer = execute(
                    prepared,
                    session,
                    max_retries=args.max_retries,
                    timeout=settings.timeout,
                    on_retry=on_retry,
                )
            except ApiError as exc:
                if prepared.operation == OBSERVABILITY_QUERY:
                    raise _explain_observability_404(exc) from None
                raise _explain_missing_team(exc, settings) from None
            if not isinstance(answer, Mapping):
                # Only the schema endpoint answers with a top level array; a
                # query that does is a response this client cannot interpret.
                raise ApiError(
                    200,
                    "invalid_response",
                    "the query returned a JSON array, but a query response is "
                    "an object carrying 'data'; run with --json to see it",
                )
            payloads.append(dict(answer))
    finally:
        session.close()

    if settings.is_speed:
        return _emit_speed(settings, args, payloads, style, out, err)
    if settings.preset.name == "overview":
        return _emit_overview(settings, args, payloads, style, out)
    return _emit_single(settings, args, payloads[0], style, out)


def _measured(
    results: Sequence[Result], metrics: Sequence[Metric], aggregation: str
) -> dict[str, float | None]:
    """The single value measured for each metric, keyed by its short name."""
    measured: dict[str, float | None] = {}
    for result, metric in zip(results, metrics):
        column = metric.column(aggregation)
        value: float | None = None
        for row in result.rows:
            if column in row.metrics:
                value = row.metrics[column]
                break
        measured[metric.short] = value
    return measured


def _emit_budgets(
    settings: Settings,
    args: argparse.Namespace,
    results: Sequence[Result],
    style: Style,
    out: TextIO,
    err: TextIO,
) -> int:
    """Report each budget and return the exit code the run should use.

    The report goes to stderr whenever the real output is machine readable, so
    a ``--json`` run stays parseable while a human still sees why the build
    failed.
    """
    if not args.budget:
        return 0
    if settings.group_by:
        raise ConfigError(
            "--budget compares one number against a limit, but this query is "
            "grouped, so there is a number per group. Drop --group-by, or use "
            "the vitals preset"
        )
    budgets = parse_budgets(args.budget, VITAL_ORDER)
    outcomes = evaluate(budgets, _measured(results, settings.metrics, settings.aggregation_label))

    stream = err if (args.json or args.csv) else out
    print(file=stream)
    print(style.bold("Budgets"), file=stream)
    for budget, value, verdict in outcomes:
        metric = metric_for(budget.metric)
        shown = format_value(value, metric.unit) if value is not None else "no data"
        limit = format_value(budget.limit, metric.unit)
        print(
            f"  {verdict:<7} {metric.label:<26} {shown:>8} against {limit}",
            file=stream,
        )
    if any_failed(outcomes):
        print(
            "at least one budget was exceeded, so this run exits "
            f"{BUDGET_EXCEEDED}",
            file=stream,
        )
        return BUDGET_EXCEEDED
    return 0


def _emit_speed(
    settings: Settings,
    args: argparse.Namespace,
    payloads: Sequence[dict[str, Any]],
    style: Style,
    out: TextIO,
    err: TextIO,
) -> int:
    """Render one Speed Insights result, or compose five into the vitals table."""
    results = [
        normalize_speed(
            payload,
            metric=metric,
            aggregation=settings.aggregation_label,
            group_by=settings.group_by,
            granularity=settings.granularity,
        )
        for payload, metric in zip(payloads, settings.metrics)
    ]

    if len(results) > 1:
        if args.json:
            document = {
                "range": {
                    "since": to_api_timestamp(settings.time_range[0]),
                    "until": to_api_timestamp(settings.time_range[1]),
                },
                "aggregation": settings.aggregation,
                "metrics": {
                    result.metric or metric.id: _result_document(
                        result, payload, settings.time_range
                    )
                    for result, payload, metric in zip(
                        results, payloads, settings.metrics
                    )
                },
            }
            print(json.dumps(document, indent=2), file=out)
            return _emit_budgets(settings, args, results, style, out, err)
        if all(_is_empty(result) for result in results):
            print(_empty_message(settings, settings.group_by), file=out)
            return _emit_budgets(settings, args, results, style, out, err)
        print(
            render_vitals(
                results,
                project=settings.project_label,
                time_range=settings.time_range,
                aggregation=settings.aggregation_label,
                filter_expr=settings.filter_expr,
                style=style,
            ),
            file=out,
        )
        return _emit_budgets(settings, args, results, style, out, err)

    result = results[0]
    if args.json:
        print(
            format_json(result, payloads[0], time_range=settings.time_range), file=out
        )
        return _emit_budgets(settings, args, results, style, out, err)
    if args.csv:
        print(format_csv(result), end="", file=out)
        return _emit_budgets(settings, args, results, style, out, err)
    if _is_empty(result):
        print(_empty_message(settings, settings.group_by), file=out)
        return _emit_budgets(settings, args, results, style, out, err)

    title = (
        f"Vercel Speed Insights: {settings.project_label} "
        f"({settings.preset.name}, {settings.aggregation})"
    )
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
    return _emit_budgets(settings, args, results, style, out, err)


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
    granularity = _overview_granularity(settings)
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
    except MissingProject as exc:
        # Answer the question behind the error. Listing costs one request and
        # only happens on this path, so a normal run pays nothing for it.
        print(f"error: {_with_project_list(exc, args, environment)}", file=stderr)
        return 2
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
