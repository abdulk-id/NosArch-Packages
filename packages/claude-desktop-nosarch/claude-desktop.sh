#!/bin/bash
# Launcher for Claude Desktop.
set -euo pipefail

# Flags can be placed in $XDG_CONFIG_HOME/claude-desktop-flags.conf (default ~/.config/claude-desktop-flags.conf),
# one or more per line
user_flags=()
config_home="${XDG_CONFIG_HOME:-}"
[[ -n "$config_home" || -z "${HOME:-}" ]] || config_home="$HOME/.config"
flags_file="${config_home:+$config_home/claude-desktop-flags.conf}"

if [[ -n "$flags_file" && -f "$flags_file" && -r "$flags_file" ]]; then
    while IFS= read -r line || [[ -n "$line" ]]; do
        line="${line%%#*}"
        [[ -n "${line//[[:space:]]/}" ]] || continue

        read -r -a flags <<<"$line"

        user_flags+=("${flags[@]}")
    done <"$flags_file"
fi

# Electron does not pick a display backend on its own. Without an Ozone switch it runs under X11, which on a Wayland
# compositor means XWayland and a blurry window on any scaled display. When a Wayland session is detected, request the
# Wayland backend explicitly.
platform=()
if [[ -n ${WAYLAND_DISPLAY:-} || ${XDG_SESSION_TYPE:-} == wayland ]]; then
    platform=(--ozone-platform=wayland)
    for flag in "${user_flags[@]}" "$@"; do
        case $flag in
            --ozone-platform=* | --ozone-platform-hint=*) platform=() ;;
        esac
    done
fi

# A platform switch given by the user (in the flags file) wins.
exec /usr/lib/claude-desktop/claude-desktop "${platform[@]}" "${user_flags[@]}" "$@"
