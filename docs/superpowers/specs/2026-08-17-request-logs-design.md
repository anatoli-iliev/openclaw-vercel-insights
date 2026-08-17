# Request logs: a third surface for this skill

Design agreed 2026-08-17. Status: approved, not yet implemented.

## 1. What this is for

An OpenClaw user should be able to say **"give me the errors my project has had
for the last 30 minutes"** and get a straight answer. Today the skill answers
"how many people came" (Web Analytics) and "how fast was it" (Speed Insights).
It cannot answer "what broke", which is the question people actually ask in a
hurry.

This adds a third query surface, **request logs**, with one headline command:

```bash
vercel-insights errors --since 30m
```

Two decisions were taken before design, and both are settled:

1. **The endpoint is added even though it is not in Vercel's public OpenAPI**,
   with the risk documented rather than hidden. Section 2 explains why there is
   no documented alternative.
2. **Scope is runtime request logs only.** Build logs for failed deployments are
   a separate question with a separate time model and are explicitly out of
   scope (section 12).

## 2. Verified ground truth

Everything in this section was probed against the live API on 2026-08-17 with a
team-scoped token, or read from the live docs the same day. Where this section
disagrees with memory or a blog post, this section wins. The facts belong in
`docs/api-notes.md` as a third "verified ground truth" chapter when this is
implemented; they are recorded here first because the design depends on them.

### 2.1 The endpoint

```
GET https://vercel.com/api/logs/request-logs
Authorization: Bearer <the same Vercel access token>
```

Note the host: **`vercel.com`, not `api.vercel.com`**. This is the endpoint the
official `vercel logs` command calls in its non-streaming mode. It is absent
from <https://openapi.vercel.sh/>, so the ground truth for it is the Vercel CLI
source (`packages/cli/src/util/logs-v2.ts`, function `fetchRequestLogs`) plus
the live probes below.

Latency observed: 1.4s to 6.0s per call. The existing 30 second default timeout
is comfortable; do not lower it for this surface.

### 2.2 Parameters

Required. Omitting either is a `400`:

| Name | Notes |
| --- | --- |
| `projectId` | Project id or project **name**; both verified working. |
| `ownerId` | Account id owning the project. Missing: `400 Validation error: Required at "ownerId"`. Wrong value: `403 You don't have permission to access this resource.` `teamId` is **not** accepted as a substitute. |
| `page` | Zero based page index. |
| `startDate`, `endDate` | Unix **milliseconds**. |

Optional, all verified to filter:

| Name | Accepted values | Notes |
| --- | --- | --- |
| `level` | `error`, `warning`, `info`, `fatal`, comma separated | Matches **application log lines only**; see 2.4. |
| `statusCode` | integers, `Nxx` classes, or the literal `None`, comma separated | See 2.5. |
| `source` | `serverless`, `edge-function`, `edge-middleware`, `static`, comma separated | |
| `environment` | `production`, `preview` | |
| `requestPath` | exact path | **Exact match**: `/api` returned nothing, `/api/me` returned only that path. |
| `route` | exact route pattern | `/api/offerings/[slug]` returned 23 rows across 14 distinct paths. |
| `requestMethod` | `GET`, `POST`, ... | |
| `branch` | git branch name | |
| `deploymentId` | `dpl_...` | |
| `requestId` | one request | |
| `search` | free text | See 2.6. |

Silently ignored, verified to have no effect: `limit`, `path`, `method`,
`domain`, `host`. **`limit` being ignored is the reason row limits are enforced
locally** (section 7).

### 2.3 Response

```json
{"rows": [ ... ], "hasMoreRows": true}
```

A page is **50 rows**, fixed. `hasMoreRows` is the only pagination signal.
Rows arrive newest first (observed; the client sorts anyway, section 7).

One real row, trimmed, from a live production project:

```json
{
  "requestId": "zgzc9-1786964768933-ce3a0a3fb303",
  "timestamp": "2026-08-17T11:06:08.933Z",
  "deploymentId": "dpl_8fQLGTTwTZXixzmKhKm9DaXeadTJ",
  "environment": "production",
  "deploymentDomain": "dobri-4zfpwg8vq-...vercel.app",
  "branch": "main",
  "domain": "dobri-4zfpwg8vq-...vercel.app",
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
  "hasFunctionCrashed": false,
  "events": [
    {
      "source": "serverless",
      "route": "/api/me",
      "httpStatus": 401,
      "region": "fra1",
      "durationMs": 9,
      "functionRuntime": "nodejs24.x",
      "functionStartType": "hot",
      "functionMaxMemoryUsed": 329,
      "invocationId": "01M07PCY66AS0DTZJ2M4GFQS9F"
    }
  ],
  "requestTags": ["ssr", "rsc"]
}
```

Other fields present on real rows and not used by this design, listed so nobody
has to re-probe: `service`, `callingService`, `resolvedDynamicPath`,
`cacheReason`, `pprState`, `workflowRunId`, `workflowStepId`, `sessionId`,
`proxyEvents`, `functionEvents`, `clientUserAgent`, `requestSearchParams`,
`requestReferer`, `microfrontendsResponseReason`,
`microfrontendsMatchedPath`, `microfrontendsDefaultAppDeploymentId`,
`isPrefetchRequest`, `isVercelTrace`.

**`logs[]` item shape is `{level, message, messageTruncated}`**, taken from the
CLI's own mapping code. It was **not** observed populated: neither live project
had produced an error or fatal log line in any window probed, so every observed
row carried `logs: []`. Parse it defensively and treat a missing field as
absent, exactly as `docs/api-notes.md` already prescribes for Web Analytics
rows. This is the one shape in the design resting on the CLI source rather than
on observation, and it must be marked ASSUMPTION in the code.

### 2.4 `level` matches log lines, not responses

This is the single most important semantic in the whole design.

`level=info` returned **zero** rows on a project that returns 50 rows
unfiltered, because every one of those rows carried `logs: []`. The filter
matches rows whose `logs[]` contains an entry of that level. A request that
returned `500` without printing anything is invisible to `level=error`, and a
request that returned `200` while its handler logged a stack trace is invisible
to `statusCode=5xx`.

Neither filter alone answers "what is broken". That is why the `errors` preset
issues two calls and merges them (section 6).

### 2.5 `statusCode` validation

Verbatim from the API:

```
400 Validation error: statusCode must contain only comma-separated integers,
status code classes like 4xx or 5xx, or "None" at "statusCode"
```

Accepted, verified: `500`, `401`, `500,502`, `5xx`, `4xx,5xx`, `40x`,
`401,4xx`, `None`. Rejected, verified: `>=500`, `xxx`. `None` returns rows
with no status recorded (28 rows in a 6 hour window on the test project).

### 2.6 `level` and `source` are not validated server-side

`level=bogus` and `source=bogus` both return **`200` with zero rows**. A typo
therefore reads as "your site is fine", which is precisely the failure mode
SKILL.md already calls the most damaging one available. **Both vocabularies must
be validated client-side**, before the request is built, the way
`--granularity` and `--metric` already are.

`search` is free text: `search=/api/me` filtered to that path and
`search=error` returned zero rows. The `field:value` syntax the CLI help
advertises does **not** work here in general: `search=path:/api/me` returned
mixed paths (no filtering), and `search=level:error` and `search=method:POST`
returned zero. Do not document a query syntax; document it as free text.

### 2.7 Retention, from the live docs

<https://vercel.com/docs/runtime-logs>, read 2026-08-17:

| Plan | Retention |
| --- | --- |
| Hobby | 1 hour |
| Pro | 1 day |
| Pro with Observability Plus | 30 days |
| Enterprise | 3 days |
| Enterprise with Observability Plus | 30 days |

