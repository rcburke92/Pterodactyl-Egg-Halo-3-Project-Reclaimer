#!/usr/bin/env python3
"""Next-game vote for the first [[server]]: an admin starts it, players pick.

Written into the server folder by the egg's installer as
reclaimer-next-vote.py; start.sh runs it when next-vote.toml exists. It
talks to the server only through `dedicated rcon`, like the panel console.

  1. An admin types !nextvote in game chat, or nextvote in the panel console.
  2. The server lists games from next-vote.toml in chat, numbered. Players
     answer with the number (!2 or 2); a player's last answer counts.
  3. When the time is up, the game with the most votes is queued with RCON
     `nextmap`: the game being played finishes, then the winner plays
     instead of the playlist's ballot, once. With no votes nothing changes.

Admin commands, in game chat (with !) or in the panel console (without):
  nextvote          start a vote
  nextvote end      close the vote now and queue the leader
  nextvote cancel   close the vote without changing anything
  nextvote list     show the games next-vote.toml offers

next-vote.toml is read each time a vote starts, so edits need no restart:

  vote_seconds = 60       # 15 to 300
  choices_per_vote = 4    # games drawn at random from the list; 0 = all (at most 9)

  [[choice]]
  name = "Snipers on Valhalla"            # optional: what players read
  map = "Valhalla"                        # as a playlist entry names it
  game = "Game Modes/snipers.json"        # a mode, bundled mode or saved game type
"""

import json
import os
import queue
import random
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

try:
    import tomllib
except ImportError:  # Python before 3.11
    tomllib = None

SETTINGS_FILE = Path("next-vote.toml")
# start.sh writes panel console lines starting with "nextvote" here.
REQUEST_FILE = Path(".next-vote-request")
RETRY_SECONDS = 15
MAX_CHOICES = 9
VOTE_RE = re.compile(r"^\s*(?:!vote\s+|!)?([1-9])\s*$", re.IGNORECASE)
COMMAND_RE = re.compile(r"^\s*!nextvote\b\s*(.*)$", re.IGNORECASE)


def say(message):
    print(f"[vote] {message}", flush=True)


def fail(message):
    say(f"Error: {message}.")
    sys.exit(1)


class SettingsError(Exception):
    """next-vote.toml can't be used."""


# ---- settings ---------------------------------------------------------------

def load_settings():
    if not SETTINGS_FILE.exists():
        raise SettingsError(f"{SETTINGS_FILE} is missing")
    try:
        with open(SETTINGS_FILE, "rb") as f:
            raw = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise SettingsError(f"could not read {SETTINGS_FILE} ({e})") from e
    try:
        seconds = int(raw.get("vote_seconds", 60))
        per_vote = int(raw.get("choices_per_vote", 4))
    except (TypeError, ValueError) as e:
        raise SettingsError("vote_seconds and choices_per_vote must be numbers") from e
    if not 15 <= seconds <= 300:
        raise SettingsError("vote_seconds must be 15 to 300")
    if not 0 <= per_vote <= MAX_CHOICES:
        raise SettingsError(f"choices_per_vote must be 0 to {MAX_CHOICES}")
    choices = []
    for i, c in enumerate(raw.get("choice") or [], 1):
        if not isinstance(c, dict) or not str(c.get("map", "")).strip() or not str(c.get("game", "")).strip():
            raise SettingsError(f"choice {i} needs a map and a game")
        name = str(c.get("name") or f"{c['game']} on {c['map']}").strip()
        choices.append({"name": name, "map": str(c["map"]).strip(), "game": str(c["game"]).strip()})
    if len(choices) < 2:
        raise SettingsError("list at least two [[choice]] games")
    return {"seconds": seconds, "per_vote": per_vote or MAX_CHOICES, "choices": choices}


def first_server():
    """(name, has an RCON password) of the first [[server]] in dedicated.toml."""
    try:
        with open("dedicated.toml", "rb") as f:
            toml = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise SettingsError(f"could not read dedicated.toml ({e})") from e
    server = (toml.get("server") or [{}])[0]
    password = (os.environ.get("RECLAIMER_DEDICATED_RCON_PASSWORD", "").strip()
                or server.get("rcon_password") or toml.get("rcon", {}).get("password"))
    return server.get("name", ""), bool(password)


# ---- RCON -------------------------------------------------------------------

