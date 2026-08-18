# Request Logs Surface Implementation Plan

> **Completed, and kept as history.** This plan was executed and the surface
> shipped in 1.1.0. Nothing below is a pending instruction or a step to carry
> out: it is the record of how the work was sequenced and what each step was
> for. For API facts and current behaviour, read `docs/api-notes.md` and
> `docs/cli-contract.md`, which are the maintained records.

**Goal:** Add a third query surface to this skill so an OpenClaw user can ask
"give me the errors my project has had for the last 30 minutes" and get a
truthful, readable answer.

**Architecture:** One new surface module, `vercel_insights/logs.py`, owning
request building, vocabulary validation, response normalization, paging and
local aggregation for `GET https://vercel.com/api/logs/request-logs`. Its data
containers and renderers live in `render.py` beside `Row`/`Result`, because
`render.py` must never import a surface module. `cli.py` gains the flags, a
three-way cross-surface guard, a paging loop and an emitter. The operation
allowlist grows by exactly one entry.

**Tech Stack:** Python 3.10+, `requests` (the only runtime dependency), pytest,
ruff, mypy --strict. No new dependency is added by this plan.

**Spec:** `docs/superpowers/specs/2026-08-17-request-logs-design.md`. Read it
first: section 2 is verified API ground truth and every design decision below
argues from it.

## Global Constraints

- **No em dashes.** Not in prose, code, comments, docstrings, or strings. Use a
  colon, semicolon, parentheses or a full stop.
- **`mypy --strict` passes with no ignores.** New code holds that line.
- **No new runtime dependency.** `requests` plus the standard library only.
- **No test touches the network.** Use `tests/helpers.py::FakeSession`. A test
  that wants a real HTTP call means the change is wrong.
- **Python floor is 3.10**, so `datetime.fromisoformat` cannot parse a trailing
  `Z`. Use the existing pattern: `value[:-1] + "+00:00"` when the string ends in
  `Z` or `z`, then `fromisoformat`.
- **Docstrings on public functions:** what it does, its arguments, what it
  returns, what it raises.
- **The token appears only in the `Authorization` header.** Never in a URL, a
  query parameter, a body, an error message or any output.
- **Every response-derived string is sanitized once**, at the normalization
  boundary in `logs.py`, via `sanitize_label` (single line values) or
  `sanitize_message` (log message bodies). Nothing downstream re-sanitizes and
  nothing downstream may skip it.
- **Verify each task with:** `.venv/bin/pytest`, `.venv/bin/ruff check .`,
  `.venv/bin/mypy --strict vercel_insights tests`.
- Commit at the end of every task. Small commits, present-tense subject, no
  trailing period, no em dash.

---

## File Structure

| File | Responsibility | Change |
| --- | --- | --- |
| `vercel_insights/__init__.py` | version, exceptions, sanitizers, base URLs | add `LOGS_BASE_URL`, bump `VERSION` to `1.1.0` |
| `vercel_insights/http.py` | operation allowlist, request prep, retries | add the `request_logs` entry, widen the host prose |
| `vercel_insights/timerange.py` | time parsing, surfaces, granularity | add the `LOGS` surface, its label, `to_unix_ms` |
| `vercel_insights/logs.py` | **new**: everything specific to the request-logs API | create |
| `vercel_insights/render.py` | generic containers and renderers | add the log containers and two renderers, plus logs JSON and CSV |
| `vercel_insights/presets.py` | the preset table | add `logs`, `errors`, `error-summary`, `default_since`, `is_logs` |
| `vercel_insights/cli.py` | flags, settings, `main()` | add logs flags, three-way surface guard, paging loop, emitter |
| `tests/test_logs.py` | **new**: the surface module | create |
| `tests/test_logs_cli.py` | **new**: the CLI paths through the surface | create |
| `tests/test_logs_render.py` | **new**: the renderers | create |
| `tests/helpers.py` | shared fakes and payloads | add the logs payload fixtures and `logs_request` |
| `tests/test_security.py` | the invariants | six operations, two documented hosts |
| `tests/test_untrusted_response.py` | hostile response text | log message and path cases |
| `tests/test_skill_manifest.py` | SKILL.md stays true | whatever the count and description change requires |
| `SKILL.md`, `README.md`, `docs/*.md`, `examples/*`, `CHANGELOG.md`, `CONTRIBUTING.md`, `pyproject.toml` | documentation and version | update |

---

### Task 1: The allowlist grows by one entry, on a second host

**Files:**
- Modify: `vercel_insights/__init__.py` (add `LOGS_BASE_URL` next to `BASE_URL`)
- Modify: `vercel_insights/http.py:55-70` (the `OPERATIONS` table) and its module
  docstring
- Test: `tests/test_security.py:62-105`

**Interfaces:**
- Consumes: nothing.
- Produces: `LOGS_BASE_URL: str = "https://vercel.com"`, and the allowlist entry
  `OPERATIONS["request_logs"] == ("GET", "https://vercel.com/api/logs/request-logs")`.

- **Step 1: Write the failing tests**

In `tests/test_security.py`, add `request_logs` to `DOCUMENTED_OPERATIONS`:

```python
    # Read-only. Runtime request logs, and the only entry not on api.vercel.com:
    # Vercel serves this one from the dashboard host, and it is the endpoint the
    # official `vercel logs` command calls. See docs/api-notes.md.
    "request_logs": ("GET", "https://vercel.com/api/logs/request-logs"),
```

Change the count assertion and replace the single-host test:

```python
def test_operations_holds_exactly_the_six_documented_entries() -> None:
    assert set(OPERATIONS) == set(DOCUMENTED_OPERATIONS)
    assert len(OPERATIONS) == 6


#: The only hosts this client may address. Written out by hand rather than read
#: back from OPERATIONS: a test that derives the answer from the table it is
#: checking cannot notice the table naming a host nobody approved.
DOCUMENTED_HOSTS: frozenset[str] = frozenset(
    {"https://api.vercel.com/", "https://vercel.com/api/"}
)


@pytest.mark.parametrize("operation", sorted(DOCUMENTED_OPERATIONS))
def test_every_allowlisted_url_is_on_a_documented_host(operation: str) -> None:
    _method, url = OPERATIONS[operation]
    assert any(url.startswith(host) for host in DOCUMENTED_HOSTS), url
```

Rename the old `test_every_allowlisted_url_is_on_the_vercel_api_host` away rather
than leaving both. Add one test proving the new entry cannot be re-pointed:

```python
@pytest.mark.parametrize(
    "url",
    [
        "https://vercel.com/api/logs/request-logs/extra",
        "https://vercel.com/api/logs",
        "http://vercel.com/api/logs/request-logs",
        "https://vercel.com.evil.example/api/logs/request-logs",
        "https://api.vercel.com/api/logs/request-logs",
    ],
)
def test_request_logs_cannot_address_anything_else(url: str) -> None:
    with pytest.raises(ConfigError):
        PreparedRequest(
            operation="request_logs", url=url, params=[], headers={}
        )
```

- **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_security.py -x -q`
Expected: FAIL, `KeyError: 'request_logs'` or an assertion that the table has 5
entries.

- **Step 3: Add the constant and the entry**

In `vercel_insights/__init__.py`, after `BASE_URL`:

```python
#: The dashboard host. Exactly one operation lives here rather than on
#: :data:`BASE_URL`: Vercel serves historical request logs from
#: ``vercel.com/api/logs/request-logs``, which is what the official CLI calls
#: and the only endpoint that answers a "what broke in the last hour" question.
#: The documented alternative on api.vercel.com is an endless stream, and the
#: metrics route needs Observability Plus. See docs/api-notes.md.
LOGS_BASE_URL = "https://vercel.com"
```

Add it to `__all__`. In `vercel_insights/http.py`, import `LOGS_BASE_URL` and add
the entry at the end of `OPERATIONS`:

```python
    # Read-only. Runtime request logs. The one entry that is not on
    # api.vercel.com and not in Vercel's published OpenAPI document: its ground
    # truth is the official CLI plus the live probes recorded in
    # docs/api-notes.md, so it can change without notice. Nothing is created or
    # mutated; the whole query travels in the query string.
    "request_logs": ("GET", LOGS_BASE_URL + "/api/logs/request-logs"),
```

- **Step 4: Update the prose that counts entries**

The `http.py` module docstring says "One of the three operations is a POST" and
speaks of "the three above". Correct both to six, and add one sentence: the
allowlist now spans two hosts, `api.vercel.com` for five operations and
`vercel.com` for request logs, and a redirect is still refused so the allowlist
binds every hop. Same for the `__init__.py` docstring if it counts.

- **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_security.py -q && .venv/bin/ruff check . && .venv/bin/mypy --strict vercel_insights tests`
Expected: PASS. `tests/test_skill_manifest.py` will now fail on the endpoint
count and on the undocumented operation; that is Task 14 and is expected to stay
red until then. Note it in the commit message.

- **Step 6: Commit**

```bash
git add vercel_insights/__init__.py vercel_insights/http.py tests/test_security.py
git commit -F - <<'MSG'
Allow one read-only logs operation, on a second host

Six entries now, five on api.vercel.com and one on vercel.com. The host test
becomes an explicit two-host set so a third host is still a failure.
test_skill_manifest stays red until SKILL.md documents the entry.
MSG
```

---

### Task 2: The logs surface exists in the time layer

**Files:**
- Modify: `vercel_insights/timerange.py:21-30` (surfaces and labels), and add
  `to_unix_ms` beside `to_api_timestamp`
- Test: `tests/test_timerange.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `LOGS: str = "logs"`, `SURFACE_LABELS[LOGS] == "request logs"`,
  `to_unix_ms(dt: datetime) -> str`.

- **Step 1: Write the failing test**

Append to `tests/test_timerange.py`:

```python
def test_to_unix_ms_renders_milliseconds_as_a_string() -> None:
    # The request-logs API takes startDate and endDate in Unix milliseconds,
    # and every query parameter this client sends is a string.
    assert tr.to_unix_ms(tr.datetime(1970, 1, 1, tzinfo=tr.timezone.utc)) == "0"
    assert tr.to_unix_ms(utc(2026, 8, 17, 11, 6, 8)) == "1786964768000"


def test_to_unix_ms_assumes_utc_for_a_naive_datetime() -> None:
    naive = tr.datetime(2026, 8, 17, 11, 6, 8)
    assert tr.to_unix_ms(naive) == tr.to_unix_ms(utc(2026, 8, 17, 11, 6, 8))


def test_the_logs_surface_has_a_name_and_a_label() -> None:
    assert tr.LOGS in tr.SURFACES
    assert tr.SURFACE_LABELS[tr.LOGS] == "request logs"
```

Import `utc` from `helpers` in that module if it is not already imported, and
confirm `1786964768000` by computing it once rather than trusting this plan:
`python3 -c "import datetime;print(int(datetime.datetime(2026,8,17,11,6,8,tzinfo=datetime.timezone.utc).timestamp()*1000))"`.

- **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_timerange.py -x -q`
Expected: FAIL with `AttributeError: module 'vercel_insights.timerange' has no
attribute 'to_unix_ms'`.

- **Step 3: Implement**

```python
#: The three query surfaces, spelled as the user facing messages spell them.
WEB_ANALYTICS = "web-analytics"
SPEED_INSIGHTS = "speed-insights"
LOGS = "logs"
SURFACES: tuple[str, ...] = (WEB_ANALYTICS, SPEED_INSIGHTS, LOGS)

SURFACE_LABELS: dict[str, str] = {
    WEB_ANALYTICS: "Web Analytics",
    SPEED_INSIGHTS: "Speed Insights",
    LOGS: "request logs",
}
```

`GRANULARITY_BY_SURFACE` is deliberately **not** given a `LOGS` entry: that
surface has no time buckets at all, `--granularity` is rejected before any
request is built (Task 9), and inventing an entry would imply a translation that
does not exist. Add that sentence as a comment above the dict.

```python
def to_unix_ms(dt: datetime) -> str:
    """Render an aware datetime as the Unix millisecond string one API wants.

    The request-logs endpoint takes ``startDate`` and ``endDate`` in
    milliseconds, unlike the two ISO-8601 surfaces, and every query parameter
    this client sends is a string.

    Args:
        dt: The instant to render. A naive value is read as UTC.

    Returns:
        Whole milliseconds since the Unix epoch, as a decimal string.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return str(int(dt.astimezone(timezone.utc).timestamp() * 1000))
```

- **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_timerange.py -q && .venv/bin/mypy --strict vercel_insights tests`
Expected: PASS.

- **Step 5: Commit**

```bash
git add vercel_insights/timerange.py tests/test_timerange.py
git commit -m "Name the logs surface and render Unix millisecond timestamps"
```

---

### Task 3: The logs vocabularies, validated locally

**Files:**
- Create: `vercel_insights/logs.py`
- Create: `tests/test_logs.py`

**Interfaces:**
- Consumes: `ConfigError` from `vercel_insights`.
- Produces, in `vercel_insights.render`: `LOG_LEVEL_SEVERITY: dict[str, int]` and
  `ERROR_LEVELS: tuple[str, ...] = ("error", "fatal")`. Both live there rather
  than in `logs.py` because `LogEntry.is_error` (Task 5) needs them and
  `render.py` must never import a surface module. `logs.py` imports them, so
  `logs.ERROR_LEVELS` still resolves and there is one source of truth.
- Produces, all from `vercel_insights.logs`:
  `OPERATION: str = "request_logs"`,
  `LEVELS: tuple[str, ...]`, `SOURCES: tuple[str, ...]`,
  `PAGE_SIZE: int = 50`, `MAX_PAGES: int = 4`,
  `MIN_LIMIT: int = 1`, `MAX_LIMIT: int = 200`, `DEFAULT_LIMIT: int = 50`,
  `validate_levels(value: str) -> str`,
  `validate_sources(value: str) -> str`,
  `validate_status_code(value: str) -> str`,
  `validate_limit(limit: int) -> int`.

Every validator takes what the user typed and returns the exact string to put on
the wire, or raises `ConfigError`.

- **Step 1: Write the failing tests**

Create `tests/test_logs.py`:

```python
"""Tests for vercel_insights/logs.py: the request logs surface.

The API validates almost nothing: an unknown level or source comes back as 200
with zero rows, which would read as "your site is fine". So the vocabularies are
checked here, before a request exists, and these tests are what hold that line.
"""

from __future__ import annotations

import pytest

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
    with pytest.raises(ConfigError):
        vi_logs.validate_sources(value)


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
    from vercel_insights.render import LOG_LEVEL_SEVERITY

    assert set(vi_logs.LEVELS) == set(LOG_LEVEL_SEVERITY)
    assert set(vi_logs.ERROR_LEVELS) <= set(vi_logs.LEVELS)
    assert vi_logs.ERROR_LEVELS == ("error", "fatal")
```

- **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_logs.py -x -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'vercel_insights.logs'`.

- **Step 3: Create the module with the vocabularies**

Create `vercel_insights/logs.py`:

```python
"""Request logs request building and response normalization.

Everything specific to ``GET https://vercel.com/api/logs/request-logs`` lives
here: the level, source and status vocabularies, the parameter allowlist, the
shape of the rows it returns, its paging, and the local aggregation that turns
rows into a summary. The modules underneath (``http``, ``timerange``,
``render``) know none of it.

Two things make this surface unlike the other two, and both shape the code:

* **The API validates almost nothing.** An unknown ``level`` or ``source``
  answers ``200`` with zero rows, so a typo would read as "nothing is broken".
  Every vocabulary is therefore checked here, before a request exists.
* **``level`` matches application log lines, not responses.** A ``500`` that
  printed nothing carries no log line and no level, and a ``200`` whose handler
  logged a stack trace is not a ``5xx``. Neither filter alone answers "what
  broke", which is why the errors presets query both and merge.

See docs/api-notes.md for the live probes behind every claim here.
"""

from __future__ import annotations

import re

from . import ConfigError
from .render import ERROR_LEVELS  # re-exported: one vocabulary, one definition

#: The operation key this surface uses. A key into ``http.OPERATIONS``, never a
#: method and never a host.
OPERATION = "request_logs"

#: Log levels the API filters on, in the order the help text lists them.
LEVELS: tuple[str, ...] = ("error", "warning", "info", "fatal")

#: Sources the API filters on.
SOURCES: tuple[str, ...] = (
    "serverless",
    "edge-function",
    "edge-middleware",
    "static",
)

#: Rows per page. Fixed by the API: the ``limit`` parameter is accepted and
#: ignored, which is why a row limit is enforced in this client instead.
PAGE_SIZE = 50

#: How many pages one call will ever fetch. A page took up to 6 seconds in
#: testing, so four pages is already 24 seconds against a 30 second per request
#: timeout. Raising this trades an answer for a hang.
MAX_PAGES = 4

MIN_LIMIT = 1
MAX_LIMIT = PAGE_SIZE * MAX_PAGES
DEFAULT_LIMIT = PAGE_SIZE

#: One ``statusCode`` item: three characters where the first is a digit and the
#: rest are digits or ``x``, or the literal ``None``. The API's own message
#: names exactly this rule, and is quoted in the error below.
_STATUS_ITEM_RE = re.compile(r"^[1-9][0-9x]{2}$")


def _split(value: str) -> list[str]:
    """Split a comma separated flag value, dropping surrounding whitespace."""
    return [item.strip() for item in value.split(",") if item.strip()]


def validate_levels(value: str) -> str:
    """Validate a ``--level`` list and return it as the API spells it.

    Args:
        value: One or more comma separated level names, any case.

    Returns:
        The lower-cased comma separated list to send.

    Raises:
        ConfigError: When the list is empty or names a level the API does not
            know. The API answers 200 with zero rows for an unknown level, so
            an unchecked typo would report a healthy site.
    """
    items = [item.lower() for item in _split(value)]
    unknown = [item for item in items if item not in LEVELS]
    if not items or unknown:
        offending = f"{unknown[0]!r}" if unknown else "an empty list"
        raise ConfigError(
            f"--level {offending} is not a log level this API knows; it accepts "
            f"{', '.join(LEVELS)}, comma separated. This is checked here because "
            "the API answers an unknown level with zero rows rather than an "
            "error, which would read as 'nothing is broken'"
        )
    return ",".join(items)


def validate_sources(value: str) -> str:
    """Validate a ``--source`` list and return it as the API spells it.

    Args:
        value: One or more comma separated source names, any case.

    Returns:
        The lower-cased comma separated list to send.

    Raises:
        ConfigError: When the list is empty or names an unknown source. Same
            reasoning as :func:`validate_levels`: an unknown value is answered
            with zero rows.
    """
    items = [item.lower() for item in _split(value)]
    unknown = [item for item in items if item not in SOURCES]
    if not items or unknown:
        offending = f"{unknown[0]!r}" if unknown else "an empty list"
        raise ConfigError(
            f"--source {offending} is not a source this API knows; it accepts "
            f"{', '.join(SOURCES)}, comma separated. An unknown value comes back "
            "as zero rows rather than an error, so it is refused here"
        )
    return ",".join(items)


def validate_status_code(value: str) -> str:
    """Validate a ``--status-code`` expression against the API's own rule.

    Args:
        value: Comma separated status codes, classes such as ``4xx``, or
            ``None`` for requests with no status recorded.

    Returns:
        The expression to send, lower-cased for classes and with ``None``
        spelled the way the API spells it.

    Raises:
        ConfigError: When an item matches neither form. The message quotes the
            API's own validation text, since that is the authority.
    """
    items = _split(value)
    normalized: list[str] = []
    for item in items:
        if item.lower() == "none":
            normalized.append("None")
            continue
        lowered = item.lower()
        if _STATUS_ITEM_RE.match(lowered):
            normalized.append(lowered)
            continue
        raise ConfigError(
            f"--status-code {item!r} is not a status this API accepts. It says: "
            '"statusCode must contain only comma-separated integers, status code '
            'classes like 4xx or 5xx, or \\"None\\"". So --status-code 500, '
            "--status-code 5xx, --status-code 4xx,5xx and --status-code None all "
            "work; a comparison such as >=500 does not"
        )
    if not normalized:
        raise ConfigError(
            "--status-code was empty; pass a status such as 500, a class such as "
            "5xx, or None for requests with no status recorded"
        )
    return ",".join(normalized)


def validate_limit(limit: int) -> int:
    """Bound the number of log rows one run will report.

    Args:
        limit: The requested row count.

    Returns:
        The limit, unchanged, when it is in range.

    Raises:
        ConfigError: When it is outside :data:`MIN_LIMIT` to :data:`MAX_LIMIT`.
    """
    if MIN_LIMIT <= limit <= MAX_LIMIT:
        return limit
    raise ConfigError(
        f"--limit {limit} is out of range on a logs preset, which counts rows "
        f"rather than groups: pass {MIN_LIMIT} to {MAX_LIMIT}. The API pages "
        f"{PAGE_SIZE} rows at a time and ignores a limit of its own, so this "
        f"client stops after {MAX_PAGES} pages"
    )
```

- **Step 4: Add the severity table and the error levels to render.py**

In `vercel_insights/render.py`, near the top with the other module constants:

```python
#: Log levels ordered by severity, so the worst line on a request can be picked
#: without a surface module having to rank them. The names are validated in
#: logs.py; tests/test_logs.py asserts the two agree.
LOG_LEVEL_SEVERITY: dict[str, int] = {
    "info": 0,
    "warning": 1,
    "error": 2,
    "fatal": 3,
}

#: The levels that make a request an error rather than a note, in the order they
#: are sent as a filter. Defined here because LogEntry.is_error needs them and
#: this module must not import a surface module; logs.py imports them from here,
#: so there is one definition rather than two that can drift.
ERROR_LEVELS: tuple[str, ...] = ("error", "fatal")
```

- **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_logs.py -q && .venv/bin/ruff check . && .venv/bin/mypy --strict vercel_insights tests`
Expected: PASS.

- **Step 6: Commit**

```bash
git add vercel_insights/logs.py vercel_insights/render.py tests/test_logs.py
git commit -F - <<'MSG'
Validate the logs vocabularies before a request exists

The API answers an unknown level or source with 200 and zero rows, which reads
as a healthy site. Checking them locally is the difference between a typo being
an error and a typo being a wrong answer.
MSG
```

---

### Task 4: Build the request, with a parameter allowlist

**Files:**
- Modify: `vercel_insights/logs.py`
- Test: `tests/test_logs.py`, `tests/helpers.py`

**Interfaces:**
- Consumes: `PreparedRequest`, `default_headers`, `operation_url` from
  `vercel_insights.http`; `to_unix_ms` from `vercel_insights.timerange`;
  the constants from Task 3.
- Produces:
  `FILTER_PARAMS: tuple[str, ...]` (the accepted filter keys, in emission
  order), and
  ```python
  def build_request(
      *,
      project: str,
      owner_id: str,
      since: datetime,
      until: datetime,
      page: int = 0,
      filters: Mapping[str, str] | None = None,
      token: str | None = None,
  ) -> PreparedRequest
  ```
  plus `tests/helpers.py::logs_request(**overrides) -> PreparedRequest` and
  `LOGS_URL: str = "https://vercel.com/api/logs/request-logs"`.

- **Step 1: Write the failing tests**

Add to `tests/helpers.py`:

```python
#: The request-logs endpoint, written out by hand from docs/api-notes.md rather
#: than read back from OPERATIONS.
LOGS_URL = "https://vercel.com/api/logs/request-logs"


def logs_request(**overrides: Any) -> PreparedRequest:
    """A prepared request-logs request, for the HTTP and security tests."""
    kwargs: dict[str, Any] = {
        "project": PROJECT,
        "owner_id": OWNER,
        "since": utc(2026, 8, 17, 10, 6, 8),
        "until": utc(2026, 8, 17, 11, 6, 8),
        "token": TOKEN,
    }
    kwargs.update(overrides)
    return build_logs_request(**kwargs)
```

with `from vercel_insights.logs import build_request as build_logs_request` at
the top. Add to `tests/test_logs.py`:

```python
from datetime import datetime, timezone

from helpers import LOGS_URL, OWNER, PROJECT, TOKEN, logs_request, utc


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
```

Recompute both millisecond expectations rather than trusting this plan:
`python3 -c "import datetime as d;print([int(d.datetime(2026,8,17,h,6,8,tzinfo=d.timezone.utc).timestamp()*1000) for h in (10,11)])"`.

- **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_logs.py -x -q`
Expected: FAIL with `ImportError: cannot import name 'build_request'`.

- **Step 3: Implement**

Add to `vercel_insights/logs.py`:

```python
#: Every filter parameter this surface may send, in the order they are emitted.
#: This is a parameter allowlist as well as an ordering: a key outside it is a
#: ConfigError, so a caller cannot introduce a query parameter of its own.
FILTER_PARAMS: tuple[str, ...] = (
    "level",
    "statusCode",
    "source",
    "requestMethod",
    "requestPath",
    "route",
    "environment",
    "branch",
    "deploymentId",
    "requestId",
    "search",
)


def build_request(
    *,
    project: str,
    owner_id: str,
    since: datetime,
    until: datetime,
    page: int = 0,
    filters: Mapping[str, str] | None = None,
    token: str | None = None,
) -> PreparedRequest:
    """Build the request that fetches one page of request logs. Pure: no I/O.

    The URL comes from the ``request_logs`` entry of the operation allowlist, so
    neither the method nor the host is written down here. The token, when
    supplied, goes into the ``Authorization`` header and nowhere else.

    ``teamId`` is deliberately absent: this endpoint does not accept it, and
    ``ownerId`` is what scopes the call.

    Args:
        project: Project id or project name; both work on this endpoint.
        owner_id: Account that owns the project. Required by the API.
        since: Start of the window, aware.
        until: End of the window, aware.
        page: Zero based page index.
        filters: Wire-named filter values, keyed by :data:`FILTER_PARAMS`.
            Empty values are dropped rather than sent.
        token: Access token for the ``Authorization`` header.

    Returns:
        The :class:`PreparedRequest` describing exactly one allowlisted call.

    Raises:
        ConfigError: When ``filters`` carries a key outside
            :data:`FILTER_PARAMS`.
    """
    supplied = dict(filters or {})
    unknown = sorted(set(supplied) - set(FILTER_PARAMS))
    if unknown:
        raise ConfigError(
            f"{unknown[0]!r} is not a request logs filter; this surface sends "
            f"only {', '.join(FILTER_PARAMS)}"
        )

    params: list[tuple[str, str]] = [
        ("projectId", project),
        ("ownerId", owner_id),
        ("page", str(page)),
        ("startDate", to_unix_ms(since)),
        ("endDate", to_unix_ms(until)),
    ]
    for name in FILTER_PARAMS:
        value = supplied.get(name)
        if value:
            params.append((name, value))

    return PreparedRequest(
        operation=OPERATION,
        url=operation_url(OPERATION),
        params=params,
        headers=default_headers(token),
    )
```

Add the imports this needs: `from collections.abc import Mapping`,
`from datetime import datetime`,
`from .http import PreparedRequest, default_headers, operation_url`,
`from .timerange import to_unix_ms`.

- **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_logs.py -q && .venv/bin/mypy --strict vercel_insights tests`
Expected: PASS.

- **Step 5: Add the security test for the new request shape**

In `tests/test_security.py`, wherever the equivalent Web Analytics and Speed
Insights assertions live, add `logs_request()` to the parametrized list that
asserts no credential reaches a URL, a parameter or a `repr`, and that
`format_dry_run` redacts the header. Follow the existing test names; do not
invent a new pattern.

- **Step 6: Run the whole suite and commit**

```bash
.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/mypy --strict vercel_insights tests
git add vercel_insights/logs.py tests/test_logs.py tests/helpers.py tests/test_security.py
git commit -m "Build one page of request logs, with a parameter allowlist"
```

---

### Task 5: Normalize a row, sanitizing once

**Files:**
- Modify: `vercel_insights/render.py` (the containers)
- Modify: `vercel_insights/logs.py` (the parser)
- Test: `tests/test_logs.py`, `tests/helpers.py`,
  `tests/test_untrusted_response.py`

**Interfaces:**
- Consumes: `sanitize_label`, `sanitize_message`, `ApiError` from
  `vercel_insights`; `LOG_LEVEL_SEVERITY` from Task 3.
- Produces, in `vercel_insights.render`:
  ```python
  @dataclass(frozen=True)
  class LogLine:
      level: str
      message: str
      truncated: bool = False

  @dataclass(frozen=True)
  class LogEntry:
      request_id: str
      timestamp: datetime | None
      status: int | None
      method: str
      path: str
      route: str
      source: str
      environment: str
      deployment_id: str
      duration_ms: float | None
      region: str
      error_code: str
      branch: str
      domain: str
      trace_id: str
      crashed: bool
      lines: tuple[LogLine, ...] = ()
      raw: dict[str, Any] = field(default_factory=dict)

      @property
      def worst_line(self) -> LogLine | None: ...
      @property
      def worst_level(self) -> str | None: ...
      @property
      def headline(self) -> str: ...
      @property
      def is_error(self) -> bool: ...
      @property
      def label(self) -> str: ...   # route, or path when the route is empty
  ```
  and in `vercel_insights.logs`:
  `normalize(payload: Mapping[str, Any]) -> tuple[list[LogEntry], bool]`
  returning the entries and `hasMoreRows`.
- Produces for tests: `tests/helpers.py::LOGS_PAGE`, `LOGS_ERROR_PAGE`,
  `LOGS_EMPTY_PAGE`, `logs_row(**overrides)`.

- **Step 1: Add the payload fixtures**

In `tests/helpers.py`, under the payload fixtures section, with a comment saying
these rows are copied from `docs/api-notes.md` (which in turn holds real probed
rows):

```python
def logs_row(**overrides: Any) -> dict[str, Any]:
    """One request-logs row, shaped exactly as the live API returns them."""
    row: dict[str, Any] = {
        "requestId": "zgzc9-1786964768933-ce3a0a3fb303",
        "timestamp": "2026-08-17T11:06:08.933Z",
        "deploymentId": "dpl_8fQLGTTwTZXixzmKhKm9DaXeadTJ",
        "environment": "production",
        "deploymentDomain": "demo.vercel.app",
        "branch": "main",
        "domain": "demo.vercel.app",
        "requestMethod": "GET",
        "requestPath": "/api/me",
        "statusCode": 401,
        "errorCode": "",
        "route": "/api/me",
        "cache": "MISS",
        "wafAction": "",
        "traceId": "",
        "logs": [],
        "requestDurationMs": 54,
        "clientRegion": "fra1",
        "hasFunctionCrashed": False,
        "events": [{"source": "serverless", "httpStatus": 401, "region": "fra1"}],
        "requestTags": ["ssr", "rsc"],
    }
    row.update(overrides)
    return row


