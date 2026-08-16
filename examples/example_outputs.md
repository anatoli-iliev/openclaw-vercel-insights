# Example output

Every fenced block below is **captured output from the real code**, not written
by hand. The data behind it is synthetic and anonymised: one fictional docs and
marketing site, one dataset, so the numbers agree across sections.

`vercel-insights` is shorthand for `python3 -m vercel_insights`.

## Getting started

### Which projects do I have?

One Vercel account holds many projects and every query names exactly one, so this is usually the first command to run. Pass either the name or the project id to `--project`.

```console
$ vercel-insights --list-projects
Projects

name            project id                    traffic  speed
--------------  ----------------------------  -------  -----
acme-docs       prj_9RkQm2vT7xLpN4dWbYcF3sJz  data     data
acme-marketing  prj_2LbGf5yUvA8qEr1oPtNm      data     empty
acme-internal   prj_7WsDj4kXzC9nBv6hRlYq      off      off

traffic and speed are Web Analytics and Speed Insights: 'data' means collected, 'empty' means enabled but nothing yet, 'off' means not enabled.
Query one with --project, using either the name or the project id.
[exit code 0]
```

### Forgetting to name a project

The error answers the question behind it rather than only naming a missing flag.

```console
$ vercel-insights vitals --since 2026-08-08 --until 2026-08-15
error: no project configured; pass --project with a project id or name, or set VERCEL_PROJECT_ID in the environment, or pass --all to query every project in the team

This account has:

name            project id                    traffic  speed
--------------  ----------------------------  -------  -----
acme-docs       prj_9RkQm2vT7xLpN4dWbYcF3sJz  data     data
acme-marketing  prj_2LbGf5yUvA8qEr1oPtNm      data     empty
acme-internal   prj_7WsDj4kXzC9nBv6hRlYq      off      off

traffic and speed are Web Analytics and Speed Insights: 'data' means collected, 'empty' means enabled but nothing yet, 'off' means not enabled.
Query one with --project, using either the name or the project id.
[exit code 2]
```

## Traffic: Web Analytics

### The 7 day overview, which is the default

Bare `vercel-insights` runs this.

```console
$ vercel-insights --since 7d
Vercel Web Analytics: prj_9RkQm2vT7xLpN4dWbYcF3sJz
Range: 2026-08-09T05:22:01Z to 2026-08-16T05:22:01Z (UTC)

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
[exit code 0]
```

### Top pages

```console
$ vercel-insights top-pages --since 2026-08-08 --until 2026-08-15
Vercel Web Analytics: prj_9RkQm2vT7xLpN4dWbYcF3sJz (top-pages)
Range: 2026-08-08T00:00:00Z to 2026-08-15T00:00:00Z (UTC)

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

Others is not a real value: it is every group beyond --limit 10, collapsed by the API into one bucket.
[exit code 0]
```

### Top framework routes

```console
$ vercel-insights top-routes --since 2026-08-08 --until 2026-08-15
Vercel Web Analytics: prj_9RkQm2vT7xLpN4dWbYcF3sJz (top-routes)
Range: 2026-08-08T00:00:00Z to 2026-08-15T00:00:00Z (UTC)

route         pageviews  visitors  % pageviews
------------  ---------  --------  -----------
/                18,420    11,930        46.3%
/docs/[slug]     14,980     9,860        37.6%
/blog/[slug]      6,415     5,104        16.1%
------------  ---------  --------  -----------
TOTAL            39,815    26,894       100.0%
[exit code 0]
```

### Where the traffic came from

```console
$ vercel-insights referrers --since 2026-08-08 --until 2026-08-15
Vercel Web Analytics: prj_9RkQm2vT7xLpN4dWbYcF3sJz (referrers)
Range: 2026-08-08T00:00:00Z to 2026-08-15T00:00:00Z (UTC)

referrerHostname      pageviews  visitors  % pageviews
--------------------  ---------  --------  -----------
(none)                   21,044    13,980        43.8%
google.com               14,310     9,720        29.8%
news.ycombinator.com      6,890     6,012        14.3%
github.com                3,402     2,560         7.1%
x.com                     2,426     1,798         5.0%
--------------------  ---------  --------  -----------
TOTAL                    48,072    34,070       100.0%
[exit code 0]
```

### Traffic by country

