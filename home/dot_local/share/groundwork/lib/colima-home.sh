# shellcheck shell=bash
# Colima 0.10.3 home and profile resolution, shared by groundwork-doctor,
# groundwork-update-run, and groundwork-colima-start. groundwork_colima should
# call gw_colima_child_home and export the printed path for the colima child
# only. This file never
# creates, moves, or deletes a Colima directory or instance.
#
# Home order matches config/files.go: COLIMA_HOME only when that directory
# exists, then ~/.colima when it exists, then $XDG_CONFIG_HOME/colima when
# that variable is set and non-empty. An empty XDG_CONFIG_HOME would make
# Colima look at a relative "colima" directory, so it is treated as unset.
# After that, macOS uses ~/.colima even when the directory is absent. Other
# systems use ${XDG_CONFIG_HOME:-$HOME/.config}/colima, which is what Go's
# os.UserConfigDir returns when XDG_CONFIG_HOME is unset. Profile names match
# config.ProfileFromName: "", "colima", and "default" select instance colima
# and config directory default. Any other name drops one leading "colima-"
# only after that switch, and the --profile flag keeps the original string so
# Colima applies the same rule. LIMA_HOME, when non-empty, replaces the _lima
# directory.

GW_COLIMA_HOME=""
GW_COLIMA_PROFILE=""
GW_COLIMA_PROFILE_SHORT=""
GW_COLIMA_PROFILE_ID=""
GW_COLIMA_LIMA_HOME=""
GW_COLIMA_CONFIG=""
GW_COLIMA_DATADISK=""
# These outputs are consumed by the CLI that sources this library.
# shellcheck disable=SC2034
GW_COLIMA_DISK_SPACE_PATH=""
# shellcheck disable=SC2034
GW_COLIMA_DISK_SPACE_KIB=""

# Print ~/.colima when COLIMA_HOME is unset or empty and that directory
# exists. Otherwise print nothing.
gw_colima_child_home() {
  if [[ -z "${COLIMA_HOME:-}" && -d "${HOME:?}/.colima" ]]; then
    printf '%s\n' "$HOME/.colima"
  fi
}

gw_colima_config_home() {
  local home
  if [[ -n "${COLIMA_HOME:-}" && -d "$COLIMA_HOME" ]]; then
    printf '%s\n' "$COLIMA_HOME"
    return 0
  fi
  home="${HOME:?}/.colima"
  if [[ -d "$home" ]]; then
    printf '%s\n' "$home"
    return 0
  fi
  if [[ -n "${XDG_CONFIG_HOME:-}" ]]; then
    printf '%s\n' "${XDG_CONFIG_HOME%/}/colima"
    return 0
  fi
  if [[ "$(uname -s 2>/dev/null || true)" == "Darwin" ]]; then
    printf '%s\n' "$home"
    return 0
  fi
  printf '%s\n' "${XDG_CONFIG_HOME:-$HOME/.config}/colima"
}

# Reject a value that could expand or break out of the double quotes in the
# recovery command. Spaces stay allowed because they are inside those quotes.
gw_colima_shell_single() {
  local value="$1"
  [[ -n "$value" ]] || return 1
  # The backslash alternative is written as $'\\' so the pattern is one
  # character and the quote does not need an escape.
  case "$value" in
    *'"'* | *$'\\'*) return 1 ;;
    *'`'* | *'!'* | *'$'* | *$'\n'* | *$'\r'*) return 1 ;;
  esac
  return 0
}

# Set the --profile flag, the config directory, and the Lima instance id.
# Return 1 when the short name is not one safe path segment.
gw_colima_apply_profile() {
  local name="${1-}" short
  case "$name" in
    "" | colima | default)
      GW_COLIMA_PROFILE="default"
      GW_COLIMA_PROFILE_SHORT="default"
      GW_COLIMA_PROFILE_ID="colima"
      return 0
      ;;
  esac
  short="$name"
  if [[ "$short" == colima-* ]]; then
    short="${short#colima-}"
  fi
  [[ "$short" =~ ^[A-Za-z0-9._-]+$ ]] || return 1
  [[ "$short" != "." && "$short" != ".." && "$short" != -* ]] || return 1
  GW_COLIMA_PROFILE="$name"
  GW_COLIMA_PROFILE_SHORT="$short"
  GW_COLIMA_PROFILE_ID="colima-$short"
}

gw_colima_resolve() {
  local home
  GW_COLIMA_HOME=""
  GW_COLIMA_PROFILE=""
  GW_COLIMA_PROFILE_SHORT=""
  GW_COLIMA_PROFILE_ID=""
  GW_COLIMA_LIMA_HOME=""
  GW_COLIMA_CONFIG=""
  GW_COLIMA_DATADISK=""
  GW_COLIMA_DISK_SPACE_PATH=""
  GW_COLIMA_DISK_SPACE_KIB=""
  home="$(gw_colima_config_home)"
  [[ -n "$home" ]] || return 1
  gw_colima_apply_profile "${COLIMA_PROFILE:-}" || return 1
  GW_COLIMA_HOME="$home"
  if [[ -n "${LIMA_HOME:-}" ]]; then
    GW_COLIMA_LIMA_HOME="$LIMA_HOME"
  else
    GW_COLIMA_LIMA_HOME="$home/_lima"
  fi
  GW_COLIMA_CONFIG="$home/$GW_COLIMA_PROFILE_SHORT/colima.yaml"
  GW_COLIMA_DATADISK="$GW_COLIMA_LIMA_HOME/_disks/$GW_COLIMA_PROFILE_ID/datadisk"
  return 0
}

