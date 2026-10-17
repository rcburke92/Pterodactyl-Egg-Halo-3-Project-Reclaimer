#!/usr/bin/env python3
"""Reserved slots for whitelisted players, run beside the first [[server]].

Written into the server folder by the egg's installer as
reclaimer-reserved-slots.py; start.sh runs it when Reserved Slots is above 0
or reserved-slots.toml exists. It talks to the server only through
`dedicated rcon`, like the panel console.

With max_players = M and R reserved slots, players who aren't whitelisted
may hold at most M - R slots (split-screen guests count):
  - Once they hold all of them, the server gets a join password (the
    reserved password), so the Server Browser shows it as PRIVATE and other
    players are asked for it instead of being kicked. Whitelisted players
    know it. The password comes off again when a public slot frees up.
  - A player who isn't whitelisted and still gets into a reserved slot
    (a leaked password, or two joins at once) is kicked: newest first.
  - With bumping on, a whitelisted player refused from a full server makes
    room: one player who isn't whitelisted is kicked, chosen by the bump
    order, and the server stays locked briefly so the whitelisted player
    can join again into that slot.
Admins (dedicated.toml and the Admins variable) are always whitelisted.

Like Project Reclaimer 0.9.18 servers, it takes up saved edits to
dedicated.toml and reserved-slots.toml without a restart: a file that
doesn't check out leaves the previous settings in place, and slots = 0
opens the server and pauses until slots go up again.

Settings come from reserved-slots.toml beside dedicated.toml (the Server
Manager writes it), and an egg variable that isn't empty overrides its key,
like the RECLAIMER_DEDICATED_* variables do for dedicated.toml:
  slots       RESERVED_SLOTS       number of reserved slots; 0 turns this off
  whitelist   RESERVED_WHITELIST   player IDs (the variable adds to the file's)
  password    RESERVED_PASSWORD    the join password whitelisted players use
  bump        RESERVED_BUMP        true or false
  bump_order  RESERVED_BUMP_ORDER  rules, first rule first:
                lowest_score        lowest score in the game being played
                least_session_time  shortest time on the server this visit
                least_total_time    least time on this server, all visits
"""

import json
import os
import queue
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

ID_RE = re.compile(r"\b[0-9a-fA-F]{64}\b")
POLL_SECONDS = 10           # re-check even without events
RETRY_SECONDS = 15          # wait while RCON doesn't answer
HOLD_SECONDS = 60           # keep the server locked after a bump
BUMP_COOLDOWN_SECONDS = 30  # one bump per whitelisted player per this long
SAVE_SECONDS = 60
SETTINGS_FILE = Path("reserved-slots.toml")
PLAYTIME_FILE = Path("data") / "reserved-slots-playtime.json"
DEFAULT_BUMP_ORDER = ["lowest_score", "least_session_time"]
BUMP_RULES = ("lowest_score", "least_session_time", "least_total_time")
EVENT_WORDS = ("join", "leave", "left", "disconnect", "kick", "ban", "refus")

KICK_RESERVED = "That slot is reserved. Join again when the server has a public slot free."
KICK_BUMP = "Removed to make room for a reserved-slot player."


def say(message):
    print(f"[slots] {message}", flush=True)


def fail(message):
    say(f"Error: {message}. Reserved slots are off until this is fixed and the server restarts.")
    sys.exit(1)


class SettingsError(Exception):
    """dedicated.toml or reserved-slots.toml doesn't work for reserved slots."""


def problem(message):
    raise SettingsError(message)


def split_list(text):
    return [item.strip() for item in re.split(r"[,\s]+", text or "") if item.strip()]


# ---- settings ---------------------------------------------------------------

