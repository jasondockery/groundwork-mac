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

# Groundwork's claude_code_owner names which installation should own `claude`.
# Two copies are not a failure: report the chosen owner and how to remove the
# other one, and never change either installation here.
gw_claude_dual_install_report() {
  local owner="${1:-homebrew}" native="$HOME/.local/bin/claude" brew_bin prefix
  local managed managed_real native_version managed_version chosen
  case "$owner" in homebrew | native) ;; *) owner=homebrew ;; esac
  [[ -e "$native" || -L "$native" ]] || return 0
  brew_bin="${GROUNDWORK_BREW_BIN:-}"
  [[ -n "$brew_bin" ]] || brew_bin="$(command -v brew || true)"
  [[ -n "$brew_bin" ]] || return 0
  prefix="$(gw_cli_bounded "$brew_bin" --prefix 2>/dev/null)" || return 0
  [[ "$prefix" == /* && "$prefix" != *$'\n'* && "$prefix" != *$'\t'* ]] || return 0
  managed="$prefix/bin/claude"
  managed_real="$(gw_cli_resolve "$managed")" || return 0
  case "$managed_real" in "$prefix/Caskroom/claude-code@latest/"*) ;; *) return 0 ;; esac
  # A ~/.local/bin/claude link into the cask is the same copy, not a second one.
  [[ "$(gw_cli_resolve "$native" || true)" != "$managed_real" ]] || return 0
  native_version="$(gw_cli_version "$native")" || native_version=unknown
  managed_version="$(gw_cli_version "$managed")" || managed_version=unknown
  printf 'Claude Code warning: two copies are installed: native %s (version %s) and Homebrew claude-code@latest %s (version %s).\n' \
    "$native" "$native_version" "$managed" "$managed_version"
  chosen="$managed"
  if [[ "$owner" == native ]]; then
    chosen="$native"
    echo 'Claude Code chosen owner: native (claude_code_owner = "native"; change it with groundwork-configure).'
    echo 'Remove the Homebrew copy: brew uninstall --cask claude-code@latest'
  else
    echo 'Claude Code chosen owner: homebrew (claude_code_owner = "homebrew"; change it with groundwork-configure).'
    echo 'Remove the native copy, with a private rollback backup: groundwork-claude-owner homebrew --yes'
  fi
  printf 'Point the T3 Code Claude provider Binary path at the chosen owner: %s\n' "$chosen"
  return 0
}

# The first executable named $1 in the colon-separated directory list $2.
gw_cli_path_lookup() {
  local name="$1" directory directories=()
  IFS=: read -r -a directories <<<"$2"
  for directory in ${directories[@]+"${directories[@]}"}; do
    [[ "$directory" == /* ]] || continue
    if [[ -f "$directory/$name" && -x "$directory/$name" ]]; then
      printf '%s\n' "$directory/$name"
      return 0
    fi
  done
  return 1
}

# Report only: which claude T3 Code would start, and whether a Claude provider
# Binary path names a missing file. T3's settings are never written.
#
# What this relies on, from T3 Code's documentation and source (2026-11):
# - The server's settings live in settings.json in its userdata directory
#   (documented), under ${T3CODE_HOME:-~/.t3} (the documented default). With
#   no file, every setting is at its default.
# - A Claude instance is providerInstances.<id> with driver "claudeAgent"; its
#   Binary path is config.binaryPath, default "claude", and ~ expands to HOME.
#   That shape comes from source, not a documented format, and has changed
#   before, so an unrecognized file is reported as unknown, never guessed at.
# - The desktop app reads PATH from "$SHELL -ilc" and puts it ahead of its
#   own inherited PATH, so a bare name resolves on that login-shell PATH.
# jq extracts only each Claude instance id and its binaryPath; no other field
# (environment variables, secrets) is read or printed.
gw_t3_claude_report() {
  local owner="${1:-homebrew}" native="$HOME/.local/bin/claude" t3_home settings
  local jq_bin entries login_shell output login_path="" brew_bin prefix
  local homebrew_claude="/opt/homebrew/bin/claude" id setting where resolved real
  case "$owner" in homebrew | native) ;; *) owner=homebrew ;; esac
  t3_home="${T3CODE_HOME:-}"
  [[ "$t3_home" == /* ]] || t3_home="$HOME/.t3"
  if [[ ! -d "$t3_home" ]]; then
    echo "T3 Code: $t3_home not found; Claude resolution not checked."
    return 0
  fi
  settings="$t3_home/userdata/settings.json"
  brew_bin="${GROUNDWORK_BREW_BIN:-}"
  [[ -n "$brew_bin" ]] || brew_bin="$(command -v brew || true)"
  if [[ -n "$brew_bin" ]] && prefix="$(gw_cli_bounded "$brew_bin" --prefix 2>/dev/null)" \
    && [[ "$prefix" == /* && "$prefix" != *$'\n'* ]]; then
    homebrew_claude="$prefix/bin/claude"
  fi
  entries=""
  if [[ -e "$settings" ]]; then
    jq_bin="$(command -v jq || true)"
    if [[ -z "$jq_bin" ]]; then
      echo "T3 Code warning: jq is unavailable, so the Claude Binary path in $settings was not read."
      return 0
    fi
    # One TSV row per Claude instance: its id, "ok" or "unsafe", then
    # binaryPath ("" when unset). A value with a control, format or other
    # non-printable character, or a backslash, is withheld so a crafted path
    # cannot write terminal escapes into the report.
    # shellcheck disable=SC2016 # $config is jq syntax, not a shell expansion.
    if ! entries="$("$jq_bin" -r '
        if type == "object" and ((.providerInstances // {}) | type) == "object" then
          (.providerInstances // {}) | to_entries[]
          | select((.value | type) == "object" and .value.driver == "claudeAgent")
          | (.value.config // {}) as $config
          | if ($config | type) == "object" and (($config.binaryPath // "") | type) == "string"
            then ($config.binaryPath // "") as $path
              | if ($path | test("[\\p{C}\\\\]")) then [.key, "unsafe", ""] else [.key, "ok", $path] end
              | @tsv
            else error("unrecognized") end
        else error("unrecognized") end' "$settings" 2>/dev/null)"; then
      echo "T3 Code warning: $settings is not in a format Groundwork recognizes, so the Claude Binary path was not checked."
      echo "Check it in T3 Code: Settings > Providers > Claude > Binary path."
      return 0
    fi
  fi
  # No Claude entry means the built-in instance with every default.
  [[ -n "$entries" ]] || entries="claudeAgent"$'\tok\t'
  login_shell="${SHELL:-}"
  [[ "$login_shell" == /* && -x "$login_shell" ]] || login_shell="$(command -v zsh || true)"
  # shellcheck disable=SC2016 # The login shell expands $PATH, not this one.
  if [[ -n "$login_shell" ]] \
    && output="$(gw_cli_bounded "$login_shell" -ilc 'printf "\nGROUNDWORK_T3_PATH=%s\n" "$PATH"' </dev/null 2>/dev/null)"; then
    login_path="$(printf '%s\n' "$output" | sed -n 's/^GROUNDWORK_T3_PATH=//p' | tail -n 1)"
  fi
  while IFS=$'\t' read -r id state setting; do
    if [[ ! "$id" =~ ^[A-Za-z0-9_.-]+$ ]]; then
      echo "T3 Code warning: a Claude instance in $settings has an id Groundwork cannot print safely; check Settings > Providers."
      continue
    fi
    if [[ "$state" != ok || "$setting" == *[[:cntrl:]]* ]]; then
      printf 'T3 Code warning: Claude instance %s has a Binary path with non-printable characters; it is not shown. Check Settings > Providers > %s.\n' "$id" "$id"
      continue
    fi
    where="providerInstances.$id.config.binaryPath in $settings"
    # T3 Code expands a leading ~ in Binary path; match it on this literal value.
    # shellcheck disable=SC2088
    case "$setting" in "") setting=claude ;; "~") setting="$HOME" ;; "~/"*) setting="$HOME/${setting#\~/}" ;; esac
    case "$setting" in
      /*)
        if [[ ! -f "$setting" || ! -x "$setting" ]]; then
          printf 'T3 Code warning: Claude instance %s has Binary path %s, which no longer exists or is not executable.\n' "$id" "$setting"
          printf 'In T3 Code, open Settings > Providers > %s and clear Binary path, or set it to %s (%s).\n' "$id" "$homebrew_claude" "$where"
          continue
        fi
        resolved="$setting"
        ;;
      */*)
        printf 'T3 Code warning: Claude instance %s has a relative Binary path, so Groundwork cannot tell what it runs (%s).\n' "$id" "$where"
        continue
        ;;
      *)
        if [[ -z "$login_path" ]]; then
          printf 'T3 Code warning: Claude instance %s runs %s from PATH, but the login-shell PATH T3 Code reads could not be observed.\n' "$id" "$setting"
          continue
        fi
        if ! resolved="$(gw_cli_path_lookup "$setting" "$login_path")"; then
          printf 'T3 Code warning: Claude instance %s cannot resolve %s on the login-shell PATH T3 Code uses.\n' "$id" "$setting"
          printf 'Install Claude Code for the chosen owner, or set Binary path to %s (%s).\n' "$homebrew_claude" "$where"
          continue
        fi
        ;;
    esac
    real="$(gw_cli_resolve "$resolved" || true)"
    printf 'T3 Code: Claude instance %s would run %s%s.\n' "$id" "$resolved" "${real:+ (resolves to $real)}"
    if [[ "$owner" == homebrew && ! -e "$native" && ! -L "$native" ]] \
      && [[ "$resolved" == "$native" || "$real" == "$HOME/.local/share/claude/versions/"* ]]; then
      printf 'T3 Code warning: that is the native copy, after the handover to Homebrew. Clear Binary path or set it to %s (%s).\n' "$homebrew_claude" "$where"
    fi
  done <<<"$entries"
  return 0
}

