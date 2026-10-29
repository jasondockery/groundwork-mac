# Environment Profiles and Release Posture

Status: partially implemented (2026-08-09, local review tranche). Shipped on
`origin/main`:
- profile/posture schema and storage, and the `groundwork-profile` reporting
  command (`f46e3a7`);
- selective editing of the `profile_preset` seed via `groundwork-configure`
  (`937ae11`);
- the browser vertical slice: every desktop Mac posture (current, preview,
  and Xcode) installs Google Chrome stable; headless profiles
  select no GUI browser. Chrome Beta is not selected. An existing Chrome Beta
  install is left in place; removal is manual. The official stable cask is
  rendered into `Brewfile.browser` and installed only after the checksummed
  Brewfile succeeds.
This local tranche makes `groundwork-configure` the first-class editor for
independent `environment_role` and `release_posture` values plus dependent Xcode
`beta`, removes those mutable preferences from bootstrap, treats
`profile_preset` as compatibility/history rather than a live master switch, and
makes `groundwork-profile set` delegate to the same guarded transaction. Xcode
beta is hidden while Xcode is off, and the final transaction reconciles its
dependent change without overriding an explicit user choice. Open:
- the remaining posture-driven application families and machine-readable
  general tool catalog. Browser selection is live;
  broader channel migration and explicit-candidate `update-all` remain open.

`AI_THESIS.md` → "Release posture" owns the product stance; this specifies how it
becomes configuration.

Implement under `skills/safe-mutating-cli` and
`skills/system-update-orchestration`.

## Problem

`update-all` today has one behavior for every machine and reports it
dishonestly: it prints skipped casks and then says `Groundwork tools
refreshed.` The browser slice installs Google Chrome stable on every desktop
Mac. Release posture no longer selects a browser channel. Editor and other
application families still need the same model where a real preview channel
exists.

The temptation is to keep adding flags — `--greedy`, `--include-vendor-casks`,
`--beta`. That produces a command whose behavior nobody can predict and whose
receipt nobody can trust. A reverted attempt on 2026-07-20 demonstrated the
failure mode: `--require-sha --greedy-auto-updates` planned to upgrade
`google-chrome`, one of the official Chrome casks that
`scripts/audit-brew-casks` deliberately keeps in the bounded exception lane.

The environment should declare its posture once, and `update-all` should read
it.

## Fixed invariants

These are not profile fields. No preset may change them.

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
5. **No OS enrollment.** Groundwork records and diagnoses the system channel;
   it never enrolls a machine in an OS beta or downloads one.

## Dimensions

Presets choose starting values. What is **persisted is the concrete choice**,
not the abstract posture, because future families may expose several concrete
preview variants. The browser slice supports one family and one managed
variant: Chrome stable. Release posture does not change it.

```yaml
schema_version: 1

environment:
  role: personal              # personal | disposable
  release_posture: preview    # current | preview; seeds defaults, does not name a channel

tools:
  primary_browser:
    family: chrome
    variant: stable           # current and preview both persist stable

system:
  declared_channel: developer-beta   # INTENT
  management: user-controlled        # user-controlled | organization-managed
```

Two vocabularies, deliberately separate:

- **Posture** — `current` or `preview`. An attitude that seeds defaults.
- **Variant** — the concrete product a family installs. Chrome persists
  `stable` for both postures.

The two words stay separate so a later family can map its preview posture to
a different variant without renaming posture. That split does not select
another Chrome channel. Posture seeds the catalog default, and Chrome's
default is stable on every desktop Mac.

`system.declared_channel` records **intent**. Detected OS state is a separate
observation made by `groundwork-doctor`, never stored as if Groundwork set it —
Groundwork does not control Software Update enrollment and must not imply it
does.

### Roles

| Role | Environment |
| ---- | ----------- |
| `personal` | The common setup for every Mac, including a machine an organization manages |
| `disposable` | Rebuildable container or VM; aggressive variants are cheap |