class Settings:
    def __init__(self):
        if tomllib is None:
            fail("needs Python 3.11 or later")
        toml = self.load(Path("dedicated.toml"))
        own = self.load(SETTINGS_FILE) if SETTINGS_FILE.exists() else {}
        env = lambda name: os.environ.get(name, "").strip()

        try:
            self.reserved = int(env("RESERVED_SLOTS") or own.get("slots", 0))
        except (TypeError, ValueError):
            problem("Reserved Slots (slots) must be a number")
        if self.reserved <= 0:
            return

        servers = toml.get("server") or [{}]
        server = servers[0]
        defaults = toml.get("defaults", {})
        self.server_name = server.get("name", "")

        rcon_password = env("RECLAIMER_DEDICATED_RCON_PASSWORD") or server.get("rcon_password") or toml.get("rcon", {}).get("password")
        if not rcon_password:
            problem("reserved slots need an RCON password: set the RCON Password variable or [rcon] password")

        # A [[server]] value beats the Max Players variable, which beats [defaults].
        if "max_players" in server:
            self.max_players = int(server["max_players"])
        elif env("RECLAIMER_DEDICATED_MAX_PLAYERS"):
            self.max_players = int(env("RECLAIMER_DEDICATED_MAX_PLAYERS"))
        else:
            self.max_players = int(defaults.get("max_players", 16))

        if "password" in server:
            own_password = server["password"]
        else:
            own_password = env("RECLAIMER_DEDICATED_PASSWORD") or defaults.get("password", "")
        if own_password:
            problem("the server already has a join password; reserved slots need it empty, since they set one only while the server is full")

        self.public = self.max_players - self.reserved
        if self.public < 1:
            problem(f"{self.reserved} reserved slots leave no public slots with max_players = {self.max_players}")

        self.password = env("RESERVED_PASSWORD") or str(own.get("password", ""))
        if not self.password or re.search(r"\s", self.password) or len(self.password) > 128:
            problem("set the reserved password: up to 128 characters, no spaces")

        bump = env("RESERVED_BUMP").lower() or own.get("bump", False)
        self.bump = bump is True or bump == "true"
        order = env("RESERVED_BUMP_ORDER")
        self.bump_order = split_list(order) if order else list(own.get("bump_order") or DEFAULT_BUMP_ORDER)
        unknown = [str(rule) for rule in self.bump_order if rule not in BUMP_RULES]
        if unknown:
            problem(f"unknown bump order rule {', '.join(unknown)} (use {', '.join(BUMP_RULES)})")

        admins = list(toml.get("admins", [])) + list(server.get("admins", []))
        admins += split_list(env("RECLAIMER_DEDICATED_ADMINS"))
        listed = [str(i) for i in own.get("whitelist", [])] + split_list(env("RESERVED_WHITELIST"))
        for entry in listed:
            if not ID_RE.fullmatch(entry):
                say(f"Ignoring '{entry}' in the whitelist: a player ID is 64 hexadecimal characters.")
        self.whitelist = {i.lower() for i in admins + listed if ID_RE.fullmatch(i)}
        if not self.whitelist:
            say("Warning: nobody is whitelisted. Add player IDs to the whitelist or to Admins.")

    @staticmethod
    def load(path):
        try:
            with open(path, "rb") as f:
                return tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError) as e:
            problem(f"could not read {path} ({e})")


# ---- RCON -------------------------------------------------------------------

class Rcon:
    """Runs the server's own `dedicated rcon` client, one process per command."""

    def __init__(self, exe, server_name):
        self.base = ["wine", exe, "dedicated", "rcon"]
        if server_name:
            self.base += ["--server", server_name]

    def command(self, *args, as_json=False):
        cmd = self.base + (["--json"] if as_json else []) + list(args)
        result = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, timeout=30)
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout).strip() or f"exit code {result.returncode}")
        return result.stdout

    def players(self):
        out = self.command("players", as_json=True)
        try:
            return parse_players(json.loads(out))
        except json.JSONDecodeError:
            # Take the last line that parses, should a notice come first.
            for line in reversed(out.splitlines()):
                try:
                    return parse_players(json.loads(line))
                except json.JSONDecodeError:
                    continue
        raise RuntimeError("the players reply wasn't JSON")

    def watch(self):
        cmd = self.base + ["--json", "--watch"]
        return subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, bufsize=1)


class Player:
    def __init__(self, raw, pid):
        self.id = pid
        self.name = str(raw.get("name") or pid[:8])
        self.admin = bool(raw.get("admin") or raw.get("is_admin"))
        score = raw.get("score")
        self.score = score if isinstance(score, (int, float)) else 0
        guests = raw.get("guest_players")
        # Split-screen players count toward max_players.
        self.slots = 1 + (len(guests) if isinstance(guests, list) else 0)


def player_id(node):
    for key in ("player_id", "id", "xuid"):
        value = node.get(key)
        if isinstance(value, str) and ID_RE.fullmatch(value):
            return value.lower()
    return None


def parse_players(reply):
    """Every object in the reply that carries a player ID, outside guest lists."""
    found = []

    def walk(node):
        if isinstance(node, dict):
            pid = player_id(node)
            if pid:
                found.append(Player(node, pid))
                return
            for key, value in node.items():
                if key != "guest_players":
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(reply)
    return found


# ---- the slot keeper --------------------------------------------------------

