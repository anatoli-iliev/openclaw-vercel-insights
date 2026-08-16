# vercel-insights

Your Vercel traffic **and** your Core Web Vitals, answered in one command line.

```console
$ vercel-insights vitals

metric                        p75  target  verdict
-------------------------  ------  ------  ------------
Largest Contentful Paint    2.9 s   2.5 s  over target
Interaction to Next Paint  184 ms  200 ms  meets target
Cumulative Layout Shift     0.128   0.100  over target
First Contentful Paint      1.6 s   1.8 s  meets target
Time to First Byte         412 ms  800 ms  meets target
```

Two Vercel APIs, one CLI: Web Analytics for how many people came and where from,
Speed Insights for how fast the site felt when they got there.

## Start here

Two ways in. Pick the one that sounds like you.

- **"I use OpenClaw and I just want to ask it questions."** Start with
  [Set it up in OpenClaw](#set-it-up-in-openclaw), just below. No programming
  needed. About five minutes, mostly waiting for downloads.
- **"I want a command line tool."** Skip to
  [Use it from a terminal](#use-it-from-a-terminal).

### Set it up in OpenClaw

Four steps. Copy each grey block whole, paste it into your terminal, press
Enter. After each one there is a line telling you what you should see, so you
always know whether it worked before moving on.

#### Step 1: install it

```bash
clawhub install vercel-insights
```

**You should see:** `Installed vercel-insights v1.0.1 -> ...`

#### Step 2: make it runnable

One time only. Two things need fixing that the installer cannot do for you: it
cannot mark the program as runnable, and this tool needs one Python library
called `requests`.

```bash
SKILL=~/.openclaw/workspace/skills/vercel-insights
chmod +x "$SKILL/bin/vercel-insights"
python3 -m venv "$SKILL/.venv"
"$SKILL/.venv/bin/python" -m pip install requests
"$SKILL/bin/vercel-insights" --version
```

**You should see:** `vercel-insights 1.0.1` on the last line. Anything installed
here goes inside the skill's own folder and touches nothing else on your
computer.

#### Step 3: give it a Vercel token

A token is a password that lets this skill read your Vercel data. Make one at
**<https://vercel.com/account/tokens>**.

When Vercel asks about **scope**, choose your **account** or your **team**. Do
not choose a single project. This matters more than it sounds like it does, and
[the note below](#the-one-thing-that-trips-people-up) explains why. Read access
is all this skill ever needs; it cannot change anything.

Vercel shows the token once, so copy it before closing the page. Then:

```bash
openclaw config set skills.entries.vercel-insights.apiKey PASTE_YOUR_TOKEN_HERE
openclaw skills check
```

**You should see:** `vercel-insights` listed as ready, not under "Missing
requirements".

Prefer clicking to typing? `openclaw dashboard` opens the Control UI, where
**Skills, vercel-insights, Save key** does the same thing.

If your Vercel projects belong to a **team** rather than to you personally, add
this one extra line (find the ID under Team Settings, General):

```bash
openclaw config set skills.entries.vercel-insights.env.VERCEL_TEAM_ID team_xxxxxxxx
```

#### Step 4: ask your agent something

That is the whole setup. Now talk to OpenClaw normally:

> **How's my site traffic this week?**
>
> **Is my site fast?**
>
> **Which pages are slowest?**
>
> **Where is my traffic coming from?**

If you have more than one Vercel project, the agent will list them and ask which
one you mean rather than guessing. You can also just say **"which Vercel
projects do I have?"**

#### If something went wrong

| What you saw | What to do |
| --- | --- |
| `Permission denied` | Step 2 was skipped. Run it. |
| `'requests' is not importable by this interpreter` | Step 2 was skipped, or its last line failed. Run it again and read the output. |
| `openclaw skills check` still says missing | The token did not save. Re-run step 3 and check for a typo in the config path. |
| `404 Observability Data not found.` | Your token is scoped to one project. Make a new account-scoped one, step 3. |
| Speed questions work, traffic questions fail with 403 or 404 | The project belongs to a team. Add `VERCEL_TEAM_ID`, end of step 3. |
| Empty results, no error | That project genuinely has no data for that period, or the feature is switched off for it in Vercel. |

Longer walkthrough, with every failure we actually hit and how to tell them
apart: **[docs/openclaw-setup.md](docs/openclaw-setup.md)**.

### Use it from a terminal

```bash
# 1. Get it
git clone https://github.com/anatoli-iliev/openclaw-vercel-insights.git
cd openclaw-vercel-insights
python3 -m venv .venv && .venv/bin/python -m pip install requests

# 2. A token, from https://vercel.com/account/tokens
#    Scope it to the ACCOUNT or TEAM, not to a single project. See the note below.
export VERCEL_TOKEN="..."

# 3. Which project? This lists them, and needs nothing else configured.
.venv/bin/python -m vercel_insights --list-projects

# 4. Ask it something. Use the name or the prj_ id from step 3.
.venv/bin/python -m vercel_insights vitals --project acme-docs
.venv/bin/python -m vercel_insights --project acme-docs        # last 7 days of traffic
```

> <a id="the-one-thing-that-trips-people-up"></a>
> **The one thing that trips people up.** A token scoped to a *single project*
> reads traffic fine but cannot read Speed Insights, because Vercel serves those
> from an account-scoped API. Symptom: `404 Observability Data not found.`, which
> reads like "no data" but means "this token cannot ask". An account or team
> scoped token does both.

Nothing to configure beyond that, and nothing is written to disk. Set
`VERCEL_PROJECT_ID` if you get tired of `--project`. Add `--dry-run` to any
command to see the exact request without sending it, no token required.

**Where to go next**

| I want to | Read |
| --- | --- |
| See what the output looks like, for everything | [examples/example_outputs.md](examples/example_outputs.md) |
| Know which presets exist | [Presets](#presets), or run `--list-presets` |
| Fail a build when the site gets slower | [Guarding performance in CI](#guarding-performance-in-ci) |
| Query something other than traffic and vitals | [Beyond web vitals](#beyond-web-vitals) |
| Understand what this can and cannot reach | [Plans, windows and what is out of reach](#plans-windows-and-what-is-out-of-reach) |
| Check the security posture | [Security and permissions](#security-and-permissions) |
| Set it up as an OpenClaw skill | [Set it up in OpenClaw](#set-it-up-in-openclaw), then [docs/openclaw-setup.md](docs/openclaw-setup.md) for the detail |

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
- **Safe by construction.** Read-only against a five-endpoint allowlist, and
  the token never leaves the `Authorization` header. See
  [Security and permissions](#security-and-permissions).

## Setup in detail

The quick start above is the whole of it for most people. This section covers
the parts that vary.

### Running it from anywhere

`bin/vercel-insights` works from any directory and prefers a `.venv` beside the
checkout, so an installed copy needs no `PATH` or working-directory setup:

```bash
/path/to/openclaw-vercel-insights/bin/vercel-insights vitals
```

`python3 -m vercel_insights` is equivalent from inside the checkout.

### Installing

From ClawHub, which is the shortest route and the one
[Set it up in OpenClaw](#set-it-up-in-openclaw) walks through step by step:

```bash
clawhub install vercel-insights
```

It lands in `~/.openclaw/workspace/skills/vercel-insights`. Two things the
installer cannot do for you, both one-time:

```bash
SKILL=~/.openclaw/workspace/skills/vercel-insights
chmod +x "$SKILL/bin/vercel-insights"                       # the exec bit is not preserved
python3 -m venv "$SKILL/.venv" && "$SKILL/.venv/bin/python" -m pip install requests
```

From a local checkout instead, which does preserve the exec bit:

```bash
openclaw skills install /path/to/openclaw-vercel-insights --as vercel-insights
```

Either way, save the token where the gateway reads it rather than exporting
anything:

```bash
openclaw config set skills.entries.vercel-insights.apiKey YOUR_TOKEN
openclaw skills check          # confirms the requirement resolved
```

The Control UI does the same thing under Skills, vercel-insights, Save key, and
`openclaw skills info vercel-insights` prints both routes.

Full walkthrough, including every failure worth recognising and how to tell them
apart: **[docs/openclaw-setup.md](docs/openclaw-setup.md)**.

The gateway runs as its own process, so a variable exported in an interactive
shell may not reach it. `openclaw configure` writes it where the gateway reads
it. To keep the token out of the config file entirely:

```bash
openclaw config set skills.entries.vercel-insights.apiKey \
  --ref-provider default --ref-source env --ref-id VERCEL_TOKEN
```

Python 3.10 or newer, and `requests` is the only thing outside the standard
library. The virtualenv in the quick start is not ceremony: Debian 12+, Ubuntu
23.04+, Fedora and Homebrew Python all mark the system interpreter as externally
managed (PEP 668), so a bare `pip install requests` there stops with
`error: externally-managed-environment` before installing anything. If you would
rather not keep a `.venv`, `pip install --user requests` works where user
installs are still permitted, as does your distribution's own package
(`apt install python3-requests`).

Already have `requests` importable? `python3 -m vercel_insights` works from the
repository root as is. From anywhere else,
`python3 /abs/path/to/vercel_insights/__main__.py` works too: the entry point
repairs `sys.path` before importing. And `pip install -e .` adds a
`vercel-insights` console script on `PATH`, which is the same entry point.

### The token, and why its scope matters

Create one at <https://vercel.com/account/tokens>. Read scope is enough; this
tool never writes.

Vercel's two APIs scope differently, and a project scoped token silently reaches
only one of them:

| Preset family | API scoped by | Project scoped token |
| --- | --- | --- |
| Web Analytics (`overview`, `top-pages`, `events`, ...) | `projectId` | works |
| Speed Insights (`vitals`, `slowest-pages`, ...) | account | `404 Observability Data not found.` |

To see what the current token can actually reach:
`npx vercel@latest metrics schema`.

### Turning the features on

Web Analytics and Speed Insights are two separate per-project switches, each
with its own package in the app: `@vercel/analytics`
(<https://vercel.com/docs/analytics/quickstart>) and `@vercel/speed-insights`
(<https://vercel.com/docs/speed-insights/quickstart>). Data exists only from the
moment each is turned on, and only from deployed builds, not local development.

`--list-projects` reports both per project: `data` collected, `empty` for
enabled but nothing yet, `off` for not enabled.

### Environment variables

Every one has a matching flag that takes precedence.

```bash
export VERCEL_TOKEN="vercel_tok_xxxxxxxxxxxxxxxxxxxxxxxx"
export VERCEL_PROJECT_ID="prj_XXXXXXXXXXXXXXXX"   # or just use --project
# export VERCEL_TEAM_ID="team_XXXXXXXXXXXXXXXX"   # team-owned projects
# export VERCEL_ORG_ID="team_XXXXXXXXXXXXXXXX"    # written by `vercel link`
```

`.env.example` documents all of them. Nothing is read from or written to a file
by the tool itself, so load them however you like:
`set -a; . ./.env; set +a`.

## What it looks like

Real output from the code, with synthetic data. The full set for every preset is
in [examples/example_outputs.md](examples/example_outputs.md).

### Traffic, at a glance

Bare `vercel-insights` gives you the last 7 days.

```console
$ vercel-insights --since 7d
Vercel Web Analytics: prj_9RkQm2vT7xLpN4dWbYcF3sJz
Range: 2026-08-09T05:23:38Z to 2026-08-16T05:23:38Z (UTC)

  pageviews  48,072
  visitors   32,280
  visitors is a sum of the buckets below, so someone who came on two days counts twice;
  run the total preset for distinct visitors over the window

By day
  2026-08-08  6,120  ██████████████████
  2026-08-09  4,980  ██████████████
  2026-08-10  7,840  ███████████████████████
  2026-08-11  8,310  ████████████████████████
  2026-08-12  7,905  ███████████████████████
  2026-08-13  7,402  █████████████████████
  2026-08-14  5,515  ████████████████

Top pages (top 5)
requestPath            pageviews  visitors  % pageviews
---------------------  ---------  --------  -----------
/                         18,420    11,930        38.3%
/docs/getting-started      9,310     6,845        19.4%
/pricing                   7,204     5,588        15.0%
/blog/shipping-faster      4,126     3,390         8.6%
/changelog                 2,870     2,115         6.0%
Others                     6,142     4,102        12.8%
---------------------  ---------  --------  -----------
TOTAL                     48,072    33,970       100.0%

Others is not a real value: it is every group beyond --limit 5, collapsed by the API into one bucket.

Top referrers (top 5)
referrerHostname      pageviews  visitors  % pageviews
--------------------  ---------  --------  -----------
(none)                   21,044    13,980        43.8%
google.com               14,310     9,720        29.8%
news.ycombinator.com      6,890     6,012        14.3%
github.com                3,402     2,560         7.1%
x.com                     2,426     1,798         5.0%
--------------------  ---------  --------  -----------
TOTAL                    48,072    34,070       100.0%
```

### Your Core Web Vitals against Vercel's targets

```console
$ vercel-insights vitals
Vercel Speed Insights: prj_9RkQm2vT7xLpN4dWbYcF3sJz
Range: 2026-08-08T00:00:00Z to 2026-08-15T00:00:00Z (UTC)

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

### Which pages are slow, and for whom

```console
$ vercel-insights slowest-pages
Vercel Speed Insights: prj_9RkQm2vT7xLpN4dWbYcF3sJz (slowest-pages, p75)
Range: 2026-08-08T00:00:00Z to 2026-08-15T00:00:00Z (UTC)

route         p75_lcp
------------  -------
/blog/[slug]    5.0 s
/docs/[slug]    3.2 s
/pricing        2.7 s
/               2.2 s

Metric: vercel.speed_insights.lcp_ms (Largest Contentful Paint)
Target: 2.5 s or less
Lower is better for all five metrics.
The target is Vercel's published 'good' threshold, so the verdict is two tier: meets target or over target.
```
```console
$ vercel-insights vitals-by-device
Vercel Speed Insights: prj_9RkQm2vT7xLpN4dWbYcF3sJz (vitals-by-device, p75)
Range: 2026-08-08T00:00:00Z to 2026-08-15T00:00:00Z (UTC)

device_type  p75_lcp
-----------  -------
mobile         4.1 s
tablet         3.0 s
desktop        2.1 s

Metric: vercel.speed_insights.lcp_ms (Largest Contentful Paint)
Target: 2.5 s or less
Lower is better for all five metrics.
The target is Vercel's published 'good' threshold, so the verdict is two tier: meets target or over target.
```

The device breakdown is usually the answer to "why is the field score worse than
my local numbers".

### Anything else, machine readable

```bash
vercel-insights devices --json | jq '.rows[] | {(.key): .metrics.pageviews}'
vercel-insights trend --granularity week --since 8w --csv > traffic.csv
```

## Beyond web vitals

Speed Insights is one family among many on the same query API. Function
invocations, edge requests, image transformations, ISR operations, firewall
actions and AI gateway usage are all queryable by id:

```console
$ vercel-insights --list-metrics                      # what this account can reach
$ vercel-insights --metric vercel.function_invocation.count --aggregation sum
$ vercel-insights --metric vercel.request.count --group-by route --limit 10
```

Metric ids are not hardcoded here. `--list-metrics` asks the API, which is the
only thing that knows what your account can reach, and it prints each metric's
unit, aggregations and dimensions so you know what to group by.

For a metric outside the five web vitals this tool claims nothing it cannot
know: no unit, so the value is a plain number rather than being labelled seconds
on a guess; no target, so no verdict; and no aggregation is sent unless you name
one, so the server applies the metric's own default rather than a percentile
that may be meaningless for a count.

> **Plan note.** Web Analytics and Speed Insights are queryable on any plan.
> Every other metric requires
> [Observability Plus](https://vercel.com/docs/observability/observability-plus).
> Without it these queries return an error, which is a plan limit rather than
> anything this tool can work around.

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

- **Read-only against a five-endpoint allowlist.** One module-level table in
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
