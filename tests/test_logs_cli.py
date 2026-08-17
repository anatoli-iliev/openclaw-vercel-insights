"""Tests for the request logs paths through cli.py.

Mirrors tests/test_speed_cli.py: one module per surface through the CLI, so a
change to one surface cannot quietly rewrite another's behaviour.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from conftest import Cli
from helpers import BASE_ENV, DRY_RUN_ENV, dry_run_calls, dry_run_values

LOGS_ONLY_FLAGS: list[list[str]] = [
    ["--level", "error"],
    ["--status-code", "500"],
    ["--source", "serverless"],
    ["--method", "POST"],
    ["--search", "boom"],
    ["--request-id", "abc"],
    ["--branch", "main"],
    ["--deployment", "dpl_abc"],
    ["--expand"],
]


@pytest.mark.parametrize("flag", LOGS_ONLY_FLAGS, ids=lambda item: item[0])
def test_a_logs_flag_is_refused_on_a_traffic_preset(cli: Cli, flag: list[str]) -> None:
    code, _out, err = cli.run(
        ["top-pages", *flag], dict(DRY_RUN_ENV) | {"VERCEL_TOKEN": "t"}
    )
    assert code == 2
    assert flag[0] in err
    # The message has to name where the flag does work, or the reader is stuck.
    assert "errors" in err or "logs" in err


@pytest.mark.parametrize("flag", LOGS_ONLY_FLAGS, ids=lambda item: item[0])
def test_a_logs_flag_is_refused_on_a_speed_preset(cli: Cli, flag: list[str]) -> None:
    code, _out, err = cli.run(
        ["vitals", *flag], dict(DRY_RUN_ENV) | {"VERCEL_TOKEN": "t"}
    )
    assert code == 2
    assert flag[0] in err


WRONG_ON_LOGS: list[tuple[list[str], str]] = [
    (["--group-by", "route"], "--group-by"),
    (["--granularity", "day"], "--granularity"),
    (["--filter", "route eq '/x'"], "--filter"),
    (["--dataset", "events"], "--dataset"),
    (["--event-name", "signup"], "--event-name"),
    (["--event-property", "plan"], "--event-property"),
    (["--flag", "beta=true"], "--flag"),
    (["--country", "US"], "--country"),
    (["--device", "mobile"], "--device"),
    (["--browser", "Safari"], "--browser"),
    (["--os", "macOS"], "--os"),
    (["--referrer", "example.com"], "--referrer"),
    (["--utm-source", "news"], "--utm-source"),
    (["--metric", "lcp"], "--metric"),
    (["--percentile", "95"], "--percentile"),
    (["--all"], "--all"),
    (["--budget", "lcp=2500"], "--budget"),
]


@pytest.mark.parametrize(
    ("argv", "flag"), WRONG_ON_LOGS, ids=[flag for _argv, flag in WRONG_ON_LOGS]
)
def test_a_flag_from_another_surface_is_refused_on_errors(
    cli: Cli, argv: list[str], flag: str
) -> None:
    code, _out, err = cli.run(
        ["errors", *argv], dict(DRY_RUN_ENV) | {"VERCEL_TOKEN": "t"}
    )
    assert code == 2, err
    assert flag in err
    # Naming the surface the preset does query is what stops the reader trying
    # the same flag on the other two logs presets next.
    assert "request logs" in err


def test_the_odata_rejection_names_what_to_use_instead(cli: Cli) -> None:
    code, _out, err = cli.run(
        ["errors", "--filter", "route eq '/x'"],
        dict(DRY_RUN_ENV) | {"VERCEL_TOKEN": "t"},
    )
    assert code == 2
    assert "--search" in err and "--status-code" in err
    # Every filter this surface has, rather than a hand-copied subset of them:
    # these three were missing while the list was prose.
    assert "--environment" in err and "--deployment" in err and "--request-id" in err


def test_an_appending_flag_is_reported_as_the_user_typed_it(cli: Cli) -> None:
    # --flag appends, so its value is a list, and printing the list itself would
    # quote Python syntax at a user who typed none of it.
    code, _out, err = cli.run(
        ["errors", "--flag", "beta=true"], dict(DRY_RUN_ENV) | {"VERCEL_TOKEN": "t"}
    )
    assert code == 2
    assert "beta=true" in err
    assert "['beta=true']" not in err


def test_csv_is_refused_on_the_multi_table_summary(cli: Cli) -> None:
    code, _out, err = cli.run(
        ["error-summary", "--csv"], dict(DRY_RUN_ENV) | {"VERCEL_TOKEN": "t"}
    )
    assert code == 2
    assert "--csv" in err and "errors" in err


BAD_LOGS_VALUES: list[list[str]] = [
    ["errors", "--level", "erro"],
    ["errors", "--source", "lambda"],
    ["errors", "--status-code", ">=500"],
]


@pytest.mark.parametrize(
    "argv", BAD_LOGS_VALUES, ids=[argv[1] for argv in BAD_LOGS_VALUES]
)
def test_a_bad_logs_value_is_refused_before_any_request(
    cli: Cli, argv: list[str]
) -> None:
    # session=None makes the fixture fail the test if a request is attempted, so
    # this also proves the check happens before the network.
    code, _out, err = cli.run(argv, dict(BASE_ENV))
    assert code == 2 and err.startswith("error:")


def test_an_out_of_range_limit_is_refused_before_any_request(cli: Cli) -> None:
    # session=None again, so this also pins the refusal ahead of the network.
    code, _out, err = cli.run(["errors", "--limit", "500"], dict(BASE_ENV))
    assert code == 2
    assert "--limit 500" in err
    # The ceiling quoted is this surface's own: 200 rows, not the 100 groups the
    # two analytics APIs bound. A logs limit counts requests, not groups.
    assert "200" in err and "rows" in err


@pytest.mark.parametrize(
    ("flag", "parameter"),
    [
        (["--path", "/api/me"], "requestPath"),
        (["--route", "/api/[id]"], "route"),
        (["--environment", "production"], "environment"),
    ],
    ids=["--path", "--route", "--environment"],
)
def test_a_shorthand_this_surface_has_narrows_every_call(
    cli: Cli, flag: list[str], parameter: str
) -> None:
    # These three are the only Web Analytics shorthands the request logs API has
    # a parameter for. The errors preset queries twice, so a narrowing that
    # reached only the first call would quietly report the other kind of error
    # unfiltered.
    code, out, err = cli.run(["errors", *flag, "--dry-run"], dict(DRY_RUN_ENV))
    assert code == 0, err
    assert len(dry_run_calls(out)) == 2
    for call in (0, 1):
        assert dry_run_values(out, parameter, call=call) == [flag[1]]


# ---------------------------------------------------------------------------
# The window default belongs to the surface
# ---------------------------------------------------------------------------

HOUR_MS = 3_600_000

#: A dry run resolves its window from the clock, so the two timestamps are
#: only approximately the requested distance apart.
TOLERANCE_MS = 5_000


def _window_ms(out: str, call: int = 0) -> int:
    """How long a window one request-logs call asked for, in milliseconds."""
    start = int(dry_run_values(out, "startDate", call=call)[0])
    end = int(dry_run_values(out, "endDate", call=call)[0])
    return end - start


def test_a_logs_run_defaults_to_the_last_hour(cli: Cli) -> None:
    # Runtime logs are retained for an hour on Hobby, so the global 7 day
    # default would mostly return nothing and read as "nothing is broken".
    code, out, err = cli.run(["logs", "--dry-run"], dict(DRY_RUN_ENV))
    assert code == 0, err
    assert abs(_window_ms(out) - HOUR_MS) <= TOLERANCE_MS


def test_the_error_summary_preset_defaults_to_six_hours(cli: Cli) -> None:
    # It tallies rather than lists, so it is worth a wider window than errors.
    code, out, err = cli.run(["error-summary", "--dry-run"], dict(DRY_RUN_ENV))
    assert code == 0, err
    assert abs(_window_ms(out) - 6 * HOUR_MS) <= TOLERANCE_MS


def test_an_explicit_since_beats_the_preset_default(cli: Cli) -> None:
    code, out, err = cli.run(["logs", "--since", "30m", "--dry-run"], dict(DRY_RUN_ENV))
    assert code == 0, err
    assert abs(_window_ms(out) - HOUR_MS // 2) <= TOLERANCE_MS


def test_an_empty_since_is_refused_rather_than_read_as_the_preset_default(
    cli: Cli,
) -> None:
    # A preset default answers "nobody asked for a window". An empty --since is
    # somebody asking for nothing, and substituting the default there would
    # report an hour of logs as though it had been chosen.
    code, _out, err = cli.run(["logs", "--since", ""], dict(BASE_ENV))
    assert code == 2
    assert "empty time value" in err


def test_a_traffic_preset_still_defaults_to_seven_days(cli: Cli) -> None:
    # Only a logs preset owns a window default. Moving the default off the
    # parser must leave every other preset asking for exactly what it did.
    code, out, err = cli.run(["top-pages", "--dry-run"], dict(DRY_RUN_ENV))
    assert code == 0, err
    # This surface sends ISO-8601 rather than Unix milliseconds.
    since = datetime.strptime(dry_run_values(out, "since")[0], "%Y-%m-%dT%H:%M:%SZ")
    until = datetime.strptime(dry_run_values(out, "until")[0], "%Y-%m-%dT%H:%M:%SZ")
    assert until - since == timedelta(days=7)


# ---------------------------------------------------------------------------
# Flags become query parameters, and an errors run queries twice
# ---------------------------------------------------------------------------


def test_the_errors_preset_dry_runs_both_calls(cli: Cli) -> None:
    code, out, err = cli.run(["errors", "--dry-run"], dict(DRY_RUN_ENV))
    assert code == 0, err
    calls = dry_run_calls(out)
    assert [endpoint for endpoint, _params in calls] == ["request-logs", "request-logs"]
    sent = [dict(params) for _endpoint, params in calls]
    # statusCode matches responses and level matches application log lines, so
    # neither call alone answers "what broke": a 5xx that printed nothing is
    # invisible to the second, and a 200 that logged a stack trace to the first.
    assert sent[0]["statusCode"] == "5xx"
    assert "level" not in sent[0]
    assert sent[1]["level"] == "error,fatal"
    assert "statusCode" not in sent[1]


def test_an_explicit_status_code_makes_errors_one_call(cli: Cli) -> None:
    code, out, err = cli.run(
        ["errors", "--status-code", "500", "--dry-run"], dict(DRY_RUN_ENV)
    )
    assert code == 0, err
    assert len(dry_run_calls(out)) == 1
    assert dry_run_values(out, "statusCode") == ["500"]


def test_an_explicit_level_makes_errors_one_call_in_the_api_spelling(cli: Cli) -> None:
    code, out, err = cli.run(
        ["errors", "--level", "ERROR,Warning", "--dry-run"], dict(DRY_RUN_ENV)
    )
    assert code == 0, err
    assert len(dry_run_calls(out)) == 1
    # Lower cased on the way out, because the API matches the spelling it
    # publishes and answers anything else with 200 and zero rows.
    assert dry_run_values(out, "level") == ["error,warning"]


def test_the_shorthand_filters_compile_to_query_parameters(cli: Cli) -> None:
    code, out, err = cli.run(
        [
            "logs",
            "--path",
            "/api/me",
            "--route",
            "/api/[id]",
            "--environment",
            "preview",
            "--method",
            "post",
            "--dry-run",
        ],
        dict(DRY_RUN_ENV),
    )
    assert code == 0, err
    sent = dict(dry_run_calls(out)[0][1])
    assert sent["requestPath"] == "/api/me"
    assert sent["route"] == "/api/[id]"
    assert sent["environment"] == "preview"
    # The API matches the method it logs, which is upper case.
    assert sent["requestMethod"] == "POST"
    # This surface takes no OData, so nothing compiles to a filter expression.
    assert "filter" not in sent


#: The filters this surface has and the two analytics surfaces do not, with the
#: parameter each one has to arrive as. Spelled out by hand rather than read from
#: the package, so a rename on either side of the mapping fails a test instead of
#: being mirrored by it.
LOGS_ONLY_MAPPINGS: list[tuple[list[str], str]] = [
    (["--branch", "release/2026-08"], "branch"),
    (["--deployment", "dpl_8fQLGTTwTZXixzmKhKm9DaXeadTJ"], "deploymentId"),
    (["--request-id", "zgzc9-1786964768933-ce3a0a3fb303"], "requestId"),
    (["--search", "Cannot read properties"], "search"),
]


@pytest.mark.parametrize(
    ("flag", "parameter"),
    LOGS_ONLY_MAPPINGS,
    ids=[flag[0] for flag, _parameter in LOGS_ONLY_MAPPINGS],
)
def test_a_logs_only_filter_arrives_under_its_own_wire_name(
    cli: Cli, flag: list[str], parameter: str
) -> None:
    # Four of the eleven filters this surface takes are spelled differently on
    # the wire than on the command line, and a filter that never arrives narrows
    # nothing while still looking like it did.
    code, out, err = cli.run(["logs", *flag, "--dry-run"], dict(DRY_RUN_ENV))
    assert code == 0, err
    assert dry_run_values(out, parameter) == [flag[1]]


def test_preview_environment_is_accepted_on_a_logs_preset(cli: Cli) -> None:
    # A Web Analytics count query refuses --environment preview and tells the
    # reader to add --group-by day instead. A logs preset has no grouping either,
    # but it refuses --group-by outright, so that advice cannot be followed and
    # the rule belongs to the surface that can offer it.
    code, out, err = cli.run(
        ["logs", "--environment", "preview", "--dry-run"], dict(DRY_RUN_ENV)
    )
    assert code == 0, err
    assert dry_run_values(out, "environment") == ["preview"]


def test_a_logs_run_needs_an_account_id_and_says_so(cli: Cli) -> None:
    # A team slug names a team but is not an account id, and ownerId wants an id.
    # Falling through to the personal account would answer for the wrong account
    # rather than failing, which is the worst outcome available.
    code, _out, err = cli.run(
        ["errors", "--team-slug", "acme"],
        {"VERCEL_TOKEN": "t", "VERCEL_PROJECT_ID": "p"},
    )
    assert code == 2
    assert "--team-slug" in err and "--owner-id" in err
    # Naming the surface that needs the id is what stops the reader concluding
    # a slug never works.
    assert "request logs" in err