# Report only: whether each T3 Code Claude instance caps Claude Code's
# subagents with Groundwork's values. The values and their reasons live in
# docs/claude.html#subagent-caps. T3's settings are
# never written, and nothing is added to a login shell, so a claude started
# from a terminal keeps the upstream defaults.
#
# An instance's Environment variables are providerInstances.<id>.environment,
# a list of {name, value, sensitive, secret?}. T3 Code applies the list in
# order when it launches that instance, so the last entry for a name wins.
# That shape comes from T3 Code's settings schema in its source, not from a
# documented format. A value kept as a T3 secret is not in the file and is
# reported as unreadable. jq reads only the two names below, compares their
# values in place, and returns a state; no environment value is printed.
gw_t3_claude_subagent_caps_report() {
  local t3_home settings jq_bin rows id first second state name want index fix
  local names=(CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH)
  local values=(4 1) states=()
  t3_home="${T3CODE_HOME:-}"
  [[ "$t3_home" == /* ]] || t3_home="$HOME/.t3"
  settings="$t3_home/userdata/settings.json"
  if [[ ! -e "$settings" ]]; then
    echo "T3 Code: no settings file at $settings; subagent caps not applicable."
    return 0
  fi
  jq_bin="$(command -v jq || true)"
  if [[ -z "$jq_bin" ]]; then
    echo "T3 Code warning: jq is unavailable, so the Claude subagent caps in $settings were not read."
    return 0
  fi
  # One TSV row per Claude instance: its id, then for each cap in order one
  # of set, missing, different or secret.
  # shellcheck disable=SC2016 # $caps and $env are jq syntax, not shell expansions.
  if ! rows="$("$jq_bin" -r \
    --argjson caps "[[\"${names[0]}\",\"${values[0]}\"],[\"${names[1]}\",\"${values[1]}\"]]" '
      if type == "object" and ((.providerInstances // {}) | type) == "object" then
        (.providerInstances // {}) | to_entries[]
        | select((.value | type) == "object" and .value.driver == "claudeAgent")
        | (.value.environment // []) as $env
        | if ($env | type) == "array" then . else error("unrecognized") end
        | [.key] + [$caps[] as [$name, $want]
            | ([$env[] | select(type == "object" and .name == $name)] | last) as $entry
            | if $entry == null then "missing"
              elif $entry.secret != null then "secret"
              elif $entry.value == $want then "set"
              else "different" end]
        | @tsv
      else error("unrecognized") end' "$settings" 2>/dev/null)"; then
    echo "T3 Code warning: $settings is not in a format Groundwork recognizes, so the Claude subagent caps were not checked."
    echo "Check them in T3 Code → Settings → Providers → the Claude instance → Environment variables."
    return 0
  fi
  if [[ -z "$rows" ]]; then
    echo "T3 Code: no Claude provider instance in $settings; subagent caps not applicable."
    return 0
  fi
  while IFS=$'\t' read -r id first second; do
    states=("$first" "$second")
    if [[ ! "$id" =~ ^[A-Za-z0-9_.-]+$ ]]; then
      echo "T3 Code warning: a Claude instance in $settings has an id Groundwork cannot print safely; check its Environment variables in Settings → Providers."
      continue
    fi
    fix=0
    for index in 0 1; do
      name="${names[index]}" want="${values[index]}" state="${states[index]}"
      case "$state" in
        set) printf 'T3 Code: Claude instance %s sets %s=%s.\n' "$id" "$name" "$want" ;;
        missing) printf 'T3 Code warning: Claude instance %s does not set %s (Groundwork value: %s).\n' "$id" "$name" "$want" ;;
        secret) printf 'T3 Code warning: Claude instance %s keeps %s as a secret, so Groundwork cannot confirm it is %s.\n' "$id" "$name" "$want" ;;
        *) printf 'T3 Code warning: Claude instance %s sets %s to a value other than %s.\n' "$id" "$name" "$want" ;;
      esac
      [[ "$state" == set ]] || fix=1
    done
    if [[ "$fix" -eq 1 ]]; then
      printf 'Fix it in T3 Code → Settings → Providers → %s → Environment variables: %s=%s and %s=%s.\n' \
        "$id" "${names[0]}" "${values[0]}" "${names[1]}" "${values[1]}"
    fi
  done <<<"$rows"
  return 0
}