There is no `managed` role and no Work Managed profile. A stored
`environment_role` of `managed`, a stored `profile_preset` of `work-managed`,
or a stored `work=true` flag is ignored. Regeneration rewrites the retired role
to `personal` and the retired preset to `personal-current`, and keeps an independent
`release_posture`. Regeneration writes one comment into the config:
`Retired work-managed setting ignored; this Mac uses the common setup.`
`groundwork-profile show` and `groundwork-configure` print that same line while
a retired role or preset is still stored. Nothing fails. Organization and device policy
still outrank Groundwork on any Mac. That is the MDM ownership guard used by
`groundwork-app-remove`, `groundwork-app-adopt`, and `update-all`, not a
setup profile.

`disposable` is in the v1 schema because the thesis already names containers as
a target and the owner has stated the requirement. Modelling the role is cheap;
building the full container experience is not, and that can follow.

`ci` is deferred until Groundwork actually owns a CI installation path.

Role and posture are independently editable through `groundwork-configure`;
the stored preset below is only the historical bootstrap seed. Confirming that
transaction runs `chezmoi apply`, so the selected desired state is reconciled
immediately. `update-all` owns later upgrades and maintenance. The managed
browser stays Google Chrome stable either way.

### Independent developer preferences

`home/.chezmoitemplates/developer-settings` is the compatibility resolver for
`docker_backend` (`colima`, `docker-desktop`, `none`), `git_identity` (`personal`,
`work`), `personal_apps`, and `work_extensions`. The shared developer tools and
AI CLIs are installed for every Mac. macOS defaults to Colima plus Docker CLI,
including headless Macs. Device policy still takes precedence.

`groundwork-configure` edits these preferences independently. Explicit stored
values win. The retired `work` flag does not choose Git identity, personal
apps, or infrastructure extensions. When a retired marker is present
(`work=true`, `environment_role=managed`, or `profile_preset=work-managed`)
and the stored pair is still the old seed (personal apps off, infrastructure
extensions on), that pair is rewritten to the common defaults: personal apps
on, infrastructure extensions off. Any other stored pair is kept. A stored
Git identity is kept. A fresh setup has no work/personal install question.
Docker Desktop removal and data migration are explicit owner operations:
[the single migration guide](../docs/docker-desktop-to-colima.md).

### Stored preset seeds

| Preset | role | posture | |
| ------ | ---- | ------- | --- |
| **Personal Current** | personal | current | **the common Mac setup** |
| **Personal Preview** | personal | preview | |
| **Disposable Experimental** | disposable | preview | |

**Personal Current is the shipped default, and that is not a cautious choice.**
Current AI tools on stable foundations is the configuration that sets an
AI-native developer up to succeed, for two reasons:

1. **The AI layer already supplies the variance.** DORA's 2024 data found
   delivery stability dropping about 7.2% for every 25-point rise in AI
   adoption. A workflow that has taken on that much new variance should not
   also be absorbing pre-release breakage in its editor and operating system.
   The managed browser stays Chrome stable in every posture.
2. **Agents work better against a documented substrate.** When an agent
   debugs a machine, it reasons from how the tool is documented to behave.
   Preview channels move behavior ahead of its documentation, so the developer
   ends up supervising the agent's confusion instead of the work.

The scarce resource for an AI-native developer is attention. Every preview-
channel breakage spends attention that should have gone to directing agents.
Preview is a first-class, fully supported choice — it is simply not the default,
and it is never a workaround or an integrity bypass.

The settings editor confirms **concrete products**, not an abstract switch. On
a desktop Mac the managed browser is Google Chrome stable for every release
posture. Groundwork never changes the operating system's default-browser
association, and organization or device policy remains authoritative. Chrome
Beta is not installed or configured. A copy already on the machine stays until
the owner removes it.

There is no "production" profile. Groundwork configures development and
automation environments; production belongs to Roost or the app's deployment
system.

### Precedence

When rules disagree, the higher line wins:

