# vercel-insights

Your Vercel traffic **and** your Core Web Vitals, answered in one command line.

```console
$ python3 -m vercel_insights top-pages --since 30d --country US
$ python3 -m vercel_insights vitals --since 30d
```

Two Vercel APIs, one CLI: Web Analytics for how many people came and where from,
Speed Insights for how fast the site felt when they got there.

## Why not just open the dashboard

Because a dashboard answers one question at a time, and only for the person
looking at it.

- **One line, one answer.** No date picker, no tab switching, no waiting for a
  chart to animate. `trend --since 4w --granularity week` is the whole
  interaction, and so is `vitals`.
- **Rankings the dashboard will not give you.** The Speed Insights dashboard
  shows a route list, but it cannot sort your routes by P75 LCP worst-first and
  hand you the top ten. `slowest-pages` is exactly that query, and
  `fastest-pages` is its mirror.
- **Comparison across projects.** A dashboard is one project per tab. On the
  Speed Insights presets, `--all` queries every project in the team in one go.
  It is a Speed Insights option only: on a traffic preset it is a configuration
  error, so compare traffic by running the same command once per `--project`
  and diffing the `--json`.
- **Diffable between deploys.** Yesterday's CSV against today's CSV is a real
  answer to "did that ship make the site slower". Two screenshots are not. Put
  `vitals-trend --granularity 1d --csv` in a nightly job and the regression
  shows up as a line in a file, not as a feeling.
- **Scriptable.** Cron job, CI step, Makefile. Exit codes are meaningful: 0 for
  success (an empty result included), 1 for an API failure, 2 for a bad command.
- **Pipeable.** `--json` feeds `jq`, `--csv` feeds a spreadsheet or `duckdb`. The
  raw API payload is preserved under `raw` in the JSON output, so nothing is
  lost in translation.
- **Agent-native.** It ships as an OpenClaw skill, so "how did the blog do this
  week" or "which pages are slowest on mobile" inside a conversation becomes a
  real query with a real table, not a guess.
