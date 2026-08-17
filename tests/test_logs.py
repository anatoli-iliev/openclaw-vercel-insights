"""Tests for vercel_insights/logs.py: the request logs surface.

The API validates almost nothing: an unknown level or source comes back as 200
with zero rows, which would read as "your site is fine". So the vocabularies are
checked here, before a request exists, and these tests are what hold that line.
"""

from __future__ import annotations

import pytest
from helpers import LOGS_URL, OWNER, PROJECT, TOKEN, logs_request

from vercel_insights import ConfigError
from vercel_insights import logs as vi_logs


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("error", "error"),
        ("ERROR", "error"),
        (" error , fatal ", "error,fatal"),
        ("error,fatal,warning,info", "error,fatal,warning,info"),
    ],
)
def test_validate_levels_normalizes_a_valid_list(value: str, expected: str) -> None:
    assert vi_logs.validate_levels(value) == expected


@pytest.mark.parametrize("value", ["erro", "errors", "critical", "", ","])
def test_validate_levels_refuses_anything_the_api_would_silently_ignore(
    value: str,
) -> None:
    with pytest.raises(ConfigError) as excinfo:
        vi_logs.validate_levels(value)
    message = str(excinfo.value)
    # The message has to name the four accepted values and say why a typo is
    # dangerous here rather than merely wrong.
    for level in vi_logs.LEVELS:
        assert level in message
    assert "zero rows" in message


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("serverless", "serverless"),
        ("edge-function,static", "edge-function,static"),
        (" EDGE-MIDDLEWARE ", "edge-middleware"),
    ],
)
def test_validate_sources_normalizes_a_valid_list(value: str, expected: str) -> None:
    assert vi_logs.validate_sources(value) == expected


@pytest.mark.parametrize("value", ["lambda", "edge", "function", ""])
def test_validate_sources_refuses_an_unknown_source(value: str) -> None:
    with pytest.raises(ConfigError) as excinfo:
        vi_logs.validate_sources(value)
    message = str(excinfo.value)
    # Same message builder as validate_levels, so it owes the same two checks:
    # every accepted value named, and the zero-rows danger explained.
    for source in vi_logs.SOURCES:
        assert source in message
    assert "zero rows" in message


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("500", "500"),
        ("5xx", "5xx"),
        ("4xx,5xx", "4xx,5xx"),
        ("401,4xx", "401,4xx"),
        ("40x", "40x"),
        ("5XX", "5xx"),
        ("none", "None"),
        (" 500 , 502 ", "500,502"),
    ],
)
def test_validate_status_code_accepts_what_the_api_accepts(
    value: str, expected: str
) -> None:
    # Verified live: comma separated integers, classes like 4xx or 5xx, or the
    # literal None. See docs/api-notes.md.
    assert vi_logs.validate_status_code(value) == expected


@pytest.mark.parametrize("value", [">=500", "xxx", "5**", "", "1234", "-1"])
def test_validate_status_code_refuses_what_the_api_rejects(value: str) -> None:
    with pytest.raises(ConfigError) as excinfo:
        vi_logs.validate_status_code(value)
    assert "4xx" in str(excinfo.value)


@pytest.mark.parametrize("limit", [1, 50, 200])
def test_validate_limit_accepts_the_documented_range(limit: int) -> None:
    assert vi_logs.validate_limit(limit) == limit


@pytest.mark.parametrize("limit", [0, -1, 201, 1000])
def test_validate_limit_refuses_a_limit_outside_the_range(limit: int) -> None:
    with pytest.raises(ConfigError) as excinfo:
        vi_logs.validate_limit(limit)
    assert "200" in str(excinfo.value)


def test_the_level_vocabulary_matches_the_severity_table() -> None:
    # The names are validated here and ranked in render.py, where LogEntry needs
    # them. Two spellings of the same vocabulary would drift, so the invariant is
    # asserted instead.
    from vercel_insights.render import ERROR_LEVELS, LOG_LEVEL_SEVERITY

    assert set(vi_logs.LEVELS) == set(LOG_LEVEL_SEVERITY)
    assert set(ERROR_LEVELS) <= set(vi_logs.LEVELS)
    assert ERROR_LEVELS == ("error", "fatal")


def test_build_request_targets_the_allowlisted_operation() -> None:
    request = logs_request()
    assert request.operation == "request_logs"
    assert request.url == LOGS_URL
    assert request.method == "GET"


def test_build_request_sends_the_five_required_parameters_first() -> None:
    request = logs_request()
    assert request.params[:5] == [
        ("projectId", PROJECT),
        ("ownerId", OWNER),
        ("page", "0"),
        ("startDate", "1786961168000"),
        ("endDate", "1786964768000"),
    ]


def test_build_request_puts_the_token_only_in_the_header() -> None:
    request = logs_request()
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in request.url
    assert all(TOKEN not in value for _name, value in request.params)


def test_build_request_emits_filters_in_a_fixed_order() -> None:
    request = logs_request(
        filters={
            "search": "boom",
            "level": "error,fatal",
            "statusCode": "5xx",
            "requestPath": "/api/checkout",
        }
    )
    names = [name for name, _value in request.params]
    assert names == [
        "projectId",
        "ownerId",
        "page",
        "startDate",
        "endDate",
        "level",
        "statusCode",
        "requestPath",
        "search",
    ]


def test_build_request_pages() -> None:
    assert ("page", "3") in logs_request(page=3).params


def test_build_request_refuses_a_parameter_that_is_not_on_the_allowlist() -> None:
    # The filters mapping reaches this function from the CLI, so it is the last
    # place an arbitrary query parameter could be introduced.
    with pytest.raises(ConfigError) as excinfo:
        logs_request(filters={"callback": "javascript:alert(1)"})
    assert "callback" in str(excinfo.value)


def test_build_request_drops_an_empty_filter_value() -> None:
    assert ("search", "") not in logs_request(filters={"search": ""}).params


def test_build_request_sends_no_team_parameter() -> None:
    # Verified live: teamId is not accepted here, and ownerId is what scopes the
    # call. Sending teamId as well would be cargo cult.
    names = [name for name, _value in logs_request().params]
    assert "teamId" not in names and "slug" not in names
