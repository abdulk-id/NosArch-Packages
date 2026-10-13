#!/bin/sh
case "${1:-}" in
    update | upgrade | install)
        echo "claude $1 is blocked: this install is managed by pacman (claude-code-nosarch)." >&2
        echo "Update or remove the package with pacman instead." >&2
        exit 1
        ;;
esac

export DISABLE_UPDATES=1
exec /opt/claude-code-nosarch/claude "$@"
