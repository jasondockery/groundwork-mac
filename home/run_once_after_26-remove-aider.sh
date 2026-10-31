#!/usr/bin/env bash
set -euo pipefail

# Groundwork no longer ships Aider. Earlier versions installed it as a uv tool,
# so remove only that tool environment, once. chezmoi records this script's
# content hash after it succeeds, so an Aider the user reinstalls later is
# left alone. User config such as ~/.aider* is never touched; it is safe to
# delete by hand.

for _brew in /opt/homebrew/bin/brew /home/linuxbrew/.linuxbrew/bin/brew /usr/local/bin/brew; do
  [[ -x "$_brew" ]] && eval "$("$_brew" shellenv)" && break
done
unset _brew
export PATH="$HOME/.local/bin:$PATH"

command -v uv >/dev/null 2>&1 || exit 0

if uv tool list 2>/dev/null | grep -Eq '^aider-chat([[:space:]]|$)'; then
  echo "Removing aider-chat (installed by an earlier Groundwork version)..."
  if uv tool uninstall aider-chat; then
    echo "Removed aider-chat. Leftover ~/.aider* files are yours; delete them by hand if unused."
  else
    echo "Could not remove aider-chat; run: uv tool uninstall aider-chat" >&2
  fi
fi
