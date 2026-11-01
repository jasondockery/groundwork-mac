#!/usr/bin/env bash
set -euo pipefail
# A full update-all reports Claude Code ownership itself, after its Homebrew
# lane has settled the installed version. Reporting here too would print the
# same section twice in one run, the first time against pre-upgrade state.
[[ "${GROUNDWORK_UPDATE_SCOPE:-}" != maintenance ]] || exit 0
ownership_lib="$HOME/.local/share/groundwork/lib/coding-cli-ownership.sh"
[[ -r "$ownership_lib" ]] || {
  echo "Groundwork: coding CLI ownership probe is missing: $ownership_lib" >&2
  exit 1
}
# shellcheck source=/dev/null
. "$ownership_lib"
gw_claude_ownership_report
