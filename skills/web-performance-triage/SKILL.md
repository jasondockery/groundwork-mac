---
name: web-performance-triage
description: Diagnoses slow, timing-out, or gateway-504 Next.js routes, React Server Component navigations, route handlers, API and polling endpoints backed by PostgreSQL, tracing from browser timing through logs to the slow statement before changing timeouts or indexes. Use only in Next.js repositories when a page is slow, times out, starves other routes, or shows database, API, or log-query pressure. Not for repositories without Next.js, and not for designing optimizations or budgets in general (use performance-sensitive-change).
---

# Web performance triage

Opt-in stack skill. It applies only where the repository serves Next.js
routes, usually backed by PostgreSQL. The repository's own budgets, gateway
timeouts, telemetry, and log tools take precedence.

Classify the incident before changing a timeout or adding an index. Fix the
server workload first; never hide timeouts behind client retries. Load
`performance-sensitive-change` for measurement and budget doctrine,
`field-failure-backpressure` when the symptom came from the field.

## Recognize saturation

Repeated route-loader failures together with gateway aborts at the gateway's
timeout are a backend saturation incident until disproven. A timeout or
fallback in application code does not cancel the database work it started;
abandoned statements keep running and starve other routes.

## Triage order

1. Map the route chain: page, layouts, shared navigation loaders, API calls,
   route handlers, and polling endpoints hit during navigation.
2. Capture browser network timing for the page, its server component payload,
   API calls, and polling calls.
3. Query the raw platform logs for the same window. Application log views can
   miss unstructured framework errors.
4. Use route and request identifiers to map slow log lines to statements or
   resolvers.
5. Inspect database activity and locks, index-build progress, and statement
   statistics when available.
6. Run `EXPLAIN (ANALYZE, BUFFERS)` only after the slow statement is known.
   `ANALYZE` executes the statement: run it on a replica or a copy, never
   against production for a data-modifying statement, and avoid adding load
   to a saturated primary.

## What to look for

- Database work that continues after the browser gave up.
- Pool or connection starvation slowing unrelated pages.
- Sequential scans or whole-table sorts on large hot-path lists.
- Aggregates, duplicate scans, exports, or raw payload reads running during
  first render when they are not the page's purpose.
- Active search or filter state carried into a destination route that
  broadens its work.
- Polling or notification endpoints that block navigation or shell hydration.
- Stale planner statistics after a bulk load.

## Fix pattern

- Contain first: remove or defer request-time aggregates and optional widgets.
  Keep the primary list query strict, paginated, and URL-driven.
- Move expensive comparisons behind drilldown links, explicit filters, or
  actions, and add cheap preconditions before heavy queries.
- When work is intentionally skipped, return an explicit "not loaded" state;
  never render a skipped count as zero.
- Treat polling and non-critical route handlers as fail-open: time-box them
  and return a shape-compatible degraded response.
- Use streaming and loading states to improve perceived progress, but never
  let navigation wait on an unbounded query.
- Add an index or refresh table statistics only with a plan that proves it
  helps. Move summary widgets to precomputed values as `nextjs-app` describes,
  and confirm search queries use an index-backed plan rather than scanning the
  whole table.
- Add structured timing for route, loader, resolver, row query, count query,
  and enrichment, with sanitized error context.

## Proof

- Before and after timing for the exact authenticated route that failed.
- Timing for the page route and every background handler it triggers.
- No gateway timeout on the route and its related API or polling calls during
  navigation, and no backend work continuing after the browser timed out.
- Other pages stay responsive after visiting the fixed page.
- Unit tests for skipped-work state, fail-open time-boxing, and URL state
  preservation.
