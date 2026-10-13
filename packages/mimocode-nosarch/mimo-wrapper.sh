#!/bin/sh
case "${1:-}" in
    upgrade|uninstall)
        echo "mimo $1 is blocked: this install is managed by pacman (mimocode-nosarch)." >&2
        echo "Upgrade or remove the package with pacman instead." >&2
        exit 1
        ;;
esac
exec /opt/mimocode-nosarch/mimo "$@"