```console
$ vercel-insights countries --since 2026-08-08 --until 2026-08-15
Vercel Web Analytics: prj_9RkQm2vT7xLpN4dWbYcF3sJz (countries)
Range: 2026-08-08T00:00:00Z to 2026-08-15T00:00:00Z (UTC)

country  pageviews  visitors  % pageviews
-------  ---------  --------  -----------
US          19,840    12,905        47.0%
DE           8,120     5,644        19.3%
GB           6,310     4,288        15.0%
IN           5,470     3,902        13.0%
BR           2,432     1,801         5.8%
-------  ---------  --------  -----------
TOTAL       42,172    28,540       100.0%
[exit code 0]
```

### Mobile against desktop

```console
$ vercel-insights devices --since 2026-08-08 --until 2026-08-15
Vercel Web Analytics: prj_9RkQm2vT7xLpN4dWbYcF3sJz (devices)
Range: 2026-08-08T00:00:00Z to 2026-08-15T00:00:00Z (UTC)

deviceType  pageviews  visitors  % pageviews
----------  ---------  --------  -----------
desktop        29,140    18,770        60.6%
mobile         17,402    11,960        36.2%
tablet          1,530     1,140         3.2%
----------  ---------  --------  -----------
TOTAL          48,072    31,870       100.0%
[exit code 0]
```

### Browsers

```console
$ vercel-insights browsers --since 2026-08-08 --until 2026-08-15
Vercel Web Analytics: prj_9RkQm2vT7xLpN4dWbYcF3sJz (browsers)
Range: 2026-08-08T00:00:00Z to 2026-08-15T00:00:00Z (UTC)

browserName  pageviews  visitors  % pageviews
-----------  ---------  --------  -----------
Chrome          26,310    17,020        54.7%
Safari          13,480     9,140        28.0%
Firefox          5,220     3,690        10.9%
Edge             3,062     2,020         6.4%
-----------  ---------  --------  -----------
TOTAL           48,072    31,870       100.0%
[exit code 0]
```

### Operating systems

```console
$ vercel-insights operating-systems --since 2026-08-08 --until 2026-08-15
Vercel Web Analytics: prj_9RkQm2vT7xLpN4dWbYcF3sJz (operating-systems)
Range: 2026-08-08T00:00:00Z to 2026-08-15T00:00:00Z (UTC)

osName   pageviews  visitors  % pageviews
-------  ---------  --------  -----------
macOS       19,840    12,610        41.3%
Windows     14,120     9,440        29.4%
iOS          8,930     6,210        18.6%
Android      5,182     3,610        10.8%
-------  ---------  --------  -----------
TOTAL       48,072    31,870       100.0%
[exit code 0]
```

### UTM campaigns

```console
$ vercel-insights campaigns --since 2026-08-08 --until 2026-08-15
Vercel Web Analytics: prj_9RkQm2vT7xLpN4dWbYcF3sJz (campaigns)
Range: 2026-08-08T00:00:00Z to 2026-08-15T00:00:00Z (UTC)

utmCampaign        pageviews  visitors  % pageviews
-----------------  ---------  --------  -----------
launch-week            4,820     3,610        59.0%
newsletter-august      2,140     1,780        26.2%
product-hunt           1,206     1,094        14.8%
-----------------  ---------  --------  -----------
TOTAL                  8,166     6,484       100.0%
[exit code 0]
```

### Custom events

```console
$ vercel-insights events --since 2026-08-08 --until 2026-08-15
Vercel Web Analytics: prj_9RkQm2vT7xLpN4dWbYcF3sJz (events)
Range: 2026-08-08T00:00:00Z to 2026-08-15T00:00:00Z (UTC)

eventName      count  visitors  % count
-------------  -----  --------  -------
signup           412       388    54.6%
subscribe        268       251    35.5%
contact_sales     74        71     9.8%
-------------  -----  --------  -------
TOTAL            754       710   100.0%
[exit code 0]
```

### Which plan did signups choose

```console
$ vercel-insights events --event-property plan --since 2026-08-08 --until 2026-08-15
Vercel Web Analytics: prj_9RkQm2vT7xLpN4dWbYcF3sJz (events)
Range: 2026-08-08T00:00:00Z to 2026-08-15T00:00:00Z (UTC)

eventName  eventData/plan  count  visitors  % count
---------  --------------  -----  --------  -------
signup     free              291       274    70.6%
signup     pro                98        92    23.8%
signup     enterprise         23        22     5.6%
---------  --------------  -----  --------  -------
TOTAL                        412       388   100.0%
[exit code 0]
```

### A daily trend

