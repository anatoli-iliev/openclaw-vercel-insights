# Example outputs

Every `console` block below is captured output from `python3 -m vercel_insights`.
The alignment, the totals, the percentages, the sparkline bars, the millisecond
and second formatting and the exact wording of the error lines all came out of
the real code, through `main()`. Nothing here was typed by hand to look like
terminal output. The one `sh` block, under "How these were produced", is
environment setup rather than output.

Two lines per block are added by the capture rather than printed by the
program: the `$ ...` command line at the top and the `[exit code N]` marker at
the bottom. Everything between them is verbatim. Blocks that show an error or
`--verbose` show stdout followed by stderr, because that is what a terminal
would interleave.

The tool covers two APIs, so this file has two halves. Web Analytics answers
"how many", Speed Insights answers "how fast", and both halves are computed
from the same records, so a route's page views and its web vital data points
are the same navigations counted twice.

## How these were produced

There is no Vercel token in this repository and no request has ever left it.
The client was pointed at a stub session that answers from one synthetic
dataset for a fictional docs and marketing site:

- **35,593 page view records**, each carrying a visitor id, a day, a URL path, a
  framework route, a referrer hostname, a country, a device type, a browser, an
  operating system and a UTM campaign. They belong to **12,479 distinct
  visitors** spread over 12 URL paths, 9 routes, 13 countries, 12 referrer
  groups (11 hostnames plus direct), 6 browsers, 7 operating systems and 5
  campaigns.
- **3,059 custom event records** across 5 event names, two of which carry a
  `plan` event property.
- **35,593 navigations**, one per page view, each carrying a Largest Contentful
  Paint, First Contentful Paint, Time to First Byte and Cumulative Layout Shift
  measurement, and an Interaction to Next Paint measurement when the visit
  produced an interaction. That is what makes the two halves of this file
  describe one site rather than two.

The stub groups, counts, sorts, orders and truncates those records the way
`docs/api-notes.md` says each API does, and hands back payloads in the
documented shape. That matters for reading the numbers: **every table below is
a real aggregation of the same records**, so the cross-table arithmetic in the
next section is a property of the data rather than a promise.

Two honest caveats about the Speed Insights half. Vercel's OpenAPI document
declares the observability `scope`, `granularity` and 200 response body as bare
objects with no inner properties, so the stub answers in the shape this client
assumes and probes for, which is marked ASSUMPTION in
`vercel_insights/speedinsights.py`. And the fixture contains production traffic
only, so nothing here exercises `environment eq 'preview'`.

Three things were pinned so the capture is reproducible: the clock was fixed at
2026-08-14T09:00:00Z, the sleep between retries and its jitter were stubbed out
so the rate limit run did not really take 24 seconds, and the same fixed window
was passed to every command. Every printed line is real.

```sh
export VERCEL_PROJECT_ID=prj_9xQ2vB7kLmT4dRnW
export VERCEL_TOKEN=...   # not needed for --dry-run
```

`--since 2026-08-07 --until 2026-08-14` is seven daily buckets, 2026-08-07
through 2026-08-13 inclusive.

## How the numbers relate

### Page views tie out, visitors do not

Every grouped report of the visits dataset below totals exactly 35,593 page
views, and so does the count endpoint. That holds even for the tables with an
`Others` row, because the limit overflow is collapsed into that bucket rather
than dropped.

Visitor columns do not tie out, and they are not supposed to. A grouped report
counts distinct visitors *within each group* and the totals row adds those up,
so anybody who appears in two groups is counted twice. Only the count endpoint
reports distinct visitors across the whole window: 12,479.

| Report | Grouping | pageviews total | visitors total |
| --- | --- | ---: | ---: |
| `trend` | `day` | 35,593 | 16,135 |
| `top-pages` | `requestPath` | 35,593 | 31,641 |
| `top-routes` | `route` | 35,593 | 28,160 |
| `referrers` | `referrerHostname` | 35,593 | 15,339 |
| `countries` | `country` | 35,593 | 12,479 |
| `devices` | `deviceType` | 35,593 | 12,479 |
| `browsers` | `browserName` | 35,593 | 12,479 |
| `operating-systems` | `osName` | 35,593 | 12,479 |
| `campaigns` | `utmCampaign` | 35,593 | 14,618 |
| `total` | none (count endpoint) | 35,593 | 12,479 |

Read that table as follows.

- The `pageviews total` column is constant. It is the same 35,593 page views
  sliced nine different ways.
- `country`, `deviceType`, `browserName` and `osName` each total exactly 12,479
  visitors, matching the count endpoint. In this fixture a visitor keeps one
  country, one device, one browser and one operating system for the whole
  window, so nobody lands in two groups and there is nothing to double count.
- Every other grouping totals more. `trend` sums to 16,135, which is 3,656
  above the distinct total, and 3,656 is exactly the number of repeat
  appearances on a second or third day. `top-pages` is the extreme at 31,641,
  because 8,766 of the 12,479 visitors (70.2%) read more than one page.

Three more relationships worth checking against the blocks:

- The site has 12 URL paths with traffic and the `top-pages` default limit is
  10, so the `Others` row holds the remaining 2, `/changelog` and `/about`:
  1,848 plus 874 is 2,722, and 32,871 in the ten named rows plus 2,722 is
  35,593. The same happens in `referrers`, which has 12 groups, and in
  `countries`, which has 13.
- `top-routes` and `top-pages` are the same traffic counted differently.
  `/docs/getting-started` (4,415), `/docs/cli` (2,988) and `/docs/deploy-hooks`
  (2,061) roll up into `/docs/[slug]` (9,464), and the two blog posts (2,850
  and 2,092) roll up into `/blog/[slug]` (4,942), so 12 paths become 9 routes.
  That fits inside the limit, which is why the route table has no `Others` row,
  and it still totals 35,593 page views.
- The two dimension events table is the one dimension events table split finer.
  Both total 3,059 events, and the three `signup` rows add back up to the single
  `signup` row: 410 = 277 + 109 + 24. The `(none)` rows are the 2,278 events
  that carry no `plan` property at all, and 2,278 plus the 781 `signup` and
  `plan_selected` events is 3,059.

### The two surfaces describe the same navigations

Speed Insights is queried separately and comes back in a different shape, but
in this fixture it counts the same events, so three ties hold exactly:

- `data-points` sums `lcp_count` by route and totals 35,593, the page view
  total. Row for row, its counts are the `top-routes` page view column:
  `/docs/[slug]` 9,464, `/docs` 5,404, `/blog/[slug]` 4,942, and so on down to
  `/about` 874.
