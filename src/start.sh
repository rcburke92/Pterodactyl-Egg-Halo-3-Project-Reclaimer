#!/bin/bash
# Project Reclaimer (Halo 3) dedicated server: Pterodactyl start script.
# Written into the server folder by the egg's installer; reinstalling the
# server rewrites it. Mirrors the official Docker image's entrypoint:
#   1. make the Wine prefix (first start only)
#   2. make the server folder with `dedicated init` (first start only)
#   3. point the first [[server]] at this server's Pterodactyl allocation
#   4. wait until `dedicated check` passes, then run the servers
set -euo pipefail
SERVER_DIR=${HOME:-/home/container}
cd "$SERVER_DIR"

EXE="$SERVER_DIR/project-reclaimer.exe"
CHECK_INTERVAL=15

say() { printf '[egg] %s\n' "$*"; }
fail() {
    say "Error: $*"
    exit 1
}

[ -f "$EXE" ] || fail "$EXE is missing. Reinstall the server from the panel's Settings tab."

# The yolk's entrypoint starts Xvfb on :0 when XVFB=1.
if [ "${XVFB:-1}" != 1 ]; then
    unset DISPLAY
fi

# 1. Wine prefix. No audio driver: the servers play no sound, and without
# a sound card Wine's ALSA driver fills the log with errors.
if [ ! -f "$WINEPREFIX/system.reg" ]; then
    say "Creating the Wine prefix in $WINEPREFIX (first start only)..."
    WINEARCH=win64 wineboot --init > .wine-init.log 2>&1 || {
        cat .wine-init.log
        fail "wineboot failed"
    }
    wine reg add 'HKCU\Software\Wine\Drivers' /v Audio /t REG_SZ /f >> .wine-init.log 2>&1 || true
    wineserver --wait
fi

# 2. Server folder: a commented dedicated.toml, playlists/, content/,
# bans.json and data/. Never touches an existing dedicated.toml.
if [ ! -f dedicated.toml ]; then
    say "No dedicated.toml yet: creating the server folder..."
    wine "$EXE" dedicated init .
    say "Created dedicated.toml. Edit it in the File Manager to name the server and pick maps or a playlist."
fi

# 3. The first [[server]] block's port follows the primary allocation, so
# players reach it through the port Pterodactyl forwards. Other [[server]]
# blocks are left alone: give each its own allocation and port by hand.
if [ "${EGG_SYNC_PORT:-1}" = 1 ] && [ -n "${SERVER_PORT:-}" ]; then
    awk -v port="$SERVER_PORT" '
        function finish() {
            if (in_first && !done) { print "port = " port; done = 1 }
            in_first = 0
        }
        /^[[:space:]]*\[\[[[:space:]]*server[[:space:]]*\]\]/ {
            finish()
            blocks++
            print
            if (blocks == 1) in_first = 1
            next
        }
        /^[[:space:]]*\[/ { finish(); print; next }
        in_first && /^[[:space:]]*port[[:space:]]*=/ {
            if (!done) { print "port = " port; done = 1 }
            next
        }
        { print }
        END { finish() }
    ' dedicated.toml > .dedicated.toml.egg
    if cmp -s dedicated.toml .dedicated.toml.egg; then
        rm -f .dedicated.toml.egg
    else
        cat .dedicated.toml.egg > dedicated.toml
        rm -f .dedicated.toml.egg
        say "Set the first [[server]]'s port in dedicated.toml to $SERVER_PORT (this server's allocation)."
    fi
fi

# 4. Wait for the game files and settings to check out. Upload Halo 3's
# files into game/ over SFTP while this waits; no restart needed.
last=""
while ! report=$(wine "$EXE" dedicated check 2>&1); do
    if [ "$report" != "$last" ]; then
        printf '%s\n\n' "$report"
        say "Waiting for 'dedicated check' to pass. Fix the above in the File Manager or over SFTP."
        say "Halo 3's files go in game/ (game/halo3/halo3.dll, game/halo3/maps/shared.map, the maps you host, campaign.map, 040_voi.map)."
        say "Checking again every ${CHECK_INTERVAL} seconds."
        last=$report
    fi
    sleep "$CHECK_INTERVAL"
done
printf '%s\n' "$report"

args=(dedicated)
if [ "${VERBOSE:-0}" = 1 ]; then
    args+=(--verbose)
fi

# 5. Panel console: each line typed there goes to the first server's
# remote console (Source RCON at 127.0.0.1:<its game port>), so it works
# with RCON closed to the internet. Needs an RCON password.

# The RCON Password variable, else [rcon] password from dedicated.toml.
rcon_password() {
    if [ -n "${RECLAIMER_DEDICATED_RCON_PASSWORD:-}" ]; then
        printf '%s' "$RECLAIMER_DEDICATED_RCON_PASSWORD"
        return
    fi
    awk '
        /^[[:space:]]*\[/ { in_rcon = ($0 ~ /^[[:space:]]*\[[[:space:]]*rcon[[:space:]]*\][[:space:]]*(#.*)?$/); next }
        in_rcon && /^[[:space:]]*password[[:space:]]*=[[:space:]]*"/ {
            sub(/^[^=]*=[[:space:]]*"/, "")
            sub(/".*$/, "")
            print
            exit
        }
    ' dedicated.toml
}

console_bridge() {
    local line password
    while IFS= read -r line; do
        line=${line%$'\r'}
        [ -n "${line//[[:space:]]/}" ] || continue
        password=$(rcon_password)
        if [ -z "$password" ]; then
            say "Console commands need an RCON password: set the RCON Password variable (8-128 characters) and restart."
            continue
        fi
        if command -v rcon > /dev/null; then
            rcon -a "127.0.0.1:${SERVER_PORT}" -p "$password" "$line" 2>&1 ||
                say "RCON command failed. Is the server still starting?"
        else
            # shellcheck disable=SC2086 # split the line into the command's words
            wine "$EXE" dedicated rcon $line 2>&1 || say "RCON command failed."
        fi
    done
}

# The egg's "server started" marker: keep in sync with config.startup.done.
say "dedicated check passed: starting Project Reclaimer"
if [ "${CONSOLE_RCON:-1}" = 1 ] && [ -n "${SERVER_PORT:-}" ]; then
    say "Console commands are sent over RCON, e.g. status, players, kick <player> [reason], map <name>."
    # A background job's stdin is /dev/null unless redirected explicitly.
    exec 3<&0
    console_bridge <&3 3<&- &
fi
# The server keeps the foreground (and PID for Ctrl+C) as before; the
# console bridge, not the server, reads the panel's input.
exec wine "$EXE" "${args[@]}" < /dev/null 3<&-