```console
$ vercel-insights trend --since 2026-08-08 --until 2026-08-15
Vercel Web Analytics: prj_9RkQm2vT7xLpN4dWbYcF3sJz (trend)
Range: 2026-08-08T00:00:00Z to 2026-08-15T00:00:00Z (UTC)

day         pageviews  visitors  % pageviews
----------  ---------  --------  -----------
2026-08-08      6,120     4,180        12.7%
2026-08-09      4,980     3,410        10.4%
2026-08-10      7,840     5,220        16.3%
2026-08-11      8,310     5,560        17.3%
2026-08-12      7,905     5,240        16.4%
2026-08-13      7,402     4,980        15.4%
2026-08-14      5,515     3,690        11.5%
----------  ---------  --------  -----------
TOTAL          48,072    32,280       100.0%
[exit code 0]
```

### One ungrouped total

```console
$ vercel-insights total --since 2026-08-08 --until 2026-08-15
Vercel Web Analytics: prj_9RkQm2vT7xLpN4dWbYcF3sJz (total)
Range: 2026-08-08T00:00:00Z to 2026-08-15T00:00:00Z (UTC)

  pageviews  148,072
  visitors    61,904
[exit code 0]
```

## Speed: Core Web Vitals

### All five vitals against Vercel's published targets

The value is the aggregate for the whole window, taken from the server's own summary. It is not derived from the buckets: a percentile does not average, so the P75 of 168 hourly P75s is not the P75 of the week.

```console
$ vercel-insights vitals --since 2026-08-08 --until 2026-08-15
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
[exit code 0]
```

### The slowest routes

```console
$ vercel-insights slowest-pages --since 2026-08-08 --until 2026-08-15
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
[exit code 0]
```

### The fastest routes

```console
$ vercel-insights fastest-pages --since 2026-08-08 --until 2026-08-15
Vercel Speed Insights: prj_9RkQm2vT7xLpN4dWbYcF3sJz (fastest-pages, p75)
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
[exit code 0]
```

### Speed by country

```console
$ vercel-insights vitals-by-country --since 2026-08-08 --until 2026-08-15
Vercel Speed Insights: prj_9RkQm2vT7xLpN4dWbYcF3sJz (vitals-by-country, p75)
Range: 2026-08-08T00:00:00Z to 2026-08-15T00:00:00Z (UTC)

country  p75_lcp
-------  -------
BR         5.4 s
IN         5.0 s
DE         2.8 s
GB         2.6 s
US         2.2 s

Metric: vercel.speed_insights.lcp_ms (Largest Contentful Paint)
Target: 2.5 s or less
Lower is better for all five metrics.
The target is Vercel's published 'good' threshold, so the verdict is two tier: meets target or over target.
[exit code 0]
```

### Speed by device

The usual explanation for a poor field score.

```console
$ vercel-insights vitals-by-device --since 2026-08-08 --until 2026-08-15
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
[exit code 0]
```

### Is it getting better or worse

A granularity is requested here, so the buckets are kept rather than collapsed into one number.

```console
$ vercel-insights vitals-trend --since 2026-08-08 --until 2026-08-15
Vercel Speed Insights: prj_9RkQm2vT7xLpN4dWbYcF3sJz (vitals-trend, p75)
Range: 2026-08-08T00:00:00Z to 2026-08-15T00:00:00Z (UTC)

day         p75_lcp
----------  -------
2026-08-08    3.4 s
2026-08-09    3.2 s
2026-08-10    3.0 s
2026-08-11    2.9 s
2026-08-12    2.8 s
2026-08-13    2.7 s
2026-08-14    2.6 s

Metric: vercel.speed_insights.lcp_ms (Largest Contentful Paint)
Target: 2.5 s or less
Lower is better for all five metrics.
The target is Vercel's published 'good' threshold, so the verdict is two tier: meets target or over target.
[exit code 0]
```

### How much data is behind those percentiles

A percentile over few measurements is not comparable to one over many.

```console
$ vercel-insights data-points --since 2026-08-08 --until 2026-08-15
Vercel Speed Insights: prj_9RkQm2vT7xLpN4dWbYcF3sJz (data-points, sum)
Range: 2026-08-08T00:00:00Z to 2026-08-15T00:00:00Z (UTC)

route         sum_lcp_count  % sum_lcp_count
------------  -------------  ---------------
/blog/[slug]          5,120            12.2%
/docs/[slug]         18,640            44.4%
/pricing              7,180            17.1%
/                    11,020            26.3%
------------  -------------  ---------------
TOTAL                41,960           100.0%

Metric: vercel.speed_insights.lcp_count (Largest Contentful Paint data points)
These are data point counts, not metric values: one data point is one measurement of one web vital during one visit, and a visit produces up to six.
They are what makes a percentile trustworthy, so a group with few of them is not comparable to one with many.
[exit code 0]
```

## Failing a build on a regression

### Every budget met

Exit code 0.