- The `data points` column of `vitals-by-device` is the `devices` page view
  column: 24,171 desktop, 10,057 mobile, 1,365 tablet.
- The Interaction to Next Paint row of `vitals` is the exception, and that is
  the point of the column: 27,741 data points rather than 35,593, because INP
  is only measured when the visit produced an interaction. 27,741 / 35,593 is
  77.9% of navigations.

The country tables tie in a subtler way. `vitals-by-country` orders by data
points and stops at the default limit of 10, so it shows 33,263 of the 35,593
measurements; the 2,330 it leaves out are `SE`, `ES` and `IT`, which is exactly
the `Others` row of the `countries` table. Unlike Web Analytics, the
observability API documents no overflow bucket, so those rows are absent rather
than collapsed.

### Reading the web vitals

The site's overall P75 LCP is 2.2 s, inside Vercel's 2.5 s target, while its
slowest route sits at 3.6 s. Both are true at once: `/dashboard` contributes
1,923 of 35,593 data points, 5.4% of them, so it cannot move a site wide 75th
percentile. **A percentile of the whole is not the average of the percentiles
of its parts**, which is why the grouped Speed Insights tables carry no totals
row.

The one metric over target is INP, at 205 ms against a 200 ms target, and the
blocks below locate it three ways that agree with each other:

- By day: 192, 191 and 195 ms through 2026-08-09, then 213, 213, 214 and 213 ms
  from 2026-08-10 onwards. Something shipped on the Monday.
- By route: `/dashboard` at 527 ms, `/docs/[slug]` at 228 ms and `/blog/[slug]`
  at 227 ms are the three routes above the target.
- By device: desktop meets the target at 172 ms; mobile is at 275 ms on 28.3%
  of page views.

Filtered to `/dashboard`, the daily trend is 369, 392 and 407 ms before the
Monday and 591, 654, 584 and 606 ms after it, which is the regression on its
own.

## Web Analytics: how many

### overview (the default preset)

Run with no preset at all and you get this. It is the only Web Analytics preset
that issues more than one request: the API cannot return an ungrouped total and
grouped rows in a single call, so the report is composed from a daily
aggregate, a top pages aggregate and a top referrers aggregate.

The tables use `--limit 5` here rather than the usual 10, so their `Others`
rows are larger than in the standalone sections further down. The page view
totals are identical either way.

```console
$ python3 -m vercel_insights --since 2026-08-07 --until 2026-08-14
Vercel Web Analytics: prj_9xQ2vB7kLmT4dRnW
Range: 2026-08-07T00:00:00Z to 2026-08-14T00:00:00Z (UTC)

  pageviews  35,593
  visitors   16,135
  visitors is a sum of the buckets below, so someone who came on two days counts twice;
  run the total preset for distinct visitors over the window

By day
  2026-08-07  5,389  ██████████████████████
  2026-08-08  3,956  ████████████████
  2026-08-09  3,693  ███████████████
  2026-08-10  5,754  ████████████████████████
  2026-08-11  5,730  ████████████████████████
  2026-08-12  5,790  ████████████████████████
  2026-08-13  5,281  ██████████████████████

Top pages (top 5)
requestPath            pageviews  visitors  % pageviews
---------------------  ---------  --------  -----------
/docs                      5,404     4,538        15.2%
/pricing                   4,452     3,889        12.5%
/                          4,446     3,909        12.5%
/docs/getting-started      4,415     3,807        12.4%
/docs/cli                  2,988     2,670         8.4%
Others                    13,888     8,705        39.0%
---------------------  ---------  --------  -----------
TOTAL                     35,593    27,518       100.0%

Others is not a real value: it is every group beyond --limit 5, collapsed by the API into one bucket.

Top referrers (top 5)
referrerHostname      pageviews  visitors  % pageviews
--------------------  ---------  --------  -----------
(none)                   12,458     5,143        35.0%
google.com                7,003     2,989        19.7%
github.com                3,539     1,535         9.9%
news.ycombinator.com      2,591     1,147         7.3%
x.com                     1,897       854         5.3%
Others                    8,105     3,471        22.8%
--------------------  ---------  --------  -----------
TOTAL                    35,593    15,139       100.0%

Others is not a real value: it is every group beyond --limit 5, collapsed by the API into one bucket.

[exit code 0]
```

### trend

Page views and visitors per time bucket. `--granularity` changes the bucket to
`hour`, `week`, `month` or `year`; the default is daily. The two quietest days,
3,956 and 3,693 page views, are the Saturday and the Sunday.

```console
$ python3 -m vercel_insights trend --since 2026-08-07 --until 2026-08-14
Vercel Web Analytics: prj_9xQ2vB7kLmT4dRnW (trend)
Range: 2026-08-07T00:00:00Z to 2026-08-14T00:00:00Z (UTC)

day         pageviews  visitors  % pageviews
----------  ---------  --------  -----------
2026-08-07      5,389     2,449        15.1%
2026-08-08      3,956     1,796        11.1%
2026-08-09      3,693     1,678        10.4%
2026-08-10      5,754     2,616        16.2%
2026-08-11      5,730     2,609        16.1%
2026-08-12      5,790     2,603        16.3%
2026-08-13      5,281     2,384        14.8%
----------  ---------  --------  -----------
TOTAL          35,593    16,135       100.0%

[exit code 0]
```

### top-pages

Exact URL paths, ordered by page views. The `Others` row is the two paths past
`--limit 10`, not a real page.

```console
$ python3 -m vercel_insights top-pages --since 2026-08-07 --until 2026-08-14
Vercel Web Analytics: prj_9xQ2vB7kLmT4dRnW (top-pages)
Range: 2026-08-07T00:00:00Z to 2026-08-14T00:00:00Z (UTC)

requestPath             pageviews  visitors  % pageviews
----------------------  ---------  --------  -----------
/docs                       5,404     4,538        15.2%
/pricing                    4,452     3,889        12.5%
/                           4,446     3,909        12.5%
/docs/getting-started       4,415     3,807        12.4%
/docs/cli                   2,988     2,670         8.4%
/blog/analytics-launch      2,850     2,608         8.0%
/login                      2,240     2,114         6.3%
/blog/edge-caching          2,092     1,970         5.9%
/docs/deploy-hooks          2,061     1,846         5.8%
/dashboard                  1,923     1,852         5.4%
Others                      2,722     2,438         7.6%
----------------------  ---------  --------  -----------
TOTAL                      35,593    31,641       100.0%

Others is not a real value: it is every group beyond --limit 10, collapsed by the API into one bucket.

[exit code 0]
```

