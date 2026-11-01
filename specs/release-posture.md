# Release Posture

Status: implemented for the browser slice; the general tool catalog and
posture-driven channel families remain open (see Sequence).

Groundwork has one release-channel setting per machine: `release_posture`,
`current` or `preview`. It lives in the chezmoi config Groundwork already owns
and is edited with `groundwork-configure`. There are no environment profiles:
no work-managed profile (removed 2026-10-29, #74) and no environment role or
profile preset (removed in #129). Every machine gets the same setup, and the
settings that are not profiles stay independent: headless, Xcode with its
dependent Xcode beta, game-dev tools, password manager, Git identity, and the
developer preferences in `home/.chezmoitemplates/developer-settings`.

`AI_THESIS.md` → "Release posture" owns the product stance; this specifies how it
becomes configuration.

Implement under `skills/safe-mutating-cli` and
`skills/system-update-orchestration`.

## Problem

`update-all` once had one behavior for every machine and reported it
dishonestly: it printed skipped casks and then said `Groundwork tools
refreshed.` The temptation is to keep adding flags — `--greedy`,
`--include-vendor-casks`, `--beta`. That produces a command whose behavior
nobody can predict and whose receipt nobody can trust. A reverted attempt on
2026-07-20 demonstrated the failure mode: `--require-sha --greedy-auto-updates`
planned to upgrade `google-chrome`. At that time the cask shipped no checksum,
so the audit kept it out of the Brewfile. That exception lane is retired.
Brave is checksummed and Sparkle owns its later updates, so `update-all` does
not brew-upgrade it.

The machine should declare its posture once, and `update-all` should read it.

## Fixed invariants

These are not settings. No release posture may change them.

1. **AI tool freshness.** Groundwork imposes **no intentional delay** on
   supported AI tools: it targets the newest Groundwork-supported release
   available through the configured official channel whenever `update-all`
   runs. There is no "delayed" mode. This is not permission to fight MDM,
   organization policy, an approved-software list, or a read-only package
   manager — see Precedence. A blocked or unverifiable update is reported
   explicitly, and Groundwork never claims the AI toolchain is current when it
   could not verify that.
2. **Integrity.** `--require-sha` and the `audit-brew-casks` exception registry
   apply in every posture. A preview channel is a different product, not a
   relaxed trust policy.
3. **Supply-chain floors.** pnpm 4 days, Renovate 5 days, mise 5 days. These
   address anonymous instant publish into deep transitive trees, not staleness
   preference. Homebrew applications and AI CLIs carry no floor.
4. **Project pins win.** Release posture governs available workstation tools,
   never repository contracts.
5. **No OS enrollment.** Groundwork never enrolls a machine in an OS beta or
   downloads one.

## The setting

```text
release_posture = "current"    # current | preview; seeds defaults, never names a channel
```

- **`current`** — the latest stable release of each application. The default
  for every fresh install, and not a cautious choice (see below).
- **`preview`** — a pre-release channel for families that have one. Expect
  occasional breakage where a preview channel is selected.

Bootstrap never asks. `chezmoi init` writes `current` on a fresh install and
carries a stored valid value forward on every regeneration.
`groundwork-configure` is the only editor: it shows the current value, stages
a change, renders the candidate config in isolation, previews the dotfile diff,
and applies only after confirmation. `groundwork-configure --release-posture
current|preview` opens the same transaction with posture preselected; there is
no second writer. Confirming runs `chezmoi apply`, so the selected desired
state is reconciled immediately. `update-all` owns later upgrades and
maintenance.

Xcode beta is the one dependent choice. It is offered only while Xcode is
enabled; disabling Xcode stages `beta=false` in the same receipt.
`groundwork-doctor --browser` reports the stored posture, Xcode, and Xcode beta
states. A one-time apply notice names the current posture and points to
`groundwork-configure`.

**Current is the shipped default.** Current AI tools on stable foundations is
the configuration that sets an AI-native developer up to succeed, for two
reasons:

1. **The AI layer already supplies the variance.** DORA's 2024 data found
   delivery stability dropping about 7.2% for every 25-point rise in AI
   adoption. A workflow that has taken on that much new variance should not
   also be absorbing pre-release breakage in its editor and operating system.
2. **Agents work better against a documented substrate.** When an agent
   debugs a machine, it reasons from how the tool is documented to behave.
   Preview channels move behavior ahead of its documentation, so the developer
   ends up supervising the agent's confusion instead of the work.

Preview is a first-class, fully supported choice. It is simply not the default,
and it is never a workaround or an integrity bypass.

There is no "production" posture. Groundwork configures development and
automation environments; production belongs to Roost or the app's deployment
system.

### Posture and variant

What a family installs is a **variant**, the concrete product. Posture only
seeds which variant a family defaults to. The two words stay separate so a
later family can map preview to a different variant without renaming posture.

The browser slice supports one family and one managed variant: Brave. Both
postures resolve to the release `brave-browser` cask, so switching posture
does not install, configure, or remove a browser. On a desktop Mac Groundwork
runs `defaultbrowser browser` once, automatically, only when the default is
Safari or unset; macOS asks you to confirm, and organization or device policy
remains authoritative. Chrome is not installed or configured. A copy already on
the machine stays until the owner removes it. A headless machine selects no GUI
browser.

### Retired environment-profile keys

Older configs can still carry `work`, `environment_role`, or `profile_preset`.
They are read once and never written back:

- `home/.chezmoi.toml.tmpl` reads them during regeneration and drops them.
  When no valid `release_posture` is stored, a `profile_preset` ending in
  `-preview` maps to `preview`; anything else maps to `current`. A stored
  posture always wins.
- A work-managed marker (`work=true`, `environment_role=managed`, or
  `profile_preset=work-managed`) writes one comment into the config:
  `Retired work-managed setting ignored; this Mac uses the common setup.`
  `groundwork-configure` prints the same line while a marker is still stored.
- `home/.chezmoitemplates/developer-settings` keeps two pieces of the old
  behavior. When a marker is present and the stored pair is still the old seed
  (personal apps off, infrastructure extensions on), that pair returns to the
  common defaults. When `work=true` is stored and `git_identity` never was,
  regeneration writes `git_identity=work`, so commits keep the work email when
  one is saved. An explicit Git identity always wins. That is commit identity,
  not a profile.
- The presence of a stored `profile_preset` still marks a pre-multiplexer
  install, which keeps tmux instead of the fresh-install Herdr recommendation.

Nothing fails. `groundwork-profile` is a one-line shim: every invocation points
to `groundwork-configure` and changes nothing. `scripts/validate-groundwork`
holds a migration case for each retired key and a grep guard that keeps the
retired names out of everything except the migration readers, history, and
tests.

Organization and device policy still outrank Groundwork on every Mac. That is
the MDM ownership guard used by `groundwork-app-remove`,
`groundwork-app-adopt`, and `update-all`, not a setup profile.

### Precedence

When rules disagree, the higher line wins:

```text
organization / device policy
→ Groundwork integrity policy (checksums, audit registry)
→ selected tool variant
→ repository version pins   (always authoritative for project runtimes)
```

An organization-managed Mac may therefore run behind when device policy blocks
an update. Groundwork reports that block and does not work around it.
Groundwork itself imposes no delay.

### Persistence

Posture is machine-local configuration, not tracked project state. It must be
readable before `chezmoi apply`, atomically written, editable without rerunning
onboarding, parsed by exactly one implementation, and recoverable when corrupt.
The answer lives in the chezmoi config Groundwork already owns; there must not
be one answer in chezmoi and a second copy elsewhere.

## Tool catalog

One canonical record per tool family. Channel variants are **separate products**
with different cask tokens, application bundles, bundle identifiers, and
settings locations — values that cannot be derived from the token.

The canonical catalog is a **machine-readable, schema-validated file**
(`data/tool-channels.yaml` or equivalent). It is not this document. Any table
here is illustrative or generated; an upstream rename must be one canonical data
edit, not a data edit plus a prose edit that silently drifts.

Shape:

```yaml
families:
  brave:
    defaults: { current: release, preview: release }
    variants:
      release:
        cask: brave-browser
        app_bundle: Brave Browser.app
```

`defaults` is how a posture becomes a variant, and why posture and variant stay
separate vocabularies. Brave's current and preview postures both resolve to
the release cask, so the browser does not vary with release posture. Another family
can later map preview to a different variant without touching the posture
vocabulary. Chrome is not a managed variant.

### Three owners, not one

"Vendor-owned" is too coarse. Each variant declares:

```text
install_owner        who installs it        (homebrew | vendor | external)
update_owner         who updates it         (homebrew | vendor | organization)
configuration_owner  who owns its settings  (groundwork | user | vendor-sync)
```

Brave is the current example: Homebrew installs the checksummed cask, Sparkle
owns updates, and Groundwork offers a configuration profile rendered from
groundwork-core. One field cannot say that.

### Each GUI variant eventually needs

```text
bundle_identifier              (prefer over literal /Applications paths)
application discovery strategy
native settings location
coexistence group
installed-version probe
available-version probe
health verification command
platform requirements
```

The universal catalog field is a **native settings location**. Brave's is the
`com.brave.Browser` configuration profile rendered from groundwork-core.
The editor path stays rendered files.

`brave-browser` installs `Brave Browser.app`. The cask is checksummed and
declares `auto_updates: true`, so it lives in the main Brewfile and Sparkle
owns later updates. `Brewfile.browser` records the selection. The cask audit
fails if a desktop profile omits Brave, selects Chrome, or a headless profile
selects a GUI browser. There is no exception registry.

Start with families that actually need a decision. Do not model software with
one channel and no ambiguity.

## Vendor identity is preserved

**Groundwork never renames a preview application, symlinks it into a stable
path, or shadows a vendor command.** Doing so breaks code signing, bundle
identity and LaunchServices registration, the vendor's own updater,
side-by-side installation, and rollback.

Concretely: `Brave Browser.app` is the managed app, and Groundwork does not
rename it. `Google Chrome.app` and `Google Chrome Beta.app` keep the names
Google gave them. Groundwork does not install them, rename them, symlink them,
or delete them. Normalization, if any, happens in
Groundwork's own invocation layer, never in the application bundle.

### Deferred: role-based resolver commands

A `groundwork-editor` / `groundwork-browser` wrapper is a plausible next step
but is **not** in this specification. It adds indirection on the most
critical path a developer has, breaks muscle memory and anything that shells
out to `code`, and introduces a failure point between the user and their
editor. Setting `$EDITOR`/`$VISUAL` to a resolver is the lower-risk half and
can come first if a real need appears. Build the catalog and each family's
native settings location first; add resolvers when something demonstrably
needs them. Brave's native settings location is the configuration profile.
The editor path stays rendered files.

## Settings: overrides that differ from upstream

Groundwork renders the policies in groundwork-core
(`core/browser/brave.json`) and does not keep a second copy. An entry applies
only when its `when` is met. The only understood condition is "Bitwarden is
the password manager." An unknown condition fails closed and writes nothing.
`upstreamDefault`, `reason`, and `when` are not written into the profile.

The rendered file is a user-scoped `.mobileconfig`. Groundwork offers to open
it. System Settings asks the user to approve it. Groundwork does not run
`profiles install`. Every Mac gets the file; organization or device policy
outranks it where one exists.

When the password manager is Bitwarden, the spec includes
`PasswordManagerEnabled=false`. When it is `1password` or `none`, that key is
omitted. The first-run backup still records the old
`com.google.Chrome PasswordManagerEnabled` key so an older backup can restore
it. Groundwork no longer writes `defaults write com.google.Chrome`.

The Bitwarden extension file under Brave's External Extensions directory is
written only after an interactive yes, using the update URL from the spec.
Brave asks before enabling it. A noninteractive run does not write it.

Groundwork does not write account data into the profile. Do not point two
browsers at one policy payload.

An installed Chrome app is not configured and is not uninstalled.
Removing it is manual:

```text
brew uninstall --cask google-chrome
```

An installed Chrome Beta app is the same kind of manual step.

```text
brew uninstall --cask google-chrome@beta
```

That command removes the app cask. It does not delete unrelated personal
files. Do not add `--zap` unless the cask has been inspected and the intent is
to remove preferences and caches too.

Where a future family needs channel-specific values, write them only to that
channel's own native settings location, and only for keys that differ from
upstream. Promotion and demotion stay explicit:

```text
promote a fallback to primary  → preserve its existing user data; show the
                                 preference-domain keys that will be written;
                                 merge or replace only per declared ownership;
                                 require confirmation
demote the former primary      → stop managing that preference domain; keep
                                 its plist and profile data; never delete
```

Distinguish an **installed** copy from a **configured** one from a
**verified** one. An unmanaged install is not a proven rollback environment.
## Switching posture

Switching posture is a mutating operation and follows
`skills/safe-mutating-cli`: show the plan, mutate only on acceptance.

```text
groundwork-configure                              # pick Release posture
groundwork-configure --release-posture preview    # same transaction, preselected
```

A change must never delete the previous channel automatically, overwrite the
other channel's settings, or alter default-application handlers without showing
it. Switching release posture does not install, configure, or remove a browser.

`update-all` gains no posture flags. Its user-facing surface stays:

```text
update-all
update-all --plan
update-all --help
```

`--plan` does not fit today's launcher, which syncs and applies before the
runner is reached. Informational commands must short-circuit above that
trampoline:

```text
PLAN-001  --plan parses and validates before synchronization or apply.
PLAN-002  A plan performs no persistent machine mutation. Metadata and network
          reads may occur; any unavoidable cache effect is documented.
PLAN-003  --help, invalid arguments, and an invalid posture invoke no git,
          chezmoi, brew, mise, installer, or application-start command.
PLAN-004  --plan does not write the last-update-all timestamp, so it never
          suppresses the stale-refresh reminder.
```

## Update ownership

**Decision: `update-all` updates every eligible installation in each supported
machine-level package-manager inventory, and reports everything it cannot
safely or conclusively update.**

The Homebrew lane inventories installed formulae, casks, and pins before
refreshing metadata. On macOS it binds every cask decision to one matching
`brew info --json=v2` snapshot. Ordinary checksummed casks use an exact normal
lane; checksummed self-updating and safely verifiable latest-version casks use
separate exact-token greedy-aware lanes driven by matching outdated queries.
Bare global `--greedy` remains prohibited. Pinned, deprecated, disabled,
unresolved no-checksum, privileged-replacement, and unknown items remain
unchanged with an explicit reason. Only tokens in Groundwork's reviewed
`vendor-updater-casks.txt` policy remain visible as accepted no-checksum vendor
coverage rather than false failure. Current privileged casks stay quiet;
cask mutation matches Homebrew's own default and may quit a running app that
declares a safe quit action, unless the invocation explicitly uses
`--no-app-quit`, which defers running applications per token and carries
Homebrew's `--no-quit` guard instead. Mac App Store updates use exact discovered IDs. A real
interactive terminal establishes macOS authorization before each mutation; the
exact non-prompting mutation then owns one process group and a conservative
30-minute hard backstop. Redirected or automated runs mark each exact app
action-required without mutation. Receipts distinguish attempted, verified,
remaining, timed-out, failed, action-required, and unexplained outcomes. Known manual
applications use explicit mappings for diagnosis and optional, separately
consented identical-artifact adoption. A manual or MDM-ambiguous app cannot
suppress unrelated safe lanes and remains a review outcome; it is not an
updater failure. Inventory, classification, mutation, and verification failures
remain nonzero while independent safe updater lanes continue.
Chezmoi's Brewfile hook remains install-only for existing packages and accepts
only an exact temporary omission when a conflicting selected manual app exists.
Repository package manifests and lockfiles remain outside machine maintenance.
After a successful transaction releases the update lock, an interactive
post-update action center may invoke the separately locked adoption and removal
helpers only after literal default-no consent. A noninteractive run prints the
safe commands and performs no ownership or removal action.

## Execution model

```text
read persisted release posture
→ inventory each supported package manager and known selected manual app
→ query installed, available, pinned, and updater-ownership state
→ classify every candidate
→ show the plan when --plan
→ update
→ retry only the same approved candidate set
→ verify essential tool behavior
→ print an evidence-based receipt
```

Receipt categories, per `skills/system-update-orchestration`:

```text
Updated
Already current
Externally managed and verified
Blocked by policy or environment
Attempted but still outdated
Status could not be verified
```

A blocked AI-tool update is reported, never silently absorbed:

```text
Claude Code
  Installed:         2.1.215
  Latest supported:  2.1.218
  Blocked by organization policy.

Groundwork does not claim the AI toolchain is fully current.
```

Exit behavior: a Groundwork-owned update failure is nonzero; invalid arguments
or an invalid posture fail before mutation; an external updater being required
is visible and does not claim fully current; unverifiable status makes the
receipt explicitly incomplete; a device-policy block is reported, never
bypassed.
## Structural guardrails

Enforced by `scripts/validate-groundwork`:

1. Every selected channel resolves to a catalog entry.
2. **At most one** primary variant per logical role. Roles declare whether zero
   is allowed — a headless container has no GUI browser. Device policy, not a
   Groundwork role, decides whether an organization-supplied editor stays.
   Secondary and fallback variants are
   permitted only where the catalog proves coexistence.
3. Conflicting casks cannot be selected together unless coexistence is proven.
4. Every rendered path belongs to the selected variant.
5. Executable templates, scripts, rendered configuration, and application logic
   derive every channel-specific token, bundle identity, command, and path from
   the catalog. Documentation and fixtures may carry examples only through an
   explicit checked exception or generated output. (This document is such an
   exception; its earlier draft asserted the broad rule and then violated it.)
6. Update and retry use the same exact selected token.
7. A posture change is idempotent.
8. Stable fallback is preserved when the catalog says coexistence is supported.
   Brave does not declare a fallback. Every desktop posture selects Brave only.
9. An upstream token or bundle rename requires one canonical production-data
   edit. Fixtures, a migration alias, and release notes may also change;
   consumers must derive the value rather than duplicate it in logic.
## Sequence

1. **Done** — guardrail skills committed (`81bb40b`).
2. **Done** — thesis stance and the first version of this specification
   (`bc2ac88`).
3. **Done** — posture storage and rendering, owned by `groundwork-configure`.
4. **Done** — browser slice: Brave on every desktop Mac posture, checksummed
   Brewfile install, policy profile rendered from groundwork-core, and
   preserved legacy `install_chrome` input. The Chrome exception lane is
   retired.
5. **Done** — environment profiles removed: work-managed (#74), then
   environment role, profile preset, and the `groundwork-profile` command
   (#129). One `release_posture` setting remains.
6. Machine-readable catalog for other families; test that channels never
   replace one another.
7. Rebuild `update-all` on explicit candidates with `--plan` and an honest
   receipt. Bare global greedy remains forbidden; exact greedy-aware lanes may
   mutate only preclassified installed tokens. Manual/MDM apps remain unchanged.
8. `groundwork-doctor` checks: posture vs installed channels, AI freshness,
   vendor-updater status, policy blocks, and unmanaged software. Groundwork
   never enrolls a machine in an OS beta.

Hostile fixtures land with each phase, not after. Red-prove every branch.
