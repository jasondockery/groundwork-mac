---
name: api-contract-change
description: Designs and changes HTTP APIs as consumable products with an audience classification, a complete OpenAPI operation bar, reusable models, deterministic change feeds, one schema source of truth, and mechanical guardrails. Use when adding or changing a REST endpoint, OpenAPI document, generated API client, API reference docs, or a change or sync feed. Not for authorization design (use secure-by-design), and not for database query shape (use sql-query-performance).
---

# API contract change

An external or contract API is a product. A consumer team, another service,
or an agent must be able to use it from the reference documentation and the
OpenAPI document alone, without reading route source. Load `secure-by-design`
for authentication and authorization, and `testing-strategy` for proof layers.

## 1. Classify the audience first

Classify every route before implementation:

- **external** — used by another organization or product team;
- **internal contract** — used across services or teams you do not control;
- **first-party interface only** — called only by your own interface;
- **private implementation detail**.

External and internal-contract routes meet this whole skill. The others
still need correct authorization, validation, and tests, but not
contract-grade reference documentation.

Before implementation, write a short design note: audience and
authentication, resources, tags, operation IDs, query model, and examples.
The repository owns its path, naming, filtering, sorting, and pagination
conventions; follow them rather than restating them.

## 2. Operation bar

Every documented external or internal-contract operation has:

- a stable, unique `operationId` and domain or audience tags;
- a short verb-object summary and a useful behavior description;
- security requirements;
- described path, query, and header parameters with examples;
- request body schema and example where applicable;
- success response schema and a realistic example;
- documented errors: validation (`400`), authentication and authorization
  (`401`, `403`) when secured, not found (`404`) for path lookups, conflict
  (`409`) where duplicates are possible, and a generic server or `default`
  error.

Examples come from real current shapes. Do not ship stale fields, placeholder
values, or fields the implementation no longer returns.

## 3. Models are named and reusable

Expose reusable named schemas for list and detail responses, page or cursor
objects, change-feed responses, and the error or problem shape. Inline-only
operation schemas are not enough. A model shared across APIs has one
canonical definition that documents reference. Copy it only where the
tooling cannot reference it, and then the copy must match the canonical
definition exactly; the guardrail checks every declared shared model.

## 4. Change feeds

A syncable domain exposes a change feed, or records why it does not.

- Paginate by keyset: change timestamp plus a tie-breaker ID, or an opaque
  cursor with the same semantics. Never timestamp-only.
- Order deterministically. Each item carries the change time, canonical ID,
  change type, and the full resource or a documented partial or tombstone
  projection.
- Each page carries `limit`, `hasMore`, and `nextCursor`. A consumer persists
  the cursor only after processing the whole page, and the cursor never moves
  past an unreturned record. A transaction-start timestamp alone cannot keep
  that promise; load `database-migration-change` for the commit-ordering
  rule.

## 5. Compatibility

A released contract only grows, judged by the direction data flows:

- Requests: adding an optional field or operation is safe; making a field
  required, removing an accepted value, tightening validation, or removing,
  renaming, or retyping a field or operation breaks callers.
- Responses: adding a field is safe and clients must ignore unknown fields;
  making a field always present is safe; removing, renaming, or retyping one,
  or making it optional or nullable, breaks clients. A new enum value is additive only when the contract
  declares the enum open and requires clients to tolerate unknown values.

A breaking change needs a deprecation period announced in the contract, and a
new version when consumers cannot migrate in place. A contract-diff check against
the last released document flags every breaking change for explicit review.

## 6. One source of truth

- If YAML or JSON is the source, edit it and regenerate derived formats
  through the repository's command. If code-first schemas generate the
  document, edit those schemas.
- Never hand-edit generated documents unless that is the documented
  convention. When two formats exist, test that the served document matches
  the source.

## 7. Reference documentation

Publish a hosted reference page, the raw machine-readable document, visible
models, and the real server URL for each audience and environment. Interactive
"try it" requests must not fail from a base-path or server-prefix mismatch. A
request-runner workspace is not primary documentation.

## 8. Guardrails

Mechanically verify that required operations exist, operation IDs are unique,
success responses reference schemas and have examples, standard errors are
documented, change feeds include their page fields, contract APIs expose
named schemas, declared shared models match their canonical definition,
breaking changes are flagged, and server and
path composition neither double-prefixes nor drops the base path. Extend the
repository's existing OpenAPI validation before adding a parallel checker.

## Done when

Route tests, schema and generated-client tests, and OpenAPI validation pass;
the reference page renders; the raw document downloads; and "try it" targets
the right environment. Missing models, missing examples, no change-feed
decision, or a broken "try it" URL blocks merge for new contract API work.
