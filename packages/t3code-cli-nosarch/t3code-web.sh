#!/bin/sh
# Control the official T3 Code background service and open the web UI.
# Never spawns a bare `t3 start`. It stacks processes with no stop path.

set -eu

unit=t3code.service
runtime="${T3CODE_HOME:-$HOME/.t3}/userdata/server-runtime.json"

notify() {
    msg=$1
    if command -v notify-send >/dev/null 2>&1; then
        notify-send -u critical "T3 Code" "$msg" 2>/dev/null || echo "$msg" >&2
    else
        echo "$msg" >&2
    fi
}

# Prints origin if a live server (service, desktop app, or anything) wrote
# server-runtime.json and its pid is still alive.
live_origin() {
    [ -f "$runtime" ] || return 1
    pid=$(sed -n 's/.*"pid":[[:space:]]*\([0-9][0-9]*\).*/\1/p' "$runtime")
    origin=$(sed -n 's/.*"origin":"\([^"]*\)".*/\1/p' "$runtime")
    [ -n "${pid:-}" ] && [ -n "${origin:-}" ] || return 1
    kill -0 "$pid" 2>/dev/null || return 1
    printf '%s\n' "$origin"
}

wait_for_origin() {
    i=0
    while [ "$i" -lt 50 ]; do
        if origin=$(live_origin); then
            return 0
        fi
        i=$((i + 1))
        sleep 0.1
    done
    return 1
}

open_ui() {
    origin=$(live_origin) || {
        notify "T3 Code server is not running. Use the Start T3 Code Service menu entry."
        exit 1
    }
    exec xdg-open "$origin"
}

start_service() {
    if ! systemctl --user start "$unit" 2>/dev/null; then
        systemctl --user daemon-reload
        systemctl --user reset-failed "$unit" 2>/dev/null || true
        if ! systemctl --user start "$unit" 2>/dev/null; then
            notify "t3code.service is not installed. Run: t3 service install"
            exit 1
        fi
    fi
    if wait_for_origin; then
        exec xdg-open "$origin"
    fi
    notify "T3 Code service started but no server appeared yet. Check: t3 service status"
    exit 1
}

stop_service() {
    if ! systemctl --user stop "$unit" 2>/dev/null; then
        notify "t3code.service is not installed or not loaded. Run: t3 service install"
        exit 1
    fi
}

status_service() {
    exec systemctl --user status "$unit"
}

case "${1:-open}" in
    open|"")
        open_ui
        ;;
    start)
        start_service
        ;;
    stop)
        stop_service
        ;;
    status)
        status_service
        ;;
    *)
        echo "usage: t3code-web [open|start|stop|status]" >&2
        exit 2
        ;;
esac