#: A page of ordinary traffic: no 5xx, no log lines. This is what a healthy
#: project really returns, and it is the shape that makes --level answer with
#: zero rows.
LOGS_PAGE: dict[str, Any] = {"rows": [logs_row()], "hasMoreRows": False}

#: A page carrying the two kinds of error: a 500 that logged a stack trace, and
#: a 502 that logged nothing at all.
LOGS_ERROR_PAGE: dict[str, Any] = {
    "rows": [
        logs_row(
            requestId="err-1",
            timestamp="2026-08-17T11:04:52.100Z",
            requestMethod="POST",
            requestPath="/api/checkout",
            route="/api/checkout",
            statusCode=500,
            logs=[
                {
                    "level": "error",
                    "message": "TypeError: Cannot read properties of undefined",
                    "messageTruncated": False,
                }
            ],
        ),
        logs_row(
            requestId="err-2",
            timestamp="2026-08-17T10:58:03.000Z",
            requestPath="/api/offerings/summer",
            route="/api/offerings/[slug]",
            statusCode=502,
            logs=[],
        ),
    ],
    "hasMoreRows": False,
}

LOGS_EMPTY_PAGE: dict[str, Any] = {"rows": [], "hasMoreRows": False}
```

- **Step 2: Write the failing tests**

Add to `tests/test_logs.py`:

```python
from helpers import LOGS_EMPTY_PAGE, LOGS_ERROR_PAGE, LOGS_PAGE, logs_row

from vercel_insights import ApiError


def test_normalize_reads_the_fields_the_table_shows() -> None:
    entries, has_more = vi_logs.normalize(LOGS_PAGE)
    assert has_more is False
    entry = entries[0]
    assert entry.request_id == "zgzc9-1786964768933-ce3a0a3fb303"
    assert entry.status == 401
    assert entry.method == "GET"
    assert entry.path == "/api/me"
    assert entry.route == "/api/me"
    assert entry.source == "serverless"
    assert entry.region == "fra1"
    assert entry.duration_ms == 54
    assert entry.timestamp is not None
    assert entry.timestamp.isoformat() == "2026-08-17T11:06:08.933000+00:00"


def test_normalize_reads_an_empty_page() -> None:
    entries, has_more = vi_logs.normalize(LOGS_EMPTY_PAGE)
    assert entries == [] and has_more is False


def test_a_row_with_no_log_lines_has_no_level_and_no_headline() -> None:
    entry = vi_logs.normalize(LOGS_PAGE)[0][0]
    assert entry.lines == ()
    assert entry.worst_level is None
    assert entry.headline == ""


def test_the_worst_line_wins_the_level_and_the_headline() -> None:
    payload = {
        "rows": [
            logs_row(
                logs=[
                    {"level": "info", "message": "starting"},
                    {"level": "fatal", "message": "connection pool exhausted"},
                    {"level": "warning", "message": "slow"},
                ]
            )
        ]
    }
    entry = vi_logs.normalize(payload)[0][0]
    assert entry.worst_level == "fatal"
    assert entry.headline == "connection pool exhausted"


def test_a_5xx_is_an_error_even_with_no_log_line() -> None:
    entries, _ = vi_logs.normalize(LOGS_ERROR_PAGE)
    assert [entry.is_error for entry in entries] == [True, True]


def test_a_4xx_is_not_an_error() -> None:
    # A 401 on /api/me is the application working. Counting it would drown the
    # answer in noise and misreport a healthy site as broken.
    assert vi_logs.normalize(LOGS_PAGE)[0][0].is_error is False


def test_a_logged_error_on_a_200_is_an_error() -> None:
    payload = {
        "rows": [logs_row(statusCode=200, logs=[{"level": "error", "message": "boom"}])]
    }
    assert vi_logs.normalize(payload)[0][0].is_error is True


def test_a_crashed_function_is_an_error() -> None:
    payload = {"rows": [logs_row(statusCode=200, hasFunctionCrashed=True)]}
    assert vi_logs.normalize(payload)[0][0].is_error is True


def test_normalize_survives_a_row_that_is_missing_everything() -> None:
    # Real rows carry 30-odd fields and Vercel adds more over time. A row that
    # arrives short must degrade, not raise.
    entries, _ = vi_logs.normalize({"rows": [{}]})
    entry = entries[0]
    assert entry.request_id == ""
    assert entry.status is None
    assert entry.timestamp is None
    assert entry.label == "(unknown)"
    assert entry.is_error is False


def test_normalize_falls_back_to_the_path_when_the_route_is_empty() -> None:
    entry = vi_logs.normalize({"rows": [logs_row(route="")]})[0][0]
    assert entry.label == "/api/me"


def test_normalize_reports_an_unusable_payload_rather_than_raising() -> None:
    for payload in ({"rows": "nope"}, {"rows": [["not", "a", "row"]]}):
        with pytest.raises(ApiError) as excinfo:
            vi_logs.normalize(payload)
        assert excinfo.value.code == "invalid_response"


def test_normalize_keeps_the_raw_row_for_json_output() -> None:
    entry = vi_logs.normalize(LOGS_PAGE)[0][0]
    assert entry.raw["cache"] == "MISS"
    assert entry.raw["requestTags"] == ["ssr", "rsc"]
```

Add to `tests/test_untrusted_response.py`, following that module's existing
style:

```python
def test_a_log_message_cannot_repaint_the_terminal() -> None:
    entry = vi_logs.normalize(
        {"rows": [logs_row(logs=[{"level": "error", "message": "\x1b[2Jerror: fine"}])]}
    )[0][0]
    assert "\x1b" not in entry.headline
    assert "\\x1b" in entry.headline


def test_a_hostile_request_path_is_escaped() -> None:
    entry = vi_logs.normalize({"rows": [logs_row(requestPath="/a\rerror: fine")]})[0][0]
    assert "\r" not in entry.path
    assert "\\x0d" in entry.path


def test_a_multi_line_log_message_keeps_its_lines_but_is_indented() -> None:
    # A stack trace is the one place newlines carry meaning, so they survive.
    # Every line after the first is indented, so nothing the server sends can
    # reach column zero and forge a line of this tool's own output.
    message = "Error: boom\nat handler (/api/checkout)"
    entry = vi_logs.normalize(
        {"rows": [logs_row(logs=[{"level": "error", "message": message}])]}
    )[0][0]
    assert entry.headline.splitlines()[1].startswith("  ")
```

- **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_logs.py tests/test_untrusted_response.py -x -q`
Expected: FAIL with `AttributeError: module 'vercel_insights.logs' has no
attribute 'normalize'`.

- **Step 4: Add the containers to render.py**

In `vercel_insights/render.py`, after `Result`:

```python
@dataclass(frozen=True)
class LogLine:
    """One application log line attached to a request.

    ``message`` is already sanitized: the surface module escapes it once, on the
    way in, so nothing downstream has to remember to.
    """

    level: str
    message: str
    truncated: bool = False


@dataclass(frozen=True)
class LogEntry:
    """One request, as the request logs surface reports it.

    Every string field arrives sanitized. ``raw`` is the exception: it keeps the
    row verbatim so ``--json`` can hand back everything the API sent rather than
    only the columns this tool tabulates. That is safe because ``raw`` is only
    ever emitted through ``json.dumps``, which escapes control characters, so no
    escape sequence in it can reach a terminal. It must never be printed
    directly, and tests/test_logs_render.py holds that line.
    """

    request_id: str = ""
    timestamp: datetime | None = None
    status: int | None = None
    method: str = ""
    path: str = ""
    route: str = ""
    source: str = ""
    environment: str = ""
    deployment_id: str = ""
    duration_ms: float | None = None
    region: str = ""
    error_code: str = ""
    branch: str = ""
    domain: str = ""
    trace_id: str = ""
    crashed: bool = False
    lines: tuple[LogLine, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def worst_line(self) -> LogLine | None:
        """The most severe log line on this request, if it logged anything."""
        if not self.lines:
            return None
        return max(
            self.lines,
            key=lambda line: LOG_LEVEL_SEVERITY.get(line.level, -1),
        )

    @property
    def worst_level(self) -> str | None:
        """The level of :attr:`worst_line`, or ``None`` when nothing was logged."""
        line = self.worst_line
        return line.level if line is not None else None

    @property
    def headline(self) -> str:
        """The message worth showing on one row, empty when nothing was logged."""
        line = self.worst_line
        return line.message if line is not None else ""

    @property
    def is_error(self) -> bool:
        """True when this request is something to worry about.

        Three ways to qualify: the response was a 5xx, the function crashed, or
        the request logged an error or fatal line. A 4xx does not qualify: a 401
        on a login route is the application working.
        """
        if self.status is not None and self.status >= 500:
            return True
        if self.crashed:
            return True
        return self.worst_level in ERROR_LEVELS

    @property
    def label(self) -> str:
        """What to show in the route column: the route, or the path, or a mark."""
        return self.route or self.path or "(unknown)"
```

`max` over `lines` is stable in Python, so the first line of the worst level
wins a tie, which is the earliest one. Note that in a comment.

- **Step 5: Implement the parser in logs.py**

```python
def _text(row: Mapping[str, Any], name: str) -> str:
    """One sanitized single-line string field, empty when absent."""
    value = row.get(name)
    if value is None or isinstance(value, (Mapping, list)):
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return sanitize_label(str(value))


def _number(row: Mapping[str, Any], name: str) -> float | None:
    """One numeric field, ``None`` when absent, non-numeric or not finite."""
    value = row.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(float(value)) else None


def _status(row: Mapping[str, Any]) -> int | None:
    """The HTTP status, ``None`` when the API recorded none.

    A status of 0 is how this API spells "no response was recorded", which is
    also what ``statusCode=None`` selects, so it is read as absent rather than
    as a status of zero.
    """
    value = _number(row, "statusCode")
    if value is None or value <= 0:
        return None
    return int(value)


def _timestamp(row: Mapping[str, Any]) -> datetime | None:
    """The row's instant, ``None`` when it is missing or unparseable.

    Values arrive as ISO-8601 with a trailing ``Z``, which
    ``datetime.fromisoformat`` cannot read before Python 3.11, so the offset is
    spelled out first.
    """
    raw = row.get("timestamp")
    if not isinstance(raw, str) or not raw:
        return None
    candidate = raw[:-1] + "+00:00" if raw.endswith(("Z", "z")) else raw
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _lines(row: Mapping[str, Any]) -> tuple[LogLine, ...]:
    """Every application log line on this request, sanitized.

    ASSUMPTION: the item shape is ``{level, message, messageTruncated}``, taken
    from the Vercel CLI's own mapping code. No probe ever saw one populated,
    because neither test project had logged an error, so anything unexpected is
    skipped rather than trusted. See docs/api-notes.md.
    """
    raw = row.get("logs")
    if not isinstance(raw, list):
        return ()
    lines: list[LogLine] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        message = item.get("message")
        level = item.get("level")
        lines.append(
            LogLine(
                level=sanitize_label(str(level)).lower() if level else "",
                message=sanitize_message(str(message)) if message else "",
                truncated=bool(item.get("messageTruncated")),
            )
        )
    return tuple(lines)


def _source(row: Mapping[str, Any]) -> str:
    """Where the request was served from, read off its first event."""
    events = row.get("events")
    if isinstance(events, list):
        for event in events:
            if isinstance(event, Mapping) and event.get("source"):
                return sanitize_label(str(event["source"]))
    return ""


def _region(row: Mapping[str, Any]) -> str:
    """The region that served the request, off its first event or the client."""
    events = row.get("events")
    if isinstance(events, list):
        for event in events:
            if isinstance(event, Mapping) and event.get("region"):
                return sanitize_label(str(event["region"]))
    return _text(row, "clientRegion")


def _entry(row: Mapping[str, Any]) -> LogEntry:
    """Turn one API row into a :class:`LogEntry`, sanitizing every string."""
    return LogEntry(
        request_id=_text(row, "requestId"),
        timestamp=_timestamp(row),
        status=_status(row),
        method=_text(row, "requestMethod"),
        path=_text(row, "requestPath"),
        route=_text(row, "route"),
        source=_source(row),
        environment=_text(row, "environment"),
        deployment_id=_text(row, "deploymentId"),
        duration_ms=_number(row, "requestDurationMs"),
        region=_region(row),
        error_code=_text(row, "errorCode"),
        branch=_text(row, "branch"),
        domain=_text(row, "domain"),
        trace_id=_text(row, "traceId"),
        crashed=bool(row.get("hasFunctionCrashed")),
        lines=_lines(row),
        raw=dict(row),
    )


def normalize(payload: Mapping[str, Any]) -> tuple[list[LogEntry], bool]:
    """Parse one page of request logs.

    Args:
        payload: The decoded response body.

    Returns:
        The page's entries in the order they arrived, and whether the API said
        more rows exist.

    Raises:
        ApiError: With code ``invalid_response`` when ``rows`` is present but is
            not a list of objects. Nothing is dropped silently: a shape this
            client cannot read is reported, because a quietly shortened list of
            errors is worse than an error message.
    """
    rows = payload.get("rows", [])
    if rows is None:
        rows = []
    if not isinstance(rows, list):
        raise ApiError(
            200,
            "invalid_response",
            "the request logs response carried 'rows' that was not a list; run "
            "with --json to see it",
        )
    entries: list[LogEntry] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ApiError(
                200,
                "invalid_response",
                "the request logs response carried a row that was not an "
                "object; run with --json to see it",
            )
        entries.append(_entry(row))
    return entries, bool(payload.get("hasMoreRows"))
```

Add the imports: `import math`, `from datetime import datetime, timezone`,
`from typing import Any`, `from . import ApiError, sanitize_label,
sanitize_message`, and extend the existing `from .render import ERROR_LEVELS`
line to `from .render import ERROR_LEVELS, LogEntry, LogLine`.

- **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_logs.py tests/test_untrusted_response.py -q && .venv/bin/mypy --strict vercel_insights tests`
Expected: PASS.

- **Step 7: Commit**

```bash
git add vercel_insights/logs.py vercel_insights/render.py tests/
git commit -F - <<'MSG'
Normalize a log row once, sanitizing on the way in