Filters compose with any preset. This is the top five paths for mobile
visitors only, with the filter echoed above the table so a screenshot cannot
lose the context:

```console
$ python3 -m vercel_insights top-pages --device mobile --limit 5 --since 2026-08-07 --until 2026-08-14
Vercel Web Analytics: prj_9xQ2vB7kLmT4dRnW (top-pages)
Range: 2026-08-07T00:00:00Z to 2026-08-14T00:00:00Z (UTC)
Filter: deviceType eq 'mobile'

requestPath            pageviews  visitors  % pageviews
---------------------  ---------  --------  -----------
/docs                      1,540     1,293        15.3%
/docs/getting-started      1,273     1,090        12.7%
/                          1,250     1,125        12.4%
/pricing                   1,247     1,090        12.4%
/docs/cli                    827       746         8.2%
Others                     3,920     2,499        39.0%
---------------------  ---------  --------  -----------
TOTAL                     10,057     7,843       100.0%

Others is not a real value: it is every group beyond --limit 5, collapsed by the API into one bucket.

[exit code 0]
```

Its 10,057 page views are the `mobile` row of the `devices` table, and the same
10,057 navigations come back as the data point count in the mobile `vitals`
block further down. One filter, one population, two APIs.

### top-routes

The same traffic grouped by framework route rather than URL path, so the three
`/docs/*` articles arrive as one `/docs/[slug]` row. Nine routes fit inside the
default limit, so there is no `Others` row here.

```console
$ python3 -m vercel_insights top-routes --since 2026-08-07 --until 2026-08-14
Vercel Web Analytics: prj_9xQ2vB7kLmT4dRnW (top-routes)
Range: 2026-08-07T00:00:00Z to 2026-08-14T00:00:00Z (UTC)

route         pageviews  visitors  % pageviews
------------  ---------  --------  -----------
/docs/[slug]      9,464     5,488        26.6%
/docs             5,404     4,538        15.2%
/blog/[slug]      4,942     3,776        13.9%
/pricing          4,452     3,889        12.5%
/                 4,446     3,909        12.5%
/login            2,240     2,114         6.3%
/dashboard        1,923     1,852         5.4%
/changelog        1,848     1,752         5.2%
/about              874       842         2.5%
------------  ---------  --------  -----------
TOTAL            35,593    28,160       100.0%

[exit code 0]
```

### referrers

Where the traffic came from. Direct traffic has no referrer hostname at all, so
it arrives as a null and renders as `(none)` rather than being dropped.

```console
$ python3 -m vercel_insights referrers --since 2026-08-07 --until 2026-08-14
Vercel Web Analytics: prj_9xQ2vB7kLmT4dRnW (referrers)
Range: 2026-08-07T00:00:00Z to 2026-08-14T00:00:00Z (UTC)

referrerHostname          pageviews  visitors  % pageviews
------------------------  ---------  --------  -----------
(none)                       12,458     5,143        35.0%
google.com                    7,003     2,989        19.7%
github.com                    3,539     1,535         9.9%
news.ycombinator.com          2,591     1,147         7.3%
x.com                         1,897       854         5.3%
newsletter.northwind.dev      1,690       787         4.7%
reddit.com                    1,569       690         4.4%
bing.com                      1,404       642         3.9%
dev.to                        1,031       465         2.9%
linkedin.com                    911       401         2.6%
Others                        1,500       686         4.2%
------------------------  ---------  --------  -----------
TOTAL                        35,593    15,339       100.0%

Others is not a real value: it is every group beyond --limit 10, collapsed by the API into one bucket.

[exit code 0]
```

### countries

Thirteen countries, ten rows, and the remaining three collapsed into `Others`.

```console
$ python3 -m vercel_insights countries --since 2026-08-07 --until 2026-08-14
Vercel Web Analytics: prj_9xQ2vB7kLmT4dRnW (countries)
Range: 2026-08-07T00:00:00Z to 2026-08-14T00:00:00Z (UTC)

country  pageviews  visitors  % pageviews
-------  ---------  --------  -----------
US          11,356     3,915        31.9%
DE           4,390     1,572        12.3%
GB           3,188     1,140         9.0%
IN           3,091     1,098         8.7%
FR           2,520       875         7.1%
CA           2,290       813         6.4%
BR           2,101       724         5.9%
NL           1,697       592         4.8%
JP           1,416       487         4.0%
AU           1,214       448         3.4%
Others       2,330       815         6.5%
-------  ---------  --------  -----------
TOTAL       35,593    12,479       100.0%

Others is not a real value: it is every group beyond --limit 10, collapsed by the API into one bucket.

[exit code 0]
```

### devices

```console
$ python3 -m vercel_insights devices --since 2026-08-07 --until 2026-08-14
Vercel Web Analytics: prj_9xQ2vB7kLmT4dRnW (devices)
Range: 2026-08-07T00:00:00Z to 2026-08-14T00:00:00Z (UTC)

deviceType  pageviews  visitors  % pageviews
----------  ---------  --------  -----------
desktop        24,171     8,431        67.9%
mobile         10,057     3,565        28.3%
tablet          1,365       483         3.8%
----------  ---------  --------  -----------
TOTAL          35,593    12,479       100.0%

[exit code 0]
```

### browsers

```console
$ python3 -m vercel_insights browsers --since 2026-08-07 --until 2026-08-14
Vercel Web Analytics: prj_9xQ2vB7kLmT4dRnW (browsers)
Range: 2026-08-07T00:00:00Z to 2026-08-14T00:00:00Z (UTC)

browserName       pageviews  visitors  % pageviews
----------------  ---------  --------  -----------
Chrome               18,999     6,712        53.4%
Safari                8,408     2,931        23.6%
Edge                  3,229     1,113         9.1%
Firefox               3,040     1,041         8.5%
Samsung Internet      1,280       445         3.6%
Opera                   637       237         1.8%
----------------  ---------  --------  -----------
TOTAL                35,593    12,479       100.0%

[exit code 0]
```

### operating-systems

```console
$ python3 -m vercel_insights operating-systems --since 2026-08-07 --until 2026-08-14
Vercel Web Analytics: prj_9xQ2vB7kLmT4dRnW (operating-systems)
Range: 2026-08-07T00:00:00Z to 2026-08-14T00:00:00Z (UTC)

osName    pageviews  visitors  % pageviews
--------  ---------  --------  -----------
Windows      12,161     4,219        34.2%
macOS         9,648     3,400        27.1%
Android       6,936     2,456        19.5%
iOS           3,966     1,416        11.1%
Linux         1,865       640         5.2%
iPadOS          520       176         1.5%
ChromeOS        497       172         1.4%
--------  ---------  --------  -----------
TOTAL        35,593    12,479       100.0%

[exit code 0]
```