# Print the nearest existing directory at or above a future storage path.
# Colima/Lima can create LIMA_HOME on first start, so df must inspect an
# existing ancestor on the same mounted filesystem without creating anything.
gw_colima_existing_directory() {
  local path="${1%/}"
  [[ -n "$path" ]] || path="/"
  case "$path" in
    *$'\n'* | *$'\r'* | *$'\t'*) return 1 ;;
  esac
  while [[ ! -d "$path" ]]; do
    case "$path" in
      */*)
        path="${path%/*}"
        [[ -n "$path" ]] || path="/"
        ;;
      *) path="." ;;
    esac
  done
  printf '%s\n' "$path"
}

# Return 0 when this profile has a config or disk artifact, 1 when it is new,
# and 2 when the profile cannot be resolved safely. A preserved Lima disk is
# existing state even when Colima's instance config has been deleted.
gw_colima_instance_exists() {
  gw_colima_resolve || return 2
  if [[ -e "$GW_COLIMA_CONFIG" || -L "$GW_COLIMA_CONFIG" ||
    -e "$GW_COLIMA_DATADISK" || -L "$GW_COLIMA_DATADISK" ||
    -d "$GW_COLIMA_HOME/$GW_COLIMA_PROFILE_SHORT" ||
    -d "$GW_COLIMA_LIMA_HOME/_disks/$GW_COLIMA_PROFILE_ID" ]]; then
    return 0
  fi
  return 1
}

# Record available 1024-byte blocks for the filesystem that will hold the
# data disk. The probe uses the nearest existing ancestor of LIMA_HOME and
# fails closed if df cannot identify that filesystem.
gw_colima_measure_disk_space() {
  local probe output available
  gw_colima_resolve || return 2
  probe="$(gw_colima_existing_directory "$GW_COLIMA_LIMA_HOME")" || return 2
  [[ -n "$probe" ]] || return 2
  output="$(LC_ALL=C df -kP "$probe")" || return 2
  available="$(printf '%s\n' "$output" | awk 'NR == 2 { print $4; exit }')" || return 2
  [[ "$available" =~ ^[0-9]+$ ]] || return 2
  # shellcheck disable=SC2034
  GW_COLIMA_DISK_SPACE_PATH="$probe"
  # shellcheck disable=SC2034
  GW_COLIMA_DISK_SPACE_KIB="$available"
}

# Return 0 when the resolved profile has disk: 0 or a 0-byte datadisk.
# Return 1 when that instance is absent or has a data disk.
# Return 2 when the home or profile cannot be resolved safely.
gw_colima_instance_lacks_data_disk() {
  gw_colima_resolve || return 2
  if [[ -f "$GW_COLIMA_CONFIG" ]] && grep -qE '^disk:[[:space:]]*0[[:space:]]*(#.*)?$' "$GW_COLIMA_CONFIG"; then
    return 0
  fi
  if [[ -f "$GW_COLIMA_DATADISK" && ! -s "$GW_COLIMA_DATADISK" ]]; then
    return 0
  fi
  return 1
}

# Print the recovery command for the home, profile, and Lima directory just
# resolved. colima delete --force removes the instance and can leave the Lima
# data disk, including a lock that still names that instance. limactl disk
# delete --force removes the disk even when that lock remains. Lima 2.2.1
# ignores a disk that is already gone and exits 0. Any other failure stays
# visible so the && chain stops before groundwork-colima-start. The final
# helper sizes the new disk against the free space on its host volume. Return 1
# instead of printing a command that would expand in another shell.
gw_colima_recovery_command() {
  local one disk start
  gw_colima_resolve || return 1
  gw_colima_shell_single "$GW_COLIMA_HOME" || return 1
  gw_colima_shell_single "$GW_COLIMA_PROFILE" || return 1
  gw_colima_shell_single "$GW_COLIMA_LIMA_HOME" || return 1
  gw_colima_shell_single "$GW_COLIMA_PROFILE_ID" || return 1
  one="LIMA_HOME=\"$GW_COLIMA_LIMA_HOME\" COLIMA_HOME=\"$GW_COLIMA_HOME\" colima --profile=\"$GW_COLIMA_PROFILE\""
  disk="LIMA_HOME=\"$GW_COLIMA_LIMA_HOME\" limactl disk delete --force \"$GW_COLIMA_PROFILE_ID\""
  start="LIMA_HOME=\"$GW_COLIMA_LIMA_HOME\" COLIMA_HOME=\"$GW_COLIMA_HOME\" groundwork-colima-start --profile=\"$GW_COLIMA_PROFILE\""
  printf '%s\n' "${one} delete --force && ${disk} && ${start}"
}
