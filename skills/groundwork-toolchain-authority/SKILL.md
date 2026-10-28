---
name: groundwork-toolchain-authority
description: Applies Groundwork's Node and pnpm authority files, sync and check commands, and machine boundary on top of the shared toolchain-authority base. Use before changing .node-version, .nvmrc, repository mise.toml, package.json packageManager or engines, Corepack setup, Node setup in CI, Renovate toolchain behavior, toolchain docs, or tests containing Node or pnpm versions in Groundwork. Not for the shared one-authority doctrine (load toolchain-authority first) and not for ordinary library dependency updates (use dependency-change).
---

# Groundwork toolchain authority

Load the shared `toolchain-authority` first; it owns the one-authority doctrine,
mirror classification, and the missing-evidence rule. Load `dependency-change`
for the general update procedure. This Groundwork-local extension adds only the
authority files, commands, and machine boundary below and never redefines the
shared base.

## Preserve the two authorities

- Change Node only in `.node-version`.
- Change pnpm only in `package.json#packageManager`.
- Treat `.nvmrc`, `mise.toml#tools.node`, `engines`, and CI as derived adapters.
- Never declare pnpm in mise, Homebrew, or another installer. Mise owns Node;
  Corepack selects pnpm.
- Never add another authoritative version file.

Run `pnpm toolchain:sync` after changing an authority. Run
`pnpm check:toolchain` before handoff. Never repair a mirror directly.

## Keep the machine boundary

Groundwork installs and selects Node with mise, enables and diagnoses Corepack,
detects competing pnpm owners, and explains repository drift. `update-all`
never chooses or rewrites another repository's Node or pnpm authorities.

## Check for drift

Use `pnpm check:outdated` for Lockfile Wanted, Compatible Latest,
maturity-filtered Latest, registry Newest, the declared specification, and the
explicit toolchain authorities. Any command, timeout, signal, network, or JSON
failure is a failed report; never convert missing evidence into "current."

Register a new version-bearing surface under the shared classification before
adding it. Current-contract tests read the authorities; parser and failure
fixtures use named values unrelated to former production pins.

## Done when

- The change touched only `.node-version` or `package.json#packageManager`
  as an authority, and every mirror came from `pnpm toolchain:sync`.
- `pnpm check:toolchain` passes.
- pnpm is declared nowhere in mise or Homebrew, and no other repository's pins changed.