A log message is the most attacker-influenceable string this tool prints, so
escaping happens at the single boundary where a payload becomes a LogEntry. A
row that arrives short degrades; a row that is not an object is reported.
MSG
```

---

### Task 6: Page, merge and deduplicate

**Files:**
- Modify: `vercel_insights/logs.py`
- Test: `tests/test_logs.py`

**Interfaces:**
- Consumes: `normalize`, `PAGE_SIZE`, `MAX_PAGES` from Tasks 3 to 5.
- Produces:
  ```python
  def collect(
      call: Callable[[int], Mapping[str, Any]],
      *,
      limit: int,
      max_pages: int = MAX_PAGES,
  ) -> tuple[list[LogEntry], bool, int]        # entries, truncated, pages read

  def merge(
      groups: Sequence[Sequence[LogEntry]], *, limit: int
  ) -> tuple[list[LogEntry], bool]             # entries, truncated

  def error_filter_sets(
      filters: Mapping[str, str]
  ) -> list[dict[str, str]]
  ```

`collect` takes the fetcher as a callable so the loop is testable with no HTTP
at all; `cli.py` passes a closure over `execute`.

- **Step 1: Write the failing tests**

```python
from typing import Any, Mapping


def _page(count: int, has_more: bool, first_id: int = 0) -> dict[str, Any]:
    return {
        "rows": [logs_row(requestId=f"r{first_id + index}") for index in range(count)],
        "hasMoreRows": has_more,
    }


def test_collect_stops_after_one_page_when_there_is_no_more() -> None:
    calls: list[int] = []

    def call(page: int) -> Mapping[str, Any]:
        calls.append(page)
        return _page(3, False)

    entries, truncated, pages = vi_logs.collect(call, limit=50)
    assert calls == [0]
    assert len(entries) == 3
    assert truncated is False and pages == 1


def test_collect_keeps_paging_until_the_budget_is_met() -> None:
    calls: list[int] = []

    def call(page: int) -> Mapping[str, Any]:
        calls.append(page)
        return _page(vi_logs.PAGE_SIZE, True, first_id=page * vi_logs.PAGE_SIZE)

    entries, truncated, pages = vi_logs.collect(call, limit=120)
    assert calls == [0, 1, 2]
    assert len(entries) == 120
    # More rows existed than were asked for, so this is a truncated answer.
    assert truncated is True and pages == 3


def test_collect_never_reads_more_than_the_page_cap() -> None:
    def call(page: int) -> Mapping[str, Any]:
        return _page(vi_logs.PAGE_SIZE, True, first_id=page * vi_logs.PAGE_SIZE)

    entries, truncated, pages = vi_logs.collect(call, limit=vi_logs.MAX_LIMIT)
    assert pages == vi_logs.MAX_PAGES
    assert len(entries) == vi_logs.MAX_LIMIT
    assert truncated is True


def test_collect_stops_on_a_short_page_even_when_the_api_claims_more() -> None:
    # Defensive: a short page means the server has nothing else for this query,
    # whatever hasMoreRows says. Trusting the flag alone would loop to the cap.
    def call(page: int) -> Mapping[str, Any]:
        return _page(2, True)

    entries, truncated, pages = vi_logs.collect(call, limit=50)
    assert pages == 1 and len(entries) == 2


def test_merge_deduplicates_by_request_id() -> None:
    # A 500 that also logged an error comes back from both calls of the errors
    # preset. It is one request and must be reported once.
    shared = vi_logs.normalize(LOGS_ERROR_PAGE)[0]
    entries, _truncated = vi_logs.merge([shared, shared], limit=50)
    assert len(entries) == 2
    assert [entry.request_id for entry in entries] == ["err-1", "err-2"]


def test_merge_prefers_the_copy_that_carries_log_lines() -> None:
    bare = vi_logs.normalize({"rows": [logs_row(requestId="x", logs=[])]})[0]
    logged = vi_logs.normalize(
        {"rows": [logs_row(requestId="x", logs=[{"level": "error", "message": "boom"}])]}
    )[0]
    entries, _ = vi_logs.merge([bare, logged], limit=50)
    assert len(entries) == 1
    assert entries[0].headline == "boom"


def test_merge_sorts_newest_first() -> None:
    older = vi_logs.normalize(
        {"rows": [logs_row(requestId="old", timestamp="2026-08-17T10:00:00.000Z")]}
    )[0]
    newer = vi_logs.normalize(
        {"rows": [logs_row(requestId="new", timestamp="2026-08-17T11:00:00.000Z")]}
    )[0]
    entries, _ = vi_logs.merge([older, newer], limit=50)
    assert [entry.request_id for entry in entries] == ["new", "old"]


def test_merge_puts_a_row_with_no_timestamp_last_and_stays_deterministic() -> None:
    undated = vi_logs.normalize({"rows": [logs_row(requestId="b", timestamp="")]})[0]
    dated = vi_logs.normalize(
        {"rows": [logs_row(requestId="a", timestamp="2026-08-17T11:00:00.000Z")]}
    )[0]
    entries, _ = vi_logs.merge([undated, dated], limit=50)
    assert [entry.request_id for entry in entries] == ["a", "b"]


def test_merge_reports_truncation_when_it_drops_rows() -> None:
    many = vi_logs.normalize(_page(10, False))[0]
    entries, truncated = vi_logs.merge([many], limit=4)
    assert len(entries) == 4 and truncated is True


def test_error_filter_sets_queries_both_kinds_of_error() -> None:
    # Verified live: level matches log lines only, so a 500 that printed nothing
    # is invisible to level=error, and a 200 that logged a stack trace is
    # invisible to statusCode=5xx. Neither filter alone answers the question.
    assert vi_logs.error_filter_sets({}) == [
        {"statusCode": "5xx"},
        {"level": "error,fatal"},
    ]


def test_error_filter_sets_keeps_the_users_own_filters_on_both_calls() -> None:
    sets = vi_logs.error_filter_sets({"requestPath": "/api/checkout"})
    assert all(item["requestPath"] == "/api/checkout" for item in sets)


@pytest.mark.parametrize("override", [{"statusCode": "500"}, {"level": "warning"}])
def test_an_explicit_filter_collapses_the_errors_preset_to_one_call(
    override: dict[str, str],
) -> None:
    assert vi_logs.error_filter_sets(override) == [override]
```

- **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_logs.py -x -q`
Expected: FAIL, `module 'vercel_insights.logs' has no attribute 'collect'`.

- **Step 3: Implement**

```python
def collect(
    call: Callable[[int], Mapping[str, Any]],
    *,
    limit: int,
    max_pages: int = MAX_PAGES,
) -> tuple[list[LogEntry], bool, int]:
    """Read pages until the row budget is met, and say whether more existed.

    The fetcher is injected so the loop can be tested without HTTP, and so this
    module still performs no I/O of its own.

    Args:
        call: Given a zero based page index, returns that page's payload.
        limit: How many rows the caller wants at most.
        max_pages: Hard ceiling on requests, defaulting to :data:`MAX_PAGES`.

    Returns:
        The entries (never more than ``limit``), whether rows were left behind,
        and how many pages were read.

    Raises:
        ApiError: Whatever :func:`normalize` raises for an unreadable page.
    """
    entries: list[LogEntry] = []
    truncated = False
    pages = 0
    for page in range(max(1, max_pages)):
        payload = call(page)
        pages = page + 1
        page_entries, has_more = normalize(payload)
        entries.extend(page_entries)
        if len(entries) >= limit:
            truncated = truncated or len(entries) > limit or has_more
            break
        if len(page_entries) < PAGE_SIZE:
            # A short page means the server has nothing else for this query,
            # whatever hasMoreRows claims. Trusting the flag alone would spend
            # every remaining request on empty pages.
            break
        if not has_more:
            break
        if pages == max(1, max_pages):
            truncated = True
    return entries[:limit], truncated, pages


def merge(
    groups: Sequence[Sequence[LogEntry]], *, limit: int
) -> tuple[list[LogEntry], bool]:
    """Combine the results of several calls into one honest list.

    One request can arrive from more than one call: a 5xx that also logged an
    error matches both filter sets of the errors presets. Requests are therefore
    deduplicated by id, and the copy carrying more log lines wins, since the
    other one would render with an empty message.

    Ordering is applied here rather than trusted from the server, so "newest
    first" is a property of this client. A row with no timestamp sorts last, and
    the request id breaks ties, so the output is deterministic.

    Args:
        groups: One sequence of entries per call.
        limit: How many rows to keep.

    Returns:
        The merged entries, and whether anything was dropped.
    """
    best: dict[str, LogEntry] = {}
    anonymous: list[LogEntry] = []
    for group in groups:
        for entry in group:
            if not entry.request_id:
                # Without an id there is nothing to deduplicate on, and dropping
                # it would hide a request. Keep it.
                anonymous.append(entry)
                continue
            previous = best.get(entry.request_id)
            if previous is None or len(entry.lines) > len(previous.lines):
                best[entry.request_id] = entry

    merged = list(best.values()) + anonymous
    epoch = datetime(1, 1, 1, tzinfo=timezone.utc)
    merged.sort(
        key=lambda entry: (
            entry.timestamp or epoch,
            entry.request_id,
        ),
        reverse=True,
    )
    return merged[:limit], len(merged) > limit


def error_filter_sets(filters: Mapping[str, str]) -> list[dict[str, str]]:
    """The filter sets an errors preset queries with.

    Two calls, because ``level`` matches application log lines and
    ``statusCode`` matches responses, and an error can be either. An explicit
    ``--level`` or ``--status-code`` collapses it to one call, which is the same
    "an explicit flag overrides a preset value" rule the rest of the tool
    follows.

    Args:
        filters: The wire-named filters the user asked for.

    Returns:
        One or two filter mappings, each a complete filter set for one call.
    """
    if "level" in filters or "statusCode" in filters:
        return [dict(filters)]
    return [
        {**filters, "statusCode": "5xx"},
        {**filters, "level": ",".join(ERROR_LEVELS)},
    ]
```

`ERROR_LEVELS` is the ordered tuple `("error", "fatal")` from Task 3, so the
filter value is `"error,fatal"`, which is what the test above expects. Do not
sort it here: the order is part of the constant so the wire value is stable.

Extend the imports: `from collections.abc import Callable, Mapping, Sequence`
(`Mapping` is already imported from Task 4).

- **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_logs.py -q && .venv/bin/mypy --strict vercel_insights tests`
Expected: PASS.

- **Step 5: Commit**

```bash
git add vercel_insights/logs.py tests/test_logs.py
git commit -F - <<'MSG'
Page, merge and deduplicate log rows

The API pages 50 rows at a time and ignores a limit, so the budget is enforced
here, with a four page ceiling because a page took up to six seconds. The errors
presets query twice and merge, since level matches log lines and statusCode
matches responses.
MSG
```

---

### Task 7: Summarize the errors locally

**Files:**
- Modify: `vercel_insights/render.py` (three containers)
- Modify: `vercel_insights/logs.py` (`summarize`)
- Test: `tests/test_logs.py`

**Interfaces:**
- Produces, in `vercel_insights.render`:
  ```python
  @dataclass(frozen=True)
  class RouteTally:
      route: str
      count: int
      worst_status: int | None
      first_seen: datetime | None
      last_seen: datetime | None

  @dataclass(frozen=True)
  class MessageTally:
      message: str
      count: int
      first_seen: datetime | None
      last_seen: datetime | None

  @dataclass(frozen=True)
  class LogSummary:
      total: int
      by_status: tuple[tuple[str, int], ...]
      by_route: tuple[RouteTally, ...]
      by_message: tuple[MessageTally, ...]
      logged_only: int      # entries that are errors only because they logged
  ```
- and in `vercel_insights.logs`:
  `summarize(entries: Sequence[LogEntry]) -> LogSummary`,
  `NO_LOG_LINE: str = "(no log line)"`.

- **Step 1: Write the failing tests**

```python
def test_summarize_counts_by_status_worst_first() -> None:
    entries = vi_logs.normalize(
        {
            "rows": [
                logs_row(requestId="a", statusCode=500),
                logs_row(requestId="b", statusCode=500),
                logs_row(requestId="c", statusCode=502),
            ]
        }
    )[0]
    summary = vi_logs.summarize(entries)
    assert summary.total == 3
    assert summary.by_status == (("500", 2), ("502", 1))


def test_summarize_groups_routes_with_their_worst_status_and_window() -> None:
    entries = vi_logs.normalize(
        {
            "rows": [
                logs_row(
                    requestId="a",
                    route="/api/checkout",
                    statusCode=500,
                    timestamp="2026-08-17T10:00:00.000Z",
                ),
                logs_row(
                    requestId="b",
                    route="/api/checkout",
                    statusCode=502,
                    timestamp="2026-08-17T11:00:00.000Z",
                ),
            ]
        }
    )[0]
    tally = vi_logs.summarize(entries).by_route[0]
    assert tally.route == "/api/checkout"
    assert tally.count == 2
    assert tally.worst_status == 502
    assert tally.first_seen is not None and tally.first_seen.hour == 10
    assert tally.last_seen is not None and tally.last_seen.hour == 11


def test_summarize_groups_messages_by_exact_text() -> None:
    # Grouping by a guessed pattern would merge two different bugs into one row.
    entries = vi_logs.normalize(
        {
            "rows": [
                logs_row(requestId="a", logs=[{"level": "error", "message": "boom 1"}]),
                logs_row(requestId="b", logs=[{"level": "error", "message": "boom 1"}]),
                logs_row(requestId="c", logs=[{"level": "error", "message": "boom 2"}]),
            ]
        }
    )[0]
    summary = vi_logs.summarize(entries)
    assert [(item.message, item.count) for item in summary.by_message] == [
        ("boom 1", 2),
        ("boom 2", 1),
    ]


def test_summarize_gives_requests_that_logged_nothing_their_own_group() -> None:
    entries = vi_logs.normalize(LOGS_ERROR_PAGE)[0]
    summary = vi_logs.summarize(entries)
    assert (vi_logs.NO_LOG_LINE, 1) in [
        (item.message, item.count) for item in summary.by_message
    ]


def test_summarize_counts_the_errors_that_are_only_errors_because_they_logged() -> None:
    entries = vi_logs.normalize(
        {
            "rows": [
                logs_row(requestId="a", statusCode=500),
                logs_row(
                    requestId="b",
                    statusCode=200,
                    logs=[{"level": "fatal", "message": "pool exhausted"}],
                ),
            ]
        }
    )[0]
    # The status table groups by status alone, so this count is what keeps a 200
    # in that table from reading as a rendering bug.
    assert vi_logs.summarize(entries).logged_only == 1


def test_summarize_of_nothing_is_empty_rather_than_an_error() -> None:
    summary = vi_logs.summarize([])
    assert summary.total == 0
    assert summary.by_status == () and summary.by_route == ()
```

- **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_logs.py -x -q`
Expected: FAIL, no attribute `summarize`.

- **Step 3: Implement the containers, then `summarize`**

Add the three dataclasses to `render.py` exactly as in the Interfaces block
above, each with a one-line docstring saying what it tallies. Then in `logs.py`:

```python
#: The message group for a request that failed without logging anything.
NO_LOG_LINE = "(no log line)"


def summarize(entries: Sequence[LogEntry]) -> LogSummary:
    """Tally a merged list of entries three ways, for the error-summary preset.

    Grouping is deliberately literal: statuses by their own number, routes by
    their pattern, messages by their exact text. Clustering messages by a
    guessed pattern would merge two different bugs into one row, which is a
    worse answer than three rows.

    Args:
        entries: The merged entries, in any order.

    Returns:
        The tallies, each ordered by count and then by name so the output is
        stable across runs.
    """
    status_counts: dict[str, int] = {}
    routes: dict[str, list[LogEntry]] = {}
    messages: dict[str, list[LogEntry]] = {}
    logged_only = 0

    for entry in entries:
        status = str(entry.status) if entry.status is not None else "(none)"
        status_counts[status] = status_counts.get(status, 0) + 1
        routes.setdefault(entry.label, []).append(entry)
        messages.setdefault(entry.headline or NO_LOG_LINE, []).append(entry)
        if (entry.status is None or entry.status < 500) and not entry.crashed:
            logged_only += 1

    def seen(group: Sequence[LogEntry]) -> tuple[datetime | None, datetime | None]:
        stamps = sorted(item.timestamp for item in group if item.timestamp is not None)
        return (stamps[0], stamps[-1]) if stamps else (None, None)

    def worst(group: Sequence[LogEntry]) -> int | None:
        found = [item.status for item in group if item.status is not None]
        return max(found) if found else None

    by_route = tuple(
        RouteTally(
            route=route,
            count=len(group),
            worst_status=worst(group),
            first_seen=seen(group)[0],
            last_seen=seen(group)[1],
        )
        for route, group in sorted(
            routes.items(), key=lambda item: (-len(item[1]), item[0])
        )
    )
    by_message = tuple(
        MessageTally(
            message=message,
            count=len(group),
            first_seen=seen(group)[0],
            last_seen=seen(group)[1],
        )
        for message, group in sorted(
            messages.items(), key=lambda item: (-len(item[1]), item[0])
        )
    )
    by_status = tuple(
        sorted(status_counts.items(), key=lambda item: (-item[1], item[0]))
    )
    return LogSummary(
        total=len(entries),
        by_status=by_status,
        by_route=by_route,
        by_message=by_message,
        logged_only=logged_only,
    )
```

- **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_logs.py -q && .venv/bin/mypy --strict vercel_insights tests`
Expected: PASS.

- **Step 5: Commit**

```bash
git add vercel_insights/logs.py vercel_insights/render.py tests/test_logs.py
git commit -m "Tally errors by status, route and exact message"
```

---

### Task 8: The three presets

**Files:**
- Modify: `vercel_insights/presets.py`
- Test: `tests/test_presets.py`

**Interfaces:**
- Consumes: `LOGS` from `timerange`, `DEFAULT_LIMIT as LOGS_DEFAULT_LIMIT` and
  `MAX_LIMIT as LOGS_MAX_LIMIT` from `logs`.
- Produces: `PRESETS["logs"]`, `PRESETS["errors"]`, `PRESETS["error-summary"]`,
  `Preset.default_since: str | None`, `Preset.is_logs: bool`,
  and `LOGS_DATASET: str = "logs"`.

- **Step 1: Write the failing tests**

Add to `tests/test_presets.py`:

```python
from vercel_insights.timerange import LOGS


@pytest.mark.parametrize("name", ["logs", "errors", "error-summary"])
def test_the_logs_presets_query_the_logs_surface(name: str) -> None:
    preset = PRESETS[name]
    assert preset.surface == LOGS
    assert preset.is_logs is True
    assert preset.group_by == ()
    assert preset.endpoint.endswith("request-logs")


def test_the_errors_presets_issue_two_calls() -> None:
    assert PRESETS["errors"].calls == 2
    assert PRESETS["error-summary"].calls == 2
    assert PRESETS["logs"].calls == 1


@pytest.mark.parametrize(
    ("name", "since"),
    [("logs", "1h"), ("errors", "1h"), ("error-summary", "6h")],
)
def test_a_logs_preset_defaults_to_a_short_window(name: str, since: str) -> None:
    # Runtime logs are retained for an hour on Hobby and a day on Pro, so the
    # global 7d default would mostly report nothing and read as "no errors".
    assert PRESETS[name].default_since == since


def test_every_other_preset_keeps_the_global_default_window() -> None:
    for name, preset in PRESETS.items():
        if not preset.is_logs:
            assert preset.default_since is None, name


def test_the_preset_table_renders_with_the_logs_presets() -> None:
    text = format_presets()
    for name in ("logs", "errors", "error-summary"):
        assert name in text
    assert "request-logs" in text
```

- **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_presets.py -x -q`
Expected: FAIL with `KeyError: 'logs'`.

- **Step 3: Implement**

In `presets.py`, add to the `Preset` dataclass:

```python
    #: A per-surface window default, overriding the global one. Only the logs
    #: presets set it: runtime logs are retained for an hour on Hobby, so a 7
    #: day default there would report nothing and read as a healthy site.
    default_since: str | None = None
```

Add the property and fix `endpoint` so it does not ask the Web Analytics
endpoint selector about a surface that has no datasets:

```python
    @property
    def is_logs(self) -> bool:
        """True when this preset queries the request logs surface."""
        return self.surface == LOGS

    @property
    def endpoint(self) -> str:
        """The endpoint this preset hits, for display purposes."""
        if self.is_logs:
            endpoint = "request-logs"
        elif self.is_speed:
            endpoint = "query"
        else:
            endpoint = select_endpoint(list(self.group_by))
        if self.calls > 1:
            return f"{self.calls} x {endpoint}"
        return endpoint
```

Add the three presets after the Speed Insights block:

```python
    "logs": Preset(
        name="logs",
        dataset=LOGS_DATASET,
        group_by=(),
        limit=LOGS_DEFAULT_LIMIT,
        description="Recent requests, newest first, whatever their status",
        surface=LOGS,
        default_since="1h",
    ),
    "errors": Preset(
        name="errors",
        dataset=LOGS_DATASET,
        group_by=(),
        limit=LOGS_DEFAULT_LIMIT,
        description="Failing requests: 5xx responses and logged error lines",
        calls=2,
        surface=LOGS,
        default_since="1h",
    ),
    "error-summary": Preset(
        name="error-summary",
        dataset=LOGS_DATASET,
        group_by=(),
        limit=LOGS_MAX_LIMIT,
        description="The same errors grouped by status, route and message",
        calls=2,
        surface=LOGS,
        default_since="6h",
    ),
```

with `LOGS_DATASET = "logs"` beside `SPEED_DATASET`. In `format_presets`, add a
closing note line: a logs preset reports rows rather than groups, so its limit
counts requests, and it takes no `--group-by` and no `--granularity`.

- **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_presets.py -q && .venv/bin/mypy --strict vercel_insights tests`
Expected: PASS. `tests/test_cli.py` may fail where it asserts the full preset
list; update those expectations in this task.

- **Step 5: Commit**

```bash
git add vercel_insights/presets.py tests/
git commit -m "Add the logs, errors and error-summary presets"
```

---

### Task 9: The flags, and a three-way surface guard

**Files:**
- Modify: `vercel_insights/cli.py:179-485` (parser), `:552-583`
  (`FILTER_SHORTHANDS`, `_shorthand_values`), `:655-726` (the surface guard)
- Test: `tests/test_logs_cli.py` (new), `tests/test_cli.py`

**Interfaces:**
- Consumes: the validators from Task 3, `LOGS` from `timerange`, the presets
  from Task 8.
- Produces: the parser accepts `--level`, `--status-code`, `--source`,
  `--method`, `--search`, `--request-id`, `--branch`, `--deployment`,
  `--expand`; and
  `_reject_cross_surface_options(args: argparse.Namespace, preset: Preset) -> None`
  rejects every option on a surface where it means nothing, in all three
  directions.

- **Step 1: Write the failing tests**

Create `tests/test_logs_cli.py`:

```python
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
    code, _out, err = cli.run(["top-pages", *flag], dict(DRY_RUN_ENV) | {"VERCEL_TOKEN": "t"})
    assert code == 2
    assert flag[0] in err
    # The message has to name where the flag does work, or the reader is stuck.
    assert "errors" in err or "logs" in err


@pytest.mark.parametrize("flag", LOGS_ONLY_FLAGS, ids=lambda item: item[0])
def test_a_logs_flag_is_refused_on_a_speed_preset(cli: Cli, flag: list[str]) -> None:
    code, _out, err = cli.run(["vitals", *flag], dict(DRY_RUN_ENV) | {"VERCEL_TOKEN": "t"})
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


@pytest.mark.parametrize("argv,flag", WRONG_ON_LOGS, ids=lambda item: str(item))
def test_a_flag_from_another_surface_is_refused_on_errors(
    cli: Cli, argv: list[str], flag: str
) -> None:
    code, _out, err = cli.run(["errors", *argv], dict(DRY_RUN_ENV) | {"VERCEL_TOKEN": "t"})
    assert code == 2, err
    assert flag in err


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


@pytest.mark.parametrize(
    "argv",
    [
        ["errors", "--level", "erro"],
        ["errors", "--source", "lambda"],
        ["errors", "--status-code", ">=500"],
        ["errors", "--limit", "500"],
    ],
)
def test_a_bad_logs_value_is_refused_before_any_request(
    cli: Cli, argv: list[str]
) -> None:
    # session=None makes the fixture fail the test if a request is attempted, so
    # this also proves the check happens before the network.
    code, _out, err = cli.run(argv, BASE_ENV)
    assert code == 2 and err.startswith("error:")
```

Also add `--path` and `--route` acceptance to the same module (they are valid
here):

```python
@pytest.mark.parametrize("flag", [["--path", "/api/me"], ["--route", "/api/[id]"]])
def test_path_and_route_are_accepted_on_a_logs_preset(cli: Cli, flag: list[str]) -> None:
    code, out, err = cli.run(["errors", *flag, "--dry-run"], DRY_RUN_ENV)
    assert code == 0, err
    assert "request-logs" in out
```

- **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_logs_cli.py -x -q`
Expected: FAIL with `unrecognized arguments: --level`.

- **Step 3: Add the parser group**

In `build_parser`, after the `speed` group:

```python
    logs = parser.add_argument_group(
        "request logs",
        "Only meaningful with a logs preset (logs, errors, error-summary). This "
        "API returns rows of text rather than aggregated numbers, and filters "
        "with query parameters rather than OData.",
    )
    logs.add_argument(
        "--level",
        metavar="LEVEL",
        default=None,
        help=(
            "only requests that logged a line at one of these levels: "
            + ", ".join(LOG_LEVELS)
            + ", comma separated. Note that this matches application log lines "
            "only, so a 5xx that printed nothing does not match"
        ),
    )
    logs.add_argument(
        "--status-code",
        dest="status_code",
        metavar="CODE",
        default=None,
        help=(
            "only responses with this status: an integer such as 500, a class "
            "such as 5xx, None for requests with no status recorded, or a comma "
            "separated mix"
        ),
    )
    logs.add_argument(
        "--source",
        metavar="SOURCE",
        default=None,
        help="only requests served by: " + ", ".join(LOG_SOURCES) + ", comma separated",
    )
    logs.add_argument(
        "--method",
        metavar="METHOD",
        default=None,
        help="only this HTTP method, for example POST",
    )
    logs.add_argument(
        "--search",
        metavar="TEXT",
        default=None,
        help=(
            "only requests whose path or log text contains this; free text, not "
            "a query syntax, so 'status:500' is matched literally"
        ),
    )
    logs.add_argument(
        "--request-id",
        dest="request_id",
        metavar="ID",
        default=None,
        help="one request, by the id shown in the table",
    )
    logs.add_argument(
        "--branch",
        metavar="NAME",
        default=None,
        help="only deployments built from this git branch",
    )
    logs.add_argument(
        "--deployment",
        metavar="ID",
        default=None,
        help="only this deployment, by its dpl_ id",
    )
    logs.add_argument(
        "--expand",
        action="store_true",
        help="print each full log message under its row instead of truncating it",
    )
```

Import `LEVELS as LOG_LEVELS`, `SOURCES as LOG_SOURCES` from `.logs`. Extend the
`--limit` help to say that on a logs preset it counts rows, up to
`LOGS_MAX_LIMIT`. Extend the parser `description` to name all three surfaces.

- **Step 4: Rewrite the surface guard as a table**

Replace `SPEED_ONLY_OPTIONS` and `WEB_ONLY_OPTIONS` with one table. Migrate every
existing entry into it **with its current reason text copied verbatim**, so no
message a user or a test already relies on changes wording. The Speed-only
attributes to migrate are `metric`, `percentile`, `aggregation`, `order_by`,
`order`, `bucket_timezone`, `all_projects`, `data_points`, and `budget`; the
Web-Analytics-only ones are `dataset`, `event_name`, `event_property` and `flag`,
whose reasons are already written out in `WEB_ONLY_OPTIONS` today.

```python
#: Every option that is not meaningful on every surface: the argparse attribute,
#: the flag as the user writes it, the surfaces it does mean something on, and
#: the reason it means nothing elsewhere. One table rather than one per surface,
#: because with three surfaces the pairwise version stops being readable.
SURFACE_OPTIONS: tuple[tuple[str, str, frozenset[str], str], ...] = (
    # Speed Insights only. Reasons copied from the SPEED_ONLY_OPTIONS this
    # replaces; the surface set is the only new information.
    ("metric", "--metric", frozenset({SPEED_INSIGHTS}),
     "only Speed Insights reports a metric per request"),
    ("percentile", "--percentile", frozenset({SPEED_INSIGHTS}),
     "a percentile only means something over a distribution of measurements"),
    ("data_points", "--data-points", frozenset({SPEED_INSIGHTS}),
     "only Speed Insights counts the measurements behind a value"),
    ("budget", "--budget", frozenset({SPEED_INSIGHTS}),
     "a budget compares a measured value against a threshold, and only Speed "
     "Insights reports one"),
    # Web Analytics only. Reasons copied verbatim from WEB_ONLY_OPTIONS.
    ("dataset", "--dataset", frozenset({WEB_ANALYTICS}),
     "Speed Insights has no datasets: it queries one metric at a time, chosen "
     "with --metric, and request logs are rows rather than a dataset"),
    ("event_name", "--event-name", frozenset({WEB_ANALYTICS}),
     "neither Speed Insights nor request logs collect custom events"),
    # Request logs only.
    ("level", "--level", frozenset({LOGS}),
     "only the request logs API records a log level"),
    ("status_code", "--status-code", frozenset({LOGS}),
     "only the request logs API reports a response status per request"),
    ("source", "--source", frozenset({LOGS}),
     "only the request logs API says what served a request"),
    ("method", "--method", frozenset({LOGS}),
     "neither analytics API filters by HTTP method"),
    ("search", "--search", frozenset({LOGS}),
     "there is no log text to search on an analytics surface"),
    ("request_id", "--request-id", frozenset({LOGS}),
     "an analytics row is an aggregate, not one request"),
    ("branch", "--branch", frozenset({LOGS}),
     "neither analytics API records the git branch"),
    ("deployment", "--deployment", frozenset({LOGS}),
     "neither analytics API filters by deployment"),
    ("expand", "--expand", frozenset({LOGS}),
     "there is no log message to expand"),
    ("group_by", "--group-by", frozenset({WEB_ANALYTICS, SPEED_INSIGHTS}),
     "request logs are rows rather than buckets, so there is nothing to group; "
     "use the error-summary preset, which groups by status, route and message"),
    ("granularity", "--granularity", frozenset({WEB_ANALYTICS, SPEED_INSIGHTS}),
     "request logs are rows rather than time buckets"),
    ("raw_filters", "--filter", frozenset({WEB_ANALYTICS, SPEED_INSIGHTS}),
     "the request logs API takes no OData; filter with --search, --path, "
     "--route, --status-code, --level, --source, --method or --branch"),
)
```

