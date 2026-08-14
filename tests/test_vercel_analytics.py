"""Tests for scripts/vercel_analytics.py.

Nothing here touches the network. Every HTTP interaction goes through a fake
session object, and every retry test injects its own sleep and jitter callables
so the suite is instant and deterministic. A test that reaches the real network
or the real ``time.sleep`` is a bug in the test.
"""

from __future__ import annotations

import csv
import io
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import pytest
import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "vercel_analytics.py"
if str(SCRIPT_PATH.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT_PATH.parent))

# The CLI is a standalone script rather than a package, so it is imported after
# its directory has been put on sys.path above.
import vercel_analytics as va

# ---------------------------------------------------------------------------
# Shared fixtures, fakes and payloads
# ---------------------------------------------------------------------------

TOKEN = "vercel-token-that-must-never-be-printed"
PROJECT = "prj_demo"
BASE_ENV = {"VERCEL_TOKEN": TOKEN, "VERCEL_PROJECT_ID": PROJECT}

NOW = datetime(2026, 8, 14, 12, 30, 45, tzinfo=timezone.utc)


def utc(
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
    second: int = 0,
) -> datetime:
    """Build an aware UTC datetime, for readable expectations."""
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)


class FakeResponse:
    """The slice of a requests response that the module actually reads."""

    def __init__(
        self,
        status_code: int,
        body: Any = None,
        headers: dict[str, str] | None = None,
        *,
        text: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        if text is not None:
            self.text = text
        else:
            self.text = json.dumps(body if body is not None else {})


class FakeSession:
    """A session that returns queued responses and records every call.

    Queue entries may be ``FakeResponse`` objects or exception instances; an
    exception is raised instead of returned, which is how the network failure
    paths are exercised.
    """

    def __init__(self, *responses: FakeResponse | BaseException) -> None:
        self.queue: list[FakeResponse | BaseException] = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    def get(
        self,
        url: str,
        *,
        params: Any = None,
        headers: Any = None,
        timeout: Any = None,
    ) -> FakeResponse:
        self.calls.append(
            {"url": url, "params": params, "headers": headers, "timeout": timeout}
        )
        if not self.queue:
            raise AssertionError(f"unexpected extra request to {url}")
        item = self.queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def close(self) -> None:
        self.closed = True


class ForbiddenSession:
    """A session that fails the test if anything ever calls it."""

    def __init__(self) -> None:
        self.calls: list[Any] = []

    def get(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((args, kwargs))
        raise AssertionError("this code path must not issue a request")

    def close(self) -> None:
        raise AssertionError("this code path must not construct a session")


class Recorder:
    """Records the exact delays handed to ``sleep``."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    def __call__(self, delay: float) -> None:
        self.delays.append(delay)


def no_jitter() -> float:
    return 0.0


class Cli:
    """Runs ``main`` with a captured environment, streams and fake session."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.monkeypatch = monkeypatch
        self.created: list[Any] = []

    def run(
        self,
        argv: list[str],
        env: dict[str, str] | None = None,
        session: Any = None,
    ) -> tuple[int, str, str]:
        created = self.created

        def factory() -> Any:
            if session is None:
                raise AssertionError("a real requests.Session was constructed")
            created.append(session)
            return session

        # vercel_analytics does `import requests`, so this is the very object
        # the module reaches for when it builds its session.
        self.monkeypatch.setattr(requests, "Session", factory)
        out, err = io.StringIO(), io.StringIO()
        code = va.main(argv, env if env is not None else {}, out=out, err=err)
        return code, out.getvalue(), err.getvalue()


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch) -> Cli:
    return Cli(monkeypatch)


def prepared(**overrides: Any) -> va.PreparedRequest:
    """A prepared request with sensible defaults, for the HTTP level tests."""
    kwargs: dict[str, Any] = {
        "dataset": "visits",
        "project": PROJECT,
        "since": utc(2026, 8, 7),
        "until": utc(2026, 8, 14),
        "group_by": ["requestPath"],
        "limit": 10,
        "token": TOKEN,
    }
    kwargs.update(overrides)
    return va.build_request(**kwargs)


# Payload fixtures. Every shape below is copied from docs/api-notes.md.

VISITS_COUNT_PAYLOAD: dict[str, Any] = {
    "version": 1,
    "query": {"filter": "requestPath eq '/blog/my-post'"},
    "data": {"pageviews": 1250, "visitors": 980},
}

EVENTS_COUNT_PAYLOAD: dict[str, Any] = {
    "version": 1,
    "query": {"since": "2024-10-01", "until": "2024-10-07"},
    "data": {"count": 42, "visitors": 36},
}

DAILY_PAYLOAD: dict[str, Any] = {
    "version": 1,
    "query": {
        "since": "2024-10-01",
        "until": "2024-10-07",
        "groupBy": ["day"],
        "filter": "requestPath eq '/blog/my-post'",
    },
    "data": [
        {"timestamp": "2024-10-01T00:00:00.000Z", "pageviews": 220, "visitors": 180},
        {"timestamp": "2024-10-02T00:00:00.000Z", "pageviews": 245, "visitors": 201},
    ],
}

COUNTRY_PAYLOAD: dict[str, Any] = {
    "version": 1,
    "query": {"since": "2024-10-01", "until": "2024-10-07", "groupBy": ["country"]},
    "data": [
        {"country": "US", "pageviews": 640, "visitors": 510},
        {"country": "DE", "pageviews": 180, "visitors": 150},
    ],
}

COUNTRY_WITH_OTHERS_PAYLOAD: dict[str, Any] = {
    "version": 1,
    "query": {"since": "2024-10-01", "until": "2024-10-07", "groupBy": ["country"]},
    "data": [
        {"country": "US", "pageviews": 640, "visitors": 510},
        {"country": "DE", "pageviews": 180, "visitors": 150},
        {"country": "Others", "pageviews": 80, "visitors": 60},
    ],
}

EVENT_DATA_PAYLOAD: dict[str, Any] = {
    "version": 1,
    "query": {"groupBy": ["eventData/plan"]},
    "data": [
        {"eventData": "pro", "count": 42, "visitors": 36},
        {"eventData": "enterprise", "count": 12, "visitors": 10},
    ],
}

FLAGS_PAYLOAD: dict[str, Any] = {
    "version": 1,
    "query": {"groupBy": ["flags/beta_banner"]},
    "data": [
        {"flags": True, "pageviews": 90, "visitors": 70},
        {"flags": "false", "pageviews": 30, "visitors": 25},
    ],
}

TOP_PAGES_PAYLOAD: dict[str, Any] = {
    "version": 1,
    "query": {
        "since": "2026-08-07",
        "until": "2026-08-14",
        "groupBy": ["requestPath"],
        "limit": 10,
    },
    "data": [
        {"requestPath": "/pricing", "pageviews": 640, "visitors": 510},
        {"requestPath": "/blog/my-post", "pageviews": 180, "visitors": 150},
    ],
}

REFERRERS_PAYLOAD: dict[str, Any] = {
    "version": 1,
    "query": {"groupBy": ["referrerHostname"], "limit": 5},
    "data": [
        {"referrerHostname": "news.ycombinator.com", "pageviews": 300, "visitors": 260},
        {"referrerHostname": "google.com", "pageviews": 120, "visitors": 110},
    ],
}

EMPTY_AGGREGATE_PAYLOAD: dict[str, Any] = {
    "version": 1,
    "query": {"since": "2026-08-07", "until": "2026-08-14", "groupBy": ["requestPath"]},
    "data": [],
}


def error_payload(code: str, message: str, **extra: Any) -> dict[str, Any]:
    """The documented Vercel error envelope."""
    error: dict[str, Any] = {"code": code, "message": message}
    error.update(extra)
    return {"error": error}


# ---------------------------------------------------------------------------
# 1. Time parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("30m", NOW - timedelta(minutes=30)),
        ("24h", NOW - timedelta(hours=24)),
        ("7d", NOW - timedelta(days=7)),
        ("4w", NOW - timedelta(weeks=4)),
        ("7D", NOW - timedelta(days=7)),
        ("now", NOW),
        ("NOW", NOW),
        ("today", utc(2026, 8, 14)),
        ("yesterday", utc(2026, 8, 13)),
        ("2026-08-01", utc(2026, 8, 1)),
        ("2026-08-01T12:00:00Z", utc(2026, 8, 1, 12)),
        ("2026-08-01T12:00:00z", utc(2026, 8, 1, 12)),
        ("2026-08-01T12:00:00+02:00", utc(2026, 8, 1, 10)),
        ("2026-08-01T12:00:00-05:00", utc(2026, 8, 1, 17)),
        ("2026-08-01T12:00:00", utc(2026, 8, 1, 12)),
        ("1700000000000", utc(2023, 11, 14, 22, 13, 20)),
    ],
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_parse_time_value_accepts_every_documented_format(
    value: str, expected: datetime
) -> None:
    parsed = va.parse_time_value(value, NOW)
    assert parsed == expected
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(0)


@pytest.mark.parametrize(
    "value",
    ["", "   ", "banana", "7x", "d7", "2026-13-01", "next tuesday", "--since", "1e9"],
)
def test_parse_time_value_rejects_garbage_with_a_config_error(value: str) -> None:
    with pytest.raises(va.ConfigError) as excinfo:
        va.parse_time_value(value, NOW)
    assert "time value" in str(excinfo.value)


def test_parse_time_value_tells_unix_seconds_apart_from_milliseconds() -> None:
    with pytest.raises(va.ConfigError) as excinfo:
        va.parse_time_value("1700000000", NOW)
    message = str(excinfo.value)
    assert "millisecond" in message
    assert "1700000000000" in message


def test_to_api_timestamp_renders_utc_with_a_z_suffix() -> None:
    assert va.to_api_timestamp(utc(2026, 8, 1, 12, 30, 45)) == "2026-08-01T12:30:45Z"


def test_to_api_timestamp_converts_a_non_utc_offset_to_utc() -> None:
    aware = datetime(2026, 8, 1, 12, tzinfo=timezone(timedelta(hours=2)))
    assert va.to_api_timestamp(aware) == "2026-08-01T10:00:00Z"


def test_resolve_range_returns_both_ends_in_order() -> None:
    start, end = va.resolve_range("7d", "now", NOW)
    assert start == NOW - timedelta(days=7)
    assert end == NOW


@pytest.mark.parametrize(
    ("since", "until"),
    [("now", "7d"), ("now", "now"), ("2026-08-02", "2026-08-01")],
)
def test_resolve_range_requires_since_strictly_before_until(
    since: str, until: str
) -> None:
    with pytest.raises(va.ConfigError) as excinfo:
        va.resolve_range(since, until, NOW)
    message = str(excinfo.value)
    assert "--since must be strictly earlier than --until" in message
    assert "--since 7d --until now" in message


def test_reporting_window_warns_only_beyond_twenty_four_months() -> None:
    assert va.reporting_window_warning(NOW - timedelta(days=400), NOW) is None
    warning = va.reporting_window_warning(NOW - timedelta(days=900), NOW)
    assert warning is not None
    assert "reporting window" in warning


# ---------------------------------------------------------------------------
# 2. OData construction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("US", "'US'"),
        ("O'Brien", "'O''Brien'"),
        ("it's a 'test'", "'it''s a ''test'''"),
        ("", "''"),
        ("/blog/[slug]", "'/blog/[slug]'"),
    ],
)
def test_quote_odata_doubles_embedded_single_quotes(value: str, expected: str) -> None:
    assert va.quote_odata(value) == expected