With Observability Plus, up to 14 consecutive days may be viewed within a
30 day window. Volume limits from the same page: each log output up to 256KB,
up to 1MB per request, at most **256 log lines per request**.

Retention drives two design choices: the logs surface defaults to a 1 hour
window (section 6), and an empty result over a window wider than an hour prints
the table above rather than implying health (section 9).

### 2.8 The two alternatives that do not work

Recorded so this is never re-litigated.

**The documented runtime-logs endpoint is a stream that never answers.**
`GET /v1/projects/{projectId}/deployments/{deploymentId}/runtime-logs` is in the
OpenAPI document, tagged `logs`, declared `application/stream+json`. Live
probes against a READY production deployment never received **response
headers** at all: three attempts (plain, `format=lines`, `follow=0`) each timed
out at 10 seconds, and an earlier attempt at 20 seconds. It is a live tail, not
a query, and a request/response client cannot use it.

**The metrics route is blocked by entitlement, not by shape.**
`POST /v2/observability/query` with `vercel.request.count` grouped by
`http_status` answers:

```
402 payment_required: Observability Plus is required to run this query for team
<team> and is available on Pro and Enterprise plans.
```

`GET /v2/observability/schema` returns 96 metrics for the same token, and
`vercel.request.count` does carry `http_status`, `error_code`, `route` and
`environment` dimensions, so the query is well formed and simply not paid for.
Request logs work on the same account without Observability Plus, which is what
makes them the right surface. This contrast belongs in SKILL.md: it stops an
agent reaching for `--metric vercel.request.count` when a user asks about
errors.

**Build logs do work, and are out of scope.**
`GET /v3/deployments/{idOrUrl}/events` returns a JSON array promptly
(`direction=backward`, `limit`, `since`, `until`, `statusCode`), carrying
`type: stdout|stderr|fatal|...` build events. Noted for a future change.

## 3. Architecture

### 3.1 Module layout

The existing layering is a stated rule in `CONTRIBUTING.md`: `http`, `odata`,
`timerange` and `render` know nothing about any API; each surface module owns
its own request building and response normalization and imports the generic
pieces. Surfaces import from `render`, never the reverse.

This design follows it exactly:

```
vercel_insights/
  logs.py     NEW. Request building, vocabulary validation, response
              normalization, merge and local aggregation for the logs surface.
  render.py   Gains the LogEntry / LogReport containers next to Row / Result,
              and the two log renderers next to render_overview / render_vitals.
  http.py     Gains one allowlist entry and a second base URL constant.
  presets.py  Gains three presets and a per-preset default window.
  timerange.py Gains the LOGS surface constant, its label, and to_unix_ms.
  cli.py      Gains the logs flags, the third arm of cross-surface
              enforcement, a logs request planner and a logs emitter.
  __init__.py Gains LOGS_BASE_URL, and the version becomes 1.1.0.
```

The log containers go in `render.py` rather than in `logs.py` because that is
where `Row` and `Result` already live, and because `render.py` must not import a
surface module. `logs.py` builds them, the same way `webanalytics.py` builds
`Result`.

`render.py` reaches roughly 1150 lines with this change. That is accepted for
now; if it grows again, the split to make is `reports.py` for the
overview/vitals/logs composite renderers, leaving `render.py` the grid, style,
JSON and CSV primitives.

### 3.2 The allowlist

One new entry, making six:

```python
OPERATIONS: dict[str, tuple[str, str]] = {
    ...
    "request_logs": ("GET", LOGS_BASE_URL + "/api/logs/request-logs"),
}
```

`LOGS_BASE_URL = "https://vercel.com"` in `__init__.py`, with a comment naming
why a second host exists at all.

It needs no change to the dispatcher: static URL with no placeholders, so
`url_is_allowed` requires an exact match, the method is still read from the
table, the token still travels only in the `Authorization` header, redirects
are still refused, and `--dry-run` renders it with no special casing.

