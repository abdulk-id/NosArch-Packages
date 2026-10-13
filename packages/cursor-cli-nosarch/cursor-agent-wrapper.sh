#!/bin/sh
set -eu

name="$(basename "$0")"
case "$name" in
    agent | cursor-agent) ;;
    *) name=cursor-agent ;;
esac

case "${1:-}" in
    update | upgrade)
        echo "cursor-agent $1 is blocked: this install is managed by pacman (cursor-cli-nosarch)." >&2
        echo "Update or remove the package with pacman instead." >&2
        exit 1
        ;;
esac

versions_dir="${HOME:-}/.local/share/cursor-agent/versions"
mkdir -p "$versions_dir" 2>/dev/null || true
chmod -x "$versions_dir" 2>/dev/null || true

# `static` is upstream's channel for packaged installs: it short-circuits every update path (the TUI's /update, the
# background check after startup, and the update command) before any network call. Best-effort: it only fills the key
# in when the user has not picked a channel with `agent set-channel`, and any failure leaves upstream behaviour intact.
"/opt/cursor-cli-nosarch/node" /usr/lib/cursor-cli-nosarch/pin-channel.js >/dev/null 2>&1 || true

exec "/opt/cursor-cli-nosarch/$name" "$@"