@pytest.mark.parametrize(
    ("dimension", "value", "expected"),
    [
        ("country", "US", "country eq 'US'"),
        ("requestPath", "/pricing", "requestPath eq '/pricing'"),
        ("requestPath", "O'Brien", "requestPath eq 'O''Brien'"),
        ("country", "US,DE", "country in ('US', 'DE')"),
        ("country", " US , DE ", "country in ('US', 'DE')"),
        ("country", "US,DE,FR", "country in ('US', 'DE', 'FR')"),
        ("country", "US,,DE", "country in ('US', 'DE')"),
        ("country", "US,", "country eq 'US'"),
        ("browserName", "O'Neill,Safari", "browserName in ('O''Neill', 'Safari')"),
    ],
)
def test_build_clause_uses_eq_for_one_value_and_in_for_a_list(
    dimension: str, value: str, expected: str
) -> None:
    assert va.build_clause(dimension, value) == expected


@pytest.mark.parametrize("value", ["", "   ", ",", ",,", " , "])
def test_build_clause_rejects_an_empty_filter_value(value: str) -> None:
    with pytest.raises(va.ConfigError) as excinfo:
        va.build_clause("country", value)
    assert "is empty" in str(excinfo.value)


@pytest.mark.parametrize(
    ("clauses", "expected"),
    [
        ([], None),
        ([""], None),
        (["   "], None),
        (["country eq 'US'"], "country eq 'US'"),
        (
            ["country eq 'US'", "requestPath eq '/pricing'"],
            "country eq 'US' and requestPath eq '/pricing'",
        ),
        (
            ["country eq 'US' or country eq 'DE'", "requestPath eq '/pricing'"],
            "(country eq 'US' or country eq 'DE') and requestPath eq '/pricing'",
        ),
        (
            ["country eq 'US'", "not (deviceType eq 'bot' or deviceType eq 'crawler')"],
            "country eq 'US' and not (deviceType eq 'bot' or deviceType eq 'crawler')",
        ),
        (["country eq 'or'"], "country eq 'or'"),
        (["referrerHostname eq 'editor.example'"], "referrerHostname eq 'editor.example'"),
    ],
)
def test_combine_filters_joins_with_and_and_parenthesizes_top_level_or(
    clauses: list[str], expected: str | None
) -> None:
    assert va.combine_filters(clauses) == expected


def test_combine_filters_only_parenthesizes_the_clause_that_needs_it() -> None:
    combined = va.combine_filters(
        ["a eq 'x' or a eq 'y'", "b eq 'z'", "c eq 'w' or c eq 'v'"]
    )
    assert combined == "(a eq 'x' or a eq 'y') and b eq 'z' and (c eq 'w' or c eq 'v')"


@pytest.mark.parametrize(
    "value", ["US", "US,DE", "O'Brien", "12", "true", "/a/b", "a or b"]
)
def test_no_comparison_operator_is_ever_emitted(value: str) -> None:
    for dimension in va.PLAIN_DIMENSIONS:
        clause = va.build_clause(dimension, value)
        assert re.search(r"(^|\s)(gt|lt|ge|le)\s", clause) is None
        assert " eq " in clause or " in (" in clause


def test_json_dimension_quotes_keys_with_punctuation_and_leaves_bare_keys_alone() -> None:
    assert va.json_dimension("eventData", "plan") == "eventData/plan"
    assert va.json_dimension("flags", "beta_banner") == "flags/beta_banner"
    assert va.json_dimension("flags", "my-flag") == "flags/'my-flag'"
    assert va.json_dimension("eventData", "'signup-source'") == "eventData/'signup-source'"


def test_json_dimension_rejects_an_empty_key() -> None:
    with pytest.raises(va.ConfigError) as excinfo:
        va.json_dimension("eventData", "  ")
    assert "eventData/plan" in str(excinfo.value)


# ---------------------------------------------------------------------------
# 3. Validation rules from docs/cli-contract.md
# ---------------------------------------------------------------------------

CONFIG_ERROR_CASES: list[tuple[str, list[str], dict[str, str], list[str]]] = [
    (
        "rule1-missing-project",
        ["top-pages"],
        {"VERCEL_TOKEN": TOKEN},
        ["--project", "VERCEL_PROJECT_ID"],
    ),
    (
        "rule2-missing-token",
        ["top-pages"],
        {"VERCEL_PROJECT_ID": PROJECT},
        ["--token", "VERCEL_TOKEN", "--dry-run", "vercel.com/docs"],
    ),
    (
        "rule3-team-and-team-slug",
        ["top-pages", "--team", "team_abc", "--team-slug", "acme"],
        dict(BASE_ENV),
        ["--team", "--team-slug", "mutually", "team_abc", "acme"],
    ),
    (
        "rule4-more-than-two-group-by",
        [
            "top-pages",
            "--group-by",
            "country",
            "--group-by",
            "deviceType",
            "--group-by",
            "browserName",
        ],
        dict(BASE_ENV),
        ["maximum of 2", "drop"],
    ),
    (
        "rule5-two-time-granularities",
        ["trend", "--group-by", "day", "--group-by", "week"],
        dict(BASE_ENV),
        ["at most one time granularity", "hour, day, week, month, year"],
    ),
    (
        "rule6-unknown-dimension",
        ["top-pages", "--group-by", "countries"],
        dict(BASE_ENV),
        ["unknown dimension", "'countries'", "Valid dimensions", "requestPath"],
    ),
    (
        "rule7-event-data-grouping-on-visits",
        ["top-pages", "--group-by", "eventData/plan"],
        dict(BASE_ENV),
        ["eventData/plan", "--dataset events"],
    ),
    (
        "rule7-event-property-on-visits",
        ["top-pages", "--event-property", "plan"],
        dict(BASE_ENV),
        ["--dataset events"],
    ),
    (
        "rule7-event-name-on-visits",
        ["top-pages", "--event-name", "signup"],
        dict(BASE_ENV),
        ["--event-name", "--dataset events"],
    ),
    (
        "rule8-limit-zero",
        ["top-pages", "--limit", "0"],
        dict(BASE_ENV),
        ["--limit 0", "1 to 100", "Others"],
    ),
    (
        "rule8-limit-101",
        ["top-pages", "--limit", "101"],
        dict(BASE_ENV),
        ["--limit 101", "1 to 100", "Others"],
    ),
    (
        "rule9-preview-environment-on-a-count-query",
        ["total", "--environment", "preview"],
        dict(BASE_ENV),
        ["--environment preview", "production", "--group-by day"],
    ),
    (
        "rule10-json-with-csv",
        ["top-pages", "--json", "--csv"],
        dict(BASE_ENV),
        ["--json", "--csv", "mutually exclusive"],
    ),
    (
        "rule11-since-not-before-until",
        ["top-pages", "--since", "now", "--until", "7d"],
        dict(BASE_ENV),
        ["--since must be strictly earlier than --until"],
    ),
    (
        "rule13-flag-without-equals",
        ["top-pages", "--flag", "beta_banner"],
        dict(BASE_ENV),
        ["--flag", "NAME=VALUE", "beta_banner=true"],
    ),
]


@pytest.mark.parametrize(
    ("argv", "env", "fragments"),
    [case[1:] for case in CONFIG_ERROR_CASES],
    ids=[case[0] for case in CONFIG_ERROR_CASES],
)
def test_config_errors_exit_two_and_name_the_fix(
    cli: Cli, argv: list[str], env: dict[str, str], fragments: list[str]
) -> None:
    code, out, err = cli.run(argv, env=env)
    assert code == 2
    assert out == ""
    assert err.startswith("error: ")
    assert "Traceback" not in err
    for fragment in fragments:
        assert fragment in err, f"{fragment!r} missing from {err!r}"


def test_rule12_an_old_since_warns_on_stderr_and_still_succeeds(cli: Cli) -> None:
    code, out, err = cli.run(
        ["top-pages", "--since", "2000-01-01", "--dry-run"],
        env={"VERCEL_PROJECT_ID": PROJECT},
    )
    assert code == 0
    assert "warning:" in err
    assert "reporting window" in err
    assert "2000-01-01T00:00:00Z" in out


def test_validate_dimension_accepts_every_documented_visits_dimension() -> None:
    for dimension in va.VISIT_DIMENSIONS:
        assert va.validate_dimension(dimension, "visits") == dimension


def test_validate_dimension_accepts_event_only_dimensions_on_events() -> None:
    assert va.validate_dimension("eventName", "events") == "eventName"
    assert va.validate_dimension("eventData/plan", "events") == "eventData/plan"
    assert va.validate_dimension("eventData/'sign-up'", "events") == "eventData/'sign-up'"
    assert va.validate_dimension("flags/beta_banner", "events") == "flags/beta_banner"


def test_validate_dimension_requires_quoting_for_a_key_with_punctuation() -> None:
    with pytest.raises(va.ConfigError) as excinfo:
        va.validate_dimension("eventData/sign-up", "events")
    assert "eventData/'sign-up'" in str(excinfo.value)


def test_validate_dimension_rejects_an_unknown_json_base() -> None:
    with pytest.raises(va.ConfigError) as excinfo:
        va.validate_dimension("metadata/plan", "events")
    assert "unknown JSON dimension" in str(excinfo.value)


def test_validate_group_by_rejects_a_repeated_dimension() -> None:
    with pytest.raises(va.ConfigError) as excinfo:
        va.validate_group_by(["day", "day"], "visits")
    assert "grouped by twice" in str(excinfo.value)


def test_validate_limit_accepts_the_inclusive_bounds() -> None:
    assert va.validate_limit(va.MIN_LIMIT) == 1
    assert va.validate_limit(va.MAX_LIMIT) == 100


def test_overview_rejects_csv_and_an_overridden_grouping(cli: Cli) -> None:
    code, _, err = cli.run(["overview", "--csv"], env=dict(BASE_ENV))
    assert code == 2
    assert "overview" in err and "--csv" in err

    code, _, err = cli.run(
        ["overview", "--group-by", "country"], env=dict(BASE_ENV)
    )
    assert code == 2
    assert "--group-by" in err


# ---------------------------------------------------------------------------
# 4. Endpoint selection and request building
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("group_by", "expected"),
    [
        ([], "count"),
        (["day"], "aggregate"),
        (["requestPath"], "aggregate"),
        (["day", "country"], "aggregate"),
    ],
)
def test_select_endpoint_picks_aggregate_only_when_grouping_is_present(
    group_by: list[str], expected: str
) -> None:
    assert va.select_endpoint(group_by) == expected


def test_a_count_request_carries_neither_by_nor_limit() -> None:
    request = prepared(group_by=[], limit=10)
    keys = [name for name, _ in request.params]
    assert request.url == f"{va.BASE_URL}/visits/count"
    assert "by" not in keys
    assert "limit" not in keys
    assert keys == ["projectId", "since", "until"]


def test_an_aggregate_request_carries_by_since_until_and_limit() -> None:
    request = prepared(group_by=["requestPath"], limit=25)
    assert request.url == f"{va.BASE_URL}/visits/aggregate"
    assert request.params == [
        ("projectId", PROJECT),
        ("by", "requestPath"),
        ("since", "2026-08-07T00:00:00Z"),
        ("until", "2026-08-14T00:00:00Z"),
        ("limit", "25"),
    ]


def test_two_grouping_dimensions_become_two_repeated_by_parameters() -> None:
    request = prepared(group_by=["day", "country"])
    assert [value for name, value in request.params if name == "by"] == ["day", "country"]


def test_build_request_places_the_events_dataset_in_the_path() -> None:
    request = prepared(dataset="events", group_by=["eventName"])
    assert request.url == f"{va.BASE_URL}/events/aggregate"