Two existing invariants must be widened deliberately, not accidentally:

- `tests/test_security.py::test_every_allowlisted_url_is_on_the_vercel_api_host`
  asserts every URL starts with `https://api.vercel.com/`. It becomes an
  assertion against an explicit two-host set, so a third host is still a test
  failure.
- The prose "five-endpoint allowlist" becomes "six-endpoint allowlist" in
  SKILL.md, README.md and the module docstrings.
  `test_skill_manifest.py::test_the_documented_endpoint_count_matches_the_allowlist`
  already handles `six`, and
  `test_every_allowlisted_operation_is_documented` strips only the
  `api.vercel.com` prefix, so the SKILL.md table row for this operation must
  carry the **full URL** `https://vercel.com/api/logs/request-logs`. That is
  also the more honest way to write it, because the host is the notable part.

### 3.3 Scope resolution

`ownerId` is required, and the skill already knows how to find it: Speed
Insights needs the same value, and `cli.py::_resolve_project_record` reads it
once per run from `GET /v9/projects/{project}` as `accountId`, short-circuited
by `VERCEL_TEAM_ID` (a team is its own owner) or `VERCEL_OWNER_ID`. The logs
surface reuses that path unchanged: `needs_lookup` becomes true for a logs run
that lacks an owner, and additionally when the project is a name rather than an
id, because `projectId` here accepts a name but the header line should show what
was actually queried.

ASSUMPTION to mark in the code and in api-notes: a **project-scoped** token
probably fails here the way it fails on Speed Insights, since this call also
carries an `ownerId`. Only a team-scoped token was available to test with. The
existing `_explain_observability_404` style hint should be mirrored for a `403`
on this operation, pointing at token scope.

## 4. Data model

In `render.py`, beside `Row` and `Result`:

```python
@dataclass(frozen=True)
class LogLine:
    """One application log line attached to a request."""
    level: str            # error | warning | info | fatal, or whatever arrived
    message: str          # already sanitized
    truncated: bool = False

@dataclass(frozen=True)
class LogEntry:
    """One request, as the logs surface reports it."""
    request_id: str
    timestamp: datetime | None
    status: int | None
    method: str
    path: str
    route: str
    source: str           # from events[0].source, "static" when absent
    environment: str
    deployment_id: str
    duration_ms: float | None
    region: str
    error_code: str
    branch: str
    domain: str
    trace_id: str
    crashed: bool
    lines: tuple[LogLine, ...]
    raw: dict[str, Any]   # for --json, sanitized on the way in

    @property
    def worst_level(self) -> str | None: ...   # fatal > error > warning > info
    @property
    def headline(self) -> str: ...             # worst line's message, or ""
    @property
    def is_error(self) -> bool: ...            # 5xx, crashed, or error/fatal line

@dataclass(frozen=True)
class LogReport:
    """Everything one logs run produced, plus what it could not see."""
    entries: list[LogEntry]
    time_range: tuple[datetime, datetime]
    project_label: str
    preset: str
    filters: dict[str, str]        # what was actually sent, for the header
    truncated: bool                # a page boundary was hit
    pages_fetched: int
    requested_limit: int
```

Every string field is passed through `sanitize_label` on the way in, and every
log message through `sanitize_message`, at the one boundary in `logs.py` where
a payload becomes a `LogEntry`. Nothing downstream re-sanitizes, and nothing
downstream may skip it. This mirrors how `stringify_label` is the single
boundary today.

## 5. Flags

New, logs-surface only. Each is validated locally before any request:

