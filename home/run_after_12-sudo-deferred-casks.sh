#!/usr/bin/env bash
# Finish casks that an earlier apply set aside because nobody could enter an
# administrator password. This runs on every apply, including after the
# Brewfile hook has been recorded as done, so a later terminal session still
# installs them. A real install error stays a failure. No password is logged.

set -euo pipefail

sudo_preflight_lib="$HOME/.local/share/groundwork/lib/sudo-preflight.sh"
if [[ ! -r "$sudo_preflight_lib" ]]; then
  echo "Groundwork: administrator-permission helper is missing: $sudo_preflight_lib" >&2
  exit 1
fi
# shellcheck source=/dev/null
. "$sudo_preflight_lib"

deferred_path="$(groundwork_sudo_deferred_path)"
if [[ ! -e "$deferred_path" ]]; then
  exit 0
fi
if [[ -L "$deferred_path" || ! -f "$deferred_path" ]]; then
  echo "Groundwork: the set-aside app list is not a regular file: $deferred_path" >&2
  exit 1
fi

deferred_tokens=()
if ! deferred_text="$(groundwork_sudo_read_deferred "$deferred_path")"; then
  echo "Groundwork: the set-aside app list is malformed, so nothing was installed." >&2
  echo "From a terminal on this machine, run chezmoi apply and enter your password when asked." >&2
  exit 1
fi
while IFS= read -r deferred_token; do
  [[ -n "$deferred_token" ]] && deferred_tokens+=("$deferred_token")
done <<<"$deferred_text"
if [[ "${#deferred_tokens[@]}" -eq 0 ]]; then
  rm -f -- "$deferred_path"
  exit 0
fi

cleanup() {
  groundwork_sudo_keepalive_stop
  [[ -z "${deferred_brewfile:-}" ]] || rm -f -- "$deferred_brewfile"
}
trap cleanup EXIT

sudo_prepare_status=0
groundwork_sudo_prepare || sudo_prepare_status=$?
case "$sudo_prepare_status" in
  0) ;;
  10)
    echo "Groundwork: these apps still need an administrator password: ${deferred_tokens[*]}."
    echo "They are not installed yet. From a terminal on this machine, run chezmoi apply and enter your password when asked."
    exit 0
    ;;
  130)
    echo "Groundwork: the password prompt was cancelled. The set-aside apps were not installed." >&2
    exit 130
    ;;
  *)
    echo "Groundwork: administrator permission was not granted (exit ${sudo_prepare_status}). The set-aside apps were not installed." >&2
    exit "$sudo_prepare_status"
    ;;
esac

for brew_bin in "${GROUNDWORK_BREW_BIN:-}" \
  /opt/homebrew/bin/brew /home/linuxbrew/.linuxbrew/bin/brew /usr/local/bin/brew; do
  [[ -n "$brew_bin" && -x "$brew_bin" ]] && eval "$("$brew_bin" shellenv)" && break
done
unset brew_bin
if ! command -v brew >/dev/null 2>&1; then
  echo "Groundwork: Homebrew is not available, so the set-aside apps were not installed." >&2
  exit 1
fi

deferred_brewfile="$(mktemp "${TMPDIR:-/tmp}/groundwork-sudo-brewfile.XXXXXX")"
chmod 600 "$deferred_brewfile"
for deferred_token in "${deferred_tokens[@]}"; do
  printf 'cask "%s"\n' "$deferred_token" >>"$deferred_brewfile"
done

echo "Groundwork: installing apps set aside until an administrator password was available: ${deferred_tokens[*]}."
export HOMEBREW_NO_ASK=1
user_cask_opts="${HOMEBREW_CASK_OPTS-}"
safe_cask_opts="${user_cask_opts:+$user_cask_opts }--require-sha"
bundle_status=0
HOMEBREW_CASK_OPTS="$safe_cask_opts" \
  HOMEBREW_NO_AUTO_UPDATE=1 \
  brew bundle install --no-upgrade --verbose --file="$deferred_brewfile" \
  || bundle_status=$?
if [[ "$bundle_status" -ne 0 ]]; then
  echo "Groundwork: the set-aside apps were not all installed (exit ${bundle_status})." >&2
  echo "Everything that installed stays installed. From a terminal on this machine, run chezmoi apply and enter your password when asked." >&2
  exit "$bundle_status"
fi

remaining="$(mktemp "${TMPDIR:-/tmp}/groundwork-sudo-remaining.XXXXXX")"
chmod 600 "$remaining"
if [[ -s "$deferred_path" ]]; then
  awk 'NR == FNR { done[$0] = 1; next } !done[$0] { print }' \
    <(printf '%s\n' "${deferred_tokens[@]}") "$deferred_path" >"$remaining"
fi
if [[ -s "$remaining" ]]; then
  mv -f -- "$remaining" "$deferred_path"
  chmod 600 "$deferred_path"
else
  rm -f -- "$remaining" "$deferred_path"
fi
echo "Groundwork: the set-aside apps are installed."
