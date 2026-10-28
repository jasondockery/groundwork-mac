---
name: multi-step-workflows
description: Implements and proves save-and-advance wizards, steppers, resumable drafts, and create-to-edit handoffs in Next.js App Router applications. Use only in Next.js repositories when a flow's primary action persists data and moves to the next step. Not for repositories without Next.js, and not for single-page form layout (use form-layout).
---

# Multi-step workflows

Opt-in stack skill. It applies only where the repository uses the Next.js App
Router. Domain rules stay in the owning product specification; this skill sets
the lifecycle contract.

Save-and-advance is one user intention that spans persistence, routing,
reload, and focus. Component tests with a mocked router do not prove it. Load
`nextjs-app` for server boundaries, `url-state-navigation` for durable route
state, `form-layout` for fields and errors, and
`accessible-product-development` for focus and dialog behavior.

## Lifecycle contract

1. One primary action completes one intention: persist, then navigate to the
   intended next step. The first save never remounts the flow at step one.
2. The current step lives in validated route or search state whenever reload
   or resume matters. Define Previous, Continue, browser Back, and Forward.
3. User-facing URLs use public identifiers; database keys stay behind server
   and operator boundaries.
4. Draft creation happens at most once. Show a pending state and refuse
   repeated activation while persistence is in flight, and reject duplicates
   in the server handler as defense in depth.
5. A failed save stays on the current step with an actionable recovery
   message. Never advance optimistically past failed persistence.
6. The server validates each step's prerequisites independently of the
   browser.
7. On every step change, move focus to the new step heading and scroll it
   clear of all sticky headers.
8. Discard or cancel uses an accessible confirmation, restores focus to the
   trigger when cancelled, and says where the saved record can be found.
9. New and existing drafts follow the same navigation contract.

## Required proof

A route-level real-browser lifecycle test on the changed flow, selected by the
repository's changed-path gate, proves:

- one Continue creates exactly one draft and lands on the intended step;
- the URL identifies the public record and the current step;
- reload restores the same record, values, selections, and step;
- Previous, Continue, Back, and Forward preserve saved state;
- slow persistence visibly blocks repeated activation and cannot duplicate;
- a failure stays on the current step with recovery guidance;
- focus lands on the new heading, clear of sticky navigation, at desktop and
  mobile widths.

Keep unit tests for parsers, guards, and server validation; they do not
replace the lifecycle test.

## Not done while

The first save remounts step one; the step disappears on reload; double
activation can create two records; focus lands behind sticky UI; discard moves
focus without a managed dialog; or the lifecycle test is optional, skipped, or
not selected by the changed-path gate.