def test_build_request_passes_filter_team_and_slug_through_as_parameters() -> None:
    request = prepared(
        filter_expr="country eq 'US'", team="team_abc", team_slug="acme"
    )
    params = dict(request.params)
    assert params["filter"] == "country eq 'US'"
    assert params["teamId"] == "team_abc"
    assert params["slug"] == "acme"


def test_build_request_puts_the_token_only_in_the_authorization_header() -> None:
    request = prepared()
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in request.url
    assert all(TOKEN not in value for _, value in request.params)
    assert request.method == "GET"


def test_build_request_omits_the_authorization_header_without_a_token() -> None:
    request = prepared(token=None)
    assert "Authorization" not in request.headers


# ---------------------------------------------------------------------------
# 5. Response normalization
# ---------------------------------------------------------------------------


def test_normalize_reads_a_visits_count_as_a_single_keyless_row() -> None:
    result = va.normalize(VISITS_COUNT_PAYLOAD, "visits", [])
    assert result.is_count is True
    assert result.metric_names == ["pageviews", "visitors"]
    assert len(result.rows) == 1
    assert result.rows[0].key is None
    assert result.rows[0].metrics == {"pageviews": 1250, "visitors": 980}
    assert result.query["filter"] == "requestPath eq '/blog/my-post'"


def test_normalize_reads_an_events_count_with_the_events_metric_names() -> None:
    result = va.normalize(EVENTS_COUNT_PAYLOAD, "events", [])
    assert result.is_count is True
    assert result.metric_names == ["count", "visitors"]
    assert result.rows[0].metrics == {"count": 42, "visitors": 36}
    assert "pageviews" not in result.rows[0].metrics


def test_normalize_reads_timestamp_rows_when_grouping_by_a_granularity() -> None:
    result = va.normalize(DAILY_PAYLOAD, "visits", ["day"])
    assert result.is_count is False
    assert result.granularity == "day"
    assert result.group_dimension is None
    assert [row.timestamp for row in result.rows] == [
        "2024-10-01T00:00:00.000Z",
        "2024-10-02T00:00:00.000Z",
    ]
    assert [row.key for row in result.rows] == [None, None]
    assert result.totals() == {"pageviews": 465, "visitors": 381}


def test_normalize_labels_rows_with_the_plain_grouping_dimension() -> None:
    result = va.normalize(COUNTRY_PAYLOAD, "visits", ["country"])
    assert result.group_dimension == "country"
    assert [row.key for row in result.rows] == ["US", "DE"]
    assert result.rows[0].metrics == {"pageviews": 640, "visitors": 510}
    assert all(row.timestamp is None for row in result.rows)


def test_normalize_remaps_event_data_rows_back_onto_the_requested_dimension() -> None:
    result = va.normalize(EVENT_DATA_PAYLOAD, "events", ["eventData/plan"])
    assert result.group_dimension == "eventData/plan"
    assert [row.key for row in result.rows] == ["pro", "enterprise"]
    assert result.metric_names == ["count", "visitors"]
    assert "eventData" not in result.rows[0].metrics


def test_normalize_remaps_flag_rows_and_stringifies_non_string_labels() -> None:
    result = va.normalize(FLAGS_PAYLOAD, "visits", ["flags/beta_banner"])
    assert [row.key for row in result.rows] == ["true", "false"]
    assert result.rows[0].metrics == {"pageviews": 90, "visitors": 70}


def test_normalize_marks_the_others_bucket_and_counts_it_in_the_total() -> None:
    result = va.normalize(COUNTRY_WITH_OTHERS_PAYLOAD, "visits", ["country"])
    assert [row.is_others for row in result.rows] == [False, False, True]
    assert result.totals()["pageviews"] == 900


def test_normalize_handles_an_empty_data_array_without_losing_metric_names() -> None:
    result = va.normalize(EMPTY_AGGREGATE_PAYLOAD, "visits", ["requestPath"])
    assert result.rows == []
    assert result.metric_names == ["pageviews", "visitors"]
    assert result.totals() == {"pageviews": 0, "visitors": 0}


def test_normalize_ignores_unexpected_extra_row_fields() -> None:
    payload = {
        "version": 1,
        "query": {"groupBy": ["country"]},
        "data": [{"country": "US", "pageviews": 5, "visitors": 4, "aiTokens": 7}],
    }
    result = va.normalize(payload, "visits", ["country"])
    assert result.rows[0].key == "US"
    assert result.rows[0].metrics["pageviews"] == 5
    assert result.metric_names[:2] == ["pageviews", "visitors"]


# ---------------------------------------------------------------------------
# 6. Formatting
# ---------------------------------------------------------------------------


def test_format_table_shows_groups_shares_and_a_totals_row() -> None:
    result = va.normalize(COUNTRY_PAYLOAD, "visits", ["country"])
    text = va.format_table(
        result,
        time_range=(utc(2026, 8, 7), utc(2026, 8, 14)),
        filter_expr="country in ('US', 'DE')",
        limit=10,
    )
    assert "Range: 2026-08-07T00:00:00Z to 2026-08-14T00:00:00Z (UTC)" in text
    assert "Filter: country in ('US', 'DE')" in text
    assert "country" in text and "pageviews" in text and "% pageviews" in text
    assert "US" in text and "640" in text and "510" in text
    assert "78.0%" in text
    assert "TOTAL" in text and "820" in text and "100.0%" in text


def test_format_table_renders_time_buckets_at_day_precision() -> None:
    result = va.normalize(DAILY_PAYLOAD, "visits", ["day"])
    text = va.format_table(result)
    assert "2024-10-01" in text
    assert "T00:00:00.000Z" not in text
    assert "220" in text and "245" in text
    assert "465" in text


def test_format_table_annotates_the_others_row_as_the_limit_overflow() -> None:
    result = va.normalize(COUNTRY_WITH_OTHERS_PAYLOAD, "visits", ["country"])
    text = va.format_table(result, limit=2)
    assert "Others" in text
    assert "is not a real value" in text
    assert "--limit 2" in text


def test_format_table_renders_a_count_as_a_labelled_block() -> None:
    result = va.normalize(VISITS_COUNT_PAYLOAD, "visits", [])
    text = va.format_table(result, time_range=(utc(2026, 8, 7), utc(2026, 8, 14)))
    assert "Range: 2026-08-07T00:00:00Z" in text
    assert "pageviews" in text and "1,250" in text
    assert "visitors" in text and "980" in text
    assert "TOTAL" not in text


def test_format_json_carries_query_range_rows_totals_and_the_raw_payload() -> None:
    result = va.normalize(COUNTRY_PAYLOAD, "visits", ["country"])
    document = json.loads(
        va.format_json(
            result, COUNTRY_PAYLOAD, time_range=(utc(2026, 8, 7), utc(2026, 8, 14))
        )
    )
    assert document["query"] == COUNTRY_PAYLOAD["query"]
    assert document["range"] == {
        "since": "2026-08-07T00:00:00Z",
        "until": "2026-08-14T00:00:00Z",
    }
    assert document["rows"][0] == {
        "key": "US",
        "groups": {"country": "US"},
        "timestamp": None,
        "metrics": {"pageviews": 640, "visitors": 510},
    }
    assert document["totals"] == {"pageviews": 820, "visitors": 660}
    assert document["raw"] == COUNTRY_PAYLOAD
    assert document["groupBy"] == ["country"]


def test_format_json_of_a_count_marks_it_as_a_count() -> None:
    result = va.normalize(VISITS_COUNT_PAYLOAD, "visits", [])
    document = json.loads(va.format_json(result, VISITS_COUNT_PAYLOAD))
    assert document["isCount"] is True
    assert document["rows"] == [
        {
            "key": None,
            "groups": {},
            "timestamp": None,
            "metrics": {"pageviews": 1250, "visitors": 980},
        }
    ]
    assert document["range"] is None


def test_format_csv_of_a_grouped_result_parses_back_to_the_expected_rows() -> None:
    result = va.normalize(COUNTRY_PAYLOAD, "visits", ["country"])
    rows = list(csv.reader(io.StringIO(va.format_csv(result))))
    assert rows == [
        ["country", "pageviews", "visitors"],
        ["US", "640", "510"],
        ["DE", "180", "150"],
    ]


def test_format_csv_of_a_time_grouped_result_uses_the_granularity_as_the_header() -> None:
    result = va.normalize(DAILY_PAYLOAD, "visits", ["day"])
    rows = list(csv.reader(io.StringIO(va.format_csv(result))))
    assert rows == [
        ["day", "pageviews", "visitors"],
        ["2024-10-01", "220", "180"],
        ["2024-10-02", "245", "201"],
    ]


def test_format_csv_of_a_count_writes_one_header_and_one_value_row() -> None:
    result = va.normalize(EVENTS_COUNT_PAYLOAD, "events", [])
    rows = list(csv.reader(io.StringIO(va.format_csv(result))))
    assert rows == [["count", "visitors"], ["42", "36"]]


def test_format_csv_quotes_a_label_containing_a_comma() -> None:
    payload = {
        "version": 1,
        "query": {"groupBy": ["requestPath"]},
        "data": [{"requestPath": "/a,b", "pageviews": 1, "visitors": 1}],
    }
    result = va.normalize(payload, "visits", ["requestPath"])
    text = va.format_csv(result)
    assert '"/a,b"' in text
    assert list(csv.reader(io.StringIO(text)))[1] == ["/a,b", "1", "1"]


def test_the_empty_result_message_names_the_range_and_the_filter(cli: Cli) -> None:
    session = FakeSession(FakeResponse(200, EMPTY_AGGREGATE_PAYLOAD))
    code, out, err = cli.run(
        [
            "top-pages",
            "--since",
            "2026-08-01",
            "--until",
            "2026-08-08",
            "--country",
            "US",
        ],
        env=dict(BASE_ENV),
        session=session,
    )
    assert code == 0
    assert err == ""
    assert "No visits data for project prj_demo" in out
    assert "grouped by requestPath" in out
    assert "2026-08-01T00:00:00Z" in out and "2026-08-08T00:00:00Z" in out
    assert "country eq 'US'" in out
    assert "Try a wider --since" in out


def test_render_overview_composes_the_three_sections() -> None:
    daily = va.normalize(DAILY_PAYLOAD, "visits", ["day"])
    pages = va.normalize(TOP_PAGES_PAYLOAD, "visits", ["requestPath"])
    referrers = va.normalize(REFERRERS_PAYLOAD, "visits", ["referrerHostname"])
    text = va.render_overview(
        [daily, pages, referrers],
        project=PROJECT,
        time_range=(utc(2026, 8, 7), utc(2026, 8, 14)),
    )
    assert f"Vercel Web Analytics: {PROJECT}" in text
    assert "By day" in text
    assert "2024-10-01" in text
    assert "Top pages (top 5)" in text and "/pricing" in text
    assert "Top referrers (top 5)" in text and "news.ycombinator.com" in text


# ---------------------------------------------------------------------------
# 7. Retry and backoff
# ---------------------------------------------------------------------------


def test_retry_delay_prefers_a_numeric_retry_after_header() -> None:
    response = FakeResponse(429, {}, {"Retry-After": "2"})
    assert va.retry_delay(0, response, None, 1000.0) == 2.0


def test_retry_delay_understands_an_http_date_retry_after() -> None:
    when = utc(2015, 10, 21, 7, 28)
    header = {"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"}
    delay = va.retry_delay(0, FakeResponse(429, {}, header), None, when.timestamp() - 5)
    assert delay == pytest.approx(5.0)