The remaining Speed-only attributes (`aggregation`, `order_by`, `order`,
`bucket_timezone`, `all_projects`) and the remaining Web-only ones
(`event_property`, `flag`) follow the same four-slot shape, with the reason text
lifted from the tuples being deleted. Do not shorten or rewrite those strings:
`tests/test_cli.py` and `tests/test_speed_cli.py` assert on them.

`_reject_cross_surface_options` keeps its `--dataset` with `--metric` special
case first, then walks the table:

```python
def _reject_cross_surface_options(args: argparse.Namespace, preset: Preset) -> None:
    # The existing --dataset with --metric conflict check stays here, first and
    # unchanged: it names a conflict between two options rather than between an
    # option and a preset, which is the more specific complaint.
    for attribute, flag, surfaces, reason in SURFACE_OPTIONS:
        value = getattr(args, attribute, None)
        if value is None or value is False or value == []:
            continue
        if preset.surface in surfaces:
            continue
        shown = "" if isinstance(value, bool) else f" {value!r}"
        raise ConfigError(
            f"{flag}{shown} has no meaning on the {preset.name} preset, which "
            f"queries {SURFACE_LABELS[preset.surface]}: {reason}. Run one of "
            f"{_preset_names(surfaces)}, or drop the flag"
        )
```

with `_preset_names(surfaces)` returning the comma separated preset names for
those surfaces, so every message still names where the flag does work. Keep the
Web-Analytics-only entries (`--dataset`, `--event-name`, `--event-property`,
`--flag`) and the Speed-only entries in the same table with their current
reasons. Move the `--country`, `--device`, `--browser`, `--os`, `--referrer` and
`--utm-*` handling for the logs surface into `FILTER_SHORTHANDS` by giving that
tuple a third slot per surface: `--path`, `--route` and `--environment` map to
wire parameter names on logs, and everything else maps to `None`, which the
existing "this surface has no such dimension" error already handles.

Add the `--csv` on `error-summary` rejection beside the existing `overview` and
`vitals` ones in `_resolve_settings`, with the same wording pattern.

Imports this task needs in `cli.py`: `LOGS` and `SURFACE_LABELS` from
`.timerange`, and `LEVELS as LOG_LEVELS`, `SOURCES as LOG_SOURCES`,
`MAX_LIMIT as LOGS_MAX_LIMIT` from `.logs`.

- **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_logs_cli.py tests/test_cli.py tests/test_speed_cli.py -q`
Expected: PASS. Any existing message that changed wording is a regression to fix
here, not a test to relax.

- **Step 6: Commit**

```bash
git add vercel_insights/cli.py tests/
git commit -F - <<'MSG'
Accept the logs flags and guard all three surfaces from one table

The pairwise speed-versus-web check stops being readable at three surfaces, so
each option now declares the surfaces it means something on. Every existing
rejection keeps its wording.
MSG
```

---

### Task 10: Resolve settings for a logs run

**Files:**
- Modify: `vercel_insights/cli.py:134` (`DEFAULT_SINCE` handling), `:300-304`
  (`--since` default), `:489-541` (`Settings`), `:826-1034`
  (`_resolve_settings`)
- Test: `tests/test_logs_cli.py`

**Interfaces:**
- Produces: `Settings.log_filters: dict[str, str]`, `Settings.is_logs: bool`, and
  `_resolve_log_filters(args: argparse.Namespace) -> dict[str, str]`.
  `--expand` is read straight off `args` by the emitter in Task 13, so it gets no
  `Settings` field: a field nothing reads is a field that goes stale.

- **Step 1: Write the failing tests**

```python
from helpers import dry_run_calls, dry_run_values


def test_a_logs_run_defaults_to_the_last_hour(cli: Cli) -> None:
    code, out, err = cli.run(["logs", "--dry-run"], DRY_RUN_ENV)
    assert code == 0, err
    start = int(dry_run_values(out, "startDate")[0])
    end = int(dry_run_values(out, "endDate")[0])
    assert 3_600_000 - 5_000 <= end - start <= 3_600_000 + 5_000


def test_error_summary_defaults_to_six_hours(cli: Cli) -> None:
    code, out, _err = cli.run(["error-summary", "--dry-run"], DRY_RUN_ENV)
    assert code == 0
    start = int(dry_run_values(out, "startDate")[0])
    end = int(dry_run_values(out, "endDate")[0])
    assert 6 * 3_600_000 - 5_000 <= end - start <= 6 * 3_600_000 + 5_000


def test_an_explicit_since_beats_the_preset_default(cli: Cli) -> None:
    code, out, _err = cli.run(["logs", "--since", "30m", "--dry-run"], DRY_RUN_ENV)
    start = int(dry_run_values(out, "startDate")[0])
    end = int(dry_run_values(out, "endDate")[0])
    assert code == 0
    assert 1_800_000 - 5_000 <= end - start <= 1_800_000 + 5_000


def test_a_traffic_preset_still_defaults_to_seven_days(cli: Cli) -> None:
    code, out, _err = cli.run(["top-pages", "--dry-run"], DRY_RUN_ENV)
    assert code == 0
    since = dry_run_values(out, "since", call=0)[0]
    until = dry_run_values(out, "until", call=0)[0]
    assert since[:4].isdigit() and until[:4].isdigit()
    # Seven days apart, in ISO-8601 on this surface rather than milliseconds.
    assert since != until


def test_the_errors_preset_dry_runs_both_calls(cli: Cli) -> None:
    code, out, _err = cli.run(["errors", "--dry-run"], DRY_RUN_ENV)
    assert code == 0
    calls = dry_run_calls(out)
    assert len(calls) == 2
    sent = [dict(params) for _endpoint, params in calls]
    assert sent[0]["statusCode"] == "5xx"
    assert sent[1]["level"] == "error,fatal"


def test_an_explicit_status_code_makes_errors_one_call(cli: Cli) -> None:
    code, out, _err = cli.run(
        ["errors", "--status-code", "500", "--dry-run"], DRY_RUN_ENV
    )
    assert code == 0
    assert len(dry_run_calls(out)) == 1
    assert dry_run_values(out, "statusCode")[0] == "500"


def test_the_shorthand_filters_compile_to_query_parameters(cli: Cli) -> None:
    code, out, _err = cli.run(
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
        DRY_RUN_ENV,
    )
    assert code == 0
    sent = dict(dry_run_calls(out)[0][1])
    assert sent["requestPath"] == "/api/me"
    assert sent["route"] == "/api/[id]"
    assert sent["environment"] == "preview"
    assert sent["requestMethod"] == "POST"
    assert "filter" not in sent


def test_a_logs_run_needs_an_owner_and_says_so(cli: Cli) -> None:
    # A team slug names a team but is not an account id, and ownerId wants an id.
    code, _out, err = cli.run(
        ["errors", "--team-slug", "acme"], {"VERCEL_TOKEN": "t", "VERCEL_PROJECT_ID": "p"}
    )
    assert code == 2
    assert "--team-slug" in err and "--owner-id" in err
```

`dry_run_calls` splits on `/web-analytics/`, so extend it in `tests/helpers.py`
to fall back to the last path segment when that marker is absent, and note in
its docstring that a request-logs call yields the endpoint `request-logs`.

- **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_logs_cli.py -x -q`
Expected: FAIL: the window default test fails first, because `--since` still
defaults to `7d` at the parser.

- **Step 3: Move the window default off the parser**

In `build_parser`, change `--since` to `default=None` and adjust the help:

```python
        help=(
            f"start of the window (default: {DEFAULT_SINCE}, or 1h on the logs "
            f"and errors presets and 6h on error-summary); {TIME_HELP}"
        ),
```

In `_resolve_settings`, resolve it:

```python
    since = args.since or preset.default_since or DEFAULT_SINCE
    time_range = resolve_range(since, args.until, now)
```

- **Step 4: Add the logs branch to `_resolve_settings`**

Add the fields to `Settings`:

```python
    #: Logs only: wire-named filter values, keyed by ``logs.FILTER_PARAMS``.
    log_filters: dict[str, str] = field(default_factory=dict)

    @property
    def is_logs(self) -> bool:
        """True when this run queries the request logs surface."""
        return self.surface == LOGS
```

Imports this task needs in `cli.py`: `validate_limit as validate_logs_limit`,
`validate_levels`, `validate_sources`, `validate_status_code`, and
`DEFAULT_LIMIT as LOGS_DEFAULT_LIMIT` from `.logs`.

Add `_resolve_log_filters`, which is the one place a flag becomes a wire
parameter, running each value through the matching validator:

```python
def _resolve_log_filters(args: argparse.Namespace) -> dict[str, str]:
    """Turn every logs filter flag into the query parameters the API takes.

    Each value goes through its validator here, before a request exists,
    because this API answers an unknown level or source with 200 and zero rows.

    Args:
        args: The parsed arguments.

    Returns:
        Wire-named filters, keyed by ``logs.FILTER_PARAMS``.

    Raises:
        ConfigError: From any validator, naming the flag and the accepted set.
    """
    filters: dict[str, str] = {}
    if args.level:
        filters["level"] = validate_levels(args.level)
    if args.status_code:
        filters["statusCode"] = validate_status_code(args.status_code)
    if args.source:
        filters["source"] = validate_sources(args.source)
    if args.method:
        filters["requestMethod"] = str(args.method).strip().upper()
    if args.path:
        filters["requestPath"] = args.path
    if args.route:
        filters["route"] = args.route
    if args.environment:
        filters["environment"] = args.environment
    if args.branch:
        filters["branch"] = args.branch
    if args.deployment:
        filters["deploymentId"] = args.deployment
    if args.request_id:
        filters["requestId"] = args.request_id
    if args.search:
        filters["search"] = args.search
    return filters
```

In the surface branch of `_resolve_settings`:

```python
    elif preset.is_logs:
        group_by = []
        limit = args.limit if args.limit is not None else preset.limit
        limit = validate_logs_limit(limit if limit is not None else LOGS_DEFAULT_LIMIT)
        log_filters = _resolve_log_filters(args)
```

Widen the team-slug guard so it covers both surfaces that need an `ownerId`,
naming the active surface in the message rather than hard-coding "Speed
Insights". Set `filter_expr=None` for a logs run: this surface sends no OData,
and leaving the field empty is what keeps the header line honest.

- **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_logs_cli.py tests/test_cli.py -q && .venv/bin/mypy --strict vercel_insights tests`
Expected: PASS except the tests from Step 1 that need `_plan_log_requests`, which
arrives in Task 13. If a dry-run test fails with "no requests printed", mark it
`xfail` with a reason naming Task 13 and remove the marker there.

- **Step 6: Commit**

```bash
git add vercel_insights/cli.py tests/
git commit -F - <<'MSG'
Resolve a logs run: per-preset window, row limit, query-parameter filters

The window default moves off the parser so a logs preset can ask for the last
hour: runtime logs are retained for an hour on Hobby, and a 7 day default would
report nothing and read as a healthy site.
MSG
```

---

### Task 11: Render the rows

**Files:**
- Modify: `vercel_insights/render.py` (`LogReport`, `render_logs`)
- Modify: `vercel_insights/logs.py` (the prose constants and `build_report`)
- Test: `tests/test_logs_render.py` (new)

**Interfaces:**
- Produces, in `vercel_insights.render`:
  ```python
  @dataclass(frozen=True)
  class LogReport:
      entries: list[LogEntry]
      time_range: tuple[datetime, datetime]
      project_label: str
      preset: str
      #: The window as a person says it, for example "30 minutes". Composed in
      #: logs.py so it cannot disagree with the range line.
      window_label: str = ""
      filters: dict[str, str] = field(default_factory=dict)
      truncated: bool = False
      pages_fetched: int = 0
      requested_limit: int = 0
      header_note: str | None = None
      notes: tuple[str, ...] = ()
      #: The "try this next" line, dropped when --expand already did it.
      hint: str | None = None

  LOG_MESSAGE_WIDTH: int = 34
  LOG_ROUTE_WIDTH: int = 32
  NO_LINE_ERROR: str = "(no log line: the response failed)"

  def render_logs(
      report: LogReport, *, style: Style = PLAIN_STYLE, expand: bool = False
  ) -> str
  ```
- and in `vercel_insights.logs`:
  `RETENTION_NOTE: str`, `ERROR_DEFINITION: str`,
  ```python
  def build_report(
      entries: Sequence[LogEntry],
      *,
      time_range: tuple[datetime, datetime],
      project_label: str,
      preset: str,
      filters: Mapping[str, str],
      truncated: bool,
      pages_fetched: int,
      requested_limit: int,
      counts_errors: bool,
  ) -> LogReport
  ```
  `build_report` is where the prose is decided: the header note, the count
  sentence, the truncation warning and the retention note. `render.py` only lays
  out what it is given, so the API knowledge stays on this side of the layering
  line.

- **Step 1: Write the failing tests**

Create `tests/test_logs_render.py`:

```python
"""Tests for the request logs renderers."""

from __future__ import annotations

from helpers import LOGS_EMPTY_PAGE, LOGS_ERROR_PAGE, utc

from vercel_insights import logs as vi_logs
from vercel_insights.render import render_logs

WINDOW = (utc(2026, 8, 17, 10, 36), utc(2026, 8, 17, 11, 6))


def _report(payload: dict[str, object], **overrides: object) -> object:
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
    assert "TypeError: Cannot read properties of undefined" in text
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
```

- **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_logs_render.py -x -q`
Expected: FAIL, `cannot import name 'render_logs'`.

- **Step 3: Add the prose to logs.py**

```python
#: What the errors presets count, stated in the output so the reader is never
#: guessing. Both halves matter: see the module docstring.
ERROR_DEFINITION = (
    "Counted as an error: a 5xx response, a crashed function, or a request "
    "that logged an error or fatal line."
)

#: Read from https://vercel.com/docs/runtime-logs on 2026-08-17. Printed when a
#: query came back empty over a window longer than the shortest retention, so an
#: empty answer is never mistaken for a healthy one.
RETENTION_NOTE = (
    "Runtime log retention is 1 hour on Hobby, 1 day on Pro, 3 days on "
    "Enterprise and 30 days with Observability Plus, so an empty result over a "
    "longer window can mean the logs aged out rather than that nothing failed."
)

#: The shortest retention any plan has. Below this there is nothing to warn
#: about, and a warning on every empty answer trains the reader to ignore it.
SHORTEST_RETENTION = timedelta(hours=1)
```

