#!/usr/bin/env bash
set -euo pipefail
ownership_lib="$HOME/.local/share/groundwork/lib/coding-cli-ownership.sh"
[[ -r "$ownership_lib" ]] || {
  echo "Groundwork: coding CLI ownership probe is missing: $ownership_lib" >&2
  exit 1
}
# shellcheck source=/dev/null
. "$ownership_lib"
gw_claude_ownership_report
