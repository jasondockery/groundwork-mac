#!/usr/bin/env bash
# bash 3.2+ (stock macOS). Wire groundwork-core's commit identity guard
# (core/docs/commit-identity.md) into this user's git and Claude Code setup.
#
#   commit-identity-install.sh --guard PATH_TO_PINNED_commit-identity-guard.sh
#
# Scope: user-level only. Hooks live in ~/.config/groundwork/git-hooks and call
# the PINNED guard through a symlink; nothing is copied. core.hooksPath is set
# in the XDG git config (~/.config/git/config), which ~/.gitconfig and
# ~/.gitconfig.local override, and only when no hooksPath is set anywhere.
# Every standard client hook name forwards to the repository's own
# .git/hooks/<name>, so setting a global hooksPath does not silence them.
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

# Hook names that forward to the repository's own hooks.
hook_names="applypatch-msg pre-applypatch post-applypatch pre-commit pre-merge-commit prepare-commit-msg commit-msg post-commit pre-rebase post-checkout post-merge post-rewrite pre-push pre-auto-gc"

dispatcher=$(
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
if [ -e "$off_flag" ] || [ "${GROUNDWORK_COMMIT_GUARD:-}" = off ]; then guard_active=0; fi
[ -x "$here/commit-identity-guard.sh" ] || guard_active=0

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
)

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

# core.hooksPath: only when nobody has set one.
cwd_safe="$(mktemp -d)"
trap 'rmdir "$cwd_safe" 2>/dev/null || true' EXIT
current="$(cd "$cwd_safe" && git config --get core.hooksPath 2>/dev/null || true)"
if [[ -z "$current" ]]; then
  mkdir -p "$(dirname "$xdg_git")"
  git config --file "$xdg_git" core.hooksPath "$hooks"
  changed=1
  say "set core.hooksPath to $hooks in $xdg_git (applies to every repo; opt out with: touch $off_flag)."
elif [[ "$current" != "$hooks" ]]; then
  say "core.hooksPath is already set to $current; left alone, so the guard hooks are not active. Chain $hooks/commit-msg and $hooks/pre-push from it to use them."
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
  say "installed. Run 'groundwork-doctor --commit-identity' to check."
fi