def test_retry_delay_falls_back_to_reset_ms_then_reset_then_backoff() -> None:
    body_ms = error_payload("rate_limited", "slow down", limit={"resetMs": 1003500})
    assert va.retry_delay(0, FakeResponse(429, body_ms), body_ms, 1000.0) == 3.5

    body_s = error_payload("rate_limited", "slow down", limit={"reset": 1004})
    assert va.retry_delay(0, FakeResponse(429, body_s), body_s, 1000.0) == 4.0

    assert va.retry_delay(0, FakeResponse(500, {}), None, 1000.0) == 0.5


@pytest.mark.parametrize(
    ("attempt", "expected"), [(0, 0.5), (1, 1.0), (2, 2.0), (3, 4.0), (10, 60.0)]
)
def test_retry_delay_backoff_doubles_and_is_capped(attempt: int, expected: float) -> None:
    assert va.retry_delay(attempt, None, None, 1000.0) == expected


def test_a_rate_limited_response_honors_retry_after_then_succeeds() -> None:
    sleeps = Recorder()
    session = FakeSession(
        FakeResponse(
            429,
            error_payload("rate_limited", "The rate limit of 6 exceeded"),
            {"Retry-After": "2"},
        ),
        FakeResponse(200, COUNTRY_PAYLOAD),
    )
    payload = va.execute(
        prepared(), session, sleep=sleeps, jitter=no_jitter, max_retries=3, now=lambda: 1000.0
    )
    assert payload == COUNTRY_PAYLOAD
    assert sleeps.delays == [2.0]
    assert len(session.calls) == 2


def test_a_rate_limited_response_honors_reset_ms_when_there_is_no_header() -> None:
    sleeps = Recorder()
    body = error_payload(
        "rate_limited",
        "The rate limit of 6 exceeded",
        limit={"remaining": 0, "reset": 1004, "resetMs": 1003500, "total": 6},
    )
    session = FakeSession(FakeResponse(429, body), FakeResponse(200, COUNTRY_PAYLOAD))
    payload = va.execute(
        prepared(), session, sleep=sleeps, jitter=no_jitter, max_retries=3, now=lambda: 1000.0
    )
    assert payload == COUNTRY_PAYLOAD
    assert sleeps.delays == [3.5]


def test_a_server_error_is_retried_with_exponential_backoff() -> None:
    sleeps = Recorder()
    session = FakeSession(
        FakeResponse(500, error_payload("internal_server_error", "boom")),
        FakeResponse(200, COUNTRY_PAYLOAD),
    )
    payload = va.execute(prepared(), session, sleep=sleeps, jitter=no_jitter, max_retries=3)
    assert payload == COUNTRY_PAYLOAD
    assert sleeps.delays == [0.5]


def test_injected_jitter_is_added_to_every_delay() -> None:
    sleeps = Recorder()
    session = FakeSession(
        FakeResponse(500, error_payload("internal_server_error", "boom")),
        FakeResponse(503, error_payload("service_unavailable", "boom")),
        FakeResponse(200, COUNTRY_PAYLOAD),
    )
    va.execute(prepared(), session, sleep=sleeps, jitter=lambda: 0.25, max_retries=3)
    assert sleeps.delays == [0.75, 1.25]


def test_exhausting_max_retries_reports_the_attempt_count() -> None:
    sleeps = Recorder()
    session = FakeSession(
        *[FakeResponse(500, error_payload("internal_server_error", "boom")) for _ in range(3)]
    )
    with pytest.raises(va.ApiError) as excinfo:
        va.execute(prepared(), session, sleep=sleeps, jitter=no_jitter, max_retries=2)
    assert "gave up after 3 attempts" in str(excinfo.value)
    assert "boom" in str(excinfo.value)
    assert sleeps.delays == [0.5, 1.0]
    assert len(session.calls) == 3


def test_exhausting_max_retries_on_a_rate_limit_raises_rate_limit_error() -> None:
    sleeps = Recorder()
    body = error_payload("rate_limited", "Try again in 7 days", limit={"total": 6})
    session = FakeSession(FakeResponse(429, body), FakeResponse(429, body))
    with pytest.raises(va.RateLimitError) as excinfo:
        va.execute(prepared(), session, sleep=sleeps, jitter=no_jitter, max_retries=1)
    assert excinfo.value.limit == {"total": 6}
    assert "Try again in 7 days" in str(excinfo.value)
    assert sleeps.delays == [0.5]


def test_a_client_error_is_never_retried() -> None:
    sleeps = Recorder()
    session = FakeSession(
        FakeResponse(400, error_payload("bad_request", "Invalid value for by")),
        FakeResponse(200, COUNTRY_PAYLOAD),
    )
    with pytest.raises(va.ApiError) as excinfo:
        va.execute(prepared(), session, sleep=sleeps, jitter=no_jitter, max_retries=3)
    assert excinfo.value.status == 400
    assert sleeps.delays == []
    assert len(session.calls) == 1


def test_a_timeout_is_retried_and_then_succeeds() -> None:
    sleeps = Recorder()
    session = FakeSession(
        requests.Timeout("timed out"), FakeResponse(200, COUNTRY_PAYLOAD)
    )
    payload = va.execute(prepared(), session, sleep=sleeps, jitter=no_jitter, max_retries=2)
    assert payload == COUNTRY_PAYLOAD
    assert sleeps.delays == [0.5]


def test_repeated_network_failures_surface_as_an_api_error_with_attempts() -> None:
    sleeps = Recorder()
    session = FakeSession(
        requests.ConnectionError("no route"), requests.Timeout("timed out")
    )
    with pytest.raises(va.ApiError) as excinfo:
        va.execute(prepared(), session, sleep=sleeps, jitter=no_jitter, max_retries=1)
    assert excinfo.value.status is None
    assert "could not reach" in str(excinfo.value)
    assert "gave up after 2 attempts" in str(excinfo.value)
    assert sleeps.delays == [0.5]


def test_max_retries_zero_makes_exactly_one_attempt() -> None:
    sleeps = Recorder()
    session = FakeSession(FakeResponse(503, error_payload("unavailable", "down")))
    with pytest.raises(va.ApiError):
        va.execute(prepared(), session, sleep=sleeps, jitter=no_jitter, max_retries=0)
    assert sleeps.delays == []
    assert len(session.calls) == 1


def test_execute_sends_a_get_with_the_prepared_parameters_and_timeout() -> None:
    session = FakeSession(FakeResponse(200, COUNTRY_PAYLOAD))
    request = prepared()
    va.execute(request, session, sleep=Recorder(), jitter=no_jitter, timeout=12.5)
    call = session.calls[0]
    assert call["url"] == request.url
    assert call["params"] == request.params
    assert call["headers"] == request.headers
    assert call["timeout"] == 12.5


# ---------------------------------------------------------------------------
# 8. Error paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "code", "message"),
    [
        (400, "bad_request", "An english description of the error that just occurred"),
        (401, "forbidden", "Not authorized"),
        (403, "forbidden", "You do not have permission to access this resource"),
        (410, "gone", "The resource is gone"),
    ],
)
def test_an_api_error_surfaces_vercels_message_verbatim(
    status: int, code: str, message: str
) -> None:
    session = FakeSession(FakeResponse(status, error_payload(code, message)))
    with pytest.raises(va.ApiError) as excinfo:
        va.execute(prepared(), session, sleep=Recorder(), jitter=no_jitter, max_retries=0)
    error = excinfo.value
    assert error.status == status
    assert error.code == code
    assert error.message == message
    assert message in str(error)
    assert f"HTTP {status}" in str(error)


def test_a_non_json_success_body_becomes_a_clean_error() -> None:
    session = FakeSession(FakeResponse(200, text="<html>gateway</html>"))
    with pytest.raises(va.ApiError) as excinfo:
        va.execute(prepared(), session, sleep=Recorder(), jitter=no_jitter, max_retries=0)
    assert "not a JSON object" in str(excinfo.value)
    assert not isinstance(excinfo.value, json.JSONDecodeError)


def test_a_non_json_error_body_falls_back_to_a_trimmed_snippet() -> None:
    session = FakeSession(FakeResponse(502, text="<html>\nbad gateway\n</html>"))
    with pytest.raises(va.ApiError) as excinfo:
        va.execute(prepared(), session, sleep=Recorder(), jitter=no_jitter, max_retries=0)
    rendered = str(excinfo.value)
    assert "bad gateway" in rendered
    assert "\n" not in rendered


def test_an_error_body_without_a_message_still_renders() -> None:
    session = FakeSession(FakeResponse(400, {"error": {"code": "bad_request"}}))
    with pytest.raises(va.ApiError) as excinfo:
        va.execute(prepared(), session, sleep=Recorder(), jitter=no_jitter, max_retries=0)
    assert "HTTP 400" in str(excinfo.value)
    assert "bad_request" in str(excinfo.value)


def test_an_unexpected_request_exception_is_not_retried() -> None:
    sleeps = Recorder()
    session = FakeSession(requests.TooManyRedirects("looping"))
    with pytest.raises(va.ApiError) as excinfo:
        va.execute(prepared(), session, sleep=sleeps, jitter=no_jitter, max_retries=3)
    assert excinfo.value.code == "request_failed"
    assert sleeps.delays == []


# ---------------------------------------------------------------------------
# 9. Security properties
# ---------------------------------------------------------------------------


def test_redact_headers_replaces_every_credential() -> None:
    safe = va.redact_headers(
        {
            "Authorization": f"Bearer {TOKEN}",
            "Cookie": "session=abc",
            "Accept": "application/json",
        }
    )
    assert safe["Authorization"] == "Bearer <redacted>"
    assert safe["Cookie"] == "<redacted>"
    assert safe["Accept"] == "application/json"
    assert TOKEN not in json.dumps(safe)


def test_redact_headers_does_not_mutate_the_original_headers() -> None:
    headers = {"Authorization": f"Bearer {TOKEN}"}
    va.redact_headers(headers)
    assert headers["Authorization"] == f"Bearer {TOKEN}"


def test_format_dry_run_never_prints_the_token() -> None:
    text = va.format_dry_run(prepared(filter_expr="country eq 'US'"))
    assert TOKEN not in text
    assert "Bearer <redacted>" in text
    assert "GET https://api.vercel.com/v1/query/web-analytics/visits/aggregate" in text
    assert "Nothing was sent" in text
    assert "projectId" in text and "requestPath" in text


def test_format_dry_run_shows_a_redacted_authorization_even_without_a_token() -> None:
    text = va.format_dry_run(prepared(token=None))
    assert "Bearer <redacted>" in text


@pytest.mark.parametrize("payload", [COUNTRY_PAYLOAD, VISITS_COUNT_PAYLOAD, DAILY_PAYLOAD])
def test_no_formatter_output_can_contain_the_token(payload: dict[str, Any]) -> None:
    group_by = [] if isinstance(payload["data"], dict) else ["country"]
    result = va.normalize(payload, "visits", group_by)
    for text in (
        va.format_table(result, time_range=(utc(2026, 8, 7), utc(2026, 8, 14))),
        va.format_json(result, payload),
        va.format_csv(result),
    ):
        assert TOKEN not in text


def test_no_exception_string_can_contain_the_token() -> None:
    session = FakeSession(FakeResponse(401, error_payload("forbidden", "Not authorized")))
    with pytest.raises(va.ApiError) as excinfo:
        va.execute(prepared(), session, sleep=Recorder(), jitter=no_jitter, max_retries=0)
    assert TOKEN not in str(excinfo.value)
    assert TOKEN not in repr(excinfo.value)

    network = FakeSession(requests.Timeout("timed out"))
    with pytest.raises(va.ApiError) as excinfo:
        va.execute(prepared(), network, sleep=Recorder(), jitter=no_jitter, max_retries=0)
    assert TOKEN not in str(excinfo.value)


