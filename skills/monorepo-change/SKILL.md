---
name: monorepo-change
description: Changes pnpm workspace and Turborepo monorepos safely, covering dependency placement, package exports, version pinning, major upgrades, Turbo task inputs, outputs, and dependencies, affected-only runs, TypeScript project references, and Docker BuildKit images. Use only in pnpm or Turborepo repositories when changing package manifests, the lockfile, workspace or turbo config, tsconfig files, package exports, or Dockerfiles. Not for repositories without pnpm workspaces or Turborepo, and not for deciding whether to adopt a dependency at all (use dependency-change).
---

# Monorepo change

Opt-in stack skill. It applies only where the repository is a pnpm workspace,
usually orchestrated by Turborepo. The repository's own scripts, version
authorities, guards, and cache limits take precedence.

Load `dependency-change` for whether and how to adopt, upgrade, or remove a
dependency, `developer-tool-change` for toolchain changes,
`verification-selection` for proof, and `secure-by-design` for secrets in
builds.

## Place dependencies with their owner

| Used by | Lives in |
|---|---|
| One app | that app's manifest |
| Consumers of a shared package | the shared package, exposed through its exports |
| One tool | that tool's manifest |
| Root scripts only | the root manifest |

Adding a dependency to the root because it is easier is wrong. Adding a UI
primitive library to an app means the work belongs in the shared UI package.

## Package boundaries

- Import only a package's public entry points. Never import its `src` or
  build output paths. Add new entry points to the package's `exports`; avoid
  wildcard exports.
- List every consumer-facing entry point, and use conditional exports when
  shipping more than one module format. After changing `exports`, typecheck
  and test the consumers.
- A foundational package such as shared environment configuration does not
  depend on sibling workspace packages; the dependency belongs in the consumer.
- Adding a workspace package is a structural change; get the owner's approval.

## Versions

- Pin direct dependencies that affect build or runtime to exact versions.
  Keep shared versions in the workspace catalog and reference them from each
  package.
- The runtime and package-manager versions come from their single version
  files. Do not copy the current version into docs, tests, Docker files, or
  workflow logic; derive it, or use obviously fake fixture versions.
- No floating `latest` in CI gates. Every override records a reason, an
  owner, and a removal condition.
- Prove a dependency is unused with `pnpm why` and a search of scripts and
  config before removing it; text search alone is not enough.
- For a major upgrade, choose the newest stable major that satisfies the
  repository's minimum release age and support policy, check engines and peer
  dependencies, update every manifest and catalog entry together, and treat
  TypeScript, lint, framework, deploy tooling, and package-manager upgrades as
  high risk. Record the reason for choosing an older major in the change.

## Turborepo tasks

- Read the documentation that matches the installed Turborepo version before
  changing `turbo.json` or flags. If the installed version offers generated
  agent guidance, keep it off when the repository already routes agent
  instructions.
- Every script Turbo runs appears in the pipeline with declared outputs;
  missing outputs make cache hits restore empty directories. Narrow inputs
  when the default is too broad.
- A test that executes code from workspace dependencies must depend on those
  dependencies' source, or its hash ignores dependency changes and replays a
  stale pass.
- Declare package-specific inputs in that package's own Turbo config; a root
  override for one package replaces the generic task definition.
- After changing `turbo.json`, run a dry run.
- Affected-only CI runs need Git history back to the comparison base.
  Do not add an unconditional full build inside an affected-only lane.

## TypeScript project references

Each referenced project is composite, references point at directories, and the
root config references every buildable package. Verify with a dry
`tsc --build`.

## Docker and BuildKit

- Local Docker lifecycle goes through repository wrappers, never ad-hoc
  Compose in package scripts. Cleanup removes only objects the repository
  proves it owns; never run a global prune, and never delete shared developer
  data volumes without explicit authorization.
- Read every Dockerfile and `.dockerignore`, not only the failing one.
- Copy manifests and the lockfile before source, install with a frozen
  lockfile and a locked BuildKit cache mount on the package store, then copy
  source.
- Pin base images intentionally. CI builds pull fresh bases; local pulls are
  opt-in. Put volatile labels at the end of the final stage.
- Pass secrets through BuildKit secret mounts, never build args or copied
  files. Untrusted forks never authenticate to a cache registry.
- Do not build container images for ordinary source, docs, or test changes.

## Proof

Run the repository's install, focused checks, and changed-package tests. Add a
Turbo dry run when `turbo.json` changed, a dry `tsc --build` when references
changed, and the repository's Docker checks when Docker files changed.
