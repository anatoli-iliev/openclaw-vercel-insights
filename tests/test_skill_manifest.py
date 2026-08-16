"""SKILL.md is the contract an agent reads, so it has to stay true.

Two claims in it are the kind people rely on and that drift silently: the list
of endpoints this skill may call, and the environment variables it reads.
ClawHub's own analysis checks the second against what the code does. Both have
gone stale during development, once by a blanket find-and-replace that updated a
sentence and left the table beneath it wrong, which is exactly the failure a test
catches and a careful reader does not.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from vercel_insights.http import OPERATIONS

SKILL = Path(__file__).resolve().parent.parent / "SKILL.md"
TEXT = SKILL.read_text()
FRONTMATTER = TEXT.split("---")[1] if TEXT.startswith("---") else ""

#: Every environment variable the package actually reads.
CODE_ENV = {
    "VERCEL_TOKEN",
    "VERCEL_PROJECT_ID",
    "VERCEL_TEAM_ID",
    "VERCEL_TEAM_SLUG",
    "VERCEL_OWNER_ID",
    "VERCEL_ORG_ID",
    "NO_COLOR",
}


def test_the_frontmatter_declares_every_environment_variable_the_code_reads() -> None:
    # ClawHub flags a mismatch between declared metadata and real behaviour, so
    # an undeclared variable is a publishing problem, not only a docs one.
    for name in sorted(CODE_ENV):
        assert name in FRONTMATTER, f"{name} is read by the code but not declared"


def test_the_code_reads_every_environment_variable_the_frontmatter_declares() -> None:
    # The other direction: declaring one the code ignores is a promise it cannot
    # keep, and it would send a user to set something with no effect.
    declared = set(re.findall(r"\b(VERCEL_[A-Z_]+|NO_COLOR)\b", FRONTMATTER))
    assert declared <= CODE_ENV, f"declared but unread: {sorted(declared - CODE_ENV)}"


def test_the_documented_endpoint_count_matches_the_allowlist() -> None:
    words = {3: "three", 4: "four", 5: "five", 6: "six", 7: "seven"}
    expected = words[len(OPERATIONS)]
    assert f"exactly {expected} entries" in TEXT
    assert f"{expected}-endpoint allowlist" in TEXT


@pytest.mark.parametrize("operation", sorted(OPERATIONS))
def test_every_allowlisted_operation_is_documented(operation: str) -> None:
    method, url = OPERATIONS[operation]
    path = url.replace("https://api.vercel.com", "")
    assert f"`{operation}`" in TEXT, f"{operation} is callable but undocumented"
    assert path in TEXT, f"{path} is callable but undocumented"
    row = next(
        (line for line in TEXT.splitlines() if f"`{operation}`" in line and "|" in line),
        None,
    )
    assert row is not None and method in row, f"{operation} documents the wrong method"


def test_no_endpoint_is_documented_that_the_code_cannot_call() -> None:
    # A documented endpoint that does not exist would overstate the surface,
    # which is as misleading as understating it.
    documented = set(re.findall(r"^\| `([a-z_]+)` \| (?:GET|POST) \|", TEXT, re.M))
    assert documented <= set(OPERATIONS), (
        f"documented but not callable: {sorted(documented - set(OPERATIONS))}"
    )


def test_the_declared_version_matches_the_package() -> None:
    from vercel_insights import VERSION

    assert re.search(rf"^version:\s*{re.escape(VERSION)}\s*$", FRONTMATTER, re.M)