### campaigns

UTM breakdowns need Web Analytics Plus or Enterprise. On a lower plan this
query is legal and comes back empty rather than failing. Sessions with no
campaign are the `(none)` row.

```console
$ python3 -m vercel_insights campaigns --since 2026-08-07 --until 2026-08-14
Vercel Web Analytics: prj_9xQ2vB7kLmT4dRnW (campaigns)
Range: 2026-08-07T00:00:00Z to 2026-08-14T00:00:00Z (UTC)

utmCampaign        pageviews  visitors  % pageviews
-----------------  ---------  --------  -----------
(none)                20,583     7,927        57.8%
launch-week            5,322     2,346        15.0%
docs-refresh           3,528     1,559         9.9%
newsletter-august      2,760     1,249         7.8%
conf-sponsorship       1,876       861         5.3%
retargeting-q3         1,524       676         4.3%
-----------------  ---------  --------  -----------
TOTAL                 35,593    14,618       100.0%

[exit code 0]
```

### events

Custom events need Pro or above. The metric column is `count` rather than
`pageviews`: this is the events dataset, and its metric names differ.

```console
$ python3 -m vercel_insights events --since 2026-08-07 --until 2026-08-14
Vercel Web Analytics: prj_9xQ2vB7kLmT4dRnW (events)
Range: 2026-08-07T00:00:00Z to 2026-08-14T00:00:00Z (UTC)

eventName           count  visitors  % count
------------------  -----  --------  -------
docs_search         1,288     1,184    42.1%
cta_click             680       657    22.2%
signup                410       407    13.4%
plan_selected         371       369    12.1%
feedback_submitted    310       303    10.1%
------------------  -----  --------  -------
TOTAL               3,059     2,920   100.0%

[exit code 0]
```

### events broken out by an event property

`--event-property plan` adds a second grouping dimension, `eventData/plan`. The
API returns those rows keyed `eventData` rather than `eventData/plan`, and the
client maps the key back onto the dimension that was asked for, which is why
the column heading reads `eventData/plan`. Events that carry no `plan` property
are grouped under `(none)`.

```console
$ python3 -m vercel_insights events --event-property plan --since 2026-08-07 --until 2026-08-14
Vercel Web Analytics: prj_9xQ2vB7kLmT4dRnW (events)
Range: 2026-08-07T00:00:00Z to 2026-08-14T00:00:00Z (UTC)

eventName           eventData/plan  count  visitors  % count
------------------  --------------  -----  --------  -------
docs_search         (none)          1,288     1,184    42.1%
cta_click           (none)            680       657    22.2%
feedback_submitted  (none)            310       303    10.1%
signup              free              277       276     9.1%
plan_selected       free              218       217     7.1%
plan_selected       pro               127       127     4.2%
signup              pro               109       109     3.6%
plan_selected       enterprise         26        26     0.8%
signup              enterprise         24        24     0.8%
------------------  --------------  -----  --------  -------
TOTAL                               3,059     2,923   100.0%

[exit code 0]
```

### total

The count endpoint: one ungrouped total, production traffic only. This is the
only way to get distinct visitors over the whole window, for the reason the
summary table above spells out.

```console
$ python3 -m vercel_insights total --since 2026-08-07 --until 2026-08-14
Vercel Web Analytics: prj_9xQ2vB7kLmT4dRnW (total)
Range: 2026-08-07T00:00:00Z to 2026-08-14T00:00:00Z (UTC)

  pageviews  35,593
  visitors   12,479

[exit code 0]
```

## Speed Insights: how fast

### vitals

The Speed Insights counterpart of `overview`. The query API answers for one
metric per request, so this preset issues five and composes the answers into
one table: the metric, its P75, Vercel's published target, whether the value
meets it, and how many measurements are behind it.

The verdict is deliberately two tier. Vercel publishes a "good" target per
metric and no boundary above it, so there is no honest third tier to print; the
dashboard's good, needs improvement and poor bands describe a derived 0 to 100
score, not a raw millisecond figure.

```console
$ python3 -m vercel_insights vitals --since 2026-08-07 --until 2026-08-14
Vercel Speed Insights: prj_9xQ2vB7kLmT4dRnW
Range: 2026-08-07T00:00:00Z to 2026-08-14T00:00:00Z (UTC)

metric                        p75  target  verdict       data points
-------------------------  ------  ------  ------------  -----------
Largest Contentful Paint    2.2 s   2.5 s  meets target       35,593
Interaction to Next Paint  205 ms  200 ms  over target        27,741
Cumulative Layout Shift     0.051   0.100  meets target       35,593
First Contentful Paint      1.2 s   1.8 s  meets target       35,593
Time to First Byte         720 ms  800 ms  meets target       35,593

Lower is better for all five metrics.
The target is Vercel's published 'good' threshold, so the verdict is two tier: meets target or over target.
A percentile over few data points is not comparable to one over many, so read the value next to its data point count.
Real Experience Score is not queryable through this API; read it on the Speed Insights dashboard.

[exit code 0]
```

Milliseconds render as milliseconds below one second and as seconds with one
decimal above it, the way Vercel writes them. Cumulative Layout Shift is
unitless, so it keeps three decimals.

Filters work here too, and this is the answer to "why does the site feel slow
on mobile":

```console
$ python3 -m vercel_insights vitals --device mobile --since 2026-08-07 --until 2026-08-14
Vercel Speed Insights: prj_9xQ2vB7kLmT4dRnW
Range: 2026-08-07T00:00:00Z to 2026-08-14T00:00:00Z (UTC)
Filter: device_type eq 'mobile'

metric                        p75  target  verdict       data points
-------------------------  ------  ------  ------------  -----------
Largest Contentful Paint    2.7 s   2.5 s  over target        10,057
Interaction to Next Paint  275 ms  200 ms  over target         7,834
Cumulative Layout Shift     0.050   0.100  meets target       10,057
First Contentful Paint      1.5 s   1.8 s  meets target       10,057
Time to First Byte         894 ms  800 ms  over target        10,057

Lower is better for all five metrics.
The target is Vercel's published 'good' threshold, so the verdict is two tier: meets target or over target.
A percentile over few data points is not comparable to one over many, so read the value next to its data point count.
Real Experience Score is not queryable through this API; read it on the Speed Insights dashboard.

[exit code 0]
```

