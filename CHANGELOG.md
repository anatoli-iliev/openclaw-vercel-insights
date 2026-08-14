# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-08-14

Speed Insights arrives, and with it the project's scope grows from traffic to
traffic and speed. The skill, the repository and the module are renamed to
match, and the single script becomes a package.

### Changed

- **Renamed.** The skill is now `vercel-insights` (was `vercel-analytics`), the
  repository is `openclaw-vercel-insights` (was `openclaw-vercel-analytics`),
  and the module is `vercel_insights`. The old name described half of what the
  tool now does. Update any bookmark, clone URL or ClawHub install accordingly;
  this entry is the record of that rename.
- **Invocation.** `python3 scripts/vercel_analytics.py` is gone. Run
  `python3 -m vercel_insights` from the repository root, or
  `python3 /abs/path/to/vercel_insights/__main__.py` from anywhere: the entry
  point repairs `sys.path` before importing, so it works uninstalled. A
  `pip install -e .` additionally provides a `vercel-insights` console script.
- **Package split.** The single script became a package of focused modules:
  `timerange` (time parsing and granularity translation), `odata` (quoting and
  clause building), `http` (the operation allowlist, redaction and retries),
  `webanalytics` and `speedinsights` (one per API), `render` (every output
  format), `presets`, and `cli`. `http`, `odata`, `timerange` and `render` know
  nothing about either API, which is what let a second surface be added without
  touching the first.
- **The read-only claim is now "read-only against a three-endpoint allowlist"**,
  not "GET only". `http.py` holds one table mapping an operation key to a fixed
  method and URL, with exactly three entries: the Web Analytics query (GET), the
  observability query (POST) and the observability schema (GET). The dispatcher
  takes an operation key, never a method and never a host. One entry is a POST
  because Vercel exposes no GET equivalent for an observability query; the body
  carries the question and nothing is created or mutated. The `/speed-insights/toggle`
  and `/web/insights/toggle` endpoints, which genuinely write, are absent from
  the table and unreachable.
- `--granularity` now accepts both time vocabularies and translates per API, so
  `day` and `1d` mean the same thing. `week` and `year` remain Web Analytics
  only, and asking for either on Speed Insights is a configuration error naming
  what that surface supports.
- HTTP 408 joins 429 and the 5xx statuses as retryable. The observability query
  API documents it: a query can time out server-side, and that is worth another
  attempt.
- A dry run of a request with no query parameters no longer prints a bare
  trailing `?` on the encoded URL line.

### Added

- **Speed Insights support** through `POST /v2/observability/query`, the only
  way to read these metrics: Speed Insights has no dedicated query API. Ten
  queryable metrics, the five web vitals (`lcp`, `inp`, `cls`, `fcp`, `ttfb`)
  and the `*_count` metric giving the number of data points behind each one.
- Seven presets on the new surface: `vitals` (P75 of all five against their
  published targets, one query per metric composed into one table),
  `slowest-pages` and `fastest-pages` (routes ordered by P75 LCP),
  `vitals-by-country`, `vitals-by-device`, `vitals-trend`, and `data-points`.
- Speed Insights options: `--metric`, `--percentile {75,90,95,99}`,
  `--aggregation`, `--order-by {count,value}`, `--order {asc,desc}`,
  `--bucket-timezone`, `--all` (every project in the team), and `--data-points`.
- Value rendering per unit: milliseconds below one second stay milliseconds and
  above it become seconds with one decimal (`2.4 s`), and the layout shift score
  renders as a bare three-decimal number. Each value is shown against Vercel's
  published "good" target with a **two-tier** verdict, `meets target` or
  `over target`. Vercel publishes no boundary above the good threshold, and the
  dashboard's three colour bands describe a derived 0 to 100 score rather than a
  raw value, so a three-tier rating is deliberately not rendered.
- Grouped Speed Insights tables carry no totals row and no share-of-total
  column, because a percentile does not add up. `data-points` is the exception,
  since a sum of measurement counts does.
- Data point counts are reported alongside every value where the response
  carries one, with a legend explaining that a percentile over few data points
  is not comparable to one over many. Grouped queries order by count by default
  for the same reason.
- Asking for Real Experience Score by name is a configuration error that says it
  is not queryable through this API and points at the Speed Insights dashboard,
  rather than quietly substituting another metric.
- Filter shorthands now compile to the dimension spelling of whichever surface
  is active: `--device mobile` becomes `deviceType eq 'mobile'` on Web Analytics
  and `device_type eq 'mobile'` on Speed Insights. A shorthand the active
  surface has no dimension for is a configuration error naming the reason.
