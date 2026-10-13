#!/bin/sh
case "${1:-}" in
    update)
        echo "copilot update is blocked: this install is managed by pacman (github-copilot-cli-nosarch)." >&2
        echo "Update or remove the package with pacman instead." >&2
        exit 1
        ;;
esac

export COPILOT_AUTO_UPDATE=false
exec /opt/github-copilot-cli-nosarch/copilot "$@"
