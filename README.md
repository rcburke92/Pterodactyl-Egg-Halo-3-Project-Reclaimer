# Project Reclaimer (Halo 3) — Pterodactyl egg

A Pterodactyl egg that runs [Project Reclaimer](https://projectreclaimer.dev/host) dedicated Halo 3 servers under Wine.

- **Image:** `ghcr.io/parkervcp/yolks:wine_latest` (WineHQ stable on Debian trixie, with Xvfb). You don't build or host a custom image.
- **Install:** downloads the official `project-reclaimer-dedicated-<version>.exe` from [GitHub releases](https://github.com/ProjectReclaimer/project-reclaimer-releases/releases) and checks it against the release's `SHA256SUMS.txt`.
- **Start:** does what the official Docker image's entrypoint does, adapted to Pterodactyl.

## Setup

1. **Import the egg.** Download [egg-project-reclaimer.json](egg-project-reclaimer.json). In the admin area go to **Nests**, then **Import Egg**, and pick that file. Choose a nest, for example create a "Halo" nest.
2. **Create a server** from the egg.
   - **Allocation:** one port per Halo server; it is used over UDP (the game) and TCP (RCON). Any port works, e.g. `49176`.
   - **Memory:** at least **2 GB**; 3 GB is comfortable. A server uses about 0.6–0.9 GB in a game and up to 1.4 GB while loading a map, plus Wine.
   - **Disk:** at least **10 GB** if you host every multiplayer map (about 5.5 GB of maps, a 340 MB Forge library, and the Wine prefix).
   - **CPU:** a full 63-player game wants about one core.
3. **Upload Halo 3's game files.** They come from your own Steam copy of MCC with Halo 3 and its campaign installed; the egg cannot download them.
   1. On a Windows PC with the game, get `project-reclaimer.exe` from [projectreclaimer.dev](https://projectreclaimer.dev) and run:
      ```powershell
      .\project-reclaimer.exe dedicated init C:\reclaimer --from
      # or only some maps:  --maps "Guardian,Valhalla"
      ```
   2. Upload the contents of `C:\reclaimer\game` into the server's `game/` folder over SFTP (shown in the panel's **Settings** tab), keeping the folder structure: `game/halo3/halo3.dll`, `game/halo3/maps/shared.map`, and so on.
   3. **Flood Infection only:** also upload `050_floodvoi.map` from MCC's `halo3\maps` into `game/halo3/maps`. The mode loads its Flood bodies from it, `dedicated init` doesn't copy it and `dedicated check` doesn't ask for it. Without it, a vote for a Flood Infection entry passes, the game fails to load and the vote starts over.
4. **Start the server.** On first start it:
   1. creates the Wine prefix;
   2. runs `dedicated init .` to create `dedicated.toml`, `playlists/`, `content/` and `bans.json`;
   3. sets the first `[[server]]`'s `port` to your allocation;
   4. runs `dedicated check` every 15 seconds until it passes, so you can upload the game files while it waits.

   The panel shows the server as running when the console prints `dedicated check passed: starting Project Reclaimer`.
5. **Configure the server.** Edit `dedicated.toml` in the File Manager to set the server name, map and mode or playlist, then restart. The format is in the [config reference](https://projectreclaimer.dev/host).

## Egg variables

Each `RECLAIMER_DEDICATED_*` variable overrides the same setting in `dedicated.toml`. An empty value keeps whatever the file says. Per-server settings such as `name`, `map`, `game`, `playlist` and `variant` live only in `dedicated.toml`.

| Variable | Default | Notes |
|---|---|---|
| Project Reclaimer Version | `latest` | Applied on (re)install. Players must run the same version as the server. |
| Host Name, Server Password, Max Players, Admins | empty | Admins are added to the file's list, comma-separated. Player IDs appear in the log when players join. |
| RCON Password | empty | 8–128 characters. Turns on the remote console, which the panel console uses (see [Panel console](#panel-console)). |
| RCON Address | `127.0.0.1` | Keeps RCON inside the container; the panel console still works. Set `0.0.0.0` only if you also want the desktop RCON app to connect over the internet on your allocation's TCP port. |
| Console Commands Via RCON | `1` | Sends what you type in the panel console to RCON. `0` turns this off. |
| Public Address | empty | Empty auto-detects the address. Set it if the node's outgoing IP isn't the allocation's IP. |
| Anti-Cheat, Block VPNs, Hidden | empty | |
| Auto Update | `false` | `true` makes the exe install new releases itself. Otherwise update by **Reinstall** with version `latest`. |
| Local Master Server | `false` | Not needed to show up in the Server Browser: servers always report to the two public masters. If you turn it on, add a second allocation and set Master Port to it. |
| Servers To Run | `1` | Which `[[server]]` blocks run. The default `dedicated.toml` may contain more than one, and each extra server needs its own allocation and a matching `port` that you set yourself. |
| Sync Port | `1` | Rewrites the first `[[server]]`'s `port` to the primary allocation on every start. Set `0` to manage the port yourself. |
| Verbose Log | `0` | `1` passes `--verbose`. |
| Reserved Slots, Reserved Whitelist, Reserved Password, Reserved Bumping, Bump Order | empty | Empty uses `reserved-slots.toml`. See [Reserved slots](#reserved-slots). |

## Updating

**Settings → Reinstall Server** downloads the version in *Project Reclaimer Version* and rewrites `reclaimer-start.sh`. Your `dedicated.toml`, `game/`, `content/`, `playlists/`, `bans.json` and `data/` are kept.

## Panel console

Set an **RCON Password** and restart. After that, each line you type in the panel console is sent to the first server's remote console on `127.0.0.1:<allocation port>`. It uses the server's own `dedicated rcon` and prints the reply in full, long `players` lists included. Quote player names that contain spaces. Useful commands:

```
status                      server info, players, current game
players                     full player list with IDs
kick <player> [reason]
ban <player> [time] [reason]
unban <target>
map <name>    mode <name>    load <map> <mode>
endround    endgame    shuffle
mute <player> [time]    unmute <player>
```

Notes:

- RCON only answers once the server is up, so commands typed during first start fail.
- The password comes from the RCON Password variable, or from `[rcon] password` in `dedicated.toml`.
- Only the first `[[server]]` in `dedicated.toml` is reached.
- The `dedicated ban`, `dedicated bans` and `dedicated vpn …` CLI commands aren't RCON commands. Use the RCON `ban`/`unban` above, in-game `/ban`, or edit `bans.json`.

## Reserved slots

Keeps slots free for whitelisted players, such as the server's owner, on the first `[[server]]`. It runs beside the server and works through RCON, so it needs an **RCON Password**.

Settings go in `reserved-slots.toml` beside `dedicated.toml`, which the Halo 3 Server Manager writes, or in the **Reserved …** egg variables. A variable that isn't empty overrides the file, and **Reserved Whitelist** adds to the file's whitelist.

```toml
slots = 1                     # 0 turns reserved slots off
password = "only-for-vips"    # no spaces
whitelist = ["<64-character player ID>"]
bump = false
bump_order = ["lowest_score", "least_session_time"]
```

1. Set `max_players` in `dedicated.toml` (or **Max Players**) to the public slots plus the reserved ones. For 15 public slots and 1 reserved, use `16`.
2. Set `slots` and `password`. Keep **Server Password** and `password` in `dedicated.toml` empty.
3. Add player IDs to `whitelist`. Admins are always whitelisted. Players find their ID under **Settings → Connectivity → Your player ID**.
4. Restart. The console prints `[slots] 1 of 16 slots reserved for …`.

How it behaves:

- Once players who aren't whitelisted fill the public slots, the server gets the reserved password and shows as **PRIVATE**. Other players are asked for the password instead of being kicked. Whitelisted players enter it and join. When a public slot frees up, the password comes off.
- A player who isn't whitelisted and still gets into a reserved slot is kicked, newest first. That covers a leaked password, or two players joining at the same moment.
- `bump = true`: when the server is completely full and a whitelisted player is refused, one player who isn't whitelisted is kicked, and the server stays locked for a minute so the whitelisted player can join again. `bump_order` picks who goes first: `lowest_score` (in the game being played; everyone ties in the lobby), `least_session_time` (this visit), `least_total_time` (all visits, kept in `data/reserved-slots-playtime.json`). Ties go to the newest player.
- Kicks from reserved slots and bumps are normal kicks: the kicked player can't rejoin for 10 minutes, longer after repeated kicks.
- Split-screen players count toward the slots, as they do for `max_players`.

## Things that work differently from the official Docker setup

- **Admin commands:** see [Panel console](#panel-console). With RCON Address set to `0.0.0.0`, `reclaimer-rcon-<version>.exe` from the releases page can also connect to `<server ip>:<port>`.
- **Workshop downloads** need Steam or SteamCMD, which the container doesn't have. Copy mod folders from `steamapps\workshop\content\976730` into `content/Mods/` instead.
- **Logs** are written to `data/<server name>/server.log` as well as the console.

## Troubleshooting

- **Stuck on "Waiting for 'dedicated check' to pass".** The lines above that message say what is missing. It is usually game files in the wrong place: `game/halo3/halo3.dll` must exist at exactly that path.
- **Players can see the server but can't join.** Make sure the node's firewall allows **UDP** on the allocation's port, and that Public Address resolves to the allocation's IP.
- **"A misspelt RECLAIMER_DEDICATED_ name stops the start".** Any extra environment variable you add to the egg must be a real Project Reclaimer setting.

## Development

| Path | What it is |
|---|---|
| [egg-project-reclaimer.json](egg-project-reclaimer.json) | The egg to import. Generated; don't edit by hand. |
| [src/install.sh](src/install.sh) | Install script: downloads and verifies the exe, writes the start script. |
| [src/start.sh](src/start.sh) | Start script, installed as `reclaimer-start.sh` in the server folder. |
| [src/reserved_slots.py](src/reserved_slots.py) | Reserved slots, installed as `reclaimer-reserved-slots.py` and started by the start script. |
| [build_egg.py](build_egg.py) | Builds the egg JSON from the scripts. Egg variables and metadata live here. |

After editing anything in `src/` or `build_egg.py`, run `python build_egg.py` (Python 3), commit the regenerated JSON, then re-import the egg (or use **Update** on the existing egg).

## License

[MIT](LICENSE). Halo is a trademark of Microsoft; this project is not affiliated with Microsoft, 343 Industries or Project Reclaimer.
