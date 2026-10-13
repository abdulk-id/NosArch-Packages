#!/bin/sh
case "${1:-}" in
    update|uninstall)
        echo "devin $1 is blocked: this install is managed by pacman (devin-cli-nosarch)." >&2
        echo "Upgrade or remove the package with pacman instead." >&2
        exit 1
        ;;
esac
exec /opt/devin-cli-nosarch/bin/devin "$@"