class Rcon:
    """Runs the server's own `dedicated rcon` client, one process per command."""

    def __init__(self, exe, server_name):
        # Wine on the egg's Linux image; straight on Windows, for testing.
        self.base = ([] if os.name == "nt" else ["wine"]) + [exe, "dedicated", "rcon"]
        if server_name:
            self.base += ["--server", server_name]

    def run(self, *args, as_json=False):
        cmd = self.base + (["--json"] if as_json else []) + list(args)
        return subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)

    def command(self, *args, as_json=False):
        result = self.run(*args, as_json=as_json)
        if result.returncode != 0:
            raise RuntimeError(clean_error(result.stderr or result.stdout) or f"exit code {result.returncode}")
        return result.stdout

    def chat(self, text):
        try:
            self.command("say", text)
        except Exception as e:  # noqa: BLE001 - a lost line shouldn't stop the vote
            say(f"Could not post to chat ({e}).")

    def tell(self, player_id, text):
        try:
            self.command("tell", player_id, text)
        except Exception:  # noqa: BLE001 - they may have left
            pass

    def admins(self):
        data = json.loads(self.command("players", as_json=True) or "{}")
        players = data.get("players", data) if isinstance(data, dict) else data
        return {str(p.get("id", "")).lower() for p in players or [] if p.get("admin")}

    def watch(self):
        return subprocess.Popen(self.base + ["--json", "--watch"], stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def clean_error(text):
    return re.sub(r"^Error:\s*", "", (text or "").strip().splitlines()[-1] if (text or "").strip() else "")


# ---- the vote ---------------------------------------------------------------

class Vote:
    def __init__(self, settings):
        pool = list(settings["choices"])
        random.shuffle(pool)
        self.choices = pool[:settings["per_vote"]]
        self.seconds = settings["seconds"]
        self.ends = time.monotonic() + self.seconds
        self.ballots = {}       # player ID -> choice index
        self.reminded = set()

    def cast(self, player_id, number):
        if 1 <= number <= len(self.choices):
            self.ballots[player_id] = number - 1
            return True
        return False

    def tally(self):
        counts = [0] * len(self.choices)
        for i in self.ballots.values():
            counts[i] += 1
        return counts

    def standings(self):
        counts = self.tally()
        order = sorted(range(len(counts)), key=lambda i: -counts[i])
        return ", ".join(f"{self.choices[i]['name']} {counts[i]}" for i in order if counts[i]) or "no votes yet"

    def winner(self):
        """(choice, votes), ties drawn at random; None without votes."""
        counts = self.tally()
        top = max(counts)
        if top == 0:
            return None
        return random.choice([self.choices[i] for i, n in enumerate(counts) if n == top]), top


class Runner:
    def __init__(self, exe):
        self.exe = exe
        self.vote = None
        self.rcon = None
        self.server = None

    def connect(self):
        """Follows dedicated.toml's first server (renaming it needs no restart)."""
        name, has_password = first_server()
        if not has_password:
            raise SettingsError("the vote needs an RCON password: set the RCON Password variable or [rcon] password")
        if self.rcon is None or name != self.server:
            self.rcon, self.server = Rcon(self.exe, name), name
        return self.rcon

    # Commands, from an admin in chat (by = player ID) or the panel console (by = None).
    def handle(self, args, by=None):
        words = args.split()
        sub = words[0].lower() if words else "start"
        reply = (lambda text: self.rcon.tell(by, text)) if by else say
        try:
            rcon = self.connect()
        except SettingsError as e:
            say(f"Error: {e}.")
            return
        if sub == "start":
            if self.vote:
                reply("A next-game vote is already open.")
                return
            try:
                settings = load_settings()
            except SettingsError as e:
                say(f"Error: {e}.")
                reply(f"Can't start the vote: {e}.")
                return
            self.vote = Vote(settings)
            say(f"Vote started{' by an admin in game' if by else ''}.")
            rcon.chat(f"Vote for the next game! Type the number in chat ({self.vote.seconds} s):")
            for n, c in enumerate(self.vote.choices, 1):
                rcon.chat(f"  !{n}  {c['name']}")
        elif sub in ("end", "stop"):
            if not self.vote:
                reply("No next-game vote is open.")
                return
            self.finish()
        elif sub == "cancel":
            if not self.vote:
                reply("No next-game vote is open.")
                return
            self.vote = None
            rcon.chat("The next-game vote was cancelled.")
            say("Vote cancelled.")
        elif sub == "list":
            try:
                settings = load_settings()
            except SettingsError as e:
                reply(f"{e}.")
                return
            reply(f"{len(settings['choices'])} games, {settings['per_vote']} per vote, {settings['seconds']} s: "
                  + "; ".join(c["name"] for c in settings["choices"]))
        else:
            reply("Use nextvote, nextvote end, nextvote cancel or nextvote list.")

    def chat_line(self, event):
        text = str(event.get("text", ""))
        player_id = str(event.get("id", "")).lower()
        if not player_id or event.get("channel") == "server":
            return
        command = COMMAND_RE.match(text)
        if command:
            try:
                admin = player_id in self.connect().admins()
            except Exception as e:  # noqa: BLE001
                say(f"Could not check whether {event.get('name', 'a player')} is an admin ({e}).")
                return
            if admin:
                self.handle(command.group(1), by=player_id)
            else:
                self.rcon.tell(player_id, "Only admins can start a next-game vote.")
            return
        number = VOTE_RE.match(text)
        if self.vote and number and self.vote.cast(player_id, int(number.group(1))):
            pass  # counted; standings go out with the reminders

    def tick(self):
        if not self.vote:
            return
        left = self.vote.ends - time.monotonic()
        if left <= 0:
            self.finish()
            return
        for mark in (30, 10):
            if left <= mark < self.vote.seconds and mark not in self.vote.reminded:
                self.vote.reminded.add(mark)
                self.rcon.chat(f"{mark} s left to vote for the next game: {self.vote.standings()}.")

    def finish(self):
        vote, self.vote = self.vote, None
        result = vote.winner()
        if not result:
            self.rcon.chat("No votes for the next game: the server picks it as usual.")
            say("Vote closed without votes.")
            return
        choice, votes = result
        try:
            self.rcon.command("nextmap", choice["map"], choice["game"])
        except Exception as e:  # noqa: BLE001
            self.rcon.chat(f"{choice['name']} won, but the server can't queue it.")
            say(f"Could not queue {choice['name']} (nextmap {choice['map']} / {choice['game']}): {e}")
            return
        self.rcon.chat(f"Next game: {choice['name']} ({votes} vote{'s' if votes != 1 else ''}). It starts after this game.")
        say(f"Queued {choice['name']} with {votes} vote(s). Totals: {vote.standings()}.")


# ---- inputs -----------------------------------------------------------------

def follow_chat(runner, inbox):
    """Feeds chat lines from `dedicated rcon --watch` to the main loop, restarting it if it ends."""
    down = False
    while True:
        try:
            proc = runner.connect().watch()
            for line in proc.stdout:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict) and event.get("event") == "chat":
                    if down:
                        say("Server answering again.")
                        down = False
                    inbox.put(("chat", event))
            proc.wait()
        except Exception as e:  # noqa: BLE001
            if not down:
                say(f"Waiting for the server's remote console ({e}).")
                down = True
        time.sleep(RETRY_SECONDS)


