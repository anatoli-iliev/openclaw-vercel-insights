# vercel-analytics

Your Vercel Web Analytics, answered in one command line.

```console
$ vercel_analytics.py top-pages --since 30d --country US
```

## Why not just open the dashboard

Because a dashboard answers one question at a time, and only for the person
looking at it.

- **One line, one answer.** No date picker, no tab switching, no waiting for a
  chart to animate. `trend --since 4w --granularity week` is the whole
  interaction.
- **Scriptable.** Put it in a cron job, a CI step, or a Makefile. Exit codes are
  meaningful: 0 for success (an empty result included), 1 for an API failure,
  2 for a bad command.
- **Pipeable.** `--json` feeds `jq`, `--csv` feeds a spreadsheet or `duckdb`. The
  raw API payload is preserved under `raw` in the JSON output, so nothing is
  lost in translation.
- **Diffable.** Yesterday's CSV against today's CSV is a real answer to "what
  changed". Two screenshots are not.
- **Agent-native.** It ships as an OpenClaw skill, so "how did the blog do this
  week" inside a conversation becomes a real query with a real table, not a
  guess.
- **Safe by construction.** Read-only, GET-only, and the token never leaves the
  `Authorization` header. See [Security and permissions](#security-and-permissions).

## Install

From ClawHub:

```bash
clawhub install vercel-analytics
```

Or clone it and run the script directly, no packaging step:

```bash
git clone https://github.com/anatoli-iliev/openclaw-vercel-analytics.git
cd openclaw-vercel-analytics
python3 -m venv .venv
.venv/bin/python -m pip install requests   # the only runtime dependency
.venv/bin/python scripts/vercel_analytics.py --help
```

The virtualenv is not ceremony. Debian 12+, Ubuntu 23.04+, Fedora and Homebrew
Python all mark the system interpreter as externally managed (PEP 668), so a
bare `python3 -m pip install requests` there stops with
`error: externally-managed-environment` before installing anything.

Two alternatives if you would rather not keep a `.venv` in the checkout:
`python3 -m pip install --user requests`, on platforms that still permit a user
install, or your distribution's own package (`apt install python3-requests`,
`dnf install python3-requests`), which adds it to the system interpreter through
the package manager rather than around it. `pipx` is worth knowing about but is
not the tool for this step: it installs applications that ship console scripts,
and `requests` is a library. Reach for it when you want a packaged CLI in its
own isolated environment.

Already have `requests` importable? Then `python3 scripts/vercel_analytics.py`
works as is: the script is a single file with no packaging step of its own.

Python 3.10 or newer. `requests` is the only thing outside the standard library.
`CONTRIBUTING.md` uses the same virtualenv flow, plus the test and lint tools.

## 60-second setup

**1. Create a Vercel access token** at
<https://vercel.com/account/tokens>. Read scope is enough; this tool never
writes. Copy it, Vercel shows it once.

**2. Make sure Web Analytics is enabled** on the project. It is a per-project
switch in the Vercel dashboard plus the `@vercel/analytics` package in the app:
<https://vercel.com/docs/analytics/quickstart>. Data only exists from the moment
it is turned on.

**3. Find the project ID.** Vercel dashboard, pick the project, Settings, then
General: the field is "Project ID" and looks like `prj_XXXXXXXXXXXXXXXX`. The
project *name* works just as well anywhere the ID does.

**4. Export the environment variables:**

```bash
export VERCEL_TOKEN="vercel_tok_xxxxxxxxxxxxxxxxxxxxxxxx"
export VERCEL_PROJECT_ID="prj_XXXXXXXXXXXXXXXX"
# export VERCEL_TEAM_ID="team_XXXXXXXXXXXXXXXX"   # team-owned projects only
```

Copy `.env.example` if you prefer keeping them in a file; the two team
variables are commented out there for the same reason. On a personal account
leave `VERCEL_TEAM_ID` unset: any value you give it is sent verbatim as the
`teamId` query parameter, placeholder or not.

**5. Check it without spending a request:**

```bash
.venv/bin/python scripts/vercel_analytics.py --dry-run
```

That prints the request and sends nothing. It works even before the token is
set, as long as a project is configured.

## Examples

> Every block below was captured verbatim from a real run of the tool, driven
> against a stub API session, so the layout, the column names, the percentages
> and the footnotes are exactly what you get. Only the traffic numbers, the
> project name and the clock are invented. `vercel_analytics.py` is shorthand for
> `.venv/bin/python scripts/vercel_analytics.py` (or `python3 scripts/vercel_analytics.py`
> wherever `requests` is already importable).