- Nine new validation rules, all enforced before any network call: `--dataset`
  with `--metric`, a dimension or shorthand used on the wrong surface (in both
  directions, each naming the other surface's spelling), an unsupported
  granularity per surface, `--all` with `--project`, a percentile outside the
  four Vercel computes, an unknown metric with a did-you-mean suggestion,
  ordering flags without a grouping, a bucket timezone at sub-daily granularity
  (a warning, since the API ignores it there), and any Speed Insights option
  used while the Web Analytics surface is active.
- Defensive response parsing for the observability surface. The published
  OpenAPI document declares the 200 body as a bare object, so the normalizer
  probes for a wrapped container, a single metric value, a rollup keyed by
  dimension value, a list of grouped rows, and a list of time buckets with rows
  nested inside them, and reports a clear `invalid_response` error naming the
  shape it found, never its content, when none of those fits. No `KeyError` ever
  reaches the user.

### Documentation

- `SKILL.md` describes both surfaces and when to use each, extends the
  phrasing-to-command decision table with performance questions, states the
  read-only guarantee in its allowlist form with the POST explained, and covers
  how to read a percentile, a target and a data point count without
  overclaiming.
- `README.md` gains a Core Web Vitals section of captured output, the new
  presets and flags, the allowlist framing of the security section, and the two
  facts most likely to be assumed wrongly: Speed Insights needs no Observability
  Plus, and Real Experience Score is dashboard-only.
- Every sample block in the documentation is captured from a real run of the
  tool driven through `main()` against a stub session. None of it is
  hand-written to look like terminal output.

## [0.1.0] - 2026-08-14

Initial release: a read-only command line client for the Vercel Web Analytics
API, packaged as an OpenClaw skill.

### Added

- A single-file CLI over the four Vercel Web Analytics query endpoints
  (`visits/count`, `visits/aggregate`, `events/count`, `events/aggregate`).
  Read-only: exactly one HTTP call site, and it is a GET.
- Twelve presets: `overview` (the default, three calls composed into one
  report), `trend`, `top-pages`, `top-routes`, `referrers`, `countries`,
  `devices`, `browsers`, `operating-systems`, `campaigns`, `events`, and
  `total`. `--list-presets` prints the table without touching the network.
- Flexible grouping with `--group-by` (up to two dimensions, at most one time
  bucket), `--granularity`, and `--event-property` for a custom event property.
  Every grouped dimension gets its own column in the table and in `--csv`, named
  exactly as it was requested, and its own entry in the per-row `groups` object
  in `--json`.
- Filter shorthands for path, route, country, device, browser, operating system,
  referrer, UTM source, medium and campaign, event name, feature flags and
  environment, plus `--filter` for raw OData. Comma-separated values become an
  `in (...)` set. Only operators the API documents are emitted.
- Time parsing for relative offsets (`30m`, `24h`, `7d`, `4w`), `now`, `today`,
  `yesterday`, ISO dates and datetimes, and Unix milliseconds, all normalized to
  UTC.
- Three output formats: an aligned text table with share-of-total percentages
  and a totals row, `--json` with the untouched API payload preserved under
  `raw`, and `--csv` written through `csv.writer`. The `Others` overflow bucket
  is labelled and footnoted wherever it appears, including in a grouping that
  carries it on the time bucket rather than on a label.
- `--dry-run`, which prints the exact request with the credential redacted,
  constructs no HTTP session, sends nothing, and works with no token configured.
- Retries with backoff for 429 and 5xx responses and network failures, honouring
  `Retry-After` and the `error.limit.resetMs` / `reset` fields, with injectable
  `sleep` and `jitter` so behaviour is deterministic under test.
- Validation of every configuration rule before any network call, with messages
  that name the offending value and the fix, and a documented exit code scheme:
  0 success (an empty result included), 1 API or network failure, 2
  configuration or usage error, 130 interrupted. Covered here: the dimension
  names and their two dimension maximum, `--limit` bounds, a finite positive
  `--timeout`, Unix millisecond values outside the representable date range,
  JSON dimension keys (`flags/<name>`, `eventData/<property>`) against the
  OData key grammar, and the mutually exclusive flag pairs.
- A 2xx response whose top level `data` is not the shape its endpoint must
  return is reported as an error rather than reinterpreted as a different kind
  of result. Row parsing itself stays permissive, as the API notes require.
- A stderr warning when `--since` predates the longest guaranteed reporting
  window of 24 months, rather than blocking the query.
- Documentation: `SKILL.md` with a phrasing-to-command decision table,
  `README.md` with setup and sample output captured from real runs,
  `.env.example` with every variable the script reads, `CONTRIBUTING.md` with
  the virtualenv and check commands, `docs/api-notes.md` with the verified API
  facts, and `docs/cli-contract.md` with the authoritative interface.

### Security

- The access token is read from the environment and placed only in the
  `Authorization` header. It never appears in a URL, a query parameter, a log
  line, an exception message, or any rendered output; every rendering of headers
  goes through `redact_headers`, including the `repr` of a prepared request.
- A token that could not safely become a header value (a newline, any other
  control or non-ASCII character, a leading or trailing space) is rejected up
  front, and the message reports the length, position and character class only,
  never the value. Any message on its way into an error is additionally scrubbed
  of the credential, so a third party exception that quotes a header cannot leak
  it.
- No write path exists: no verb other than GET is reachable, and no request body
  is ever built.
- No `eval`, no `exec`, no `subprocess`, and no filesystem writes.

[Unreleased]: https://github.com/anatoli-iliev/openclaw-vercel-insights/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/anatoli-iliev/openclaw-vercel-insights/releases/tag/v0.2.0
[0.1.0]: https://github.com/anatoli-iliev/openclaw-vercel-insights/releases/tag/v0.1.0