Then `build_report` itself. It is the only place the prose is decided, which is
what keeps API knowledge out of `render.py`:

```python
def _window_prose(time_range: tuple[datetime, datetime]) -> str:
    """The window as a person says it: "30 minutes", "6 hours", "3 days"."""
    span = time_range[1] - time_range[0]
    minutes = int(round(span.total_seconds() / 60))
    if minutes < 60:
        return f"{minutes} minute{'' if minutes == 1 else 's'}"
    hours = span.total_seconds() / 3600
    if hours < 48:
        rounded = int(round(hours))
        return f"{rounded} hour{'' if rounded == 1 else 's'}"
    days = int(round(hours / 24))
    return f"{days} day{'' if days == 1 else 's'}"


def build_report(
    entries: Sequence[LogEntry],
    *,
    time_range: tuple[datetime, datetime],
    project_label: str,
    preset: str,
    filters: Mapping[str, str],
    truncated: bool,
    pages_fetched: int,
    requested_limit: int,
    counts_errors: bool,
) -> LogReport:
    """Wrap entries in everything needed to print them honestly.

    Every sentence the output adds beyond the table is composed here: what
    counted as an error, how many there were, what was left out, and what an
    empty answer does not prove. ``render.py`` only lays out what it is given.

    Args:
        entries: The merged entries, newest first.
        time_range: The resolved window.
        project_label: How to name what was queried.
        preset: The preset name, shown in the title.
        filters: The filters the user asked for, wire-named.
        truncated: Whether any call left rows behind.
        pages_fetched: How many requests were spent.
        requested_limit: The row budget that was in force.
        counts_errors: True for the presets that filter to failures.

    Returns:
        The report, ready to render in any format.
    """
    window = _window_prose(time_range)
    notes: list[str] = []
    hint: str | None = None

    if entries:
        summary = summarize(entries)
        noun = "error" if counts_errors else "request"
        plural = "" if summary.total == 1 else "s"
        breakdown = ", ".join(
            f"{count} x {status}" for status, count in summary.by_status
        )
        notes.append(f"{summary.total} {noun}{plural} in {window}: {breakdown}.")
        if len(summary.by_route) > 1:
            worst = summary.by_route[0]
            notes.append(f"Most affected route: {worst.route} ({worst.count}).")
        if counts_errors and summary.logged_only:
            notes.append(
                f"{summary.logged_only} of them returned a non-5xx status and "
                "count as errors only because they logged an error or fatal line."
            )
        hint = (
            "Add --expand for full messages, or --request-id to pull one request "
            "apart."
        )

    if truncated:
        notes.append(
            f"More rows matched than were shown: this is the most recent "
            f"{requested_limit}. Raise --limit (up to {MAX_LIMIT}) or narrow the "
            "window."
        )
        if counts_errors and not {"level", "statusCode"} & set(filters):
            notes.append(
                "Both filters were paging, so this is the most recent "
                f"{requested_limit} of each kind rather than a global top "
                f"{requested_limit}."
            )

    if not entries and time_range[1] - time_range[0] > SHORTEST_RETENTION:
        notes.append(RETENTION_NOTE)

    return LogReport(
        entries=list(entries),
        time_range=time_range,
        project_label=project_label,
        preset=preset,
        window_label=window,
        filters=dict(filters),
        truncated=truncated,
        pages_fetched=pages_fetched,
        requested_limit=requested_limit,
        header_note=ERROR_DEFINITION if counts_errors else None,
        notes=tuple(notes),
        hint=hint,
    )
```

Add `from datetime import timedelta` to the imports for `SHORTEST_RETENTION`.

- **Step 4: Implement `render_logs`**

Columns exactly as the spec's section 8.1. Reuse `render_grid`, `_truncate` and
`Style`; add no new layout primitive.

```python
def _log_time(entry: LogEntry, time_range: tuple[datetime, datetime]) -> str:
    """The row's clock, at a precision the window justifies."""
    if entry.timestamp is None:
        return "(no time)"
    span = time_range[1] - time_range[0]
    pattern = "%H:%M:%S" if span <= timedelta(hours=24) else "%m-%d %H:%M:%S"
    return entry.timestamp.strftime(pattern)


def _log_message_cell(entry: LogEntry, style: Style) -> str:
    """The one line of message that fits in the table.

    An error that logged nothing says so: an empty cell there reads as a
    rendering fault rather than as the fact that the response failed before any
    handler printed anything.
    """
    message = entry.headline
    if not message:
        return NO_LINE_ERROR if entry.is_error else ""
    return _truncate(message.splitlines()[0], LOG_MESSAGE_WIDTH, style)


def _expanded_lines(entry: LogEntry, style: Style) -> list[str]:
    """Every log line of one request, worst first, indented under its row.

    A message may itself be several lines: ``sanitize_message`` indents its
    continuations, so they stay visibly quoted rather than reaching column zero.
    """
    ordered = sorted(
        entry.lines,
        key=lambda line: LOG_LEVEL_SEVERITY.get(line.level, -1),
        reverse=True,
    )
    out: list[str] = []
    for line in ordered:
        label = f"{line.level}: " if line.level else ""
        suffix = " [truncated by Vercel]" if line.truncated else ""
        out.append(style.dim(f"    {label}{line.message}{suffix}"))
    if entry.request_id:
        out.append(style.dim(f"    request {entry.request_id}"))
    return out


def render_logs(
    report: LogReport, *, style: Style = PLAIN_STYLE, expand: bool = False
) -> str:
    """Render a logs report as aligned text.

    One row per request, newest first. An empty report prints one line naming
    what was asked rather than a table head with nothing under it.

    Args:
        report: The report to print.
        style: Colour and glyph settings.
        expand: Print every full log message under its row.

    Returns:
        The report as text, with no trailing newline.
    """
    title = (
        f"Vercel request logs: {report.project_label} "
        f"({report.preset}, last {report.window_label})"
    )
    parts: list[str] = [style.bold(title), _range_line(report.time_range)]
    if report.filters:
        shown = ", ".join(f"{name} {value}" for name, value in report.filters.items())
        parts.append(f"Filter: {shown}")
    if report.header_note:
        parts.append(style.dim(report.header_note))
    parts.append("")

    if not report.entries:
        since, until = report.time_range
        parts.append(
            f"No request logs for project {report.project_label} between "
            f"{to_api_timestamp(since)} and {to_api_timestamp(until)}."
        )
    else:
        headers = ["time", "level", "status", "method", "route", "source", "message"]
        aligns = ["left", "left", "right", "left", "left", "left", "left"]
        body = [
            [
                _log_time(entry, report.time_range),
                entry.worst_level or "-",
                str(entry.status) if entry.status is not None else "(none)",
                entry.method or "-",
                _truncate(entry.label, LOG_ROUTE_WIDTH, style),
                entry.source or "-",
                _log_message_cell(entry, style),
            ]
            for entry in report.entries
        ]
        grid = render_grid(headers, aligns, body, None, style)
        # render_grid emits the head, the rule, then one line per body row in
        # order, which is what lets the expansions be spliced under their rows.
        parts.extend(grid[:2])
        for index, entry in enumerate(report.entries):
            parts.append(grid[2 + index])
            if expand:
                parts.extend(_expanded_lines(entry, style))

    if report.notes:
        parts.append("")
        parts.extend(style.dim(note) for note in report.notes)
    if report.hint and not expand:
        parts.append(style.dim(report.hint))
    return "\n".join(parts)
```

- **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_logs_render.py -q && .venv/bin/mypy --strict vercel_insights tests`
Expected: PASS.

- **Step 6: Commit**

```bash
git add vercel_insights/logs.py vercel_insights/render.py tests/test_logs_render.py
git commit -F - <<'MSG'
Render log rows, and say what an empty answer does not prove

The prose is composed in logs.py and laid out in render.py, so API knowledge
stays out of the generic renderer. An empty window longer than the shortest
retention prints the retention table rather than implying nothing failed.
MSG
```

---

### Task 12: Render the summary, and the machine formats

**Files:**
- Modify: `vercel_insights/render.py`
- Test: `tests/test_logs_render.py`

**Interfaces:**
- Produces:
  ```python
  def render_error_summary(
      report: LogReport, summary: LogSummary, *, style: Style = PLAIN_STYLE
  ) -> str

  def format_logs_json(report: LogReport) -> str
  def format_logs_csv(report: LogReport) -> str
  ```

- **Step 1: Write the failing tests**

```python
import csv
import io
import json

from vercel_insights.render import format_logs_csv, format_logs_json, render_error_summary


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
```

- **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_logs_render.py -x -q`
Expected: FAIL, `cannot import name 'render_error_summary'`.

- **Step 3: Implement**

`render_error_summary` prints the title and range line, then three
`render_grid` tables:

- status: `status`, `count`, `share`, with a `TOTAL` footer row, shares computed
  against `summary.total` and formatted like the existing share column;
- route: `route`, `count`, `worst status`, `first seen`, `last seen`, no totals
  row (a worst status does not add up);
- message: `message` truncated to 48 characters, `count`, `first seen`,
  `last seen`.

Then the report's notes, verbatim from `report.notes`. The `logged_only`
sentence is already one of those, composed in `build_report` (Task 11), so this
renderer must **not** add its own copy: that is what the "logged" assertion in
the test above is checking for, and printing it twice would be a bug.

```python
def _log_entry_json(entry: LogEntry) -> dict[str, Any]:
    """One entry as a JSON object, keeping the whole row alongside the columns."""
    return {
        "requestId": entry.request_id,
        "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
        "status": entry.status,
        "method": entry.method,
        "path": entry.path,
        "route": entry.route,
        "source": entry.source,
        "environment": entry.environment,
        "deploymentId": entry.deployment_id,
        "durationMs": entry.duration_ms,
        "region": entry.region,
        "errorCode": entry.error_code,
        "branch": entry.branch,
        "domain": entry.domain,
        "traceId": entry.trace_id,
        "crashed": entry.crashed,
        "isError": entry.is_error,
        "level": entry.worst_level,
        "message": entry.headline,
        "lines": [
            {
                "level": line.level,
                "message": line.message,
                "truncated": line.truncated,
            }
            for line in entry.lines
        ],
        "raw": entry.raw,
    }


def format_logs_json(report: LogReport) -> str:
    """Render a logs report as JSON, keeping every field the API sent.

    ``raw`` carries the untouched row, which is safe here and only here: this is
    the one output path that escapes control characters on the way out.
    """
    since, until = report.time_range
    document = {
        "query": {
            "project": report.project_label,
            "preset": report.preset,
            "since": to_api_timestamp(since),
            "until": to_api_timestamp(until),
            "filters": report.filters,
            "limit": report.requested_limit,
        },
        "entries": [_log_entry_json(entry) for entry in report.entries],
        "truncated": report.truncated,
        "pagesFetched": report.pages_fetched,
        "notes": list(report.notes),
    }
    return json.dumps(document, indent=2, allow_nan=False)


#: The CSV columns, in order. Kept next to the writer so the header and the row
#: cannot drift apart.
LOG_CSV_COLUMNS: tuple[str, ...] = (
    "time",
    "level",
    "status",
    "method",
    "route",
    "path",
    "source",
    "requestId",
    "message",
)


def format_logs_csv(report: LogReport) -> str:
    """Render a logs report as CSV, one row per request.

    Messages are already sanitized, so a newline inside one is the visible
    escape ``\\x0a`` and cannot break a row open. The csv module quotes the rest.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(LOG_CSV_COLUMNS)
    for entry in report.entries:
        writer.writerow(
            [
                entry.timestamp.isoformat() if entry.timestamp else "",
                entry.worst_level or "",
                entry.status if entry.status is not None else "",
                entry.method,
                entry.route,
                entry.path,
                entry.source,
                entry.request_id,
                entry.headline,
            ]
        )
    return buffer.getvalue()
```

`allow_nan=False` is deliberate: `--json` is sold as jq-pipeable in the README,
and `NaN` is not JSON. `csv` and `io` and `json` are already imported by
`render.py`.

- **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_logs_render.py -q && .venv/bin/mypy --strict vercel_insights tests`
Expected: PASS.

- **Step 5: Commit**

```bash
git add vercel_insights/render.py tests/test_logs_render.py
git commit -m "Render the error summary, plus logs JSON and CSV"
```

---

### Task 13: Wire it into main()

**Files:**
- Modify: `vercel_insights/cli.py:1037-1080` (planners), `:1096-1131`
  (the `_explain_*` helpers), `:1459-1578` (`_run`), and the emitters
- Test: `tests/test_logs_cli.py`

**Interfaces:**
- Produces:
  `_plan_log_requests(settings: Settings, page: int = 0) -> list[PreparedRequest]`,
  `_collect_logs(settings, args, session, on_retry) -> LogReport`,
  `_emit_logs(settings, args, report, style, out) -> int`,
  `_explain_request_logs_403(exc: ApiError) -> ApiError`.

- **Step 1: Write the failing tests**

```python
from helpers import LOGS_EMPTY_PAGE, LOGS_ERROR_PAGE, LOGS_URL, error_payload
from helpers import FakeResponse, FakeSession


def test_errors_reports_both_kinds_of_failure(cli: Cli) -> None:
    session = FakeSession(
        FakeResponse(200, LOGS_ERROR_PAGE),
        FakeResponse(200, LOGS_EMPTY_PAGE),
    )
    code, out, err = cli.run(["errors", "--since", "30m"], BASE_ENV, session)
    assert code == 0, err
    assert "/api/checkout" in out
    assert "TypeError" in out
    assert [call["url"] for call in session.calls] == [LOGS_URL, LOGS_URL]


def test_an_empty_window_is_a_success_not_a_failure(cli: Cli) -> None:
    session = FakeSession(
        FakeResponse(200, LOGS_EMPTY_PAGE), FakeResponse(200, LOGS_EMPTY_PAGE)
    )
    code, out, _err = cli.run(["errors"], BASE_ENV, session)
    assert code == 0
    assert "No request logs" in out


def test_the_logs_preset_makes_one_call(cli: Cli) -> None:
    session = FakeSession(FakeResponse(200, LOGS_ERROR_PAGE))
    code, _out, _err = cli.run(["logs"], BASE_ENV, session)
    assert code == 0
    assert len(session.calls) == 1


def test_paging_stops_at_the_limit(cli: Cli) -> None:
    full = {"rows": [logs_row(requestId=f"r{i}") for i in range(50)], "hasMoreRows": True}
    session = FakeSession(*[FakeResponse(200, full) for _ in range(4)])
    code, out, _err = cli.run(["logs", "--limit", "120"], BASE_ENV, session)
    assert code == 0
    assert len(session.calls) == 3
    assert "more" in out.lower()


def test_error_summary_prints_the_grouped_tables(cli: Cli) -> None:
    session = FakeSession(
        FakeResponse(200, LOGS_ERROR_PAGE), FakeResponse(200, LOGS_EMPTY_PAGE)
    )
    code, out, _err = cli.run(["error-summary"], BASE_ENV, session)
    assert code == 0
    assert "worst status" in out


