# Example outputs

Every `console` block below is captured output from
`scripts/vercel_analytics.py`. The alignment, the totals, the percentages, the
sparkline bars and the exact wording of the error lines all came out of the
real code, through `main()`. Nothing here was typed by hand to look like
terminal output. The one `sh` block, under "How these were produced", is
environment setup rather than output.

Two lines per block are added by the capture rather than printed by the
program: the `$ ...` command line at the top and the `[exit code N]` marker at
the bottom. Everything between them is verbatim. Blocks that show an error or
`--verbose` show stdout followed by stderr, because that is what a terminal
would interleave.

## How these were produced

There is no Vercel token in this repository and no request has ever left it.
The client was pointed at a stub session that answers from one synthetic
dataset: 31,699 page view records for a fictional docs and marketing site, each
carrying a visitor id, a day, a URL path, a referrer hostname, a country, a
device type, a browser, an operating system and a UTM campaign, plus 2,713
custom event records. The stub groups, counts, sorts and truncates those
records the way `docs/api-notes.md` says the API does, and hands back payloads
in the documented shape.

That matters for reading the numbers: **every table below is a real aggregation
of the same records**, so the cross-table arithmetic in the next section is a
property of the data rather than a promise. Two things were pinned so the
capture is reproducible: the clock was fixed at 2026-08-14T09:00:00Z, and in
the rate limit block the sleep between retries and its jitter were stubbed out,
so that run did not really take 24 seconds. Every printed line is real.

Every command uses the same project and the same window:

```sh
export VERCEL_PROJECT_ID=prj_9xQ2vB7kLmT4dRnW
export VERCEL_TOKEN=...   # not needed for --dry-run
```

`--since 2026-08-07 --until 2026-08-14` is seven daily buckets, 2026-08-07
through 2026-08-13 inclusive.

## How the numbers relate

Page views tie out everywhere. Every grouped report of the visits dataset below
totals exactly 31,699 page views, and so does the count endpoint. That holds
even for the tables with an `Others` row, because the limit overflow is
collapsed into that bucket rather than dropped.

Visitor columns do not tie out, and they are not supposed to. A grouped report
counts distinct visitors *within each group* and the totals row adds those up,
so anybody who appears in two groups is counted twice. Only the count endpoint
reports distinct visitors across the whole window: 12,479.

| Report | Grouping | pageviews total | visitors total |
| --- | --- | ---: | ---: |
| `trend` | `day` | 31,699 | 15,794 |
| `top-pages` | `requestPath` | 31,699 | 26,543 |
| `top-routes` | `route` | 31,699 | 24,458 |
| `referrers` | `referrerHostname` | 31,699 | 15,029 |
| `countries` | `country` | 31,699 | 12,479 |
| `devices` | `deviceType` | 31,699 | 12,479 |
| `browsers` | `browserName` | 31,699 | 12,479 |
| `operating-systems` | `osName` | 31,699 | 12,479 |
| `campaigns` | `utmCampaign` | 31,699 | 13,634 |
| `total` | none (count endpoint) | 31,699 | 12,479 |

Read that table as follows.

- The `pageviews total` column is constant. It is the same 31,699 page views
  sliced 9 different ways.
- `country`, `deviceType`, `browserName` and `osName` each total exactly 12,479
  visitors, matching the count endpoint. In this fixture a visitor keeps one
  country, one device, one browser and one operating system for the whole
  window, so nobody lands in two groups and there is nothing to double count.
- Every other grouping totals more. `trend` sums to 15,794, which is 3,315
  above the distinct total, and that difference is exactly the number of repeat
  appearances on a second or third day. `top-pages` is the extreme at 26,543,
  because 60.8% of visitors read more than one page.

Three more relationships worth checking against the blocks:

- The site has 12 URL paths with traffic and the `top-pages` default limit is
  10, so the `Others` row holds the remaining 2: 30,756 page views in the ten
  named rows plus 943 in `Others` is 31,699. The same happens in `referrers`,
  which has 12 groups (hostnames plus direct traffic), and in `countries`,
  which has 13.
- `top-routes` and `top-pages` are the same traffic counted differently:
  `/docs/getting-started` and `/docs/cli` roll up into `/docs/[slug]`, so 12
  paths become 7 routes. That fits inside the limit, which is why the route
  table has no `Others` row, and it still totals 31,699 page views.