def test_dry_run_without_a_token_exits_zero_and_never_touches_a_session(
    cli: Cli,
) -> None:
    session = ForbiddenSession()
    code, out, err = cli.run(
        ["top-pages", "--dry-run"],
        env={"VERCEL_PROJECT_ID": PROJECT},
        session=session,
    )
    assert code == 0
    assert err == ""
    assert cli.created == [], "a dry run must not construct a session at all"
    assert session.calls == []
    assert "Nothing was sent" in out
    assert "Bearer <redacted>" in out


def test_a_verbose_run_prints_redacted_headers_only(cli: Cli) -> None:
    session = FakeSession(FakeResponse(200, TOP_PAGES_PAYLOAD))
    code, out, err = cli.run(
        ["top-pages", "--verbose"], env=dict(BASE_ENV), session=session
    )
    assert code == 0
    assert "verbose: GET" in err
    assert "Bearer <redacted>" in err
    assert TOKEN not in err
    assert TOKEN not in out


def test_the_script_contains_exactly_one_http_call_site_and_it_is_a_get() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert source.count("session.get(") == 1
    for verb in ("post", "put", "patch", "delete", "head", "options", "request"):
        assert f"session.{verb}(" not in source
        assert f"requests.{verb}(" not in source


@pytest.mark.parametrize(
    "pattern",
    [r"\beval\s*\(", r"\bexec\s*\(", r"\bsubprocess\b", r"\bos\.system\b", r"\bopen\s*\("],
)
def test_the_script_has_no_dynamic_execution_or_filesystem_writes(pattern: str) -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert re.search(pattern, source) is None


def test_neither_the_script_nor_this_suite_uses_an_em_dash() -> None:
    em_dash = "\u2014"  # an escape, so this file stays free of the character
    for path in (SCRIPT_PATH, Path(__file__)):
        assert em_dash not in path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 10. main() end to end
# ---------------------------------------------------------------------------


