---
name: vercel-insights
description: >-
  Reports a Vercel site's traffic and speed: page views, visitors, top pages,
  referrers, and Core Web Vitals against Vercel's published targets. Trigger on
  requests like "how is my site traffic this week", "which pages are slowest",
  "what are my core web vitals", or "where is my traffic coming from". Read
  only.
version: 1.0.3
homepage: https://github.com/anatoli-iliev/openclaw-vercel-insights
compatibility: openclaw >=1.0
metadata:
  security_level: L1
  openclaw:
    requires:
      env: [VERCEL_TOKEN]
      bins: [python3]
    primaryEnv: VERCEL_TOKEN
    envVars:
      - name: VERCEL_TOKEN
        required: true
        description: Vercel access token, read scope is sufficient.
      - name: VERCEL_PROJECT_ID
        required: false
        description: >-
          Default project, by id or name. Optional: without it the skill lists
          the account's projects and asks which one.
      - name: VERCEL_TEAM_ID
        required: false
        description: Team ID for team-owned projects. Omit for personal accounts.
      - name: VERCEL_ORG_ID
        required: false
        description: >-
          Vercel's own name for the owning account, written by `vercel link`.
          Read as the Speed Insights scope owner when VERCEL_OWNER_ID is unset.
      - name: VERCEL_OWNER_ID
        required: false
        description: >-
          Account id owning the project, used as scope.ownerId by Speed
          Insights presets. A team is its own owner, so VERCEL_TEAM_ID covers
          team projects; otherwise it is read from the API once per run.
      - name: VERCEL_TEAM_SLUG
        required: false
        description: Team slug, an alternative to VERCEL_TEAM_ID. Never set both.
      - name: NO_COLOR
        required: false
        description: Set to any value to disable coloured output.
    emoji: "📊"
    homepage: https://github.com/anatoli-iliev/openclaw-vercel-insights
---

# Vercel Insights

Query a Vercel project's **traffic** (Web Analytics) and its **speed** (Speed
Insights) from one command line: page views, visitors, top pages and routes,
referrers, countries, devices, browsers, UTM campaigns, custom events, and the
five Core Web Vitals against Vercel's published targets.

## Setting it up

Only `VERCEL_TOKEN` is required. Everything else is discoverable: without a
project configured this skill lists the account's projects and asks which one.

**Get the token at <https://vercel.com/account/tokens>, scoped to the account or
team rather than to a single project.** A project scoped token reads traffic but
not speed: Vercel serves Speed Insights from an account scoped API, and the
symptom is `404 Observability Data not found.`, which reads like "no data" but
means "this token cannot ask".

### The easy way

```bash
openclaw config set skills.entries.vercel-insights.apiKey YOUR_TOKEN
```

Or in the Control UI (`openclaw dashboard`): **Skills, vercel-insights, Save
key**. Both write the same place. `openclaw skills info vercel-insights` prints
these two routes for itself.

This works because the skill declares `primaryEnv: VERCEL_TOKEN`, which is what
maps a saved key onto `skills.entries.vercel-insights.apiKey`.

Note that `openclaw configure --section skills` reports skill status but does
not prompt for a key, so it is not the route to use here.

### Without storing the secret in the config file

`apiKey` also accepts a reference, so the token can stay in the environment or a
secrets provider:

```bash
openclaw config set skills.entries.vercel-insights.apiKey \
  --ref-provider default --ref-source env --ref-id VERCEL_TOKEN
```

### By hand

`~/.openclaw/openclaw.json`, under `skills.entries`:

```json
{
  "skills": {
    "entries": {
      "vercel-insights": {
        "enabled": true,
        "apiKey": "vercel_tok_...",
        "env": {
          "VERCEL_TEAM_ID": "team_...",
          "VERCEL_PROJECT_ID": "prj_..."
        }
      }
    }
  }
}
```

The `env` map is optional and takes `"${SOME_VAR}"` to read from the environment
instead of storing a value.

### The full walkthrough

