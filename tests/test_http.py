"""Tests for vercel_insights/http.py: retries, backoff and error paths."""

from __future__ import annotations

import json

import pytest
import requests
from helpers import (
    COUNTRY_PAYLOAD,
    FakeResponse,
    FakeSession,
    Recorder,
    error_payload,
    no_jitter,
    prepared,
    utc,
)

from vercel_insights import ApiError, ConfigError, RateLimitError
from vercel_insights import http as vi_http
from vercel_insights.http import PreparedRequest

# ---------------------------------------------------------------------------
# Retry and backoff
# ---------------------------------------------------------------------------


def test_retry_delay_prefers_a_numeric_retry_after_header() -> None:
    response = FakeResponse(429, {}, {"Retry-After": "2"})
    assert vi_http.retry_delay(0, response, None, 1000.0) == 2.0


def test_retry_delay_understands_an_http_date_retry_after() -> None:
    when = utc(2015, 10, 21, 7, 28)
    header = {"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"}
    delay = vi_http.retry_delay(
        0, FakeResponse(429, {}, header), None, when.timestamp() - 5
    )
    assert delay == pytest.approx(5.0)


def test_retry_delay_falls_back_to_reset_ms_then_reset_then_backoff() -> None:
    body_ms = error_payload("rate_limited", "slow down", limit={"resetMs": 1003500})
    assert vi_http.retry_delay(0, FakeResponse(429, body_ms), body_ms, 1000.0) == 3.5

    body_s = error_payload("rate_limited", "slow down", limit={"reset": 1004})
    assert vi_http.retry_delay(0, FakeResponse(429, body_s), body_s, 1000.0) == 4.0

    assert vi_http.retry_delay(0, FakeResponse(500, {}), None, 1000.0) == 0.5