- **Safe by construction.** Read-only against a three-endpoint allowlist, and
  the token never leaves the `Authorization` header. See
  [Security and permissions](#security-and-permissions).

## Install

From ClawHub:

```bash
clawhub install vercel-insights
```

Or clone it and run the package directly, no packaging step:

```bash
git clone https://github.com/anatoli-iliev/openclaw-vercel-insights.git
cd openclaw-vercel-insights
python3 -m venv .venv
.venv/bin/python -m pip install requests   # the only runtime dependency
.venv/bin/python -m vercel_insights --help
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

Already have `requests` importable? Then `python3 -m vercel_insights` works from
the repository root as is, with no installation. From anywhere else,
`python3 /abs/path/to/vercel_insights/__main__.py` works too: the entry point
repairs `sys.path` before importing anything. And `pip install -e .` adds a
`vercel-insights` console script on `PATH`, which is the same entry point.

Python 3.10 or newer. `requests` is the only thing outside the standard library.
`CONTRIBUTING.md` uses the same virtualenv flow, plus the test and lint tools.

## 60-second setup

**1. Create a Vercel access token** at
<https://vercel.com/account/tokens>. Read scope is enough; this tool never
writes. Copy it, Vercel shows it once.

> **Scope it to the account or team, not to a single project**, if you want
> Speed Insights. Vercel's two APIs scope differently, and a project scoped
> token silently reaches only one of them:
>
> | Preset family | API | Project scoped token |
> | --- | --- | --- |
> | Web Analytics (`overview`, `top-pages`, `events`, ...) | scoped by `projectId` | works |
> | Speed Insights (`vitals`, `slowest-pages`, ...) | scoped by account | `404 Observability Data not found.` |
>
> That 404 reads like "your project has no data" but means "this token cannot
> ask". To see what the current token can reach:
> `npx vercel@latest metrics schema`

**2. Make sure the feature you want is enabled** on the project. Web Analytics
and Speed Insights are two separate per-project switches, each with its own
package in the app: `@vercel/analytics`
(<https://vercel.com/docs/analytics/quickstart>) and `@vercel/speed-insights`
(<https://vercel.com/docs/speed-insights/quickstart>). Data only exists from the
moment each one is turned on. Speed Insights does **not** need Observability
Plus: its metrics are readable on the query surface without it. It does need a
token that is not scoped to a single project; see the note in step 1.

**3. Find the project.** One Vercel account holds many projects, and a query
names exactly one, so start by seeing what you have:

```console
$ vercel-insights --list-projects
name            project id                    traffic  speed
--------------  ----------------------------  -------  -----
my-site         prj_tjgvYZgQGYqNxBP1nQffcF1A  data     data
marketing       prj_9xQ2vB7kLmT4dRnW          data     empty
internal-tools  prj_Kd8sPqR2nX5vB             off      off
```

`data` means collected, `empty` means the feature is on but nothing has arrived
yet, `off` means it is not enabled. Pass either the **name** or the **project
id** to `--project`; both work on every preset.

If you forget to name a project, the error prints this table rather than only
telling you a flag is missing.

**3b. Or find the ID by hand.** Vercel dashboard, pick the project, Settings, then
General: the field is "Project ID" and looks like `prj_XXXXXXXXXXXXXXXX`. The
project *name* works just as well anywhere the ID does.

**4. Export the environment variables:**

```bash
export VERCEL_TOKEN="vercel_tok_xxxxxxxxxxxxxxxxxxxxxxxx"
export VERCEL_PROJECT_ID="prj_XXXXXXXXXXXXXXXX"
# export VERCEL_TEAM_ID="team_XXXXXXXXXXXXXXXX"   # team-owned projects only
# export VERCEL_ORG_ID="team_XXXXXXXXXXXXXXXX"    # written by `vercel link`; read as the owner
```

Copy `.env.example` if you prefer keeping them in a file; the two team
variables are commented out there for the same reason. On a personal account
leave `VERCEL_TEAM_ID` unset: any value you give it is sent verbatim as the
`teamId` query parameter, placeholder or not.

**5. Check it without spending a request:**

```bash
.venv/bin/python -m vercel_insights --dry-run
```

That prints the request and sends nothing. It works even before the token is
set, as long as a project is configured.

## Examples

> Every block below was captured verbatim from a real run of the tool, driven
> through `main()` against a stub API session, so the layout, the column names,
> the percentages, the units and the footnotes are exactly what you get. Only
> the numbers, the project name and the clock are invented. `vercel-insights` is
> shorthand for `.venv/bin/python -m vercel_insights` (or
> `python3 -m vercel_insights` wherever `requests` is already importable).

### The 7-day overview (this is the default)

```console
$ vercel-insights
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
$ vercel-insights top-pages --since 30d --country US
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
$ vercel-insights devices --since 30d
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
$ vercel-insights trend --granularity week --since 8w --csv
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
$ vercel-insights events --event-property plan --since 30d
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
$ vercel-insights events --event-property plan --since 30d --csv
eventName,eventData/plan,count,visitors
signup,free,1904,1755
signup,pro,412,388
signup,enterprise,51,47
```

To drop the event name column, group by the property on its own with
`events --group-by eventData/plan`.

### Distinct visitors for the month, and the same number in JSON

```console
$ vercel-insights total --since 30d
Vercel Web Analytics: prj_demo (total)
Range: 2026-07-15T09:00:00Z to 2026-08-14T09:00:00Z (UTC)

  pageviews  62,704
  visitors   38,915
```

The same number, machine readable:

```console
$ vercel-insights total --since 30d --json | jq '.rows[0].metrics'
{
  "pageviews": 62704,
  "visitors": 38915
}
```

## Core Web Vitals examples

Speed Insights answers a different question from the same command line: not how
many people came, but how fast the site was for them. Every value is a
percentile over real user measurements, P75 by default, which is what the
dashboard shows.

### All five vitals against Vercel's published targets

```console
$ vercel-insights vitals
Vercel Speed Insights: prj_demo
Range: 2026-08-07T09:00:00Z to 2026-08-14T09:00:00Z (UTC)

metric                        p75  target  verdict       data points
-------------------------  ------  ------  ------------  -----------
Largest Contentful Paint    2.4 s   2.5 s  meets target       18,204
Interaction to Next Paint  176 ms  200 ms  meets target       12,110
Cumulative Layout Shift     0.072   0.100  meets target       18,204
First Contentful Paint      1.2 s   1.8 s  meets target       18,204
Time to First Byte         918 ms  800 ms  over target        18,204

Lower is better for all five metrics.
The target is Vercel's published 'good' threshold, so the verdict is two tier: meets target or over target.
A percentile over few data points is not comparable to one over many, so read the value next to its data point count.
Real Experience Score is not queryable through this API; read it on the Speed Insights dashboard.
```

The verdict is two tier by design. Vercel publishes one "good" threshold per
metric and no boundary above it, so a three-band good / needs improvement / poor
scale would be invented rather than reported. The dashboard's colour bands
describe a derived 0 to 100 score, not the raw millisecond value.

`vitals` issues five requests, one per metric, because the API answers for one
metric per request. That is why `--csv`, `--group-by` and `--metric` are all
configuration errors there: the preset already reports every vital, so there is
no single metric to select and no single table to write. Use `vitals-trend`,
`slowest-pages` or `vitals-by-country` when you want one metric in one table.

### Which routes are slowest, on mobile

```console
$ vercel-insights slowest-pages --device mobile --limit 5
Vercel Speed Insights: prj_demo (slowest-pages, p75)
Range: 2026-08-07T09:00:00Z to 2026-08-14T09:00:00Z (UTC)
Filter: device_type eq 'mobile'

route              p75_lcp  data_points
-----------------  -------  -----------
/blog/[slug]         4.1 s        1,830
/pricing             3.0 s        2,240
/dashboard/[id]      2.5 s          902
/docs/[[...slug]]    2.0 s        4,410
/                    1.2 s        8,822

Metric: vercel.speed_insights.lcp_ms (Largest Contentful Paint)
Target: 2.5 s or less
Lower is better for all five metrics.
The target is Vercel's published 'good' threshold, so the verdict is two tier: meets target or over target.
A percentile over few data points is not comparable to one over many, so read the value next to its data point count.
```

Two things to notice. `--device mobile` compiled to `device_type eq 'mobile'`,
the Speed Insights spelling of the dimension: the shorthand flags translate
per surface so you never have to remember which API is camelCase. And there is
no totals row and no share column, because summing percentiles is meaningless.

### Speed by country, and by device

```console
$ vercel-insights vitals-by-country --since 30d
Vercel Speed Insights: prj_demo (vitals-by-country, p75)
Range: 2026-07-15T09:00:00Z to 2026-08-14T09:00:00Z (UTC)

country  p75_lcp  data_points
-------  -------  -----------
US         1.8 s        8,140
DE         2.1 s        3,020
GB         2.3 s        2,470
IN         3.5 s        1,990
BR         3.9 s        1,180

Metric: vercel.speed_insights.lcp_ms (Largest Contentful Paint)
Target: 2.5 s or less
Lower is better for all five metrics.
The target is Vercel's published 'good' threshold, so the verdict is two tier: meets target or over target.
A percentile over few data points is not comparable to one over many, so read the value next to its data point count.
```

```console
$ vercel-insights vitals-by-device --since 30d
Vercel Speed Insights: prj_demo (vitals-by-device, p75)
Range: 2026-07-15T09:00:00Z to 2026-08-14T09:00:00Z (UTC)

device_type  p75_lcp  data_points
-----------  -------  -----------
desktop        1.6 s        9,840
mobile         3.2 s        7,910
tablet         2.5 s          454

Metric: vercel.speed_insights.lcp_ms (Largest Contentful Paint)
Target: 2.5 s or less
Lower is better for all five metrics.
The target is Vercel's published 'good' threshold, so the verdict is two tier: meets target or over target.
A percentile over few data points is not comparable to one over many, so read the value next to its data point count.
```

Both default to `--metric lcp`. Pass `--metric inp`, `cls`, `fcp` or `ttfb` for
a different vital. Both order by data point count by default, so a group with a
handful of measurements does not lead the table.

### Did it regress? A daily trend

```console
$ vercel-insights vitals-trend --metric inp --granularity 1d
Vercel Speed Insights: prj_demo (vitals-trend, p75)
Range: 2026-08-07T09:00:00Z to 2026-08-14T09:00:00Z (UTC)

1d          p75_inp  data_points
----------  -------  -----------
2026-08-07   168 ms        1,704
2026-08-08   172 ms        1,622
2026-08-09   155 ms        1,180
2026-08-10   204 ms        1,866
2026-08-11   231 ms        1,940
2026-08-12   188 ms        1,812
2026-08-13   176 ms        1,786

Metric: vercel.speed_insights.inp_ms (Interaction to Next Paint)
Target: 200 ms or less
Lower is better for all five metrics.
The target is Vercel's published 'good' threshold, so the verdict is two tier: meets target or over target.
A percentile over few data points is not comparable to one over many, so read the value next to its data point count.
```

The same thing as CSV, which is the shape you want in a nightly job so two days
can be diffed:

```console
$ vercel-insights vitals-trend --metric inp --granularity 1d --csv
1d,p75_inp,data_points
2026-08-07,168.0,1704.0
2026-08-08,172.0,1622.0
2026-08-09,155.0,1180.0
2026-08-10,204.0,1866.0
2026-08-11,231.0,1940.0
2026-08-12,188.0,1812.0
2026-08-13,176.0,1786.0
```

`--granularity` accepts either vocabulary: `1d` and `day` mean the same thing
and each API gets the spelling it wants. `week` and `year` exist on Web
Analytics only.

### How much data is behind those percentiles

```console
$ vercel-insights data-points --since 30d
Vercel Speed Insights: prj_demo (data-points, sum)
Range: 2026-07-15T09:00:00Z to 2026-08-14T09:00:00Z (UTC)

route              sum_lcp_count  % sum_lcp_count
-----------------  -------------  ---------------
/                          8,822            48.5%
/docs/[[...slug]]          4,410            24.2%
/pricing                   2,240            12.3%
/blog/[slug]               1,830            10.1%
/dashboard/[id]              902             5.0%
-----------------  -------------  ---------------
TOTAL                     18,204           100.0%

Metric: vercel.speed_insights.lcp_count (Largest Contentful Paint data points)
These are data point counts, not metric values: one data point is one measurement of one web vital during one visit, and a visit produces up to six.
They are what makes a percentile trustworthy, so a group with few of them is not comparable to one with many.
```

This is the one Speed Insights table that keeps a totals row and a share column,
because a sum of measurement counts genuinely adds up.

### Real Experience Score is not queryable

```console
$ vercel-insights vitals-trend --metric res --dry-run
error: --metric 'res': Real Experience Score is not queryable. Vercel states plainly that it is not available through the query API this tool uses, so there is nothing to request and this client will not substitute another metric for it. Read it on the Speed Insights tab of your project dashboard (https://vercel.com/docs/speed-insights/metrics), or query one of the five metrics it is derived from: lcp, inp, cls, fcp, ttfb
```

That line is on stderr, with exit code 2. RES is a composite score derived from
these five metrics; the five are the honest command line answer.

### Show the request without sending it

A GET, on the Web Analytics surface:

```console
$ vercel-insights top-pages --dry-run
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
  User-Agent     vercel-insights-skill/0.2.0

Encoded URL (never contains the token):
  https://api.vercel.com/v1/query/web-analytics/visits/aggregate?projectId=prj_demo&by=requestPath&since=2026-08-07T09%3A00%3A00Z&until=2026-08-14T09%3A00%3A00Z&limit=10

Nothing was sent. No credential is printed above.
```

And the POST, on the Speed Insights surface, where the dry run prints the whole
query body:

```console
$ vercel-insights slowest-pages --since 30d --dry-run
POST https://api.vercel.com/v2/observability/query

Query parameters:
  (none)

Headers:
  Accept         application/json
  Authorization  Bearer <redacted>
  User-Agent     vercel-insights-skill/0.2.0

JSON body:
  {
    "metric": "vercel.speed_insights.lcp_ms",
    "scope": {
      "type": "project",
      "projectId": "prj_demo"
    },
    "aggregation": "p75",
    "groupBy": [
      "route"
    ],
    "limit": 10,
    "orderBy": "value",
    "orderDirection": "desc",
    "startTime": "2026-07-15T09:00:00Z",
    "endTime": "2026-08-14T09:00:00Z"
  }

Encoded URL (never contains the token):
  https://api.vercel.com/v2/observability/query

Nothing was sent. No credential is printed above.
```

The token is not in that body, and never is: it lives in the `Authorization`
header and nowhere else, which is exactly why the body can be printed in full.

## Guarding performance in CI

`--budget` turns a measurement into a pass or a fail, so a regression can stop a
build instead of being noticed later:

```console
$ vercel-insights vitals --since 7d --budget lcp=2500 --budget inp=200 --budget cls=0.1

Budgets
  pass    Largest Contentful Paint      2.4 s against 2.5 s
  fail    Interaction to Next Paint    205 ms against 200 ms
at least one budget was exceeded, so this run exits 3
```

Exit **3** means a budget was exceeded, which is deliberately not 1: a failing
budget is a successful run reporting bad news, and a CI step usually wants to
tell that apart from the API being down. A metric with no data does not fail,
because an empty window means the measurement is missing rather than the site
being slower.

A ready-to-copy workflow is in
[`examples/github-action-budget.yml`](examples/github-action-budget.yml). Note
it is scheduled rather than run per commit: these are real user measurements,
so they accumulate from visitors over time and do not change the moment a deploy
lands.

## Presets

`vercel-insights --list-presets` prints this table at any time. The preset is
the optional first positional argument; with no arguments the tool runs
`overview`.

### Web Analytics

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

### Speed Insights

| Preset | Metric | Groups by | Default limit | What it shows |
| --- | --- | --- | --- | --- |
| `vitals` | all five (5 calls) | nothing | n/a | P75 of every web vital against its published target |
| `slowest-pages` | `lcp` | `route`, worst first | 10 | Routes with the worst P75 LCP |
| `fastest-pages` | `lcp` | `route`, best first | 10 | Routes with the best P75 LCP |
| `vitals-by-country` | `--metric`, default `lcp` | `country` | 10 | Where in the world the site is slow |
| `vitals-by-device` | `--metric`, default `lcp` | `device_type` | 10 | Mobile against desktop against tablet |
| `vitals-trend` | `--metric`, default `lcp` | time, `1d` by default | n/a | Whether it is getting better or worse |
| `data-points` | `<metric>_count` | `route` | 10 | How many measurements each route contributed |

Any explicit flag overrides a preset value, with two exceptions. `overview`
issues its own three queries, so `--group-by`, `--event-property` and `--csv`
are rejected there. `vitals` issues one query per web vital, so `--group-by`,
`--csv` and `--metric` are rejected there. Both exit 2 and name a preset to use
instead.

A preset also fixes which API is queried, and that is enforced rather than
implied: every Speed Insights option is a configuration error on a Web Analytics
preset, and every Web-Analytics-only option is a configuration error on a Speed
Insights preset. The tables below say which is which for each flag.

Groups past the limit are never dropped: they roll into a single `Others` row
that still counts toward the total.

## Flags

### Configuration

| Flag | Env fallback | Default | Notes |
| --- | --- | --- | --- |
| `--token TOKEN` | `VERCEL_TOKEN` | none | Required for real requests, not for `--dry-run`. |
| `--project ID_OR_NAME` | `VERCEL_PROJECT_ID` | none | Project ID or project name. Required, except on a Speed Insights preset run with `--all`. |
| `--team TEAM_ID` | `VERCEL_TEAM_ID` | none | Team-owned projects. Not with `--team-slug`. |
| `--owner-id ID` | `VERCEL_OWNER_ID` | resolved | Account owning the project, required by a Speed Insights scope. A team is its own owner, so `--team` covers it; otherwise the personal account id is read once from the API. |
| `--team-slug SLUG` | `VERCEL_TEAM_SLUG` | none | Sent as `slug`. Not with `--team`. |

### Query shape

| Flag | Surface | Default | Notes |
| --- | --- | --- | --- |
| `--dataset {visits,events}` | Web Analytics only | preset's choice, usually `visits` | `events` for custom events. Not with `--metric`, and a configuration error on a Speed Insights preset, which has no datasets. |
| `--group-by DIM`, `--dimension DIM` | both | the preset's grouping | Repeatable, maximum 2. Web Analytics: at most one time bucket. The dimension *names* are not portable: a camelCase name on Speed Insights, or a snake_case one on Web Analytics, is a configuration error. |
| `--granularity BUCKET` | both | none | `hour`, `1h`, `day`, `1d`, `week`, `month`, `1mo`, `year`. Both vocabularies accepted and translated per API; `week` and `year` are Web Analytics only, and a configuration error on Speed Insights. |
| `--since WHEN` | both | `7d` | `30m`, `24h`, `7d`, `4w`, `now`, `today`, `yesterday`, `2026-08-01`, `2026-08-01T12:00:00Z`, or Unix ms. |
| `--until WHEN` | both | `now` | Same forms. Must be strictly after `--since`. |
| `--limit N` | both | preset's, usually 10 | 1 to 100, checked before the request. On Web Analytics the overflow becomes `Others`; on Speed Insights it bounds grouped results per time bucket. An ungrouped query (`total`, `vitals`) has nothing to limit, so the value is accepted and goes unused. |
| `--event-property NAME` | Web Analytics, events dataset only | none | Adds `eventData/NAME` as a second grouping dimension next to `eventName`, and each dimension gets its own column. A configuration error on `visits`, on Speed Insights, and on `overview`. |

### Speed Insights

Every flag in this table is a Speed Insights option. None of them is universal:
on a Web Analytics preset (`overview`, `trend`, `top-pages`, `top-routes`,
`referrers`, `countries`, `devices`, `browsers`, `operating-systems`,
`campaigns`, `events`, `total`) each one exits 2 with a message naming the seven
presets that do accept it. That is enforced in code, not a convention.

| Flag | Default | Notes |
| --- | --- | --- |
| `--metric NAME` | the preset's, usually `lcp` | `lcp`, `inp`, `cls`, `fcp`, `ttfb`. The full id (`vercel.speed_insights.lcp_ms`) and the human label are accepted too. Not with `--dataset`, and a configuration error on `vitals`, which reports all five. |
| `--percentile N` | `75` | One of 75, 90, 95, 99. Sugar for `--aggregation p75` and friends. |
| `--aggregation NAME` | the metric's default | Raw passthrough, for example `sum`, `count`, `min`, `max`, `p90`. Not with `--percentile`. |
| `--order-by COLUMN` | `count` | `count` or `value`. Grouped queries only; without a grouping it is an error. |
| `--order DIRECTION` | `desc` | `asc` or `desc`. Grouped queries only. |
| `--bucket-timezone IANA` | none | Aligns `1d` and `1mo` buckets, for example `Europe/Paris`. Timestamps stay UTC; a sub-daily bucket ignores it and the tool warns. |
| `--all` | off | Query every project in the team, instead of one. Mutually exclusive with `--project`, and a configuration error on every Web Analytics preset: there is no team-wide traffic query, so compare those one `--project` at a time. |
| `--data-points` | off | Report the number of measurements instead of the metric value. Defaults the aggregation to `sum`. |

### Filters

Each adds one OData clause; all clauses are joined with `and`. A comma-separated
value becomes an `in (...)` set, so `--country US,CA,MX` is one clause. The
dimension name compiles to the spelling of whichever surface is active.

| Flag | On Web Analytics | On Speed Insights |
| --- | --- | --- |
| `--path VALUE` | `requestPath eq 'VALUE'` | `request_path eq 'VALUE'` |
| `--route VALUE` | `route eq 'VALUE'` | `route eq 'VALUE'` |
| `--country VALUE` | `country eq 'VALUE'` | `country eq 'VALUE'` |
| `--device VALUE` | `deviceType eq 'VALUE'` | `device_type eq 'VALUE'` |
| `--environment {production,preview}` | `environment eq 'VALUE'` | `environment eq 'VALUE'` |
| `--browser VALUE` | `browserName eq 'VALUE'` | not collected, configuration error |
| `--os VALUE` | `osName eq 'VALUE'` | not collected, configuration error |
| `--referrer VALUE` | `referrerHostname eq 'VALUE'` | not collected, configuration error |
| `--utm-source VALUE` | `utmSource eq 'VALUE'` | not collected, configuration error |
| `--utm-medium VALUE` | `utmMedium eq 'VALUE'` | not collected, configuration error |
| `--utm-campaign VALUE` | `utmCampaign eq 'VALUE'` | not collected, configuration error |
| `--event-name VALUE` | `eventName eq 'VALUE'`, events dataset only | no custom events, configuration error |
| `--flag NAME=VALUE` | `flags/NAME eq 'VALUE'`, repeatable. A name with punctuation is quoted for you: `--flag my-flag=on` builds `flags/'my-flag' eq 'on'` | no feature flags, configuration error |
| `--filter ODATA` | appended verbatim, repeatable | appended verbatim, repeatable |

Web Analytics accepts `eq`, `ne`, `in`, `and`, `or`, `not`, parentheses and
`startswith`. It has no comparison operators, so `gt`, `lt`, `ge` and `le` do
not work in a `--filter` there. Speed Insights accepts the same set plus
`endsWith` and the numeric comparisons `>`, `>=`, `<`, `<=`. Raw `--filter` text
is passed through unvalidated on both, so a clause the API refuses comes back as
its own 400 with Vercel's message.

### Output and behaviour

| Flag | Default | Notes |
| --- | --- | --- |
| `--json` | off | Machine readable, with the untouched API payload under `raw`. Not with `--csv`. |
| `--csv` | off | `csv.writer` quoting. Not with `--json`, and not with `overview` or `vitals`. |
| `--dry-run` | off | Print the request, send nothing, no token needed. Prints the full JSON body on a POST. |
| `--timeout SECONDS` | `30.0` | Per request. Must be a finite number greater than 0; anything else is a usage error. |
| `--max-retries N` | `3` | Retries after the first attempt. Only 408, 429 and 5xx responses and network failures are retried. |
| `--no-color` | auto | Also honours `NO_COLOR` and a non-TTY stdout. |
| `--verbose` | off | Diagnostics on stderr. Never the token. |
| `--list-presets` | | Print the preset table and exit 0. |
| `--version` | | Print the version and exit 0. |

Exit codes: `0` success including an empty result, `1` API or network failure,
`2` configuration or usage error, `130` interrupted.

## Security and permissions

- **Read-only against a three-endpoint allowlist.** One module-level table in
  `vercel_insights/http.py` maps an operation key to a fixed method and URL, and
  it has exactly three entries: the Web Analytics query
  (`GET /v1/query/web-analytics/{dataset}/{endpoint}`), the observability query
  (`POST /v2/observability/query`), and the observability schema
  (`GET /v2/observability/schema`). The dispatcher takes an operation key, never
  a method and never a host, so no user input can select, extend or override an
  entry. There are exactly two HTTP call sites in the package, `session.get` and
  `session.post`, and both are inside that dispatcher.
- **The allowlist binds every hop, not just the first.** Both call sites pass
  `allow_redirects=False`, and any 3xx is turned into an error rather than
  followed. That is what keeps a redirect from an allowlisted URL from carrying
  the `Authorization` header off to whatever host a `Location` header names. The
  error reports the location it refused, so a proxy or a captive network in the
  way is visible rather than silent.
- **Why one is a POST, and why it is still a read.** Vercel exposes no GET
  equivalent for an observability query. Speed Insights has no query API of its
  own, and the general observability surface takes its query in a JSON request
  body because a query is too structured for a query string. Nothing is created,
  updated or deleted: the body is the question, not a change. The endpoints in
  the same API that genuinely write, `/speed-insights/toggle` and
  `/web/insights/toggle`, which enable and disable the features, are absent from
  the allowlist and unreachable from any code path here. This tool cannot change
  deployments, projects, domains, environment variables or settings.
- **The token is never logged.** It is placed only in the `Authorization`
  header, never in a URL, a query parameter, a request body, a log line, an
  exception message, or any formatter output. `--verbose` and error paths render
  headers through a redactor that replaces the credential with
  `Bearer <redacted>`, and any message on its way into an error is scrubbed of
  the credential first.
- **A malformed token is caught before a request exists.** A value carrying a
  newline, another control or non-ASCII character, or a leading or trailing
  space is rejected with exit code 2 before any request object is built, and the
  message reports the length, the position and the character class only. The
  token itself is never printed. One nuance worth knowing: surrounding
  whitespace on `VERCEL_TOKEN` is trimmed as the environment is read, so a
  trailing newline picked up from a shell here-doc is fixed rather than
  reported; the same value passed with `--token` is reported instead.
- **`--dry-run` proves it.** It prints the full request, including the encoded
  URL and, for the POST operation, the complete JSON body. It never constructs
  an HTTP session and works with no token in the environment. Run it first when
  you want to know exactly what will be sent.
- **Scopes.** A standard Vercel access token with read access is enough. For a
  team-owned project the token must belong to an account with access to that
  team, and the team must be identified with `VERCEL_TEAM_ID` or
  `VERCEL_TEAM_SLUG`. No write scope is used or needed.
- **The token comes from the environment.** `VERCEL_TOKEN`, or `--token` when
  you would rather pass it explicitly. It is not read from, or written to, any
  file. Nothing is cached to disk: this tool performs no filesystem writes at
  all.
- **No dynamic execution.** No `eval`, no `exec`, no `subprocess`.

## Plans, windows and what is out of reach

**Reporting window.** Analytics data is only guaranteed to be queryable for a
limited period, and it depends on the plan:

| Plan | Reporting window |
| --- | --- |
| Hobby | 1 month |
| Pro | 12 months |
| Pro with Web Analytics Plus | 24 months |
| Enterprise | 24 months |

A `--since` beyond your plan's window is still a legal query, it just tends to
come back empty. The plan tier is not discoverable through this API, so the tool
warns on stderr past 24 months rather than blocking anything.

**Plan-gated features.** Custom events need Pro or above, and UTM dimensions
need Web Analytics Plus or Enterprise. Below those tiers the queries return
nothing rather than failing. **Speed Insights needs no Observability Plus**:
Vercel documents its metrics as readable on the query surface without it, and
unlike the Web Analytics count endpoints it collects on every deployed
environment, preview included.

**Real Experience Score is dashboard-only.** Vercel states that RES is not
available through the query API this tool uses, so it is not queryable here and
this client will not substitute another metric for it. Read it on the Speed
Insights tab of the project dashboard. The five vitals it is derived from are
all queryable, and `vitals` reports them together.

## More

- [examples/example_outputs.md](examples/example_outputs.md) for fuller sample
  output.
- [docs/api-notes.md](docs/api-notes.md) for the verified facts about both APIs,
  including the response shapes, the parsing traps, and what the published
  OpenAPI document does and does not pin down.
- [docs/cli-contract.md](docs/cli-contract.md) for the authoritative interface.
- [CONTRIBUTING.md](CONTRIBUTING.md) to add a preset or report a bug.

## License

MIT-0 (MIT No Attribution). See [LICENSE](LICENSE).
