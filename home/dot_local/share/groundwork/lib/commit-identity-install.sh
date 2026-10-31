#!/usr/bin/env bash
# bash 3.2+ (stock macOS). Wire groundwork-core's commit identity guard
# (core/docs/commit-identity.md) into this user's git and Claude Code setup.
#
#   commit-identity-install.sh --guard PATH_TO_PINNED_commit-identity-guard.sh
#
# Scope: user-level hooks, active only in repositories this user owns. Hooks
# live in ~/.config/groundwork/git-hooks and call the PINNED guard through a
# symlink; nothing is copied. core.hooksPath is NOT set globally. It is set in
# ~/.config/groundwork/commit-guard.gitconfig, which the XDG git config
# (~/.config/git/config) includes through includeIf "hasconfig:remote.*.url:"
# for the owner's GitHub URL forms, any scp-style host alias such as
# git@github-personal:owner/repo, and any ssh:// host, alias, or port such as
# ssh://git@ssh.github.com:443/owner/repo (git 2.36+). The patterns come from
# core/commit-guard/owner-remote-patterns. URLs with userinfo
# (https://user@github.com/...) are not matched. Work repositories are untouched.
# If the user already sets core.hooksPath anywhere, nothing is written.
# Gaps: a push straight to an owned URL from a repo with no owned remote, and
# owned repos with their own local core.hooksPath (husky, lefthook), are not guarded.
#
# Opt out: create ~/.config/groundwork/commit-guard-off (a runtime check in
# the hooks, and a skip here), or set GROUNDWORK_COMMIT_GUARD=off for one command.
# Idempotent: a rerun that finds everything in place prints nothing.
set -euo pipefail

guard=""
while (($#)); do
  case "$1" in
    --guard)
      guard="${2:-}"
      shift 2 || true
      ;;
    *)
      echo "usage: commit-identity-install.sh --guard PATH" >&2
      exit 64
      ;;
  esac
done
if [[ -z "$guard" ]]; then
  echo "usage: commit-identity-install.sh --guard PATH" >&2
  exit 64
fi

cfg="${XDG_CONFIG_HOME:-$HOME/.config}"
gw="$cfg/groundwork"
hooks="$gw/git-hooks"
off_flag="$gw/commit-guard-off"
denylist="${GROUNDWORK_COMMIT_DENYLIST:-$gw/commit-denylist}"
xdg_git="$cfg/git/config"
claude_settings="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/settings.json"

say() { printf 'Groundwork commit identity guard: %s\n' "$*"; }

if [[ -e "$off_flag" ]]; then
  say "opted out ($off_flag exists); nothing installed or changed."
  exit 0
fi
if [[ ! -f "$guard" ]]; then
  say "$guard is not in this checkout (is the core submodule checked out?); skipped."
  exit 0
fi

# The owner-scoped remote URL patterns come only from the pinned core, next to
# the guard (core/commit-guard/owner-remote-patterns). Read and check them
# before anything is written. A broken list leaves the guard inactive, the same
# outcome as a missing guard, so it is a loud skip that writes nothing, not a
# failed apply. groundwork-doctor --commit-identity reports it as a failure.
patterns_lib="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/commit-guard-patterns.sh"
# shellcheck source=home/dot_local/share/groundwork/lib/commit-guard-patterns.sh
. "$patterns_lib"
patterns_file="$(dirname "$guard")/owner-remote-patterns"
if ! raw_patterns="$(gw_owner_patterns_read "$patterns_file")"; then
  if [[ -e "$hooks/commit-identity-guard.sh" || -L "$hooks/commit-identity-guard.sh" ]]; then
    state="the earlier install in $hooks was left exactly as it was and was NOT updated"
  else
    state="the commit identity guard is NOT active"
  fi
  {
    echo "Groundwork commit identity guard: WARNING: $raw_patterns."
    echo "Groundwork commit identity guard: nothing was installed or changed; $state."
    echo "Groundwork commit identity guard: update the core submodule (git submodule update --init core), then run groundwork-update. groundwork-doctor --commit-identity reports this."
  } >&2
  exit 0