### The 7-day overview (this is the default)

```console
$ vercel_analytics.py
Vercel Web Analytics: prj_demo
Range: 2026-08-07T09:00:00Z to 2026-08-14T09:00:00Z (UTC)

  pageviews  14,622
  visitors    9,016
  visitors is a sum of the buckets below, so someone who came on two days counts twice;
  run the total preset for distinct visitors over the window

By day
  2026-08-07  1,840  ███████████████
  2026-08-08  1,512  ████████████
  2026-08-09  1,097  █████████
  2026-08-10  2,604  █████████████████████
  2026-08-11  2,988  ████████████████████████
  2026-08-12  2,415  ███████████████████
  2026-08-13  2,166  █████████████████

Top pages (top 5)
requestPath            pageviews  visitors  % pageviews
---------------------  ---------  --------  -----------
/                          4,821     3,110        33.0%
/pricing                   2,740     1,988        18.7%
/docs/getting-started      1,866     1,204        12.8%
/blog/shipping-faster      1,402     1,121         9.6%
/changelog                   903       640         6.2%
Others                     2,890     1,702        19.8%
---------------------  ---------  --------  -----------
TOTAL                     14,622     9,765       100.0%

Others is not a real value: it is every group beyond --limit 5, collapsed by the API into one bucket.

Top referrers (top 5)
referrerHostname      pageviews  visitors  % pageviews
--------------------  ---------  --------  -----------
(direct)                  6,120     4,002        41.9%
news.ycombinator.com      3,411     2,870        23.3%
google.com                2,588     1,930        17.7%
x.com                     1,204       998         8.2%
github.com                  742       611         5.1%
Others                      557       405         3.8%
--------------------  ---------  --------  -----------
TOTAL                    14,622    10,816       100.0%

Others is not a real value: it is every group beyond --limit 5, collapsed by the API into one bucket.
```

### Top pages last month, US traffic only

```console
$ vercel_analytics.py top-pages --since 30d --country US
Vercel Web Analytics: prj_demo (top-pages)
Range: 2026-07-15T09:00:00Z to 2026-08-14T09:00:00Z (UTC)
Filter: country eq 'US'

requestPath                   pageviews  visitors  % pageviews
----------------------------  ---------  --------  -----------
/                                18,422    11,903        28.3%
/pricing                          9,884     7,120        15.2%
/docs/getting-started             6,551     4,302        10.1%
/blog/shipping-faster             5,218     4,110         8.0%
/changelog                        3,907     2,544         6.0%
/docs/api                         3,122     2,011         4.8%
/blog/analytics-from-the-cli      2,840     2,266         4.4%
/login                            2,013     1,502         3.1%
/about                            1,655     1,288         2.5%
/docs/cli                         1,471       966         2.3%
Others                            9,930     6,104        15.3%
----------------------------  ---------  --------  -----------
TOTAL                            65,013    44,116       100.0%

Others is not a real value: it is every group beyond --limit 10, collapsed by the API into one bucket.
```

### Mobile vs desktop

```console
$ vercel_analytics.py devices --since 30d
Vercel Web Analytics: prj_demo (devices)
Range: 2026-07-15T09:00:00Z to 2026-08-14T09:00:00Z (UTC)

deviceType  pageviews  visitors  % pageviews
----------  ---------  --------  -----------
mobile          8,221     5,410        56.2%
desktop         6,104     3,902        41.7%
tablet            297       188         2.0%
----------  ---------  --------  -----------
TOTAL          14,622     9,500       100.0%
```

### A weekly trend, straight into a spreadsheet

```console
$ vercel_analytics.py trend --granularity week --since 8w --csv
week,pageviews,visitors
2026-06-22,10422,6810
2026-06-29,11877,7203
2026-07-06,9640,6122
2026-07-13,13288,8004
```

### Custom events, broken down by an event property

`--event-property plan` groups by the event name *and* the property, and each
dimension gets its own column:

```console
$ vercel_analytics.py events --event-property plan --since 30d
Vercel Web Analytics: prj_demo (events)
Range: 2026-07-15T09:00:00Z to 2026-08-14T09:00:00Z (UTC)

eventName  eventData/plan  count  visitors  % count
---------  --------------  -----  --------  -------
signup     free            1,904     1,755    80.4%
signup     pro               412       388    17.4%
signup     enterprise         51        47     2.2%
---------  --------------  -----  --------  -------
TOTAL                      2,367     2,190   100.0%
```

The same grouping in CSV, one column per dimension:

```console
$ vercel_analytics.py events --event-property plan --since 30d --csv
eventName,eventData/plan,count,visitors
signup,free,1904,1755
signup,pro,412,388
signup,enterprise,51,47
```