Three of the five miss on mobile where only one misses site wide, and mobile is
28.3% of this site's page views. That is the whole argument for grouping a web
vital before acting on it.

### slowest-pages

P75 LCP by route, worst first. Two things are missing from this table on
purpose: there is no totals row and no share of total column, because summing
or percentaging a percentile would produce a number that means nothing. What
takes their place is the data point count, so a route with 874 measurements
cannot be read as though it were as solid as one with 9,464.

```console
$ python3 -m vercel_insights slowest-pages --since 2026-08-07 --until 2026-08-14
Vercel Speed Insights: prj_9xQ2vB7kLmT4dRnW (slowest-pages, p75)
Range: 2026-08-07T00:00:00Z to 2026-08-14T00:00:00Z (UTC)

route         p75_lcp  data_points
------------  -------  -----------
/dashboard      3.6 s        1,923
/blog/[slug]    2.7 s        4,942
/docs/[slug]    2.2 s        9,464
/pricing        2.1 s        4,452
/changelog      2.0 s        1,848
/docs           1.9 s        5,404
/about          1.8 s          874
/               1.7 s        4,446
/login          1.6 s        2,240

Metric: vercel.speed_insights.lcp_ms (Largest Contentful Paint)
Target: 2.5 s or less
Lower is better for all five metrics.
The target is Vercel's published 'good' threshold, so the verdict is two tier: meets target or over target.
A percentile over few data points is not comparable to one over many, so read the value next to its data point count.

[exit code 0]
```

`--metric` switches which vital is reported. This is the same route ranking for
Interaction to Next Paint, and it is where the site's one failing metric lives:

```console
$ python3 -m vercel_insights slowest-pages --metric inp --limit 5 --since 2026-08-07 --until 2026-08-14
Vercel Speed Insights: prj_9xQ2vB7kLmT4dRnW (slowest-pages, p75)
Range: 2026-08-07T00:00:00Z to 2026-08-14T00:00:00Z (UTC)

route         p75_inp  data_points
------------  -------  -----------
/dashboard     527 ms        1,523
/docs/[slug]   228 ms        7,388
/blog/[slug]   227 ms        3,882
/pricing       184 ms        3,469
/changelog     175 ms        1,407

Metric: vercel.speed_insights.inp_ms (Interaction to Next Paint)
Target: 200 ms or less
Lower is better for all five metrics.
The target is Vercel's published 'good' threshold, so the verdict is two tier: meets target or over target.
A percentile over few data points is not comparable to one over many, so read the value next to its data point count.

[exit code 0]
```

`--percentile` switches which percentile is requested. P95 asks about the
slowest tail rather than the typical visit, and every route moves:

```console
$ python3 -m vercel_insights slowest-pages --percentile 95 --limit 5 --since 2026-08-07 --until 2026-08-14
Vercel Speed Insights: prj_9xQ2vB7kLmT4dRnW (slowest-pages, p95)
Range: 2026-08-07T00:00:00Z to 2026-08-14T00:00:00Z (UTC)

route         p95_lcp  data_points
------------  -------  -----------
/dashboard      5.3 s        1,923
/blog/[slug]    4.0 s        4,942
/docs/[slug]    3.2 s        9,464
/pricing        3.0 s        4,452
/changelog      2.9 s        1,848

Metric: vercel.speed_insights.lcp_ms (Largest Contentful Paint)
Target: 2.5 s or less
Lower is better for all five metrics.
The target is Vercel's published 'good' threshold, so the verdict is two tier: meets target or over target.
A percentile over few data points is not comparable to one over many, so read the value next to its data point count.

[exit code 0]
```

### fastest-pages

The same query ordered the other way. It is the one worth running after a fix,
to see what good looks like on this site rather than in a benchmark.

```console
$ python3 -m vercel_insights fastest-pages --since 2026-08-07 --until 2026-08-14
Vercel Speed Insights: prj_9xQ2vB7kLmT4dRnW (fastest-pages, p75)
Range: 2026-08-07T00:00:00Z to 2026-08-14T00:00:00Z (UTC)

route         p75_lcp  data_points
------------  -------  -----------
/login          1.6 s        2,240
/               1.7 s        4,446
/about          1.8 s          874
/docs           1.9 s        5,404
/changelog      2.0 s        1,848
/pricing        2.1 s        4,452
/docs/[slug]    2.2 s        9,464
/blog/[slug]    2.7 s        4,942
/dashboard      3.6 s        1,923

Metric: vercel.speed_insights.lcp_ms (Largest Contentful Paint)
Target: 2.5 s or less
Lower is better for all five metrics.
The target is Vercel's published 'good' threshold, so the verdict is two tier: meets target or over target.
A percentile over few data points is not comparable to one over many, so read the value next to its data point count.

[exit code 0]
```

### vitals-by-country

Grouped results are ordered by data point count by default, not by value, so a
country with a handful of measurements cannot lead the table on the strength of
a percentile computed over nothing. Pass `--order-by value` to rank by the
metric instead.

```console
$ python3 -m vercel_insights vitals-by-country --since 2026-08-07 --until 2026-08-14
Vercel Speed Insights: prj_9xQ2vB7kLmT4dRnW (vitals-by-country, p75)
Range: 2026-08-07T00:00:00Z to 2026-08-14T00:00:00Z (UTC)

country  p75_lcp  data_points
-------  -------  -----------
US         1.9 s       11,356
DE         2.1 s        4,390
GB         2.1 s        3,188
IN         2.8 s        3,091
FR         2.1 s        2,520
CA         2.0 s        2,290
BR         2.7 s        2,101
NL         2.1 s        1,697
JP         2.4 s        1,416
AU         2.6 s        1,214

Metric: vercel.speed_insights.lcp_ms (Largest Contentful Paint)
Target: 2.5 s or less
Lower is better for all five metrics.
The target is Vercel's published 'good' threshold, so the verdict is two tier: meets target or over target.
A percentile over few data points is not comparable to one over many, so read the value next to its data point count.

[exit code 0]
```

Ten rows out of thirteen countries, and no `Others`: this API documents a limit
on grouped results and no overflow bucket, so the three smallest are absent
rather than collapsed. Three of the ten are over the 2.5 s target (`IN` 2.8 s,
`BR` 2.7 s, `AU` 2.6 s) while the site wide figure is 2.2 s, which is the
distance an edge network still has to cover.

### vitals-by-device

