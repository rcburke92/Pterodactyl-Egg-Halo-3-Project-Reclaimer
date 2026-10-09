#!/bin/bash
# Project Reclaimer (Halo 3) dedicated server: Pterodactyl install script.
# Runs as root in the installer container with the server folder at
# /mnt/server. Downloads the Windows dedicated server build from GitHub
# releases, verifies it against the release's SHA256SUMS.txt and writes
# the start script. Reinstalling updates the executable and start script
# and keeps dedicated.toml, game/, content/, playlists/, bans.json and data/.
#
# The game files are NOT downloaded: Halo 3's files come from your own copy
# of Halo: The Master Chief Collection and are uploaded into game/.
set -euo pipefail

REPO=ProjectReclaimer/project-reclaimer-releases
SERVER_DIR=${INSTALL_DIR:-/mnt/server}

say() { printf '[install] %s\n' "$*"; }
fail() {
    say "Error: $*"
    exit 1
}

if ! command -v curl > /dev/null || ! command -v sha256sum > /dev/null; then
    apt-get update -qq
    apt-get install -y -qq --no-install-recommends curl ca-certificates coreutils
fi

mkdir -p "$SERVER_DIR"
cd "$SERVER_DIR"

version=${RECLAIMER_VERSION:-latest}
if [ -z "$version" ] || [ "$version" = latest ]; then
    release=$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest") ||
        fail "could not reach the GitHub API for $REPO"
    tag=$(printf '%s\n' "$release" | grep -m1 '"tag_name"' |
        sed -E 's/.*"tag_name"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/' || true)
    [ -n "$tag" ] || fail "could not find the latest release of $REPO"
else
    tag="v${version#v}"
fi
say "Project Reclaimer $tag"

base="https://github.com/$REPO/releases/download/$tag"
sums=$(curl -fsSL "$base/SHA256SUMS.txt") || fail "release $tag not found (no $base/SHA256SUMS.txt)"

# The dedicated-only build exists from 0.8.14; older releases have only the
# full client, which runs dedicated servers too.
asset=""
for candidate in "project-reclaimer-dedicated-$tag.exe" "project-reclaimer-$tag.exe"; do
    if printf '%s\n' "$sums" | grep -q "[ *]$candidate\$"; then
        asset=$candidate
        break
    fi
done
[ -n "$asset" ] || fail "release $tag has no Windows server executable"
expected=$(printf '%s\n' "$sums" | grep "[ *]$asset\$" | head -n 1 | cut -d ' ' -f 1)

say "Downloading $asset..."
curl -fL --retry 3 -o project-reclaimer.exe.new "$base/$asset"
actual=$(sha256sum project-reclaimer.exe.new | cut -d ' ' -f 1)
if [ "$actual" != "$expected" ]; then
    rm -f project-reclaimer.exe.new
    fail "checksum mismatch for $asset (expected $expected, got $actual)"
fi
mv -f project-reclaimer.exe.new project-reclaimer.exe
printf '%s\n' "$tag" > .reclaimer-version
say "Verified SHA-256 $actual"

mkdir -p game/halo3/maps
cat > game/PUT_HALO3_FILES_HERE.txt << 'README'
Halo 3's game files go in this folder, copied from your own Steam copy of
Halo: The Master Chief Collection (with Halo 3 and its campaign installed).

Easiest way: on a Windows PC with the game, download project-reclaimer.exe from
https://projectreclaimer.dev and run

    .\project-reclaimer.exe dedicated init C:\reclaimer --from

(add --maps "Guardian,Valhalla" to copy only some maps), then upload the
contents of C:\reclaimer\game into this folder over SFTP, keeping the folders:

    game/halo3/halo3.dll
    game/halo3/maps/shared.map
    game/halo3/maps/campaign.map
    game/halo3/maps/040_voi.map
    game/halo3/maps/<the multiplayer maps you host>.map
    ...

The server checks every 15 seconds while it waits, and starts once
`dedicated check` passes. You can delete this file.
README

cat > reclaimer-start.sh << 'START_SH'
@@START_SH@@
START_SH
chmod +x reclaimer-start.sh

say "Done. Start the server; on first start it creates dedicated.toml, then waits for Halo 3's files in game/."
