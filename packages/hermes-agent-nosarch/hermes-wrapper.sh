#!/bin/sh
case "${1:-}" in
    update|uninstall)
        echo "hermes $1 is blocked: this install is managed by pacman (hermes-agent-nosarch)." >&2
        echo "Upgrade or remove the package with pacman instead." >&2
        exit 1
        ;;
esac
exec /opt/hermes-agent-nosarch/libexec/hermes "$@"