| Flag | Values | Notes |
| --- | --- | --- |
| `--level` | `error`, `warning`, `info`, `fatal`, comma separated | Unknown value is a `ConfigError` naming the four, because the API answers 200 with zero rows for a typo. |
| `--status-code` | integers, `Nxx`, `None`, comma separated | Client-side regex mirroring the API's own rule, quoted in the error message. |
| `--source` | `serverless`, `edge-function`, `edge-middleware`, `static` | Same reasoning as `--level`. |
| `--method` | an HTTP method, upper-cased for the wire | |
| `--search` | free text | Help text says free text, not a query syntax (2.6). |
| `--request-id` | one id | |
| `--branch` | branch name | |
| `--deployment` | `dpl_...` | Pass-through; no lookup, so no extra allowlist entry. |
| `--expand` | flag | Print each full message under its row instead of truncating to the column. |

Reused unchanged: `--since`, `--until`, `--environment`, `--path`, `--route`,
`--project`, `--team`, `--team-slug`, `--owner-id`, `--token`, `--json`,
`--csv`, `--limit`, `--dry-run`, `--verbose`, `--timeout`, `--max-retries`,
`--no-color`.

`--path` and `--route` become query parameters rather than OData clauses on this
surface, and both are **exact match**, which the help text must say because
`--path` on Web Analytics is also exact but `--search` is the substring tool
here.

`--limit` means **rows** here, default 50, maximum 200. Web Analytics keeps its
own 1 to 100 group limit; the validation is per surface, so
`webanalytics.validate_limit` is untouched and `logs.validate_limit` is new.

### 5.1 Cross-surface enforcement

`cli.py::_reject_cross_surface_options` is currently a two-way check built on
`preset.is_speed`, with `SPEED_ONLY_OPTIONS` and `WEB_ONLY_OPTIONS`. It becomes
a three-way check driven by one table mapping each option to the set of surfaces
it is meaningful on, plus the reason it is not meaningful elsewhere. The
existing messages must not regress: every current rejection keeps its wording
and its exit code 2, and the tests that assert those messages stay green.

Rejected on a logs preset, each naming the alternative:

| Rejected | Message names |
| --- | --- |
| `--filter` | this surface takes no OData; use `--search`, `--path`, `--route`, `--status-code` |
| `--group-by`, `--granularity` | logs are rows, not buckets; use `error-summary` |
| `--dataset`, `--event-name`, `--event-property`, `--flag` | logs are neither dataset |
| `--country`, `--device`, `--browser`, `--os`, `--referrer`, `--utm-*` | the logs API collects no such dimension |
| every Speed Insights flag, `--all`, `--budget` | surface mismatch, existing wording |
| `--csv` on `error-summary` | three tables, one file; use `errors --csv` |

And the reverse: every new logs flag is rejected on a Web Analytics or Speed
Insights preset, naming `errors` or `logs` as the preset to use.

## 6. Presets

| Preset | Surface | Calls | Default `--since` | Default `--limit` |
| --- | --- | --- | --- | --- |
| `logs` | logs | 1 | `1h` | 50 |
| `errors` | logs | 2 | `1h` | 50 |
| `error-summary` | logs | 2 | `6h` | 200 |

`Preset` gains two optional fields: `default_since: str | None` and a row-limit
default, both `None` for every existing preset so the global `7d` default and
current limits are untouched. `DEFAULT_SINCE` stays `7d` for the other two
surfaces; a logs preset overrides it, and an explicit `--since` overrides the
preset as usual.

**`errors` issues two calls** and merges them:

- call A: `statusCode=5xx`
- call B: `level=error,fatal`

Section 2.4 is the whole reason. Passing `--level` or `--status-code` explicitly
collapses `errors` to a single call with the user's filter, which is the same
"an explicit flag overrides a preset value" rule the rest of the tool follows.
`--json` and `--csv` are allowed on `errors` because the merge still yields one
table.

**`error-summary`** runs the same two calls and then computes three tables
locally from the merged rows: by status code, by route, and by message. It is
the `overview` of this surface: multi-table, so `--csv` and `--group-by` are
rejected there exactly as they are on `overview`.

## 7. Paging, merging, ordering

