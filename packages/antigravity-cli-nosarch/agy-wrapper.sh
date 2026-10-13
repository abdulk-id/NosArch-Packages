#!/bin/sh
case "${1:-}" in
    update)
        echo "agy update is blocked: this install is managed by pacman (antigravity-cli-nosarch)." >&2
        echo "Update or remove the package with pacman instead." >&2
        exit 1
        ;;
esac

export AGY_CLI_DISABLE_AUTO_UPDATE=true
exec /opt/antigravity-cli-nosarch/agy "$@"
