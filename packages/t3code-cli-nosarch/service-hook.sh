#!/bin/sh
# Pacman hook helper for t3code-cli-nosarch.
# Usage: service-hook.sh install|uninstall

set -u

mode=${1:-}
case "$mode" in
    install|uninstall) ;;
    *)
        echo "usage: service-hook.sh install|uninstall" >&2
        exit 2
        ;;
esac

human_users() {
    # UID >= 1000, home under /home or /var/home (NosArch is single-user; this still
    # covers extra local accounts without touching system/root).
    getent passwd | awk -F: '$3 >= 1000 && $6 ~ /^\/(var\/)?home\// { print $1 }'
}

run_as_user() {
    user=$1
    shift
    uid=$(id -u "$user" 2>/dev/null) || return 1
    home=$(getent passwd "$user" | cut -d: -f6)
    [ -n "$home" ] || return 1

    # systemctl --user needs the runtime dir; linger keeps user@.service alive
    # after logout so install works from a pacman session.
    loginctl enable-linger --no-ask-password "$user" 2>/dev/null || true

    runuser -u "$user" -- env \
        HOME="$home" \
        USER="$user" \
        LOGNAME="$user" \
        XDG_RUNTIME_DIR="/run/user/$uid" \
        PATH="/usr/local/bin:/usr/bin:/bin" \
        t3 service "$mode"
}

status=0
found=0
for user in $(human_users); do
    found=1
    echo "t3code-cli-nosarch: t3 service $mode for $user"
    if ! run_as_user "$user"; then
        echo "t3code-cli-nosarch: t3 service $mode failed for $user (network required on first install)" >&2
        status=1
    fi
done

if [ "$found" -eq 0 ]; then
    echo "t3code-cli-nosarch: no human users found; skipping t3 service $mode"
fi

# Never fail the pacman transaction (PostTransaction ignores exit status anyway;
# PreTransaction without AbortOnFail only reports).
exit 0
