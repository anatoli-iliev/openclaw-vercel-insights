# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-08-14

Initial release: a read-only command line client for the Vercel Web Analytics
API, packaged as an OpenClaw skill.

### Added

- `scripts/vercel_analytics.py`, a single-file CLI over the four Vercel Web
  Analytics query endpoints (`visits/count`, `visits/aggregate`, `events/count`,
  `events/aggregate`). Read-only: exactly one HTTP call site, and it is a GET.
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

[Unreleased]: https://github.com/anatoli-iliev/openclaw-vercel-analytics/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/anatoli-iliev/openclaw-vercel-analytics/releases/tag/v0.1.0
