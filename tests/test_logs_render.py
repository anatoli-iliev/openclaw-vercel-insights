"""Tests for the request logs renderers."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Mapping
from typing import Any

from helpers import LOGS_EMPTY_PAGE, LOGS_ERROR_PAGE, utc

from vercel_insights import logs as vi_logs
from vercel_insights.render import (
    LogReport,
    format_logs_csv,
    format_logs_json,
    render_error_summary,
    render_logs,
)

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


def test_a_two_call_truncation_says_it_is_the_most_recent_of_each_kind() -> None:
    # No explicit level or statusCode filter, so the errors preset ran its two
    # calls and merged them: what was cut is per kind, not a global top N, and
    # the footer must say so rather than let the generic sentence imply less.
    text = render_logs(_report(LOGS_ERROR_PAGE, truncated=True, requested_limit=2))
    assert "the most recent 2 of each kind rather than a global top 2" in text


def test_a_single_call_truncation_does_not_claim_a_merge_that_did_not_happen() -> None:
    # An explicit --level (or --status-code) collapses the errors preset to one
    # call, so there was no per-kind merge, and the sharper sentence would be a
    # lie here: it must not appear.
    text = render_logs(
        _report(
            LOGS_ERROR_PAGE,
            truncated=True,
            requested_limit=2,
            filters={"level": "error"},
        )
    )
    assert "of each kind" not in text


def test_the_footer_counts_the_errors_by_status() -> None:
    text = render_logs(_report(LOGS_ERROR_PAGE))
    assert "2 errors" in text


def test_expand_keeps_a_multiline_message_indented_under_its_row() -> None:
    # sanitize_message indents continuation lines by two spaces so nothing a
    # server sends can reach column zero; render_logs must add its own indent
    # on top of that on every line, not only the first, or a stack trace steps
    # backwards under --expand instead of staying nested under its row.
    payload = {
        "rows": [
            {
                "requestId": "trace-1",
                "timestamp": "2026-08-17T11:00:00.000Z",
                "statusCode": 500,
                "requestPath": "/api/checkout",
                "logs": [
                    {
                        "level": "error",
                        "message": "Error: boom\nat foo (a.js:1)\nat bar (b.js:2)",
                    }
                ],
            }
        ]
    }
    text = render_logs(_report(payload), expand=True)
    lines = [
        line
        for line in text.splitlines()
        if line.startswith(" ")
        and ("boom" in line or "at foo" in line or "at bar" in line)
    ]
    assert len(lines) == 3
    indents = [len(line) - len(line.lstrip(" ")) for line in lines]
    assert all(indent >= indents[0] for indent in indents)


def test_a_row_with_no_timestamp_says_so_rather_than_leaving_a_blank() -> None:
    payload = {
        "rows": [
            {
                "requestId": "no-time",
                "statusCode": 500,
                "requestPath": "/api/checkout",
            }
        ]
    }
    text = render_logs(_report(payload))
    assert "(no time)" in text


def test_a_window_over_a_day_shows_the_date_in_the_time_column() -> None:
    text = render_logs(
        _report(
            LOGS_ERROR_PAGE,
            time_range=(utc(2026, 8, 15, 11, 6), utc(2026, 8, 17, 11, 6)),
        )
    )
    assert "08-17 11:04:52" in text


# ---------------------------------------------------------------------------
# render_error_summary
# ---------------------------------------------------------------------------


def test_the_summary_prints_three_tables() -> None:
    report = _report(LOGS_ERROR_PAGE, preset="error-summary")
    text = render_error_summary(report, vi_logs.summarize(report.entries))
    assert "status" in text and "route" in text and "message" in text
    assert "TOTAL" in text
    assert "100.0%" in text


def test_the_summary_explains_a_non_5xx_row_in_the_status_table() -> None:
    payload = {
        "rows": [
            {
                "requestId": "a",
                "statusCode": 200,
                "timestamp": "2026-08-17T11:00:00.000Z",
                "logs": [{"level": "fatal", "message": "pool exhausted"}],
            }
        ]
    }
    report = _report(payload, preset="error-summary")
    text = render_error_summary(report, vi_logs.summarize(report.entries))
    assert "logged" in text


def test_json_output_keeps_every_field_the_api_sent() -> None:
    report = _report(LOGS_ERROR_PAGE)
    parsed = json.loads(format_logs_json(report))
    assert parsed["truncated"] is False
    assert parsed["pagesFetched"] == 1
    first = parsed["entries"][0]
    assert first["requestId"] == "err-1"
    assert first["status"] == 500
    assert first["lines"][0]["level"] == "error"
    # Nothing probed is thrown away: the whole row is still there.
    assert first["raw"]["cache"] == "MISS"


def test_json_output_is_strict_json() -> None:
    # The README sells piping --json into jq, so NaN and Infinity must never
    # reach the output.
    text = format_logs_json(_report(LOGS_ERROR_PAGE))
    assert "NaN" not in text and "Infinity" not in text


def test_json_output_escapes_a_control_character_in_the_raw_row() -> None:
    # raw is the one field kept verbatim, so this is what makes that safe: it
    # only ever leaves through json.dumps, which escapes the escape.
    payload = {"rows": [{"requestId": "a", "cacheReason": "\x1b[2Jgone"}]}
    text = format_logs_json(_report(payload))
    assert "\x1b" not in text
    assert "\\u001b" in text


def test_csv_output_has_one_row_per_request() -> None:
    text = format_logs_csv(_report(LOGS_ERROR_PAGE))
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == [
        "time",
        "level",
        "status",
        "method",
        "route",
        "path",
        "source",
        "requestId",
        "message",
    ]
    assert len(rows) == 3


def test_csv_keeps_a_hostile_message_inside_one_cell() -> None:
    payload = {
        "rows": [
            {
                "requestId": "a",
                "statusCode": 500,
                "logs": [{"level": "error", "message": "a\r\nerror: fine"}],
            }
        ]
    }
    rows = list(csv.reader(io.StringIO(format_logs_csv(_report(payload)))))
    assert len(rows) == 2
