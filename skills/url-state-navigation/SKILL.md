---
name: url-state-navigation
description: Keeps meaningful view state in the URL for Next.js App Router applications, covering search and hash params, router push versus replace, filters, tabs, pagination, selected records, drilldowns, URL-synced search inputs, and remembered list preferences. Use only in Next.js repositories when changing what a URL restores or how Back and Forward behave. Not for repositories without Next.js, and not for server data fetching (use nextjs-app).
---

# URL state navigation

Opt-in stack skill. It applies only where the repository uses the Next.js App
Router. The repository's own helpers, parameter names, and tests take
precedence; this skill supplies defaults and known failure modes.

State that changes which data or section the user sees lives in the URL, so a
view can be shared, reloaded, and replayed with Back and Forward.

## Push or replace

Use `router.push` or a real link for navigation the user expects Back to undo:
overview to detail, drilldowns, major tabs, pagination, opening a selected
record, and applying a committed filter (a choice, a chip, a submit, or a
blur).

Use `router.replace` only for non-semantic cleanup and high-frequency
transient state: typing before submit, removing default or empty params,
canonical param ordering, dropping stale params, and UI-only expand or
collapse. Never replace for selected rows, tabs, committed filters, pages,
records, or drilldowns unless the user should not be able to go Back through
them.

## Shape the URL

- Build URL changes through one shared helper that makes push versus replace
  explicit and canonicalizes params. Avoid direct `window.history` calls.
- Omit default and empty params; keep names human-readable and stable.
- The hash is a scroll target only, never the sole source of meaningful state.
- Opening a URL restores the same view. An invalid identifier shows a clear
  not-found state, not a silent default.
- Keep route-specific typed param parsing in the app until a second consumer
  proves it should be shared.
- External links are ordinary anchors, never internal router navigation.
  When the product opens them in a new tab, use `rel="noopener noreferrer"`
  and say so in the link; load `accessible-product-development` for that
  change of context.
- Links and buttons inside a selectable row never trigger the row's own
  selection.

## URL-synced search inputs

URL navigation resolves asynchronously. An input that writes every keystroke
to the URL and also re-syncs from the URL replays stale values over newer
keystrokes and spams history. A URL-backed search input does all three:

1. Debounces emission so one pause becomes one navigation, and lets an
   explicit Search action flush immediately.
2. Remembers the values it emitted that have not round-tripped yet. An
   incoming value that matches one is its own echo; anything else is an
   external change (Back, Forward, reset, saved view), so cancel the pending
   emit and accept it, even mid-typing. The input converges to the URL; it
   never holds a draft the URL no longer shows.
3. Uses replace for live filtering while typing so Back leaves the page
   instead of walking through drafts, and push only for an explicitly
   submitted search.

Value matching cannot distinguish an external change to a value that is also
still pending. The complete fix is a navigation-generation token; do not add
more value heuristics.

## Preference scope

| State | Remembered? | URL |
|---|---|---|
| Committed filters, search text, page | Never | URL only |
| Column set, density, sort, page size | Per user, per list | The URL wins when present; never write remembered values into the URL on load |
| Navigation rail collapsed | Per user, global | Never; read it on the server so the rail does not flash |

## Proof

Unit-test parsing, serialization, defaults, and that toggling a filter keeps
protected context such as a selected record. Use real-browser component tests for
filter, sort, and search controls. Use route-level browser tests only for
reload and history: the URL restores the view, Back steps through meaningful
states and Forward replays them, transient typing creates no history entries,
and a popstate never resets to a default view. Select any heavier proof with
`verification-selection`.