`docs/openclaw-setup.md` in this skill's own directory covers every step, and a
troubleshooting table where each row is a failure hit during a real setup: token
scope, the missing team, the copied virtualenv, and the rest.

### Checking it worked

```bash
openclaw skills check
```

The skill moves out of "Missing requirements" once the token resolves. Note that
the gateway runs as its own process, so exporting a variable in an interactive
shell may not reach it: configuring it through `openclaw configure` or the
config file is the reliable route.

Set `VERCEL_TEAM_ID` if the project belongs to a team. It is also the account
that owns it, which saves a lookup on every speed query.

## How to answer a question with this

Three steps, in order. Most questions only need the third.

**1. Is it configured?** `VERCEL_TOKEN` is required. If it is missing, say so and
point at <https://vercel.com/account/tokens>, and tell the user to scope the
token to the **account or team**, not to a single project, or Speed Insights
will not work for them. Do not guess a token or ask them to paste one into the
conversation.

**2. Which project?** One account holds many, and every query names exactly one.
If the user did not name one and `VERCEL_PROJECT_ID` is unset, or they named it
loosely ("the blog", "our marketing site"), run:

```bash
python3 -m vercel_insights --list-projects
```

Match their words against the names, then pass the name or the `prj_` id to
`--project`. If several could match, ask rather than picking. That listing also
shows whether each project has traffic and speed data at all.

**3. Run the preset and read the answer back.** Use the decision table below.
The table output is already formatted for a person, so quote it rather than
re-typesetting it, then add the one sentence of interpretation the numbers
support.

**When to add `--json`.** Prefer the table when you are relaying an answer. Add
`--json` when you need to *compute* something the table does not state: compare
two runs, rank across a dimension the preset did not group by, or pull a single
figure into a sentence. Do not show raw JSON to a user who asked a plain
question.

**What the exit code means.** `0` succeeded, and an empty result is a success:
say "no data in that window", not "it failed". `1` the API returned an error,
and the message is Vercel's own, so quote it. `2` the command was wrong, and the
message names the fix, so apply it and retry rather than reporting it verbatim.
`3` only from `--budget`: the query worked and a threshold was exceeded.

**Never invent a number.** If a query comes back empty, or a metric is missing,
say so. The most damaging failure available here is a confidently worded figure
that was not measured.

## Two surfaces, one command

These are two different Vercel APIs with different vocabularies, and the preset
you pick decides which one is queried.

| | Web Analytics | Speed Insights |
| --- | --- | --- |
| Answers | how many people came, and from where | how fast the site felt for them |
| Metrics | `pageviews`, `visitors`, event `count` | LCP, INP, CLS, FCP, TTFB, plus data point counts |
| Presets | `overview`, `trend`, `top-pages`, `top-routes`, `referrers`, `countries`, `devices`, `browsers`, `operating-systems`, `campaigns`, `events`, `total` | `vitals`, `slowest-pages`, `fastest-pages`, `vitals-by-country`, `vitals-by-device`, `vitals-trend`, `data-points` |
| Dimension spelling | camelCase: `requestPath`, `deviceType` | snake_case: `request_path`, `device_type` |
| Time buckets | `--granularity day` | `--granularity 1d` |
| Selected by | `--dataset visits\|events` | `--metric lcp\|inp\|cls\|fcp\|ttfb` |

Rule of thumb: a question about **how many** is Web Analytics, a question about
**how fast** is Speed Insights. "Which pages are popular" is `top-pages`.
"Which pages are slow" is `slowest-pages`.

Both spellings of `--granularity` are accepted whichever surface is active and
translated per API, so `--granularity day` and `--granularity 1d` mean the same
thing. `week` and `year` exist on Web Analytics only; asking for them on Speed
Insights is a configuration error that says so.

`--dataset` and `--metric` select different APIs and are mutually exclusive.
Speed Insights options on a Web Analytics preset, and the reverse, are rejected
before any request is built, with a message naming the preset to use instead.

## This skill is read-only

