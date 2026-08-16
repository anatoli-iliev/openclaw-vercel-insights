# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.3] - 2026-08-16

Raises the `requests` floor past every published advisory. No code changes.

### Security

- **`requests>=2.28` becomes `requests>=2.33.0`.** ClawHub's scanner flagged the
  old bound on the 1.0.1 submission: it permitted releases with known
  vulnerabilities. Enumerating the GitHub Advisory Database for the package
  gives eight advisories, and the newest applicable one is
  **GHSA-gc5v-m9x4-r6x2**, insecure temporary file reuse in
  `extract_zipped_paths()`, fixed in **2.33.0**. The three that a reader is more
  likely to have heard of are all older: the `Proxy-Authorization` leak
  (GHSA-j8r2-6x86-q33q, fixed 2.31.0), a `Session` not honouring `verify=False`
  on later requests (GHSA-9wx4-h78v-vm56, 2.32.0), and the `.netrc` credential
  leak via malicious URLs (GHSA-9hjg-9r4m-mvj7, 2.32.4).

  A floor of 2.32.4 would therefore have looked sufficient and been wrong, which
  is the argument for enumerating the advisory database rather than recalling
  the well-known CVEs.

  This is a security floor, not a feature floor: nothing in this codebase needs
  an API newer than 2.28. It is expressed as `>=` rather than a pin so that
  users and distributions stay free to move forward.

  `requests` 2.33.0 declares `requires-python >=3.10`, exactly matching this
  project's own floor, so the supported Python range is unchanged. Verified by
  installing `requests==2.33.0` specifically, rather than the latest release,
  and running the full suite against it: 1080 passed.

## [1.0.2] - 2026-08-16

Documentation only. No behaviour changes, and no change to what the tool can
reach. Released so that the ClawHub listing carries the rewritten setup
instructions, since `README.md` ships inside the published bundle.

### Fixed

Two blockers that stop a freshly installed copy from running at all. Both were
found by installing the **published** 1.0.1 into a scratch directory and running
it as a new user would, and neither is visible from a source checkout, which is
why 1080 tests, a security review and a clean publish all missed them:

- `clawhub install` does not preserve the executable bit. `bin/vercel-insights`
  is `100755` in git and arrives at `644`, so the first thing a new user sees is
  `Permission denied`.
- `requests` is absent from most system interpreters, so even invoking the
  launcher through `sh` stops at the dependency error.

Neither is a code defect, and neither is fixable from inside the package. They
are now handled in step two of the setup instructions instead of being left for
the reader to discover.

### Changed

- **`README.md` now opens by asking which kind of reader it has** and routes
  OpenClaw users to a four step walkthrough, each step stating what should
  appear before continuing, so a reader always knows whether it worked. Adds a
  symptom to fix table for the failures a beginner is most likely to hit. The
  terminal instructions are unchanged, moved below the OpenClaw ones. Every
  command in the new text was run before it was written down.
- **`docs/openclaw-setup.md`** gains the ClawHub install route alongside the
  local checkout one, and a troubleshooting row for `Permission denied`.
- **`.github/CODEOWNERS`** now covers `README.md` and `docs/openclaw-setup.md`.
  Their setup sections are copy-paste blocks containing a `chmod` and a
  `pip install`, so a change there runs on a reader's machine as surely as a
  code change does, and is read by people trusting it precisely because they
  cannot audit it.

### Known, and deliberately not changed here

`requests>=2.28` permits releases with known vulnerabilities, which ClawHub's
scanner noted on the 1.0.1 submission. Raising the floor changes what gets
installed, so it belongs in its own release rather than inside a documentation
patch.

## [1.0.1] - 2026-08-16

Documentation accuracy only. No behaviour changes, and no change to what the
tool can reach.

### Fixed

- Two comments described the operation allowlist as holding **four** endpoints
  when it holds five. Both were written before `GET /v10/projects` was added for
  `--list-projects`, and were missed when it was: `.env.example`, in the note
  explaining why a read-scope token is sufficient, and `.github/CODEOWNERS`, in
  the note explaining why `http.py` is called out separately. `README.md`,
  `SKILL.md` and `docs/cli-contract.md` already said five.

  The count understated the surface rather than overstating it, so nothing was
  presented as safer than it is. It still warrants a patch release: the sentence
  is a security claim, it sits in the file a user has open while pasting an API
  token into it, and anyone who counts the table and finds five learns that the
  documentation cannot be trusted on precisely the subject where it has to be.