class SlotKeeper:
    def __init__(self, settings, rcon):
        self.s = settings
        self.rcon = rcon
        self.locked = None          # unknown until set
        self.active = True          # False while slots = 0
        self.watch_proc = None      # the `dedicated rcon --watch` follow_events reads
        self.hold_until = 0.0
        self.joined = {}            # player ID -> when first seen this visit
        self.arrival = {}           # player ID -> order first seen, newest highest
        self.arrivals = 0
        self.last_bump = {}         # whitelisted ID -> when it last caused a bump
        self.totals = self.load_totals()
        self.last_tick = time.monotonic()
        self.last_save = self.last_tick

    def stop_watch(self):
        """End the event stream, so follow_events starts one with the current RCON."""
        proc = self.watch_proc
        if proc and proc.poll() is None:
            proc.terminate()

    # Playtime ---------------------------------------------------------------

    def load_totals(self):
        try:
            return {k: float(v) for k, v in json.loads(PLAYTIME_FILE.read_text()).items()}
        except (OSError, ValueError, AttributeError):
            return {}

    def save_totals(self):
        try:
            PLAYTIME_FILE.parent.mkdir(exist_ok=True)
            tmp = PLAYTIME_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps({k: round(v) for k, v in self.totals.items()}))
            tmp.replace(PLAYTIME_FILE)
        except OSError as e:
            say(f"Could not save playtime ({e}).")

    def track(self, players):
        now = time.monotonic()
        elapsed = now - self.last_tick
        self.last_tick = now
        present = {p.id for p in players}
        for pid in list(self.joined):
            if pid not in present:
                del self.joined[pid]
                del self.arrival[pid]
        for p in players:
            if p.id in self.joined:
                self.totals[p.id] = self.totals.get(p.id, 0.0) + elapsed
            else:
                self.joined[p.id] = now
                self.arrivals += 1
                self.arrival[p.id] = self.arrivals
        if now - self.last_save >= SAVE_SECONDS:
            self.save_totals()
            self.last_save = now

    # Decisions --------------------------------------------------------------

    def whitelisted(self, p):
        return p.admin or p.id in self.s.whitelist

    def rank_key(self, p):
        now = time.monotonic()
        key = []
        for rule in self.s.bump_order:
            if rule == "lowest_score":
                key.append(p.score)
            elif rule == "least_session_time":
                key.append(now - self.joined.get(p.id, now))
            elif rule == "least_total_time":
                key.append(self.totals.get(p.id, 0.0))
        # Ties go to whoever joined last.
        key.append(-self.arrival.get(p.id, 0))
        return key

    def kick(self, p, reason):
        try:
            self.rcon.command("kick", p.id, *reason.split())
        except Exception as e:  # noqa: BLE001 - keep running whatever RCON says
            say(f"Could not kick {p.name}: {e}")
            return False
        return True

    def set_lock(self, locked):
        if locked == self.locked:
            return
        try:
            self.rcon.command("password", self.s.password if locked else "")
        except Exception as e:  # noqa: BLE001
            say(f"Could not {'set' if locked else 'clear'} the join password: {e}")
            self.locked = None
            return
        if locked:
            say("Public slots full: the server now needs the reserved password to join.")
        elif self.locked is not None:
            say("A public slot is free: the server is open again.")
        self.locked = locked

    def check(self):
        players = self.rcon.players()
        self.track(players)
        others = [p for p in players if not self.whitelisted(p)]
        used = sum(p.slots for p in others)

        # Players who aren't whitelisted in reserved slots: newest out first.
        while used > self.s.public and others:
            newest = max(others, key=lambda p: self.arrival.get(p.id, 0))
            if self.kick(newest, KICK_RESERVED):
                say(f"Kicked {newest.name}: they took a reserved slot.")
            others.remove(newest)
            used -= newest.slots

        self.set_lock(used >= self.s.public or time.monotonic() < self.hold_until)
        return players

    def refused(self, pid):
        """A whitelisted player was turned away; make room if the server is full."""
        players = self.rcon.players()
        used = sum(p.slots for p in players)
        if used < self.s.max_players:
            return  # not full, so refused for another reason
        if not self.s.bump:
            say("A whitelisted player was refused from the full server. Bumping is off.")
            return
        now = time.monotonic()
        if now - self.last_bump.get(pid, -BUMP_COOLDOWN_SECONDS) < BUMP_COOLDOWN_SECONDS:
            return
        self.track(players)
        others = [p for p in players if not self.whitelisted(p)]
        if not others:
            say("A whitelisted player was refused, but everyone on the server is whitelisted.")
            return
        target = min(others, key=self.rank_key)
        if self.kick(target, KICK_BUMP):
            self.last_bump[pid] = now
            self.hold_until = now + HOLD_SECONDS
            self.set_lock(True)
            say(f"Bumped {target.name} for a whitelisted player, who can join again now.")


