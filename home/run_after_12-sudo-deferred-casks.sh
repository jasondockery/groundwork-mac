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
mas_deferred_path="$(groundwork_sudo_mas_deferred_path)"
if [[ ! -e "$deferred_path" && ! -L "$deferred_path" && ! -e "$mas_deferred_path" && ! -L "$mas_deferred_path" ]]; then
  exit 0
fi
if [[ -L "$deferred_path" || (-e "$deferred_path" && ! -f "$deferred_path") ||
  -L "$mas_deferred_path" || (-e "$mas_deferred_path" && ! -f "$mas_deferred_path") ]]; then
  echo "Groundwork: the set-aside app list is not a regular file: $deferred_path" >&2
  exit 1
fi

work_dir="$(mktemp -d "${TMPDIR:-/tmp}/groundwork-sudo-retry.XXXXXX")"
cleanup() {
  groundwork_sudo_keepalive_stop
  rm -rf -- "$work_dir"
}
trap cleanup EXIT

if ! groundwork_sudo_read_deferred "$deferred_path" >"$work_dir/saved"; then
  echo "Groundwork: the set-aside app list is malformed, so nothing was installed." >&2
  exit 1
fi
manifest="$HOME/.config/homebrew/Brewfile"
if [[ ! -f "$manifest" || -L "$manifest" ]] \
  || ! groundwork_brewfile_casks "$manifest" >"$work_dir/desired"; then
  echo "Groundwork: the current Brewfile is unavailable or malformed; set-aside apps were preserved." >&2
  exit 1
fi
: >"$work_dir/excluded"
while IFS= read -r token; do
  [[ -n "$token" ]] || continue
  if [[ ! "$token" =~ ^[A-Za-z0-9@+._-]+$ ]]; then
    echo "Groundwork: the current cask exclusion is malformed; nothing was installed." >&2
    exit 64
  fi
  printf '%s\n' "$token" >>"$work_dir/excluded"
done <<<"${GROUNDWORK_BREWFILE_SKIP_CASKS:-}"
awk -v desired="$work_dir/desired" -v excluded="$work_dir/excluded" '
  BEGIN {
    while ((getline token < desired) > 0) wanted[token] = 1
    while ((getline token < excluded) > 0) blocked[token] = 1
  }
  wanted[$0] && !blocked[$0] && !seen[$0]++ { print }
' "$work_dir/saved" >"$work_dir/selected"
for brew_bin in "${GROUNDWORK_BREW_BIN:-}" \
  /opt/homebrew/bin/brew /home/linuxbrew/.linuxbrew/bin/brew /usr/local/bin/brew; do
  [[ -n "$brew_bin" && -x "$brew_bin" ]] && eval "$("$brew_bin" shellenv)" && break
done
unset brew_bin
if ! command -v brew >/dev/null 2>&1; then
  echo "Groundwork: Homebrew is not available, so the set-aside apps were not installed." >&2
  exit 1
fi

if ! groundwork_pending_casks "$work_dir/selected" >"$work_dir/pending"; then
  echo "Groundwork: installed app inventory failed; set-aside apps were preserved." >&2
  exit 1
fi
mv -f -- "$work_dir/pending" "$work_dir/selected"
if ! groundwork_pending_mas_entries "$manifest" >"$work_dir/current-mas"; then
  echo "Groundwork: App Store inventory failed; retry state was preserved." >&2
  exit 1
fi
: >"$work_dir/selected-mas"
if [[ -f "$mas_deferred_path" ]]; then
  if ! awk '$0 !~ /^mas "[^"\t]+", id: [0-9]+[[:space:]]*(#.*)?$/ { exit 1 }' "$mas_deferred_path"; then
    echo "Groundwork: App Store retry state is malformed; no installation was attempted." >&2
    exit 1
  fi
  awk -v saved="$mas_deferred_path" 'BEGIN { while ((getline row < saved) > 0) wanted[row] = 1 } wanted[$0]' \
    "$work_dir/current-mas" >"$work_dir/selected-mas"
fi
if [[ ! -s "$work_dir/selected" && ! -s "$work_dir/selected-mas" ]]; then
  rm -f -- "$deferred_path" "$mas_deferred_path"
  echo "Groundwork: no set-aside apps remain selected by the current setup."
  exit 0
fi
# Historical retry state never grants permission to install a removed app.
# Reconcile before prompting, and retain selected tokens after any failure.
staging="$(mktemp "${deferred_path}.XXXXXX")"
chmod 600 "$staging"
cat "$work_dir/selected" >"$staging"
mv -f -- "$staging" "$deferred_path"
if [[ -s "$work_dir/selected-mas" ]]; then
  staging="$(mktemp "${mas_deferred_path}.XXXXXX")"
  chmod 600 "$staging"
  cat "$work_dir/selected-mas" >"$staging"
  mv -f -- "$staging" "$mas_deferred_path"
else
  rm -f -- "$mas_deferred_path"
fi
deferred_tokens=()
while IFS= read -r token; do
  deferred_tokens+=("$token")
done <"$work_dir/selected"

sudo_prepare_status=0
groundwork_sudo_prepare || sudo_prepare_status=$?
case "$sudo_prepare_status" in
  0) ;;
  10)
    echo "Groundwork: set-aside cask or App Store installations still need an administrator password: ${deferred_tokens[*]-}."
    echo "Their installation or ownership reconciliation is pending. From a terminal on this machine, run chezmoi apply and enter your password when asked."
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

deferred_brewfile="$work_dir/Brewfile"
: >"$deferred_brewfile"
chmod 600 "$deferred_brewfile"
if [[ -s "$work_dir/selected" ]]; then
  for deferred_token in "${deferred_tokens[@]}"; do
    printf 'cask "%s"\n' "$deferred_token" >>"$deferred_brewfile"
  done
fi

cat "$work_dir/selected-mas" >>"$deferred_brewfile"

echo "Groundwork: installing apps set aside until an administrator password was available: ${deferred_tokens[*]-}."
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

groundwork_check_xcode_license

remaining="$work_dir/remaining"
: >"$remaining"
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
rm -f -- "$mas_deferred_path"
echo "Groundwork: the set-aside apps are installed."
