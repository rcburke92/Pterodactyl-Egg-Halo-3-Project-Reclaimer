"""Builds egg-project-reclaimer.json from src/install.sh, src/start.sh,
src/reserved_slots.py and src/next_vote.py.

Edit the scripts or the metadata below, then run:  python build_egg.py
Import the resulting JSON in Pterodactyl under Admin > Nests > Import Egg.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "egg-project-reclaimer.json"

# Printed by src/start.sh right before it hands over to the server.
DONE_MARKER = "dedicated check passed: starting Project Reclaimer"


def read_script(name: str) -> str:
    return (ROOT / "src" / name).read_text(encoding="utf-8").replace("\r\n", "\n")


def variable(name, env, default, description, rules, editable=True, viewable=True):
    return {
        "name": name,
        "description": description,
        "env_variable": env,
        "default_value": default,
        "user_viewable": viewable,
        "user_editable": editable,
        "rules": rules,
        "field_type": "text",
    }


FLAG = "nullable|string|in:true,false"

VARIABLES = [
    variable(
        "Project Reclaimer Version",
        "RECLAIMER_VERSION",
        "latest",
        "Release to install, such as 0.9.5, or latest. Applied when the server is "
        "(re)installed. Every player needs the same version as the server.",
        # No "|" inside the regex: Laravel splits rules on it, and the broken
        # pattern makes server creation fail with a 500.
        "required|string|regex:/^(latest$)?(v?\\d+\\.\\d+\\.\\d+)?$/",
    ),
    variable(
        "Host Name",
        "RECLAIMER_DEDICATED_HOST_NAME",
        "",
        "Host name shown in the Server Browser. Empty keeps host_name from dedicated.toml.",
        "nullable|string|max:48",
    ),
    variable(
        "Server Password",
        "RECLAIMER_DEDICATED_PASSWORD",
        "",
        "Password players need to join. Empty keeps dedicated.toml's setting (none by default).",
        "nullable|string|max:128",
    ),
    variable(
        "Max Players",
        "RECLAIMER_DEDICATED_MAX_PLAYERS",
        "",
        "Default player limit, 1-127, split-screen players included (a campaign "
        "co-op server takes 16 at most). Empty keeps dedicated.toml's setting (16 by default).",
        "nullable|integer|between:1,127",
    ),
    variable(
        "Admins",
        "RECLAIMER_DEDICATED_ADMINS",
        "",
        "Player IDs with kick and ban rights, separated by commas. Added to the admins "
        "in dedicated.toml. A player's ID is in the server log when they join.",
        "nullable|string|max:2048",
    ),
    variable(
        "RCON Password",
        "RECLAIMER_DEDICATED_RCON_PASSWORD",
        "",
        "Set one (8-128 characters) to turn on the remote console, which the panel "
        "console uses to send commands. Empty leaves it off.",
        "nullable|string|between:8,128",
    ),
    variable(
        "RCON Address",
        "RECLAIMER_DEDICATED_RCON_ADDRESS",
        "127.0.0.1",
        "127.0.0.1 keeps the remote console inside the container (the panel console "
        "still works). 0.0.0.0 also opens it to the internet on TCP at this server's "
        "port, for the desktop RCON app.",
        "nullable|string|in:0.0.0.0,127.0.0.1",
    ),
    variable(
        "Console Commands Via RCON",
        "CONSOLE_RCON",
        "1",
        "1 sends each line typed in the panel console to the first server's remote "
        "console. Needs an RCON password.",
        "required|string|in:0,1",
    ),
    variable(
        "Public Address",
        "RECLAIMER_DEDICATED_PUBLIC_ADDRESS",
        "",
        "IPv4 address or DNS name players connect to. Empty detects it (api.ipify.org). "
        "Set it when the node's outgoing address differs from the allocation's.",
        "nullable|string|max:253",
    ),
    variable(
        "Anti-Cheat",
        "RECLAIMER_DEDICATED_ANTI_CHEAT",
        "",
        "enforce, detect (log only) or off. Empty keeps dedicated.toml's setting (enforce).",
        "nullable|string|in:enforce,detect,off",
    ),
    variable(
        "Block VPNs",
        "RECLAIMER_DEDICATED_BLOCK_VPN",
        "",
        "true or false. Empty keeps dedicated.toml's setting (true).",
        FLAG,
    ),
    variable(
        "Hidden",
        "RECLAIMER_DEDICATED_HIDDEN",
        "",
        "true keeps the server out of the Server Browser (players use Direct Connect). "
        "Empty keeps dedicated.toml's setting (false).",
        FLAG,
    ),
    variable(
        "Min Players",
        "RECLAIMER_DEDICATED_MIN_PLAYERS",
        "",
        "Wait in the lobby until this many players are in: no playlist vote or "
        "automatic start before that. 1 up to Max Players. Empty keeps dedicated.toml's "
        "setting (1 by default).",
        "nullable|integer|between:1,127",
    ),
    variable(
        "Welcome Message",
        "RECLAIMER_DEDICATED_WELCOME",
        "",
        "A chat line every player reads as they join, such as your rules or Discord. "
        "{name} is the player's name, {server} the server's. Needs text chat. For "
        "several lines use a list in dedicated.toml. Empty keeps dedicated.toml's setting.",
        "nullable|string|max:300",
    ),
    variable(
        "Friendly Fire",
        "RECLAIMER_DEDICATED_FRIENDLY_FIRE",
        "",
        "false stops players hurting teammates and campaign co-op partners in every "
        "game. true follows each game type's own rules. Empty keeps dedicated.toml's "
        "setting (true).",
        FLAG,
    ),
    variable(
        "Team Changing",
        "RECLAIMER_DEDICATED_TEAM_CHANGING",
        "",
        "How far players may change teams themselves: balanced (only to a team with "
        "fewer players), game_type (as each game type allows) or off. Admins can always "
        "move players. Empty keeps dedicated.toml's setting (balanced).",
        "nullable|string|in:balanced,game_type,off",
    ),
    variable(
        "Voice Chat",
        "RECLAIMER_DEDICATED_VOICE",
        "",
        "false turns all voice chat off. Empty keeps dedicated.toml's setting (true).",
        FLAG,
    ),
    variable(
        "Global Voice",
        "RECLAIMER_DEDICATED_VOICE_GLOBAL",
        "",
        "Global voice (V key). false with Team Voice false leaves only proximity chat. "
        "Empty keeps dedicated.toml's setting (true).",
        FLAG,
    ),
    variable(
        "Team Voice",
        "RECLAIMER_DEDICATED_VOICE_TEAM",
        "",
        "Team voice (B key). Empty keeps dedicated.toml's setting (true).",
        FLAG,
    ),
    variable(
        "Proximity Voice",
        "RECLAIMER_DEDICATED_VOICE_PROXIMITY",
        "",
        "Proximity voice (N key). Empty keeps dedicated.toml's setting (true).",
        FLAG,
    ),
    variable(
        "Text Chat",
        "RECLAIMER_DEDICATED_TEXT_CHAT",
        "",
        "true or false. Empty keeps dedicated.toml's setting (true).",
        FLAG,
    ),
    variable(
        "Chat Log",
        "RECLAIMER_DEDICATED_CHAT_LOG",
        "",
        "Keep each server's text chat in data/<server>/chat, a file per day. Empty keeps "
        "dedicated.toml's setting (true).",
        FLAG,
    ),
    variable(
        "Player Votes",
        "RECLAIMER_DEDICATED_VOTES",
        "",
        "Let players vote to kick a player, end the round or end the game. Empty keeps "
        "dedicated.toml's setting (true).",
        FLAG,
    ),
    variable(
        "Max Ping",
        "RECLAIMER_DEDICATED_MAX_PING",
        "",
        "Turn away players whose ping is over this many milliseconds as they join "
        "(checked only at the join), up to 1000. 0 takes everyone. Empty keeps "
        "dedicated.toml's setting (0).",
        "nullable|integer|between:0,1000",
    ),
    variable(
        "Load Timeout",
        "RECLAIMER_DEDICATED_LOAD_TIMEOUT",
        "",
        "Seconds one player's game may hold up the next game while it loads, before "
        "that player is removed so the others can play. 0 waits as long as it takes. "
        "Empty keeps dedicated.toml's setting (30).",
        "nullable|integer|between:0,600",
    ),
    variable(
        "Share Mods",
        "RECLAIMER_DEDICATED_SHARE_MODS",
        "",
        "true lets players who lack a mod in content/Mods download it from the server. "
        "Empty keeps dedicated.toml's setting (false).",
        FLAG,
    ),
    variable(
        "Share Rate",
        "RECLAIMER_DEDICATED_SHARE_RATE",
        "",
        "Upload limit for shared mods per server, in Mbit/s. 0 is no limit. Empty keeps "
        "dedicated.toml's setting (20).",
        "nullable|integer|between:0,10000",
    ),
    variable(
        "Trust Player Games",
        "RECLAIMER_DEDICATED_TRUST_PLAYER_GAMES",
        "",
        "Campaign co-op: when every player's game goes out of step with the server's, "
        "take one player's game instead of making everyone load the server's. Empty "
        "keeps dedicated.toml's setting (true).",
        FLAG,
    ),
    variable(
        "VPN Lists",
        "RECLAIMER_DEDICATED_VPN_LISTS",
        "",
        "More lists of networks Block VPNs refuses (https:// addresses or files, one IP "
        "or range per line), separated by commas. Added to dedicated.toml's [vpn] lists; "
        "include default to keep the default lists beside your own.",
        "nullable|string|max:2048",
    ),
    variable(
        "Stats Server",
        "RECLAIMER_DEDICATED_STATS_SERVER",
        "",
        "Where finished games are reported for players' ranks: empty uses dedicated.toml "
        "(the project's public service by default), off reports nowhere, or your own "
        "service's https:// address.",
        "nullable|string|max:253",
    ),
    variable(
        "Character Mods",
        "RECLAIMER_DEDICATED_CUSTOMIZATION",
        "",
        "Character mods (in content/Mods) whose characters every server's multiplayer "
        "games add, by the names Customize shows, separated by commas: Armor Pack,Sci-Fi "
        "Heroes. Added to dedicated.toml's. Needs all 27 multiplayer maps in game/.",
        "nullable|string|max:2048",
    ),
    variable(
        "Require Character Mods",
        "RECLAIMER_DEDICATED_REQUIRE_CUSTOMIZATION",
        "",
        "true: players must accept the character mods to join. Empty keeps "
        "dedicated.toml's setting (false).",
        FLAG,
    ),
    variable(
        "No Vanilla Characters",
        "RECLAIMER_DEDICATED_NO_VANILLA_CHARACTERS",
        "",
        "true: every player plays one of the character mods' characters, never Halo 3's "
        "own. Empty keeps dedicated.toml's setting (false).",
        FLAG,
    ),
    variable(
        "Auto Reload",
        "RECLAIMER_DEDICATED_AUTO_RELOAD",
        "",
        "Apply saved edits to dedicated.toml, playlists and content while the servers run "
        "(0.9.18 and later), without dropping players. false waits for the reload command "
        "in the console. Empty keeps dedicated.toml's setting (true).",
        FLAG,
    ),
    variable(
        "Auto Update",
        "RECLAIMER_DEDICATED_AUTO_UPDATE",
        "false",
        "true installs each new Project Reclaimer release and restarts. Otherwise "
        "update by reinstalling with version latest.",
        FLAG,
    ),
    variable(
        "Local Master Server",
        "RECLAIMER_DEDICATED_MASTER_ENABLED",
        "false",
        "Run this machine's own discovery master. Not needed to be listed: servers "
        "always report to the two public masters. If true, add an allocation for "
        "Master Port.",
        FLAG,
    ),
    variable(
        "Master Port",
        "RECLAIMER_DEDICATED_MASTER_PORT",
        "49175",
        "TCP port of the local master server, when it is on. Must be one of this "
        "server's allocations.",
        "nullable|integer|between:1024,65535",
    ),
    variable(
        "Servers To Run",
        "RECLAIMER_DEDICATED_ONLY",
        "1",
        "Which [[server]] blocks of dedicated.toml to run: positions, names or ports, "
        "such as 1 or 1,2. Each server needs its own UDP allocation.",
        "required|string|max:256",
    ),
    variable(
        "Sync Port",
        "EGG_SYNC_PORT",
        "1",
        "1 sets the first [[server]]'s port in dedicated.toml to this server's primary "
        "allocation on every start. 0 leaves dedicated.toml alone.",
        "required|string|in:0,1",
    ),
    variable(
        "Verbose Log",
        "VERBOSE",
        "0",
        "1 prints everything the servers log, not just joins, leaves, kicks, bans and errors.",
        "required|string|in:0,1",
    ),
    variable(
        "Reserved Slots",
        "RESERVED_SLOTS",
        "",
        "Slots only whitelisted players may take, out of the first server's "
        "max_players. While the public slots are full the server needs the reserved "
        "password to join. 0 turns this off; empty uses reserved-slots.toml (off "
        "without one). Needs an RCON password.",
        "nullable|integer|between:0,126",
    ),
    variable(
        "Reserved Whitelist",
        "RESERVED_WHITELIST",
        "",
        "Player IDs that may use reserved slots, separated by commas. Added to the "
        "whitelist in reserved-slots.toml. Admins always may.",
        "nullable|string|max:4096",
    ),
    variable(
        "Reserved Password",
        "RESERVED_PASSWORD",
        "",
        "Join password set while the public slots are full; give it to whitelisted "
        "players. No spaces. Empty uses reserved-slots.toml.",
        "nullable|string|max:128|regex:/^\\S*$/",
    ),
    variable(
        "Reserved Bumping",
        "RESERVED_BUMP",
        "",
        "true kicks a player who isn't whitelisted when a whitelisted player is "
        "refused from the full server, so they can join. Empty uses "
        "reserved-slots.toml (off without one).",
        FLAG,
    ),
    variable(
        "Bump Order",
        "RESERVED_BUMP_ORDER",
        "",
        "Who gets bumped first: lowest_score, least_session_time (this visit), "
        "least_total_time (all visits), separated by commas. Ties go to the newest "
        "player. Empty uses reserved-slots.toml, else lowest_score,least_session_time.",
        "nullable|string|max:128",
    ),
    variable(
        "Virtual Display",
        "XVFB",
        "1",
        "Runs Wine on a virtual display (Xvfb), as the official Docker image does.",
        "required|string|in:0,1",
        editable=False,
        viewable=False,
    ),
]


def build() -> dict:
    start = read_script("start.sh")
    if DONE_MARKER not in start:
        raise SystemExit(f"src/start.sh no longer prints the done marker: {DONE_MARKER!r}")
    if "\nSTART_SH\n" in f"\n{start}\n":
        raise SystemExit("src/start.sh must not contain a line reading START_SH")

    install = read_script("install.sh")
    if "@@START_SH@@" not in install:
        raise SystemExit("src/install.sh is missing the @@START_SH@@ placeholder")
    install = install.replace("@@START_SH@@", start.rstrip("\n"))

    slots = read_script("reserved_slots.py")
    if "\nRESERVED_SLOTS_PY\n" in f"\n{slots}\n":
        raise SystemExit("src/reserved_slots.py must not contain a line reading RESERVED_SLOTS_PY")
    if "@@RESERVED_SLOTS_PY@@" not in install:
        raise SystemExit("src/install.sh is missing the @@RESERVED_SLOTS_PY@@ placeholder")
    install = install.replace("@@RESERVED_SLOTS_PY@@", slots.rstrip("\n"))

    vote = read_script("next_vote.py")
    if "\nNEXT_VOTE_PY\n" in f"\n{vote}\n":
        raise SystemExit("src/next_vote.py must not contain a line reading NEXT_VOTE_PY")
    if "@@NEXT_VOTE_PY@@" not in install:
        raise SystemExit("src/install.sh is missing the @@NEXT_VOTE_PY@@ placeholder")
    install = install.replace("@@NEXT_VOTE_PY@@", vote.rstrip("\n"))

    return {
        "_comment": "DO NOT EDIT: FILE GENERATED AUTOMATICALLY BY PTERODACTYL PANEL - PTERODACTYL.IO",
        "meta": {"version": "PTDL_v2", "update_url": None},
        "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        "name": "Project Reclaimer (Halo 3)",
        "author": "86576924+rcburke92@users.noreply.github.com",
        "description": (
            "Project Reclaimer dedicated servers for Halo 3 (Halo: The Master Chief "
            "Collection), run under Wine. Needs Halo 3's files from your own MCC copy, "
            "uploaded into game/. https://projectreclaimer.dev/host"
        ),
        "features": None,
        "docker_images": {"Wine Stable": "ghcr.io/parkervcp/yolks:wine_latest"},
        "file_denylist": [],
        "startup": "bash ./reclaimer-start.sh",
        "config": {
            "files": "{}",
            "startup": json.dumps({"done": DONE_MARKER}),
            "logs": "{}",
            "stop": "^C",
        },
        "scripts": {
            "installation": {
                "script": install,
                "container": "ghcr.io/parkervcp/installers:debian",
                "entrypoint": "bash",
            }
        },
        "variables": VARIABLES,
    }


if __name__ == "__main__":
    OUT.write_text(json.dumps(build(), indent=4) + "\n", encoding="utf-8", newline="\n")
    print(f"Wrote {OUT.relative_to(ROOT)}")
