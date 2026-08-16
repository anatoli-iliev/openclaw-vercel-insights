"""The setup guide has to keep describing this tool, not a past version of it.

Every row of its troubleshooting table quotes a message a user might see. A
quoted message that no longer matches what the code emits is worse than no
table, because it teaches someone to search for a string that will never appear.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GUIDE = (ROOT / "docs" / "openclaw-setup.md").read_text()
CLI = (ROOT / "vercel_insights" / "cli.py").read_text()
HTTP = (ROOT / "vercel_insights" / "http.py").read_text()
MAIN = (ROOT / "vercel_insights" / "__main__.py").read_text()
SOURCE = CLI + HTTP + MAIN


def test_the_guide_exists_and_is_linked_from_both_entry_points() -> None:
    assert "docs/openclaw-setup.md" in (ROOT / "README.md").read_text()
    assert "openclaw-setup.md" in (ROOT / "SKILL.md").read_text()


@pytest.mark.parametrize(
    "phrase",
    [
        # Each of these is quoted in the troubleshooting table and must still be
        # something the code can actually produce.
        "is not importable by this interpreter",
        "scoped to a single project",
        "VERCEL_TEAM_ID",
    ],
)
def test_quoted_messages_still_exist_in_the_code(phrase: str) -> None:
    assert phrase in GUIDE, f"the guide no longer mentions {phrase!r}"
    assert phrase in SOURCE, f"the code no longer emits {phrase!r}"


def test_the_documented_exit_codes_match_the_code() -> None:
    from vercel_insights.budgets import BUDGET_EXCEEDED

    # The number alone is not enough: a row that says "3" and describes the
    # wrong thing is worse than a missing row.
    for code, meaning in ((0, "success"), (1, "API"), (2, "configured"), (3, "budget")):
        row = next((ln for ln in GUIDE.splitlines() if ln.startswith(f"| {code} |")), None)
        assert row is not None, f"exit code {code} is undocumented"
        assert meaning.lower() in row.lower(), f"exit code {code} describes the wrong thing"
    assert BUDGET_EXCEEDED == 3, "the documented budget exit code drifted"


def test_the_endpoint_table_matches_the_allowlist() -> None:
    from vercel_insights.http import OPERATIONS

    assert "Five endpoints" in GUIDE or f"{len(OPERATIONS)} endpoints" in GUIDE.lower()
    for _operation, (method, url) in OPERATIONS.items():
        path = url.replace("https://api.vercel.com", "")
        assert path in GUIDE, f"{path} is callable but missing from the guide"
        row = next((ln for ln in GUIDE.splitlines() if path in ln and "|" in ln), None)
        assert row is not None and method in row, f"{path} documents the wrong method"


def test_the_guide_does_not_recommend_the_route_that_does_not_prompt() -> None:
    # `openclaw configure --section skills` reports status and exits. It may
    # only appear here as the warning that it is not the way in.
    for line in GUIDE.splitlines():
        if "openclaw configure --section skills" in line:
            assert "not" in line.lower(), (
                "configure is mentioned without saying it does not prompt"
            )
