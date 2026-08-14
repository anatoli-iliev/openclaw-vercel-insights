"""The Speed Insights surface driven through the real CLI.

Everything here goes through ``main()``: the preset bodies, the per-surface
dimension spellings, the granularity translation, validation rules 14 to 22 and
the end to end runs. No test touches the network. A run that sends anything
uses a fake session; a run that must send nothing is given a session that fails
the test if it is used at all.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

import pytest
from conftest import Cli
from helpers import (
    BASE_ENV,
    CLS_ID,
    DRY_RUN_ENV,
    FCP_ID,
    INP_ID,
    LCP_COUNT_ID,
    LCP_ID,
    PROJECT,
    SPEED_EMPTY_PAYLOAD,
    SPEED_QUERY_URL,
    SPEED_ROUTE_PAYLOAD,
    SPEED_TREND_PAYLOAD,
    SPEED_VITALS_PAYLOADS,
    TOKEN,
    TTFB_ID,
    WEB_ANALYTICS_BASE,
    FakeResponse,
    FakeSession,
    ForbiddenSession,
    dry_run_bodies,
    dry_run_values,
    error_payload,
    patch_retry_sleep,
)

from vercel_insights import ConfigError
from vercel_insights.timerange import (
    SPEED_INSIGHTS,
    WEB_ANALYTICS,
    normalize_granularity,
)

WINDOW = ["--since", "2026-08-07T00:00:00Z", "--until", "2026-08-14T00:00:00Z"]
START = "2026-08-07T00:00:00Z"
END = "2026-08-14T00:00:00Z"
SCOPE: dict[str, Any] = {"type": "project", "projectId": PROJECT}


# ---------------------------------------------------------------------------
# 1. One exact request body per Speed Insights preset
# ---------------------------------------------------------------------------
#
# Every body below is written out in full, from the preset table and the
# request body table in docs/. Comparing whole dicts is what makes an added,
# renamed or nulled field fail rather than pass unnoticed.

PRESET_BODIES: list[tuple[str, list[str], list[dict[str, Any]]]] = [
    (
        "vitals",
        ["vitals"],
        [
            {
                "metric": metric_id,
                "scope": SCOPE,
                "aggregation": "p75",
                "startTime": START,
                "endTime": END,
            }
            for metric_id in (LCP_ID, INP_ID, CLS_ID, FCP_ID, TTFB_ID)
        ],
    ),
    (
        "slowest-pages",
        ["slowest-pages"],
        [
            {
                "metric": LCP_ID,
                "scope": SCOPE,
                "aggregation": "p75",
                "groupBy": ["route"],
                "limit": 10,
                "orderBy": "value",
                "orderDirection": "desc",
                "startTime": START,
                "endTime": END,
            }
        ],
    ),
    (
        "fastest-pages",
        ["fastest-pages"],
        [
            {
                "metric": LCP_ID,
                "scope": SCOPE,
                "aggregation": "p75",
                "groupBy": ["route"],
                "limit": 10,
                "orderBy": "value",
                "orderDirection": "asc",
                "startTime": START,
                "endTime": END,
            }
        ],
    ),
    (
        "vitals-by-country",
        ["vitals-by-country"],
        [
            {
                "metric": LCP_ID,
                "scope": SCOPE,
                "aggregation": "p75",
                "groupBy": ["country"],
                "limit": 10,
                "startTime": START,
                "endTime": END,
            }
        ],
    ),
    (
        "vitals-by-device",
        ["vitals-by-device"],
        [
            {
                "metric": LCP_ID,
                "scope": SCOPE,
                "aggregation": "p75",
                "groupBy": ["device_type"],
                "limit": 10,
                "startTime": START,
                "endTime": END,
            }
        ],
    ),
    (
        "vitals-trend",
        ["vitals-trend"],
        [
            {
                "metric": LCP_ID,
                "scope": SCOPE,
                "aggregation": "p75",
                "granularity": {"interval": "1d"},
                "startTime": START,
                "endTime": END,
            }
        ],
    ),
    (
        "data-points",
        ["data-points"],
        [
            {
                "metric": LCP_COUNT_ID,
                "scope": SCOPE,
                "aggregation": "sum",
                "groupBy": ["route"],
                "limit": 10,
                "startTime": START,
                "endTime": END,
            }
        ],
    ),
    (
        "vitals-by-country-with-metric",
        ["vitals-by-country", "--metric", "cls", "--percentile", "95"],
        [
            {
                "metric": CLS_ID,
                "scope": SCOPE,
                "aggregation": "p95",
                "groupBy": ["country"],
                "limit": 10,
                "startTime": START,
                "endTime": END,
            }
        ],
    ),
    (
        "vitals-trend-with-granularity",
        ["vitals-trend", "--metric", "inp", "--granularity", "1mo"],
        [
            {
                "metric": INP_ID,
                "scope": SCOPE,
                "aggregation": "p75",
                "granularity": {"interval": "1mo"},
                "startTime": START,
                "endTime": END,
            }
        ],
    ),
]


@pytest.mark.parametrize(
    ("argv", "expected"),
    [case[1:] for case in PRESET_BODIES],
    ids=[case[0] for case in PRESET_BODIES],
)
def test_every_speed_preset_builds_exactly_its_documented_post_body(
    cli: Cli, argv: list[str], expected: list[dict[str, Any]]
) -> None:
    code, out, err = cli.run([*argv, *WINDOW, "--dry-run"], env=dict(DRY_RUN_ENV))
    assert code == 0, err
    assert dry_run_bodies(out) == expected


@pytest.mark.parametrize(
    ("argv", "expected"),
    [case[1:] for case in PRESET_BODIES],
    ids=[case[0] for case in PRESET_BODIES],
)
def test_the_body_a_preset_actually_posts_is_the_body_it_printed(
    cli: Cli, argv: list[str], expected: list[dict[str, Any]]
) -> None:
    # The same expectation, this time read off the session rather than out of
    # the dry run, so a dry run that prints one thing and sends another fails.
    payloads = [FakeResponse(200, SPEED_EMPTY_PAYLOAD) for _ in expected]
    session = FakeSession(*payloads)
    code, _out, err = cli.run([*argv, *WINDOW], env=dict(BASE_ENV), session=session)
    assert code == 0, err
    assert [call["json"] for call in session.calls] == expected
    assert all(call["method"] == "POST" for call in session.calls)
    assert all(call["url"] == SPEED_QUERY_URL for call in session.calls)


@pytest.mark.parametrize(
    "preset",
    [
        "vitals",
        "slowest-pages",
        "fastest-pages",
        "vitals-by-country",
        "vitals-by-device",
        "vitals-trend",
        "data-points",
    ],
)
def test_no_speed_preset_ever_sends_an_optional_field_as_null(
    cli: Cli, preset: str
) -> None:
    code, out, err = cli.run([preset, *WINDOW, "--dry-run"], env=dict(DRY_RUN_ENV))
    assert code == 0, err
    for body in dry_run_bodies(out):
        assert None not in body.values()
        assert "null" not in json.dumps(body)


@pytest.mark.parametrize(
    ("preset", "grouped"),
    [
        ("vitals", False),
        ("vitals-trend", False),
        ("slowest-pages", True),
        ("fastest-pages", True),
        ("vitals-by-country", True),
        ("vitals-by-device", True),
        ("data-points", True),
    ],
)
def test_ordering_and_limit_appear_only_on_a_grouped_query(
    cli: Cli, preset: str, grouped: bool
) -> None:
    code, out, err = cli.run([preset, *WINDOW, "--dry-run"], env=dict(DRY_RUN_ENV))
    assert code == 0, err
    for body in dry_run_bodies(out):
        assert ("groupBy" in body) is grouped
        assert ("limit" in body) is grouped
        if not grouped:
            assert "orderBy" not in body
            assert "orderDirection" not in body


def test_an_ordered_grouped_query_names_both_the_column_and_the_direction(
    cli: Cli,
) -> None:
    code, out, err = cli.run(
        ["vitals-by-country", "--order-by", "count", "--order", "asc", *WINDOW, "--dry-run"],
        env=dict(DRY_RUN_ENV),
    )
    assert code == 0, err
    body = dry_run_bodies(out)[0]
    assert body["orderBy"] == "count"
    assert body["orderDirection"] == "asc"


def test_all_projects_sends_an_owner_scope_and_no_project_id(cli: Cli) -> None:
    code, out, err = cli.run(
        ["vitals-by-country", "--all", *WINDOW, "--dry-run"], env={}
    )
    assert code == 0, err
    body = dry_run_bodies(out)[0]
    assert body["scope"] == {"type": "owner"}
    assert PROJECT not in json.dumps(body)


def test_data_points_without_an_aggregation_sums_rather_than_percentiles(
    cli: Cli,
) -> None:
    # The 75th percentile of a number of measurements answers nothing.
    code, out, err = cli.run(
        ["vitals-by-country", "--data-points", *WINDOW, "--dry-run"],
        env=dict(DRY_RUN_ENV),
    )
    assert code == 0, err
    body = dry_run_bodies(out)[0]
    assert body["metric"] == LCP_COUNT_ID
    assert body["aggregation"] == "sum"


# ---------------------------------------------------------------------------
# 2. Dimension spelling per surface
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("flag", "value", "web_clause", "speed_clause"),
    [
        ("--path", "/pricing", "requestPath eq '/pricing'", "request_path eq '/pricing'"),
        ("--device", "mobile", "deviceType eq 'mobile'", "device_type eq 'mobile'"),
        ("--route", "/blog/[slug]", "route eq '/blog/[slug]'", "route eq '/blog/[slug]'"),
        ("--country", "US", "country eq 'US'", "country eq 'US'"),
        (
            "--environment",
            "production",
            "environment eq 'production'",
            "environment eq 'production'",
        ),
    ],
)
def test_a_shared_shorthand_compiles_to_the_spelling_of_the_active_surface(
    cli: Cli, flag: str, value: str, web_clause: str, speed_clause: str
) -> None:
    code, out, err = cli.run(
        ["top-pages", flag, value, "--dry-run"], env=dict(DRY_RUN_ENV)
    )
    assert code == 0, err
    assert dry_run_values(out, "filter") == [web_clause]

    code, out, err = cli.run(
        ["slowest-pages", flag, value, "--dry-run"], env=dict(DRY_RUN_ENV)
    )
    assert code == 0, err
    assert dry_run_bodies(out)[0]["filter"] == speed_clause


@pytest.mark.parametrize(
    ("flag", "value", "web_dimension"),
    [
        ("--browser", "Chrome", "browserName"),
        ("--os", "macOS", "osName"),
        ("--referrer", "news.ycombinator.com", "referrerHostname"),
        ("--utm-source", "newsletter", "utmSource"),
        ("--utm-medium", "email", "utmMedium"),
        ("--utm-campaign", "launch", "utmCampaign"),
    ],
)
def test_a_web_analytics_only_shorthand_is_a_config_error_on_the_speed_surface(
    cli: Cli, flag: str, value: str, web_dimension: str
) -> None:
    code, out, err = cli.run(
        ["slowest-pages", flag, value, "--dry-run"], env=dict(DRY_RUN_ENV)
    )
    assert code == 2
    assert out == ""
    assert flag in err
    assert web_dimension in err
    assert "Speed Insights" in err
    assert "Traceback" not in err


@pytest.mark.parametrize(
    ("flag", "value"),
    [("--event-name", "signup"), ("--event-property", "plan"), ("--flag", "beta=true")],
)
def test_a_web_analytics_only_option_is_a_config_error_on_a_speed_preset(
    cli: Cli, flag: str, value: str
) -> None:
    code, out, err = cli.run(["vitals", flag, value], env=dict(BASE_ENV))
    assert code == 2
    assert out == ""
    assert flag in err
    assert "vitals" in err


@pytest.mark.parametrize(
    ("camel", "snake"),
    [("requestPath", "request_path"), ("deviceType", "device_type")],
)
def test_a_camel_case_grouping_on_the_speed_surface_names_the_snake_case_one(
    cli: Cli, camel: str, snake: str
) -> None:
    code, out, err = cli.run(
        ["vitals-by-country", "--group-by", camel], env=dict(BASE_ENV)
    )
    assert code == 2
    assert out == ""
    assert camel in err and snake in err
    assert "snake_case" in err


@pytest.mark.parametrize(
    ("snake", "camel"),
    [("request_path", "requestPath"), ("device_type", "deviceType")],
)
def test_a_snake_case_grouping_on_the_web_surface_names_the_camel_case_one(
    cli: Cli, snake: str, camel: str
) -> None:
    code, out, err = cli.run(["top-pages", "--group-by", snake], env=dict(BASE_ENV))
    assert code == 2
    assert out == ""
    assert snake in err and camel in err
    assert "camelCase" in err


def test_a_speed_grouping_reaches_the_body_in_its_own_spelling(cli: Cli) -> None:
    code, out, err = cli.run(
        ["vitals-by-country", "--group-by", "request_path", "--dry-run"],
        env=dict(DRY_RUN_ENV),
    )
    assert code == 0, err
    assert dry_run_bodies(out)[0]["groupBy"] == ["request_path"]


# ---------------------------------------------------------------------------
# 3. Granularity translation, both vocabularies, both surfaces
# ---------------------------------------------------------------------------

GRANULARITY_TRANSLATIONS: list[tuple[str, str, str | None]] = [
    ("hour", "hour", "1h"),
    ("1h", "hour", "1h"),
    ("day", "day", "1d"),
    ("1d", "day", "1d"),
    ("month", "month", "1mo"),
    ("1mo", "month", "1mo"),
    ("week", "week", None),
    ("year", "year", None),
]


@pytest.mark.parametrize(
    ("value", "web", "speed"),
    GRANULARITY_TRANSLATIONS,
    ids=[case[0] for case in GRANULARITY_TRANSLATIONS],
)
def test_normalize_granularity_translates_into_each_surfaces_vocabulary(
    value: str, web: str, speed: str | None
) -> None:
    assert normalize_granularity(value, WEB_ANALYTICS) == web
    if speed is None:
        with pytest.raises(ConfigError) as excinfo:
            normalize_granularity(value, SPEED_INSIGHTS)
        message = str(excinfo.value)
        assert value in message
        assert "Speed Insights" in message
        assert "no equivalent" in message
    else:
        assert normalize_granularity(value, SPEED_INSIGHTS) == speed


def test_normalize_granularity_refuses_a_spelling_neither_surface_knows() -> None:
    with pytest.raises(ConfigError) as excinfo:
        normalize_granularity("fortnight", SPEED_INSIGHTS)
    assert "unknown granularity" in str(excinfo.value)


@pytest.mark.parametrize(
    ("value", "interval"),
    [("hour", "1h"), ("1h", "1h"), ("day", "1d"), ("1d", "1d"), ("month", "1mo"), ("1mo", "1mo")],
)
def test_either_vocabulary_reaches_the_speed_body_as_the_interval(
    cli: Cli, value: str, interval: str
) -> None:
    code, out, err = cli.run(
        ["vitals-trend", "--granularity", value, "--dry-run"], env=dict(DRY_RUN_ENV)
    )
    assert code == 0, err
    assert dry_run_bodies(out)[0]["granularity"] == {"interval": interval}


@pytest.mark.parametrize(("value", "expected"), [("1h", "hour"), ("1d", "day"), ("1mo", "month")])
def test_the_speed_vocabulary_is_accepted_on_web_analytics_and_translated_back(
    cli: Cli, value: str, expected: str
) -> None:
    code, out, err = cli.run(
        ["trend", "--granularity", value, "--dry-run"], env=dict(DRY_RUN_ENV)
    )
    assert code == 0, err
    assert dry_run_values(out, "by") == [expected]


@pytest.mark.parametrize("value", ["week", "year"])
def test_week_and_year_are_fine_on_web_analytics_and_refused_on_speed_insights(
    cli: Cli, value: str
) -> None:
    code, out, err = cli.run(
        ["trend", "--granularity", value, "--dry-run"], env=dict(DRY_RUN_ENV)
    )
    assert code == 0, err
    assert dry_run_values(out, "by") == [value]

    code, out, err = cli.run(
        ["vitals-trend", "--granularity", value], env=dict(BASE_ENV)
    )
    assert code == 2
    assert out == ""
    assert value in err
    assert "Speed Insights" in err
    assert "1h" in err and "1d" in err and "1mo" in err


# ---------------------------------------------------------------------------
# 4. Validation rules 14 to 22
# ---------------------------------------------------------------------------

SPEED_CONFIG_ERRORS: list[tuple[str, list[str], dict[str, str], list[str]]] = [
    (
        "rule14-dataset-with-metric",
        ["top-pages", "--dataset", "visits", "--metric", "lcp"],
        dict(BASE_ENV),
        ["--dataset", "--metric", "mutually exclusive"],
    ),
    (
        "rule15-web-shorthand-on-speed",
        ["slowest-pages", "--browser", "Chrome"],
        dict(BASE_ENV),
        ["--browser", "browserName", "Speed Insights", "route"],
    ),
    (
        "rule15-web-dimension-on-speed",
        ["slowest-pages", "--group-by", "browserName"],
        dict(BASE_ENV),
        ["browserName", "no Speed Insights", "request_path"],
    ),
    (
        "rule15-speed-dimension-on-web",
        ["top-pages", "--group-by", "device_type"],
        dict(BASE_ENV),
        ["device_type", "deviceType", "camelCase"],
    ),
    (
        "rule16-granularity-week-on-speed",
        ["vitals-trend", "--granularity", "week"],
        dict(BASE_ENV),
        ["week", "Speed Insights", "hour (1h)", "day (1d)", "month (1mo)"],
    ),
    (
        "rule16-granularity-year-on-speed",
        ["vitals-trend", "--granularity", "year"],
        dict(BASE_ENV),
        ["year", "no equivalent"],
    ),
    (
        "rule17-all-with-project",
        ["vitals", "--all", "--project", "prj_other"],
        dict(BASE_ENV),
        ["--all", "--project", "mutually exclusive"],
    ),
    (
        "rule18-percentile-50",
        ["vitals", "--percentile", "50"],
        dict(BASE_ENV),
        ["--percentile 50", "75, 90, 95, 99"],
    ),
    (
        "rule18-percentile-100",
        ["vitals-by-country", "--percentile", "100"],
        dict(BASE_ENV),
        ["--percentile 100", "75, 90, 95, 99"],
    ),
    (
        "rule19-unknown-metric",
        ["vitals-by-country", "--metric", "lcpp"],
        dict(BASE_ENV),
        ["unknown metric 'lcpp'", "Did you mean 'lcp'?", "lcp, inp, cls, fcp, ttfb"],
    ),
    (
        "rule19-real-experience-score",
        ["vitals-by-country", "--metric", "res"],
        dict(BASE_ENV),
        ["Real Experience Score is not queryable", "dashboard"],
    ),
    (
        "rule20-order-by-without-grouping",
        ["vitals-trend", "--order-by", "value"],
        dict(BASE_ENV),
        ["--order-by", "not grouped", "--group-by route"],
    ),
    (
        "rule20-order-without-grouping",
        ["vitals-trend", "--order", "asc"],
        dict(BASE_ENV),
        ["--order", "nothing to order"],
    ),
    (
        "rule20-unknown-order-by-column",
        ["slowest-pages", "--order-by", "route"],
        dict(BASE_ENV),
        ["--order-by 'route'", "count, value"],
    ),
    (
        "rule20-unknown-order-direction",
        ["slowest-pages", "--order", "sideways"],
        dict(BASE_ENV),
        ["--order 'sideways'", "desc or asc"],
    ),
    (
        "rule22-metric-on-web-preset",
        ["top-pages", "--metric", "lcp"],
        dict(BASE_ENV),
        ["--metric", "Speed Insights surface", "top-pages", "vitals"],
    ),
    (
        "rule22-percentile-on-web-preset",
        ["countries", "--percentile", "90"],
        dict(BASE_ENV),
        ["--percentile", "Web Analytics", "vitals"],
    ),
    (
        "rule22-aggregation-on-web-preset",
        ["trend", "--aggregation", "sum"],
        dict(BASE_ENV),
        ["--aggregation", "Speed Insights surface"],
    ),
    (
        "rule22-order-by-on-web-preset",
        ["top-pages", "--order-by", "count"],
        dict(BASE_ENV),
        ["--order-by", "Speed Insights surface"],
    ),
    (
        "rule22-order-on-web-preset",
        ["top-pages", "--order", "asc"],
        dict(BASE_ENV),
        ["--order", "Speed Insights surface"],
    ),
    (
        "rule22-bucket-timezone-on-web-preset",
        ["trend", "--bucket-timezone", "Europe/Paris"],
        dict(BASE_ENV),
        ["--bucket-timezone", "Speed Insights surface"],
    ),
    (
        "rule22-all-on-web-preset",
        ["top-pages", "--all"],
        dict(BASE_ENV),
        ["--all", "Speed Insights surface"],
    ),
    (
        "rule22-data-points-on-web-preset",
        ["top-pages", "--data-points"],
        dict(BASE_ENV),
        ["--data-points", "Speed Insights surface"],
    ),
    (
        "aggregation-and-percentile-together",
        ["vitals", "--aggregation", "max", "--percentile", "90"],
        dict(BASE_ENV),
        ["--aggregation", "--percentile", "shorthand"],
    ),
    (
        "bad-bucket-timezone",
        ["vitals-trend", "--bucket-timezone", "Europe/Paris; drop"],
        dict(BASE_ENV),
        ["--bucket-timezone", "IANA"],
    ),
    (
        "speed-limit-out-of-bounds",
        ["slowest-pages", "--limit", "101"],
        dict(BASE_ENV),
        ["--limit 101", "1 to 100"],
    ),
    (
        "vitals-rejects-group-by",
        ["vitals", "--group-by", "route"],
        dict(BASE_ENV),
        ["vitals", "--group-by", "vitals-by-country"],
    ),
    (
        "vitals-rejects-csv",
        ["vitals", "--csv"],
        dict(BASE_ENV),
        ["--csv", "one query per web vital"],
    ),
    (
        "speed-json-with-csv",
        ["slowest-pages", "--json", "--csv"],
        dict(BASE_ENV),
        ["--json", "--csv", "mutually exclusive"],
    ),
]


@pytest.mark.parametrize(
    ("argv", "env", "fragments"),
    [case[1:] for case in SPEED_CONFIG_ERRORS],
    ids=[case[0] for case in SPEED_CONFIG_ERRORS],
)
def test_a_speed_config_error_exits_two_and_names_the_fix(
    cli: Cli, argv: list[str], env: dict[str, str], fragments: list[str]
) -> None:
    # session stays None, so building one would fail the test outright: every
    # rule below is enforced before anything reaches the network.
    code, out, err = cli.run(argv, env=env)
    assert code == 2
    assert out == ""
    assert err.startswith("error: ")
    assert "Traceback" not in err
    assert cli.created == []
    for fragment in fragments:
        assert fragment in err, f"{fragment!r} missing from {err!r}"


def test_rule21_a_bucket_timezone_on_an_hourly_bucket_warns_and_still_runs(
    cli: Cli,
) -> None:
    code, out, err = cli.run(
        [
            "vitals-trend",
            "--granularity",
            "1h",
            "--bucket-timezone",
            "Europe/Paris",
            *WINDOW,
            "--dry-run",
        ],
        env=dict(DRY_RUN_ENV),
    )
    assert code == 0, err
    assert "warning:" in err
    assert "--bucket-timezone Europe/Paris" in err
    assert "no effect" in err
    assert "error:" not in err
    # It is still sent: the API ignores it, and the printed body must say what
    # would really go on the wire.
    assert dry_run_bodies(out)[0]["bucketTimezone"] == "Europe/Paris"


@pytest.mark.parametrize("granularity", ["1d", "1mo"])
def test_a_bucket_timezone_on_a_calendar_bucket_warns_about_nothing(
    cli: Cli, granularity: str
) -> None:
    code, out, err = cli.run(
        [
            "vitals-trend",
            "--granularity",
            granularity,
            "--bucket-timezone",
            "America/New_York",
            *WINDOW,
            "--dry-run",
        ],
        env=dict(DRY_RUN_ENV),
    )
    assert code == 0, err
    assert err == ""
    assert dry_run_bodies(out)[0]["bucketTimezone"] == "America/New_York"


# ---------------------------------------------------------------------------
# 5. main() end to end
# ---------------------------------------------------------------------------


def test_vitals_issues_exactly_five_posts_one_per_web_vital(cli: Cli) -> None:
    session = FakeSession(
        *[FakeResponse(200, payload) for payload in SPEED_VITALS_PAYLOADS]
    )
    code, out, err = cli.run(["vitals", *WINDOW], env=dict(BASE_ENV), session=session)
    assert code == 0, err
    assert len(session.calls) == 5
    assert all(call["method"] == "POST" for call in session.calls)
    assert [call["json"]["metric"] for call in session.calls] == [
        LCP_ID,
        INP_ID,
        CLS_ID,
        FCP_ID,
        TTFB_ID,
    ]
    assert f"Vercel Speed Insights: {PROJECT}" in out
    assert session.closed is True


def test_slowest_pages_issues_exactly_one_post(cli: Cli) -> None:
    session = FakeSession(FakeResponse(200, SPEED_ROUTE_PAYLOAD))
    code, out, err = cli.run(
        ["slowest-pages", *WINDOW], env=dict(BASE_ENV), session=session
    )
    assert code == 0, err
    assert len(session.calls) == 1
    assert session.calls[0]["method"] == "POST"
    assert session.calls[0]["url"] == SPEED_QUERY_URL
    assert "/blog/[slug]" in out
    assert "4.1 s" in out


def test_a_web_analytics_preset_still_issues_a_get_and_no_post(cli: Cli) -> None:
    session = FakeSession(FakeResponse(200, {"version": 1, "query": {}, "data": []}))
    code, _out, err = cli.run(["top-pages"], env=dict(BASE_ENV), session=session)
    assert code == 0, err
    assert [call["method"] for call in session.calls] == ["GET"]
    assert session.calls[0]["url"].startswith(WEB_ANALYTICS_BASE)


def test_a_vitals_trend_renders_its_time_buckets(cli: Cli) -> None:
    session = FakeSession(FakeResponse(200, SPEED_TREND_PAYLOAD))
    code, out, err = cli.run(
        ["vitals-trend", *WINDOW], env=dict(BASE_ENV), session=session
    )
    assert code == 0, err
    assert "2026-08-10" in out and "2026-08-11" in out
    assert "2.1 s" in out and "2.5 s" in out
    assert "T00:00:00.000Z" not in out


def test_an_empty_speed_result_exits_zero_with_one_explanatory_line(cli: Cli) -> None:
    session = FakeSession(FakeResponse(200, SPEED_EMPTY_PAYLOAD))
    code, out, err = cli.run(
        ["slowest-pages", *WINDOW], env=dict(BASE_ENV), session=session
    )
    assert code == 0
    assert err == ""
    assert f"No {LCP_ID} data for project {PROJECT}" in out
    assert "grouped by route" in out
    assert "Try a wider --since" in out


def test_an_empty_vitals_run_exits_zero_without_printing_a_table(cli: Cli) -> None:
    session = FakeSession(*[FakeResponse(200, SPEED_EMPTY_PAYLOAD) for _ in range(5)])
    code, out, err = cli.run(["vitals", *WINDOW], env=dict(BASE_ENV), session=session)
    assert code == 0
    assert err == ""
    assert "meets target" not in out
    assert f"No {LCP_ID} data" in out


def test_a_speed_api_error_exits_one_and_repeats_vercels_message(cli: Cli) -> None:
    session = FakeSession(
        FakeResponse(403, error_payload("forbidden", "Speed Insights is not enabled"))
    )
    code, out, err = cli.run(
        ["slowest-pages", "--max-retries", "0"], env=dict(BASE_ENV), session=session
    )
    assert code == 1
    assert out == ""
    assert "Speed Insights is not enabled" in err
    assert "HTTP 403" in err
    assert TOKEN not in err


def test_a_speed_config_error_exits_two_without_constructing_a_session(
    cli: Cli,
) -> None:
    code, out, err = cli.run(["vitals", "--percentile", "50"], env=dict(BASE_ENV))
    assert code == 2
    assert out == ""
    assert cli.created == []
    assert "--percentile 50" in err


def test_an_unreadable_speed_response_exits_one_rather_than_rendering_a_number(
    cli: Cli,
) -> None:
    session = FakeSession(FakeResponse(200, {"version": 1, "query": {}}))
    code, out, err = cli.run(
        ["slowest-pages", "--max-retries", "0"], env=dict(BASE_ENV), session=session
    )
    assert code == 1
    assert out == ""
    assert "invalid_response" in err
    assert "Traceback" not in err


def test_a_408_from_the_query_endpoint_is_retried_and_then_succeeds(
    cli: Cli,
) -> None:
    # 408 is documented on the observability query endpoint and on no Web
    # Analytics endpoint: a query can time out server side, and that is worth
    # another attempt.
    delays = patch_retry_sleep(cli.monkeypatch)
    session = FakeSession(
        FakeResponse(408, error_payload("request_timeout", "the query timed out")),
        FakeResponse(200, SPEED_ROUTE_PAYLOAD),
    )
    code, out, err = cli.run(
        ["slowest-pages", *WINDOW], env=dict(BASE_ENV), session=session
    )
    assert code == 0, err
    assert len(session.calls) == 2
    assert all(call["method"] == "POST" for call in session.calls)
    assert delays == [0.5]
    assert "/blog/[slug]" in out


def test_a_408_that_never_clears_exits_one_after_the_documented_attempts(
    cli: Cli,
) -> None:
    delays = patch_retry_sleep(cli.monkeypatch)
    session = FakeSession(
        *[
            FakeResponse(408, error_payload("request_timeout", "the query timed out"))
            for _ in range(3)
        ]
    )
    code, out, err = cli.run(
        ["slowest-pages", "--max-retries", "2", *WINDOW],
        env=dict(BASE_ENV),
        session=session,
    )
    assert code == 1
    assert out == ""
    assert len(session.calls) == 3
    assert delays == [0.5, 1.0]
    assert "the query timed out" in err


def test_a_400_from_the_query_endpoint_is_not_retried(cli: Cli) -> None:
    delays = patch_retry_sleep(cli.monkeypatch)
    session = FakeSession(
        FakeResponse(400, error_payload("bad_request", "granularity is not an object"))
    )
    code, _out, err = cli.run(
        ["vitals-trend", *WINDOW], env=dict(BASE_ENV), session=session
    )
    assert code == 1
    assert len(session.calls) == 1
    assert delays == []
    # The API's own wording for a shape this client guessed wrong is surfaced
    # verbatim, which is the whole recovery path for an unpinned schema.
    assert "granularity is not an object" in err


def test_a_speed_run_as_json_carries_the_metric_unit_target_and_raw_payload(
    cli: Cli,
) -> None:
    session = FakeSession(FakeResponse(200, SPEED_ROUTE_PAYLOAD))
    code, out, err = cli.run(
        ["slowest-pages", "--json", *WINDOW], env=dict(BASE_ENV), session=session
    )
    assert code == 0, err
    document = json.loads(out)
    assert document["metric"] == LCP_ID
    assert document["metricLabel"] == "Largest Contentful Paint"
    assert document["unit"] == "ms"
    assert document["target"] == 2500.0
    assert document["raw"] == SPEED_ROUTE_PAYLOAD
    assert document["rows"][0]["key"] == "/blog/[slug]"
    # A percentile does not add up, so no totals are reported at all.
    assert document["totals"] is None


def test_a_vitals_run_as_json_keys_its_sections_by_metric_id(cli: Cli) -> None:
    session = FakeSession(
        *[FakeResponse(200, payload) for payload in SPEED_VITALS_PAYLOADS]
    )
    code, out, err = cli.run(
        ["vitals", "--json", *WINDOW], env=dict(BASE_ENV), session=session
    )
    assert code == 0, err
    document = json.loads(out)
    assert list(document["metrics"]) == [LCP_ID, INP_ID, CLS_ID, FCP_ID, TTFB_ID]
    assert document["aggregation"] == "p75"
    assert document["range"] == {"since": START, "until": END}


def test_a_grouped_speed_run_as_csv_parses_back(cli: Cli) -> None:
    session = FakeSession(FakeResponse(200, SPEED_ROUTE_PAYLOAD))
    code, out, err = cli.run(
        ["slowest-pages", "--csv", *WINDOW], env=dict(BASE_ENV), session=session
    )
    assert code == 0, err
    rows = list(csv.reader(io.StringIO(out)))
    assert rows[0] == ["route", "p75_lcp", "data_points"]
    assert rows[1] == ["/blog/[slug]", "4120.0", "1830.0"]


def test_a_dry_run_of_a_post_sends_nothing_and_needs_no_token(cli: Cli) -> None:
    session = ForbiddenSession()
    code, out, err = cli.run(
        ["vitals", "--dry-run"], env=dict(DRY_RUN_ENV), session=session
    )
    assert code == 0, err
    assert cli.created == [], "a dry run must not construct a session at all"
    assert session.calls == []
    assert out.count(f"POST {SPEED_QUERY_URL}") == 5
    assert out.count("JSON body:") == 5
    assert out.count("Nothing was sent") == 5


def test_a_dry_run_of_a_post_with_no_query_parameters_prints_no_trailing_question_mark(
    cli: Cli,
) -> None:
    code, out, err = cli.run(["vitals-trend", "--dry-run"], env=dict(DRY_RUN_ENV))
    assert code == 0, err
    assert f"{SPEED_QUERY_URL}?" not in out
    assert SPEED_QUERY_URL in out


def test_list_presets_shows_every_speed_preset_with_its_query_endpoint(
    cli: Cli,
) -> None:
    code, out, err = cli.run(["--list-presets"], env={})
    assert code == 0
    assert err == ""
    rows = {
        line.split()[0]: line.split()
        for line in out.splitlines()
        if line.split() and not line.startswith(" ")
    }
    # Transcribed from the preset table in docs/cli-contract.md.
    assert rows["vitals"][1:4] == ["speed", "5", "x"]
    assert rows["slowest-pages"][1:5] == ["speed", "query", "route", "10"]
    assert rows["fastest-pages"][1:5] == ["speed", "query", "route", "10"]
    assert rows["vitals-by-country"][1:5] == ["speed", "query", "country", "10"]
    assert rows["vitals-by-device"][1:5] == ["speed", "query", "device_type", "10"]
    assert rows["vitals-trend"][1:5] == ["speed", "query", "1d", "n/a"]
    assert rows["data-points"][1:5] == ["speed", "query", "route", "10"]
