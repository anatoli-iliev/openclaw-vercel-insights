# Vercel Web Analytics API: verified ground truth

Everything here was read from the live Vercel docs on 2026-08-14. Where this file
disagrees with memory, folklore, or a blog post, this file wins. Re-verify against
the sources below before changing request or response handling.

Sources:

- <https://vercel.com/docs/analytics/web-analytics-api> (concepts, worked examples)
- <https://vercel.com/docs/rest-api/web-analytics/counts-page-views>
- <https://vercel.com/docs/rest-api/web-analytics/aggregates-page-views>
- <https://vercel.com/docs/rest-api/web-analytics/counts-custom-events>
- <https://vercel.com/docs/rest-api/web-analytics/aggregates-custom-events>
- <https://vercel.com/docs/rest-api/errors> (error envelope, rate limiting)
- <https://vercel.com/docs/analytics/limits-and-pricing> (reporting window)

## Endpoints

Base: `https://api.vercel.com/v1/query/web-analytics`

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/visits/count` | One total of page views. Production only. |
| GET | `/visits/aggregate` | Page view rows grouped by time and/or one dimension. |
| GET | `/events/count` | One total of custom events. Production only. |
| GET | `/events/aggregate` | Custom event rows grouped by time and/or one dimension. |

All four are GET. There is no write surface in this API.

## Authentication

`Authorization: Bearer <token>` using a Vercel access token. Project and team are
passed as query parameters, not headers.

## Query parameters

### count endpoints (`/visits/count`, `/events/count`)

| Name | Required | Notes |
| --- | --- | --- |
| `projectId` | yes | Project ID or project name. |
| `since` | no | Timestamp in milliseconds, or a valid Date string. |
| `until` | no | Timestamp in milliseconds, or a valid Date string. |
| `filter` | no | OData filter. URL-encode the value. |
| `teamId` | no | Team ID. Omit for personal-account projects. |
| `slug` | no | Team slug. Alternative to `teamId`. |

The docs describe count as counting "on a project (production only), since Web
Analytics was enabled". There is no `by` and no `limit`.

### aggregate endpoints (`/visits/aggregate`, `/events/aggregate`)

| Name | Required | Notes |
| --- | --- | --- |
| `projectId` | yes | Project ID or project name. |
| `by` | **yes** | Up to two dimensions. At most one time granularity. |
| `since` | **yes** | Timestamp in milliseconds, or a valid Date string. |
| `until` | **yes** | Timestamp in milliseconds, or a valid Date string. |
| `limit` | no | Integer, min 1, max 100, default 10. |
| `filter` | no | OData filter. URL-encode the value. |
| `teamId` | no | Team ID. |
| `slug` | no | Team slug. |

`by` is required. There is no such thing as an ungrouped aggregate query. An
ungrouped total must use a count endpoint, or must group by a time granularity.

`limit` bounds the number of distinct groups. Remaining groups are collapsed into
a single row named `Others`, which still contributes to the represented total.

### How `by` is serialized on the wire

Confirmed against the machine-readable OpenAPI document at
<https://openapi.vercel.sh/>. The `by` parameter is:

```json
{
  "name": "by",
  "in": "query",
  "required": true,
  "schema": {
    "type": "array",
    "minItems": 1,
    "maxItems": 2,
    "uniqueItems": true,
    "example": ["day", "country"]
  }
}
```

The document is OpenAPI 3.0.3 and sets neither `style` nor `explode` on this
parameter, so the specification defaults apply: `style: form` with
`explode: true`. Array values are therefore sent as **repeated query parameters**,
not as one comma-joined value:

```
?by=day&by=country
```

`uniqueItems: true` means the same dimension must not appear twice, and
`maxItems: 2` is the hard ceiling. Both are rejected client-side before any
request goes out.

The schema also pins the accepted JSON dimension syntax as a regular expression,
`^(flags)(/([0-9A-Za-z_]+|'([^']|'')*'))+$` on the visits dataset, which confirms
that keys may be bare when they are alphanumeric-plus-underscore and must
otherwise be single-quoted with embedded quotes doubled.

## Dimensions

Time granularities, at most one per query: `hour`, `day`, `week`, `month`, `year`.

Plain dimensions, valid on both datasets:

`country`, `deviceType`, `environment`, `requestPath`, `referrerHostname`,
`osName`, `browserName`, `route`, `utmSource`, `utmMedium`, `utmCampaign`,
`utmContent`, `utmTerm`

Events-only additional dimension: `eventName`

JSON dimensions:

- `flags` (both datasets). Bare, it groups by flag name. With a key, `flags/beta_banner`, it groups by that flag's value.
- `eventData` (events dataset only). Bare, it groups by property name. With a key, `eventData/plan`, it groups by that property's value.

Keys containing anything other than letters, digits, and underscores must be
wrapped in single quotes: `flags/'my-flag'`, `eventData/'signup-source'`.

