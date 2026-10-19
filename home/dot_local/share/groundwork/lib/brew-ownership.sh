# shellcheck shell=bash
# A known Homebrew-to-Homebrew rename is reversible; manual commands stay owned
# by their user. Never overwrite an unrelated command to make a bundle pass.
groundwork_reconcile_opencode() {
  local prefix old_prefix new_prefix command_path install_status=0
  prefix="$(brew --prefix)" || return 1
  old_prefix="$(brew --prefix opencode-v2 2>/dev/null)" || return 0
  command_path="$prefix/bin/opencode"
  [[ -f "$old_prefix/bin/opencode" ]] || return 0
  if [[ ! -L "$command_path" || ! "$command_path" -ef "$old_prefix/bin/opencode" ]]; then
    # Already converged or user-owned: the normal bundle retains ownership.
    return 0
  fi
  echo "Groundwork: migrating the Homebrew opencode-v2 command to opencode; both installations are retained."
  new_prefix="$(brew --prefix opencode)" || return 1
  if [[ ! -x "$new_prefix/bin/opencode" ]]; then
    HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_ASK=1 brew install --formula --skip-link opencode || install_status=$?
    [[ "$install_status" -eq 0 ]] || return "$install_status"
  fi
  [[ -x "$new_prefix/bin/opencode" ]] || return 1
  brew unlink opencode-v2 || return 1
  if brew link opencode; then
    [[ "$command_path" -ef "$new_prefix/bin/opencode" ]] && return 0
  fi
  echo "Groundwork: linking opencode failed; restoring the original command." >&2
  brew unlink opencode || return 1
  brew link opencode-v2 || return 1
  if [[ ! "$command_path" -ef "$old_prefix/bin/opencode" ]]; then
    echo "Groundwork: original OpenCode ownership could not be restored; review Homebrew's output." >&2
  fi
  return 1
}
