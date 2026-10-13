#!/bin/sh
case "${1:-}" in
    update|uninstall)
        echo "t3 $1 is blocked: this install is managed by pacman (t3code-cli-nosarch)." >&2
        echo "Update or remove the package with pacman instead." >&2
        exit 1
        ;;
esac
exec /opt/t3code-cli-nosarch/t3 "$@"