- The two dimension events table is the one dimension events table split finer.
  Both total 2,713 events, and the three `signup` rows add back up to the
  single `signup` row: 1,656 = 1,163 + 396 + 97.

## overview (the default preset)

Run with no preset at all and you get this. It is the only preset that issues
more than one request: the API cannot return an ungrouped total and grouped
rows in a single call, so the report is composed from a daily aggregate, a top
pages aggregate and a top referrers aggregate.

The tables use `--limit 5` here rather than the usual 10, so their `Others`
rows are larger than in the standalone sections further down. The page view
totals are identical either way.

```console
$ python3 scripts/vercel_analytics.py --since 2026-08-07 --until 2026-08-14
Vercel Web Analytics: prj_9xQ2vB7kLmT4dRnW
Range: 2026-08-07T00:00:00Z to 2026-08-14T00:00:00Z (UTC)

  pageviews  31,699
  visitors   15,794
  visitors is a sum of the buckets below, so someone who came on two days counts twice;
  run the total preset for distinct visitors over the window

By day
  2026-08-07  4,199  ████████████████
  2026-08-08  2,797  ███████████
  2026-08-09  2,603  ██████████
  2026-08-10  5,472  █████████████████████
  2026-08-11  6,275  ████████████████████████
  2026-08-12  5,306  ████████████████████
  2026-08-13  5,047  ███████████████████

Top pages (top 5)
requestPath            pageviews  visitors  % pageviews
---------------------  ---------  --------  -----------
/                          9,039     6,488        28.5%
/pricing                   4,744     3,945        15.0%
/docs/getting-started      4,378     3,703        13.8%
/blog/shipping-faster      3,390     2,951        10.7%
/docs/api-reference        2,762     2,468         8.7%
Others                     7,386     5,605        23.3%
---------------------  ---------  --------  -----------
TOTAL                     31,699    25,160       100.0%

Others is not a real value: it is every group beyond --limit 5, collapsed by the API into one bucket.

Top referrers (top 5)
referrerHostname      pageviews  visitors  % pageviews
--------------------  ---------  --------  -----------
google.com               10,198     4,724        32.2%
(none)                    8,754     4,026        27.6%
news.ycombinator.com      3,946     1,911        12.4%
github.com                3,069     1,475         9.7%
x.com                     2,021       990         6.4%
Others                    3,711     1,859        11.7%
--------------------  ---------  --------  -----------
TOTAL                    31,699    14,985       100.0%

Others is not a real value: it is every group beyond --limit 5, collapsed by the API into one bucket.

[exit code 0]
```

## trend

Page views per time bucket, in chronological order. Change the bucket with
`--granularity` (`hour`, `day`, `week`, `month`, `year`).

```console
$ python3 scripts/vercel_analytics.py trend --since 2026-08-07 --until 2026-08-14
Vercel Web Analytics: prj_9xQ2vB7kLmT4dRnW (trend)
Range: 2026-08-07T00:00:00Z to 2026-08-14T00:00:00Z (UTC)

day         pageviews  visitors  % pageviews
----------  ---------  --------  -----------
2026-08-07      4,199     2,098        13.2%
2026-08-08      2,797     1,371         8.8%
2026-08-09      2,603     1,316         8.2%
2026-08-10      5,472     2,732        17.3%
2026-08-11      6,275     3,150        19.8%
2026-08-12      5,306     2,637        16.7%
2026-08-13      5,047     2,490        15.9%
----------  ---------  --------  -----------
TOTAL          31,699    15,794       100.0%

[exit code 0]
```

## top-pages

Exact URL paths, without query parameters.

```console
$ python3 scripts/vercel_analytics.py top-pages --since 2026-08-07 --until 2026-08-14
Vercel Web Analytics: prj_9xQ2vB7kLmT4dRnW (top-pages)
Range: 2026-08-07T00:00:00Z to 2026-08-14T00:00:00Z (UTC)

requestPath             pageviews  visitors  % pageviews
----------------------  ---------  --------  -----------
/                           9,039     6,488        28.5%
/pricing                    4,744     3,945        15.0%
/docs/getting-started       4,378     3,703        13.8%
/blog/shipping-faster       3,390     2,951        10.7%
/docs/api-reference         2,762     2,468         8.7%
/changelog                  1,836     1,720         5.8%
/blog/why-edge-caching      1,500     1,404         4.7%
/docs/cli                   1,337     1,275         4.2%
/about                        942       901         3.0%
/docs/deploying               828       787         2.6%
Others                        943       901         3.0%
----------------------  ---------  --------  -----------
TOTAL                      31,699    26,543       100.0%

Others is not a real value: it is every group beyond --limit 10, collapsed by the API into one bucket.

[exit code 0]
```