```console
$ vercel-insights vitals --since 2026-08-08 --until 2026-08-15 --budget inp=200 --budget ttfb=800
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

Budgets
  pass    Interaction to Next Paint    184 ms against 200 ms
  pass    Time to First Byte           412 ms against 800 ms
[exit code 0]
```

### A budget exceeded

Exit code **3**, deliberately not 1: the run succeeded and is reporting bad news, which a CI step usually wants to tell apart from the API being down. A copyable workflow is in [`github-action-budget.yml`](github-action-budget.yml).

```console
$ vercel-insights vitals --since 2026-08-08 --until 2026-08-15 --budget lcp=2500 --budget cls=0.1
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

Budgets
  fail    Largest Contentful Paint      2.9 s against 2.5 s
  fail    Cumulative Layout Shift       0.128 against 0.100
at least one budget was exceeded, so this run exits 3
[exit code 3]
```

## Beyond web vitals

### What can this account query?

The schema is the source of truth for what an account can reach. Everything outside Web Analytics and Speed Insights needs Observability Plus.

```console
$ vercel-insights --list-metrics vercel
Queryable metrics

7 queryable metric(s):

vercel.function_invocation.count
    unit          count
    aggregations  sum
    default       sum
    dimensions    route, function_region
    Function Invocations Count

vercel.request.count
    unit          count
    aggregations  sum
    default       sum
    dimensions    route, http_status
    Requests Count

vercel.speed_insights.cls
    unit          score
    aggregations  p75, p90, p95, p99
    default       p75
    dimensions    route, request_path, country, device_type
    Speed Insights Cumulative Layout Shift

vercel.speed_insights.fcp_ms
    unit          ms
    aggregations  p75, p90, p95, p99
    default       p75
    dimensions    route, request_path, country, device_type
    Speed Insights First Contentful Paint

vercel.speed_insights.inp_ms
    unit          ms
    aggregations  p75, p90, p95, p99
    default       p75
    dimensions    route, request_path, country, device_type
    Speed Insights Interaction to Next Paint

vercel.speed_insights.lcp_ms
    unit          ms
    aggregations  p75, p90, p95, p99
    default       p75
    dimensions    route, request_path, country, device_type
    Speed Insights Largest Contentful Paint

vercel.speed_insights.ttfb_ms
    unit          ms
    aggregations  p75, p90, p95, p99
    default       p75
    dimensions    route, request_path, country, device_type
    Speed Insights Time to First Byte
[exit code 0]
```

### Any metric, by id

No unit and no target are claimed for a metric outside the five web vitals, so the value is reported rather than judged.

```console
$ vercel-insights --metric vercel.function_invocation.count --aggregation sum --group-by route --since 2026-08-08 --until 2026-08-15
Vercel Speed Insights: prj_9RkQm2vT7xLpN4dWbYcF3sJz (metric, sum)
Range: 2026-08-08T00:00:00Z to 2026-08-15T00:00:00Z (UTC)

route         sum_count  % sum_count
------------  ---------  -----------
/api/search      48,210        63.3%
/api/auth        21,840        28.7%
/api/webhook      6,120         8.0%
------------  ---------  -----------
TOTAL            76,170       100.0%
[exit code 0]
```

## Machine readable output

### As JSON, for jq

```console
$ vercel-insights devices --since 2026-08-08 --until 2026-08-15 --json
{
  "query": {
    "groupBy": [
      "deviceType"
    ]
  },
  "range": {
    "since": "2026-08-08T00:00:00Z",
    "until": "2026-08-15T00:00:00Z"
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
        "pageviews": 29140,
        "visitors": 18770
      }
    },
    {
      "key": "mobile",
      "groups": {
        "deviceType": "mobile"
      },
      "timestamp": null,
      "metrics": {
        "pageviews": 17402,
        "visitors": 11960
      }
    },
    {
      "key": "tablet",
      "groups": {
        "deviceType": "tablet"
      },
      "timestamp": null,
      "metrics": {
        "pageviews": 1530,
        "visitors": 1140
      }
    }
  ],
  "totals": {
    "pageviews": 48072,
    "visitors": 31870
  },
  "raw": {
    "version": 1,
    "query": {
      "groupBy": [
        "deviceType"
      ]
    },
    "data": [
      {
        "deviceType": "desktop",
        "pageviews": 29140,
        "visitors": 18770
      },
      {
        "deviceType": "mobile",
        "pageviews": 17402,
        "visitors": 11960
      },
      {
        "deviceType": "tablet",
        "pageviews": 1530,
        "visitors": 1140
      }
    ]
  }
}
[exit code 0]
```

