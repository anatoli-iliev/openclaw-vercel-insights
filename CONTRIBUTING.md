# Contributing

Thanks for taking a look. This is a small, deliberately boring codebase: one
package, one runtime dependency, and a contract in `docs/` that everything is
written against. Read `docs/api-notes.md` and `docs/cli-contract.md` before
changing behaviour; where they disagree with folklore, they win.

## The layout

The tool is a package at the repository root, not a script. It covers two
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
tests/               one module per package module, plus test_security.py for
                     the invariants and test_speed_cli.py / test_speed_render.py
                     for the Speed Insights paths through cli and render
docs/                api-notes.md (verified facts), cli-contract.md (the interface)
```

The layering is the point, so keep it: `http`, `odata`, `timerange` and `render`
know nothing about either API. Everything Web Analytics specific lives in
`webanalytics.py` and everything Speed Insights specific in `speedinsights.py`,
and neither imports the other. That is what let the second surface be added
without touching the first, and a patch that reaches across the line will be
asked to move.

Both invocations must keep working:

```bash
python3 -m vercel_insights --help              # from the repository root
python3 /abs/path/vercel_insights/__main__.py  # from anywhere, uninstalled
```

## Set up a local environment

```bash
git clone https://github.com/anatoli-iliev/openclaw-vercel-insights.git
cd openclaw-vercel-insights
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install requests pytest ruff mypy types-requests
```

`requests` is the only runtime dependency; the rest are the checks below, and
they match the `dev` extra in `pyproject.toml`, so
`.venv/bin/python -m pip install -e ".[dev]"` gets the same set with the version
bounds applied, and adds the `vercel-insights` console script.

Python 3.10 or newer. Use the venv interpreter explicitly rather than activating
the shell, so it is obvious which Python ran what. The virtualenv is not
optional on Debian 12+, Ubuntu 23.04+, Fedora or Homebrew Python: those mark the
system interpreter as externally managed (PEP 668) and refuse a bare
`pip install`.

## Run the checks

All three must pass before a pull request is ready:

```bash
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/mypy --strict vercel_insights tests
```

`pyproject.toml` already points `mypy` at `vercel_insights` and `tests`, so a
bare `.venv/bin/mypy --strict` checks the same set. `pytest` picks up `tests/`
from the same file.

Two more that cost nothing and catch most mistakes:

```bash
.venv/bin/python -m vercel_insights --help
.venv/bin/python -m vercel_insights --list-presets
```

And one that costs nothing and checks the request you are actually changing,
on whichever surface you touched:

```bash
.venv/bin/python -m vercel_insights top-pages --project p --dry-run
.venv/bin/python -m vercel_insights vitals --project p --dry-run
```

No test may touch the network. `execute()` takes an injected `session`, `sleep`
and `jitter` precisely so retry behaviour is deterministic offline; pass a fake
session that returns canned payloads (`tests/helpers.py` has one, and its
`FakeSession` records `get` and `post` in one queue so a test can assert which
verb was used). If a change makes a test want a real HTTP call, the change is
wrong.

## Code style

- **Type hints everywhere.** Every function signature is annotated, and
  `mypy --strict` passes with no ignores. New code holds that line.
- **No new runtime dependencies.** `requests` is the only one, and the rest is
  the standard library. Development tools (pytest, ruff, mypy) are separate and
  are not imported by the package.
- **No em dashes.** Not in prose, code, comments, docstrings, or strings. Use a
  colon when what follows explains what precedes it, a semicolon between two
  related clauses, parentheses or paired commas for an aside, or just a full
  stop. This is enforced in review.
- **Read-only forever.** The operation allowlist in `http.py` has exactly three
  entries and there are exactly two HTTP call sites, `session.get` and
  `session.post`, both inside `execute()`. A patch that adds a fourth operation,
  a method or host taken from user input, or any write path will be declined:
  the toggle endpoints that enable and disable these features are deliberately
  absent. So will anything that puts the token anywhere except the
  `Authorization` header, or renders headers without going through
  `redact_headers`.
- **Docstrings** on public functions: what it does, its arguments, what it
  returns, and what it raises.
- **Error messages** name the offending value and the fix. No stack trace ever
  reaches the user for a configuration problem.
- **Mark an assumption as one.** The published OpenAPI document declares the
  observability `scope`, `granularity` and 200 response body as bare objects, so
  parts of `speedinsights.py` are inferred from documented CLI behaviour rather
  than read from a schema. Those spots say ASSUMPTION in a comment. If you learn
  the real shape, fix the code *and* the comment, and update
  `docs/api-notes.md`.

## Proposing a new preset

A preset is a named bundle of defaults, so adding one is cheap. First decide
which surface it belongs to, because that decides almost everything else:

| | Web Analytics | Speed Insights |
| --- | --- | --- |
| Answers | how many people came | how fast it was for them |
| `Preset` fields | `dataset`, `group_by`, `limit` | also `surface=SPEED_INSIGHTS`, `metric`, `aggregation`, `order_by`, `order`, `granularity`, `data_points` |
| Dimensions | camelCase (`requestPath`) | snake_case (`request_path`) |
| Time buckets | part of `group_by` (`day`) | the separate `granularity` field (`1d`) |

A preset queries exactly one surface and no flag changes that: `--metric` picks
which web vital a Speed Insights preset reports, it does not turn a Web
Analytics preset into a Speed Insights one. On a Web Analytics preset `--metric`
is a configuration error, and on `vitals` it is one too, since that preset
reports all five vitals and has no single metric to choose.

Then do all five steps in the same pull request, or the preset will be
half-documented:

1. **Add it to `PRESETS`** in `vercel_insights/presets.py`: a `Preset` with a
   name, dataset, grouping, limit, and a one-line description. The description
   is what `--list-presets` prints, so keep it to one clause. A Speed Insights
   preset also sets `surface=SPEED_INSIGHTS` and uses `SPEED_DATASET` for its
   `dataset` column.
2. **Add a test** in `tests/` covering the preset's resolved grouping, dataset
   and limit, and covering the request it builds. Both `build_request`
   functions are pure, so assert on the `PreparedRequest`: on Web Analytics
   that means the query parameters, on Speed Insights the JSON body, including
   which optional fields are *absent* rather than sent as null.
3. **Add a row to the right presets table in `README.md`.** There is one per
   surface.
4. **Add a row to the decision table in `SKILL.md`**, phrased the way a user
   would actually ask, in the traffic or the performance half. That table is how
   an agent picks the command, so a preset missing from it effectively does not
   exist.
5. **Add sample output to `examples/example_outputs.md`.** Capture it from a
   real run through `main()` against a stub session. Nothing in the docs is
   hand-written to look like terminal output, and nothing new should be.

Presets should answer a question people actually ask. If the answer is already
one flag away from an existing preset, a README example is usually the better
contribution.

## Reporting a bug

Open an issue at
<https://github.com/anatoli-iliev/openclaw-vercel-insights/issues> with:

- The exact command, **with `--dry-run` added** and the output pasted in. The
  dry run shows the full request with the credential redacted, including the
  whole JSON body on a Speed Insights query, which is almost always enough to
  diagnose the problem and is safe to share.
- What you expected and what happened, including the exit code.
- The output of `.venv/bin/python -m vercel_insights --version` and your Python
  version.
- If the API returned an error, the `error:` line verbatim. It carries Vercel's
  own message, which is the most specific diagnostic available.
- If a Speed Insights query came back as `invalid_response`, paste the whole
  `error:` line rather than just the code. That line names the shape this client
  actually saw ("a JSON object with 2 field(s)", "a JSON array of 3
  entry/entries"), which is the first thing the parser needs to learn a shape the
  OpenAPI document does not publish. Add the `--dry-run` output of the same
  command alongside it, so the query that produced the shape is on record too.
  Together those two are enough to open the issue on.

  The untouched payload would settle it faster still, so try the same command
  with `--json` and paste whatever it prints. Be aware of what you may get: the
  shape error is raised while the response is being normalized, before anything
  is rendered, so on that path `--json` can print nothing at all on stdout and
  repeat the same `error:` line on stderr with exit code 1. If that is what
  happens, say so in the issue rather than assuming you ran it wrong. It is a
  known rough edge, and the two items above still give us something to work
  with.

Please **never paste a token**, an unredacted `Authorization` header, or a raw
`--verbose` transcript you have not read through first. If you think you have
leaked one, revoke it at <https://vercel.com/account/tokens>.

Empty results are usually not bugs. Check that the feature is enabled on the
project (Web Analytics and Speed Insights are separate per-project switches,
each with its own package, and each only has data from the moment it was turned
on), that `--since` is inside your plan's reporting window (1 month on Hobby),
and that custom events and UTM dimensions are available on your plan. Speed
Insights itself needs no Observability Plus.

## License

Contributions are accepted under MIT-0 (MIT No Attribution), the same license as
the rest of the repository.