**Read-only against a five-endpoint allowlist.** One module-level table in
`vercel_insights/http.py` maps an operation key to a fixed method and URL, and
it has exactly five entries:

| Operation | Method | Endpoint |
| --- | --- | --- |
| `web_analytics` | GET | `/v1/query/web-analytics/{dataset}/{endpoint}` |
| `observability_query` | POST | `/v2/observability/query` |
| `observability_schema` | GET | `/v2/observability/schema` |
| `project` | GET | `/v9/projects/{project}` |
| `projects` | GET | `/v10/projects` |

The dispatcher takes an operation key, never a method and never a host, so no
user input can select, extend or override an entry. There are exactly two HTTP
call sites in the whole package, `session.get` and `session.post`, and both are
inside that dispatcher.

Neither call site follows redirects (`allow_redirects=False`), and a 3xx is
reported as an error instead, so the allowlist binds every hop rather than only
the first: a redirect cannot carry the `Authorization` header to a host outside
the three above.

**Why one of them is a POST, and why that is still a read.** Vercel exposes no
GET equivalent for an observability query: Speed Insights has no query API of
its own, and the general observability surface takes its query in a JSON request
body because a query is too structured for a query string. Nothing is created,
updated or deleted. The body is the question, not a change. The endpoints in
the same API that *do* write, `/speed-insights/toggle` and
`/web/insights/toggle`, which turn the features on and off, are absent from the
allowlist entirely and are unreachable from any code path here.

This skill cannot modify deployments, projects, domains, environment variables,
team settings or DNS. If a user asks for a change to their Vercel setup, this
skill is the wrong tool: say so rather than trying.

The access token is read from the environment and placed only in the
`Authorization` header. It never appears in a URL, a query parameter, a request
body, a log line, an error message, or any output this skill prints.

## Running it

Use the launcher at the skill's own directory. It works from any working
directory and picks an interpreter that can import `requests`, so neither the
caller's location nor its `PATH` has to be right:

```bash
<skill-dir>/bin/vercel-insights [PRESET] [OPTIONS]
```

`<skill-dir>` is wherever this skill is installed. From inside a checkout,
`python3 -m vercel_insights` is equivalent and shorter, but it needs the working
directory to be the skill root and `requests` importable by the first `python3`
on `PATH`, which is why the launcher exists. Every example below writes
`python3 -m vercel_insights` for readability; substitute the launcher path when
running from elsewhere.

If neither interpreter can import `requests`, the tool says so and names the one
it tried, rather than failing with an import traceback. The fix is a virtualenv
beside the skill: `python3 -m venv .venv && .venv/bin/python -m pip install
requests`, which the launcher then prefers automatically.

With no arguments at all it runs the `overview` preset for the last 7 days.

Add `--dry-run` to any command to print the exact request that would be sent,
with the token redacted, and send nothing. On the POST operation it prints the
full JSON body, so a dry run shows the whole query rather than its envelope. It
works with no token configured, so it is the safe way to show a user what a
query will do before running it.

## Decision table: user phrasing to command

Traffic questions:

| The user says | Run |
| --- | --- |
| "how is my site doing", "traffic this week", "give me the numbers" | `python3 -m vercel_insights` |
| "how did traffic move over the last month", "daily trend", "chart it by week" | `python3 -m vercel_insights trend --since 30d` (add `--granularity week`) |
| "top pages", "most viewed pages", "what are people reading" | `python3 -m vercel_insights top-pages --since 30d` |
| "top routes", "which route is hottest", "roll the blog posts up" | `python3 -m vercel_insights top-routes --since 30d` |
| "where is my traffic coming from", "who links to us", "referrers" | `python3 -m vercel_insights referrers --since 30d` |
| "which countries", "where are visitors located" | `python3 -m vercel_insights countries --since 30d` |
| "mobile vs desktop", "what devices" | `python3 -m vercel_insights devices --since 30d` |
| "which browsers", "how much Safari" | `python3 -m vercel_insights browsers --since 30d` |
| "which operating systems", "Windows vs Mac" | `python3 -m vercel_insights operating-systems --since 30d` |
| "which campaign worked", "utm breakdown", "did the newsletter land" | `python3 -m vercel_insights campaigns --since 30d` |
| "how many signups", "custom events", "conversions" | `python3 -m vercel_insights events --since 30d` |
| "which campaign drove signups" | `python3 -m vercel_insights events --event-name signup --since 30d --group-by utmCampaign` |
| "how many visitors in total", "unique visitors for the month" | `python3 -m vercel_insights total --since 30d` |
| "which projects do I have", "what can you see", "is analytics even on" | `python3 -m vercel_insights --list-projects` |
| "how did /pricing do" | `python3 -m vercel_insights trend --path /pricing --since 30d` |