- The link references at the foot of this file pointed `[Unreleased]` at a
  comparison against v0.2.0 and carried no entry for 1.0.0, so both resolved
  wrongly.

## [1.0.0] - 2026-08-16

First published release. Neither 0.1.0 nor 0.2.0 was ever released, so
everything below arrives at once for anyone installing this from ClawHub; the
earlier entries stay as development history.

What it does: reports a Vercel project's traffic through the Web Analytics API
and its speed through Speed Insights, with 19 presets, project discovery,
performance budgets that can fail a build, and any other Vercel observability
metric by id.

Why 1.0 rather than 0.3. The parts that face a user are settled and exercised:
the request shapes for both APIs are verified against the live API rather than
inferred, the response parsing is pinned to real payloads, and 1080 tests run on
Python 3.10 through 3.14. The interface is one worth committing to.

Two things are honestly short of that bar, and are documented as such rather
than smoothed over:

- Metrics outside Web Analytics and Speed Insights require the Observability
  Plus add-on, and have never been exercised against an account that has it.
  They are built against the published schema and a real metric listing, but no
  such query has been answered.
- Whether an empty `projectIds` really means "every project" for `--all` is
  inferred from the field's name, not confirmed.

Neither affects the paths most people will use, and both are named in
`docs/api-notes.md`.


## [0.2.0] - 2026-08-14

Speed Insights arrives, and with it the project's scope grows from traffic to
traffic and speed. The skill, the repository and the module are renamed to
match, and the single script becomes a package.

In summary: Core Web Vitals with published targets, a project listing so the
right project is easy to find, performance budgets that can fail a build, any
Vercel observability metric queryable by id, and a metric listing that asks the
API what an account can actually reach. Several request and response shapes were
corrected against the live API along the way, since the OpenAPI document
declares them as bare objects; each is marked VERIFIED in `docs/api-notes.md`.

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

- A Web Analytics 403 or 404 with no team configured now says that a team owned
  project needs its team named. Vercel is explicit that `teamId` or `slug` must
  be on every request for a team owned project and omitted for a personal one,
  and a refusal for the missing-team reason is indistinguishable from one for
  no access. The hint is withheld when a team was already given, since
  suggesting the fix someone already applied misdirects them.


- **`bin/vercel-insights`**, a launcher that works from any working directory.
  `python3 -m vercel_insights` needs the caller's working directory to be the
  skill root and `requests` importable by the first `python3` on `PATH`, and
  neither holds when an agent invokes the skill from its own workspace. The
  launcher resolves its own location, following symlinks, prefers a virtualenv
  sitting beside the skill, and hands off to the entry point. `SKILL.md` now
  documents it as the way to run this when the skill is installed rather than
  checked out.


- **Any observability metric is queryable by id**, not only the five web vitals:
  `--metric vercel.function_invocation.count` and the other ninety-odd the API
  serves. Naming a metric selects the right surface on its own, so no unrelated
  preset has to be chosen first. Ids are deliberately not enumerated in the
  source: `--list-metrics` asks the API, which is the only thing that knows what
  an account can reach, and a hardcoded copy would go stale the moment Vercel
  adds one.
- For a metric outside the web vitals nothing is claimed that cannot be known.
  No unit, so the value renders as a plain number rather than being labelled
  seconds on a guess. No published target, so no verdict. No aggregation is sent
  unless one is named, so the server applies the metric's own default rather
  than a percentile that would be meaningless for a count. Grouping dimensions
  are accepted without a local list, because there is none to check against and
  inventing one would reject grouping the API supports; the web vitals keep
  their checked list.
- A `metric` preset, for querying one metric by id with no other opinions.

  **Verification note.** The web vitals path is verified end to end against a
  live account. These other metrics are not: they require Observability Plus,
  which the account used for testing does not have. The ids in the tests come
  from a real schema listing, so they are real, but no query using one has been
  answered.


- **`--budget NAME=VALUE`**, repeatable, which fails with exit code **3** when a
  web vital exceeds the limit. The code is deliberately not 1: a blown budget is
  a successful run reporting bad news, and a CI step usually wants to tell that
  apart from the API being unreachable. A metric with no data does not fail,
  because an empty window means the measurement is missing rather than the site
  being slower, and failing on absent data trains people to ignore the check.
  The boundary belongs to pass, matching how Vercel phrases its own targets
  ("2.5 seconds or less"). A grouped query refuses a budget, since there is a
  number per group rather than one to compare. Under `--json` or `--csv` the
  report goes to stderr so machine output stays parseable.
