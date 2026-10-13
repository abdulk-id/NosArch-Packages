#!/bin/sh
# Point the app at this package's agent instead of letting it bootstrap a private
# Hermes tree into $HOME, which would be a second, unmanaged install.
HERMES_DESKTOP_HERMES="${HERMES_DESKTOP_HERMES:-/usr/bin/hermes}"
HERMES_DESKTOP_IS_PACKAGED=1
export HERMES_DESKTOP_HERMES HERMES_DESKTOP_IS_PACKAGED

if [ -z "${AGENT_BROWSER_EXECUTABLE_PATH:-}" ]; then
    for browser in google-chrome-stable google-chrome chromium; do
        if path=$(type -P "$browser"); then
            AGENT_BROWSER_EXECUTABLE_PATH="$path"
            export AGENT_BROWSER_EXECUTABLE_PATH
            break
        fi
    done
fi

exec /opt/hermes-agent-nosarch/libexec/hermes desktop --skip-build "$@"