Performance questions:

| The user says | Run |
| --- | --- |
| "how fast is my site", "core web vitals", "is my site healthy", "performance check" | `python3 -m vercel_insights vitals --since 7d` |
| "what is my LCP", "what is my CLS", "is my CLS bad", "how is my INP" | `python3 -m vercel_insights vitals` and read that row against its target |
| "which pages are slowest", "what is dragging the site down", "worst routes" | `python3 -m vercel_insights slowest-pages --since 30d` |
| "which pages are fastest", "what is already fine" | `python3 -m vercel_insights fastest-pages --since 30d` |
| "fail the build if it gets slower", "set a performance budget", "check against a threshold" | `python3 -m vercel_insights vitals --budget lcp=2500 --budget cls=0.1` (exit 3 when exceeded) |
| "did my performance regress", "is it getting worse", "LCP over time", "since the last deploy" | `python3 -m vercel_insights vitals-trend --since 30d --granularity 1d` |
| "why is it slow on mobile", "mobile vs desktop speed" | `python3 -m vercel_insights vitals-by-device --since 30d` |
| "is it slow abroad", "speed by country", "how is it in India" | `python3 -m vercel_insights vitals-by-country --since 30d` |
| "how slow is the blog specifically" | `python3 -m vercel_insights vitals --route '/blog/[slug]' --since 30d` |
| "is that number trustworthy", "how much data is behind this" | `python3 -m vercel_insights data-points --since 30d` |
| "show me the worst case, not the typical case" | add `--percentile 95` (or `90`, `99`) |
| "what is my Real Experience Score" | Not queryable through any API. Send them to the Speed Insights tab of the dashboard. |

Applies to both:

| The user says | Run |
| --- | --- |
| "traffic from the US only", "US visitors only" | add `--country US` to any command |
| "mobile only" | add `--device mobile` |
| "production only" | add `--environment production` |
| "give me a CSV", "put it in a spreadsheet" | add `--csv` (not available on `overview` or `vitals`) |
| "give me JSON", "pipe it to jq" | add `--json` |
| "what would that request look like" | add `--dry-run` |

Anything else on the account:

| The user says | Run |
| --- | --- |
| "what else can you measure", "what metrics are available" | `python3 -m vercel_insights --list-metrics` |
| "how many function invocations", "edge requests", "cache hit rate", "firewall blocks" | `python3 -m vercel_insights --metric <id from --list-metrics> --aggregation sum` |

Those last ones need the Observability Plus add-on; Web Analytics and Speed
Insights do not. Without it they return an error no flag can fix, so say that
rather than retrying.

## Presets

Run `python3 -m vercel_insights --list-presets` for this table at any time.