# ---- main loop --------------------------------------------------------------

def follow_events(keeper, inbox):
    """Feeds the main loop from `dedicated rcon --watch`, restarting it if it ends."""
    while True:
        try:
            proc = keeper.watch_proc = keeper.rcon.watch()
            for line in proc.stdout:
                text = line.strip()
                if not text:
                    continue
                kind = text.lower()
                try:
                    event = json.loads(text)
                    if isinstance(event, dict):
                        # Lines read {"type": "event", "event": "join", ...}: the kind is "event".
                        kind = str(event.get("event") or event.get("kind") or event.get("type") or kind).lower()
                except json.JSONDecodeError:
                    pass
                if not any(word in kind for word in EVENT_WORDS):
                    continue
                if "refus" in kind:
                    for pid in ID_RE.findall(text):
                        if pid.lower() in keeper.s.whitelist:
                            inbox.put(("refused", pid.lower()))
                inbox.put(("changed", None))
            proc.wait()
        except Exception as e:  # noqa: BLE001
            say(f"Event stream stopped ({e}); checking every {POLL_SECONDS} seconds meanwhile.")
        time.sleep(RETRY_SECONDS)


def config_stamp():
    """When dedicated.toml and reserved-slots.toml last changed."""
    stamp = []
    for path in (Path("dedicated.toml"), SETTINGS_FILE):
        try:
            stamp.append(path.stat().st_mtime_ns)
        except OSError:
            stamp.append(0)
    return tuple(stamp)


def load_settings(first):
    """New settings, or None (saying why) when the files don't work for reserved slots."""
    try:
        return Settings()
    except SettingsError as e:
        keep = "Reserved slots are off" if first else "Keeping the previous settings"
        say(f"Error: {e}. {keep} until dedicated.toml or reserved-slots.toml is fixed.")
        return None


def apply_settings(fresh, keeper, exe, inbox):
    """Start the keeper, or switch it to new settings. Returns it (None while off from the start)."""
    if fresh.reserved <= 0:
        if keeper is not None and keeper.active:
            keeper.active = False
            keeper.set_lock(False)
        say("Reserved slots are off (slots = 0).")
        return keeper
    if keeper is None:
        keeper = SlotKeeper(fresh, Rcon(exe, fresh.server_name))
        threading.Thread(target=follow_events, args=(keeper, inbox), daemon=True).start()
    else:
        old = keeper.s
        keeper.s = fresh
        keeper.active = True
        if fresh.server_name != old.server_name:
            # Another first server: talk to it from now on.
            keeper.rcon = Rcon(exe, fresh.server_name)
            keeper.locked = None
            keeper.stop_watch()
        elif keeper.locked and fresh.password != old.password:
            keeper.locked = None  # set the new password at the next check
    say(f"{fresh.reserved} of {fresh.max_players} slots reserved for "
        f"{len(fresh.whitelist)} whitelisted player(s); bumping "
        f"{'on (' + ', '.join(fresh.bump_order) + ')' if fresh.bump else 'off'}.")
    return keeper


def main():
    if len(sys.argv) != 2:
        fail("usage: reclaimer-reserved-slots.py <path to project-reclaimer.exe>")
    exe = sys.argv[1]
    inbox = queue.Queue()
    keeper = None
    stamp = None

    down = False
    while True:
        # Saved edits apply without a restart, as they do on the server.
        now_stamp = config_stamp()
        if now_stamp != stamp:
            first = stamp is None
            stamp = now_stamp
            fresh = load_settings(first)
            if fresh is not None:
                if not first:
                    say("Settings changed.")
                keeper = apply_settings(fresh, keeper, exe, inbox)
        if keeper is None or not keeper.active:
            time.sleep(POLL_SECONDS)
            continue
        try:
            refused = set()
            try:
                kind, pid = inbox.get(timeout=POLL_SECONDS)
                if kind == "refused":
                    refused.add(pid)
                while True:  # handle a burst of events at once
                    kind, pid = inbox.get_nowait()
                    if kind == "refused":
                        refused.add(pid)
            except queue.Empty:
                pass
            for pid in refused:
                keeper.refused(pid)
            keeper.check()
            if down:
                say("Server answering again.")
                down = False
        except Exception as e:  # noqa: BLE001
            if not down:
                say(f"Waiting for the server's remote console ({e}).")
                down = True
            # A restarted server has its own password back: set it again.
            keeper.locked = None
            time.sleep(RETRY_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
