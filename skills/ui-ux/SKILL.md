---
name: ui-ux
description: Shapes interface structure and interaction for React web applications that keep reusable components in a shared UI package, covering component ownership, action hierarchy, page headers, navigation ownership, lists and row actions, search and filter toolbars, detail pages, status badges, semantic tokens, and data exports. Use only in React web repositories when changing pages, shared components, design tokens, or list, detail, and toolbar layouts. Not for repositories without a React web UI, not for accessibility requirements (use accessible-product-development), and not for user-facing wording (use inclusive-content-design).
---

# UI and UX

Opt-in stack skill. It applies only where the repository builds a React web UI
with a shared component package. The repository's own components, tokens,
visual system, and tests take precedence; this skill supplies structure and
interaction defaults, not a palette or aesthetic.

Make the user's next action obvious on desktop and mobile. Load
`accessible-product-development` for semantics, keyboard, focus, contrast,
target size, and stable interaction geometry; this skill does not restate
them. Load `inclusive-content-design` for labels and messages,
`form-layout` for forms, `url-state-navigation` for list and filter state,
and `privacy-by-design` for exports that carry personal data.

## Thin apps, shared components

Apps own routing, page composition, and data wiring. A component belongs in
the shared UI package when two apps would want it, when it implements a
standard pattern (button, dialog, combobox, popover), when it wraps a headless
or primitive library, or when it is sensitive enough to need central review.
Apps consume curated exports from that package instead of installing
primitive, overlay, chart, toast, or theme libraries directly. Never
hand-roll overlays.

When the shared component cannot express what a page needs, extend the
component; never restyle one page.

## Action hierarchy

- Verbs: "New thing" creates a record; "Add thing" attaches something to a
  parent or list. Use one verb per kind of action within an app. A create
  form is titled "New thing" and submits with "Create thing".
- A list or management page is a task page: at most one primary action,
  usually create or add. A launch or overview page has no primary action;
  peer tasks have equal weight. Error-page Retry is secondary.
- Shared buttons and state components default to primary, so set an explicit
  non-primary variant on every other action, and test the visible primary
  count.
- The sidebar is navigation only. Menus group secondary choices and never
  hide the primary action.

## Page structure

- One shared page-layout component owns the page header and the route's only
  `h1`; pages do not hand-build a header or add a second `h1`.
- Route shells own the `main` landmark; reusable content components never
  render it. Site banner, primary navigation, and footer stay outside `main`.
- A central navigation resolver owns active top navigation, secondary
  navigation, sidebar selection, and breadcrumbs. Never patch those states
  inside a page. Each destination has one navigation home; detail routes keep
  the navigation family of the list that owns them.
- Breadcrumbs use sentence case. Notification badges appear only on the
  global affordance, the owning area and section, and the actionable item.

## Lists and row actions

- Dense data uses one shared list or table component that adapts to narrow
  layouts; pages do not build their own row or card markup.
- Each row has exactly one native detail link, on its human-readable
  identity. No whole-row click handlers and no "View" buttons.
- Row actions are never primary, and a row action that navigates is a link.
  Load `accessible-product-development` for their names, live results, and
  table semantics.
- Details open on a dedicated page in the same tab so Back restores the list.
- A capped or unavailable result total says so in words instead of failing the
  page. Pagination never depends on an exact count; use one only when it is
  cheap and bounded.

## Search and filter toolbars

- Use the shared URL-driven list shell and its facet component. Do not build
  app-local search buttons, clear buttons, debounce state, or a second facet
  family.
- Search and filtering follow the server-side list rules in `nextjs-app`
  where that skill applies.
- Do not add quick-filter buttons that duplicate a dropdown's state.
- Controls in one toolbar come from the shared control set, so they share one
  height and chrome. Clear is neutral, never destructive styling.

## Detail and edit pages

- Detail pages are read-only first. Never display data in disabled form
  fields.
- Complex entities use full-page create and edit routes. Drawers and dialogs
  are for small quick edits that say what they edit and return to context.

## Status, badges, and tokens

- One primary status badge per row or card, first; context chips stay quiet
  and never repeat the same value elsewhere on the item. Action chips are
  controls, not status.
- Danger color is reserved for errors, destructive actions, failed
  validation, and blockers. Ordinary attention states use quieter variants.
  Health pages stay calm unless something actually failed.
- Use semantic tokens, not raw palette classes, in new or edited code. Each
  surface family (page, card, control, shell, overlay, code) owns its tokens;
  never borrow the closest-looking token from another family. Raw palette
  values appear only in a named categorical map; a map whose keys are really
  statuses uses status tokens.
- Do not churn unrelated old UI to satisfy these rules; sweep only when the
  owner authorizes it.

## Data exports

- Offer an export only for a real audit, follow-up, handoff, troubleshooting,
  or automation need. "All data" means every authorized row matching the
  current filters, not the visible page.
- Sensitive exports are private, uncached responses authorized on the server,
  with filenames that contain no personal data, and an audit entry recording
  actor, scope, row count, and purpose, not row contents.

## Proof

Shared list, filter, and interactive components need real-browser component
tests for keyboard reach, sort, pagination, clear, menus, and focus after
interaction. Use route-level browser tests when behavior depends on routing,
authentication, or server data. Select the rest with `verification-selection`.
