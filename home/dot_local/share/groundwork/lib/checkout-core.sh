#!/usr/bin/env bash
# bash 3.2+ (stock macOS). Check out the pinned core submodule before anything
# reads core/browser/brave.json. `git submodule update --init` follows the
# parent gitlink. It does not follow core's branch.
# A tree with no Git checkout, or no core submodule, is left unchanged.
set -euo pipefail

if [[ $# -ne 1 || -z "${1:-}" ]]; then
  echo "usage: checkout-core.sh <working-tree>" >&2
  exit 64
fi

root="$1"
if [[ "$(basename "$root")" == "home" && -f "$(dirname "$root")/.gitmodules" ]]; then
  root="$(dirname "$root")"
fi

if [[ ! -e "$root/.git" || ! -f "$root/.gitmodules" ]]; then
  exit 0
fi

if ! git -C "$root" config -f "$root/.gitmodules" --get submodule.core.path >/dev/null 2>&1; then
  exit 0
fi

deadline="${GROUNDWORK_CORE_CHECKOUT_DEADLINE_SECONDS:-120}"
if [[ ! "$deadline" =~ ^[0-9]+$ || "$deadline" -lt 1 || "$deadline" -gt 600 ]]; then
  echo "Groundwork: the core checkout deadline must be an integer from 1 through 600 seconds." >&2
  exit 64
fi

marker="$(mktemp)"
child_pid=""

finish() {
  if [[ -n "$child_pid" ]]; then
    kill "$child_pid" 2>/dev/null || true
    pkill -P "$child_pid" 2>/dev/null || true
    wait "$child_pid" 2>/dev/null || true
    child_pid=""
  fi
  if [[ -n "$marker" ]]; then
    rm -f -- "$marker"
    marker=""
  fi
}

trap finish EXIT
trap 'finish; exit 130' INT
trap 'finish; exit 143' TERM

# git's own stderr is the progress. The wait stays in this process: a background
# sleeper would outlive the checkout and fail the validator's process-group check.
# The poll is short so an already-checked-out core does not add a second to
# every update. The deadline is a failure, not a slow success.
GIT_TERMINAL_PROMPT=0 git -C "$root" submodule update --init -- core &
child_pid=$!
started="$(date +%s)"
while kill -0 "$child_pid" 2>/dev/null; do
  now="$(date +%s)"
  if [[ $((now - started)) -ge "$deadline" ]]; then
    printf 'timed-out\n' >"$marker"
    kill "$child_pid" 2>/dev/null || true
    pkill -P "$child_pid" 2>/dev/null || true
    break
  fi
  sleep 0.1
done
status=0
wait "$child_pid" || status=$?
child_pid=""

if [[ -s "$marker" ]]; then
  echo "Groundwork: checking out core exceeded its ${deadline}s deadline." >&2
  finish
  exit 124
fi
finish
exit "$status"
