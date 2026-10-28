---
name: form-layout
description: Lays out and validates forms in React web applications built on a shared form-control package, covering sections, field width, visible labels, required markers, error summaries, autofill, collection inputs, toggles, select choice, and native controls in dark mode. Use only in React web repositories when creating or changing a form, form section, or shared form control. Not for repositories without a React web UI, not for save-and-advance wizards (use multi-step-workflows), and not for search and filter toolbars (use ui-ux).
---

# Form layout

Opt-in stack skill. It applies only where the repository builds a React web UI
with shared form primitives. The repository's own component names, sizes, and
tests take precedence; this skill supplies defaults and known failure modes.

Forms are document workflows, not dashboards: calm, linear, one primary
surface per page. Load `ui-ux` for component ownership and action hierarchy,
`accessible-product-development` for labels, focus, contrast, and target
size, and `inclusive-content-design` for labels, help, and error wording.

## Use the shared layer

- Every control in app code is a shared form control. A raw `select`,
  `input`, `textarea`, or `button` with app-local styling is migration debt;
  a page you touch moves its controls to the shared components in the same
  change. A remaining raw control needs a recorded reason.
- Fix spacing, radius, dark mode, and control state in the shared primitive,
  never in one page. After changing a primitive, verify its own tests, the
  built package output, and one consuming page.
- Create and edit for the same entity share the schema, default-value mapper,
  section definitions, validation messages, and server actions.

## Choose a select

Pick the variant from the shared select family by need: native for a short
fixed list, a custom variant for rich options, and a searchable or combobox
variant when the user must search or type. The shared primitive owns height
and tokens so the variants stay consistent; pages never restyle one.

## Lay out the form

- One primary form surface per page. Do not nest bordered cards inside it.
  A section is a title, an optional one-line description, a divider, and its
  fields. Use cards only for independently meaningful objects such as
  repeatable items, reorderable groups, or review summaries.
- Long text, lookups, and complex controls take the full width. Short related
  fields (start and end, minimum and maximum) may share a row. Use one column
  on mobile, and never add columns only to shorten a form.
- Field width matches the expected input; a single-column form keeps a
  readable measure instead of stretching across the page.
- One shared form-footer component owns the committing action and form state
  for long forms, and keeps destructive actions separate from submit.
  Full-page create and edit routes guard unsaved changes on navigation,
  refresh, and close.

## Field conventions

- Every input has a visible label. A placeholder holds only a format example,
  never the label or instructions.
- Mark whichever of required or optional is rarer and explain the marker once
  at the top.
- Keep submit enabled; never disable it to signal invalid input. Submitting
  with problems shows one shared error summary. Disable submit only while
  saving. Turn off native browser validation bubbles so they do not hide the
  summary. Load `accessible-product-development` for required state, error
  association, and focus.
- Helper and error text sit below the field.
- Autofill is on for sign-in and self-service forms and off when staff enter
  someone else's details. A person's own sign-in, password, and one-time-code
  fields use the standard credential autocomplete tokens; self-service
  profile fields use semantic tokens. Keep the correct input type and input
  mode either way.

## Collections and toggles

- Repeatable values (aliases, tags, languages, external identifiers) use chips
  or a searchable multi-select, not stacked input-plus-Add rows, unless each
  item is complex.
- Toggles use the shared toggle control, which owns label, description, and
  checked-state presentation.

## Known failure modes

- **Bright native controls on dark surfaces.** Native date, time, search, and
  select controls render light by default. Fix the color scheme in the shared
  primitive, never with page-local overrides.
- **Invisible control state.** Checked, disabled, and error states need
  explicit styling that passes a contrast check in every theme.
- **Short selects beside taller inputs.** A raw select with local classes
  renders shorter than the shared input; replace it with the shared select.
- **Review artifacts committed.** Screenshots, snapshots, DOM dumps, and
  browser traces are review evidence, not source, unless they are intentional
  fixtures.

## Proof

Shared primitive changes need real-browser component tests for keyboard and
focus behavior. Moving a page to shared controls needs browser proof of that
page at a narrow mobile and a desktop width, in light and dark themes, with an
automated accessibility scan. Select further proof with
`verification-selection`; a green scanner is evidence, not conformance.
