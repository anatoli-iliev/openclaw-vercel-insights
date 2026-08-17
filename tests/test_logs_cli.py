"""Tests for the request logs paths through cli.py.

Mirrors tests/test_speed_cli.py: one module per surface through the CLI, so a
change to one surface cannot quietly rewrite another's behaviour.
"""

from __future__ import annotations

import pytest
from conftest import Cli
from helpers import BASE_ENV, DRY_RUN_ENV

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


@pytest.mark.xfail(
    strict=True,
    reason=(
        "the level, source and status vocabularies are checked where a logs run "
        "turns flags into query parameters, which is the next task: this task "
        "only makes the flags exist and rejects them on the wrong surface"
    ),
)
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
    # Which ceiling the message quotes (rows on this surface, groups on the
    # other two) is settled where a logs run resolves its limit, in the next
    # task; that it is refused at all, naming the value, is settled here.
    code, _out, err = cli.run(["errors", "--limit", "500"], dict(BASE_ENV))
    assert code == 2
    assert "--limit 500" in err


@pytest.mark.parametrize(
    "flag",
    [["--path", "/api/me"], ["--route", "/api/[id]"], ["--environment", "production"]],
    ids=lambda item: item[0],
)
def test_the_shorthands_this_surface_has_are_not_refused_on_a_logs_preset(
    cli: Cli, flag: list[str]
) -> None:
    # These three are dimensions the request logs API does have, so the guard
    # lets them through. What they compile to on the wire is the next task's
    # business; here it only matters that they are not rejected.
    code, _out, err = cli.run(["errors", *flag, "--dry-run"], dict(DRY_RUN_ENV))
    assert code == 0, err
    assert flag[0] not in err
