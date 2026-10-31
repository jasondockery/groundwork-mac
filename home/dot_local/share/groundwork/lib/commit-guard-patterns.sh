# shellcheck shell=bash
# bash 3.2+ (stock macOS). Read groundwork-core's owner remote pattern list
# (core/commit-guard/owner-remote-patterns). The commit guard installer and
# groundwork-doctor share this check, so they agree on what is broken.
#
# gw_owner_patterns_read FILE
#   Valid: prints each pattern (<owner> not yet expanded), one per line, and
#   returns 0. Missing, unreadable, empty, or comment-only list, or a line
#   without <owner> (which would guard repositories this user does not own):
#   prints the problem and returns 1.
gw_owner_patterns_read() {
  local file="$1" pattern patterns="" count=0
  if [[ ! -f "$file" || ! -r "$file" ]]; then
    printf 'the owner remote pattern list is missing (%s)\n' "$file"
    return 1
  fi
  while IFS= read -r pattern || [[ -n "$pattern" ]]; do
    case "$pattern" in '' | '#'*) continue ;; esac
    if [[ "$pattern" != *"<owner>"* ]]; then
      printf 'a pattern line in %s has no <owner>: %s\n' "$file" "$pattern"
      return 1
    fi
    patterns+="$pattern"$'\n'
    count=$((count + 1))
  done <"$file"
  if [[ "$count" -eq 0 ]]; then
    printf 'the owner remote pattern list is empty or only comments (%s)\n' "$file"
    return 1
  fi
  printf '%s' "$patterns"
}
