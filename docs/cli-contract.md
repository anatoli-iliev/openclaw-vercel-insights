# CLI and module contract

Authoritative interface for the `vercel-insights` skill. Tests, documentation and
examples are written against it. Read `docs/api-notes.md` first: it holds the
verified facts for both APIs this contract is built on.

Target: Python 3.10+. Runtime dependency: `requests`. Everything else is stdlib.

## Package layout

The tool is a package at the repository root, not a single script. It covers two
different Vercel APIs with different request shapes, so one file no longer earns
its keep.

```
vercel_insights/
  __init__.py        VERSION, exceptions, shared constants
  __main__.py        entry point, path-robust so it runs from anywhere
  timerange.py       time parsing, range resolution, granularity translation
  odata.py           OData quoting, clause building, JSON dimension keys
  http.py            operation allowlist, request prep, redaction, retries
  webanalytics.py    Web Analytics request building and response normalization
  speedinsights.py   Speed Insights request building and response normalization
  render.py          table, JSON, CSV, overview and vitals renderers
  presets.py         the preset table
  cli.py             argument parsing and main()
```

Both of these must work:

```bash
python3 -m vercel_insights --help              # from the repository root
python3 /abs/path/vercel_insights/__main__.py  # from anywhere
```

`__main__.py` puts the package's parent directory on `sys.path` before importing,
so the second form works without installation. `pip install -e .` additionally
provides a `vercel-insights` console script.

## Two surfaces, one CLI

| | Web Analytics | Speed Insights |
| --- | --- | --- |
| Endpoints | `GET /v1/query/web-analytics/{visits,events}/{count,aggregate}` | `POST /v2/observability/query`, `GET /v2/observability/schema[/{metricId}]` |
| Selected by | `--dataset visits\|events` | `--metric lcp\|inp\|cls\|fcp\|ttfb` |
| Dimension case | camelCase (`requestPath`) | snake_case (`request_path`) |
| Time buckets | `by=day` | `granularity: 1d` |
| Metrics | `pageviews`/`visitors`, `count`/`visitors` | one value per metric, plus `*_count` data points |

A preset determines which surface is used. `--dataset` and `--metric` are
mutually exclusive: passing both is a config error naming the conflict.

## Presets

| Preset | Surface | Query | Default limit |
| --- | --- | --- | --- |
| `overview` (default) | web analytics | 3 aggregate calls: `day`, `requestPath`, `referrerHostname` | 5 |
| `trend` | web analytics | aggregate by `day` | 100 |
| `top-pages` | web analytics | aggregate by `requestPath` | 10 |
| `top-routes` | web analytics | aggregate by `route` | 10 |
| `referrers` | web analytics | aggregate by `referrerHostname` | 10 |
| `countries` | web analytics | aggregate by `country` | 10 |
| `devices` | web analytics | aggregate by `deviceType` | 10 |
| `browsers` | web analytics | aggregate by `browserName` | 10 |
| `operating-systems` | web analytics | aggregate by `osName` | 10 |
| `campaigns` | web analytics | aggregate by `utmCampaign` | 10 |
| `events` | web analytics | aggregate by `eventName` (+ `eventData/<p>`) | 10 |
| `total` | web analytics | count | n/a |
| `vitals` | speed insights | 5 queries, P75 of each metric, ungrouped | n/a |
| `slowest-pages` | speed insights | P75 `lcp_ms` by `route`, `orderBy value`, `desc` | 10 |
| `fastest-pages` | speed insights | P75 `lcp_ms` by `route`, `orderBy value`, `asc` | 10 |
| `vitals-by-country` | speed insights | P75 of `--metric` by `country` | 10 |
| `vitals-by-device` | speed insights | P75 of `--metric` by `device_type` | 10 |
| `vitals-trend` | speed insights | P75 of `--metric` over time, `granularity` default `1d` | n/a |
| `data-points` | speed insights | `sum` of `<metric>_count` by `route` | 10 |

