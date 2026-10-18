#!/usr/bin/env bash

# Ask for administrator permission once, and tell callers when no terminal
# can answer. Passwords stay on the terminal: this file never reads, logs,
# or stores them. A cached sudo timestamp is refreshed until the caller stops
# the keepalive, so a long install does not ask again.

groundwork_sudo_keepalive_pid=""

groundwork_sudo_keepalive_stop() {
  local pid="${groundwork_sudo_keepalive_pid:-}"
  groundwork_sudo_keepalive_pid=""
  if [[ -n "$pid" ]]; then
    kill "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
  fi
}

groundwork_sudo_keepalive_start() {
  local parent=$$
  groundwork_sudo_keepalive_stop
  # Own the sleeper so stopping this refresh also stops the wait. A bare
  # background sleep would keep running after the shell that started it exits.
  (
    sleep_pid=""
    trap 'if [[ -n "$sleep_pid" ]]; then kill "$sleep_pid" 2>/dev/null || true; fi; exit 0' TERM INT
    while kill -0 "$parent" 2>/dev/null; do
      sleep 50 &
      sleep_pid=$!
      wait "$sleep_pid" || exit 0
      sleep_pid=""
      sudo -n true 2>/dev/null || exit 0
    done
  ) &
  groundwork_sudo_keepalive_pid=$!
}

# 0 when /dev/tty is a controlling terminal this process can use.
groundwork_sudo_terminal_open() {
  [[ -r /dev/tty && -w /dev/tty ]] || return 1
  : </dev/tty >/dev/null || return 1
}

# Returns 0 when privileged commands can proceed, 10 when they must be set
# aside because nobody can enter a password, 130 when the person cancelled
# the prompt, and 1 when sudo failed for another reason.
groundwork_sudo_prepare() {
  local status=0
  groundwork_sudo_keepalive_stop
  if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
    return 0
  fi
  if ! command -v sudo >/dev/null 2>&1; then
    return 10
  fi
  if sudo -n true 2>/dev/null; then
    groundwork_sudo_keepalive_start
    return 0
  fi
  if ! groundwork_sudo_terminal_open; then
    return 10
  fi
  echo "Groundwork: this step needs an administrator password."
  echo "Enter your password when asked. This approval covers the privileged steps in this run."
  # sudo -v reads the password on its own standard input. Point that prompt at
  # the terminal. These redirects are not a command run under sudo.
  # shellcheck disable=SC2024
  sudo -v </dev/tty >/dev/tty 2>/dev/tty || status=$?
  if [[ "$status" -ne 0 ]]; then
    if [[ "$status" -eq 130 ]]; then
      return 130
    fi
    return 1
  fi
  groundwork_sudo_keepalive_start
  return 0
}

groundwork_sudo_deferred_path() {
  printf '%s\n' "${HOME}/.local/state/groundwork/sudo-deferred-casks.txt"
}

# Print cask tokens whose Homebrew installer is a pkg or script installer.
# Those are the installs that call sudo. Returns 2 when the metadata or a
# parser is unavailable; the caller must not guess which casks to skip.
groundwork_casks_needing_installer_sudo() {
  local brewfile="$1"
  local requested metadata needed parser_status token
  requested="$(mktemp "${TMPDIR:-/tmp}/groundwork-sudo-casks.XXXXXX")"
  metadata="$(mktemp "${TMPDIR:-/tmp}/groundwork-sudo-meta.XXXXXX")"
  needed="$(mktemp "${TMPDIR:-/tmp}/groundwork-sudo-needed.XXXXXX")"
  awk '
    $1 == "cask" {
      token = $2
      gsub(/^"|"$/, "", token)
      gsub(/,$/, "", token)
      if (token ~ /^[A-Za-z0-9@+._-]+$/) print token
    }
  ' "$brewfile" | LC_ALL=C sort -u >"$requested"
  if [[ ! -s "$requested" ]]; then
    rm -f -- "$requested" "$metadata" "$needed"
    return 0
  fi

  local -a tokens=()
  while IFS= read -r token; do
    [[ -n "$token" ]] && tokens+=("$token")
  done <"$requested"
  if ! HOMEBREW_NO_AUTO_UPDATE=1 brew info --json=v2 --cask -- "${tokens[@]}" >"$metadata"; then
    rm -f -- "$requested" "$metadata" "$needed"
    return 2
  fi

  parser_status=0
  if command -v jq >/dev/null 2>&1; then
    jq -r '
      .casks[]?
      | select(any(.artifacts[]?; has("pkg") or has("installer")))
      | .token
      | select(test("^[A-Za-z0-9@+._-]+$"))
    ' "$metadata" >"$needed" || parser_status=$?
  elif perl -MJSON::PP -e 1 >/dev/null 2>&1; then
    perl -MJSON::PP -e '
      local $/;
      my $parsed = JSON::PP->new->utf8->decode(<>);
      for my $cask (@{ $parsed->{casks} || [] }) {
        my $needs_sudo = 0;
        for my $artifact (@{ $cask->{artifacts} || [] }) {
          $needs_sudo = 1 if exists $artifact->{pkg} || exists $artifact->{installer};
        }
        my $token = $cask->{token} // "";
        print $token, "\n" if $needs_sudo && $token =~ /^[A-Za-z0-9@+._-]+\z/;
      }
    ' "$metadata" >"$needed" || parser_status=$?
  elif command -v python3 >/dev/null 2>&1; then
    python3 - "$metadata" >"$needed" <<'PY' || parser_status=$?
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    parsed = json.load(handle)
for cask in parsed.get("casks") or []:
    token = cask.get("token") or ""
    artifacts = cask.get("artifacts") or []
    if not token or any(character.isspace() for character in token):
        continue
    if not all(character.isalnum() or character in "@+._-" for character in token):
        continue
    if any(isinstance(artifact, dict) and ("pkg" in artifact or "installer" in artifact) for artifact in artifacts):
        print(token)
PY
  else
    parser_status=2
  fi
  if [[ "$parser_status" -ne 0 ]]; then
    rm -f -- "$requested" "$metadata" "$needed"
    return 2
  fi

  while IFS= read -r token; do
    [[ -n "$token" ]] || continue
    if grep -qxF -- "$token" "$requested"; then
      printf '%s\n' "$token"
    fi
  done <"$needed"
  rm -f -- "$requested" "$metadata" "$needed"
}

groundwork_sudo_record_deferred() {
  local path dir token
  path="$(groundwork_sudo_deferred_path)"
  dir="$(dirname "$path")"
  mkdir -p -- "$dir"
  if [[ -L "$path" || (-e "$path" && ! -f "$path") ]]; then
    return 1
  fi
  [[ -e "$path" ]] || : >"$path"
  chmod 600 "$path"
  for token in "$@"; do
    [[ "$token" =~ ^[A-Za-z0-9@+._-]+$ ]] || return 1
  done
  for token in "$@"; do
    if ! grep -qxF -- "$token" "$path"; then
      printf '%s\n' "$token" >>"$path"
    fi
  done
}

groundwork_sudo_read_deferred() {
  local path="$1"
  [[ -f "$path" && ! -L "$path" ]] || return 0
  if ! awk 'NF == 0 { next } NF != 1 || $0 !~ /^[A-Za-z0-9@+._-]+$/ { exit 1 }' "$path"; then
    return 1
  fi
  awk 'NF == 1 { print }' "$path"
}