```text
organization / device policy
→ Groundwork integrity policy (checksums, audit registry)
→ selected tool variant
→ repository version pins   (always authoritative for project runtimes)
```

An organization-managed Mac may therefore run behind when device policy blocks
an update. Groundwork reports that block and does not work around it. Groundwork
itself imposes no delay and no separate work setup.

### Persistence

The profile is machine-local configuration, not tracked project state. It must
be: readable before `chezmoi apply`, schema-versioned, atomically written,
editable without rerunning onboarding, parsed by exactly one implementation, and
recoverable when corrupt. Answers live in the chezmoi config Groundwork already
owns — there must not be one answer in chezmoi and a second copy elsewhere.

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
  chrome:
    defaults: { current: stable, preview: stable }
    variants:
      stable:
        cask: google-chrome
        app_bundle: Google Chrome.app
```

`defaults` is how a posture becomes a variant, and why posture and variant stay
separate vocabularies. Chrome's current and preview postures both resolve to
stable, so the browser no longer varies with release posture. Another family
can later map preview to a different variant without touching the profile
vocabulary. Chrome Beta is not a managed variant.

### Three owners, not one

"Vendor-owned" is too coarse. Each variant declares:

```text
install_owner        who installs it        (homebrew | vendor | external)
update_owner         who updates it         (homebrew | vendor | organization)
configuration_owner  who owns its settings  (groundwork | user | vendor-sync)
```

Chrome is exactly why: Groundwork may facilitate installation, Google owns
updates, and Groundwork may own a small set of configuration defaults. One field
cannot say that.

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

The universal catalog field is a **native settings location**. Chrome's is its
preference domain. The editor path stays rendered files.

Values verified 2026-08-04 through Homebrew cask metadata for the one managed
variant: `google-chrome` installs `Google Chrome.app`. It declares
`sha256 :no_check` and `auto_updates: true`, so the checksummed main Brewfile
excludes it. `Brewfile.browser` records that one exception on every desktop
Mac, and the cask audit fails if its integrity or update-owner assumptions
change. Chrome Beta is not in the exception registry.

Start with families that actually need a decision. Do not model software with
one channel and no ambiguity.

## Vendor identity is preserved

**Groundwork never renames a preview application, symlinks it into a stable
path, or shadows a vendor command.** Doing so breaks code signing, bundle
identity and LaunchServices registration, the vendor's own updater,
side-by-side installation, and rollback.

Concretely: `Google Chrome.app` always means Stable and
`Google Chrome Beta.app` always means Beta, exactly as Google intends.
Groundwork installs only `Google Chrome.app`. It never renames Beta, symlinks
it into the Stable path, or deletes it. Normalization, if any, happens in
Groundwork's own invocation layer, never in the application bundle.

### Deferred: role-based resolver commands

A `groundwork-editor` / `groundwork-browser` wrapper is a plausible next step
but is **not** in this specification. It adds indirection on the most
critical path a developer has, breaks muscle memory and anything that shells
out to `code`, and introduces a failure point between the user and their
editor. Setting `$EDITOR`/`$VISUAL` to a resolver is the lower-risk half and
can come first if a real need appears. Build the catalog and each family's
native settings location first; add resolvers when something demonstrably
needs them. Chrome's native settings location is its preference domain. The
editor path stays rendered files.

## Settings: overrides that differ from upstream

Groundwork writes a Chrome preference only when it differs from Chrome's
upstream default, and each write names its reason. No other Chrome preference
is written.

Chrome turns its built-in password manager on. When setup chose Bitwarden or
1Password, Groundwork turns that one key off so the built-in manager does not
compete with the chosen manager:

```text
defaults write com.google.Chrome PasswordManagerEnabled -bool false
```

| Setting | Upstream | Groundwork | Reason |
| --- | --- | --- | --- |
| `PasswordManagerEnabled` | `true` | `false` on `com.google.Chrome` when a third-party manager is configured | The built-in manager would compete with Bitwarden or 1Password |

The domain is Stable's `com.google.Chrome`. The Beta domain is not written.
When the password manager is `none`, the write is skipped. The first-run
backup still records the Stable key on a desktop Mac so a later choice can be
restored.

Groundwork never writes into a browser's profile data directories under
`~/Library/Application Support`; the browser owns those. Do not point two
channels at one domain. Policies, schemas, and migrations differ between them.

An installed Chrome Beta app is not configured and is not uninstalled.
Removing it is manual:

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

## Profile changes are planned migrations

Switching posture is a mutating operation and follows
`skills/safe-mutating-cli`: show the plan, mutate only on acceptance.

```text
groundwork-profile show
groundwork-profile set preview               # guarded preview, then confirm
groundwork-profile edit
```

A change must never delete the previous channel automatically, overwrite the
other channel's settings, or alter default-application handlers without showing
it. Switching release posture does not install, configure, or remove a browser.
Chrome stable stays the managed browser. A Chrome Beta cask that is already
installed stays installed, with its preferences and profile data left alone,
until the owner runs the manual removal command above.

`update-all` gains no new posture flags. Its user-facing surface stays:

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
PLAN-003  --help, invalid arguments, and an invalid profile invoke no git,
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
read persisted profile
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
or an invalid profile fail before mutation; an external updater being required
is visible and does not claim fully current; unverifiable status makes the
receipt explicitly incomplete; a device-policy block is reported, never
bypassed.

## Migration for existing installations

Never guess a profile silently. Detect installed channels, recommend the closest
preset, show resulting changes, let the user accept or edit, then persist.

Migration preserves installed applications and their settings. The Homebrew
upgrade scope now follows the rendered Groundwork Brewfile without a prompt:
that narrows mutation to declared software and leaves independently installed
applications and their data alone. A posture change does not add or remove a
browser. Chrome stable stays selected on every desktop Mac, and an existing
Chrome Beta cask and its profile data stay until the owner runs
`brew uninstall --cask google-chrome@beta`.

```text
interactive, unmigrated     → show the recommended profile and plan; require a
                              selection before the next MUTATING update
