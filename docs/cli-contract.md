# CLI and module contract

This is the authoritative interface for `scripts/vercel_analytics.py`. Tests,
documentation, and examples are all written against it. Read `docs/api-notes.md`
first for the API facts this contract is built on.

Target: Python 3.10+. Runtime dependency: `requests`. Everything else is stdlib.

## Invocation

```
python3 scripts/vercel_analytics.py [PRESET] [OPTIONS]
```

`PRESET` is an optional positional argument. With no arguments at all, the script
runs the `overview` preset for the last 7 days.

## Presets

Each preset is a named bundle of defaults. Any explicit flag overrides the preset.

| Preset | Dataset | Endpoint | Grouping | Default limit |
| --- | --- | --- | --- | --- |
| `overview` (default) | visits | 3 aggregate calls | `day`, then `requestPath`, then `referrerHostname` | 5 for the two tables |
| `trend` | visits | aggregate | `day` (override with `--granularity`) | n/a |
| `top-pages` | visits | aggregate | `requestPath` | 10 |
| `top-routes` | visits | aggregate | `route` | 10 |
| `referrers` | visits | aggregate | `referrerHostname` | 10 |
| `countries` | visits | aggregate | `country` | 10 |
| `devices` | visits | aggregate | `deviceType` | 10 |
| `browsers` | visits | aggregate | `browserName` | 10 |
| `operating-systems` | visits | aggregate | `osName` | 10 |
| `campaigns` | visits | aggregate | `utmCampaign` | 10 |
| `events` | events | aggregate | `eventName`, plus `eventData/<p>` when `--event-property` is given | 10 |
| `total` | visits | count | none | n/a |

`overview` is the only preset that issues more than one request. It exists because
the API cannot return ungrouped totals and grouped rows in a single call.

`--list-presets` prints this table and exits 0 without touching the network.

## Options

Configuration:

| Flag | Env fallback | Default | Notes |
| --- | --- | --- | --- |
| `--token` | `VERCEL_TOKEN` | none | Required for real requests, not for `--dry-run`. |
| `--project` | `VERCEL_PROJECT_ID` | none | Required. Project ID or name. |
| `--team` | `VERCEL_TEAM_ID` | none | Optional. Mutually exclusive with `--team-slug`. |
| `--team-slug` | `VERCEL_TEAM_SLUG` | none | Optional. Sent as `slug`. |

Query shape:

| Flag | Default | Notes |
| --- | --- | --- |
| `--dataset {visits,events}` | `visits` | Preset may set it. |
| `--group-by DIM` / `--dimension DIM` | preset | Repeatable. Maximum 2 total. |
| `--granularity {hour,day,week,month,year}` | none | Sugar that appends a time dimension to the grouping. |
| `--since VALUE` | `7d` | See time formats below. |
| `--until VALUE` | `now` | See time formats below. |
| `--limit N` | `10` | Integer 1..100. |

Filter shorthands. Each builds one OData clause; all clauses are joined with
`and`. A comma-separated value becomes an `in (...)` clause.

| Flag | Clause |
| --- | --- |
| `--path VALUE` | `requestPath eq 'VALUE'` |
| `--route VALUE` | `route eq 'VALUE'` |
| `--country VALUE` | `country eq 'VALUE'` |
| `--device VALUE` | `deviceType eq 'VALUE'` |
| `--browser VALUE` | `browserName eq 'VALUE'` |
| `--os VALUE` | `osName eq 'VALUE'` |
| `--referrer VALUE` | `referrerHostname eq 'VALUE'` |
| `--utm-source VALUE` | `utmSource eq 'VALUE'` |
| `--utm-medium VALUE` | `utmMedium eq 'VALUE'` |
| `--utm-campaign VALUE` | `utmCampaign eq 'VALUE'` |
| `--event-name VALUE` | `eventName eq 'VALUE'` (events dataset only) |
| `--flag NAME=VALUE` | `flags/NAME eq 'VALUE'`, repeatable |
| `--environment {production,preview}` | `environment eq 'VALUE'` |
| `--filter ODATA` | Raw, repeatable, appended verbatim |
| `--event-property NAME` | Not a filter: adds `eventData/NAME` to the grouping |

Output and behavior:

| Flag | Default | Notes |
| --- | --- | --- |
| `--json` | off | Machine-readable. Mutually exclusive with `--csv`. |
| `--csv` | off | Mutually exclusive with `--json`. |
| `--dry-run` | off | Print the request, send nothing. Works with no token. |
| `--timeout SECONDS` | `30.0` | Applied to every request. |
| `--max-retries N` | `3` | Retries after the first attempt. `0` disables. |
| `--no-color` | auto | Also honors `NO_COLOR` and non-TTY stdout. |
| `--verbose` | off | Diagnostics to stderr. Never prints the token. |
| `--list-presets` | | Print presets, exit 0. |
| `--version` | | Print version, exit 0. |

## Time formats

`--since` and `--until` accept:

- Relative offsets: `30m`, `24h`, `7d`, `4w` (minutes, hours, days, weeks). Interpreted as "ago".
- `now`, `today` (UTC midnight today), `yesterday` (UTC midnight yesterday).
- ISO date: `2026-08-01`.
- ISO datetime: `2026-08-01T12:00:00Z` or with a numeric offset.
- Unix milliseconds: a bare integer of 11 or more digits.

Both are normalized to UTC and sent as ISO-8601 with a `Z` suffix. `since` must be
strictly earlier than `until`, otherwise it is a config error.

## Validation rules, all enforced before any network call