## top-routes

The same traffic grouped by framework route pattern instead of URL path.

```console
$ python3 scripts/vercel_analytics.py top-routes --since 2026-08-07 --until 2026-08-14
Vercel Web Analytics: prj_9xQ2vB7kLmT4dRnW (top-routes)
Range: 2026-08-07T00:00:00Z to 2026-08-14T00:00:00Z (UTC)

route         pageviews  visitors  % pageviews
------------  ---------  --------  -----------
/docs/[slug]      9,305     6,597        29.4%
/                 9,039     6,488        28.5%
/blog/[slug]      5,280     4,270        16.7%
/pricing          4,744     3,945        15.0%
/changelog        1,836     1,720         5.8%
/about              942       901         3.0%
/contact            553       537         1.7%
------------  ---------  --------  -----------
TOTAL            31,699    24,458       100.0%

[exit code 0]
```

## referrers

Referrer hostnames. Direct traffic has no referrer at all, so the API returns a
null group label and the client renders it as `(none)` rather than as an empty
cell.

```console
$ python3 scripts/vercel_analytics.py referrers --since 2026-08-07 --until 2026-08-14
Vercel Web Analytics: prj_9xQ2vB7kLmT4dRnW (referrers)
Range: 2026-08-07T00:00:00Z to 2026-08-14T00:00:00Z (UTC)

referrerHostname      pageviews  visitors  % pageviews
--------------------  ---------  --------  -----------
google.com               10,198     4,724        32.2%
(none)                    8,754     4,026        27.6%
news.ycombinator.com      3,946     1,911        12.4%
github.com                3,069     1,475         9.7%
x.com                     2,021       990         6.4%
reddit.com                1,336       698         4.2%
linkedin.com                847       436         2.7%
bing.com                    502       253         1.6%
duckduckgo.com              436       214         1.4%
t.co                        284       145         0.9%
Others                      306       157         1.0%
--------------------  ---------  --------  -----------
TOTAL                    31,699    15,029       100.0%

Others is not a real value: it is every group beyond --limit 10, collapsed by the API into one bucket.

[exit code 0]
```

## countries

Traffic by ISO country code.

```console
$ python3 scripts/vercel_analytics.py countries --since 2026-08-07 --until 2026-08-14
Vercel Web Analytics: prj_9xQ2vB7kLmT4dRnW (countries)
Range: 2026-08-07T00:00:00Z to 2026-08-14T00:00:00Z (UTC)

country  pageviews  visitors  % pageviews
-------  ---------  --------  -----------
US          11,366     4,511        35.9%
DE           4,654     1,860        14.7%
GB           3,744     1,478        11.8%
IN           3,206     1,257        10.1%
BR           2,233       892         7.0%
CA           1,795       667         5.7%
FR           1,515       572         4.8%
NL             971       389         3.1%
AU             755       286         2.4%
JP             572       223         1.8%
Others         888       344         2.8%
-------  ---------  --------  -----------
TOTAL       31,699    12,479       100.0%

Others is not a real value: it is every group beyond --limit 10, collapsed by the API into one bucket.

[exit code 0]
```

## devices

Traffic by device type.

```console
$ python3 scripts/vercel_analytics.py devices --since 2026-08-07 --until 2026-08-14
Vercel Web Analytics: prj_9xQ2vB7kLmT4dRnW (devices)
Range: 2026-08-07T00:00:00Z to 2026-08-14T00:00:00Z (UTC)

deviceType  pageviews  visitors  % pageviews
----------  ---------  --------  -----------
desktop        21,509     8,507        67.9%
mobile          8,959     3,489        28.3%
tablet          1,231       483         3.9%
----------  ---------  --------  -----------
TOTAL          31,699    12,479       100.0%

[exit code 0]
```

## browsers

Traffic by browser.