To drop the event name column, group by the property on its own with
`events --group-by eventData/plan`.

### Distinct visitors for the month, and the same number in JSON

```console
$ vercel_analytics.py total --since 30d
Vercel Web Analytics: prj_demo (total)
Range: 2026-07-15T09:00:00Z to 2026-08-14T09:00:00Z (UTC)

  pageviews  62,704
  visitors   38,915
```

The same number, machine readable:

```console
$ vercel_analytics.py total --since 30d --json | jq '.rows[0].metrics'
{
  "pageviews": 62704,
  "visitors": 38915
}
```

### Show the request without sending it

```console
$ vercel_analytics.py top-pages --dry-run
GET https://api.vercel.com/v1/query/web-analytics/visits/aggregate

Query parameters:
  projectId  prj_demo
  by         requestPath
  since      2026-08-07T09:00:00Z
  until      2026-08-14T09:00:00Z
  limit      10

Headers:
  Accept         application/json
  Authorization  Bearer <redacted>
  User-Agent     vercel-analytics-skill/0.1.0

Encoded URL (never contains the token):
  https://api.vercel.com/v1/query/web-analytics/visits/aggregate?projectId=prj_demo&by=requestPath&since=2026-08-07T09%3A00%3A00Z&until=2026-08-14T09%3A00%3A00Z&limit=10

Nothing was sent. No credential is printed above.
```

## Presets

`vercel_analytics.py --list-presets` prints this table at any time. The preset is
the optional first positional argument; with no arguments the tool runs
`overview`.

| Preset | Dataset | Groups by | Default limit | What it shows |
| --- | --- | --- | --- | --- |
| `overview` (default) | visits | `day`, then `requestPath`, then `referrerHostname` (3 calls) | 5 per table | Totals, a daily trend, top pages and top referrers |
| `trend` | visits | `day` | 100 | Page views over time; change buckets with `--granularity` |
| `top-pages` | visits | `requestPath` | 10 | Most viewed URL paths |
| `top-routes` | visits | `route` | 10 | Most viewed framework routes, for example `/blog/[slug]` |
| `referrers` | visits | `referrerHostname` | 10 | Where the traffic came from |
| `countries` | visits | `country` | 10 | Traffic by country |
| `devices` | visits | `deviceType` | 10 | Traffic by device type |
| `browsers` | visits | `browserName` | 10 | Traffic by browser |
| `operating-systems` | visits | `osName` | 10 | Traffic by operating system |
| `campaigns` | visits | `utmCampaign` | 10 | Traffic by `utm_campaign` (needs Web Analytics Plus) |
| `events` | events | `eventName` | 10 | Custom events; add `--event-property NAME` to break one out |
| `total` | visits | nothing, one ungrouped count | n/a | One total for the window, production only |

Any explicit flag overrides a preset value, with one exception: `overview`
issues its own three queries, so `--group-by`, `--event-property` and `--csv`
are rejected there with exit code 2 rather than being applied. Use `trend`,
`top-pages` or `referrers` when you want to control the grouping or take a
single table away as CSV.

Groups past the limit are never dropped: they roll into a single `Others` row
that still counts toward the total.

## Flags

### Configuration

| Flag | Env fallback | Default | Notes |
| --- | --- | --- | --- |
| `--token TOKEN` | `VERCEL_TOKEN` | none | Required for real requests, not for `--dry-run`. |
| `--project ID_OR_NAME` | `VERCEL_PROJECT_ID` | none | Required. Project ID or project name. |
| `--team TEAM_ID` | `VERCEL_TEAM_ID` | none | Team-owned projects. Not with `--team-slug`. |
| `--team-slug SLUG` | `VERCEL_TEAM_SLUG` | none | Sent as `slug`. Not with `--team`. |

### Query shape

| Flag | Default | Notes |
| --- | --- | --- |
| `--dataset {visits,events}` | preset's choice, usually `visits` | `events` for custom events. |
| `--group-by DIM`, `--dimension DIM` | the preset's grouping | Repeatable, maximum 2, at most one time bucket. |
| `--granularity {hour,day,week,month,year}` | none | Replaces the preset's time bucket; alongside an explicit `--group-by` it is appended to it. |
| `--since WHEN` | `7d` | `30m`, `24h`, `7d`, `4w`, `now`, `today`, `yesterday`, `2026-08-01`, `2026-08-01T12:00:00Z`, or Unix ms. |
| `--until WHEN` | `now` | Same forms. Must be strictly after `--since`. |
| `--limit N` | preset's, usually 10 | 1 to 100. Overflow becomes `Others`. |
| `--event-property NAME` | none | Adds `eventData/NAME` as a second grouping dimension next to `eventName`, and each dimension gets its own column. Events only. |

