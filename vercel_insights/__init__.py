"""Read-only command line client for Vercel's analytics query APIs.

This package answers the everyday questions about a Vercel project: how many
page views and visitors it had, which pages and referrers drove them, where the
visitors came from, and how custom events break down.

Read-only guarantee
-------------------
Every request this package can issue comes from a fixed operation allowlist in
:mod:`vercel_insights.http`. The dispatcher takes an operation key, never a
method or a host, so no user input can select, extend or override an entry. The
access token is only ever placed in the ``Authorization`` header, never in a
URL, a query parameter, a log line, an exception, or any rendered output.

This module holds only what every other module needs: the version, the API
root, and the exception types. It deliberately imports no submodule, so the
dependency graph inside the package stays acyclic.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

VERSION = "0.2.0"

#: The REST API root. Every allowlisted operation is built from this prefix.
BASE_URL = "https://api.vercel.com"

DOCS_TOKEN_URL = "https://vercel.com/docs/rest-api#creating-an-access-token"

#: Rows collapsed by the API once ``limit`` is exceeded arrive under this label.
OTHERS_LABEL = "Others"

__all__ = [
    "BASE_URL",
    "DOCS_TOKEN_URL",
    "OTHERS_LABEL",
    "VERSION",
    "ApiError",
    "ConfigError",
    "RateLimitError",
]


class ConfigError(Exception):
    """A configuration or usage problem detected before any network call.

    Every ``ConfigError`` message names the offending value and the fix, and is
    reported to the user as a single line with exit code 2.
    """


class ApiError(Exception):
    """The API returned an error, or the network failed after every retry.

    ``message`` holds Vercel's ``error.message`` verbatim whenever the response
    carried one. The rendered string prefixes it with the HTTP status and the
    API error code, and notes the attempt count when retries were used up.
    """

    def __init__(
        self,
        status: int | None,
        code: str | None,
        message: str,
        *,
        attempts: int = 1,
    ) -> None:
        self.status = status
        self.code = code
        self.message = message
        self.attempts = attempts
        super().__init__(self._render())

    def _render(self) -> str:
        prefix = f"HTTP {self.status}" if self.status is not None else "Network error"
        if self.code:
            prefix = f"{prefix} ({self.code})"
        text = f"{prefix}: {self.message}"
        if self.attempts > 1:
            text = f"{text} [gave up after {self.attempts} attempts]"
        return text

    def __str__(self) -> str:
        return self._render()


class RateLimitError(ApiError):
    """A ``rate_limited`` response. ``limit`` holds Vercel's limit object."""

    def __init__(
        self,
        status: int | None,
        code: str | None,
        message: str,
        *,
        attempts: int = 1,
        limit: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(status, code, message, attempts=attempts)
        self.limit: Mapping[str, Any] = dict(limit or {})