`requestPath` is the exact URL path without query parameters, for example
`/blog/my-post`. `route` is the framework route pattern, for example
`/blog/[slug]`, so many URLs roll up into one row.

## Filters

OData syntax. Quote string values with single quotes and URL-encode the whole
expression.

Supported: `eq`, `ne`, `in`, the logical operators `and`, `or`, `not`,
parentheses, and functions such as `startswith` that the OData parser accepts.

**There are no comparison operators** (`gt`, `lt`, `ge`, `le`) documented for this
API. Do not emit them.

Filterable dimensions match the grouping dimensions above, including
`flags/<name> eq 'true'` and, on events, `eventData/<property> eq 'pro'`.

Example: `requestPath eq '/pricing' and country eq 'US'`

Aggregate endpoints document that the filter "by default, filters for production
environment only". Pass `environment eq 'preview'` to reach preview data.

## Response shapes

Every response is `{ "version": <number>, "query": {...}, "data": ... }`.

`query` echoes the interpreted request. On aggregate it always contains `since`,
`until`, and `limit`, and may contain `groupBy` (an array) and `filter`. On count
it always contains `since` and `until`, and may contain `filter`.

### count

`data` is a single object.

- `/visits/count`: `{ "pageviews": number, "visitors": number }`
- `/events/count`: `{ "count": number, "visitors": number }`

```json
{
  "version": 1,
  "query": { "filter": "requestPath eq '/blog/my-post'" },
  "data": { "pageviews": 1250, "visitors": 980 }
}
```

### aggregate

`data` is an array of row objects.

Grouped by a time granularity, each row carries a `timestamp` plus the metrics:

```json
{
  "version": 1,
  "query": {
    "since": "2024-10-01",
    "until": "2024-10-07",
    "groupBy": ["day"],
    "filter": "requestPath eq '/blog/my-post'"
  },
  "data": [
    { "timestamp": "2024-10-01T00:00:00.000Z", "pageviews": 220, "visitors": 180 },
    { "timestamp": "2024-10-02T00:00:00.000Z", "pageviews": 245, "visitors": 201 }
  ]
}
```

Grouped by a plain dimension, each row carries that dimension as a key:

```json
{
  "data": [
    { "country": "US", "pageviews": 640, "visitors": 510 },
    { "country": "DE", "pageviews": 180, "visitors": 150 }
  ]
}
```

### Parsing trap: JSON dimension row keys

Grouping by `eventData/plan` returns rows keyed **`eventData`**, not
`eventData/plan`:

```json
{
  "query": { "groupBy": ["eventData/plan"] },
  "data": [
    { "eventData": "pro", "count": 42, "visitors": 36 },
    { "eventData": "enterprise", "count": 12, "visitors": 10 }
  ]
}
```

The same applies to `flags/<name>`, which returns rows keyed `flags`. Normalization
must map the returned base key back to the requested dimension so output labels
read correctly.

### Metric names differ per dataset

- visits: `pageviews`, `visitors`
- events: `count`, `visitors`

Code must not assume `pageviews` exists on an events response.

### A note on the published JSON Schema

The REST reference pages publish a generated `oneOf` schema whose row variant
lists roughly 300 field names as `required` (every telemetry column Vercel has,
including AI gateway and workflow fields). That is a schema-generation artifact of
a shared internal row type, not a description of real responses. Real rows contain
only the grouped dimension plus the dataset's metrics, as the worked examples
above show. Parse defensively: read known metric keys, treat everything else as
the group key, and never require fields the examples do not show.

## Errors

Documented statuses on these endpoints: `400` (invalid query value), `401` (not
authorized), `402`, `403` (no permission), `410`.

The envelope is consistent across the REST API:

```json
{ "error": { "code": "bad_request", "message": "An english description of the error that just occurred" } }
```

Rate limiting returns code `rate_limited` and carries a `limit` object:

```json
{
  "error": {
    "code": "rate_limited",
    "message": "The rate limit of 6 exceeded for 'api-www-user-update-username'. Try again in 7 days",
    "limit": { "remaining": 0, "reset": 1571432075, "resetMs": 1571432075563, "total": 6 }
  }
}
```

`reset` is Unix seconds; `resetMs` is Unix milliseconds. Rate limits are documented
as per-endpoint, so one throttled endpoint does not block the others.

Surface `error.message` verbatim to the user. It is the most specific diagnostic
available and is written for humans.

## Reporting window

The reporting window is how long analytics data is guaranteed to be queryable.

| Plan | Reporting window |
| --- | --- |
| Hobby | 1 month |
| Pro | 12 months |
| Pro with Web Analytics Plus | 24 months |
| Enterprise | 24 months |

Plan tier is not discoverable from this API, so a `--since` older than the window
should warn rather than block: the query is still legal and may return data, since
Vercel may retain beyond the guarantee.

Other plan-gated behavior worth knowing: custom events require Pro or above, and
UTM parameters require Web Analytics Plus or Enterprise. A query for those on a
lower plan is expected to come back empty rather than to fail.
