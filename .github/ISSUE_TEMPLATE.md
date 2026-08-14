# Bug report

> **Never paste a real token or a full API response.**
>
> This is a public tracker. A Vercel access token grants access to your account,
> so treat one like a password: if a token has ever appeared in text you pasted,
> revoke it immediately at <https://vercel.com/account/tokens>.
>
> Redact before you post:
>
> - Replace any token with `REDACTED`, including the value of `--token`, of
>   `VERCEL_TOKEN`, and anything after `Bearer ` in a header dump.
> - Do not attach a full API response. Real responses carry traffic data for
>   your project. Trim it to the few rows that show the problem, and rename
>   paths, hostnames, and event names if they are sensitive.
> - Project IDs, team IDs, and team slugs are identifying. Replace them with
>   `prj_example`, `team_example`, and `example-team` unless they are the point
>   of the report.
>
> `--dry-run` output is already safe to paste: it redacts the token for you.

## What happened

<!-- What the skill did. Include the exact error text if there was one. -->

## What you expected

<!-- What you expected instead, and why. -->

## Exact command

<!-- The full command, with the token replaced by REDACTED. -->

```console
$ python3 scripts/vercel_analytics.py ...
```

## `--dry-run` output

<!--
Re-run the same command with --dry-run added and paste the output here. It
sends no request, needs no token, and shows the exact URL and parameters the
skill built, which is usually enough to spot the problem.
-->

```console
$ python3 scripts/vercel_analytics.py ... --dry-run
```

## Environment

- OS and version:
- Python version (`python3 --version`):
- Skill version (`python3 scripts/vercel_analytics.py --version`):
- `requests` version (`python3 -m pip show requests`):
- Installed how (cloned the repo, installed through OpenClaw, other):

## Anything else

<!--
Optional. Relevant context: does it reproduce every time, did it work before,
does it happen on one preset only, is the project on Hobby, Pro, or Enterprise.
Plan matters for some queries: custom events need Pro or above, and UTM
dimensions need Web Analytics Plus or Enterprise.
-->