One function in `logs.py`, driven by `LogReport.requested_limit`:

1. Fetch page 0. If fewer than 50 rows came back, or `hasMoreRows` is false, or
   the row budget is met, stop.
2. Otherwise fetch the next page, up to a hard cap of **4 pages** (200 rows) per
   call. The cap is a constant, not a magic number, and the reason is latency:
   at up to 6 seconds a page, 4 pages is already 24 seconds against a 30 second
   default timeout per request.
3. Normalize every row to a `LogEntry`, discarding nothing silently: a row that
   fails to normalize becomes an `ApiError` with code `invalid_response`, the
   way `speedinsights.normalize` already behaves.
4. For a two-call preset, concatenate both result sets, **deduplicate by
   `request_id`** (a 5xx that also logged an error appears in both), sort by
   timestamp descending, and truncate to the limit.
5. Set `truncated` when any call hit a page boundary or the merge dropped rows.

Sorting is done locally even though rows arrive newest first, so ordering is a
property of this client rather than an observation about a server.

Honesty requirement on the merge: when both calls fill their pages, the result
is "the most recent N 5xx plus the most recent N logged errors", not a true
global top N. The footer says so when `truncated` is set. It must not silently
read as complete.

## 8. Rendering

### 8.1 `errors` and `logs`

```console
$ vercel-insights errors --since 30m
Vercel request logs: dobri-web (errors, last 30m)
Range: 2026-08-17T10:36:00Z to 2026-08-17T11:06:00Z (UTC)
Counted as an error: a 5xx response, or a request that logged an error or fatal line.

time      level  status  method  route                  source      message
--------  -----  ------  ------  ---------------------  ----------  ----------------------------------
11:04:52  error     500  POST    /api/checkout          serverless  TypeError: Cannot read properties
11:03:19  error     500  POST    /api/checkout          serverless  TypeError: Cannot read properties
11:02:41  fatal     200  GET     /api/cron/sync         serverless  FATAL: connection pool exhausted
10:58:03  -         502  GET     /api/offerings/[slug]  serverless  (no log line: the response failed)

4 errors in 30 minutes: 2 x 500, 1 x 502, 1 fatal log line on a 200.
Most affected route: /api/checkout (2).
Add --expand for full messages, or --request-id to pull one request apart.
```

Column rules: `time` is `HH:MM:SS` UTC when the window is under 24 hours and
`MM-DD HH:MM:SS` beyond it. `level` shows the worst level among the request's
log lines, or `-` when it logged nothing. `message` is the worst line's message
truncated to the column with the existing ellipsis helper; `(no log line: the
response failed)` when there is none, because an empty cell there reads as a
rendering bug. `route` falls back to `path` when the route is empty.

`--expand` prints the full sanitized message, indented, under each row, and all
of a request's lines rather than only the worst.

`logs` prints the same table without the "counted as an error" line and with a
plain count in the footer.

### 8.2 `error-summary`

```console
$ vercel-insights error-summary --since 6h
Vercel request logs: dobri-web (error-summary, last 6h)
Range: 2026-08-17T05:06:00Z to 2026-08-17T11:06:00Z (UTC)

status  count  share
------  -----  ------
500        41   74.5%
502        12   21.8%
200         2    3.6%
------  -----  ------
TOTAL      55  100.0%

route                  count  worst status  first seen  last seen
---------------------  -----  ------------  ----------  ---------
/api/checkout             38           500  05:11:02    11:04:52
/api/offerings/[slug]     12           502  06:40:19    10:58:03
/api/cron/sync             5           500  05:30:00    09:30:00

message                                          count  first seen  last seen
-----------------------------------------------  -----  ----------  ---------
TypeError: Cannot read properties of undefined      38  05:11:02    11:04:52
FATAL: connection pool exhausted                     2  07:15:44    11:02:41
(no log line)                                       15  06:40:19    10:58:03

55 errors in 6 hours across 3 routes. Worst route: /api/checkout (38).
2 of them returned 200 and count as errors only because they logged a fatal line.
```