```console
$ python3 scripts/vercel_analytics.py browsers --since 2026-08-07 --until 2026-08-14
Vercel Web Analytics: prj_9xQ2vB7kLmT4dRnW (browsers)
Range: 2026-08-07T00:00:00Z to 2026-08-14T00:00:00Z (UTC)

browserName       pageviews  visitors  % pageviews
----------------  ---------  --------  -----------
Chrome               15,223     6,006        48.0%
Safari                8,266     3,191        26.1%
Firefox               3,698     1,471        11.7%
Edge                  2,618     1,044         8.3%
Samsung Internet      1,077       432         3.4%
Opera                   817       335         2.6%
----------------  ---------  --------  -----------
TOTAL                31,699    12,479       100.0%

[exit code 0]
```

## operating-systems

Traffic by operating system.

```console
$ python3 scripts/vercel_analytics.py operating-systems --since 2026-08-07 --until 2026-08-14
Vercel Web Analytics: prj_9xQ2vB7kLmT4dRnW (operating-systems)
Range: 2026-08-07T00:00:00Z to 2026-08-14T00:00:00Z (UTC)

osName     pageviews  visitors  % pageviews
---------  ---------  --------  -----------
Windows        9,710     3,851        30.6%
macOS          8,642     3,402        27.3%
iOS            5,814     2,248        18.3%
Android        4,376     1,724        13.8%
Linux          2,511     1,002         7.9%
Chrome OS        646       252         2.0%
---------  ---------  --------  -----------
TOTAL         31,699    12,479       100.0%

[exit code 0]
```

## campaigns

Traffic by `utm_campaign`. UTM dimensions need Web Analytics Plus or
Enterprise; on a lower plan `docs/api-notes.md` records that this comes back
empty rather than failing. Untagged traffic carries no campaign value, so it
arrives as the same null label that direct traffic does.

```console
$ python3 scripts/vercel_analytics.py campaigns --since 2026-08-07 --until 2026-08-14
Vercel Web Analytics: prj_9xQ2vB7kLmT4dRnW (campaigns)
Range: 2026-08-07T00:00:00Z to 2026-08-14T00:00:00Z (UTC)

utmCampaign      pageviews  visitors  % pageviews
---------------  ---------  --------  -----------
(none)              24,736    10,212        78.0%
launch-week          2,984     1,469         9.4%
product-hunt         1,655       796         5.2%
newsletter-june      1,425       719         4.5%
docs-refresh           899       438         2.8%
---------------  ---------  --------  -----------
TOTAL               31,699    13,634       100.0%

[exit code 0]
```

## events

Custom events (Pro and above), grouped by event name.

```console
$ python3 scripts/vercel_analytics.py events --since 2026-08-07 --until 2026-08-14
Vercel Web Analytics: prj_9xQ2vB7kLmT4dRnW (events)
Range: 2026-08-07T00:00:00Z to 2026-08-14T00:00:00Z (UTC)

eventName      count  visitors  % count
-------------  -----  --------  -------
signup         1,656     1,506    61.0%
subscribe        835       795    30.8%
contact_sales    222       214     8.2%
-------------  -----  --------  -------
TOTAL          2,713     2,515   100.0%

[exit code 0]
```

## events broken out by an event property

`--event-property plan` adds `eventData/plan` as a second grouping dimension.
The API accepts at most two, and sends them as repeated `by` parameters rather
than one comma joined value, which the dry run shows exactly:

```console
$ python3 scripts/vercel_analytics.py events --event-property plan --since 2026-08-07 --until 2026-08-14 --dry-run
GET https://api.vercel.com/v1/query/web-analytics/events/aggregate

Query parameters:
  projectId  prj_9xQ2vB7kLmT4dRnW
  by         eventName
  by         eventData/plan
  since      2026-08-07T00:00:00Z
  until      2026-08-14T00:00:00Z
  limit      10

Headers:
  Accept         application/json
  Authorization  Bearer <redacted>
  User-Agent     vercel-analytics-skill/0.1.0

Encoded URL (never contains the token):
  https://api.vercel.com/v1/query/web-analytics/events/aggregate?projectId=prj_9xQ2vB7kLmT4dRnW&by=eventName&by=eventData%2Fplan&since=2026-08-07T00%3A00%3A00Z&until=2026-08-14T00%3A00%3A00Z&limit=10

Nothing was sent. No credential is printed above.

[exit code 0]
```

The response to that request keys its rows `eventData`, not `eventData/plan`,
as `docs/api-notes.md` warns. The client maps the base key back onto the
dimension you asked for, and gives **each dimension its own column**, so the
event name and the plan are both readable on every row:

