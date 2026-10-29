# Bounded and observable operations

Groundwork runs long external work — Homebrew, mise, chezmoi, git, downloads,
macOS configuration — where a hang looks exactly like slow progress. Every finite
operation declares four things: a completion deadline, how progress is observed,
how it cancels, and what is true after it stops.

`AGENTS.md` carries the one-line rule. This spec holds the model.

## The four bounds are not interchangeable

Collapsing them causes both false kills and silent hangs.

| Bound | Meaning | On expiry |
| --- | --- | --- |
| **Hard deadline** | The operation's real completion limit | Abort and fail |
| **Stall threshold** | Progress has gone quiet | Report and run diagnostics — never kill on its own, because a slow download is quiet but healthy |
| **Performance budget** | The operation finished but missed its target | Report; this is not a failure |
| **Workflow `timeout-minutes`** | Last-resort protection | Never the operation's real deadline |

A retry count without a cumulative deadline is still unbounded.

## A timeout is a failure, never a slow success

Exit nonzero, cancel the child tree, preserve evidence, and print the exact
recovery command. A failed or timed-out bootstrap never reports that the machine
is ready.

## Long-lived things bound their phases, not their lifetime

Intentionally long-lived processes — login shells, tmux sessions, watchers, dev
servers — bound startup, readiness, individual requests, and shutdown rather than
total lifetime.

## Do not assume GNU `timeout`

Bootstrap runs before Homebrew exists, and this repo has already been bitten by
GNU/BSD `stat` differences. A bounded runner must use what is guaranteed at the
point in bootstrap where it runs, and must be tested on macOS.

The shared implementation is
`home/dot_local/share/groundwork/lib/maintenance-runner.sh`; the validator's
outer supervisor is `scripts/run-validation-deadline`.

## A whole-second clock never ends a bound early

The portable epoch clock (`date +%s`, also Bash's `SECONDS`) counts whole
seconds, so an instant stamped S happened somewhere in [S, S+1). An N-second
deadline or grace has provably elapsed only once the clock reads more than
S + N. Comparing with `-ge` ends it anywhere from one poll to N seconds after it
started, which turned a 1-second drain grace into a false process-leak failure.
The strict comparison overshoots by at most one second plus one poll, which is
the accepted cost of never cutting a declared bound short. The shared runner's
`bounded_seconds_elapsed` owns this rule, and `scripts/test-maintenance-runner`
proves it with a scripted clock. The foreground Mac App Store authorization
watchdog uses the same comparison. A `sudo -v` that has already exited 0 is
not a timeout when the cancel scan loses that race.
`scripts/test-mas-auth-deadline` proves both.
