#!/bin/sh
if [ "${1:-}" = "update" ]; then
    for arg in "$@"; do
        case "$arg" in
            -l|--plugins)
                exec /opt/omp-nosarch/omp "$@"
                ;;
        esac
    done
    echo "omp update is blocked: this install is managed by pacman (omp-nosarch)." >&2
    echo "Update or remove the package with pacman instead." >&2
    echo "Plugins can be updated with: omp update --plugins." >&2
    exit 1
fi
exec /opt/omp-nosarch/omp "$@"
