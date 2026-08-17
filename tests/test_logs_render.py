"""Tests for the request logs renderers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from helpers import LOGS_EMPTY_PAGE, LOGS_ERROR_PAGE, utc

from vercel_insights import logs as vi_logs
from vercel_insights.render import LogReport, render_logs

WINDOW = (utc(2026, 8, 17, 10, 36), utc(2026, 8, 17, 11, 6))


def _report(payload: Mapping[str, Any], **overrides: object) -> LogReport:
    entries, _more = vi_logs.normalize(payload)
    kwargs: dict[str, object] = {
        "time_range": WINDOW,
        "project_label": "dobri-web",
        "preset": "errors",
        "filters": {},
        "truncated": False,
        "pages_fetched": 1,
        "requested_limit": 50,
        "counts_errors": True,
    }
    kwargs.update(overrides)
    return vi_logs.build_report(entries, **kwargs)  # type: ignore[arg-type]


def test_the_table_shows_one_row_per_request() -> None:
    text = render_logs(_report(LOGS_ERROR_PAGE))
    assert "Vercel request logs: dobri-web (errors" in text
    assert "Range: 2026-08-17T10:36:00Z to 2026-08-17T11:06:00Z (UTC)" in text
    assert "/api/checkout" in text
    # The fixture message is 46 characters, wider than LOG_MESSAGE_WIDTH (34),
    # so the compact table truncates it; the untruncated form is covered by
    # test_expand_prints_the_whole_message_under_the_row instead.
    assert "TypeError: Cannot read properties" in text
    assert "500" in text and "502" in text


def test_the_header_says_what_counts_as_an_error() -> None:
    text = render_logs(_report(LOGS_ERROR_PAGE))
    assert vi_logs.ERROR_DEFINITION in text


def test_a_request_that_logged_nothing_says_so_rather_than_showing_a_blank() -> None:
    text = render_logs(_report(LOGS_ERROR_PAGE))
    assert "(no log line" in text


def test_a_row_with_no_level_shows_a_dash() -> None:
    lines = render_logs(_report(LOGS_ERROR_PAGE)).splitlines()
    row = next(line for line in lines if "/api/offerings/[slug]" in line)
    assert " -  " in row or row.split()[1] == "-"


def test_expand_prints_the_whole_message_under_the_row() -> None:
    long_message = "Error: " + "x" * 200
    payload = {
        "rows": [
            {
                "requestId": "a",
                "timestamp": "2026-08-17T11:00:00.000Z",
                "statusCode": 500,
                "requestPath": "/api/checkout",
                "logs": [{"level": "error", "message": long_message}],
            }
        ]
    }
    compact = render_logs(_report(payload))
    expanded = render_logs(_report(payload), expand=True)
    assert long_message not in compact
    assert long_message in expanded


def test_an_empty_result_names_the_window_and_the_retention_limits() -> None:
    # Six hours is longer than the shortest retention any plan has, so an empty
    # answer here genuinely might be aged-out logs rather than a healthy site.
    text = render_logs(
        _report(
            LOGS_EMPTY_PAGE,
            time_range=(utc(2026, 8, 17, 5, 6), utc(2026, 8, 17, 11, 6)),
        )
    )
    assert "No request logs" in text
    assert "1 hour on Hobby" in text


def test_a_thirty_minute_window_does_not_lecture_about_retention() -> None:
    # Inside the shortest retention window there is nothing to warn about, and a
    # warning on every empty answer trains the reader to ignore it. WINDOW is 30
    # minutes.
    text = render_logs(_report(LOGS_EMPTY_PAGE))
    assert "No request logs" in text
    assert "1 hour on Hobby" not in text


def test_truncation_is_stated_rather_than_implied() -> None:
    text = render_logs(_report(LOGS_ERROR_PAGE, truncated=True, requested_limit=2))
    assert "more" in text.lower()


def test_the_footer_counts_the_errors_by_status() -> None:
    text = render_logs(_report(LOGS_ERROR_PAGE))
    assert "2 errors" in text
