# Pull request

## Summary

<!-- What this change does, in a sentence or two. -->

## Motivation

<!--
Why the change is worth making: the bug it fixes, the question a user could not
answer before, or the friction it removes. Link the issue if there is one, for
example "Fixes #12".
-->

## How it was verified

<!--
The commands you ran and what they showed. If the change touches request
building, a --dry-run before and after is the clearest evidence.
-->

```console
$ ruff check .
$ mypy --strict vercel_insights tests
$ pytest -q
$ python3 -m vercel_insights --version
```

## Checklist

- [ ] Tests added or updated for the behaviour this change introduces, and they
      fail without the change.
- [ ] `ruff check .` is clean.
- [ ] `mypy --strict vercel_insights tests` is clean.
- [ ] `pytest -q` passes.
- [ ] Docs updated where the behaviour changed: `README.md`, `SKILL.md`,
      `docs/cli-contract.md`, and `docs/api-notes.md` if an API fact changed.
      An API fact change cites the Vercel doc page it came from.
- [ ] `CHANGELOG.md` has an entry.
- [ ] No new runtime dependency. `requests` is the only one, and everything else
      is stdlib. New dev-only tooling is called out below if any was added.
- [ ] No em dash (U+2014) anywhere in the diff: not in prose, code, comments,
      docs, or strings. Use a colon, a semicolon, parentheses, or a full stop.
- [ ] The change stays read-only and reaches no endpoint outside the
      three-entry allowlist in `http.py`: the Web Analytics query (GET), the
      observability query (POST), and the observability schema (GET). No entry
      was added, widened or made selectable by user input, and no toggle or
      other write endpoint is reachable.
- [ ] The only HTTP call sites are still one `session.get` and one
      `session.post`, both inside the allowlist dispatcher, and no code path
      takes a method or a host from user input.
- [ ] The token is still confined to the `Authorization` header. It appears in
      no URL, query parameter, log line, exception message, or rendered output,
      and `redact_headers` still covers every path that renders headers.
- [ ] The test suite still runs fully offline: no real network call, no real
      `time.sleep`, and no secret required in CI.

## Notes for the reviewer

<!--
Anything worth flagging: a trade-off you made, an alternative you rejected, a
part you are unsure about, or a follow-up you deliberately left out of scope.
-->