```console
$ python3 -m vercel_insights vitals-by-device --since 2026-08-07 --until 2026-08-14
Vercel Speed Insights: prj_9xQ2vB7kLmT4dRnW (vitals-by-device, p75)
Range: 2026-08-07T00:00:00Z to 2026-08-14T00:00:00Z (UTC)

device_type  p75_lcp  data_points
-----------  -------  -----------
desktop        1.9 s       24,171
mobile         2.7 s       10,057
tablet         2.3 s        1,365

Metric: vercel.speed_insights.lcp_ms (Largest Contentful Paint)
Target: 2.5 s or less
Lower is better for all five metrics.
The target is Vercel's published 'good' threshold, so the verdict is two tier: meets target or over target.
A percentile over few data points is not comparable to one over many, so read the value next to its data point count.

[exit code 0]
```

The same breakdown for INP is what turns "the site feels slow on phones" into a
number:

```console
$ python3 -m vercel_insights vitals-by-device --metric inp --since 2026-08-07 --until 2026-08-14
Vercel Speed Insights: prj_9xQ2vB7kLmT4dRnW (vitals-by-device, p75)
Range: 2026-08-07T00:00:00Z to 2026-08-14T00:00:00Z (UTC)

device_type  p75_inp  data_points
-----------  -------  -----------
desktop       172 ms       18,845
mobile        275 ms        7,834
tablet        208 ms        1,062

Metric: vercel.speed_insights.inp_ms (Interaction to Next Paint)
Target: 200 ms or less
Lower is better for all five metrics.
The target is Vercel's published 'good' threshold, so the verdict is two tier: meets target or over target.
A percentile over few data points is not comparable to one over many, so read the value next to its data point count.

[exit code 0]
```

### vitals-trend

P75 over time. The time bucket is not part of the grouping on this surface: it
travels as `granularity`, which this API spells `1h`, `1d` and `1mo`. The
column heading is the bucket as that API spells it.

```console
$ python3 -m vercel_insights vitals-trend --metric inp --since 2026-08-07 --until 2026-08-14
Vercel Speed Insights: prj_9xQ2vB7kLmT4dRnW (vitals-trend, p75)
Range: 2026-08-07T00:00:00Z to 2026-08-14T00:00:00Z (UTC)

1d          p75_inp  data_points
----------  -------  -----------
2026-08-07   192 ms        4,233
2026-08-08   191 ms        3,088
2026-08-09   195 ms        2,844
2026-08-10   213 ms        4,486
2026-08-11   213 ms        4,462
2026-08-12   214 ms        4,524
2026-08-13   213 ms        4,104

Metric: vercel.speed_insights.inp_ms (Interaction to Next Paint)
Target: 200 ms or less
Lower is better for all five metrics.
The target is Vercel's published 'good' threshold, so the verdict is two tier: meets target or over target.
A percentile over few data points is not comparable to one over many, so read the value next to its data point count.

[exit code 0]
```

The daily data point counts add up to the 27,741 that the `vitals` table
reports for INP, because a bucketed query splits the same measurements rather
than sampling them again.

Add a filter and the same trend answers for one route. This is the deploy that
the site wide trend only hints at:

```console
$ python3 -m vercel_insights vitals-trend --metric inp --route /dashboard --since 2026-08-07 --until 2026-08-14
Vercel Speed Insights: prj_9xQ2vB7kLmT4dRnW (vitals-trend, p75)
Range: 2026-08-07T00:00:00Z to 2026-08-14T00:00:00Z (UTC)
Filter: route eq '/dashboard'

1d          p75_inp  data_points
----------  -------  -----------
2026-08-07   369 ms          232
2026-08-08   392 ms          152
2026-08-09   407 ms          161
2026-08-10   591 ms          256
2026-08-11   654 ms          221
2026-08-12   584 ms          263
2026-08-13   606 ms          238

Metric: vercel.speed_insights.inp_ms (Interaction to Next Paint)
Target: 200 ms or less
Lower is better for all five metrics.
The target is Vercel's published 'good' threshold, so the verdict is two tier: meets target or over target.
A percentile over few data points is not comparable to one over many, so read the value next to its data point count.

[exit code 0]
```

### data-points

The `*_count` metrics: how many measurements each route contributed. This is
the one Speed Insights table that does keep a totals row and a share column,
because a sum of counts genuinely adds up, and it gets its own legend rather
than the web vitals one, since more measurements is better while a lower metric
value is better.

```console
$ python3 -m vercel_insights data-points --since 2026-08-07 --until 2026-08-14
Vercel Speed Insights: prj_9xQ2vB7kLmT4dRnW (data-points, sum)
Range: 2026-08-07T00:00:00Z to 2026-08-14T00:00:00Z (UTC)

route         sum_lcp_count  % sum_lcp_count
------------  -------------  ---------------
/docs/[slug]          9,464            26.6%
/docs                 5,404            15.2%
/blog/[slug]          4,942            13.9%
/pricing              4,452            12.5%
/                     4,446            12.5%
/login                2,240             6.3%
/dashboard            1,923             5.4%
/changelog            1,848             5.2%
/about                  874             2.5%
------------  -------------  ---------------
TOTAL                35,593           100.0%

Metric: vercel.speed_insights.lcp_count (Largest Contentful Paint data points)
These are data point counts, not metric values: one data point is one measurement of one web vital during one visit, and a visit produces up to six.
They are what makes a percentile trustworthy, so a group with few of them is not comparable to one with many.

[exit code 0]
```

## Output formats

### JSON, Web Analytics

`--json` prints the normalized rows and totals, plus the untouched API payload
under `raw` so nothing is lost in translation.

```console
$ python3 -m vercel_insights devices --json --since 2026-08-07 --until 2026-08-14
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
        "pageviews": 24171,
        "visitors": 8431
      }
    },
    {
      "key": "mobile",
      "groups": {
        "deviceType": "mobile"
      },
      "timestamp": null,
      "metrics": {
        "pageviews": 10057,
        "visitors": 3565
      }
    },
    {
      "key": "tablet",
      "groups": {
        "deviceType": "tablet"
      },
      "timestamp": null,
      "metrics": {
        "pageviews": 1365,
        "visitors": 483
      }
    }
  ],
  "totals": {
    "pageviews": 35593,
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
        "pageviews": 24171,
        "visitors": 8431
      },
      {
        "deviceType": "mobile",
        "pageviews": 10057,
        "visitors": 3565
      },
      {
        "deviceType": "tablet",
        "pageviews": 1365,
        "visitors": 483
      }
    ]
  }
}

[exit code 0]
```

### JSON, Speed Insights