```console
$ python3 scripts/vercel_analytics.py events --event-property plan --since 2026-08-07 --until 2026-08-14
Vercel Web Analytics: prj_9xQ2vB7kLmT4dRnW (events)
Range: 2026-08-07T00:00:00Z to 2026-08-14T00:00:00Z (UTC)

eventName      eventData/plan  count  visitors  % count
-------------  --------------  -----  --------  -------
signup         free            1,163     1,089    42.9%
subscribe      free              441       429    16.3%
signup         pro               396       392    14.6%
subscribe      pro               317       311    11.7%
signup         enterprise         97        97     3.6%
contact_sales  pro                94        94     3.5%
contact_sales  enterprise         78        77     2.9%
subscribe      enterprise         77        77     2.8%
contact_sales  free               50        50     1.8%
-------------  --------------  -----  --------  -------
TOTAL                          2,713     2,616   100.0%

[exit code 0]
```

`--csv` emits the same two label columns ahead of the metrics:

```console
$ python3 scripts/vercel_analytics.py events --event-property plan --csv --since 2026-08-07 --until 2026-08-14
eventName,eventData/plan,count,visitors
signup,free,1163,1089
subscribe,free,441,429
signup,pro,396,392
subscribe,pro,317,311
signup,enterprise,97,97
contact_sales,pro,94,94
contact_sales,enterprise,78,77
subscribe,enterprise,77,77
contact_sales,free,50,50

[exit code 0]
```

`--json` carries both labels per row in a `groups` object keyed by the
dimension names as you wrote them. `key` remains the first label, for callers
that only ever group by one thing. Filtering to a single event keeps this short
enough to show whole, `raw` payload included:

```console
$ python3 scripts/vercel_analytics.py events --event-property plan --event-name signup --json --since 2026-08-07 --until 2026-08-14
{
  "query": {
    "since": "2026-08-07T00:00:00Z",
    "until": "2026-08-14T00:00:00Z",
    "limit": 10,
    "groupBy": [
      "eventName",
      "eventData/plan"
    ],
    "filter": "eventName eq 'signup'"
  },
  "range": {
    "since": "2026-08-07T00:00:00Z",
    "until": "2026-08-14T00:00:00Z"
  },
  "dataset": "events",
  "groupBy": [
    "eventName",
    "eventData/plan"
  ],
  "isCount": false,
  "metrics": [
    "count",
    "visitors"
  ],
  "rows": [
    {
      "key": "signup",
      "groups": {
        "eventName": "signup",
        "eventData/plan": "free"
      },
      "timestamp": null,
      "metrics": {
        "count": 1163,
        "visitors": 1089
      }
    },
    {
      "key": "signup",
      "groups": {
        "eventName": "signup",
        "eventData/plan": "pro"
      },
      "timestamp": null,
      "metrics": {
        "count": 396,
        "visitors": 392
      }
    },
    {
      "key": "signup",
      "groups": {
        "eventName": "signup",
        "eventData/plan": "enterprise"
      },
      "timestamp": null,
      "metrics": {
        "count": 97,
        "visitors": 97
      }
    }
  ],
  "totals": {
    "count": 1656,
    "visitors": 1578
  },
  "raw": {
    "version": 1,
    "query": {
      "since": "2026-08-07T00:00:00Z",
      "until": "2026-08-14T00:00:00Z",
      "limit": 10,
      "groupBy": [
        "eventName",
        "eventData/plan"
      ],
      "filter": "eventName eq 'signup'"
    },
    "data": [
      {
        "eventName": "signup",
        "eventData": "free",
        "count": 1163,
        "visitors": 1089
      },
      {
        "eventName": "signup",
        "eventData": "pro",
        "count": 396,
        "visitors": 392
      },
      {
        "eventName": "signup",
        "eventData": "enterprise",
        "count": 97,
        "visitors": 97
      }
    ]
  }
}

[exit code 0]
```

## total

The count endpoint: one ungrouped total, production traffic only. This is the
only way to get distinct visitors over the whole window, for the reason the
summary table above spells out.

```console
$ python3 scripts/vercel_analytics.py total --since 2026-08-07 --until 2026-08-14
Vercel Web Analytics: prj_9xQ2vB7kLmT4dRnW (total)
Range: 2026-08-07T00:00:00Z to 2026-08-14T00:00:00Z (UTC)

  pageviews  31,699
  visitors   12,479

[exit code 0]
```

## JSON output

