# Contributing

Thanks for taking a look. This is a small, deliberately boring codebase: one
script, one runtime dependency, and a contract in `docs/` that everything is
written against. Read `docs/api-notes.md` and `docs/cli-contract.md` before
changing behaviour; where they disagree with folklore, they win.

## Set up a local environment

```bash
git clone https://github.com/anatoli-iliev/openclaw-vercel-analytics.git
cd openclaw-vercel-analytics
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install requests pytest ruff mypy types-requests
```

`requests` is the only runtime dependency; the rest are the checks below, and
they match the `dev` extra in `pyproject.toml`, so
`.venv/bin/python -m pip install -e ".[dev]"` gets the same set with the version
bounds applied.

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
.venv/bin/mypy --strict scripts/vercel_analytics.py
```

Two more that cost nothing and catch most mistakes:

```bash
.venv/bin/python scripts/vercel_analytics.py --help
.venv/bin/python scripts/vercel_analytics.py --list-presets
```

No test may touch the network. `execute()` takes an injected `session`, `sleep`
and `jitter` precisely so retry behaviour is deterministic offline; pass a fake
session that returns canned payloads. If a change makes a test want a real HTTP
call, the change is wrong.

## Code style

- **Type hints everywhere.** Every function signature is annotated, and
  `mypy --strict` passes with no ignores. New code holds that line.
- **No new runtime dependencies.** `requests` is the only one, and the rest is
  the standard library. Development tools (pytest, ruff, mypy) are separate and
  are not imported by the script.
- **No em dashes.** Not in prose, code, comments, docstrings, or strings. Use a
  colon when what follows explains what precedes it, a semicolon between two
  related clauses, parentheses or paired commas for an aside, or just a full
  stop. This is enforced in review.
- **Read-only forever.** The only HTTP call site is `session.get`. A patch that
  adds any other verb, a request body, or a write path will be declined. So will
  anything that puts the token anywhere except the `Authorization` header, or
  renders headers without going through `redact_headers`.
- **Docstrings** on public functions: what it does, its arguments, what it
  returns, and what it raises.
- **Error messages** name the offending value and the fix. No stack trace ever
  reaches the user for a configuration problem.

## Proposing a new preset

A preset is a named bundle of defaults, so adding one is cheap. Do all five
steps in the same pull request, or the preset will be half-documented:

1. **Add it to `PRESETS`** in `scripts/vercel_analytics.py`: a `Preset` with a
   name, dataset, grouping, limit, and a one-line description. The description
   is what `--list-presets` prints, so keep it to one clause.
2. **Add a test** in `tests/` covering the preset's resolved grouping, dataset
   and limit, and covering the request it builds (`build_request` is pure, so
   assert on the `PreparedRequest`, not on a live call).
3. **Add a row to the presets table in `README.md`.**
4. **Add a row to the decision table in `SKILL.md`**, phrased the way a user
   would actually ask. That table is how an agent picks the command, so a preset
   missing from it effectively does not exist.
5. **Add sample output to `examples/example_outputs.md`**, clearly marked as
   illustrative.

Presets should answer a question people actually ask. If the answer is already
one flag away from an existing preset, a README example is usually the better
contribution.

## Reporting a bug

Open an issue at
<https://github.com/anatoli-iliev/openclaw-vercel-analytics/issues> with:

- The exact command, **with `--dry-run` added** and the output pasted in. The
  dry run shows the full request with the credential redacted, which is almost
  always enough to diagnose the problem and is safe to share.
- What you expected and what happened, including the exit code.
- The output of `.venv/bin/python scripts/vercel_analytics.py --version` and
  your Python version.
- If the API returned an error, the `error:` line verbatim. It carries Vercel's
  own message, which is the most specific diagnostic available.

Please **never paste a token**, an unredacted `Authorization` header, or a raw
`--verbose` transcript you have not read through first. If you think you have
leaked one, revoke it at <https://vercel.com/account/tokens>.

Empty results are usually not bugs. Check that Web Analytics is enabled on the
project, that `--since` is inside your plan's reporting window (1 month on
Hobby), and that custom events and UTM dimensions are available on your plan.

## License

Contributions are accepted under MIT-0 (MIT No Attribution), the same license as
the rest of the repository.
