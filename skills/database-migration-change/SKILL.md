---
name: database-migration-change
description: Changes relational schemas through immutable, forward-only migrations that follow expand-migrate-contract, keep destructive steps reviewed and late, add indexes with the queries that need them, keep change-feed timestamps truthful, and run bulk backfills safely. Use when writing or editing a migration, schema definition, index, constraint, trigger, change-feed column, data backfill, or bulk import. Not for tuning a slow query (use sql-query-performance), and not for API change-feed design (use api-contract-change).
---

# Database migration change

The database outlives every release that talks to it. Load
`sql-query-performance` for query shape and plan proof, and
`testing-strategy` for database test layers. PostgreSQL examples below are
illustrative; keep the rule when the engine differs.

## 1. Applied migrations are immutable

Once a migration has run in any shared environment, it never changes. Fix
forward with a new migration. A branch-only migration that no shared
environment has applied may be flattened to its clean end state.

Before writing one, compare the branch with the trunk that deploys:

| State | Action |
| --- | --- |
| On trunk and applied to a shared environment | Immutable; add a new migration |
| Branch-only, never applied to a shared environment | Flatten to the end state |
| Branch is missing migrations already on trunk | Rebase first |

## 2. Expand, migrate, contract

Code and schema never deploy atomically, so every migration must work with
whatever code is deployed on either side of it for at least one release.

1. **Expand** — add the new shape beside the old: new tables, nullable or
   defaulted columns, indexes, views, compatibility views, dual-write
   triggers. Backfill here, bounded and idempotent.
2. **Migrate** — ship code that reads and writes the new shape, then wait
   until no deployed consumer references the old one.
3. **Contract** — in a later release, remove the old shape: renames, drops,
   column type changes, `SET NOT NULL`, or a new `NOT NULL` column without a
   default.

On a large or busy table, expand without blocking: build indexes with the
engine's non-blocking form (when the migration runner wraps each migration in
a transaction, that build is the planned operational step in section 4), add constraints unvalidated and validate them
separately, run each statement under a short lock timeout, and avoid
statements that rewrite the table.

A migration that introduces a replacement and drops the original in the same
release turns rollback into a point of no return. Install and prove the new
guard first; drop the old one as a later contract step.

## 3. Contract steps are named and reviewed

- A contract migration carries a header marker naming the reviewed issue or
  decision that approved it, and records which release retired the last
  reader or writer and what the rollback is.
- Irreversible statements (dropping a table, a column, or an enum value) are
  named one by one in that header so the reviewer sees each destructive
  statement, not just "this file contracts".
- A mechanical check classifies every statement, including statements built
  inside dynamic SQL, and fails an unmarked contract step.

## 4. Forbidden in shared-environment rollouts

Unless the owner approves a specific named statement: dropping a table or
schema, truncating, destructive swaps, dropping a column before every reader
stopped, removing an enum value, and column type changes that are not
expand-contract safe. Session-level advisory locks, privileged functions with
an unsafe search path, and index builds that cannot run inside the migration
runner's transaction belong in a separately planned operational step.

## 5. Schema and invariants

- Constraints, foreign keys, unique indexes, and triggers in SQL are the
  authority for invariants; application types follow them. After every
  migration, update the schema definitions and confirm regeneration produces
  no diff. Commit generated migration metadata in the repository's format.
- Add an index in the same change as any new filter, sort, join, or keyset
  cursor on a large table, defined where the schema definitions live. A
  keyset index matches the cursor's `ORDER BY` exactly. Refresh statistics
  after an index built outside the migration transaction.
- Identity columns that reached production are never updated through normal
  paths; use lifecycle, deactivation, or audited reassignment instead.

## 6. Change-feed columns

Tables that drive incremental sync keep a non-null, monotonic `updated_at`,
set on insert and refreshed on every update, preferably by trigger. A child
change that alters a parent's projection advances the parent's timestamp in
the same transaction.

A timestamp taken at transaction start does not order commits: a long
transaction can commit a row behind a cursor that has already moved past it,
and a feed keyed on that timestamp silently skips the row. Before promising
that a cursor never skips a record, order the feed by a commit-ordered
sequence, or read behind a lag or overlap window that exceeds a maximum transaction
duration the database enforces, and make consumers idempotent.

## 7. Bulk import and backfill

- Backfills are bounded, batched, idempotent, and safe to resume.
- Batch per-row work into set-based statements and assert statement count,
  not wall-clock time.
- An import sets `updated_at` to the import time by default. Preserving older
  source timestamps hides the rows from active sync consumers; when that is
  required, document the consumer impact.
- Prove a backfill against representative data, not an empty database.

## Done when

- Migration metadata checks pass and the migration applies to a run-owned
  disposable database through the repository's normal migration path.
- Regenerating schema metadata produces no diff.
- Integration tests run against a run-owned disposable database. Never reset
  or reseed a shared database to make a test start.