`vitals` is the Speed Insights counterpart of `overview`: it issues one query per
metric because the API returns one metric per request. Like `overview`, it
rejects `--group-by`, `--csv` and `--metric` with a message naming the preset to
use instead.

`--list-presets` prints this table and exits 0 without touching the network.

## Options

Configuration is unchanged: `--token`/`VERCEL_TOKEN`, `--project`/`VERCEL_PROJECT_ID`,
`--team`/`VERCEL_TEAM_ID`, `--team-slug`/`VERCEL_TEAM_SLUG`.

### Speed Insights options

| Flag | Default | Notes |
| --- | --- | --- |
| `--metric lcp\|inp\|cls\|fcp\|ttfb` | preset | Selects the Speed Insights surface. |
| `--percentile 75\|90\|95\|99` | `75` | Sugar for `--aggregation p75` and friends. |
| `--aggregation NAME` | metric default | Raw passthrough, for example `sum`, `p90`, `max`. |
| `--order-by count\|value` | `count` | Grouped results only. |
| `--order asc\|desc` | `desc` | Grouped results only. |
| `--bucket-timezone IANA` | none | Aligns `1d`/`1mo` buckets only. |
| `--all` | off | Query every project in the team. Mutually exclusive with `--project`. |
| `--data-points` | off | Query the `*_count` metric instead of the value metric. |

### Shared options

`--group-by` (repeatable), `--granularity`, `--since`, `--until`, `--limit`,
`--filter` (repeatable), `--json`, `--csv`, `--dry-run`, `--timeout`,
`--max-retries`, `--no-color`, `--verbose`, `--version`, `--list-presets`.

Filter shorthands compile to the correct dimension spelling for the active
surface: `--path` becomes `requestPath eq '...'` on Web Analytics and
`request_path eq '...'` on Speed Insights. Shorthands valid on both:
`--path`, `--route`, `--country`, `--device`, `--environment`. Shorthands that
exist only on Web Analytics (`--browser`, `--os`, `--referrer`, the UTM flags,
`--event-name`, `--flag`, `--event-property`) are a config error when the Speed
Insights surface is active, and the message names the reason.

### Granularity

`--granularity` accepts both vocabularies and translates per surface:

| Accepted input | Web Analytics | Speed Insights |
| --- | --- | --- |
| `hour`, `1h` | `hour` | `1h` |
| `day`, `1d` | `day` | `1d` |
| `week` | `week` | config error, no equivalent |
| `month`, `1mo` | `month` | `1mo` |
| `year` | `year` | config error, no equivalent |

An unsupported combination is rejected before any network call, and the error
names both the granularity and the surface.

## Validation rules, all enforced before any network call

Rules 1 to 13 from the previous contract still apply (missing project, missing
token unless `--dry-run`, `--team` with `--team-slug`, more than 2 grouping
dimensions, more than one time granularity, unknown dimension, events-only
dimension on visits, `--limit` out of bounds, `--environment preview` on a count
query, `--json` with `--csv`, `--since` not before `--until`, reporting-window
warning, `--flag` without `=`). Added:

14. `--dataset` together with `--metric`: config error naming the conflict.
15. A Web-Analytics-only shorthand or grouping dimension used on the Speed Insights surface, and the reverse.
16. `--granularity week` or `year` on Speed Insights: config error listing what that surface supports.
17. `--all` together with `--project`: config error.
18. `--percentile` outside 75, 90, 95, 99: config error listing the four.
19. `--metric` with an unknown name: config error listing the five, with a did-you-mean suggestion.
20. `--order-by` or `--order` without a grouping: config error explaining they apply to grouped results only.
21. `--bucket-timezone` with a sub-daily granularity: warning on stderr, not an error, since the API ignores it there.
22. Any Speed Insights option used while the Web Analytics surface is active: config error.

Every message names the offending value and the fix. No traceback reaches the user.

## Exit codes

0 success including empty results, 1 API error, 2 configuration error, 130 interrupted.

## Security invariants

Restated for two surfaces. These are testable properties.