`--json` prints the normalized rows and totals, plus the untouched API payload
under `raw` so nothing is lost in translation.

```console
$ python3 scripts/vercel_analytics.py devices --since 2026-08-07 --until 2026-08-14 --json
{
  "query": {
    "since": "2026-08-07T00:00:00Z",
    "until": "2026-08-14T00:00:00Z",
    "limit": 10,
    "groupBy": [
      "deviceType"
    ]
  },
  "range": {
    "since": "2026-08-07T00:00:00Z",
    "until": "2026-08-14T00:00:00Z"
  },
  "dataset": "visits",
  "groupBy": [
    "deviceType"
  ],
  "isCount": false,
  "metrics": [
    "pageviews",
    "visitors"
  ],
  "rows": [
    {
      "key": "desktop",
      "groups": {
        "deviceType": "desktop"
      },
      "timestamp": null,
      "metrics": {
        "pageviews": 21509,
        "visitors": 8507
      }
    },
    {
      "key": "mobile",
      "groups": {
        "deviceType": "mobile"
      },
      "timestamp": null,
      "metrics": {
        "pageviews": 8959,
        "visitors": 3489
      }
    },
    {
      "key": "tablet",
      "groups": {
        "deviceType": "tablet"
      },
      "timestamp": null,
      "metrics": {
        "pageviews": 1231,
        "visitors": 483
      }
    }
  ],
  "totals": {
    "pageviews": 31699,
    "visitors": 12479
  },
  "raw": {
    "version": 1,
    "query": {
      "since": "2026-08-07T00:00:00Z",
      "until": "2026-08-14T00:00:00Z",
      "limit": 10,
      "groupBy": [
        "deviceType"
      ]
    },
    "data": [
      {
        "deviceType": "desktop",
        "pageviews": 21509,
        "visitors": 8507
      },
      {
        "deviceType": "mobile",
        "pageviews": 8959,
        "visitors": 3489
      },
      {
        "deviceType": "tablet",
        "pageviews": 1231,
        "visitors": 483
      }
    ]
  }
}

[exit code 0]
```

## CSV output

`--csv` writes a header row of the group column or columns followed by the
metric columns, then one row per group. It goes through `csv.writer`, so a
label containing a comma or a quote stays correct.

```console
$ python3 scripts/vercel_analytics.py devices --since 2026-08-07 --until 2026-08-14 --csv
deviceType,pageviews,visitors
desktop,21509,8507
mobile,8959,3489
tablet,1231,483

[exit code 0]
```

## Dry run

`--dry-run` prints the exact request that would be sent and sends nothing. It
needs no token, which makes it the safest way to check a filter before spending
a rate limit on it. The `Authorization` header is redacted here and everywhere
else this client renders headers. This block was captured with no
`VERCEL_TOKEN` in the environment at all.

```console
$ python3 scripts/vercel_analytics.py top-pages --since 2026-08-07 --until 2026-08-14 --country US --dry-run
GET https://api.vercel.com/v1/query/web-analytics/visits/aggregate

Query parameters:
  projectId  prj_9xQ2vB7kLmT4dRnW
  by         requestPath
  since      2026-08-07T00:00:00Z
  until      2026-08-14T00:00:00Z
  limit      10
  filter     country eq 'US'

Headers:
  Accept         application/json
  Authorization  Bearer <redacted>
  User-Agent     vercel-analytics-skill/0.1.0

Encoded URL (never contains the token):
  https://api.vercel.com/v1/query/web-analytics/visits/aggregate?projectId=prj_9xQ2vB7kLmT4dRnW&by=requestPath&since=2026-08-07T00%3A00%3A00Z&until=2026-08-14T00%3A00%3A00Z&limit=10&filter=country+eq+%27US%27

Nothing was sent. No credential is printed above.

[exit code 0]
```

## An empty result

An empty result set is a success, not an error: exit code 0, one line naming
the resolved range and the active filter, and no empty table or traceback.

```console
$ python3 scripts/vercel_analytics.py events --event-name checkout_started --since 2026-08-07 --until 2026-08-14
No events data for project prj_9xQ2vB7kLmT4dRnW (grouped by eventName) between 2026-08-07T00:00:00Z and 2026-08-14T00:00:00Z with eventName eq 'checkout_started'. Try a wider --since, or relax the filter.

[exit code 0]
```

## Configuration errors