1. Missing project: config error naming `--project` and `VERCEL_PROJECT_ID`.
2. Missing token, unless `--dry-run`: config error naming `--token` and `VERCEL_TOKEN`, with a pointer to the token-creation docs.
3. `--team` together with `--team-slug`: config error.
4. More than 2 grouping dimensions: config error stating the API maximum is 2.
5. More than one time granularity in the grouping: config error listing the granularities.
6. Unknown grouping dimension for the dataset: config error listing valid dimensions for that dataset.
7. `eventData/...` grouping or `--event-name` on the `visits` dataset: config error pointing at `--dataset events`.
8. `--limit` outside 1..100: config error stating the API bounds and that overflow rolls into `Others`.
9. `--environment preview` on a count query: config error explaining count is production-only and suggesting `--group-by day`.
10. `--json` with `--csv`: config error.
11. `--since` not strictly before `--until`: config error.
12. `--since` older than 24 months: warning on stderr about the reporting window, not an error.
13. `--flag` without `=`: config error showing the `NAME=VALUE` form.

Every message names the offending value and the fix. No stack traces reach the
user for any of these.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Success, including an empty result set. |
| 1 | API returned an error, or the network failed after retries. |
| 2 | Configuration or usage error. |
| 130 | Interrupted. |

## Module surface

These names are public within the module and are what the tests import.

Exceptions: `ConfigError`, `ApiError` (carries `status`, `code`, `message`),
`RateLimitError(ApiError)`.

Constants: `BASE_URL`, `VERSION`, `TIME_GRANULARITIES`, `VISIT_DIMENSIONS`,
`EVENT_DIMENSIONS`, `JSON_DIMENSIONS`, `MIN_LIMIT`, `MAX_LIMIT`, `MAX_GROUP_BY`,
`RETRYABLE_STATUSES`, `PRESETS`.

Dataclasses:

- `PreparedRequest`: `method`, `url`, `params` (a list of `(key, value)` pairs, ordered), `headers`
- `Row`: `key` (display label, `None` for a count result), `metrics` (dict of name to number), `timestamp` (optional)
- `Result`: `rows`, `is_count`, `dataset`, `group_by`, `query` (the echoed `query` block), `metric_names`

Functions:

| Name | Responsibility |
| --- | --- |
| `parse_time_value(value, now)` | One `--since`/`--until` token to an aware UTC datetime. |
| `resolve_range(since, until, now)` | Both tokens, with ordering validation. |
| `to_api_timestamp(dt)` | Aware datetime to the ISO-8601 `Z` string sent to the API. |
| `quote_odata(value)` | Wrap in single quotes, doubling any embedded single quote. |
| `build_clause(dimension, value)` | One `eq` clause, or an `in (...)` clause for comma-separated values. |
| `combine_filters(clauses)` | Join with `and`, parenthesizing any clause containing a top-level `or`. Returns `None` when empty. |
| `validate_dimension(dimension, dataset)` | Validate one grouping dimension, including JSON dimension keys and their quoting. |
| `validate_group_by(dimensions, dataset)` | Apply the count and granularity rules. |
| `select_endpoint(group_by)` | `"aggregate"` when grouping is present, else `"count"`. |
| `build_request(...)` | Produce a `PreparedRequest`. Pure; performs no I/O. |
| `redact_headers(headers)` | Replace the bearer credential with a fixed placeholder. |
| `format_dry_run(request)` | Human-readable request dump with the token redacted. |
| `retry_delay(attempt, response, body, now)` | `Retry-After`, else `error.limit.resetMs`/`reset`, else exponential backoff with jitter. |
| `execute(request, session, sleep, jitter, max_retries, timeout)` | Perform the GET with retries. Returns parsed JSON. |
| `normalize(payload, dataset, group_by)` | Response JSON to a `Result`, including the JSON-dimension key remap. |
| `format_table(result, ...)` | Aligned table with a totals row and share percentages. |
| `format_json(result, payload)` | JSON output. |
| `format_csv(result)` | CSV output. |
| `render_overview(results, ...)` | Compose the three `overview` results into one report. |
| `build_parser()` | The `argparse.ArgumentParser`. |
| `main(argv, env)` | Entry point returning an exit code. |

`execute` takes injected `session`, `sleep`, and `jitter` callables so retry
behavior is deterministic under test. `retry_delay` is pure.

## Security invariants

These are testable properties, not aspirations.

1. Exactly one HTTP call site in the module, and it is `session.get`. There is no code path that can issue any other verb.
2. The token appears only in the `Authorization` header. It is never placed in a URL, query parameter, log line, exception message, or any formatter output.
3. `--dry-run` never constructs a session and never sends a request, and succeeds with no token in the environment.
4. `redact_headers` is applied to every rendering of headers, including verbose diagnostics and error paths.
5. No `eval`, no `exec`, no `subprocess`, no filesystem writes.

## Output expectations

Table output for a grouped query shows the group label, each metric column right
aligned, and a share-of-total percentage for the primary metric, followed by a
totals row. A row returned as `Others` is labeled as such and annotated so users
understand it is the limit overflow bucket, not a real group value.

Count output shows the metrics as a small labeled block, plus the resolved date
range.

Empty results print a single explanatory line naming the resolved range and the
active filter, and exit 0. They never print an empty table or a traceback.

JSON output is an object with `query`, `range`, `rows`, and `totals`, plus the
untouched API payload under `raw`.

CSV output writes a header row of the group column and metric columns, then one
row per group, using `csv.writer` so quoting is correct.