fi
owner="jasondockery"
owner_glob=""
for ((i = 0; i < ${#owner}; i++)); do
  ch="${owner:i:1}"
  upper="$(printf '%s' "$ch" | tr '[:lower:]' '[:upper:]')"
  if [[ "$upper" == "$ch" ]]; then owner_glob+="$ch"; else owner_glob+="[$ch$upper]"; fi
done
owner_patterns=()
while IFS= read -r pattern; do
  owner_patterns+=("${pattern//<owner>/$owner_glob}")
done <<<"$raw_patterns"

# Hook names that forward to the repository's own hooks.
hook_names="applypatch-msg pre-applypatch post-applypatch pre-commit pre-merge-commit prepare-commit-msg commit-msg post-commit pre-rebase post-checkout post-merge post-rewrite pre-push pre-auto-gc reference-transaction push-to-checkout sendemail-validate fsmonitor-watchman post-index-change p4-changelist p4-prepare-changelist p4-post-changelist p4-pre-submit pre-receive update proc-receive post-receive post-update"

# The text lives in a function, not in a heredoc inside $( ): stock macOS
# bash 3.2 ends a command substitution at the first case pattern's ")" even
# inside a quoted heredoc, so the hook body ran in the installer instead.
dispatcher_text() {
  cat <<'DISPATCH'
#!/usr/bin/env bash
# Managed by Groundwork (commit-identity-install.sh). Runs the pinned commit
# identity guard for commit-msg and pre-push, then the repository's own hook.
name="$(basename "$0")"
here="$(cd "$(dirname "$0")" && pwd)"
off_flag="${XDG_CONFIG_HOME:-$HOME/.config}/groundwork/commit-guard-off"
stdin_copy=""
trap '[ -n "$stdin_copy" ] && rm -f "$stdin_copy"' EXIT

guard_active=1
if [ -e "$off_flag" ] || [ "${GROUNDWORK_COMMIT_GUARD:-}" = off ]; then
  guard_active=0
elif [ ! -x "$here/commit-identity-guard.sh" ]; then
  guard_active=0
  echo "Groundwork: the pinned commit identity guard is missing ($here/commit-identity-guard.sh); skipping it. Run groundwork-update." >&2
fi

if [ "$guard_active" = 1 ]; then
  case "$name" in
    commit-msg)
      "$here/commit-identity-guard.sh" commit-msg "$@" || rc=$?
      ;;
    pre-push)
      stdin_copy="$(mktemp)"
      cat >"$stdin_copy"
      "$here/commit-identity-guard.sh" pre-push "$@" <"$stdin_copy" || rc=$?
      ;;
  esac
  if [ "${rc:-0}" != 0 ]; then
    {
      echo "Groundwork blocked this $name. Fix the message or identity, or opt out:"
      echo "  one command:  GROUNDWORK_COMMIT_GUARD=off git ..."
      echo "  everywhere:   touch \"$off_flag\""
    } >&2
    exit "$rc"
  fi
fi

common="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || exit 0
local_hook="$common/hooks/$name"
[ -x "$local_hook" ] && [ -f "$local_hook" ] || exit 0
if [ "$(cd "$(dirname "$local_hook")" && pwd -P)/$name" = "$(cd "$here" && pwd -P)/$name" ]; then exit 0; fi
if [ -n "$stdin_copy" ]; then
  "$local_hook" "$@" <"$stdin_copy"
else
  exec "$local_hook" "$@"
fi
DISPATCH
}
dispatcher="$(dispatcher_text)"

changed=0

mkdir -p "$hooks"

# Dispatcher: rewrite only when the content differs.
if [[ "$(cat "$hooks/dispatch" 2>/dev/null || true)" != "$dispatcher" ]]; then
  printf '%s\n' "$dispatcher" >"$hooks/dispatch"
  changed=1
fi
[[ -x "$hooks/dispatch" ]] || chmod 755 "$hooks/dispatch"

# Pinned guard: a symlink, repointed when the pin moves.
if [[ "$(readlink "$hooks/commit-identity-guard.sh" 2>/dev/null || true)" != "$guard" ]]; then
  ln -sfn "$guard" "$hooks/commit-identity-guard.sh"
  changed=1
fi

for hook in $hook_names; do
  if [[ "$(readlink "$hooks/$hook" 2>/dev/null || true)" != "dispatch" ]]; then
    ln -sfn dispatch "$hooks/$hook"
    changed=1
  fi
done

# core.hooksPath, scoped to repositories with an owned GitHub remote; the
# patterns were read and validated before anything was written.
include_file="$gw/commit-guard.gitconfig"
cwd_safe="$(mktemp -d)"
trap 'rmdir "$cwd_safe" 2>/dev/null || true' EXIT
git_version="$(git --version 2>/dev/null | sed -n 's/^git version \([0-9][0-9]*\)\.\([0-9][0-9]*\).*/\1 \2/p')"
git_major="${git_version%% *}"
git_minor="${git_version##* }"
# Undo a global hooksPath an earlier version of this installer wrote.
if [[ -f "$xdg_git" && "$(git config --file "$xdg_git" --get core.hooksPath 2>/dev/null || true)" == "$hooks" ]]; then
  git config --file "$xdg_git" --unset core.hooksPath
  changed=1
fi
current="$(cd "$cwd_safe" && git config --get core.hooksPath 2>/dev/null || true)"
if [[ -z "$git_version" ]] || ((git_major < 2 || (git_major == 2 && git_minor < 36))); then
  say "git 2.36 or newer is needed to scope the hooks to your repositories (includeIf hasconfig); skipped hook activation."
elif [[ -n "$current" ]]; then
  say "core.hooksPath is already set to $current; left alone, so the guard hooks are not active. Chain $hooks/commit-msg and $hooks/pre-push from it to use them."
else
  include_text="[core]
	hooksPath = $hooks"
  if [[ "$(cat "$include_file" 2>/dev/null || true)" != "$include_text" ]]; then
    printf '%s\n' "$include_text" >"$include_file"
    changed=1
  fi
  mkdir -p "$(dirname "$xdg_git")"
  for url in "${owner_patterns[@]}"; do
    key="includeIf.hasconfig:remote.*.url:$url.path"
    if [[ "$(git config --file "$xdg_git" --get "$key" 2>/dev/null || true)" != "$include_file" ]]; then
      git config --file "$xdg_git" "$key" "$include_file"
      changed=1
    fi
  done
fi

# Denylist: an empty file only when missing; the repo never supplies values.
if [[ ! -e "$denylist" ]]; then
  mkdir -p "$(dirname "$denylist")"
  : >"$denylist"
  changed=1
  say "created an empty denylist at $denylist (one case-insensitive substring per line)."
fi

# Claude Code attribution: fill in only the keys the user has not set.
if command -v python3 >/dev/null 2>&1; then
  result="$(
    python3 -I - "$claude_settings" <<'PY'
import json, os, shutil, sys, tempfile

path = sys.argv[1]
real = os.path.realpath(path)
doc = {}
if os.path.exists(real):
    try:
        with open(real, encoding="utf-8") as handle:
            doc = json.load(handle)
    except (OSError, ValueError):
        print("invalid")
        sys.exit(0)
    if not isinstance(doc, dict):
        print("invalid")
        sys.exit(0)
attribution = doc.get("attribution", {})
if not isinstance(attribution, dict):
    print("kept")
    sys.exit(0)
missing = [key for key in ("commit", "pr") if key not in attribution]
if not missing:
    print("kept")
    sys.exit(0)
for key in missing:
    attribution[key] = ""
doc["attribution"] = attribution
parent = os.path.dirname(real)
os.makedirs(parent, exist_ok=True)
if os.path.exists(real):
    n = 1
    while os.path.exists("%s.bak.%d" % (real, n)):
        n += 1
    shutil.copy2(real, "%s.bak.%d" % (real, n))
fd, tmp = tempfile.mkstemp(dir=parent, prefix=".settings.")
with os.fdopen(fd, "w", encoding="utf-8") as handle:
    json.dump(doc, handle, indent=2, ensure_ascii=False)
    handle.write("\n")
if os.path.exists(real):
    shutil.copymode(real, tmp)
os.replace(tmp, real)
print("wrote " + ",".join(missing))
PY
  )" || result="error"
  case "$result" in
    wrote*)
      changed=1
      say "set Claude Code attribution (${result#wrote }) to empty in $claude_settings; a numbered .bak.N copy was kept if the file existed."
      ;;
    invalid)
      say "$claude_settings is not a JSON object; left untouched. Set \"attribution\": {\"commit\": \"\", \"pr\": \"\"} yourself."
      ;;
    error)
      say "could not update $claude_settings; left untouched."
      ;;
  esac
else
  say "python3 is not available; skipped Claude Code attribution settings."
fi

if [[ "$changed" = 1 ]]; then
  say "installed; active in repositories with a remote under github.com/$owner. Run 'groundwork-doctor --commit-identity' to check."
fi
