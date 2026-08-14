---
name: vercel-analytics
description: >-
  Answer questions about a Vercel site's traffic from the command line, covering
  "how is my site traffic this week", "top pages on my Vercel site", "where is
  my traffic coming from", "which countries visit us", "compare mobile vs
  desktop visitors", "which browsers do people use" and "which campaign drove
  signups". Use it for anything about Vercel Web Analytics: page views,
  visitors, traffic trends over time, referrers, routes, UTM campaigns, devices,
  browsers, or custom events. Read only, HTTP GET only, and it never changes
  anything in the Vercel account.
version: 0.1.0
homepage: https://github.com/anatoli-iliev/openclaw-vercel-analytics
compatibility: openclaw >=1.0
metadata:
  security_level: L1
  openclaw:
    requires:
      env: [VERCEL_TOKEN, VERCEL_PROJECT_ID]
      bins: [python3]
    primaryEnv: VERCEL_TOKEN
    envVars:
      - name: VERCEL_TOKEN
        required: true
        description: Vercel access token, read scope is sufficient.
      - name: VERCEL_PROJECT_ID
        required: true
        description: Project ID or project name to query.
      - name: VERCEL_TEAM_ID
        required: false
        description: Team ID for team-owned projects. Omit for personal accounts.
      - name: VERCEL_TEAM_SLUG
        required: false
        description: Team slug, an alternative to VERCEL_TEAM_ID. Never set both.
      - name: NO_COLOR
        required: false
        description: Set to any value to disable coloured output.
    emoji: "📊"
    homepage: https://github.com/anatoli-iliev/openclaw-vercel-analytics
---

# Vercel Web Analytics

Query the Vercel Web Analytics API and report a project's traffic: page views,
visitors, top pages and routes, referrers, countries, devices, browsers, UTM
campaigns, and custom events.

## This skill is read-only

Everything below issues **HTTP GET and nothing else**. The Vercel Web Analytics
API is a query API with no write surface, and the script has exactly one HTTP
call site (`session.get`).

This skill cannot and does not modify deployments, projects, domains,
environment variables, team settings, DNS, or anything else in the Vercel
account. There is no code path that sends POST, PATCH, PUT, or DELETE. If a
user asks for a change to their Vercel setup, this skill is the wrong tool: say
so rather than trying.

The access token is read from the environment and is placed only in the
`Authorization` header. It never appears in a URL, a query parameter, a log
line, an error message, or any output this skill prints.

## Running it

```bash
python3 scripts/vercel_analytics.py [PRESET] [OPTIONS]
```

With no arguments at all it runs the `overview` preset for the last 7 days.

Add `--dry-run` to any command to print the exact request that would be sent,
with the token redacted, and send nothing. It works with no token configured, so
it is the safe way to show a user what a query will do before running it.

## Decision table: user phrasing to command

| The user says | Run |
| --- | --- |
| "how is my site doing", "traffic this week", "give me the numbers" | `python3 scripts/vercel_analytics.py` |
| "how did traffic move over the last month", "daily trend", "chart it by week" | `python3 scripts/vercel_analytics.py trend --since 30d` (add `--granularity week`) |
| "top pages", "most viewed pages", "what are people reading" | `python3 scripts/vercel_analytics.py top-pages --since 30d` |
| "top routes", "which route is hottest", "roll the blog posts up" | `python3 scripts/vercel_analytics.py top-routes --since 30d` |
| "where is my traffic coming from", "who links to us", "referrers" | `python3 scripts/vercel_analytics.py referrers --since 30d` |
| "which countries", "where are visitors located" | `python3 scripts/vercel_analytics.py countries --since 30d` |
| "mobile vs desktop", "what devices" | `python3 scripts/vercel_analytics.py devices --since 30d` |
| "which browsers", "how much Safari" | `python3 scripts/vercel_analytics.py browsers --since 30d` |
| "which operating systems", "Windows vs Mac" | `python3 scripts/vercel_analytics.py operating-systems --since 30d` |
| "which campaign worked", "utm breakdown", "did the newsletter land" | `python3 scripts/vercel_analytics.py campaigns --since 30d` |
| "how many signups", "custom events", "conversions" | `python3 scripts/vercel_analytics.py events --since 30d` |
| "which campaign drove signups" | `python3 scripts/vercel_analytics.py events --event-name signup --since 30d --group-by utmCampaign` |
| "how many visitors in total", "unique visitors for the month" | `python3 scripts/vercel_analytics.py total --since 30d` |
| "how did /pricing do" | `python3 scripts/vercel_analytics.py trend --path /pricing --since 30d` |
| "traffic from the US only" | add `--country US` to any command |
| "give me a CSV", "put it in a spreadsheet" | add `--csv` (not available on `overview`) |
| "give me JSON", "pipe it to jq" | add `--json` |
| "what would that request look like" | add `--dry-run` |

## Presets

Run `python3 scripts/vercel_analytics.py --list-presets` for this table at any time.

