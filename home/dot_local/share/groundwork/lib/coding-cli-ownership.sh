# shellcheck shell=bash
# Read-only command resolution facts; installation receipts do not prove PATH.

gw_cli_bounded() {
  local supervisor
  supervisor="$(command -v timeout || command -v gtimeout || true)"
  [[ -n "$supervisor" ]] || return 69
  "$supervisor" --kill-after=1s 5 "$@"
}

gw_cli_resolve() {
  local path="$1" target count=0 directory
  [[ "$path" == /* && "$path" != *$'\n'* && "$path" != *$'\t'* ]] || return 1
  while [[ "$count" -lt 20 ]]; do
    directory="$(cd -P -- "$(dirname -- "$path")" 2>/dev/null && pwd -P)" || return 1
    path="$directory/$(basename -- "$path")"
    if [[ ! -L "$path" ]]; then
      [[ -x "$path" && -f "$path" ]] || return 1
      printf '%s\n' "$path"
      return 0
    fi
    target="$(readlink -- "$path")" || return 1
    case "$target" in /*) path="$target" ;; *) path="$directory/$target" ;; esac
    count=$((count + 1))
  done
  return 1
}

gw_cli_version() {
  local output version
  output="$(gw_cli_bounded "$1" --version 2>/dev/null)" || return 1
  read -r version _ <<<"$output"
  [[ "$version" =~ ^[0-9]{1,9}\.[0-9]{1,9}\.[0-9]{1,9}$ ]] || return 1
  printf '%s\n' "$version"
}

gw_cli_version_older() {
  local left="$1" right="$2" la lb lc ra rb rc
  IFS=. read -r la lb lc <<<"$left"
  IFS=. read -r ra rb rc <<<"$right"
  ((10#$la < 10#$ra)) && return 0
  ((10#$la == 10#$ra)) || return 1
  ((10#$lb < 10#$rb)) && return 0
  ((10#$lb == 10#$rb)) || return 1
  ((10#$lc < 10#$rc))
}

gw_claude_ownership_report() {
  local brew_bin prefix managed managed_real effective effective_real
  local managed_version effective_version owner
  effective="$(command -v claude || true)"
  if [[ -z "$effective" ]]; then
    echo 'Claude Code: no effective claude command; no installed-version claim.'
    return 0
  fi
  printf 'Claude Code effective command: %s\n' "$effective"
  effective_real="$(gw_cli_resolve "$effective")" || {
    echo 'Claude Code warning: effective executable ownership is unknown.'
    return 0
  }
  printf 'Claude Code resolved executable: %s\n' "$effective_real"
  owner='manual or separately managed'
  if [[ "$effective" == "$HOME/.local/bin/claude" && "$effective_real" == "$HOME/.local/share/claude/versions/"* ]]; then
    owner='native installer'
  fi
  effective_version="$(gw_cli_version "$effective")" || effective_version=unknown
  brew_bin="${GROUNDWORK_BREW_BIN:-}"
  [[ -n "$brew_bin" ]] || brew_bin="$(command -v brew || true)"
  prefix="$(gw_cli_bounded "$brew_bin" --prefix 2>/dev/null)" || prefix=''
  if [[ "$prefix" != /* || "$prefix" == *$'\n'* || "$prefix" == *$'\t'* ]]; then
    printf 'Claude Code effective version: %s (owner: %s)\n' "$effective_version" "$owner"
    echo 'Claude Code warning: Homebrew prefix unavailable; freshness comparison is unknown.'
    return 0
  fi
  managed="$prefix/bin/claude"
  managed_real="$(gw_cli_resolve "$managed")" || managed_real=''
  case "$managed_real" in
    "$prefix/Caskroom/claude-code@latest/"*) ;;
    *)
      printf 'Claude Code effective version: %s (owner: %s)\n' "$effective_version" "$owner"
      echo 'Claude Code: selected Homebrew installation is unavailable or has unknown ownership; no freshness claim.'
      return 0
      ;;
  esac
  if [[ "$effective_real" == "$managed_real" ]]; then owner=Homebrew; fi
  printf 'Claude Code effective version: %s (owner: %s)\n' "$effective_version" "$owner"
  managed_version="$(gw_cli_version "$managed")" || managed_version=unknown
  printf 'Claude Code Homebrew command: %s (version: %s)\n' "$managed" "$managed_version"
  if [[ "$effective_real" == "$managed_real" ]]; then
    echo 'Claude Code: effective command is the selected Homebrew installation.'
  elif [[ "$effective_version" == unknown || "$managed_version" == unknown ]]; then
    echo 'Claude Code warning: a separate command shadows Homebrew; version comparison is unknown.'
  elif gw_cli_version_older "$effective_version" "$managed_version"; then
    echo 'Claude Code warning: an older command shadows the newer Homebrew installation.'
    echo 'Review ownership and reversible recovery: groundwork-help Claude'
  else
    echo 'Claude Code: a separate command shadows Homebrew and is at least its observed version.'
    echo 'Separate updater ownership remains deliberate; no installation or PATH was changed.'
  fi
  return 0
}