### As CSV, for a spreadsheet

```console
$ vercel-insights devices --since 2026-08-08 --until 2026-08-15 --csv
deviceType,pageviews,visitors
desktop,29140,18770
mobile,17402,11960
tablet,1530,1140
[exit code 0]
```

## Seeing the request without sending it

### A Web Analytics request

`--dry-run` needs no token and sends nothing.

```console
$ vercel-insights top-pages --since 2026-08-08 --until 2026-08-15 --country US --dry-run
GET https://api.vercel.com/v1/query/web-analytics/visits/aggregate

Query parameters:
  projectId  prj_9RkQm2vT7xLpN4dWbYcF3sJz
  by         requestPath
  since      2026-08-08T00:00:00Z
  until      2026-08-15T00:00:00Z
  limit      10
  filter     country eq 'US'

Headers:
  Accept         application/json
  Authorization  Bearer <redacted>
  User-Agent     vercel-insights-skill/0.2.0

Encoded URL (never contains the token):
  https://api.vercel.com/v1/query/web-analytics/visits/aggregate?projectId=prj_9RkQm2vT7xLpN4dWbYcF3sJz&by=requestPath&since=2026-08-08T00%3A00%3A00Z&until=2026-08-15T00%3A00%3A00Z&limit=10&filter=country+eq+%27US%27

Nothing was sent. No credential is printed above.
[exit code 0]
```

### A Speed Insights request, with its JSON body

```console
$ vercel-insights vitals-trend --metric inp --granularity 1d --since 2026-08-08 --until 2026-08-15 --dry-run
POST https://api.vercel.com/v2/observability/query

Query parameters:
  (none)

Headers:
  Accept         application/json
  Authorization  Bearer <redacted>
  User-Agent     vercel-insights-skill/0.2.0

JSON body:
  {
    "metric": "vercel.speed_insights.inp_ms",
    "scope": {
      "type": "project",
      "ownerId": "team_8mHvK3nQpR6tXwZa",
      "projectIds": [
        "prj_9RkQm2vT7xLpN4dWbYcF3sJz"
      ]
    },
    "aggregation": "p75",
    "granularity": {
      "days": 1
    },
    "startTime": "2026-08-08T00:00:00Z",
    "endTime": "2026-08-15T00:00:00Z"
  }

Encoded URL (never contains the token):
  https://api.vercel.com/v2/observability/query

Nothing was sent. No credential is printed above.
[exit code 0]
```

## When something is wrong

### Nothing collected in the window

Exit code 0. An empty result is an answer, not a failure.

```console
$ vercel-insights top-pages --since 2026-01-01 --until 2026-01-02
No visits data for project prj_9RkQm2vT7xLpN4dWbYcF3sJz (grouped by requestPath) between 2026-01-01T00:00:00Z and 2026-01-02T00:00:00Z with no filter. Try a wider --since, or relax the filter.
[exit code 0]
```

### A token that cannot reach Speed Insights

Vercel answers `404 Observability Data not found.`, which reads as "your project has no data" but means "this token cannot ask".

```console
$ vercel-insights vitals --since 2026-08-08 --until 2026-08-15
error: HTTP 404 (not_found): Observability Data not found.
This usually means the access token is scoped to a single project. Speed Insights is served by Vercel's observability API, which scopes by account rather than by project, so it needs a token with account (or team) scope. Web Analytics presets keep working with a project scoped token. Create an account scoped token at https://vercel.com/account/tokens, or confirm the scope of the current one with: npx vercel@latest metrics schema
[exit code 1]
```

### No permission

Vercel's own message is kept verbatim.

```console
$ vercel-insights top-pages --since 2026-08-08 --until 2026-08-15
error: HTTP 403 (forbidden): Not authorized
[exit code 1]
```

### Rate limited, after retries are used up

```console
$ vercel-insights top-pages --since 2026-08-08 --until 2026-08-15 --max-retries 1
error: HTTP 429 (rate_limited): Too many requests [gave up after 2 attempts]
hint: rate limits are per endpoint; wait for the reset above or raise --max-retries so the client waits for you
[exit code 1]
```

### A mistyped dimension

Caught before any request is sent.

```console
$ vercel-insights top-pages --group-by contry --since 2026-08-08 --until 2026-08-15 --dry-run
error: unknown dimension 'contry' for the visits dataset. Did you mean 'country'? Valid dimensions: hour, day, week, month, year, country, deviceType, environment, requestPath, referrerHostname, osName, browserName, route, utmSource, utmMedium, utmCampaign, utmContent, utmTerm, flags, plus flags/<name>
[exit code 2]
```