| Preset | Command | Groups by | Default limit |
| --- | --- | --- | --- |
| `overview` (default) | `vercel_analytics.py` | `day`, then `requestPath`, then `referrerHostname` (3 calls) | 5 per table |
| `trend` | `vercel_analytics.py trend` | `day` | 100 |
| `top-pages` | `vercel_analytics.py top-pages` | `requestPath` | 10 |
| `top-routes` | `vercel_analytics.py top-routes` | `route` | 10 |
| `referrers` | `vercel_analytics.py referrers` | `referrerHostname` | 10 |
| `countries` | `vercel_analytics.py countries` | `country` | 10 |
| `devices` | `vercel_analytics.py devices` | `deviceType` | 10 |
| `browsers` | `vercel_analytics.py browsers` | `browserName` | 10 |
| `operating-systems` | `vercel_analytics.py operating-systems` | `osName` | 10 |
| `campaigns` | `vercel_analytics.py campaigns` | `utmCampaign` | 10 |
| `events` | `vercel_analytics.py events` | `eventName` | 10 |
| `total` | `vercel_analytics.py total` | nothing, one ungrouped count | n/a |

Any explicit flag overrides a preset value, with one exception: `overview` runs
three queries of its own, so `--group-by`, `--event-property` and `--csv` are
rejected there with exit code 2. Pick `trend`, `top-pages` or `referrers` when
the user wants a different grouping or a CSV.

Groups past the limit are not dropped: they roll into a single `Others` row,
and the table prints a line underneath saying so.

## When to reach for the events dataset

There are two datasets. `visits` is page views, and it is the default for every
preset except `events`. Use `--dataset events` (or the `events` preset, which
sets it) when the question is about something a person *did* rather than a page
they loaded: signups, checkouts, button clicks, form submissions, anything sent
through `track()` in `@vercel/analytics`.

Signs the events dataset is wanted: the user names an event ("signup",
"checkout_started"), asks about conversions, or asks to break a result down by a
property attached to an event ("signups by plan", "checkouts by coupon").

Three things only exist on the events dataset, and asking for them on `visits`
is a configuration error with an exit code of 2:

- the `eventName` dimension and the `--event-name` filter
- `--event-property NAME`, which adds `eventData/NAME` to the grouping
- any `eventData/...` grouping written out longhand

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

`--path`, `--route`, `--country`, `--device`, `--browser`, `--os`, `--referrer`,
`--utm-source`, `--utm-medium`, `--utm-campaign`, `--event-name` (events only),
`--flag NAME=VALUE` (repeatable), `--environment {production,preview}`, and
`--filter ODATA` for a raw clause.

The API supports `eq`, `ne`, `in`, `and`, `or`, `not`, and parentheses. It has
**no comparison operators**: do not write `gt`, `lt`, `ge`, or `le` in a
`--filter`, they will be rejected.

## Time window

`--since` defaults to `7d` and `--until` defaults to `now`. Both accept a
relative offset (`30m`, `24h`, `7d`, `4w`), `now`, `today`, `yesterday`, an ISO
date (`2026-08-01`), an ISO datetime (`2026-08-01T12:00:00Z`), or Unix
milliseconds. Everything is normalized to UTC.

The guaranteed reporting window depends on the plan: 1 month on Hobby, 12 months
on Pro, 24 months on Web Analytics Plus and Enterprise. A `--since` older than
that is allowed but may return nothing, and the script warns on stderr past 24
months.

## Environment variables

| Variable | Required | Meaning |
| --- | --- | --- |
| `VERCEL_TOKEN` | yes, except for `--dry-run` | Vercel access token, read scope is enough. Overridable with `--token`. |
| `VERCEL_PROJECT_ID` | yes | Project ID or project name. Overridable with `--project`. |
| `VERCEL_TEAM_ID` | no | Team ID for a team-owned project. Overridable with `--team`. |
| `VERCEL_TEAM_SLUG` | no | Team slug instead of the ID. Never set both; it is an error. |
| `NO_COLOR` | no | Set to any value to disable colour. |

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Success, including an empty result set. |
| 1 | The API returned an error, or the network failed after retries. |
| 2 | Configuration or usage error. Fix the command and rerun. |
| 130 | Interrupted. |

An empty result is a success, not a failure. It prints one line naming the
resolved range and the active filter. When a user sees that, the usual fixes are
a wider `--since`, a looser filter, or checking that Web Analytics is actually
enabled on the project.

## Gotchas worth knowing

- `requestPath` is the literal URL path (`/blog/my-post`). `route` is the
  framework pattern (`/blog/[slug]`), which rolls many URLs into one row. Use
  `top-routes` when the user wants sections rather than individual posts.
- `visitors` summed across time buckets double counts a person who visited on
  two days. For distinct visitors over the whole window use `total`.
- The count endpoints behind `total` report production traffic only, so
  `--environment preview` with `total` is a configuration error. Group by
  something (for example `--group-by day`) to reach preview data.
- `--json` and `--csv` are mutually exclusive, and `--csv`, `--group-by` and
  `--event-property` are rejected with `overview` because it issues three
  separate queries.
- UTM dimensions require Web Analytics Plus or Enterprise. On lower plans
  `campaigns` returns nothing rather than failing.

## Further reading

- `README.md` for setup and worked examples.
- `docs/api-notes.md` for the verified API facts this is built on.
- `examples/example_outputs.md` for full sample output.