noninteractive, unmigrated  → fail before mutation, naming the exact command
                              that selects a profile
compatibility escape hatch  → owner-approved, visibly deprecated, with a bounded
                              removal date
```

Read-only commands (`--plan`, `--help`, `groundwork-profile show`) keep working
unmigrated.

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
7. A profile change is idempotent.
8. Stable fallback is preserved when the catalog says coexistence is supported.
   Chrome does not declare a fallback. Every desktop posture selects stable only.
9. An upstream token or bundle rename requires one canonical production-data
   edit. Fixtures, a migration alias, and release notes may also change;
   consumers must derive the value rather than duplicate it in logic.

## Sequence

1. **Done** — guardrail skills committed (`81bb40b`).
2. **Done** — thesis stance + this specification (`bc2ac88`).
3. **Done** — profile schema and persistence for role, posture, and system
   intent, with storage, argument safety, and rendering proven, plus the
   `groundwork-profile` reporting command (`f46e3a7`); the numbered-menu
   interview writes the fields (`4bb48df`). No channel depends on it yet.
4. **Browser slice done** — Google Chrome stable on every desktop Mac posture,
   rendered browser manifest, bounded exception installer, and preserved legacy
   `install_chrome` input. Chrome Beta is not selected and is not uninstalled
   when already present. A general machine-readable catalog for other families
   remains; test that channels never replace one another.
5. Migration and profile-changing commands, built on catalog-backed plans —
   migration needs the catalog to map observed casks to known variants.
6. Rebuild `update-all` on explicit candidates with `--plan` and an honest
   receipt. Bare global greedy remains forbidden; exact greedy-aware lanes may
   mutate only preclassified installed tokens. Manual/MDM apps remain unchanged.
7. `groundwork-doctor` checks: profile vs installed channels, AI freshness,
   vendor-updater status, policy blocks, unmanaged software, system channel vs
   declared intent.

Hostile fixtures land with each phase, not after. Red-prove every branch.