- `examples/github-action-budget.yml`, a copyable workflow. It is scheduled
  rather than per-commit on purpose: real user measurements accumulate from
  visitors and do not change the instant a deploy lands.


- **`--list-projects`**, because one account holds many and every query names
  exactly one. It shows each project's name and `prj_` id alongside whether Web
  Analytics and Speed Insights hold data, told apart three ways: `data`
  collected, `empty` for enabled but nothing yet, `off` for not enabled. Those
  last two both produce an empty query and need different fixes, so they are
  worth distinguishing. Needs no project of its own, which is the point.
- Naming no project now prints that same table in the error, instead of only
  restating which flag is missing. It costs one request, only on that path.


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

### Added

- **`--list-metrics`**, which asks the API which metrics an account can actually
  query, optionally filtered by a prefix. Vercel documents the schema endpoint
  as the source of truth for the metrics, dimensions and aggregations available
  to an account, so this is what to reach for when a query is refused: it
  answers "does this metric exist for me" outright instead of by inference. It
  needs only a token, no project and no owner, so it works even when a query
  cannot be built at all.
- A top level JSON array is now accepted from the API. The schema endpoint
  answers with one, while every query endpoint answers with an object, and a
  query that returns an array is reported as an unusable response rather than
  parsed.

### Fixed

- **A project name worked for traffic and silently returned nothing for speed.**
  The Web Analytics endpoints accept "the project identifier or the project
  name", but Speed Insights scopes by `projectIds` and wants identifiers, so
  `--project my-site` produced real numbers on one surface and an empty result
  on the other. A name is now resolved to its id from the project record this
  client already reads for the owner, so one request answers both and both
  surfaces behave the same. The previous warning about `prj_` prefixes is gone,
  because the situation it warned about no longer arises.

- **The `vitals` headline number was the first time bucket, not the window.**
  An ungrouped query comes back as a time series because the server picks a
  granularity when none is given, and this client showed row zero as though it
  were the aggregate. On a real project that read 6.7 seconds where the true
  P75 for the week was 2.9. The response carries a `summary` block holding the
  window aggregate, and that is now what an ungrouped result reports. It cannot
  be computed locally: a percentile does not average, so the P75 of 168 hourly
  P75s is not the P75 of the week. A requested granularity still returns its
  buckets, so `vitals-trend` is unaffected.
- **`--granularity` never worked on Speed Insights.** The object was sent as
  `{"interval": "1d"}`, which the API refuses: a granularity "must divide a day
  evenly or be a single week, month or year". The real shape is a unit and a
  count, verified live: `{"hours": 1}`, `{"days": 1}`, `{"weeks": 1}`,
  `{"months": 1}`, `{"years": 1}`.
- Row values are read from the computed rollup key (the metric id with dots as
  underscores, then the aggregation) rather than by probing for a lone number.
  That is deterministic, and it lets a row carrying both a value and a data
  point count be read at all, which the previous ambiguity guard refused.

- **A project scoped token now says why Speed Insights is unavailable.** Vercel
  answers `404 Observability Data not found.` when a credential cannot reach the
  observability API at all, which reads as "your project has no data" and sends
  the reader looking in the wrong place entirely. Web Analytics scopes by
  project and works with such a token; Speed Insights scopes by account and does
  not. The tool now explains that, names the fix, and says which presets still
  work. Only a 404 from the observability surface is annotated: a 403 is a
  different problem with a different answer.
- `VERCEL_ORG_ID` is read as the Speed Insights scope owner. It is Vercel's own
  name for the owning account and `vercel link` writes it, so a standard setup
  often supplies the owner already. `VERCEL_OWNER_ID` and `--owner-id` still
  take precedence.

Found by two rounds of adversarial review before this version was released, so
none of these ever reached a published version. Each was reproduced first.

- **The `vitals` preset silently ignored `--metric`.** It took a code path that
  never read the flag, so an explicit request was discarded with exit 0. Worst
  of all, `vitals --metric res` ran all five queries instead of refusing, which
  defeated the Real Experience Score refusal every other preset enforces. Now
  rejected, with the Real Experience Score message taking precedence over the
  generic one.
