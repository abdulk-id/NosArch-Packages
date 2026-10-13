#!/bin/sh
if [ "${1:-}" = "update" ]; then
    # Scan a copy of the arguments ($@ is left untouched for the exec below).
    wants_self=0
    user_target=0
    help=0
    expect_value=0
    first=1
    for arg in "$@"; do
        if [ "$first" -eq 1 ]; then
            first=0 # the `update` word itself, which decides nothing
            continue
        fi
        if [ "$expect_value" -eq 1 ]; then
            # The value of --extension is a package source, so `pi update --extension self`
            # updates an extension named self rather than Pi.
            expect_value=0
            user_target=1
            continue
        fi
        case "$arg" in
            -h|--help)
                help=1
                ;;
            --extensions|--models)
                user_target=1
                ;;
            --extension)
                expect_value=1
                user_target=1
                ;;
            --extension=*)
                user_target=1
                ;;
            --self|--all)
                wants_self=1
                ;;
            -*)
                # Trust/force flags do not change which target the update selects.
                ;;
            self|pi)
                wants_self=1
                ;;
            *)
                user_target=1
                ;;
        esac
    done

    if [ "$help" -eq 0 ] && { [ "$wants_self" -eq 1 ] || [ "$user_target" -eq 0 ]; }; then
        echo "pi update is blocked: this install is managed by pacman (pi-nosarch)." >&2
        echo "Update or remove the package with pacman instead." >&2
        echo "Updates confined to ~/.pi still work: pi update --extensions, --models, <source>." >&2
        exit 1
    fi
fi
exec /opt/pi-nosarch/pi "$@"