The same document, with the fields a web vital needs in order to be
interpreted: the metric id, its human label, its unit and its published target.
`totals` is `null` rather than a number, because these rows do not add up.

```console
$ python3 -m vercel_insights vitals-by-device --metric inp --json --since 2026-08-07 --until 2026-08-14
{
  "query": {
    "metric": "vercel.speed_insights.inp_ms",
    "aggregation": "p75",
    "startTime": "2026-08-07T00:00:00Z",
    "endTime": "2026-08-14T00:00:00Z",
    "groupBy": [
      "device_type"
    ]
  },
  "range": {
    "since": "2026-08-07T00:00:00Z",
    "until": "2026-08-14T00:00:00Z"
  },
  "dataset": "speed-insights",
  "groupBy": [
    "device_type"
  ],
  "isCount": false,
  "metrics": [
    "p75_inp",
    "data_points"
  ],
  "metric": "vercel.speed_insights.inp_ms",
  "metricLabel": "Interaction to Next Paint",
  "unit": "ms",
  "target": 200.0,
  "granularity": null,
  "rows": [
    {
      "key": "desktop",
      "groups": {
        "device_type": "desktop"
      },
      "timestamp": null,
      "metrics": {
        "p75_inp": 171.6838,
        "data_points": 18845.0
      }
    },
    {
      "key": "mobile",
      "groups": {
        "device_type": "mobile"
      },
      "timestamp": null,
      "metrics": {
        "p75_inp": 275.2905,
        "data_points": 7834.0
      }
    },
    {
      "key": "tablet",
      "groups": {
        "device_type": "tablet"
      },
      "timestamp": null,
      "metrics": {
        "p75_inp": 207.711,
        "data_points": 1062.0
      }
    }
  ],
  "totals": null,
  "raw": {
    "version": 2,
    "query": {
      "metric": "vercel.speed_insights.inp_ms",
      "aggregation": "p75",
      "startTime": "2026-08-07T00:00:00Z",
      "endTime": "2026-08-14T00:00:00Z",
      "groupBy": [
        "device_type"
      ]
    },
    "data": [
      {
        "device_type": "desktop",
        "value": 171.6838,
        "count": 18845
      },
      {
        "device_type": "mobile",
        "value": 275.2905,
        "count": 7834
      },
      {
        "device_type": "tablet",
        "value": 207.711,
        "count": 1062
      }
    ]
  }
}

[exit code 0]
```

### CSV

`--csv` writes a header row of the time bucket and group columns followed by
the metric columns, then one row per group. It goes through `csv.writer`, so a
label containing a comma or a quote stays correct.

```console
$ python3 -m vercel_insights trend --csv --since 2026-08-07 --until 2026-08-14
day,pageviews,visitors
2026-08-07,5389,2449
2026-08-08,3956,1796
2026-08-09,3693,1678
2026-08-10,5754,2616
2026-08-11,5730,2609
2026-08-12,5790,2603
2026-08-13,5281,2384

[exit code 0]
```

CSV carries the values as they arrived, unrounded and unformatted, because the
next tool in the pipeline should do its own rounding:

```console
$ python3 -m vercel_insights vitals-trend --metric inp --csv --since 2026-08-07 --until 2026-08-14
1d,p75_inp,data_points
2026-08-07,192.0465,4233.0
2026-08-08,191.4646,3088.0
2026-08-09,194.8626,2844.0
2026-08-10,212.7102,4486.0
2026-08-11,212.8368,4462.0
2026-08-12,213.7763,4524.0
2026-08-13,213.0439,4104.0

[exit code 0]
```

## Dry runs

`--dry-run` prints the exact request that would be sent and sends nothing. It
needs no token, which makes it the safest way to check a filter before spending
a rate limit on it. The `Authorization` header is redacted here and everywhere
else this client renders headers. Both blocks were captured with no
`VERCEL_TOKEN` in the environment at all.

### A Web Analytics GET

```console
$ python3 -m vercel_insights top-pages --country US --dry-run --since 2026-08-07 --until 2026-08-14
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
  User-Agent     vercel-insights-skill/0.2.0

Encoded URL (never contains the token):
  https://api.vercel.com/v1/query/web-analytics/visits/aggregate?projectId=prj_9xQ2vB7kLmT4dRnW&by=requestPath&since=2026-08-07T00%3A00%3A00Z&until=2026-08-14T00%3A00%3A00Z&limit=10&filter=country+eq+%27US%27

Nothing was sent. No credential is printed above.

[exit code 0]
```

### A Speed Insights POST

Speed Insights is a POST because Vercel exposes no GET equivalent for an
observability query: the query travels in the body. It is still a read, and
nothing else about it changes. A dry run of a POST prints the whole body, which
is the only way to see what was actually asked. Note what `--device mobile`
compiled to: `device_type eq 'mobile'` here, against the `deviceType eq
'mobile'` in the filtered `top-pages` block above. One flag, two spellings,
chosen by the surface the query is going to.

```console
$ python3 -m vercel_insights slowest-pages --device mobile --dry-run --since 2026-08-07 --until 2026-08-14
POST https://api.vercel.com/v2/observability/query

Query parameters:
  (none)

Headers:
  Accept         application/json
  Authorization  Bearer <redacted>
  User-Agent     vercel-insights-skill/0.2.0

JSON body:
  {
    "metric": "vercel.speed_insights.lcp_ms",
    "scope": {
      "type": "project",
      "projectId": "prj_9xQ2vB7kLmT4dRnW"
    },
    "aggregation": "p75",
    "groupBy": [
      "route"
    ],
    "filter": "device_type eq 'mobile'",
    "limit": 10,
    "orderBy": "value",
    "orderDirection": "desc",
    "startTime": "2026-08-07T00:00:00Z",
    "endTime": "2026-08-14T00:00:00Z"
  }

Encoded URL (never contains the token):
  https://api.vercel.com/v2/observability/query

Nothing was sent. No credential is printed above.

[exit code 0]
```

## Empty results

An empty result set is a success, not an error: exit code 0, one line naming
the resolved range and the active filter, and no empty table or traceback.

```console
$ python3 -m vercel_insights events --event-name checkout_started --since 2026-08-07 --until 2026-08-14
No events data for project prj_9xQ2vB7kLmT4dRnW (grouped by eventName) between 2026-08-07T00:00:00Z and 2026-08-14T00:00:00Z with eventName eq 'checkout_started'. Try a wider --since, or relax the filter.

[exit code 0]
```

The Speed Insights surface says the same thing, naming the metric id it asked
for rather than a dataset:

```console
$ python3 -m vercel_insights vitals-by-country --country ZZ --since 2026-08-07 --until 2026-08-14
No vercel.speed_insights.lcp_ms data for project prj_9xQ2vB7kLmT4dRnW (grouped by country) between 2026-08-07T00:00:00Z and 2026-08-14T00:00:00Z with country eq 'ZZ'. Try a wider --since, or relax the filter.

[exit code 0]
```

## Configuration errors

Every validation rule runs before anything touches the network, so a mistake
costs no request and no rate limit. Each message names the offending value and
the fix, and exits 2.

```console
$ python3 -m vercel_insights top-pages --limit 500 --since 2026-08-07 --until 2026-08-14
error: --limit 500 is outside the API bounds of 1 to 100; pick a value in that range, and note that groups past the limit are not dropped, they roll into a single 'Others' row

[exit code 2]
```

```console
$ python3 -m vercel_insights top-pages --group-by contry --since 2026-08-07 --until 2026-08-14
error: unknown dimension 'contry' for the visits dataset. Did you mean 'country'? Valid dimensions: hour, day, week, month, year, country, deviceType, environment, requestPath, referrerHostname, osName, browserName, route, utmSource, utmMedium, utmCampaign, utmContent, utmTerm, flags, plus flags/<name>

[exit code 2]
```

The two APIs spell their dimensions differently, and the message says which
spelling belongs where rather than letting the API refuse it:

```console
$ python3 -m vercel_insights slowest-pages --group-by requestPath --since 2026-08-07 --until 2026-08-14
error: 'requestPath' is the Web Analytics spelling; the Speed Insights API uses snake_case, so group by 'request_path' instead

[exit code 2]
```

An option that belongs to the other surface is refused with the presets that
would accept it:

```console
$ python3 -m vercel_insights top-pages --percentile 95 --since 2026-08-07 --until 2026-08-14
error: --percentile 95 only applies to the Speed Insights surface, but the top-pages preset queries Web Analytics. Run one of vitals, slowest-pages, fastest-pages, vitals-by-country, vitals-by-device, vitals-trend, data-points, or drop the flag

[exit code 2]
```

A granularity the target API has no equivalent for is refused before the
request is built, listing what that surface does support:

```console
$ python3 -m vercel_insights vitals-trend --granularity week --since 2026-08-07 --until 2026-08-14
error: --granularity 'week' has no equivalent on the Speed Insights surface, which buckets only by hour (1h), day (1d), month (1mo); pick one of those, or run a Web Analytics preset such as trend, which does support week buckets

[exit code 2]
```

Real Experience Score is not queryable through this API. Asking for it fails
loudly and points at the dashboard rather than quietly substituting another
metric:

```console
$ python3 -m vercel_insights vitals-by-country --metric res --since 2026-08-07 --until 2026-08-14
error: --metric 'res': Real Experience Score is not queryable. Vercel states plainly that it is not available through the query API this tool uses, so there is nothing to request and this client will not substitute another metric for it. Read it on the Speed Insights tab of your project dashboard (https://vercel.com/docs/speed-insights/metrics), or query one of the five metrics it is derived from: lcp, inp, cls, fcp, ttfb

[exit code 2]
```

## A permission error

This is the `top-pages` command from further up, run against a token that has
no read access to the project: the stub answered 403 instead of a payload.
Vercel's `error.message` is surfaced verbatim, because it is the most specific
diagnostic available and it is written for humans. No stack trace reaches the
user. API and network failures exit 1, configuration mistakes exit 2.

```console
$ python3 -m vercel_insights top-pages --since 2026-08-07 --until 2026-08-14
error: HTTP 403 (forbidden): Not authorized to access the project prj_9xQ2vB7kLmT4dRnW. The token is missing the read scope for this team.

[exit code 1]
```

## Rate limiting

429 is retried, and so are 408 and 5xx. The wait comes from `Retry-After` when
the response carries one, otherwise from `error.limit.resetMs` or
`error.limit.reset`, otherwise from exponential backoff. Jitter is added on
top, and was set to zero for this capture so the printed delays are
reproducible. Once the retries are used up the error is reported with the
attempt count. `--verbose` puts the request and the retry decisions on stderr,
with the token redacted there too.

```console
$ python3 -m vercel_insights trend --max-retries 2 --verbose --since 2026-08-07 --until 2026-08-14
verbose: GET https://api.vercel.com/v1/query/web-analytics/visits/aggregate
verbose: params [('projectId', 'prj_9xQ2vB7kLmT4dRnW'), ('by', 'day'), ('since', '2026-08-07T00:00:00Z'), ('until', '2026-08-14T00:00:00Z'), ('limit', '100')]
verbose: headers {'Accept': 'application/json', 'User-Agent': 'vercel-insights-skill/0.2.0', 'Authorization': 'Bearer <redacted>'}
verbose: HTTP 429; retrying in 12.00s
verbose: HTTP 429; retrying in 12.00s
error: HTTP 429 (rate_limited): The rate limit of 100 exceeded for 'api-web-analytics-query'. Try again in 12 seconds [gave up after 3 attempts]
hint: rate limits are per endpoint; wait for the reset above or raise --max-retries so the client waits for you

[exit code 1]
```

## The preset table

`--list-presets` prints every preset with its dataset, endpoint, grouping and
default limit, and exits 0 without touching the network. These are the defaults
the sections above were captured at. A `speed` preset queries Speed Insights;
everything else queries Web Analytics.

```console
$ python3 -m vercel_insights --list-presets
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
vitals              speed    5 x query      none                                  n/a  P75 of all five web vitals against their targets
slowest-pages       speed    query          route                                  10  Routes with the worst P75 LCP, worst first
fastest-pages       speed    query          route                                  10  Routes with the best P75 LCP, best first
vitals-by-country   speed    query          country                                10  P75 of --metric (default lcp) by country
vitals-by-device    speed    query          device_type                            10  P75 of --metric (default lcp) by device type
vitals-trend        speed    query          1d                                    n/a  P75 of --metric (default lcp) over time
data-points         speed    query          route                                  10  How many measurements each route contributed

Any explicit flag overrides a preset value. Groups beyond the limit roll into a single 'Others' row rather than being dropped.
A 'speed' preset queries Speed Insights, which reports one metric per request: pick it with --metric, and note that this API spells its dimensions in snake_case (request_path, device_type).

[exit code 0]
```

## Version

`--version` prints the name the skill is installed under and the version the
blocks above were captured at, and, like `--list-presets`, touches nothing.

```console
$ python3 -m vercel_insights --version
vercel-insights 0.2.0

[exit code 0]
```