def test_a_403_explains_token_scope(cli: Cli) -> None:
    session = FakeSession(
        FakeResponse(403, error_payload("forbidden", "You don't have permission"))
    )
    code, _out, err = cli.run(["logs"], BASE_ENV, session)
    assert code == 1
    assert "account" in err and "team" in err
    assert "vercel.com/account/tokens" in err


def test_json_output_goes_through_the_logs_formatter(cli: Cli) -> None:
    session = FakeSession(FakeResponse(200, LOGS_ERROR_PAGE))
    code, out, _err = cli.run(["logs", "--json"], BASE_ENV, session)
    assert code == 0
    assert json.loads(out)["entries"][0]["requestId"] == "err-1"


def test_the_token_never_reaches_the_output(cli: Cli) -> None:
    session = FakeSession(FakeResponse(200, LOGS_ERROR_PAGE))
    code, out, err = cli.run(["logs", "--verbose"], BASE_ENV, session)
    assert code == 0
    assert TOKEN not in out and TOKEN not in err
```

Remove any `xfail` markers added in Task 10.

- **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_logs_cli.py -x -q`
Expected: FAIL, the logs presets currently fall through to the Web Analytics
planner.

- **Step 3: Implement the planner and the collector**

```python
def _plan_log_requests(settings: Settings, page: int = 0) -> list[PreparedRequest]:
    """One request per filter set, for a single page.

    The errors presets have two filter sets, so this returns two requests. It is
    also what --dry-run prints, which is why it takes a page rather than looping.
    """
    filter_sets = (
        error_filter_sets(settings.log_filters)
        if settings.preset.calls > 1
        else [dict(settings.log_filters)]
    )
    return [
        build_logs_request(
            project=settings.project,
            owner_id=settings.owner_id or "",
            since=settings.time_range[0],
            until=settings.time_range[1],
            page=page,
            filters=filters,
            token=settings.token,
        )
        for filters in filter_sets
    ]


def _collect_logs(
    settings: Settings,
    args: argparse.Namespace,
    session: Any,
    on_retry: Callable[[str], None],
    err: TextIO,
) -> LogReport:
    """Fetch every filter set, page by page, and build the report.

    Each filter set gets its own paging budget, then the sets are merged and
    deduplicated: one request can match both.
    """
    limit = settings.limit or LOGS_DEFAULT_LIMIT
    groups: list[list[LogEntry]] = []
    truncated = False
    pages = 0

    for index in range(len(_plan_log_requests(settings))):
        def call(page: int, index: int = index) -> Mapping[str, Any]:
            prepared = _plan_log_requests(settings, page)[index]
            if args.verbose:
                print(
                    f"verbose: {prepared.method} {prepared.url} page {page}",
                    file=err,
                )
            try:
                answer = execute(
                    prepared,
                    session,
                    max_retries=args.max_retries,
                    timeout=settings.timeout,
                    on_retry=on_retry,
                )
            except ApiError as exc:
                raise _explain_request_logs_403(exc) from None
            if not isinstance(answer, Mapping):
                raise ApiError(
                    200,
                    "invalid_response",
                    "the request logs response was a JSON array, but this "
                    "endpoint answers with an object carrying 'rows'",
                )
            return answer

        entries, call_truncated, call_pages = collect_logs(call, limit=limit)
        groups.append(entries)
        truncated = truncated or call_truncated
        pages += call_pages

    merged, merge_truncated = merge_logs(groups, limit=limit)
    return build_log_report(
        merged,
        time_range=settings.time_range,
        project_label=settings.project_label,
        preset=settings.preset.name,
        filters=settings.log_filters,
        truncated=truncated or merge_truncated,
        pages_fetched=pages,
        requested_limit=limit,
        counts_errors=settings.preset.name in ("errors", "error-summary"),
    )
```

The verbose line goes to the `err` stream `_run` already holds rather than to
`sys.stderr`, which is why `err` is a parameter: the CLI tests capture streams,
and a print to the global would escape them.

`_explain_request_logs_403`:

```python
def _explain_request_logs_403(exc: ApiError) -> ApiError:
    """Turn a 403 from the logs endpoint into the answer, not just the status.

    This endpoint is scoped by ownerId, like Speed Insights, so the usual cause
    is a token scoped to a single project rather than to the account or team.
    ASSUMPTION: only a team scoped token was available to verify this against.
    """
    if exc.status != 403:
        return exc
    return ApiError(
        exc.status,
        exc.code,
        f"{exc.message} Request logs are scoped by the owning account, so a "
        "token scoped to a single project cannot read them. Create an account "
        f"or team scoped token at {DOCS_TOKEN_URL}, and set VERCEL_TEAM_ID for "
        "a team owned project.",
        attempts=exc.attempts,
    )
```

- **Step 4: Branch in `_run` and add the emitter**

In `_run`, extend `needs_lookup` to cover logs (an owner is required there too,
and a project name is fine on this endpoint, so only the owner forces a lookup),
make `_plan_requests` delegate to `_plan_log_requests` for a logs preset so
`--dry-run` works, and inside the session `try` block:

```python
    payloads: list[dict[str, Any]] = []
    report: LogReport | None = None      # declared here so mypy sees one type
    session = requests.Session()
    try:
        # The existing owner lookup block stays here, unchanged.
        if settings.is_logs:
            report = _collect_logs(settings, args, session, on_retry, err)
        else:
            ... the existing payload loop, unchanged ...
```

After the `finally`:

```python
    if report is not None:
        return _emit_logs(settings, args, report, style, out)
```

Keying the branch off `report is not None` rather than off `settings.is_logs`
keeps `mypy --strict` happy without an assert, and reads as what it is: a report
was collected, so print it.

```python
def _emit_logs(
    settings: Settings,
    args: argparse.Namespace,
    report: LogReport,
    style: Style,
    out: TextIO,
) -> int:
    """Print a logs report in whichever format was asked for. Always exit 0."""
    if args.json:
        print(format_logs_json(report), file=out)
        return 0
    if args.csv:
        print(format_logs_csv(report), end="", file=out)
        return 0
    if settings.preset.name == "error-summary":
        print(render_error_summary(report, summarize(report.entries), style=style), file=out)
        return 0
    print(render_logs(report, style=style, expand=args.expand), file=out)
    return 0
```

Import the logs names in `cli.py` with the same aliasing style the module
already uses for the other two surfaces (`from .logs import build_request as
build_logs_request`, `collect as collect_logs`, `merge as merge_logs`,
`build_report as build_log_report`, `summarize`, `error_filter_sets`,
`DEFAULT_LIMIT as LOGS_DEFAULT_LIMIT`, `MAX_LIMIT as LOGS_MAX_LIMIT`,
`validate_limit as validate_logs_limit`, `validate_levels`,
`validate_sources`, `validate_status_code`).

- **Step 5: Run the whole suite**

Run: `.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/mypy --strict vercel_insights tests`
Expected: PASS, except `tests/test_skill_manifest.py`, which Task 14 fixes.

- **Step 6: Run it against the real API**

This is the first point where the feature exists end to end, and the payload
fixtures came from a live probe, so check the real thing once:

```bash
export VERCEL_TOKEN=...        # an account or team scoped token
export VERCEL_TEAM_ID=...      # if the project is team owned
python3 -m vercel_insights logs --since 30m --limit 5
python3 -m vercel_insights errors --since 24h
python3 -m vercel_insights error-summary --since 6h
python3 -m vercel_insights errors --since 30m --dry-run
```

Expected: real rows or an honest empty line with the retention note. Any
difference from the fixtures is a fact for `docs/api-notes.md`, not something to
paper over in the parser.

- **Step 7: Commit**

```bash
git add vercel_insights/cli.py tests/
git commit -F - <<'MSG'
Answer a logs question end to end

Each filter set pages independently, then the sets are merged and deduplicated.
A 403 explains token scope rather than repeating the status, since this endpoint
is scoped by the owning account.
MSG
```

---

### Task 14: SKILL.md tells the truth, and the version moves

**Files:**
- Modify: `SKILL.md` (front matter, surfaces, decision table, read-only
  section, gotchas, a new reading section)
- Modify: `vercel_insights/__init__.py` (`VERSION`), `pyproject.toml`
- Test: `tests/test_skill_manifest.py`

**Interfaces:**
- Consumes: the finished feature.
- Produces: a SKILL.md that routes an error question to this skill, and
  `VERSION == "1.1.0"` in all three places.

- **Step 1: Run the manifest tests to see what is red**

Run: `.venv/bin/pytest tests/test_skill_manifest.py -q`
Expected: FAIL on the endpoint count, on `request_logs` being undocumented, and
on the version once it is bumped.

- **Step 2: Rewrite the front-matter description**

```yaml
description: >-
  Reports a Vercel site's errors, traffic and speed: runtime error logs,
  failing requests, page views, visitors, top pages, referrers, and Core Web
  Vitals. Trigger on requests like "what errors did my site have in the last
  30 minutes", "why am I getting 500s", "show me the logs", "how is my
  traffic this week", or "which pages are slowest". Read only.
```

350 characters joined, against the 400 character cap the manifest test
enforces. Check it rather than trusting this plan:

```bash
.venv/bin/pytest tests/test_skill_manifest.py::test_the_description_stays_short_enough_to_read_in_a_list -q
```

Bump `version:` in the front matter to `1.1.0`.

- **Step 3: Document the sixth endpoint**

In the read-only section, change "five-endpoint allowlist" to
"six-endpoint allowlist" and "exactly five entries" to "exactly six entries",
both of which the manifest test checks, and add the row:

```markdown
| `request_logs` | GET | `https://vercel.com/api/logs/request-logs` |
```

The row must carry the full URL, because the test strips only the
`api.vercel.com` prefix before looking for the path. Then add the paragraph that
tells the truth about it: this is the one endpoint that is not on
`api.vercel.com` and not in Vercel's published OpenAPI document; it is what the
official `vercel logs` command calls; the documented alternative is an endless
stream and the metrics route needs Observability Plus; it is read-only and can
change without notice.

- **Step 4: Add the logs surface to the guidance**

- Change "Two surfaces, one command" to three, adding a logs column: answers
  "what broke", rows rather than aggregates, presets `logs`, `errors`,
  `error-summary`, filters by query parameter rather than OData, selected by a
  logs preset.
- Add the decision table from the spec's section 11, verbatim.
- Add a "Reading a logs answer" section carrying the spec's section 9 in full:
  empty is not proof of health and why, 4xx is excluded on purpose, `--level`
  only sees requests that logged, truncation, log text is untrusted, and log
  bodies may contain the user's own secrets so they must not be forwarded to
  another service.
- Add to the gotchas: request logs need no Observability Plus while a
  metric-based error count answers 402 (so do not reach for
  `--metric vercel.request.count` for an error question); there is no live tail;
  `--path` and `--route` are exact match here and `--search` is the substring
  tool.
- Update the exit code and environment sections if the logs surface changes
  anything there (it does not add a variable: the owner comes from the same
  place Speed Insights gets it).

- **Step 5: Bump the version in the package and the project file**

`vercel_insights/__init__.py`: `VERSION = "1.1.0"`. `pyproject.toml`:
`version = "1.1.0"`.

- **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/mypy --strict vercel_insights tests`
Expected: PASS, the whole suite, including every manifest test.

- **Step 7: Commit**

```bash
git add SKILL.md vercel_insights/__init__.py pyproject.toml tests/
git commit -F - <<'MSG'
Teach SKILL.md the logs surface, release 1.1.0

The description is what decides whether an error question reaches this skill at
all, so it leads with errors now. The allowlist section documents the sixth
endpoint, its second host, and that it is CLI-verified rather than
OpenAPI-documented.
MSG
```

---

### Task 15: The rest of the documentation

**Files:**
- Modify: `docs/api-notes.md`, `docs/cli-contract.md`, `README.md`,
  `examples/example_outputs.md`, `CONTRIBUTING.md`, `CHANGELOG.md`

**Interfaces:**
- Consumes: the finished feature and the spec.
- Produces: documentation that matches the code.

- **Step 1: Add the third chapter to `docs/api-notes.md`**

Copy the spec's section 2 in full, in the house style of the two existing
chapters: a sources list, endpoint table, parameters, response shape with a real
row, the semantics of `level`, the validation rules, retention, and the "two
alternatives that do not work" subsection with both the streaming endpoint and
the 402. Mark the two ASSUMPTION items (the `logs[]` item shape and
project-scoped tokens) the way the existing chapters mark theirs. Date the
chapter 2026-08-17 and name the CLI source file that ground-truths the endpoint.

- **Step 2: Extend `docs/cli-contract.md`**

Add the three presets to the preset table, the nine new flags to the flag table
with their surfaces and validation, the per-preset window defaults, the row
meaning of `--limit` on a logs preset, and the rejection rules from Task 9 as
numbered contract rules in the same style as the existing ones.

- **Step 3: Extend `README.md`**

A logs section after the speed section: what it answers, the three presets, the
one-line "errors in the last 30 minutes" example, the retention table, and the
note about the second host and why it exists. Update any place the README says
this skill covers two APIs or five endpoints.

- **Step 4: Extend `examples/example_outputs.md`**

Paste the three real outputs captured in Task 13 step 6 (redacting the project
name if it matters), or the spec's section 8 mockups if the live account had no
errors to show, labelled as illustrative in that case.

- **Step 5: Update `CONTRIBUTING.md`**

Add `logs.py` to the layout block with a one-line responsibility, and add
`tests/test_logs*.py` to the tests line. Extend the layering paragraph: the log
containers live in `render.py` beside `Row` and `Result` because `render.py` must
not import a surface module, and the log prose is composed in `logs.py` so API
knowledge stays out of the renderer.

- **Step 6: Add the CHANGELOG entry**

A `1.1.0` entry in the existing style: what was added (the surface, three
presets, nine flags), what was verified live and what remains an assumption, the
allowlist going from five entries to six on two hosts, and the honesty rules for
an empty result.

- **Step 7: Verify and commit**

```bash
.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/mypy --strict vercel_insights tests
grep -rnP '\x{2014}' SKILL.md README.md CHANGELOG.md CONTRIBUTING.md docs/ vercel_insights/ tests/ ; echo "em dashes above must be empty"
git add -A
git commit -m "Document the logs surface across the docs set"
```

---

## Verification of the whole branch

- `.venv/bin/pytest -q` passes with no skips other than pre-existing ones.
- `.venv/bin/ruff check .` clean.
- `.venv/bin/mypy --strict vercel_insights tests` clean, no new ignores.
- `python3 -m vercel_insights --help` names all three surfaces.
- `python3 -m vercel_insights --list-presets` lists the three logs presets.
- `python3 /abs/path/vercel_insights/__main__.py errors --dry-run` works from
  an unrelated directory.
- `python3 -m vercel_insights errors --since 30m` answers against the real
  account, and an empty answer carries the retention note.
- No em dash anywhere in the diff.
- `git log --oneline` reads as a sequence of small, honest steps.
