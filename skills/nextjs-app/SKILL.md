---
name: nextjs-app
description: Builds and reviews Next.js App Router application code, covering rendering mode, server data fetching, React Server Component caching and Suspense, page metadata and titles, middleware or proxy, and server-side list pages. Use only in repositories that use the Next.js App Router, when changing app pages, layouts, route handlers, next.config, middleware, or proxy. Not for repositories without Next.js, not for deploy packaging (use aws-sst-deploy), and not for URL state rules (use url-state-navigation).
---

# Next.js app

Opt-in stack skill. It applies only where the repository uses the Next.js App
Router. The repository's own instructions, packages, commands, and budgets
take precedence; this skill supplies defaults and known failure modes.

Load `url-state-navigation` for search params and history,
`web-performance-triage` for slow or timing-out routes, and
`aws-sst-deploy` for OpenNext packaging. Load `dependency-change` before
changing the Next.js version itself.

## Baseline

- App Router only; do not add a `pages/` directory to an App Router app.
- Every app in a monorepo follows the repository's single Next.js version
  authority. Do not pin one app separately.
- Next.js APIs move between releases. Read the documentation that matches the
  installed version, including any docs shipped inside the installed package,
  before using an API you have not verified in this repository.
- If the installed version offers to generate agent instruction files inside
  app directories, keep that off when the repository already routes agent
  guidance; one instruction authority per repository.
- Every app declares its required environment variables in one validated
  schema and a committed template with placeholders, never real values.
- Adding a new app is a structural change; get the owner's approval first.

## Choose the rendering intent

| The page | Intent |
|---|---|
| Serves static marketing or documentation content | prerendered |
| Reads a database, an API, headers, cookies, or live environment | rendered per request |
| Shows request-independent data that tolerates bounded staleness | cached with explicit invalidation |

The mechanism depends on the installed version and on whether the app uses
Cache Components: with them, rendering is per request unless a scope opts into
caching, and route-segment rendering config is not available. Read the
installed version's documentation before choosing the mechanism.

Never read a database or API at module top level or at build time, never
statically generate a page that queries a provisioned database, and never ship
a `page` whose only job is to redirect; use configured redirects or
middleware.

## Fetch server data deliberately

- Keep first-render data small: session, route shell, search params, and the
  first page of the primary list. Put slow or optional widgets behind
  Suspense, a separate endpoint, or a cached server component, and give each
  a visible degraded state. An optional widget never blocks the primary table
  or the page.
- Use a cache directive only for request-independent reads, and pair it with
  an explicit lifetime, a tag, and invalidation owned by the writer. Never
  place cookies, headers, authentication-derived values, raw search params, or
  user-specific data inside a cached scope. Suspense never authorizes caching
  identity-scoped data.
- Serve summary numbers on data-heavy pages from precomputed values instead of
  aggregating during the request, and show when they were last updated.

## Server-side lists

Database-backed list pages paginate, filter, and sort on the server, driven by
URL search params translated into bounded queries. Select only the columns the
view renders. Never filter a database-sourced list only on the client. The
exception is a small, static, in-memory list.

## Page titles

- One shared metadata helper owns the application name, environment marker,
  separator, and title template. Pages pass only the page name; never
  concatenate app names, stages, or separators in a page, and never assign
  `document.title` directly.
- Pages inherit layout metadata by default. Add page metadata only when the
  route is a meaningfully different page. Page names match the visible heading
  and navigation wording, not URL spelling.
- Dynamic record pages use a generic name such as "Person details". Never put
  personal data, record names, or identifiers in a title; apply
  `privacy-by-design`.
- Route error boundaries must be client components, and the global error
  boundary renders its own `html` and `body`. Root pages and the root
  not-found page do not receive a same-segment title template, so they set
  their metadata explicitly.

## Middleware or proxy

Newer releases rename middleware to proxy, and the runtime it runs in depends
on the installed version; check that version's documentation before using
Node-only APIs there. Use it for request normalization, authentication gating
before render, and non-production no-index headers. Business logic does not
belong there.

## Proof

Run the repository's typecheck, lint, tests, and production build for each
changed app; the build is what proves the output mode and route rendering
classification. For server data changes, smoke the actual route URL and its
client navigation payload, prove related API or polling endpoints do not time
out during navigation, and exercise degraded optional widgets and route error
boundaries. Select heavier proof with `verification-selection`.