The status table groups by HTTP status alone, so a request that is an error only
because it logged an error or fatal line appears under its real status (the two
`200` rows above), and the footer says how many those are. Mixing a level into a
status column would read as though `fatal` were a status code.

Messages are grouped by **exact text**, truncated only for display. No
normalization of ids or numbers into patterns: clustering that guesses would
merge two different bugs into one row and is not worth the risk. `(no log line)`
is its own group.

### 8.3 Empty, and `--json` / `--csv`

Empty is a success, exit 0, one line naming what was asked, plus the retention
table when the window exceeds one hour (section 9).

`--json` emits `{"query": {...}, "entries": [...], "truncated": bool,
"pagesFetched": n}` where each entry is the full sanitized row, so nothing
probed in section 2.3 is thrown away by the tool. `--csv` emits the flat table
columns of 8.1.

## 9. Honesty rules

These are the reason this feature is worth building carefully; a wrong "no
errors" is worse than no feature.

1. **Empty over a long window prints retention.** Zero rows and a window wider
   than one hour appends: "Runtime log retention is 1 hour on Hobby, 1 day on
   Pro, 3 days on Enterprise, and 30 days with Observability Plus, so an empty
   result over a longer window may mean the logs have aged out rather than that
   nothing failed."
2. **4xx is excluded from `errors` on purpose**, and the docs say so with the
   reason: a 401 on `/api/me` is the application working. `--status-code 4xx`
   asks for them.
3. **`--level` only sees requests that logged.** Stated in `--help`, in
   SKILL.md, and in the `errors` header line.
4. **Truncation is always visible**, per section 7.
5. **Log text is hostile input.** These are the most attacker-influenceable
   strings the skill has ever printed: a request path, a user agent echoed into
   a log, a message containing an ANSI escape. Everything goes through the
   existing sanitizers at the normalization boundary, and `tests/test_untrusted_response.py`
   gains logs cases.
6. **Log bodies may contain the user's own secrets.** SKILL.md tells the agent
   not to forward log output to any external service, and to quote only the
   lines needed to answer the question. The existing `scrub_credentials` still
   redacts the Vercel token if it ever appears in one.

## 10. Errors and exit codes

Unchanged: `0` success including empty, `1` API or network failure with
Vercel's own message quoted, `2` configuration or usage error, `130`
interrupted. `3` stays exclusive to `--budget`, which is not offered here.

Two mapped explanations, in the style of the existing `_explain_*` helpers:

- `403` on `request_logs`: name token scope and the `ownerId` requirement, and
  point at <https://vercel.com/account/tokens> for an account or team scoped
  token.
- `400 Validation error: ...`: quote it verbatim; it names the field. Client-side
  validation should make this unreachable for the flags the tool builds, so if
  it appears, the request builder is wrong and the message should be believed.

## 11. Documentation changes

`SKILL.md` is the deliverable an agent actually reads, so it carries the most
weight:

- **Front-matter `description` rewritten** so OpenClaw routes an error question
  here at all. Current text names only traffic and speed. New text, which must
  stay under the 400 character cap that `test_the_description_stays_short_enough_to_read_in_a_list`
  enforces:

  > Reports a Vercel site's errors, traffic and speed: runtime error logs,
  > failing requests, page views, visitors, top pages, referrers, and Core Web
  > Vitals. Trigger on requests like "what errors did my site have in the last
  > 30 minutes", "why am I getting 500s", "show me the logs", "how is my
  > traffic this week", or "which pages are slowest". Read only.

- "Two surfaces, one command" becomes three, with the logs column added to the
  comparison table.
