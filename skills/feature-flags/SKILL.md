---
name: feature-flags
description: Governs runtime feature flags and operational controls from the product decision through classification, a reviewed registry, safe defaults, lifecycle proof, and removal. Use when adding, changing, flipping, or removing a feature flag, kill switch, maintenance or read-only mode, worker or writer control, an *_ENABLED or *_DISABLED setting, or a condition that hides a route behind a flag. Not for authorization or entitlements (use secure-by-design), and not for optional capability selection at build or install time.
---

# Feature flags

A runtime flag is a product decision with an owner and an end date, not a
convenience. Load `secure-by-design` for authorization and
`testing-strategy` for proof layers. Compass doctrine already separates
capability selection from feature flags; this skill covers runtime controls
only.

## 1. Start with the decision

- Do not add a flag or runtime control unless the owner or the owning issue
  explicitly asks for one. A partial flag that already exists is not a
  reason to expand or repair it; if the reason is unclear, stop and ask
  whether the control should exist.
- Record before implementation: purpose, product owner, technical owner,
  safe default, outage behavior, behavior per environment, consumers,
  activation proof, rollback proof, and a review date. The removal condition
  names when the need ends, such as cutover completion or retirement of a
  legacy system. It does not replace the authorization above.

## 2. Classify the value

| Class | Correct owner | Treatment |
| --- | --- | --- |
| Temporary release flag | Flag registry and value store | Short-lived; safe default, owner, remove-by date, removal condition |
| Operational control | Typed mode or dedicated state machine | Modes such as open or read-only, legal transitions, outage behavior |
| Experiment | Experiment system | Targeting, exposure telemetry, success metric, expiry |
| Permission or entitlement | Authorization policy | Never a flag |
| Deployment or cutover coordination | Release procedure or state machine | Never independent booleans in place of sequencing or single-writer ownership |
| Ordinary configuration | Typed configuration | Never turned into an enabled boolean |

Safety-critical ownership transitions use a dedicated, strongly consistent
state machine. A flag never replaces authorization, durable workflow state,
secrets, or single-writer fencing.

## 3. One reviewed registry

- Flag definitions live in one code-reviewed registry; runtime values live in
  one value store. The value store may change only values for an approved
  definition. Never create local copies or environment-variable aliases the
  registry does not own.
- Keys follow the repository's naming grammar, scoped to the owning domain.
- Each definition carries owners, change risk, lifecycle, safe default,
  outage policy, allowed environments, and review or removal date.
- Generate derived registries through the repository's command; never
  hand-edit them.
- Unavoidable bootstrap or emergency-stop environment keys go on a narrow,
  governed allowlist with the same metadata, and never become a second flag
  platform.
- Flipping a value is an audited write whose confirmation scales with
  environment and risk.

## 4. Implement one governed contract

- Enforce authorization and domain prerequisites independently of the flag.
- Keep navigation and direct routes consistent: a visible link never leads to
  a flag-disabled dead end.
- Distinguish disabled from unavailable, and stale from current, in
  diagnostics.
- Evaluate through the shared evaluation path; never query the value store ad
  hoc.
- A newly introduced flag defaults to off, or to the safest mode, until
  activation is proven.

## 5. Prove the lifecycle

- Test default, enabled, disabled, unavailable, stale, and recovery behavior,
  and authorization with the control in every state.
- Test every environment mapping and prove production cannot inherit a
  preview or development value.
- Test activation and rollback.
- Deployed certification fails on missing URL, credentials, configuration,
  zero executed tests, or skipped tests.

## 6. Remove on schedule

When the removal condition is met, remove the flag, its definition, value,
dead branches, and tests in one change. An expired flag past its review date
is a defect, not a setting.
