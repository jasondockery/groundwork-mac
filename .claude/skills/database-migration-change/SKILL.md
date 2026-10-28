---
name: database-migration-change
description: Changes relational schemas through immutable, forward-only migrations that follow expand-migrate-contract, keep destructive steps reviewed and late, add indexes with the queries that need them, keep change-feed timestamps truthful, and run bulk backfills safely. Use when writing or editing a migration, schema definition, index, constraint, trigger, change-feed column, data backfill, or bulk import. Not for tuning a slow query (use sql-query-performance), and not for API change-feed design (use api-contract-change).
---

# database-migration-change adapter

Load `../../../skills/database-migration-change/SKILL.md` as the canonical procedure.
This adapter contains no independent policy.