- A **Logs section** in the decision table:

  | The user says | Run |
  | --- | --- |
  | "any errors in the last 30 minutes", "what is broken", "is my site erroring" | `errors --since 30m` |
  | "am I returning 500s", "server errors today" | `errors --since 24h` |
  | "show me the logs", "recent requests" | `logs --since 15m` |
  | "what is failing most", "group the errors" | `error-summary --since 6h` |
  | "errors on /api/checkout" | `errors --path /api/checkout --since 1h` |
  | "find the request that logged ECONNRESET" | `logs --search ECONNRESET --since 1h` |
  | "everything about request X" | `logs --request-id X --expand` |
  | "warnings too" | `logs --level error,warning,fatal` |
  | "errors on my preview deploys" | `errors --environment preview` |

- A "Reading a logs answer" section carrying rules 1 to 6 of section 9.
- Gotchas: the six-endpoint allowlist and the second host, with the sentence
  that this one endpoint is CLI-verified rather than OpenAPI-documented and can
  change without notice; that request logs need no Observability Plus while
  metric-based error counts answer 402; that there is no live tail.
- The read-only section: six entries, and why a second host exists.

`docs/api-notes.md` gains section 2 of this spec as a third chapter.
`docs/cli-contract.md` gains the presets, flags and exit-code rows.
`README.md` gains a logs section with worked examples.
`examples/example_outputs.md` gains the three outputs from section 8.
`CONTRIBUTING.md` layout block gains `logs.py`.
`CHANGELOG.md` gains a 1.1.0 entry. Version bumps in `__init__.py`,
`pyproject.toml` and the SKILL.md front matter, which
`test_the_declared_version_matches_the_package` checks.

## 12. Non-goals

- **No live tail.** The streaming endpoint never returns headers (2.8), and a
  skill invocation is the wrong place to hold a socket open.
- **No build logs.** `/v3/deployments/{id}/events` works and is documented in
  2.8 for a later change.
- **No log drains**, no writes, no toggles.
- **No error budgets.** `--budget` and exit 3 stay Speed Insights only.
- **No message clustering** beyond exact grouping (8.2).

## 13. Testing

Offline only, as `CONTRIBUTING.md` requires: `tests/helpers.py::FakeSession`
serves canned payloads built from the real rows in 2.3.

New:

- `tests/test_logs.py`: request building (every parameter, exact serialization,
  ms timestamps), vocabulary validation for `--level`, `--status-code`,
  `--source`, defensive normalization (missing fields, `logs: []`, a row that is
  not an object, non-finite numbers), the paging loop and its 4 page cap, the
  two-call merge and its dedupe by request id, sort order, truncation flags.
- `tests/test_logs_cli.py`: the three presets end to end against a fake session,
  cross-surface rejection in both directions with the exact messages, per-preset
  default windows, `--limit` bounds, `--dry-run` output, `--json`, `--csv`,
  exit codes, the 403 explanation.
- `tests/test_logs_render.py`: table layout, the `-` level cell, the
  `(no log line: the response failed)` cell, `--expand`, the summary tables and
  their percentages, the empty-plus-retention line, the truncation footer.

Edited:

- `tests/test_security.py`: six operations, the two-host assertion, no token in
  URL or params for the new operation, redirect refusal, and that
  `request_logs` cannot be addressed with a crafted URL.
- `tests/test_untrusted_response.py`: an ANSI escape, a `\r`, a newline and a
  very long message in a log line, and a hostile `requestPath`.
- `tests/test_skill_manifest.py`: whatever the count and description changes
  require, with the existing assertions kept.

Green means: `pytest`, `ruff check .`, `mypy --strict vercel_insights tests`,
and both invocation forms still working.

## 14. Assumptions carried forward

Two, both to be marked ASSUMPTION in the code as the project already does:

1. `logs[]` items are `{level, message, messageTruncated}`, from the CLI source,
   never observed populated (2.3).
2. A project-scoped token probably cannot read this endpoint, by analogy with
   Speed Insights (3.3). Only a team-scoped token was available.
