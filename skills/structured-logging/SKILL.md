---
name: structured-logging
description: Treats emitted logs as an operator-facing contract with stable event names, meaningful levels, correlation fields, structured metadata, allowlisted free text, and plain-language rendering. Use when adding or changing a log statement, event name, log level, logged field, or a diagnostic that captures error or console text. Not for querying logs or building dashboards, and not for deciding which personal data may be collected (use privacy-by-design).
---

# Structured logging

Logs are an operator product. Write each event for the people who triage it,
including people who never read the code. Load `secure-by-design` for
credentials and `privacy-by-design` for personal data; keep the event
contract here.

## 1. Emit through the repository logger

- Use the repository's registered structured logger. Never write
  unstructured stdout or stderr lines from application or server code; those
  lines lose the structured base fields.
- Base fields such as application, environment, deployment stage, and
  version come from registered metadata, never from per-event payloads. Give
  a domain value that resembles a base field an explicit name
  (`targetEnvironment`, `releaseVersion`) so it cannot shadow one.

## 2. Event names are an API

- The message is a stable dotted event name, not a sentence. The repository
  owns the grammar, for example `domain.area.subject.action`.
- Renaming an event breaks saved searches, dashboards, and alerts. Treat a
  rename as an interface change and search for every reference first.
- Operations use lifecycle suffixes: `.start`; `.done` with a numeric
  duration; `.failed` with the error. Use a distinct suffix for an exceeded
  observability budget where the repository defines one.

## 3. Correlate every line

- Mint a request or job ID once at the logical boundary and propagate it
  through every service and line that work touches. Background work mints a
  fresh ID per run; one reused string merges every run into one request.
- An attempt ID is per execution attempt. A retried job keeps its request ID
  and gets a new attempt ID; never substitute one for the other.
- A stable operation name groups recurring work across runs. Request-scoped
  work also logs its route.

## 4. Levels mean something to the reader

| Level | Meaning to the person reading |
| --- | --- |
| debug | Detailed diagnostic evidence; invisible in normal triage. |
| info | Expected lifecycle or audit evidence: completions, counts, durations. No action needed. |
| warn | Unexpected or degraded: fallback, partial result, retry, threshold crossed. The outcome may still succeed. |
| error | The requested operation failed or produced an unusable result. Someone may need to act. |
| fatal | The process or service cannot continue. |

Alert rules decide paging from recurrence and impact. A level alone never
means "page someone": a recurring warn may page, while a one-off error on a
retried path may not.

## 5. Structured metadata

- Use structured fields, never values interpolated into the message.
  Numbers stay numbers so they aggregate.
- When an operator must find a record from a log line, log its internal ID
  and document which ID to search by.
- Follow the repository's identifier and credential classification and the
  logger's field allowlist. Neither redact-all nor log-all is correct:
  bounded, intentionally allowlisted identifiers may be searchable;
  credentials and arbitrary payload dumps never are.

## 6. Free text: allowlist, never denylist

When a diagnostic captures arbitrary text such as exception messages,
console output, or network failure strings, keep only tokens from a fixed
vocabulary (known error names, platform error codes, short status numbers,
reviewed non-credential words) and replace everything else with one marker.

- Denylists never converge. Each review round finds another leak shape:
  header placement, encodings, quoting, Unicode, `key: value` assignments,
  credentials embedded in URLs, and secrets that look like plain words.
- Prove the filter with a property test across the token grammar (credential
  carrier, separator, value shape, encoding, quoting, context) plus seeded
  fuzzing that every output token belongs to the vocabulary, checked before
  length truncation.
- The vocabulary is the residual risk: a secret equal to an allowed word
  passes. Use this filter only where the surface's accepted contract records
  that residual. Where secret-bearing text must be omitted entirely, emit
  structured fields only.
- When an operator needs more detail, add a structured field, never more
  free text.

## 7. Operator rendering is part of the change

When the repository renders events for operators, a new event family that
operators will see (warn and above, or named in a runbook) gets a
plain-language title and summary: what happened, the impact, and whether
action is needed. Claim only what the event proves; unknown families get
neutral copy. Add a rendering test case.

## Done when

- Focused tests for the changed emitters and rendering pass.
- A renamed event has no stale reference in repository-owned dashboards,
  alerts, documentation, or link builders.