- **`overview` sent an untranslated granularity.** Given the alias spellings
  (`1d`, `1h`, `1mo`) it put them straight onto the wire as `by=1d`, which the
  Web Analytics API does not accept. Only the overview path skipped the
  translator that `trend` already used.
- **An ungrouped Speed Insights value of exactly `0.0` read as "no data".**
  Emptiness was decided by truthiness, but a Cumulative Layout Shift of `0.0` is
  a perfect score, not an absent measurement. The two surfaces now decide
  emptiness differently.
- **The team did not reach the Speed Insights scope object.** It travelled only
  as a query parameter, but `POST /v2/observability/query` declares an empty
  `parameters` list in the OpenAPI document, so it accepts no query parameters
  at all, while the Web Analytics endpoints explicitly declare `teamId` and
  `slug`. A team owned project would likely have resolved against the personal
  account. The team is now carried inside `scope` on both scope types, with the
  inert query parameter still sent so the two channels cannot disagree.
- **`NaN`, `Infinity` and `-Infinity` could escape as a traceback**, because
  `json.loads` accepts all three by default. Refused at the parse boundary.
- **A number that overflowed to infinity slipped past that guard.** `1e999` is
  well formed JSON and never reaches `parse_constant`, so it became `inf`,
  rendered as `inf` in a table, and came back out of `--json` as a bare
  `Infinity`, which a strict consumer such as `jq` rejects. The parsed body is
  now walked and any non-finite number refused.
- **Redirects were followed**, so the operation allowlist bound only the first
  hop and a redirect could have handed the bearer token to another host. Both
  call sites pass `allow_redirects=False` and report a 3xx as an error naming
  the location, so the allowlist binds every hop. That error also reports the
  real attempt count rather than always claiming one.
- **Control characters from a response reached the terminal.** Row labels were
  hardened first, then review found three more values from the same response
  that bypassed the boundary: a `Location` header, Vercel's own `error.message`,
  and a metric name claimed off a row, which becomes a table column header and a
  CSV header cell. A hostile `error.message` could blank the screen and forge a
  reassuring second line under the tool's own `error:` prefix. All of them are
  sanitized now, and `sanitize_label` moved to the package root so every layer
  can reach it.
- **A very short credential turned messages into confetti.** The scrubber
  replaced the bare token wherever it appeared, so a token of `t` rewrote
  `https` as `h<redacted><redacted>ps`. Substring matching now requires a
  credential long enough to be one; the whole header value is still scrubbed
  regardless of length, so nothing is exposed.
- **The Speed Insights `scope` was the wrong shape, confirmed against the live
  API.** The OpenAPI document declares `scope` as a bare object, so the shape
  was inferred, and the inference was wrong: a real query answered HTTP 400
  naming `scope.ownerId` (a string) and `scope.projectIds` (an array) as the
  required fields. There is no `type` discriminator and no team key. The scope
  is now `{"type": "project", "ownerId": ..., "projectIds": [...]}`: a union
  discriminated on `type` whose project variant carries both fields, which took
  two 400s to pin down because the OpenAPI document describes none of it. A team
  is simply its own
  owner, and a personal account id is read once per run from `GET /v2/user`,
  read once per run from the project's own record (`GET /v9/projects/{idOrName}`,
  whose `accountId` is the owner), which joins the operation allowlist as a
  fourth read-only entry. New `--owner-id` / `VERCEL_OWNER_ID` skip that call.
  The account endpoint was tried first and is not equivalent: a team scoped
  token has no personal user, and it answers `404 User not found.`
- **A team slug alone could have answered for the wrong account.** A slug names
  a team but is not an account id, so it cannot fill `ownerId`; falling through
  to the personal-account lookup would have returned confident numbers for the
  wrong account. It is refused now, naming `--team` and `--owner-id` as the fix.
  A slug still works for every Web Analytics preset.
- Multi-line API error bodies keep their line structure instead of being
  flattened into `\x0a` escapes. These bodies are usually pretty-printed JSON,
  and escaping the newlines made the one thing worth reading unreadable. Lines
  after the first are indented, so a server supplied string still cannot reach
  column zero and forge a line that looks like this tool's own output.
- A `--project` value that does not look like a project id now warns on the
  Speed Insights surface, which scopes by `projectIds`. Web Analytics accepts a
  project name there; this surface is likely to return nothing instead.