| Preset | Surface | Groups by | Default limit |
| --- | --- | --- | --- |
| `overview` (default) | web analytics | `day`, then `requestPath`, then `referrerHostname` (3 calls) | 5 per table |
| `trend` | web analytics | `day` | 100 |
| `top-pages` | web analytics | `requestPath` | 10 |
| `top-routes` | web analytics | `route` | 10 |
| `referrers` | web analytics | `referrerHostname` | 10 |
| `countries` | web analytics | `country` | 10 |
| `devices` | web analytics | `deviceType` | 10 |
| `browsers` | web analytics | `browserName` | 10 |
| `operating-systems` | web analytics | `osName` | 10 |
| `campaigns` | web analytics | `utmCampaign` | 10 |
| `events` | web analytics | `eventName` | 10 |
| `total` | web analytics | nothing, one ungrouped count | n/a |
| `vitals` | speed insights | nothing; one query per vital (5 calls) | n/a |
| `slowest-pages` | speed insights | `route`, worst P75 LCP first | 10 |
| `fastest-pages` | speed insights | `route`, best P75 LCP first | 10 |
| `vitals-by-country` | speed insights | `country` | 10 |
| `vitals-by-device` | speed insights | `device_type` | 10 |
| `vitals-trend` | speed insights | time, `1d` buckets by default | n/a |
| `data-points` | speed insights | `route`, summing the `*_count` metric | 10 |

Any explicit flag overrides a preset value, with two exceptions. `overview`
runs three queries of its own, so `--group-by`, `--event-property` and `--csv`
are rejected there. `vitals` runs one query per web vital, so `--group-by`,
`--csv` and `--metric` are rejected there too: it already reports all five, so
there is no metric to pick and no single table to write. Both exit with code 2
and name the preset to use instead: `trend`, `top-pages` or `referrers` for
traffic, `vitals-trend`, `slowest-pages` or `vitals-by-country` for speed.

The preset also fixes the surface, and the code enforces it both ways: a Speed
Insights option on a Web Analytics preset is a configuration error, and a
Web-Analytics-only option on a Speed Insights preset is one too. Neither is
ignored, so never reach for a flag from the other column to "see if it helps".

Groups past the limit are not dropped: they roll into a single `Others` row,
and the table prints a line underneath saying so.

## The flags worth remembering

`--help` prints every one with its defaults. These are the ones that change an
answer rather than its formatting. The **Surface** column is not advice, it is
what the code enforces: a flag marked *Speed Insights only* exits 2 on any
traffic preset, and a flag marked *Web Analytics only* exits 2 on any speed
preset.

| Flag | Surface | What it does |
| --- | --- | --- |
| `--limit N` | both | How many groups to show, 1 to 100. The rest roll into `Others` on Web Analytics; on Speed Insights it bounds grouped results per time bucket. An ungrouped query (`total`, `vitals`) has nothing to limit, so it goes unused there. |
| `--granularity BUCKET` | both | Time bucket, in either vocabulary. `week` and `year` are Web Analytics only and a configuration error on a speed preset. |
| `--metric {lcp,inp,cls,fcp,ttfb}` | Speed Insights only | Which web vital to report. A configuration error on a traffic preset, and on `vitals`, which reports all five. |
| `--percentile {75,90,95,99}` | Speed Insights only | 75 by default, as on the dashboard. Higher asks about the slow tail. |
| `--aggregation NAME` | Speed Insights only | `sum`, `count`, `min`, `max`, `p90` and so on, instead of a percentile. Not with `--percentile`. |
| `--order-by {count,value}`, `--order {asc,desc}` | Speed Insights only | Grouped queries only; on an ungrouped speed query they are an error too. Default `count` and `desc`, so a group with few measurements does not lead. |
| `--data-points` | Speed Insights only | Report how many measurements were collected instead of the metric value, aggregated with `sum`. |
| `--all` | Speed Insights only | Every project in the team instead of one. Mutually exclusive with `--project`. There is no equivalent on the traffic presets: compare those one `--project` at a time. |
| `--bucket-timezone IANA` | Speed Insights only | Aligns `1d` and `1mo` buckets; timestamps stay UTC and a sub-daily bucket ignores it, with a warning. |
| `--dataset {visits,events}`, `--event-property NAME` | Web Analytics only | Pick the custom events dataset and break it down by an event property. A configuration error on a speed preset, which has no datasets and no events. |
| `--timeout SECONDS`, `--max-retries N` | both | 30 seconds and 3 retries by default. Only 408, 429 and 5xx responses and network failures are retried. |
| `--verbose` | both | Diagnostics on stderr. Never the token. |
| `--list-presets`, `--version` | both | Print and exit 0, touching no network. |