1. **Operation allowlist.** `http.py` holds one module-level table mapping each allowed operation to a fixed `(method, url_template)` pair. There are exactly three entries: the Web Analytics query (GET), the observability query (POST), and the observability schema (GET). The dispatcher takes an operation key, never a method or a host. No user input can select, extend or override an entry.
2. The only HTTP calls in the package are `session.get` and `session.post`, each appearing exactly once, both inside that dispatcher.
3. The token appears only in the `Authorization` header: never in a URL, query parameter, request body, log line, exception message, `__repr__`, or formatter output. It is validated at config time as header-safe and scrubbed from every error path.
4. `--dry-run` constructs no session and sends nothing, and succeeds with no token present. For a POST operation it prints the full JSON body it would have sent.
5. `redact_headers` is applied everywhere headers are rendered.
6. No `eval`, no `exec`, no `subprocess`, no filesystem writes.

The project's public claim changes from "GET-only" to "read-only against a
five-endpoint allowlist". Documentation must state why one endpoint is POST:
Vercel exposes no GET equivalent for observability queries, and a query body is
still a read.

## Speed Insights rendering

`Result` gains what the renderer needs to interpret a value: the metric id, its
unit (`ms` or a unitless score), and the number of data points when available.

- Millisecond values render as milliseconds under 1000 and as seconds with one decimal above, for example `1.4 s`.
- CLS renders as a bare number with three decimals.
- The `vitals` preset prints one row per metric: metric name, P75 value, Vercel's published target, and whether the value meets it.
- Targets come from `docs/api-notes.md`: LCP 2500 ms, INP 200 ms, CLS 0.1, FCP 1800 ms, TTFB 800 ms. Render a two-tier verdict, meets target or over target. **Do not render a three-tier good / needs improvement / poor scale**: Vercel publishes only the good target, and the dashboard's three colour bands apply to derived 0-100 scores, not to raw values.
- Lower is better for all five metrics. Say so in the output legend so a reader does not misread an ordering.
- When a data point count is available, show it, and note that a percentile over few data points is not comparable to one over many.
- Real Experience Score is not queryable. If a user asks for it by name, fail with a config error that says so and points at the dashboard, rather than silently substituting another metric.

## Module surface

Exceptions and constants live in `__init__.py`: `ConfigError`, `ApiError`,
`RateLimitError`, `VERSION`, `BASE_URL`.

| Module | Public surface |
| --- | --- |
| `timerange` | `parse_time_value`, `resolve_range`, `to_api_timestamp`, `normalize_granularity(value, surface)` |
| `odata` | `quote_odata`, `build_clause`, `combine_filters`, `json_dimension`, `validate_key_segments` |
| `http` | `OPERATIONS`, `PreparedRequest`, `redact_headers`, `format_dry_run`, `retry_delay`, `execute`, `scrub_credentials` |
| `webanalytics` | `VISIT_DIMENSIONS`, `EVENT_DIMENSIONS`, `select_endpoint`, `validate_group_by`, `build_request`, `normalize` |
| `speedinsights` | `METRICS`, `TARGETS`, `SPEED_DIMENSIONS`, `validate_metric`, `build_request`, `normalize` |
| `render` | `Row`, `Result`, `format_table`, `format_json`, `format_csv`, `render_overview`, `render_vitals`, `verdict` |
| `presets` | `PRESETS`, `Preset`, `format_presets` |
| `cli` | `build_parser`, `main` |

`execute` keeps its injected `session`, `sleep` and `jitter` callables so retry
behavior stays deterministic under test. `retry_delay` stays pure. Retryable
statuses now include **408**, which the observability API documents and Web
Analytics does not.

## Output expectations

Unchanged for Web Analytics: grouped tables carry one column per grouped
dimension, a share-of-total percent for the primary metric, a totals row, and a
labelled `Others` bucket with its explanatory note. Empty results print one
explanatory line and exit 0. JSON carries `query`, `range`, `rows`, `totals` and
the untouched payload under `raw`. CSV is written with `csv.writer`.

Speed Insights output follows the same conventions, with the value column
formatted per its unit and, for `vitals`, the target and verdict columns
described above.