def test_main_runs_top_pages_and_prints_a_table(cli: Cli) -> None:
    session = FakeSession(FakeResponse(200, TOP_PAGES_PAYLOAD))
    code, out, err = cli.run(
        ["top-pages", "--since", "7d", "--limit", "10"],
        env=dict(BASE_ENV),
        session=session,
    )
    assert code == 0
    assert err == ""
    assert len(session.calls) == 1
    assert session.calls[0]["url"] == f"{va.BASE_URL}/visits/aggregate"
    assert ("by", "requestPath") in session.calls[0]["params"]
    assert ("limit", "10") in session.calls[0]["params"]
    assert session.calls[0]["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert "/pricing" in out and "640" in out
    assert "TOTAL" in out and "820" in out
    assert session.closed is True


def test_main_top_pages_as_csv_parses_back(cli: Cli) -> None:
    session = FakeSession(FakeResponse(200, TOP_PAGES_PAYLOAD))
    code, out, _ = cli.run(["top-pages", "--csv"], env=dict(BASE_ENV), session=session)
    assert code == 0
    assert list(csv.reader(io.StringIO(out))) == [
        ["requestPath", "pageviews", "visitors"],
        ["/pricing", "640", "510"],
        ["/blog/my-post", "180", "150"],
    ]


def test_main_top_pages_as_json_includes_the_raw_payload(cli: Cli) -> None:
    session = FakeSession(FakeResponse(200, TOP_PAGES_PAYLOAD))
    code, out, _ = cli.run(["top-pages", "--json"], env=dict(BASE_ENV), session=session)
    assert code == 0
    document = json.loads(out)
    assert document["raw"] == TOP_PAGES_PAYLOAD
    assert document["totals"]["pageviews"] == 820


def test_main_total_preset_uses_the_count_endpoint(cli: Cli) -> None:
    session = FakeSession(FakeResponse(200, VISITS_COUNT_PAYLOAD))
    code, out, _ = cli.run(["total"], env=dict(BASE_ENV), session=session)
    assert code == 0
    assert session.calls[0]["url"] == f"{va.BASE_URL}/visits/count"
    assert all(name != "by" for name, _ in session.calls[0]["params"])
    assert "1,250" in out


def test_main_overview_issues_exactly_three_get_requests(cli: Cli) -> None:
    session = FakeSession(
        FakeResponse(200, DAILY_PAYLOAD),
        FakeResponse(200, TOP_PAGES_PAYLOAD),
        FakeResponse(200, REFERRERS_PAYLOAD),
    )
    code, out, err = cli.run([], env=dict(BASE_ENV), session=session)
    assert code == 0
    assert err == ""
    assert len(session.calls) == 3
    grouped = [
        [value for name, value in call["params"] if name == "by"]
        for call in session.calls
    ]
    assert grouped == [["day"], ["requestPath"], ["referrerHostname"]]
    assert all(
        call["url"] == f"{va.BASE_URL}/visits/aggregate" for call in session.calls
    )
    assert f"Vercel Web Analytics: {PROJECT}" in out
    assert "By day" in out
    assert "Top pages" in out and "Top referrers" in out


def test_main_overview_as_json_has_the_three_named_sections(cli: Cli) -> None:
    session = FakeSession(
        FakeResponse(200, DAILY_PAYLOAD),
        FakeResponse(200, TOP_PAGES_PAYLOAD),
        FakeResponse(200, REFERRERS_PAYLOAD),
    )
    code, out, _ = cli.run(["overview", "--json"], env=dict(BASE_ENV), session=session)
    assert code == 0
    document = json.loads(out)
    assert set(document["sections"]) == {"byGranularity", "topPages", "topReferrers"}
    assert document["sections"]["topPages"]["rows"][0]["key"] == "/pricing"


def test_main_exits_zero_on_an_empty_result(cli: Cli) -> None:
    session = FakeSession(FakeResponse(200, EMPTY_AGGREGATE_PAYLOAD))
    code, out, err = cli.run(["top-pages"], env=dict(BASE_ENV), session=session)
    assert code == 0
    assert err == ""
    assert "No visits data" in out
    assert "TOTAL" not in out


def test_main_exits_one_on_an_api_error_and_repeats_the_message(cli: Cli) -> None:
    session = FakeSession(
        FakeResponse(
            403, error_payload("forbidden", "You do not have permission for this project")
        )
    )
    code, out, err = cli.run(
        ["top-pages", "--max-retries", "0"], env=dict(BASE_ENV), session=session
    )
    assert code == 1
    assert out == ""
    assert "You do not have permission for this project" in err
    assert "HTTP 403" in err
    assert TOKEN not in err


def test_main_exits_one_on_a_rate_limit_with_a_hint(cli: Cli) -> None:
    body = error_payload(
        "rate_limited", "The rate limit of 6 exceeded", limit={"total": 6, "reset": 1}
    )
    session = FakeSession(FakeResponse(429, body))
    code, _, err = cli.run(
        ["top-pages", "--max-retries", "0"], env=dict(BASE_ENV), session=session
    )
    assert code == 1
    assert "The rate limit of 6 exceeded" in err
    assert "rate limits are per endpoint" in err


def test_main_exits_two_on_a_configuration_error(cli: Cli) -> None:
    code, out, err = cli.run(["top-pages"], env={"VERCEL_TOKEN": TOKEN})
    assert code == 2
    assert out == ""
    assert "--project" in err


def test_main_list_presets_prints_the_table_without_touching_the_network(
    cli: Cli,
) -> None:
    # The row contents are checked against hard-coded literals in section 12,
    # deliberately not against va.PRESETS: a test that iterates the same dict
    # the renderer iterates cannot detect a wrong value in it.
    code, out, err = cli.run(["--list-presets"], env={})
    assert code == 0
    assert err == ""
    assert "overview" in out and "3 x aggregate" in out


def test_main_version_prints_the_version_and_exits_zero(cli: Cli) -> None:
    code, out, _ = cli.run(["--version"], env={})
    assert code == 0
    assert va.VERSION in out


def test_main_applies_filter_flags_to_the_query(cli: Cli) -> None:
    session = FakeSession(FakeResponse(200, TOP_PAGES_PAYLOAD))
    code, _, _ = cli.run(
        ["top-pages", "--country", "US,DE", "--path", "/pricing", "--flag", "beta=true"],
        env=dict(BASE_ENV),
        session=session,
    )
    assert code == 0
    filters = [value for name, value in session.calls[0]["params"] if name == "filter"]
    assert filters == [
        "requestPath eq '/pricing' and country in ('US', 'DE') and flags/beta eq 'true'"
    ]


def test_main_events_preset_breaks_out_an_event_property(cli: Cli) -> None:
    session = FakeSession(FakeResponse(200, EVENT_DATA_PAYLOAD))
    code, out, _ = cli.run(
        ["events", "--event-property", "plan"], env=dict(BASE_ENV), session=session
    )
    assert code == 0
    grouped = [value for name, value in session.calls[0]["params"] if name == "by"]
    assert grouped == ["eventName", "eventData/plan"]
    assert session.calls[0]["url"] == f"{va.BASE_URL}/events/aggregate"
    assert "pro" in out and "42" in out


def test_main_team_slug_is_sent_as_slug(cli: Cli) -> None:
    session = FakeSession(FakeResponse(200, TOP_PAGES_PAYLOAD))
    env = dict(BASE_ENV, VERCEL_TEAM_SLUG="acme")
    code, _, _ = cli.run(["top-pages"], env=env, session=session)
    assert code == 0
    assert ("slug", "acme") in session.calls[0]["params"]
    assert all(name != "teamId" for name, _ in session.calls[0]["params"])


# ---------------------------------------------------------------------------
# 11. Filter shorthands, one row per documented flag
# ---------------------------------------------------------------------------
#
# Everything below drives the real CLI with --dry-run and reads the request
# back out of the printed encoded URL, which is the string the script promises
# is what would go on the wire. Asserting the whole parameter value means a
# flag wired to the wrong dimension (--browser building an osName clause, say)
# fails here instead of returning a confidently formatted wrong number.


def dry_run_calls(out: str) -> list[tuple[str, list[tuple[str, str]]]]:
    """Parse a ``--dry-run`` dump into ``(endpoint, query parameter pairs)``.

    One entry per request, so the three request overview parses too. The
    endpoint is the tail of the path, for example ``visits/aggregate``.
    """
    calls: list[tuple[str, list[tuple[str, str]]]] = []
    lines = out.splitlines()
    for index, line in enumerate(lines):
        if not line.startswith("Encoded URL"):
            continue
        split = urlsplit(lines[index + 1].strip())
        endpoint = split.path.split("/web-analytics/", 1)[1]
        calls.append((endpoint, parse_qsl(split.query, keep_blank_values=True)))
    return calls


def dry_run_values(out: str, name: str, call: int = 0) -> list[str]:
    """Every value sent for one query parameter, in order, from one request."""
    return [value for key, value in dry_run_calls(out)[call][1] if key == name]


DRY_RUN_ENV = {"VERCEL_PROJECT_ID": PROJECT}

# (flag, argv, the exact OData clause it must produce). Every row of the flag
# table in docs/cli-contract.md appears here.
FILTER_SHORTHAND_CASES: list[tuple[str, list[str], str]] = [
    ("--path", ["top-pages", "--path", "/pricing"], "requestPath eq '/pricing'"),
    ("--route", ["top-routes", "--route", "/blog/[slug]"], "route eq '/blog/[slug]'"),
    ("--country", ["countries", "--country", "US"], "country eq 'US'"),
    ("--device", ["devices", "--device", "mobile"], "deviceType eq 'mobile'"),
    ("--browser", ["browsers", "--browser", "Chrome"], "browserName eq 'Chrome'"),
    ("--os", ["operating-systems", "--os", "macOS"], "osName eq 'macOS'"),
    (
        "--referrer",
        ["referrers", "--referrer", "news.ycombinator.com"],
        "referrerHostname eq 'news.ycombinator.com'",
    ),
    (
        "--utm-source",
        ["campaigns", "--utm-source", "newsletter"],
        "utmSource eq 'newsletter'",
    ),
    ("--utm-medium", ["campaigns", "--utm-medium", "email"], "utmMedium eq 'email'"),
    (
        "--utm-campaign",
        ["campaigns", "--utm-campaign", "launch"],
        "utmCampaign eq 'launch'",
    ),
    ("--event-name", ["events", "--event-name", "signup"], "eventName eq 'signup'"),
    (
        "--flag",
        ["top-pages", "--flag", "beta_banner=true"],
        "flags/beta_banner eq 'true'",
    ),
    (
        "--environment",
        ["top-pages", "--environment", "preview"],
        "environment eq 'preview'",
    ),
    (
        "--filter",
        ["top-pages", "--filter", "startswith(requestPath, '/docs')"],
        "startswith(requestPath, '/docs')",
    ),
]


@pytest.mark.parametrize(
    ("argv", "expected"),
    [case[1:] for case in FILTER_SHORTHAND_CASES],
    ids=[case[0] for case in FILTER_SHORTHAND_CASES],
)
def test_every_filter_shorthand_builds_exactly_its_documented_clause(
    cli: Cli, argv: list[str], expected: str
) -> None:
    code, out, err = cli.run([*argv, "--dry-run"], env=dict(DRY_RUN_ENV))
    assert code == 0, err
    assert dry_run_values(out, "filter") == [expected]


def test_two_filter_shorthands_are_joined_with_and(cli: Cli) -> None:
    code, out, err = cli.run(
        ["top-pages", "--country", "US", "--browser", "Chrome", "--dry-run"],
        env=dict(DRY_RUN_ENV),
    )
    assert code == 0, err
    assert dry_run_values(out, "filter") == [
        "country eq 'US' and browserName eq 'Chrome'"
    ]


def test_a_comma_separated_shorthand_value_becomes_an_in_clause(cli: Cli) -> None:
    code, out, err = cli.run(
        ["countries", "--country", "US,DE,FR", "--dry-run"], env=dict(DRY_RUN_ENV)
    )
    assert code == 0, err
    assert dry_run_values(out, "filter") == ["country in ('US', 'DE', 'FR')"]


def test_repeating_flag_and_filter_appends_a_clause_each_time(cli: Cli) -> None:
    code, out, err = cli.run(
        [
            "top-pages",
            "--flag",
            "beta_banner=true",
            "--flag",
            "new_nav=false",
            "--filter",
            "not (deviceType eq 'bot')",
            "--dry-run",
        ],
        env=dict(DRY_RUN_ENV),
    )
    assert code == 0, err
    assert dry_run_values(out, "filter") == [
        "flags/beta_banner eq 'true' and flags/new_nav eq 'false' "
        "and not (deviceType eq 'bot')"
    ]


# ---------------------------------------------------------------------------
# 12. Presets, against literals from docs/cli-contract.md
# ---------------------------------------------------------------------------
#
# The expectations below are transcribed by hand from the preset table in
# docs/cli-contract.md. They are deliberately not read back from va.PRESETS,
# so a preset that quietly changes its dataset, grouping or limit fails here.

# preset -> one (endpoint, by values, limit) triple per request it issues.
PRESET_EXPECTATIONS: dict[str, list[tuple[str, list[str], str | None]]] = {
    "overview": [
        # The trend section asks for the API maximum so no bucket is dropped;
        # the two tables use the documented overview limit of 5.
        ("visits/aggregate", ["day"], "100"),
        ("visits/aggregate", ["requestPath"], "5"),
        ("visits/aggregate", ["referrerHostname"], "5"),
    ],
    "trend": [("visits/aggregate", ["day"], "100")],
    "top-pages": [("visits/aggregate", ["requestPath"], "10")],
    "top-routes": [("visits/aggregate", ["route"], "10")],
    "referrers": [("visits/aggregate", ["referrerHostname"], "10")],
    "countries": [("visits/aggregate", ["country"], "10")],
    "devices": [("visits/aggregate", ["deviceType"], "10")],
    "browsers": [("visits/aggregate", ["browserName"], "10")],
    "operating-systems": [("visits/aggregate", ["osName"], "10")],
    "campaigns": [("visits/aggregate", ["utmCampaign"], "10")],
    "events": [("events/aggregate", ["eventName"], "10")],
    "total": [("visits/count", [], None)],
}


@pytest.mark.parametrize("preset", sorted(PRESET_EXPECTATIONS))
def test_every_preset_hits_its_documented_endpoint_grouping_and_limit(
    cli: Cli, preset: str
) -> None:
    code, out, err = cli.run([preset, "--dry-run"], env=dict(DRY_RUN_ENV))
    assert code == 0, err
    calls = dry_run_calls(out)
    expected = PRESET_EXPECTATIONS[preset]
    assert len(calls) == len(expected), f"{preset} issued {len(calls)} requests"
    for (endpoint, params), (want_endpoint, want_by, want_limit) in zip(calls, expected):
        assert endpoint == want_endpoint
        assert [value for key, value in params if key == "by"] == want_by
        limits = [value for key, value in params if key == "limit"]
        assert limits == ([want_limit] if want_limit is not None else [])


def test_the_default_run_with_no_arguments_is_the_overview_preset(cli: Cli) -> None:
    code, out, err = cli.run(["--dry-run"], env=dict(DRY_RUN_ENV))
    assert code == 0, err
    assert [endpoint for endpoint, _ in dry_run_calls(out)] == [
        "visits/aggregate",
        "visits/aggregate",
        "visits/aggregate",
    ]
    assert dry_run_values(out, "by", call=0) == ["day"]
    assert dry_run_values(out, "by", call=1) == ["requestPath"]
    assert dry_run_values(out, "by", call=2) == ["referrerHostname"]


def preset_row(out: str, name: str) -> list[str]:
    """The --list-presets line for one preset, split into its cells."""
    for line in out.splitlines():
        cells = line.split()
        if cells and cells[0] == name:
            return cells
    raise AssertionError(f"no {name!r} row in:\n{out}")


def test_list_presets_rows_match_the_documented_table(cli: Cli) -> None:
    code, out, err = cli.run(["--list-presets"], env={})
    assert code == 0
    assert err == ""

    # Transcribed from docs/cli-contract.md, not from va.PRESETS.
    top_pages = preset_row(out, "top-pages")
    assert top_pages[1:5] == ["visits", "aggregate", "requestPath", "10"]

    total = preset_row(out, "total")
    assert total[1:5] == ["visits", "count", "none", "n/a"]

    events = preset_row(out, "events")
    assert events[1:3] == ["events", "aggregate"]
    assert "eventName" in " ".join(events)

    overview = preset_row(out, "overview")
    assert overview[1] == "(default)"
    assert "3 x aggregate" in " ".join(overview)


# ---------------------------------------------------------------------------
# 13. --granularity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("granularity", list(va.TIME_GRANULARITIES))
def test_granularity_replaces_the_presets_time_bucket(
    cli: Cli, granularity: str
) -> None:
    # The preset supplies "day". Appending rather than replacing would send two
    # time granularities, which the API forbids and rule 5 rejects, so this
    # covers both the wiring and the replacement.
    code, out, err = cli.run(
        ["trend", "--granularity", granularity, "--dry-run"], env=dict(DRY_RUN_ENV)
    )
    assert code == 0, err
    assert dry_run_values(out, "by") == [granularity]


def test_granularity_is_appended_to_an_explicit_grouping(cli: Cli) -> None:
    code, out, err = cli.run(
        ["top-pages", "--group-by", "country", "--granularity", "day", "--dry-run"],
        env=dict(DRY_RUN_ENV),
    )
    assert code == 0, err
    assert dry_run_values(out, "by") == ["country", "day"]


def test_granularity_on_top_of_an_explicit_time_dimension_is_a_config_error(
    cli: Cli,
) -> None:
    code, _, err = cli.run(
        ["trend", "--group-by", "day", "--granularity", "week"], env=dict(BASE_ENV)
    )
    assert code == 2
    assert "at most one time granularity" in err


def test_granularity_rebuckets_the_overview_trend_section(cli: Cli) -> None:
    code, out, err = cli.run(
        ["overview", "--granularity", "week", "--dry-run"], env=dict(DRY_RUN_ENV)
    )
    assert code == 0, err
    assert dry_run_values(out, "by", call=0) == ["week"]


def test_granularity_relabels_the_overview_trend_heading(cli: Cli) -> None:
    weekly = {
        "version": 1,
        "query": {"groupBy": ["week"]},
        "data": [{"timestamp": "2026-08-03T00:00:00.000Z", "pageviews": 9, "visitors": 7}],
    }
    session = FakeSession(
        FakeResponse(200, weekly),
        FakeResponse(200, TOP_PAGES_PAYLOAD),
        FakeResponse(200, REFERRERS_PAYLOAD),
    )
    code, out, _ = cli.run(
        ["overview", "--granularity", "week"], env=dict(BASE_ENV), session=session
    )
    assert code == 0
    assert "By week" in out


# ---------------------------------------------------------------------------
# 14. Interruption
# ---------------------------------------------------------------------------


def test_a_keyboard_interrupt_exits_one_hundred_and_thirty(cli: Cli) -> None:
    session = FakeSession(KeyboardInterrupt())
    code, out, err = cli.run(["top-pages"], env=dict(BASE_ENV), session=session)
    assert code == 130
    assert out == ""
    assert "interrupted" in err
    assert "Traceback" not in err
    assert session.closed is True


def test_a_keyboard_interrupt_between_overview_requests_still_exits_one_thirty(
    cli: Cli,
) -> None:
    session = FakeSession(FakeResponse(200, DAILY_PAYLOAD), KeyboardInterrupt())
    code, _, err = cli.run([], env=dict(BASE_ENV), session=session)
    assert code == 130
    assert "interrupted" in err


# ---------------------------------------------------------------------------
# 15. --timeout, --no-color and NO_COLOR wiring
# ---------------------------------------------------------------------------


class TtyStream(io.StringIO):
    """A stdout that claims to be a terminal, so the colour path activates."""

    def isatty(self) -> bool:
        return True


ANSI = "\033["


@pytest.mark.parametrize("value", ["12.5", "0.25", "90"])
def test_the_cli_forwards_its_parsed_timeout_to_the_request(
    cli: Cli, value: str
) -> None:
    session = FakeSession(FakeResponse(200, TOP_PAGES_PAYLOAD))
    code, _, _ = cli.run(
        ["top-pages", "--timeout", value], env=dict(BASE_ENV), session=session
    )
    assert code == 0
    assert session.calls[0]["timeout"] == float(value)


def test_the_default_timeout_is_forwarded_when_the_flag_is_absent(cli: Cli) -> None:
    session = FakeSession(FakeResponse(200, TOP_PAGES_PAYLOAD))
    code, _, _ = cli.run(["top-pages"], env=dict(BASE_ENV), session=session)
    assert code == 0
    assert session.calls[0]["timeout"] == va.DEFAULT_TIMEOUT


def test_color_is_used_on_a_tty_with_no_color_unset() -> None:
    out, err = TtyStream(), io.StringIO()
    assert va.main(["--list-presets"], {}, out=out, err=err) == 0
    assert ANSI in out.getvalue()


@pytest.mark.parametrize(
    ("argv", "env"),
    [
        (["--list-presets", "--no-color"], {}),
        (["--list-presets"], {"NO_COLOR": "1"}),
        (["--list-presets"], {"NO_COLOR": ""}),
    ],
    ids=["--no-color", "NO_COLOR=1", "NO_COLOR-empty"],
)
def test_color_is_suppressed_by_the_flag_and_by_no_color(
    argv: list[str], env: dict[str, str]
) -> None:
    out, err = TtyStream(), io.StringIO()
    assert va.main(argv, env, out=out, err=err) == 0
    text = out.getvalue()
    if env.get("NO_COLOR") == "":
        # An empty NO_COLOR is falsy, so the TTY still gets colour. Pinning the
        # behaviour here keeps the env check honest either way.
        assert ANSI in text
    else:
        assert ANSI not in text
    assert "Presets" in text


def test_color_is_suppressed_when_stdout_is_not_a_tty() -> None:
    out, err = io.StringIO(), io.StringIO()
    assert va.main(["--list-presets"], {}, out=out, err=err) == 0
    assert ANSI not in out.getvalue()


def test_a_report_on_a_tty_is_coloured_and_the_same_report_piped_is_not(
    cli: Cli,
) -> None:
    tty_out, err = TtyStream(), io.StringIO()
    session = FakeSession(FakeResponse(200, TOP_PAGES_PAYLOAD))
    cli.monkeypatch.setattr(requests, "Session", lambda: session)
    assert va.main(["top-pages"], dict(BASE_ENV), out=tty_out, err=err) == 0
    assert ANSI in tty_out.getvalue()

    plain_out = io.StringIO()
    session2 = FakeSession(FakeResponse(200, TOP_PAGES_PAYLOAD))
    cli.monkeypatch.setattr(requests, "Session", lambda: session2)
    assert va.main(["top-pages"], dict(BASE_ENV), out=plain_out, err=err) == 0
    assert ANSI not in plain_out.getvalue()


# ---------------------------------------------------------------------------
# 16. Version consistency across the repo
# ---------------------------------------------------------------------------


def test_the_version_matches_pyproject_and_the_skill_frontmatter() -> None:
    # pyyaml is not a dependency, so the frontmatter is read with a regex; the
    # pyproject version is parsed properly. This drift has happened before.
    tomllib: Any = pytest.importorskip("tomllib", reason="tomllib needs Python 3.11")
    pyproject = tomllib.loads(
        (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert pyproject["project"]["version"] == va.VERSION

    skill = (REPO_ROOT / "SKILL.md").read_text(encoding="utf-8")
    frontmatter = skill.split("---", 2)[1]
    match = re.search(r"^version:[ \t]*(\S+)[ \t]*$", frontmatter, re.MULTILINE)
    assert match is not None, "SKILL.md frontmatter has no version key"
    assert match.group(1) == va.VERSION


def test_the_version_is_reported_by_the_flag_and_the_user_agent(cli: Cli) -> None:
    code, out, _ = cli.run(["--version"], env={})
    assert code == 0
    assert out.strip() == f"vercel-analytics {va.VERSION}"
    assert prepared().headers["User-Agent"] == f"vercel-analytics-skill/{va.VERSION}"


# ---------------------------------------------------------------------------
# 17. Defensive parsing of malformed payloads
# ---------------------------------------------------------------------------


def test_normalize_rejects_an_aggregate_payload_with_no_data_key() -> None:
    with pytest.raises(va.ApiError) as excinfo:
        va.normalize({"version": 1, "query": {}}, "visits", ["country"])
    assert excinfo.value.code == "invalid_response"
    assert "missing or null" in str(excinfo.value)


def test_normalize_rejects_a_count_payload_with_no_data_key() -> None:
    with pytest.raises(va.ApiError) as excinfo:
        va.normalize({"version": 1, "query": {}}, "visits", [])
    assert excinfo.value.code == "invalid_response"
    assert "count response" in str(excinfo.value)


@pytest.mark.parametrize(
    ("group_by", "data", "expected"),
    [
        (["country"], {"pageviews": 5}, "aggregate response"),
        (["country"], "rows", "aggregate response"),
        (["country"], 7, "aggregate response"),
        ([], [{"pageviews": 5}], "count response"),
        ([], "totals", "count response"),
    ],
    ids=["aggregate-dict", "aggregate-str", "aggregate-int", "count-list", "count-str"],
)
def test_normalize_rejects_a_data_value_of_the_wrong_type(
    group_by: list[str], data: Any, expected: str
) -> None:
    payload = {"version": 1, "query": {}, "data": data}
    with pytest.raises(va.ApiError) as excinfo:
        va.normalize(payload, "visits", group_by)
    rendered = str(excinfo.value)
    assert expected in rendered
    assert excinfo.value.status == 200
    # The message names the shape only, so nothing from the body is echoed back.
    assert "pageviews" not in rendered
    assert "totals" not in rendered


def test_normalize_survives_a_row_that_carries_no_metrics() -> None:
    payload = {
        "version": 1,
        "query": {"groupBy": ["country"]},
        "data": [{"country": "US"}, {"country": "DE", "pageviews": 4}],
    }
    result = va.normalize(payload, "visits", ["country"])
    assert [row.key for row in result.rows] == ["US", "DE"]
    assert result.rows[0].metrics == {}
    assert result.totals()["pageviews"] == 4
    text = va.format_table(result)
    assert "US" in text and "DE" in text
    assert "Traceback" not in text


def test_normalize_skips_a_row_that_is_not_an_object() -> None:
    payload = {
        "version": 1,
        "query": {},
        "data": ["nonsense", 42, None, {"country": "US", "pageviews": 3}],
    }
    result = va.normalize(payload, "visits", ["country"])
    assert [row.key for row in result.rows] == ["US"]


def test_a_valid_json_body_that_is_not_an_object_is_a_clean_error() -> None:
    session = FakeSession(FakeResponse(200, text="[1, 2, 3]"))
    with pytest.raises(va.ApiError) as excinfo:
        va.execute(prepared(), session, sleep=Recorder(), jitter=no_jitter, max_retries=0)
    assert excinfo.value.code == "invalid_response"
    assert "not a JSON object" in str(excinfo.value)


def test_an_empty_response_body_is_a_clean_error() -> None:
    session = FakeSession(FakeResponse(200, text=""))
    with pytest.raises(va.ApiError) as excinfo:
        va.execute(prepared(), session, sleep=Recorder(), jitter=no_jitter, max_retries=0)
    assert "not a JSON object" in str(excinfo.value)


def test_a_malformed_payload_exits_one_rather_than_rendering_something(
    cli: Cli,
) -> None:
    session = FakeSession(FakeResponse(200, text="<html>gateway timeout</html>"))
    code, out, err = cli.run(
        ["top-pages", "--max-retries", "0"], env=dict(BASE_ENV), session=session
    )
    assert code == 1
    assert out == ""
    assert "Traceback" not in err


# ---------------------------------------------------------------------------
# 18. Regression cover for the security and correctness fixes
# ---------------------------------------------------------------------------

SECRET = "sk_SUPERSECRETVALUE"

BAD_TOKENS: list[tuple[str, str]] = [
    ("line-feed", SECRET + "\nX-Evil: 1"),
    ("carriage-return", SECRET + "\r"),
    ("crlf-injection", SECRET + "\r\nX-Evil: 1"),
    ("null-byte", "\x00" + SECRET),
    ("delete", SECRET + "\x7f"),
    ("tab", SECRET + "\t"),
    ("non-ascii", "café" + SECRET),
    ("leading-space", " " + SECRET),
    ("trailing-space", SECRET + " "),
]


@pytest.mark.parametrize(
    "token", [case[1] for case in BAD_TOKENS], ids=[case[0] for case in BAD_TOKENS]
)
def test_an_unusable_token_is_rejected_before_any_request_and_is_never_printed(
    cli: Cli, token: str
) -> None:
    # session stays None, so constructing one would fail the test outright.
    code, out, err = cli.run(
        ["top-pages", "--token", token], env={"VERCEL_PROJECT_ID": PROJECT}
    )
    assert code == 2
    assert out == ""
    assert cli.created == []
    assert "Traceback" not in err
    assert "access token" in err
    assert "not shown" in err
    assert SECRET not in err
    assert token not in err
    assert "X-Evil" not in err


def test_a_header_injecting_token_from_the_environment_is_rejected_too(
    cli: Cli,
) -> None:
    env = {"VERCEL_TOKEN": f"{SECRET}\nX-Evil: 1", "VERCEL_PROJECT_ID": PROJECT}
    code, out, err = cli.run(["top-pages"], env=env)
    assert code == 2
    assert out == ""
    assert cli.created == []
    assert SECRET not in err
    assert "X-Evil" not in err


def test_surrounding_whitespace_on_an_environment_token_is_trimmed_not_sent(
    cli: Cli,
) -> None:
    # The env reader trims, so a copy and paste with a trailing newline still
    # works; what matters is that the trimmed value is what reaches the header.
    session = FakeSession(FakeResponse(200, TOP_PAGES_PAYLOAD))
    env = {"VERCEL_TOKEN": f"  {TOKEN}\n", "VERCEL_PROJECT_ID": PROJECT}
    code, _, _ = cli.run(["top-pages"], env=env, session=session)
    assert code == 0
    assert session.calls[0]["headers"]["Authorization"] == f"Bearer {TOKEN}"


def test_validate_token_reports_the_position_and_class_but_not_the_value() -> None:
    with pytest.raises(va.ConfigError) as excinfo:
        va.validate_token(SECRET + "\n")
    message = str(excinfo.value)
    assert "line feed" in message
    assert f"position {len(SECRET) + 1}" in message
    assert str(len(SECRET) + 1) in message
    assert SECRET not in message


def test_a_usable_token_passes_validation_unchanged() -> None:
    assert va.validate_token(TOKEN) == TOKEN


def test_an_empty_token_is_rejected_with_the_docs_pointer() -> None:
    with pytest.raises(va.ConfigError) as excinfo:
        va.validate_token("")
    assert "VERCEL_TOKEN" in str(excinfo.value)


def test_the_repr_of_a_prepared_request_hides_the_token() -> None:
    request = prepared()
    for text in (repr(request), f"{request!r}", repr([request]), str([request])):
        assert TOKEN not in text
        assert "Bearer <redacted>" in text
    assert "visits/aggregate" in repr(request)


def test_scrub_credentials_removes_both_the_bearer_and_the_bare_token() -> None:
    headers = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}
    leaked = f"InvalidHeader: Bearer {TOKEN} and also {TOKEN} on its own"
    scrubbed = va.scrub_credentials(leaked, headers)
    assert TOKEN not in scrubbed
    assert "<redacted>" in scrubbed


def test_an_exception_message_quoting_the_header_is_scrubbed() -> None:
    session = FakeSession(requests.ConnectionError(f"failed sending Bearer {TOKEN}"))
    with pytest.raises(va.ApiError) as excinfo:
        va.execute(prepared(), session, sleep=Recorder(), jitter=no_jitter, max_retries=0)
    assert TOKEN not in str(excinfo.value)


def test_an_error_body_echoing_the_token_is_scrubbed() -> None:
    body = error_payload("bad_request", f"the header Bearer {TOKEN} was rejected")
    session = FakeSession(FakeResponse(400, body))
    with pytest.raises(va.ApiError) as excinfo:
        va.execute(prepared(), session, sleep=Recorder(), jitter=no_jitter, max_retries=0)
    assert TOKEN not in str(excinfo.value)


TWO_DIMENSION_PAYLOAD: dict[str, Any] = {
    "version": 1,
    "query": {"groupBy": ["eventName", "eventData/plan"], "limit": 10},
    "data": [
        {"eventName": "signup", "eventData": "free", "count": 30, "visitors": 28},
        {"eventName": "signup", "eventData": "pro", "count": 12, "visitors": 11},
        {"eventName": "purchase", "eventData": "pro", "count": 3, "visitors": 3},
    ],
}
TWO_DIMENSIONS = ["eventName", "eventData/plan"]


def test_a_two_dimension_grouping_keeps_both_labels_on_every_row() -> None:
    result = va.normalize(TWO_DIMENSION_PAYLOAD, "events", TWO_DIMENSIONS)
    assert result.group_dimensions == TWO_DIMENSIONS
    assert [row.labels for row in result.rows] == [
        ("signup", "free"),
        ("signup", "pro"),
        ("purchase", "pro"),
    ]
    assert result.metric_names == ["count", "visitors"]
    assert "eventData" not in result.rows[0].metrics
    assert "eventName" not in result.rows[0].metrics


def test_a_json_dimension_label_comes_from_its_base_key_not_a_stray_string() -> None:
    # eventData/plan rows arrive keyed plain "eventData". A row that also
    # carries some other string field must still take its label from the base
    # key, not from whichever string field happens to come first.
    payload = {
        "version": 1,
        "query": {"groupBy": ["eventName", "eventData/plan"]},
        "data": [
            {
                "eventName": "signup",
                "note": "unrelated",
                "eventData": "free",
                "count": 30,
                "visitors": 28,
            }
        ],
    }
    result = va.normalize(payload, "events", TWO_DIMENSIONS)
    assert result.rows[0].labels == ("signup", "free")
    assert "note" not in result.rows[0].metrics


def test_a_two_dimension_grouping_renders_both_columns_in_the_table() -> None:
    result = va.normalize(TWO_DIMENSION_PAYLOAD, "events", TWO_DIMENSIONS)
    lines = va.format_table(result).splitlines()
    assert lines[0].split() == ["eventName", "eventData/plan", "count", "visitors", "%", "count"]
    assert lines[2].split()[:2] == ["signup", "free"]
    assert lines[3].split()[:2] == ["signup", "pro"]
    assert lines[4].split()[:2] == ["purchase", "pro"]


def test_a_two_dimension_grouping_renders_both_columns_in_csv() -> None:
    result = va.normalize(TWO_DIMENSION_PAYLOAD, "events", TWO_DIMENSIONS)
    rows = list(csv.reader(io.StringIO(va.format_csv(result))))
    assert rows == [
        ["eventName", "eventData/plan", "count", "visitors"],
        ["signup", "free", "30", "28"],
        ["signup", "pro", "12", "11"],
        ["purchase", "pro", "3", "3"],
    ]


def test_a_two_dimension_grouping_names_both_labels_in_json_rows() -> None:
    result = va.normalize(TWO_DIMENSION_PAYLOAD, "events", TWO_DIMENSIONS)
    document = json.loads(va.format_json(result, TWO_DIMENSION_PAYLOAD))
    assert [row["groups"] for row in document["rows"]] == [
        {"eventName": "signup", "eventData/plan": "free"},
        {"eventName": "signup", "eventData/plan": "pro"},
        {"eventName": "purchase", "eventData/plan": "pro"},
    ]


def test_a_time_plus_dimension_grouping_puts_the_timestamp_column_first() -> None:
    payload = {
        "version": 1,
        "query": {"groupBy": ["day", "country"]},
        "data": [
            {"timestamp": "2026-08-01T00:00:00.000Z", "country": "US", "pageviews": 4,
             "visitors": 3},
        ],
    }
    result = va.normalize(payload, "visits", ["day", "country"])
    rows = list(csv.reader(io.StringIO(va.format_csv(result))))
    assert rows == [
        ["day", "country", "pageviews", "visitors"],
        ["2026-08-01", "US", "4", "3"],
    ]


TIME_ONLY_OTHERS_PAYLOAD: dict[str, Any] = {
    "version": 1,
    "query": {"groupBy": ["day"], "limit": 2},
    "data": [
        {"timestamp": "2026-08-01T00:00:00.000Z", "pageviews": 10, "visitors": 8},
        {"timestamp": "2026-08-02T00:00:00.000Z", "pageviews": 5, "visitors": 4},
        {"timestamp": "Others", "pageviews": 6, "visitors": 5},
    ],
}


def test_the_others_bucket_is_detected_on_a_time_only_grouping() -> None:
    result = va.normalize(TIME_ONLY_OTHERS_PAYLOAD, "visits", ["day"])
    assert [row.is_others for row in result.rows] == [False, False, True]
    assert result.totals()["pageviews"] == 21


def test_the_others_bucket_is_visible_and_annotated_on_a_time_only_grouping() -> None:
    result = va.normalize(TIME_ONLY_OTHERS_PAYLOAD, "visits", ["day"])
    text = va.format_table(result, limit=2)
    assert "Others" in text
    assert "is not a real value" in text
    assert "--limit 2" in text
    assert "21" in text


def test_an_others_row_without_a_label_never_renders_as_a_blank_cell() -> None:
    payload = {
        "version": 1,
        "query": {"groupBy": ["country"]},
        "data": [
            {"country": "US", "pageviews": 10, "visitors": 8},
            {"country": "Others", "pageviews": 6, "visitors": 5},
        ],
    }
    result = va.normalize(payload, "visits", ["country"])
    rows = list(csv.reader(io.StringIO(va.format_csv(result))))
    assert rows[2][0] == "Others"


def test_an_aggregate_body_shaped_like_a_count_exits_one_instead_of_rendering(
    cli: Cli,
) -> None:
    payload = {"version": 1, "query": {}, "data": {"pageviews": 1250, "visitors": 980}}
    session = FakeSession(FakeResponse(200, payload))
    code, out, err = cli.run(
        ["top-pages", "--max-retries", "0"], env=dict(BASE_ENV), session=session
    )
    assert code == 1
    assert out == ""
    assert "invalid_response" in err
    assert "1,250" not in out
    assert "Traceback" not in err


def test_a_count_body_shaped_like_an_aggregate_exits_one(cli: Cli) -> None:
    payload = {"version": 1, "query": {}, "data": [{"pageviews": 5, "visitors": 4}]}
    session = FakeSession(FakeResponse(200, payload))
    code, out, err = cli.run(["total"], env=dict(BASE_ENV), session=session)
    assert code == 1
    assert out == ""
    assert "invalid_response" in err


@pytest.mark.parametrize(
    "value", ["99999999999999999", "253402300800000", "99999999999999999999999"]
)
def test_an_out_of_range_unix_millisecond_value_is_a_config_error(value: str) -> None:
    with pytest.raises(va.ConfigError) as excinfo:
        va.parse_time_value(value, NOW)
    message = str(excinfo.value)
    assert "outside the representable range" in message
    assert str(va.MAX_UNIX_MS) in message


def test_the_largest_representable_unix_millisecond_value_still_parses() -> None:
    parsed = va.parse_time_value(str(va.MAX_UNIX_MS), NOW)
    assert parsed.year == 9999


def test_an_out_of_range_since_exits_two_without_a_traceback(cli: Cli) -> None:
    code, out, err = cli.run(
        ["top-pages", "--since", "99999999999999999", "--dry-run"],
        env=dict(DRY_RUN_ENV),
    )
    assert code == 2
    assert out == ""
    assert "Traceback" not in err
    assert "representable range" in err


@pytest.mark.parametrize("value", ["0", "-1", "-0.5", "1e400", "nan", "0.0"])
def test_a_bad_timeout_is_a_config_error_rather_than_a_traceback(
    cli: Cli, value: str
) -> None:
    code, out, err = cli.run(
        ["top-pages", "--timeout", value, "--dry-run"], env=dict(DRY_RUN_ENV)
    )
    assert code == 2
    assert out == ""
    assert "Traceback" not in err
    assert "--timeout" in err


@pytest.mark.parametrize("value", [0.0, -1.0, float("inf"), float("-inf"), float("nan")])
def test_validate_timeout_rejects_every_unusable_value(value: float) -> None:
    with pytest.raises(va.ConfigError):
        va.validate_timeout(value)


@pytest.mark.parametrize("value", [0.25, 1.0, 30.0, 600.0])
def test_validate_timeout_accepts_a_finite_positive_value(value: float) -> None:
    assert va.validate_timeout(value) == value


ODATA_INJECTION_KEYS: list[str] = [
    "x' or 1 eq '1",
    "plan' or requestPath eq '/admin",
    "'a' or 1 eq '1'",
    "'unbalanced",
    "a'b",
    "''",
    "'",
]


@pytest.mark.parametrize("key", ODATA_INJECTION_KEYS)
def test_a_crafted_flag_key_cannot_inject_odata_into_the_filter(
    cli: Cli, key: str
) -> None:
    code, out, err = cli.run(
        ["top-pages", "--flag", f"{key}=true", "--dry-run"], env=dict(DRY_RUN_ENV)
    )
    assert code == 2, out
    assert out == ""
    assert "Traceback" not in err


@pytest.mark.parametrize("key", ODATA_INJECTION_KEYS)
def test_a_crafted_grouping_key_cannot_inject_odata_into_by(
    cli: Cli, key: str
) -> None:
    code, out, err = cli.run(
        ["events", "--group-by", f"eventData/{key}", "--dry-run"],
        env=dict(DRY_RUN_ENV),
    )
    assert code == 2, out
    assert out == ""
    assert "Traceback" not in err


@pytest.mark.parametrize("key", ODATA_INJECTION_KEYS)
def test_a_crafted_event_property_cannot_inject_odata_into_by(
    cli: Cli, key: str
) -> None:
    code, out, err = cli.run(
        ["events", "--event-property", key, "--dry-run"], env=dict(DRY_RUN_ENV)
    )
    assert code == 2, out
    assert out == ""
    assert "Traceback" not in err


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("plan", "eventData/plan"),
        ("beta_2", "eventData/beta_2"),
        ("sign-up", "eventData/'sign-up'"),
        ("'sign-up'", "eventData/'sign-up'"),
        ("'it''s'", "eventData/'it''s'"),
        ("a/b", "eventData/a/b"),
    ],
)
def test_a_legal_event_property_reaches_by_exactly_as_documented(
    cli: Cli, key: str, expected: str
) -> None:
    code, out, err = cli.run(
        ["events", "--event-property", key, "--dry-run"], env=dict(DRY_RUN_ENV)
    )
    assert code == 0, err
    assert dry_run_values(out, "by") == ["eventName", expected]


def test_a_quote_in_a_filter_value_is_doubled_rather_than_escaping_the_clause(
    cli: Cli,
) -> None:
    code, out, err = cli.run(
        ["countries", "--country", "US' or 1 eq '1", "--dry-run"],
        env=dict(DRY_RUN_ENV),
    )
    assert code == 0, err
    assert dry_run_values(out, "filter") == ["country eq 'US'' or 1 eq ''1'"]


def test_a_multi_segment_json_key_is_accepted_per_the_openapi_schema() -> None:
    assert va.validate_dimension("eventData/a/b", "events") == "eventData/a/b"
    assert va.validate_dimension("flags/'a/b'", "visits") == "flags/'a/b'"


@pytest.mark.parametrize(
    "dimension",
    ["eventData/'a' or 1 eq '1'", "eventData/'unbalanced", "eventData/a'b", "flags/''"],
)
def test_a_malformed_quoted_json_key_is_rejected(dimension: str) -> None:
    with pytest.raises(va.ConfigError):
        va.validate_dimension(dimension, "events")