@pytest.mark.parametrize(
    ("attempt", "expected"), [(0, 0.5), (1, 1.0), (2, 2.0), (3, 4.0), (10, 60.0)]
)
def test_retry_delay_backoff_doubles_and_is_capped(
    attempt: int, expected: float
) -> None:
    assert vi_http.retry_delay(attempt, None, None, 1000.0) == expected


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
    payload = vi_http.execute(
        prepared(),
        session,
        sleep=sleeps,
        jitter=no_jitter,
        max_retries=3,
        now=lambda: 1000.0,
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
    payload = vi_http.execute(
        prepared(),
        session,
        sleep=sleeps,
        jitter=no_jitter,
        max_retries=3,
        now=lambda: 1000.0,
    )
    assert payload == COUNTRY_PAYLOAD
    assert sleeps.delays == [3.5]


def test_a_server_error_is_retried_with_exponential_backoff() -> None:
    sleeps = Recorder()
    session = FakeSession(
        FakeResponse(500, error_payload("internal_server_error", "boom")),
        FakeResponse(200, COUNTRY_PAYLOAD),
    )
    payload = vi_http.execute(
        prepared(), session, sleep=sleeps, jitter=no_jitter, max_retries=3
    )
    assert payload == COUNTRY_PAYLOAD
    assert sleeps.delays == [0.5]


def test_a_408_request_timeout_is_retried() -> None:
    # 408 is on the retryable list because the observability query API
    # documents it: a query can time out server side and is worth another go.
    sleeps = Recorder()
    session = FakeSession(
        FakeResponse(408, error_payload("request_timeout", "the query timed out")),
        FakeResponse(200, COUNTRY_PAYLOAD),
    )
    payload = vi_http.execute(
        prepared(), session, sleep=sleeps, jitter=no_jitter, max_retries=3
    )
    assert payload == COUNTRY_PAYLOAD
    assert sleeps.delays == [0.5]
    assert len(session.calls) == 2


def test_408_is_on_the_retryable_status_list() -> None:
    assert 408 in vi_http.RETRYABLE_STATUSES


def test_injected_jitter_is_added_to_every_delay() -> None:
    sleeps = Recorder()
    session = FakeSession(
        FakeResponse(500, error_payload("internal_server_error", "boom")),
        FakeResponse(503, error_payload("service_unavailable", "boom")),
        FakeResponse(200, COUNTRY_PAYLOAD),
    )
    vi_http.execute(
        prepared(), session, sleep=sleeps, jitter=lambda: 0.25, max_retries=3
    )
    assert sleeps.delays == [0.75, 1.25]


def test_exhausting_max_retries_reports_the_attempt_count() -> None:
    sleeps = Recorder()
    session = FakeSession(
        *[
            FakeResponse(500, error_payload("internal_server_error", "boom"))
            for _ in range(3)
        ]
    )
    with pytest.raises(ApiError) as excinfo:
        vi_http.execute(
            prepared(), session, sleep=sleeps, jitter=no_jitter, max_retries=2
        )
    assert "gave up after 3 attempts" in str(excinfo.value)
    assert "boom" in str(excinfo.value)
    assert sleeps.delays == [0.5, 1.0]
    assert len(session.calls) == 3


def test_exhausting_max_retries_on_a_rate_limit_raises_rate_limit_error() -> None:
    sleeps = Recorder()
    body = error_payload("rate_limited", "Try again in 7 days", limit={"total": 6})
    session = FakeSession(FakeResponse(429, body), FakeResponse(429, body))
    with pytest.raises(RateLimitError) as excinfo:
        vi_http.execute(
            prepared(), session, sleep=sleeps, jitter=no_jitter, max_retries=1
        )
    assert excinfo.value.limit == {"total": 6}
    assert "Try again in 7 days" in str(excinfo.value)
    assert sleeps.delays == [0.5]


def test_a_client_error_is_never_retried() -> None:
    sleeps = Recorder()
    session = FakeSession(
        FakeResponse(400, error_payload("bad_request", "Invalid value for by")),
        FakeResponse(200, COUNTRY_PAYLOAD),
    )
    with pytest.raises(ApiError) as excinfo:
        vi_http.execute(
            prepared(), session, sleep=sleeps, jitter=no_jitter, max_retries=3
        )
    assert excinfo.value.status == 400
    assert sleeps.delays == []
    assert len(session.calls) == 1


def test_a_timeout_is_retried_and_then_succeeds() -> None:
    sleeps = Recorder()
    session = FakeSession(
        requests.Timeout("timed out"), FakeResponse(200, COUNTRY_PAYLOAD)
    )
    payload = vi_http.execute(
        prepared(), session, sleep=sleeps, jitter=no_jitter, max_retries=2
    )
    assert payload == COUNTRY_PAYLOAD
    assert sleeps.delays == [0.5]


def test_repeated_network_failures_surface_as_an_api_error_with_attempts() -> None:
    sleeps = Recorder()
    session = FakeSession(
        requests.ConnectionError("no route"), requests.Timeout("timed out")
    )
    with pytest.raises(ApiError) as excinfo:
        vi_http.execute(
            prepared(), session, sleep=sleeps, jitter=no_jitter, max_retries=1
        )
    assert excinfo.value.status is None
    assert "could not reach" in str(excinfo.value)
    assert "gave up after 2 attempts" in str(excinfo.value)
    assert sleeps.delays == [0.5]


def test_max_retries_zero_makes_exactly_one_attempt() -> None:
    sleeps = Recorder()
    session = FakeSession(FakeResponse(503, error_payload("unavailable", "down")))
    with pytest.raises(ApiError):
        vi_http.execute(
            prepared(), session, sleep=sleeps, jitter=no_jitter, max_retries=0
        )
    assert sleeps.delays == []
    assert len(session.calls) == 1


def test_execute_sends_a_get_with_the_prepared_parameters_and_timeout() -> None:
    session = FakeSession(FakeResponse(200, COUNTRY_PAYLOAD))
    request = prepared()
    vi_http.execute(request, session, sleep=Recorder(), jitter=no_jitter, timeout=12.5)
    call = session.calls[0]
    assert call["method"] == "GET"
    assert call["url"] == request.url
    assert call["params"] == request.params
    assert call["headers"] == request.headers
    assert call["timeout"] == 12.5


def test_execute_sends_a_post_with_its_json_body_for_a_post_operation() -> None:
    # The dispatcher reads the verb out of OPERATIONS, so an operation the
    # table marks POST is issued as a POST and carries its body.
    body = {"metric": "vercel.speed_insights.lcp_ms", "scope": {"projectId": "prj"}}
    request = PreparedRequest(
        operation="observability_query",
        url="https://api.vercel.com/v2/observability/query",
        params=[],
        headers={"Accept": "application/json"},
        json_body=body,
    )
    session = FakeSession(FakeResponse(200, {"data": []}))
    vi_http.execute(request, session, sleep=Recorder(), jitter=no_jitter, timeout=9.0)
    call = session.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://api.vercel.com/v2/observability/query"
    assert call["json"] == body
    assert call["timeout"] == 9.0


# ---------------------------------------------------------------------------
# Error paths
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
    with pytest.raises(ApiError) as excinfo:
        vi_http.execute(
            prepared(), session, sleep=Recorder(), jitter=no_jitter, max_retries=0
        )
    error = excinfo.value
    assert error.status == status
    assert error.code == code
    assert error.message == message
    assert message in str(error)
    assert f"HTTP {status}" in str(error)


def test_a_non_json_success_body_becomes_a_clean_error() -> None:
    session = FakeSession(FakeResponse(200, text="<html>gateway</html>"))
    with pytest.raises(ApiError) as excinfo:
        vi_http.execute(
            prepared(), session, sleep=Recorder(), jitter=no_jitter, max_retries=0
        )
    assert "not a JSON object" in str(excinfo.value)
    assert not isinstance(excinfo.value, json.JSONDecodeError)


def test_a_non_json_error_body_falls_back_to_a_trimmed_snippet() -> None:
    session = FakeSession(FakeResponse(502, text="<html>\nbad gateway\n</html>"))
    with pytest.raises(ApiError) as excinfo:
        vi_http.execute(
            prepared(), session, sleep=Recorder(), jitter=no_jitter, max_retries=0
        )
    rendered = str(excinfo.value)
    assert "bad gateway" in rendered
    assert "\n" not in rendered


def test_an_error_body_without_a_message_still_renders() -> None:
    session = FakeSession(FakeResponse(400, {"error": {"code": "bad_request"}}))
    with pytest.raises(ApiError) as excinfo:
        vi_http.execute(
            prepared(), session, sleep=Recorder(), jitter=no_jitter, max_retries=0
        )
    assert "HTTP 400" in str(excinfo.value)
    assert "bad_request" in str(excinfo.value)


def test_an_unexpected_request_exception_is_not_retried() -> None:
    sleeps = Recorder()
    session = FakeSession(requests.TooManyRedirects("looping"))
    with pytest.raises(ApiError) as excinfo:
        vi_http.execute(
            prepared(), session, sleep=sleeps, jitter=no_jitter, max_retries=3
        )
    assert excinfo.value.code == "request_failed"
    assert sleeps.delays == []


def test_a_valid_json_body_that_is_not_an_object_is_a_clean_error() -> None:
    session = FakeSession(FakeResponse(200, text="[1, 2, 3]"))
    with pytest.raises(ApiError) as excinfo:
        vi_http.execute(
            prepared(), session, sleep=Recorder(), jitter=no_jitter, max_retries=0
        )
    assert excinfo.value.code == "invalid_response"
    assert "not a JSON object" in str(excinfo.value)


def test_an_empty_response_body_is_a_clean_error() -> None:
    session = FakeSession(FakeResponse(200, text=""))
    with pytest.raises(ApiError) as excinfo:
        vi_http.execute(
            prepared(), session, sleep=Recorder(), jitter=no_jitter, max_retries=0
        )
    assert "not a JSON object" in str(excinfo.value)


# ---------------------------------------------------------------------------
# --timeout validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value", [0.0, -1.0, float("inf"), float("-inf"), float("nan")]
)
def test_validate_timeout_rejects_every_unusable_value(value: float) -> None:
    with pytest.raises(ConfigError):
        vi_http.validate_timeout(value)


@pytest.mark.parametrize("value", [0.25, 1.0, 30.0, 600.0])
def test_validate_timeout_accepts_a_finite_positive_value(value: float) -> None:
    assert vi_http.validate_timeout(value) == value
