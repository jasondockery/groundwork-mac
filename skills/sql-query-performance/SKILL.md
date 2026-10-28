---
name: sql-query-performance
description: Keeps relational queries on data-heavy pages, lists, facets, counts, exports, and dashboards within budget through indexed keyset reads, real database timeouts, bounded aggregates, a measured escalation ladder, and plan-based proof. Use before or while writing or changing a SQL query, ORM query, pagination, count, aggregate, export, projection, rollup, materialized view, or partition, or when a list or page is slow. Not for schema migration safety (use database-migration-change).
---

# SQL query performance

Optimize from measured workload evidence. Load `performance-sensitive-change`
for the general measure-first procedure and `database-migration-change` for
index and schema changes. The repository owns its numeric budgets. PostgreSQL
examples below are illustrative; keep the rule when the engine differs.

## 1. Hard rules

- Split a data-heavy page into independently measurable detail, facet, and
  aggregate paths; one slow query must not block the page.
- Detail reads are live, indexed, select only the fields the view renders,
  and use keyset pagination. Use offset pagination only for shallow, capped
  jumps with a reviewed note.
- Never run a broad unbounded aggregate over a large table on request render.
  Every accepted aggregate has explicit cardinality and timeout bounds and
  measured proof.
- Avoid exact counts on the hot path for large tables. Prefer estimates or
  precomputed counts, and label exact versus estimated values explicitly.
- A race against a timer is not a database timeout. Unless the query receives
  a real cancellation or runs under a shorter statement timeout, it keeps
  running after the race resolves. Interactive reads use read-only
  transactions with a transaction-scoped statement timeout (for example
  `SET LOCAL statement_timeout`), never a session setting that leaks into
  pooled connections; exports have their
  own reviewed budget. A too-broad request returns a purposeful "too broad"
  result, never a raw database error.
- Add indexes in the same change as every new filter, sort, join, or keyset
  column. Leftmost columns match common constraints; wide multicolumn indexes
  stay rare. Use a trigram or equivalent text index for broad text search,
  never an unindexed substring match.
- An expression index serves only the exact expression the query uses, and a
  partial index serves only queries whose predicate implies the index
  predicate.
- Gate expensive comparison, duplicate, or reconciliation queries behind
  cheap preconditions and explicit drilldowns.
- Counts and sums combine across periods; medians, percentiles, averages, and
  distinct counts do not.
- Never cache authorization decisions globally. Projections and rollups are
  rebuildable, idempotent, labeled with their freshness, and scoped after
  authorization.

## 2. Escalation ladder

Climb only when the indexed canonical query misses its budget:

1. the canonical indexed query;
2. a rebuildable one-row-per-fact projection;
3. incremental additive period rollups;
4. a materialized view or partitioning, with explicit evidence and lifecycle
   ownership.

Add extended statistics only when correlated predicates cause demonstrated
estimate errors. A concurrently refreshed materialized view needs a unique
index over all rows, and still allows one refresh at a time.

## 3. Proof

- Refresh statistics, then capture the analyzed plan with buffer counts at
  realistic volume for both the slow and the fixed query.
- On a near-empty local database, disabling sequential scans shows whether
  an index can serve the plan at all; it does not prove realistic cost.
- Reject a full table scan on a hot path over a large table. Confirm
  estimates are close to actual rows and that pagination uses the intended
  index without sorting the whole set.
- Time row, count, and enrichment queries separately.
- A unit test proves query shape, not runtime. Prove route-level behavior
  through the real page or endpoint, not only the query helper.
- Record whether expensive counts were loaded, skipped, or deferred to a
  drilldown, and document freshness and degraded behavior for every
  projection or rollup.
- Keep index and schema migrations separate from application refactors, one
  rollback boundary per commit.