## Reading a Speed Insights answer

`vitals` is the one to reach for when the question is broad. It issues one query
per metric because the API answers for one metric per request, and composes the
five answers into one table:

```console
$ python3 -m vercel_insights vitals
Vercel Speed Insights: prj_9RkQm2vT7xLpN4dWbYcF3sJz
Range: 2026-08-09T05:33:49Z to 2026-08-16T05:33:49Z (UTC)

metric                        p75  target  verdict
-------------------------  ------  ------  ------------
Largest Contentful Paint    2.9 s   2.5 s  over target
Interaction to Next Paint  184 ms  200 ms  meets target
Cumulative Layout Shift     0.128   0.100  over target
First Contentful Paint      1.6 s   1.8 s  meets target
Time to First Byte         412 ms  800 ms  meets target

Lower is better for all five metrics.
The target is Vercel's published 'good' threshold, so the verdict is two tier: meets target or over target.
Real Experience Score is not queryable through this API; read it on the Speed Insights dashboard.
```

Six things to carry into how you report this to a user:

- **Lower is better for all five metrics.** Never read a table of vitals as
  though a bigger number were a better one.
- **The verdict is two tier on purpose: `meets target` or `over target`.**
  Vercel publishes one "good" threshold per metric and no boundary above it, so
  there is no honest third tier. Do not invent "needs improvement" or "poor".
  The dashboard's green, amber and red bands describe a derived 0 to 100 score,
  not the raw millisecond or score value this tool reports.
- **The default is P75**, which is what the dashboard shows: the fastest 75% of
  users, excluding the slowest 25%. A P75 LCP of 2.4 s means three quarters of
  visits painted the main content within 2.4 seconds. `--percentile 90|95|99`
  asks about the tail instead.
- **Data points make the percentile trustworthy.** One data point is one
  measurement of one vital during one visit, and a visit can produce up to six.
  A P75 over 90 data points and a P75 over 18,000 are not comparable numbers.
  Say so when a row's count is small. Grouped queries order by count by default
  for exactly this reason, so a route with a handful of measurements does not
  lead the table.
- **INP usually has fewer data points than the rest**, because it needs an
  interaction. That is normal, not a bug.
- **Real Experience Score is not queryable.** Vercel states plainly that RES is
  not available through the query API this tool uses, so there is nothing to
  request, and this client will not substitute another metric for it. Asking for
  it by name is a configuration error pointing at the dashboard. RES is a
  composite derived from these five metrics, so the five are the honest answer
  to "how healthy is my site" from a command line.

Grouped Speed Insights tables have **no totals row and no share-of-total
column**, unlike the traffic tables. That is deliberate: summing the P75 of six
countries is meaningless. `data-points` is the one exception, because a sum of
measurement counts genuinely adds up.