### Filters

Each adds one OData clause; all clauses are joined with `and`. A comma-separated
value becomes an `in (...)` set, so `--country US,CA,MX` is one clause.

| Flag | Clause it builds |
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
| `--event-name VALUE` | `eventName eq 'VALUE'`, events dataset only |
| `--flag NAME=VALUE` | `flags/NAME eq 'VALUE'`, repeatable. A name with punctuation is quoted for you: `--flag my-flag=on` builds `flags/'my-flag' eq 'on'` |
| `--environment {production,preview}` | `environment eq 'VALUE'` |
| `--filter ODATA` | Appended verbatim, repeatable |

The API supports `eq`, `ne`, `in`, `and`, `or`, `not` and parentheses. It has no
comparison operators, so `gt`, `lt`, `ge` and `le` do not work in `--filter`.

### Output and behaviour

| Flag | Default | Notes |
| --- | --- | --- |
| `--json` | off | Machine readable, with the untouched API payload under `raw`. Not with `--csv`. |
| `--csv` | off | `csv.writer` quoting. Not with `--json`, and not with `overview`. |
| `--dry-run` | off | Print the request, send nothing, no token needed. |
| `--timeout SECONDS` | `30.0` | Per request. Must be a finite number greater than 0; anything else is a usage error. |
| `--max-retries N` | `3` | Retries after the first attempt. Only 429, 5xx and network failures are retried. |
| `--no-color` | auto | Also honours `NO_COLOR` and a non-TTY stdout. |
| `--verbose` | off | Diagnostics on stderr. Never the token. |
| `--list-presets` | | Print the preset table and exit 0. |
| `--version` | | Print the version and exit 0. |

Exit codes: `0` success including an empty result, `1` API or network failure,
`2` configuration or usage error, `130` interrupted.

## Security and permissions

- **Read-only, by construction.** The Vercel Web Analytics API is a query API
  with no write surface, and this client has exactly one HTTP call site:
  `session.get`. No other verb is reachable from any code path, and no request
  body is ever built. It cannot change deployments, projects, domains,
  environment variables, or settings.
- **The token is never logged.** It is placed only in the `Authorization`
  header. It never appears in a URL, a query parameter, a log line, an exception
  message, or any formatter output. `--verbose` and error paths render headers
  through a redactor that replaces the credential with `Bearer <redacted>`, and
  any message on its way into an error is scrubbed of the credential first.
- **A malformed token is caught before a request exists.** A value carrying a
  newline, another control or non-ASCII character, or a leading or trailing
  space is rejected with exit code 2, and the message reports the length, the
  position and the character class only. The token itself is never printed.
- **`--dry-run` proves it.** It prints the full request including the encoded
  URL, never constructs an HTTP session, and works with no token in the
  environment. Run it first when you want to know exactly what will be sent.
- **Scopes.** A standard Vercel access token with read access is enough. For a
  team-owned project the token must belong to an account with access to that
  team, and the team must be identified with `VERCEL_TEAM_ID` or
  `VERCEL_TEAM_SLUG`. No write scope is used or needed.
- **The token comes from the environment.** `VERCEL_TOKEN`, or `--token` when
  you would rather pass it explicitly. It is not read from, or written to, any
  file. Nothing is cached to disk: this tool performs no filesystem writes at
  all.
- **No dynamic execution.** No `eval`, no `exec`, no `subprocess`.

## Reporting window

Analytics data is only guaranteed to be queryable for a limited period, and it
depends on the plan:

| Plan | Reporting window |
| --- | --- |
| Hobby | 1 month |
| Pro | 12 months |
| Pro with Web Analytics Plus | 24 months |
| Enterprise | 24 months |

A `--since` beyond your plan's window is still a legal query, it just tends to
come back empty. The plan tier is not discoverable through this API, so the tool
warns on stderr past 24 months rather than blocking anything. Two related
limits: custom events need Pro or above, and UTM dimensions need Web Analytics
Plus or Enterprise. Below those tiers the queries return nothing rather than
failing.

## More

- [examples/example_outputs.md](examples/example_outputs.md) for fuller sample
  output.
- [docs/api-notes.md](docs/api-notes.md) for the verified API facts this is
  built on, including the response shapes and the parsing traps.
- [CONTRIBUTING.md](CONTRIBUTING.md) to add a preset or report a bug.

## License

MIT-0 (MIT No Attribution). See [LICENSE](LICENSE).
