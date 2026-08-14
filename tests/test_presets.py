"""Tests for vercel_insights/presets.py, against literals from the contract.

The expectations below are transcribed by hand from the preset table in
docs/cli-contract.md. They are deliberately not read back from ``PRESETS``, so
a preset that quietly changes its dataset, grouping or limit fails here.
"""

from __future__ import annotations

import pytest
from conftest import Cli
from helpers import DRY_RUN_ENV, dry_run_calls, dry_run_values

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
    for (endpoint, params), (want_endpoint, want_by, want_limit) in zip(
        calls, expected
    ):
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

    # Transcribed from docs/cli-contract.md, not from PRESETS.
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