- **A missing `requests` dumped a traceback as the tool's very first output.**
  The documented invocation is `python3 -m vercel_insights`, so anyone whose
  `python3` is a system interpreter without the dependency met a raw
  `ModuleNotFoundError` before seeing anything else, which named the wrong
  problem: the import line rather than the interpreter. The entry point now
  explains it, names the interpreter it is running under, and, when a virtualenv
  beside the package already has the dependency, names that interpreter as the
  fix. Found by running the documented command on a clean shell.
- **The stdlib shadowing repair covered only one invocation form.** This package
  contains `http.py`, which shadows the standard library `http` that `requests`
  imports. The repair was guarded to the plain-script path, leaving
  `python3 -m vercel_insights` breakable by a stray `sys.path` entry, confirmed
  before fixing. It is unconditional now.

### Documentation

- `docs/openclaw-setup.md`, a complete walkthrough of installing this as an
  OpenClaw skill, checked against a real install rather than written from help
  text. It covers token scope, the virtualenv, saving the credential where the
  gateway can read it, when the team is required and why it cannot be a hard
  requirement, and a troubleshooting table in which every row is a failure that
  actually happened during setup rather than one imagined for the occasion.


- Setup documents the two routes that actually work, both printed by
  `openclaw skills info` itself: the Control UI's Save key, and
  `openclaw config set skills.entries.vercel-insights.apiKey`.
  `openclaw configure --section skills` reports skill status but does **not**
  prompt for a key, and documenting it as the way in sent people to a dead end.
  Checked against a real install this time rather than read out of a help text.


- Setup now leads with `openclaw configure --section skills`, which prompts for
  the credential and writes it where the gateway reads it. The skill already
  declared `primaryEnv`, which is what maps a prompted key onto
  `skills.entries.<slug>.apiKey`, so this needed no code change, only
  documenting. The hand-edited JSON is kept as the last resort rather than the
  only route.
- The secret-reference form is documented too:
  `openclaw config set skills.entries.vercel-insights.apiKey --ref-provider
  default --ref-source env --ref-id VERCEL_TOKEN` keeps the token in the
  environment or a secrets provider instead of in `openclaw.json`.
- Both files now say that the gateway runs as its own process, so a variable
  exported in an interactive shell may never reach it.


- The skill description is 310 characters, down from 1090. `openclaw skills
  list` renders it in a narrow column, where the previous keyword-packed
  paragraph wrapped over eight lines and read as noise. Breadth of phrasing
  belongs in the decision table, which the agent reads once it has chosen the
  skill; the description only has to get it chosen. A test keeps it short.
- **Only `VERCEL_TOKEN` gates the skill now.** `requires.env` also listed
  `VERCEL_PROJECT_ID`, which is a hard gate, so the skill reported "needs setup"
  even with a working token. The project is discoverable: without one configured
  the skill lists the account's projects and asks. A test pins the gate to the
  token alone.
- `SKILL.md` documents configuration through `~/.openclaw/openclaw.json` under
  `skills.entries`, including that `apiKey` is what `primaryEnv` maps to, so the
  credential can live with the skill rather than in a shell profile.


- `SKILL.md` opens with the flow an agent actually follows: check configuration,
  identify the project, then run and read back. It says when to prefer `--json`
  (only when a figure has to be computed rather than relayed), what each exit
  code means for what to tell the user, and that an empty result is a success to
  be reported as "no data" rather than a failure. It also says outright never to
  state a number that was not measured, which is the most damaging thing an
  agent could do with this tool.
- The decision table covers project discovery, budgets, the metric listing and
  arbitrary metrics, none of which it previously mentioned.
- The endpoint allowlist in `SKILL.md` listed three of five entries, because a
  find-and-replace corrected the sentence above it and left the table alone.
  Corrected, and now pinned by tests that compare the documented operations,
  their methods and the declared environment variables against the code, in both
  directions.


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

[Unreleased]: https://github.com/anatoli-iliev/openclaw-vercel-insights/compare/v1.0.3...HEAD
[1.0.3]: https://github.com/anatoli-iliev/openclaw-vercel-insights/compare/v1.0.2...v1.0.3
[1.0.2]: https://github.com/anatoli-iliev/openclaw-vercel-insights/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/anatoli-iliev/openclaw-vercel-insights/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/anatoli-iliev/openclaw-vercel-insights/releases/tag/v1.0.0
[0.2.0]: https://github.com/anatoli-iliev/openclaw-vercel-insights/releases/tag/v0.2.0
[0.1.0]: https://github.com/anatoli-iliev/openclaw-vercel-insights/releases/tag/v0.1.0