Every validation rule runs before anything touches the network, so a mistake
costs no request and no rate limit. Each message names the offending value and
the fix, and exits 2.

```console
$ python3 scripts/vercel_analytics.py top-pages --since 2026-08-07 --until 2026-08-14 --limit 500
error: --limit 500 is outside the API bounds of 1 to 100; pick a value in that range, and note that groups past the limit are not dropped, they roll into a single 'Others' row

[exit code 2]
```

```console
$ python3 scripts/vercel_analytics.py top-pages --group-by contry --since 2026-08-07 --until 2026-08-14
error: unknown dimension 'contry' for the visits dataset. Did you mean 'country'? Valid dimensions: hour, day, week, month, year, country, deviceType, environment, requestPath, referrerHostname, osName, browserName, route, utmSource, utmMedium, utmCampaign, utmContent, utmTerm, flags, plus flags/<name>

[exit code 2]
```

## A permission error

Vercel's `error.message` is surfaced verbatim, because it is the most specific
diagnostic available and it is written for humans. No stack trace reaches the
user. API and network failures exit 1, configuration mistakes exit 2.

```console
$ python3 scripts/vercel_analytics.py top-pages --since 2026-08-07 --until 2026-08-14
error: HTTP 403 (forbidden): Not authorized to access the project prj_9xQ2vB7kLmT4dRnW. The token is missing the read scope for this team.

[exit code 1]
```

## Rate limiting

429 is retried. The wait comes from `Retry-After` when the response carries
one, otherwise from `error.limit.resetMs` or `error.limit.reset`, otherwise
from exponential backoff. Jitter is added on top, and was set to zero for this
capture so the printed delays are reproducible. Once the retries are used up
the error is reported with the attempt count. `--verbose` puts the request and
the retry decisions on stderr, with the token redacted there too.

```console
$ python3 scripts/vercel_analytics.py trend --since 2026-08-07 --until 2026-08-14 --max-retries 2 --verbose
verbose: GET https://api.vercel.com/v1/query/web-analytics/visits/aggregate
verbose: params [('projectId', 'prj_9xQ2vB7kLmT4dRnW'), ('by', 'day'), ('since', '2026-08-07T00:00:00Z'), ('until', '2026-08-14T00:00:00Z'), ('limit', '100')]
verbose: headers {'Accept': 'application/json', 'User-Agent': 'vercel-analytics-skill/0.1.0', 'Authorization': 'Bearer <redacted>'}
verbose: HTTP 429; retrying in 12.00s
verbose: HTTP 429; retrying in 12.00s
error: HTTP 429 (rate_limited): The rate limit of 100 exceeded for 'api-web-analytics-query'. Try again in 12 seconds [gave up after 3 attempts]
hint: rate limits are per endpoint; wait for the reset above or raise --max-retries so the client waits for you

[exit code 1]
```

## The preset table

`--list-presets` prints every preset with its dataset, endpoint, grouping and
default limit, and exits 0 without touching the network. These are the defaults
the sections above were captured at.

```console
$ python3 scripts/vercel_analytics.py --list-presets
Presets

preset              dataset  endpoint       grouping                            limit  what it shows
------------------  -------  -------------  ----------------------------------  -----  ----------------------------------------------------------
overview (default)  visits   3 x aggregate  day, requestPath, referrerHostname      5  Totals, a daily trend, top pages and top referrers
trend               visits   aggregate      day                                   100  Page views over time (change buckets with --granularity)
top-pages           visits   aggregate      requestPath                            10  Most viewed URL paths
top-routes          visits   aggregate      route                                  10  Most viewed framework routes, for example /blog/[slug]
referrers           visits   aggregate      referrerHostname                       10  Where the traffic came from
countries           visits   aggregate      country                                10  Traffic by country
devices             visits   aggregate      deviceType                             10  Traffic by device type
browsers            visits   aggregate      browserName                            10  Traffic by browser
operating-systems   visits   aggregate      osName                                 10  Traffic by operating system
campaigns           visits   aggregate      utmCampaign                            10  Traffic by utm_campaign (needs Web Analytics Plus)
events              events   aggregate      eventName [+ eventData/<property>]     10  Custom events, plus --event-property NAME to break one out
total               visits   count          none                                  n/a  One ungrouped total from the count endpoint

Any explicit flag overrides a preset value. Groups beyond the limit roll into a single 'Others' row rather than being dropped.

[exit code 0]
```