def console_requests(inbox):
    """Panel console lines starting with nextvote, which start.sh leaves in REQUEST_FILE."""
    while True:
        try:
            lines = REQUEST_FILE.read_text(encoding="utf-8").splitlines()
            REQUEST_FILE.unlink()
        except OSError:
            lines = []
        for line in lines:
            inbox.put(("console", re.sub(r"^\s*nextvote\b\s*", "", line, flags=re.IGNORECASE)))
        time.sleep(1)


def main():
    if tomllib is None:
        fail("needs Python 3.11 or later")
    if len(sys.argv) != 2:
        fail("usage: reclaimer-next-vote.py <path to project-reclaimer.exe>")
    runner = Runner(sys.argv[1])
    try:
        n = len(load_settings()["choices"])
        say(f"Next-game vote ready with {n} games: an admin types !nextvote in chat, or nextvote in this console.")
    except SettingsError as e:
        say(f"Error: {e}. Fix next-vote.toml; it's read again when a vote starts.")
    REQUEST_FILE.unlink(missing_ok=True)

    inbox = queue.Queue()
    threading.Thread(target=follow_chat, args=(runner, inbox), daemon=True).start()
    threading.Thread(target=console_requests, args=(inbox,), daemon=True).start()
    while True:
        try:
            kind, data = inbox.get(timeout=1)
            if kind == "chat":
                runner.chat_line(data)
            else:
                runner.handle(data)
        except queue.Empty:
            pass
        except Exception as e:  # noqa: BLE001 - keep the vote helper running
            say(f"Error: {e}")
        try:
            runner.tick()
        except Exception as e:  # noqa: BLE001
            say(f"Error: {e}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
