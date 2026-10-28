---
name: aws-sst-deploy
description: Changes AWS deploys built with SST and OpenNext, covering deploy surfaces and stages, read-only cloud diagnostics, mutation barriers, stale-commit guards, a single OpenNext adapter version authority, CDN eventual consistency, post-deploy checks, and stage-scoped preview cleanup. Use only in repositories that deploy to AWS with SST, when changing infrastructure code, deploy or cleanup workflows, or OpenNext packaging. Not for repositories without SST, and not for application code (use nextjs-app).
---

# AWS SST deploy

Opt-in stack skill. It applies only where the repository deploys to AWS with
SST, usually packaging Next.js apps with OpenNext. The repository's own
workflows, stage names, scripts, and release authority take precedence.

Load `secure-by-design` for credentials and least privilege,
`verification-selection` for deployed acceptance,
`repo-contribution-etiquette` for who may trigger what, and
`concurrent-agent-runtimes` for stage and resource naming.

## Know the deploy surfaces

Keep one table in the repository of every deploy and cleanup workflow, its
trigger, and its stage, so no stage is deployed or torn down by a workflow
nobody listed. Production activation follows explicit owner authority. An
environment name on a job does not prove an approval gate exists; inspect the
effective settings read-only and report gaps, and change them only with
separate authorization.

## Cloud access

Routine diagnostics stay inside read access: account identity, stack status
and events, describe and list metadata, and logs. Credentials, IAM, and
deployment environments are the enforced boundary; client-side prompts only
flag.

## Guard every mutation

- Every automatic deploy waits for the required gates of the exact commit
  before any cloud, database, or forge mutation. A cancelled, skipped, or
  failed required gate blocks the deploy.
- Before mutating, assert the commit is still the branch head (or the change's
  head for previews) so a queued stale deploy fails without mutating.

## Deterministic OpenNext adapter

- Install the OpenNext adapter through the repository's dependency manifest
  and lockfile, and run the repository-local binary. Never fetch it live in a
  deploy or preview path through `npx`, `pnpm dlx`, `yarn dlx`, or `bunx`.
- Keep one version authority for the adapter; every other setting that needs
  its version derives from it. No second literal and no environment override.

## SST invariants

- Declare every stack output a workflow consumes. Do not mix patterns from an
  older SST major into the current one.
- Run SST from the repository's pinned dependency; never bake the SST or
  Pulumi CLI into runner images.
- Bundle functions locally; no deploy path pulls a public container image
  unless it is on the repository's approved, mirrored list.

## Eventual consistency

CDN key-value and configuration writes are eventually consistent. Order the
deploy so writes are observable before behavior that depends on them, and
define success as the dependent behavior being observable, not as the API call
returning.

## Cleanup safety

- Select resources by tag key with client-side matching of the exact preview
  stage pattern, never wildcard tag filters, and require extra evidence before
  treating an unusual stage name as a closed preview.
- Scope cleanup to the resources the stage owns; never act on a global
  listing.
- Delete dependents before the roles they are tied to, or teardown deadlocks.

## Proof

Typecheck the infrastructure code, lint the workflows, and search deploy
paths for live OpenNext acquisition. Real deploy proof comes only from a
pushed run in a real preview stage bound to the exact commit; say so in the
handoff instead of claiming it locally.