```console
$ python3 -m vercel_insights slowest-pages --device mobile --limit 5
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

Note what `--device mobile` compiled to: `device_type eq 'mobile'`, the Speed
Insights spelling. The same flag on a traffic preset compiles to
`deviceType eq 'mobile'`. Use the shorthand flags rather than writing raw
`--filter` clauses and the spelling is handled for you.

Speed Insights needs no Observability Plus: these metrics are available on the
query surface without it. It also collects on every deployed environment,
preview included, so unlike the traffic count endpoints there is no
production-only restriction; narrow it with `--environment production` when the
user means the live site.

## When to reach for the events dataset

There are two Web Analytics datasets. `visits` is page views, and it is the
default for every traffic preset except `events`. Use `--dataset events` (or the
`events` preset, which sets it) when the question is about something a person
*did* rather than a page they loaded: signups, checkouts, button clicks, form
submissions, anything sent through `track()` in `@vercel/analytics`.

Signs the events dataset is wanted: the user names an event ("signup",
"checkout_started"), asks about conversions, or asks to break a result down by a
property attached to an event ("signups by plan", "checkouts by coupon").

Three things only exist on the events dataset, and asking for them on `visits`
is a configuration error with an exit code of 2:

- the `eventName` dimension and the `--event-name` filter
- `--event-property NAME`, which adds `eventData/NAME` to the grouping
- any `eventData/...` grouping written out longhand

None of them exist on Speed Insights at all: that API collects no custom events,
so `--dataset`, `--event-name`, `--event-property` and `--flag` on a Speed
Insights preset are configuration errors naming the reason.

The metric names differ too: `visits` returns `pageviews` and `visitors`, while
`events` returns `count` and `visitors`.

Custom events require a Vercel Pro plan or above. On a lower plan the query is
legal and simply comes back empty.

Note on `--event-property`: it adds a second grouping dimension, so rows come
back split by both event name and property value, and each dimension gets its
own column named exactly as it was requested:

```
eventName  eventData/plan  count  visitors  % count
---------  --------------  -----  --------  -------
signup     free            1,904     1,755    80.4%
signup     pro               412       388    17.4%
signup     enterprise         51        47     2.2%
---------  --------------  -----  --------  -------
TOTAL                      2,367     2,190   100.0%
```

`--csv` emits the same two columns. In `--json` every row carries a `groups`
object mapping each grouped dimension to that row's label (`"groups":
{"eventName": "signup", "eventData/plan": "free"}`), alongside `key`, which is
the first label only. Group by the property alone
(`events --group-by eventData/plan`) when the event name column is not wanted.

## Filters

Each filter flag adds one OData clause and all clauses are joined with `and`. A
comma-separated value becomes an `in (...)` set, so `--country US,CA,MX` is one
clause covering three countries.

Valid on **both** surfaces, compiled to the right spelling for whichever one is
active: `--path`, `--route`, `--country`, `--device`,
`--environment {production,preview}`.

Valid on **Web Analytics only**: `--browser`, `--os`, `--referrer`,
`--utm-source`, `--utm-medium`, `--utm-campaign`, `--event-name` (events
dataset), `--flag NAME=VALUE` (repeatable). Using one while a Speed Insights
preset is active is a configuration error that names the reason: that API does
not collect the dimension at all.

`--filter ODATA` appends a raw clause verbatim on either surface, repeatable.

The two APIs accept different operators, and this matters when writing a raw
`--filter`:

- Web Analytics: `eq`, `ne`, `in`, `and`, `or`, `not`, parentheses, and
  `startswith`. It has **no comparison operators**: `gt`, `lt`, `ge` and `le`
  are rejected by the API, so do not write them.
- Speed Insights: the same, plus `endsWith` and the numeric comparisons `>`,
  `>=`, `<`, `<=`.

Raw `--filter` text is passed through unvalidated on both surfaces, so a clause
the target API does not accept comes back as its own 400 with Vercel's message.

## Time window

`--since` defaults to `7d` and `--until` defaults to `now`. Both accept a
relative offset (`30m`, `24h`, `7d`, `4w`), `now`, `today`, `yesterday`, an ISO
date (`2026-08-01`), an ISO datetime (`2026-08-01T12:00:00Z`), or Unix
milliseconds. Everything is normalized to UTC.

The guaranteed reporting window depends on the plan: 1 month on Hobby, 12 months
on Pro, 24 months on Web Analytics Plus and Enterprise. A `--since` older than
that is allowed but may return nothing, and the tool warns on stderr past 24
months.

## Environment variables

| Variable | Required | Meaning |
| --- | --- | --- |
| `VERCEL_TOKEN` | yes, except for `--dry-run` | Vercel access token, read scope is enough. Overridable with `--token`. |
| `VERCEL_PROJECT_ID` | yes, except on a Speed Insights preset run with `--all` | Project ID or project name. Overridable with `--project`. |
| `VERCEL_TEAM_ID` | no | Team ID for a team-owned project. Overridable with `--team`. |
| `VERCEL_TEAM_SLUG` | no | Team slug instead of the ID. Never set both; it is an error. |
| `NO_COLOR` | no | Set to any value to disable colour. |

These five are the only variables the code reads. `--all`, which queries every
project in the team, is Speed Insights only: on a traffic preset it is a
configuration error, so a project is always required there. It is also mutually
exclusive with `--project`.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Success, including an empty result set. |
| 1 | The API returned an error, or the network failed after retries. |
| 2 | Configuration or usage error. Fix the command and rerun. |
| 130 | Interrupted. |

An empty result is a success, not a failure. It prints one line naming the
resolved range and the active filter. When a user sees that, the usual fixes are
a wider `--since`, a looser filter, or checking that the feature is actually
enabled on the project: Web Analytics and Speed Insights are separate
per-project switches, and each only has data from the moment it was turned on.

## Metrics beyond web vitals

The same API serves every Vercel metric. If the user asks about function
invocations, edge requests, cache behaviour, firewall actions or AI gateway
usage, run `--list-metrics` to see what their account can reach, then query by
id with `--metric`. Naming a metric is enough; no preset is needed.

Two things to tell the user honestly. Everything outside Web Analytics and Speed
Insights requires the Observability Plus add-on, so a plan without it gets an
error that no flag can fix. And for those metrics this tool knows no unit and no
target, so it reports the number without a verdict; do not describe such a value
as good or bad on its own.

## Finding the right project

One Vercel account holds many projects and every query names exactly one, so
when the user's request does not identify a project, or names one loosely ("the
blog", "our marketing site"), list them first:

```bash
python3 -m vercel_insights --list-projects
```

That returns each project's name, its `prj_` id, and whether Web Analytics and
Speed Insights actually hold data. Match the user's words against the names,
then pass either the name or the id to `--project`. Both work on every preset.

If a project shows `off` or `empty` for the feature being asked about, say so
rather than reporting an empty result as though the site had no traffic: `off`
means the feature is not enabled, `empty` means it is enabled but has collected
nothing yet, and they need different fixes.

## Gotchas worth knowing

**A project scoped token cannot read Speed Insights.** Vercel's two APIs scope
differently: Web Analytics takes a `projectId` and is project-level, while Speed
Insights is served by the observability API and scopes by account. A token
scoped to a single project therefore reads traffic fine and answers every Speed
Insights preset with `404 Observability Data not found.` That message reads like
"no data" but means "this token cannot ask". The tool says so when it happens.
If a user hits it, tell them to create an account or team scoped token at
<https://vercel.com/account/tokens>; `npx vercel@latest metrics schema` shows
what the current one can reach.

- `requestPath` is the literal URL path (`/blog/my-post`). `route` is the
  framework pattern (`/blog/[slug]`), which rolls many URLs into one row. Use
  `top-routes` and `slowest-pages` when the user wants sections rather than
  individual pages.
- A dimension name is **not portable between the surfaces**. `requestPath` on a
  Speed Insights preset is an error telling you to write `request_path`, and the
  reverse holds too. The shorthand filter flags avoid the whole problem.
- `visitors` summed across time buckets double counts a person who visited on
  two days. For distinct visitors over the whole window use `total`.
- The count endpoints behind `total` report production traffic only, so
  `--environment preview` with `total` is a configuration error. Group by
  something (for example `--group-by day`) to reach preview data. Speed Insights
  has no such restriction.
- `--json` and `--csv` are mutually exclusive. `--csv` needs a single table, so
  it is rejected with `overview` and with `vitals`, both of which issue several
  queries.
- UTM dimensions require Web Analytics Plus or Enterprise, and custom events
  require Pro. On lower plans those queries return nothing rather than failing.
  Speed Insights needs no Observability Plus.
- A Speed Insights percentile over a handful of data points is noise. Check
  `data-points` before drawing a conclusion from a small route.

## Further reading

- `README.md` for setup and worked examples.
- `docs/api-notes.md` for the verified facts about both APIs.
- `docs/cli-contract.md` for the authoritative interface.
- `examples/example_outputs.md` for fuller sample output.
