# SPDX-License-Identifier: GPL-3.0-or-later
"""fragq: send Quake Live match results to FragQ, the Discord pickup bot, and let players link their
Steam account to Discord from the game.

One file for both minqlx and minqlxtended. Needs a FragQ connector key (FragQ web panel ->
Connectors -> Create connector, game Quake Live). FragQ connectors are in beta.

When a match ends the plugin works out the highlights (Top Damage, Least Damage, Most Damage Taken,
Most Frags, Highest Accuracy, Quitters) and a per-player table, and sends them to FragQ in one request.
FragQ finds the pickup match the players were in and posts the results in its Discord channel.

With qlx_fragqVoice 1 (and a key allowed to move players in voice), the plugin tells FragQ the teams when the
match countdown starts, again when the match starts if the teams changed, and after team changes, and sends
everyone back to the lobby when it ends or is aborted. FragQ moves the players between the queue's voice channels
in Discord; that needs voice moves turned on for the queue. !fragq shows what the last game event did about voice
moves ("Last voice event") and how the last request went; the server log has every one.
Admins can also move players by hand with !voice, for teams arranged in the game, with or without qlx_fragqVoice.

Setup, from the server console or rcon (the key must not be typed in chat):
    qlx !fragq url https://fragq.example.com
    qlx !fragq key fq_...
    qlx !fragq test
or in server.cfg:
    set qlx_fragqUrl "https://fragq.example.com"
    set qlx_fragqKey "fq_..."
A URL and key set with the command are kept in the bot's database and take precedence over the cvars.
Match results are built from the ZMQ stats feed, on minqlx and minqlxtended alike: set zmq_stats_enable 1.
Voice moves, !link and link enforcement work without it.

Commands:
    !link <discord id>               link your Steam account to your Discord account (confirm in Discord)
    !link <player id> <discord id>   the same for another player (permission qlx_fragqAdminLevel);
                                     player id = client id as shown by /players
    !linkenforce [on|off]            keep players without a linked Steam account in spectator (qlx_fragqAdminLevel)
    !setdiscord <invite URL>         the Discord invite shown to players who aren't on the server yet
                                     (qlx_fragqAdminLevel); !setdiscord off removes it
    !voice teams [queue]             move everyone to their team's voice channel now, in warmup too (qlx_voicemoveperm)
    !voice lobby [queue]             move everyone in a team channel back to the lobby (qlx_voicemoveperm)
    !voice <player id> red|blue|lobby [queue]   move one player (qlx_voicemoveperm)
    !fragq                           status, one setting per line (qlx_fragqAdminLevel)
    !fragq queue                     the key's queues (voice moves on or off, which one qlx_fragqQueue picks)
                                     and the Discord server's queues the key doesn't have (qlx_fragqAdminLevel)
    !fragq url <url>                 set the FragQ address (permission 5)
    !fragq key <key>                 set the connector key (permission 5, server console / rcon only)
    !fragq test                      check the connection and the key (permission 5)

Cvars:
    qlx_fragqUrl            FragQ web panel address, e.g. https://fragq.example.com
    qlx_fragqKey            connector key
    qlx_fragqServerName     server name sent with results (default: sv_hostname)
    qlx_fragqResults        1 = send match results (default 1)
    qlx_fragqMinPlayers     fewest players a match needs for its results to be sent (default 2)
    qlx_fragqMinShots       fewest shots for Highest Accuracy (default 50)
    qlx_fragqEnforceLink    1 = unlinked players stay in spectator (default 0; !linkenforce changes it and is remembered)
    qlx_fragqAdminLevel     permission level for !linkenforce, !setdiscord, !fragq and !link for others (default 3)
    qlx_fragqDiscordInvite  Discord invite link shown to players (default empty; !setdiscord changes it and is remembered)
    qlx_fragqVerifyTls      0 = accept a self-signed certificate (default 1)
    qlx_fragqVoice          1 = move players between the queue's Discord voice channels (default 0)
    qlx_voicemoveperm       permission level for !voice (default 4)
    qlx_fragqQueue          the FragQ queue this server plays (default empty: FragQ works it out from the
                            key's queues). Sent with every voice request and result; a queue name typed after
                            !voice takes precedence. Not case-sensitive. Needed when the key has several
                            queues with voice moves on; set it in server.cfg so a restart keeps it.
"""
import collections
import json
import re
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

# The two runtimes are separate forks with their own module name and return-value constants; everything
# else this plugin uses has the same name in both. Handlers that receive extra arguments on minqlxtended
# (team_switch_attempt) take *_ so the same signature registers on both.
try:
    import minqlxtended as ql
    STOP_ALL = ql.Return.STOP_ALL
    RUNTIME = "minqlxtended"
except ImportError:
    import minqlx as ql
    STOP_ALL = ql.RET_STOP_ALL
    RUNTIME = "minqlx"

VERSION = "1.4.0"
DB_URL = "minqlx:fragq:url"
DB_KEY = "minqlx:fragq:key"
DB_ENFORCE = "minqlx:fragq:enforce"
DB_INVITE = "minqlx:fragq:invite"
DB_FRAGDEX_URL = "minqlx:fragdex:url"   # written by fragdex.py; read only here
DB_FRAGDEX_KEY = "minqlx:fragdex:key"
TIMEOUT = 10              # seconds per HTTP request
MAX_RESPONSE = 1 << 20    # bytes of a reply read at most
FRAGDEX_BATCH = 100       # Steam IDs per Fragdex POST /players/lookup (server limit)
QV_CONFIRM_DELAY = 1.5    # seconds after !queueverify's moves to check they stuck (queue plugins react after 0.5 s)
QV_PLAYING = {"started", "waiting_report"}   # teams set and the game on: what the server should match
QV_PRE_GAME = {"init", "check_in", "draft"}  # still in Discord
QV_TAG = "^1QVerify:^7"
WHOIS_COOLDOWN = 3        # between !whois commands of the same player
FINAL_STATS_WAIT = 3      # PLAYER_STATS of everyone still playing arrive just after MATCH_REPORT
RESULT_RETRIES = (5, 30, 120, 600)   # seconds before each new attempt while FragQ is unreachable
MAX_OUTBOX = 10
LINKED_TTL = 600          # a linked player is checked again after this long
UNLINKED_TTL = 15         # an unlinked player can be checked again this soon (they may have just confirmed)
LINK_WATCH = 15 * 60      # after !link, watch for the Discord confirmation this long
LINK_COOLDOWN = 30        # between !link commands of the same player
WARN_COOLDOWN = 20        # between spectator warnings to the same player
LOOKUP_BATCH = 64
VOICE_SETTLE = 3          # seconds after the last team change before the teams are sent
VOICE_COOLDOWN = 5        # between !voice commands
VOICE_TARGETS = {"red", "blue", "lobby"}
COLOR_RE = re.compile(r"\^[0-9]")
STEAM2_RE = re.compile(r"^STEAM_[0-5]:([01]):(\d{1,10})\Z", re.I)
STEAM64_BASE = 76561197960265728
DISCORD_RE = re.compile(r"^(?:\d{15,21}|[A-Za-z0-9_.]{2,32})\Z")
INVITE_RE = re.compile(r"^(?:https?://)?(?:www\.)?(?:discord\.gg|discord(?:app)?\.com/invite)/([A-Za-z0-9-]{2,32})/?\Z", re.I)
# game.type_short of the team modes: a str on minqlx, a Gametype StrEnum on minqlxtended (str() gives the same
# short name). Both use the same names, including "1f" (One Flag CTF) and "ol" (Overload).
TEAM_MODES = {"ca", "tdm", "ctf", "1f", "ol", "ft", "ad", "dom", "har", "rr"}
TEAMS = {0: "Free", 1: "Red", 2: "Blue"}
SKIP_WEAPONS = {"GAUNTLET"}   # melee: hits and shots don't mean accuracy


def _is_steam_id(sid):
    s = str(sid)
    return len(s) == 17 and s.isdigit() and s.startswith("7656119")


def _api_url(url):
    """'fragq.example.com', 'https://host:4443' or the full .../api/connect/v1 URL -> the API base URL, or None."""
    url = (url or "").strip().rstrip("/")
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc or parts.query or parts.fragment:
        return None
    # anything from /api on (/api, /api/v1, a pasted .../api/connect/v1/status) is dropped: the connector API is
    # always <panel address>/api/connect/v1, and a doubled /api/... path is answered "Not logged in."
    path = re.sub(r"/api(/.*)?\Z", "", parts.path.rstrip("/"), flags=re.IGNORECASE)
    return f"{parts.scheme}://{parts.netloc}{path}/api/connect/v1"


def _text(s):
    """Safe for tell(): the QL client reads % as a format code and corrupts its state."""
    return str(s).replace("%", "％")


def _clean(s):
    """Colour codes removed: for logs, database keys, FragQ / Fragdex payloads and lookups. Never for chat."""
    return COLOR_RE.sub("", str(s or ""))


def _plain(s, limit=40):
    """A Discord queue or channel name the QL client can draw: no colour codes, emoji or box characters."""
    return re.sub(r"[^\x20-\x7e]+", "", _clean(s)).strip(" |-_")[:limit] or "?"


def _opt(label, value):
    """One status line: the option in cyan, its setting in white (on/yes green, off/no red)."""
    colour = {"on": "^2", "yes": "^2", "off": "^1", "no": "^1"}.get(str(value), "^7")
    return f"^5{label}:{colour} {value}^7"


def _colored(s):
    """A player name for chat (tell, center_print, msg, channel.reply): ^0-^7 kept, % made safe, and the colour
    reset to white after it so the rest of the line isn't painted in the name's last colour."""
    s = _text(s or "")
    return s + "^7" if COLOR_RE.search(s) else s


def _steam64(token):
    """A SteamID64 or STEAM_X:Y:Z -> the SteamID64 string, or None."""
    s = str(token or "").strip()
    if _is_steam_id(s):
        return s
    m = STEAM2_RE.match(s)
    if m:
        sid = str(STEAM64_BASE + int(m.group(2)) * 2 + int(m.group(1)))
        return sid if _is_steam_id(sid) else None
    return None


def _fragdex_api_url(url):
    """'fragdex.example.com', 'https://host' or '.../api/v1' -> the Fragdex API base URL ending in /api/v1, '' when
    unset, or None when it isn't a web address. The same as fragdex.py's."""
    url = (url or "").strip().rstrip("/")
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc or parts.query or parts.fragment:
        return None
    while url.endswith("/api/v1"):
        url = url[:-len("/api/v1")].rstrip("/")
    return url + "/api/v1"


def _invite(text):
    """A Discord invite link in any usual form -> 'discord.gg/<code>', or None."""
    m = INVITE_RE.match((text or "").strip())
    return f"discord.gg/{m.group(1)}" if m else None


def _int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _team(team):
    """'red', 'blue', 'free', 'spectator' or 'any': minqlx gives strings, minqlxtended Team members."""
    return str(getattr(team, "name", team) or "").lower()


VOICE_WHY = {"not_linked": "not linked", "not_in_voice": "not in voice", "other_channel": "in another voice channel",
             "already_there": "already there", "not_member": "not on the Discord", "no_permission": "bot lacks permission",
             "failed": "failed", "in_series": "in a series"}


def _voice_counts(data):
    """A /voice reply -> (moved, players, queue, why the others weren't moved)."""
    players = data.get("players") or []
    counts = collections.Counter(p.get("status") for p in players)
    moved = counts.pop("moved", 0)
    rest = ", ".join(f"{n} {VOICE_WHY.get(st, st)}" for st, n in counts.most_common())
    return moved, len(players), data.get("queue"), rest


NO_QUEUE = "Send the queue's name in 'queue'."   # FragQ's reply when the key has several voice queues and no match


def _voice_error(error, cfg, manual=False):
    """A failed /voice reply, with what to do in Quake Live terms when FragQ couldn't tell which queue to use."""
    if NO_QUEUE not in error or cfg.get("queue"):
        return error
    how = "set qlx_fragqQueue" + (", or add a queue name after the command" if manual else "")
    return error.replace(NO_QUEUE, f"To fix it, {how} (!fragq queue lists them).")


def _voice_queues(conn):
    """The names of a /status connector's queues with voice moves on, or None for an older FragQ."""
    queues = conn.get("queue_list")
    if not isinstance(queues, list):
        return None
    return [str(q.get("name")) for q in queues if isinstance(q, dict) and q.get("voice")]


def _with_queue(payload, cfg):
    """A voice request with qlx_fragqQueue added, unless !voice named a queue."""
    if cfg.get("queue") and not payload.get("queue"):
        return dict(payload, queue=cfg["queue"])
    return payload


def _num(d, *path):
    for key in path:
        d = d.get(key) if isinstance(d, dict) else None
    return d if isinstance(d, (int, float)) and not isinstance(d, bool) else 0


# ---------------------------------------------------------------- !queueverify: the decision (pure, no game state)

def qverify_plan(roster, on_server, discord_of, lookup_ok=True, protected=()):
    """
    roster:     {discord_id: fragq team 0 / 1 / None} of the FragQ match
    on_server:  [(client_id, steam_id, name, team)] with team 'red' / 'blue' / 'spectator' / ...
    discord_of: {steam_id: discord_id} for the players that could be resolved
    lookup_ok:  False when Fragdex couldn't be asked: then a missing mapping proves nothing
    protected:  subs (!sub), {sub Steam ID: replaced Steam ID or None} (a plain list of Steam IDs is fine too).
                - A sub for a named player takes that player's place in the PUG, with their FragQ team.
                - A sub without one is never moved, and on a team covers one PUG slot.

    Returns a dict:
      switch      [(out_entry, in_entry)]: a non-PUG player on a team and the PUG spectator who takes their slot
      evict       non-PUG players on a team with no PUG spectator to swap with: to spectator
      place       [(entry, 'red'|'blue')]: PUG spectators whose side is known, with nobody there to swap with
      wait        [(entry, reason)]: PUG spectators with nobody to swap with and no known side: prompted
      unverified  entries on a team without a mapping while Fragdex was down (left alone)
      subs        protected subs on a team (left alone)
      covered     PUG spectators not brought in because a sub has their slot
      missing     Discord IDs of the PUG not on the server
      sides       {0: 'red'|'blue', 1: ...} or None, and sides_why when None

    FragQ gives teams as 0/1, not Red/Blue: a side is known only when every PUG player already on a team agrees
    (all of team 0 on one colour, all of team 1 on the other). Anything else is never guessed.
    """
    evict, pull, unverified, subs, present = [], [], [], [], set()
    protected = dict(protected) if isinstance(protected, dict) else dict.fromkeys(protected)
    replaced = {rep: sub for sub, rep in protected.items() if rep}   # replaced Steam ID -> their sub
    member_fq = {}   # Steam ID -> FragQ team of everyone on the server who holds a PUG place
    for entry in on_server:
        _, sid, _, team = entry
        did = discord_of.get(sid)
        playing = team in ("red", "blue")
        if sid in replaced and sid not in protected:     # subbed out: their place went to the sub
            if did in roster:
                present.add(did)
            if playing:
                evict.append(entry)
            continue
        if protected.get(sid):                           # subbed in for a named player: holds their place
            rdid = discord_of.get(protected[sid])
            if rdid in roster:
                present.add(rdid)
            member_fq[sid] = roster.get(rdid)
            if not playing:
                pull.append(entry)
            continue
        if sid in protected and did not in roster:
            if playing:
                subs.append(entry)
            continue
        if did is None:
            if playing:
                (evict if lookup_ok else unverified).append(entry)
            continue
        if did in roster:
            present.add(did)
            member_fq[sid] = roster[did]
            if not playing:
                pull.append(entry)
        elif playing:
            evict.append(entry)

    # FragQ's team 0/1 -> Red/Blue, only from unanimous evidence.
    count = collections.Counter()
    for _, sid, _, team in on_server:
        fq = member_fq.get(sid)
        if fq in (0, 1) and team in ("red", "blue"):
            count[(fq, team)] += 1
    straight = count[(0, "red")] + count[(1, "blue")]
    crossed = count[(0, "blue")] + count[(1, "red")]
    sides, sides_why = None, None
    if straight and not crossed:
        sides = {0: "red", 1: "blue"}
    elif crossed and not straight:
        sides = {0: "blue", 1: "red"}
    elif straight and crossed:
        sides_why = "the PUG's teams are mixed across Red and Blue"
    else:
        sides_why = "no PUG player is on a team yet"

    # Pair each PUG spectator with a player to remove. One whose side is known only takes a slot on that side.
    # A sub for a named player takes exactly that player's slot when they're still on a team.
    out_left, switch, place, wait, unpaired = list(evict), [], [], [], []
    for entry in list(pull):
        partner = next((e for e in out_left if e[1] == protected.get(entry[1])), None)
        if partner is not None:
            out_left.remove(partner)
            pull.remove(entry)
            switch.append((partner, entry))
    for entry in pull:
        fq = member_fq.get(entry[1])
        side = sides[fq] if sides is not None and fq in (0, 1) else None
        if side is not None:
            partner = next((e for e in out_left if e[3] == side), None)
            if partner is not None:
                out_left.remove(partner)
                switch.append((partner, entry))
            else:
                place.append((entry, side))
        else:
            unpaired.append((entry, fq))
    for entry, fq in unpaired:
        if out_left:
            switch.append((out_left.pop(0), entry))
        elif fq not in (0, 1):
            wait.append((entry, "teams not picked in FragQ"))
        else:
            wait.append((entry, sides_why))

    # A sub on a team fills the slot of the PUG player they replaced: don't add that player on top of them.
    covered = []
    for sub in subs:
        hit = next((x for x in place if x[1] == sub[3]), None)
        if hit is not None:
            place.remove(hit)
            covered.append(hit[0])
        elif wait:
            covered.append(wait.pop(0)[0])
    return dict(switch=switch, evict=out_left, place=place, wait=wait, unverified=unverified, subs=subs,
                covered=covered, sides=sides, sides_why=sides_why, member_fq=member_fq,
                missing=[did for did in roster if did not in present])


class fragq(ql.Plugin):
    def __init__(self):
        super().__init__()
        self.set_cvar_once("qlx_fragqUrl", "")
        self.set_cvar_once("qlx_fragqKey", "")
        self.set_cvar_once("qlx_fragqServerName", "")
        self.set_cvar_once("qlx_fragqResults", "1")
        self.set_cvar_once("qlx_fragqMinPlayers", "2")
        self.set_cvar_once("qlx_fragqMinShots", "50")
        self.set_cvar_once("qlx_fragqEnforceLink", "0")
        self.set_cvar_once("qlx_fragqAdminLevel", "3")
        self.set_cvar_once("qlx_fragqDiscordInvite", "")
        self.set_cvar_once("qlx_fragqVerifyTls", "1")
        self.set_cvar_once("qlx_fragqVoice", "0")
        self.set_cvar_once("qlx_voicemoveperm", "4")
        self.set_cvar_once("qlx_fragqQueue", "")
        self.set_cvar_once("qlx_fragqQverifyLevel", "")   # empty: qlx_fragqAdminLevel
        self.set_cvar_once("qlx_fragqWhoisLevel", "0")
        # Shared with fragdex.py; set_cvar_once never overwrites a value it has set.
        self.set_cvar_once("qlx_fragdexUrl", "")
        self.set_cvar_once("qlx_fragdexKey", "")
        self.set_cvar_once("qlx_fragdexVerifyTls", "1")

        # Shared with the worker thread. Cvars and the database are read on the game thread (load_config)
        # and handed over as a plain dict; the stats hook (the ZMQ thread on minqlx, the main thread on minqlxtended) only updates dicts.
        self._lock = threading.Lock()
        self._cfg = {}
        self._match = {}               # steam_id -> stats summed over the player's time in this match
        self._report = None            # MATCH_REPORT data once the match ended
        self._finish_at = 0.0          # when to send it (after the last PLAYER_STATS)
        self._outbox = collections.deque(maxlen=MAX_OUTBOX)   # [payload, attempts, next try]
        self._linked = {}              # steam_id -> (True / False / None = couldn't check, checked at)
        self._lookups = collections.deque(maxlen=1000)
        self._watch = {}               # steam_id -> (client id, until): waiting for a Discord confirmation
        self._warned = {}              # steam_id -> time of the last spectator warning
        self._link_at = {}             # steam_id -> time of the last !link
        self._command_at = 0.0
        self._last = {"time": None, "message": "nothing sent yet"}
        self._voice_due = 0.0          # when to read the teams and send them (after team changes settle)
        self._voice_out = None         # a voice request waiting for the worker
        self._voice_last = "nothing sent yet"
        self._voice_live = False       # teams were sent for a match that hasn't ended: an abort sends the lobby
        self._voice_sent = None        # {team: frozenset of SteamIDs} last sent, so game start doesn't repeat the countdown
        self._voice_event = "none since the plugin loaded"
        self._voice_cmd_at = 0.0
        self._qv_busy = False          # a !queueverify / !sub check is running (set on the game thread, cleared by the worker)
        # !sub: Steam ID -> (raw name, replaced Steam ID or None, replaced raw name or None), game thread only,
        # for the FragQ match in _subs_match. Cleared when !queueverify finds a different match.
        self._subs = {}
        self._subs_match = None
        self._whois_at = {}            # steam_id -> time of the last !whois
        self._stop = threading.Event()
        self._wake = threading.Event()
        self.load_config()

        self.add_hook("stats", self.handle_stats)
        self.add_hook("player_loaded", self.handle_player_loaded)
        self.add_hook("player_disconnect", self.handle_player_disconnect)
        self.add_hook("team_switch_attempt", self.handle_team_switch_attempt)
        self.add_hook("map", self.handle_map)
        self.add_hook("game_countdown", self.handle_game_countdown)
        self.add_hook("game_start", self.handle_game_start)
        self.add_hook("game_end", self.handle_game_end)
        self.add_hook("new_game", self.handle_new_game)
        self.add_hook("team_switch", self.handle_team_switch)
        self.add_hook("unload", self.handle_unload)
        self.add_command("link", self.cmd_link, usage="<discord id> | <player id> <discord id>")
        self.add_command("linkenforce", self.cmd_linkenforce, usage="[on|off]")
        self.add_command("setdiscord", self.cmd_setdiscord, usage="<invite URL> | off")
        self.add_command("fragq", self.cmd_fragq, usage="[url <url> | key <key> | test | queue]")
        self.add_command("voice", self.cmd_voice, usage="teams | lobby | <player id> red|blue|lobby [queue]")
        self.add_command(("queueverify", "qv"), self.cmd_queueverify, usage="[dry|status]")
        self.add_command("sub", self.cmd_sub, usage="<player id> [<player id it replaces>] | off <player id> | clear")
        self.add_command("unsub", self.cmd_unsub, usage="<player id>")
        self.add_command("whois", self.cmd_whois,
                         usage="<player id | Steam ID | Discord id | Discord username | part of a name>")

        self._thread = threading.Thread(target=self._worker, name="fragq", daemon=True)
        self._thread.start()

    # ------------------------------------------------------------ config (game thread)

    def load_config(self):
        try:
            url, key, enforce = self.db.get(DB_URL), self.db.get(DB_KEY), self.db.get(DB_ENFORCE)
            invite = self.db.get(DB_INVITE)
            dex_url, dex_key = self.db.get(DB_FRAGDEX_URL), self.db.get(DB_FRAGDEX_KEY)
        except Exception:  # noqa: BLE001 - no database configured: cvars only
            self.logger.warning("fragq: database unavailable, using the qlx_fragq* cvars")
            url = key = enforce = invite = dex_url = dex_key = None
        admin_level = _int(self.get_cvar("qlx_fragqAdminLevel"), 3)
        cfg = {
            "url": _api_url(url or self.get_cvar("qlx_fragqUrl")) or "",
            "key": (key or self.get_cvar("qlx_fragqKey") or "").strip(),
            "server": _clean(self.get_cvar("qlx_fragqServerName") or self.get_cvar("sv_hostname"))[:80],
            "results": _int(self.get_cvar("qlx_fragqResults"), 1) != 0,
            "min_players": max(1, _int(self.get_cvar("qlx_fragqMinPlayers"), 2)),
            "min_shots": max(1, _int(self.get_cvar("qlx_fragqMinShots"), 50)),
            "enforce": (str(enforce) == "1") if enforce is not None else _int(self.get_cvar("qlx_fragqEnforceLink"), 0) != 0,
            "admin_level": admin_level,
            "qverify_level": _int(self.get_cvar("qlx_fragqQverifyLevel"), admin_level),   # empty: the admin level
            "whois_level": _int(self.get_cvar("qlx_fragqWhoisLevel"), 0),
            # "" in the database: removed with !setdiscord off, don't fall back to the cvar
            "invite": _invite(self.get_cvar("qlx_fragqDiscordInvite")) if invite is None else _invite(invite),
            "verify_tls": _int(self.get_cvar("qlx_fragqVerifyTls"), 1) != 0,
            "voice": _int(self.get_cvar("qlx_fragqVoice"), 0) != 0,
            "voice_perm": _int(self.get_cvar("qlx_voicemoveperm"), 4),
            "queue": " ".join(_clean(self.get_cvar("qlx_fragqQueue")).split())[:60],
            "fragdex_url": _fragdex_api_url(dex_url or self.get_cvar("qlx_fragdexUrl")) or "",
            "fragdex_key": (dex_key or self.get_cvar("qlx_fragdexKey") or "").strip(),
            "fragdex_tls": _int(self.get_cvar("qlx_fragdexVerifyTls"), 1) != 0,
        }
        with self._lock:
            self._cfg = cfg
        return cfg

    def _config(self):
        with self._lock:
            return dict(self._cfg)

    # ------------------------------------------------------------ hooks: O(1), update and return

    def handle_stats(self, stats):
        kind = stats.get("TYPE")
        data = stats.get("DATA") or {}
        if kind == "MATCH_STARTED":
            with self._lock:
                self._match, self._report, self._finish_at = {}, None, 0.0
        elif kind == "PLAYER_STATS":
            if data.get("WARMUP") or data.get("ABORTED"):
                return
            sid = str(data.get("STEAM_ID") or "")
            if not _is_steam_id(sid):
                return   # bots
            hits = shots = 0
            for weapon, w in (data.get("WEAPONS") or {}).items():
                if weapon not in SKIP_WEAPONS:
                    hits += _num(w, "H")
                    shots += _num(w, "S")
            with self._lock:
                p = self._match.setdefault(sid, {"kills": 0, "deaths": 0, "score": 0, "dealt": 0, "taken": 0,
                                                 "time": 0, "hits": 0, "shots": 0})
                for k, v in (("kills", _num(data, "KILLS")), ("deaths", _num(data, "DEATHS")),
                             ("dealt", _num(data, "DAMAGE", "DEALT")), ("taken", _num(data, "DAMAGE", "TAKEN")),
                             ("time", _num(data, "PLAY_TIME")), ("hits", hits), ("shots", shots)):
                    p[k] += v   # a player who left and came back sends one PLAYER_STATS per stretch
                p["score"] = _num(data, "SCORE")
                p["name"] = _clean(data.get("NAME"))[:64] or sid
                p["team"] = _int(data.get("TEAM"), 0)
                p["rank"] = _int(data.get("RANK"), 0)
                p["quit"] = bool(data.get("QUIT"))
        elif kind == "MATCH_REPORT":
            with self._lock:
                if data.get("ABORTED"):
                    self._match, self._report = {}, None
                    return
                self._report = dict(data)
                self._finish_at = time.time() + FINAL_STATS_WAIT
            self._wake.set()

    def handle_player_loaded(self, player):
        if self._cfg.get("enforce") and _is_steam_id(player.steam_id):
            self._lookups.append(str(player.steam_id))
            self._wake.set()

    def handle_player_disconnect(self, player, *_):
        sid = str(player.steam_id)
        self._watch.pop(sid, None)
        self._warned.pop(sid, None)
        self._whois_at.pop(sid, None)

    def handle_team_switch_attempt(self, player, old_team, new_team, *_):
        if not self._cfg.get("enforce") or _team(new_team) == "spectator":
            return
        sid = str(player.steam_id)
        if not _is_steam_id(sid):
            return
        linked, at = self._linked.get(sid, (False, 0))
        if linked or linked is None:   # None: FragQ couldn't be asked, don't lock players out
            return
        if time.time() - at >= UNLINKED_TTL:
            self._lookups.append(sid)
            self._wake.set()
        player.tell(_text(self._warning(sid, at)))
        return STOP_ALL

    def handle_map(self, *_):
        self.load_config()   # picks up cvars changed since the last map
        with self._lock:
            self._match, self._report, self._finish_at = {}, None, 0.0
            self._voice_due, self._voice_out = 0.0, None
        self._voice_live, self._voice_sent = False, None

    # Voice moves follow the match: teams when the countdown starts (game_countdown, () on both runtimes), again at
    # game_start if they changed, after team changes, the lobby at game_end or an abort. game_start: (data) on
    # minqlx, () on minqlxtended; game_end: (data) on minqlx, (aborted) on minqlxtended; new_game: () on both. No
    # argument is needed, so *_ registers on both. Some minqlxtended builds never raise game_start; the countdown
    # covers them.
    def handle_game_countdown(self, *_):
        self.load_config()   # a qlx_fragqVoice or qlx_fragqQueue set in warmup counts from this match
        self._send_teams("countdown")

    def handle_game_start(self, *_):
        self._send_teams("match start", repeat=False)

    def handle_game_end(self, *_):
        self._voice_live, self._voice_sent = False, None
        if not self._cfg.get("voice"):
            self._note_voice("match end", "nothing sent, qlx_fragqVoice is 0")
            return
        teams, why = self._voice_teams()
        with self._lock:
            self._voice_due = 0.0
        if not teams:
            self._note_voice("match end", f"nothing sent, {why}")
            return
        lobby = [sid for ids in teams["teams"].values() for sid in ids]
        self._queue_voice({"lobby": lobby}, "match end")
        self._note_voice("match end", f"sending {len(lobby)} player(s) to the lobby")

    def handle_new_game(self, *_):
        # !abort and abort votes restart the map: new_game in warmup, and game_end never comes. A match starting
        # restarts the map too, so the state is read a second later, when a starting match is in progress.
        if self._voice_live:
            self._check_abort()

    @ql.delay(1)
    def _check_abort(self):
        if not self._voice_live or self._state() != "warmup":
            return
        self._voice_live, self._voice_sent = False, None
        if not self._cfg.get("voice"):
            return
        with self._lock:
            self._voice_due = 0.0
        lobby = self._everyone()
        if lobby:
            self._queue_voice({"lobby": lobby}, "abort")
            self._note_voice("abort", f"sending {len(lobby)} player(s) to the lobby")

    def handle_team_switch(self, player, old_team, new_team):
        if self._cfg.get("voice") and self._state() in ("countdown", "in_progress"):
            with self._lock:   # read the teams once the changes settle: one request for a whole shuffle
                self._voice_due = time.time() + VOICE_SETTLE
            self._wake.set()

    def _state(self):
        try:
            return str(getattr(self.game.state, "name", self.game.state)).lower()
        except Exception:  # noqa: BLE001 - NonexistentGameError between maps
            return ""

    def _in_progress(self):
        return self._state() == "in_progress"

    def _note_voice(self, event, outcome):
        """What a game event did about voice moves: !fragq shows the last one, the server log has them all."""
        self._voice_event = f"{time.strftime('%H:%M')} {event}: {outcome}"
        self.logger.info(f"fragq: voice, {event}: {outcome}")

    def _send_teams(self, event, repeat=True):
        """Read the teams and hand them to the worker, or note why not (game thread)."""
        if not self._cfg.get("voice"):
            self._note_voice(event, "nothing sent, qlx_fragqVoice is 0")
            return
        teams, why = self._voice_teams()
        if not teams:
            self._note_voice(event, f"nothing sent, {why}")
            return
        self._voice_live = True
        sent = {team: frozenset(ids) for team, ids in teams["teams"].items()}
        if not repeat and sent == self._voice_sent:
            self._note_voice(event, "teams unchanged since they were sent, not sent again")
            return
        self._voice_sent = sent
        self._queue_voice(teams, event)
        self._note_voice(event, f"sending red {len(sent['red'])}, blue {len(sent['blue'])}")

    def _voice_teams(self):
        """({"teams": {"red": [...], "blue": [...]}}, None) of a team game, or (None, why not) (game thread)."""
        try:
            mode = str(self.game.type_short).lower()
        except Exception:  # noqa: BLE001 - NonexistentGameError
            return None, "no game loaded"
        if mode not in TEAM_MODES:
            return None, f"{mode} isn't a team mode"
        teams = {"red": [], "blue": []}
        bots = 0
        for p in self.players():
            team, sid = _team(p.team), str(p.steam_id)
            if team in teams:
                if _is_steam_id(sid):
                    teams[team].append(sid)
                else:
                    bots += 1
        if teams["red"] or teams["blue"]:
            return {"teams": teams}, None
        return None, f"only bots on red and blue ({bots})" if bots else "nobody on red or blue"

    def _everyone(self):
        """The SteamIDs of everyone on the server, spectators too (game thread)."""
        return [str(p.steam_id) for p in self.players() if _is_steam_id(p.steam_id)][:64]

    def _queue_voice(self, payload, label):
        if payload:
            with self._lock:
                self._voice_out = (payload, label)
            self._wake.set()

    @ql.next_frame
    def _voice_snapshot(self):
        """The teams after a team change, read on the game thread for the worker to send."""
        if self._state() in ("countdown", "in_progress"):
            self._send_teams("team change", repeat=False)

    def handle_unload(self, plugin):
        if plugin == self.__class__.__name__:
            self._stop.set()
            self._wake.set()

    def _warning(self, sid, checked_at):
        if not checked_at:
            return "^1FragQ:^7 checking your linked Steam account, try again in a few seconds."
        invite = self._cfg.get("invite")
        return ("^1FragQ:^7 this server needs a Steam account linked to Discord. You stay in spectator until it is "
                "linked: type ^5!link <your Discord id>^7 and confirm in Discord."
                + (f" Not on our Discord yet? Join ^5{invite}^7 first." if invite else ""))

    def _join_hint(self):
        invite = self._cfg.get("invite")
        return f"^1FragQ:^3 not on our Discord yet? Join ^5{invite}^3, then type ^5!link^3 again." if invite else None

    # ------------------------------------------------------------ commands (game thread)

    def cmd_link(self, player, msg, channel):
        cfg = self._cfg
        console = getattr(channel, "name", "") == "console"
        if len(msg) not in (2, 3):
            player.tell("^1FragQ:^7 usage: ^5!link <your Discord id>^7. Find it in Discord: Settings -> Advanced -> "
                        "Developer Mode, then right-click your name -> Copy User ID.")
            return STOP_ALL
        target = None if console else player
        if len(msg) == 3:
            cid = msg[1]
            try:
                found = self.player(int(cid)) if cid.isdigit() and int(cid) < 64 else None
            except Exception:  # noqa: BLE001 - NonexistentPlayerError on either runtime
                found = None
            if found is None:
                player.tell(_text(f"^1FragQ:^7 no player with id {cid[:10]}. Player ids are shown by /players."))
                return STOP_ALL
            if not console and found.id != player.id and not self.db.has_permission(player, cfg.get("admin_level", 3)):
                player.tell("^1FragQ:^7 you can only link your own Steam account: ^5!link <your Discord id>^7")
                return STOP_ALL
            target = found
        if target is None:
            player.tell("^1FragQ:^7 from the console, name the player: !link <player id> <discord id>")
            return STOP_ALL
        discord = msg[-1].strip().lstrip("@")
        if not DISCORD_RE.match(discord):
            player.tell("^1FragQ:^7 that isn't a Discord user id (a long number) or username.")
            return STOP_ALL
        sid = str(target.steam_id)
        if not _is_steam_id(sid):
            player.tell("^1FragQ:^7 that player has no Steam account to link.")
            return STOP_ALL
        now = time.time()
        if now - self._link_at.get(sid, 0) < LINK_COOLDOWN:
            player.tell(f"^1FragQ:^7 wait {int(LINK_COOLDOWN - (now - self._link_at[sid])) + 1}s.")
            return STOP_ALL
        self._link_at[sid] = now
        player.tell("^1FragQ:^7 asking FragQ...")
        self._request_link(self._reply_target(player, channel), (target.id, sid), _clean(target.name), discord)
        return STOP_ALL

    def cmd_linkenforce(self, player, msg, channel):
        cfg = self._cfg
        if not self.db.has_permission(player, cfg.get("admin_level", 3)):
            player.tell("^1FragQ:^7 you don't have permission to change that.")
            return STOP_ALL
        if len(msg) < 2:
            on = not cfg.get("enforce")
        elif msg[1].lower() in ("on", "1", "yes"):
            on = True
        elif msg[1].lower() in ("off", "0", "no"):
            on = False
        else:
            player.tell("^1FragQ:^7 usage: !linkenforce [on|off]")
            return STOP_ALL
        try:
            self.db.set(DB_ENFORCE, "1" if on else "0")
        except Exception:  # noqa: BLE001 - no database: only until the next map
            self.set_cvar("qlx_fragqEnforceLink", "1" if on else "0")
        self.load_config()
        if on:
            self.msg("^1FragQ:^7 linked Steam accounts are now required to play. Players without one are moved to "
                     "spectator: type ^5!link <your Discord id>^7 to link yours.")
            with self._lock:
                self._linked = {}   # check everyone again
            for p in self.players():
                if _is_steam_id(p.steam_id):
                    self._lookups.append(str(p.steam_id))
            self._wake.set()
        else:
            self.msg("^1FragQ:^7 linked Steam accounts are no longer required to play.")
        return STOP_ALL

    def cmd_setdiscord(self, player, msg, channel):
        cfg = self._cfg
        if not self.db.has_permission(player, cfg.get("admin_level", 3)):
            player.tell("^1FragQ:^7 you don't have permission to change that.")
            return STOP_ALL
        if len(msg) < 2:
            current = cfg.get("invite")
            player.tell(_text(f"^1FragQ:^7 Discord invite: ^5{current}^7. Change it with !setdiscord <invite URL>, remove it with !setdiscord off."
                              if current else "^1FragQ:^7 no Discord invite set. Usage: !setdiscord <invite URL>, such as https://discord.gg/abc123"))
            return STOP_ALL
        if msg[1].lower() in ("off", "none", "clear", "remove"):
            value, invite = "", None
        else:
            invite = _invite(msg[1])
            if not invite:
                player.tell("^1FragQ:^7 that isn't a Discord invite link. Use one like https://discord.gg/abc123 "
                            "(Discord: right-click the server -> Invite People; make it never expire).")
                return STOP_ALL
            value = invite
        try:
            self.db.set(DB_INVITE, value)
        except Exception:  # noqa: BLE001 - no database: only until the next map
            self.set_cvar("qlx_fragqDiscordInvite", value)
        self.load_config()
        player.tell(_text(f"^1FragQ:^7 players who aren't on the Discord are now told to join ^5{invite}^7." if invite
                          else "^1FragQ:^7 Discord invite removed."))
        return STOP_ALL

    def cmd_fragq(self, player, msg, channel):
        sub = msg[1].lower() if len(msg) > 1 else "status"
        cfg = self._cfg
        if sub in ("url", "key", "test") and not self.db.has_permission(player, 5):
            player.tell("^1FragQ:^7 that needs permission level 5.")
            return STOP_ALL
        if sub == "key" and getattr(channel, "name", "") != "console":
            # whatever was typed has already reached the server as chat: refuse it, and ask for a new key
            player.tell("^1FragQ:^7 set the key from the server console or rcon: ^5qlx !fragq key <key>^7. "
                        "If you just typed a key in chat, replace it on the FragQ Connectors page.")
            return STOP_ALL
        if sub in ("url", "key"):
            if len(msg) < 3:
                player.tell(f"^1FragQ:^7 usage: !fragq {sub} <{'address' if sub == 'url' else 'connector key'}>")
                return STOP_ALL
            value = msg[2].strip()
            if sub == "url":
                url = _api_url(value)
                if not url:
                    player.tell("^1FragQ:^7 that is not a web address, e.g. https://fragq.example.com")
                    return STOP_ALL
                self.db.set(DB_URL, url)
                player.tell(_text(f"^1FragQ:^7 address set to ^5{url}^7. Run ^5!fragq test^7 to check it."))
            else:
                if not re.fullmatch(r"fq_[A-Za-z0-9_-]{20,100}\Z", value):
                    player.tell("^1FragQ:^7 that is not a FragQ connector key (they start with fq_).")
                    return STOP_ALL
                self.db.set(DB_KEY, value)
                player.tell(f"^1FragQ:^7 key set ({value[:9]}...). Run ^5!fragq test^7 to check it.")
            self.load_config()
            self._wake.set()
            return STOP_ALL
        if sub == "test":
            now = time.time()
            if now - self._command_at < 5:
                player.tell("^1FragQ:^7 wait a few seconds.")
                return STOP_ALL
            self._command_at = now
            self.load_config()
            self._test(self._reply_target(player, channel))
            return STOP_ALL
        if not self.db.has_permission(player, cfg.get("admin_level", 3)):
            player.tell("^1FragQ:^7 you don't have permission to see the FragQ settings.")
            return STOP_ALL
        if sub == "queue":
            now = time.time()
            if now - self._command_at < 5:
                player.tell("^1FragQ:^7 wait a few seconds.")
                return STOP_ALL
            self._command_at = now
            self._list_queues(self._reply_target(player, channel))
            return STOP_ALL
        with self._lock:
            last = dict(self._last)
        lines = [
            f"^1FragQ^7 {VERSION} on {RUNTIME}",
            _opt("Address", cfg.get("url") or "^1not set"),
            _opt("Key", cfg["key"][:9] + "..." if cfg.get("key") else "^1not set"),
            _opt("Results", "on" if cfg.get("results") else "off"),
            _opt("Last result", f"{last['time'] or 'never'} ({last['message']}), {len(self._outbox)} waiting"),
            _opt("Link required", "yes" if cfg.get("enforce") else "no"),
            _opt("Discord invite", cfg.get("invite") or "not set"),
            _opt("Queue", cfg.get("queue") or "not set (^5!fragq queue^7 lists them)"),
            _opt("Auto voice moves", "on" if cfg.get("voice") else "off"),
            _opt("Last voice event", self._voice_event),
            _opt("Last voice request", self._voice_last),
        ]
        for line in lines:
            player.tell(_text(line))
        return STOP_ALL

    def cmd_voice(self, player, msg, channel):
        cfg = self._cfg
        if not self.db.has_permission(player, cfg.get("voice_perm", 4)):
            player.tell(f"^1FragQ:^7 !voice needs permission level {cfg.get('voice_perm', 4)}.")
            return STOP_ALL
        usage = ("^1FragQ:^7 usage: ^5!voice teams^7 (everyone to their team's channel), ^5!voice lobby^7, or "
                 "^5!voice <player id> red|blue|lobby^7. Add a queue name at the end if the key has several queues.")
        args = msg[1:]
        if not args:
            player.tell(usage)
            return STOP_ALL
        what = args[0].lower()
        if what in ("teams", "lobby"):
            rest = args[1:]
            if what == "teams":
                payload, why = self._voice_teams()
                if not payload:
                    player.tell(_text(f"^1FragQ:^7 nothing to send: {why}."))
                    return STOP_ALL
                label = "teams"
            else:
                lobby = self._everyone()
                if not lobby:
                    player.tell("^1FragQ:^7 nobody to move.")
                    return STOP_ALL
                payload, label = {"lobby": lobby}, "lobby"
        elif what.isdigit() and len(args) >= 2:
            target, rest = args[1].lower(), args[2:]
            if target not in VOICE_TARGETS:
                player.tell(usage)
                return STOP_ALL
            try:
                found = self.player(int(what)) if int(what) < 64 else None
            except Exception:  # noqa: BLE001 - NonexistentPlayerError on either runtime
                found = None
            if found is None or not _is_steam_id(found.steam_id):
                player.tell(_text(f"^1FragQ:^7 no player with id {what[:10]}. Player ids are shown by /players."))
                return STOP_ALL
            sid = str(found.steam_id)
            payload = {"lobby": [sid]} if target == "lobby" else {"teams": {target: [sid]}}
            label = f"{_clean(found.name)[:32]} to {target}"
        else:
            player.tell(usage)
            return STOP_ALL
        if rest:   # FragQ matches queue names in any case; this takes precedence over qlx_fragqQueue
            payload["queue"] = " ".join(rest)[:60]
        now = time.time()
        if now - self._voice_cmd_at < VOICE_COOLDOWN:
            player.tell(f"^1FragQ:^7 wait {int(VOICE_COOLDOWN - (now - self._voice_cmd_at)) + 1}s.")
            return STOP_ALL
        self._voice_cmd_at = now
        player.tell("^1FragQ:^7 asking FragQ to move players...")
        self._manual_voice(self._reply_target(player, channel), payload, label)
        return STOP_ALL

    @staticmethod
    def _reply_target(player, channel):
        """Something a worker thread can reply to safely later: the console channel, or a player's
        client id + Steam ID so the reply can't reach whoever takes over the slot after they leave."""
        if getattr(channel, "name", "") == "console":
            return ("console", channel)
        return ("player", player.id, str(player.steam_id))

    # ------------------------------------------------------------ HTTP (worker threads only)

    def _request(self, cfg, method, path, body=None):
        """FragQ connector API. Returns (data, error, status). Never raises."""
        if not cfg.get("url") or not cfg.get("key"):
            return None, "FragQ address or connector key not set (!fragq url / !fragq key)", 0
        return self._http(cfg["url"], cfg["key"], cfg.get("verify_tls", True), method, path, body)

    def _fragdex(self, cfg, method, path, body=None):
        """Fragdex API (a different service, key and reply shape from FragQ). Returns (data, error, status)."""
        if not cfg.get("fragdex_url") or not cfg.get("fragdex_key"):
            return None, "Fragdex address or key not set (qlx_fragdexUrl / qlx_fragdexKey)", 0
        return self._http(cfg["fragdex_url"], cfg["fragdex_key"], cfg.get("fragdex_tls", True), method, path, body)

    @staticmethod
    def _http(base, key, verify_tls, method, path, body=None):
        """Returns (data, error, status), data always a dict. Never raises. Status 0: no HTTP answer at all."""
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(base + path, data=data, method=method, headers={
            "Authorization": "Bearer " + key, "Content-Type": "application/json",
            "Accept": "application/json", "User-Agent": f"fragq-{RUNTIME}/{VERSION}"})
        ctx = None if verify_tls else ssl._create_unverified_context()  # noqa: S323 - opt-in
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
                raw, status = resp.read(MAX_RESPONSE + 1), resp.status
            if len(raw) > MAX_RESPONSE:
                return None, "the answer was too large", status
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                return None, "the answer wasn't a JSON object", status
            return payload, None, status
        except urllib.error.HTTPError as e:
            try:
                reply = json.loads(e.read(65536).decode("utf-8"))
                msg = (reply.get("error") or reply.get("detail") or e.reason) if isinstance(reply, dict) else e.reason
            except Exception:  # noqa: BLE001 - not a JSON reply (proxy page etc.)
                msg = e.reason
            retry = e.headers.get("Retry-After") if e.headers else None
            return None, f"HTTP {e.code}: {msg}" + (f" (retry after {retry}s)" if retry else ""), e.code
        except Exception as e:  # noqa: BLE001 - network errors, bad JSON, TLS
            return None, str(getattr(e, "reason", e))[:200], 0

    def _worker(self):
        next_watch = 0.0
        while not self._stop.is_set():
            with self._lock:   # a finished match is sent FINAL_STATS_WAIT after its MATCH_REPORT
                wait = max(0.0, self._finish_at - time.time()) if self._report is not None else 5.0
                if self._voice_due:
                    wait = min(wait, max(0.0, self._voice_due - time.time()))
            if wait:
                self._wake.wait(min(wait, 5.0))
            self._wake.clear()
            cfg = self._config()
            try:
                self._finish_match(cfg)
                if self._outbox:
                    self._send_results(cfg)
                now = time.time()
                if self._watch and now >= next_watch:
                    next_watch = now + 10
                    for sid, (_, until) in list(self._watch.items()):
                        if now > until:
                            self._watch.pop(sid, None)
                        else:
                            self._lookups.append(sid)
                if self._lookups:
                    self._run_lookups(cfg)
                self._run_voice(cfg)
            except Exception:  # noqa: BLE001 - keep the worker alive whatever a reply contains
                self.logger.exception("fragq: worker error")

    def _finish_match(self, cfg):
        with self._lock:
            if self._report is None or time.time() < self._finish_at:
                return
            report, players = self._report, self._match
            self._report, self._match = None, {}
        payload = self._build(cfg, report, players)
        if payload:
            self._outbox.append([payload, 0, 0.0])
        elif cfg.get("results"):
            self.logger.info("fragq: the match had too few players, no results sent")

    # ------------------------------------------------------------ results

    def _build(self, cfg, report, players):
        """The FragQ result for a finished match, or None when there is nothing worth posting."""
        if not cfg.get("results"):
            return None
        mode = str(report.get("GAME_TYPE") or "").lower()
        played = {sid: p for sid, p in players.items() if p.get("team") in (0, 1, 2) and (p["time"] > 0 or p["quit"])}
        if len(played) < cfg.get("min_players", 2):
            return None
        length = _int(report.get("GAME_LENGTH"), 0)
        teams_on = mode in TEAM_MODES and any(p["team"] in (1, 2) for p in played.values())

        def acc(p):
            return 100.0 * p["hits"] / p["shots"] if p["shots"] else 0.0

        def best(label, key, pool, lowest=False, fmt="{:,}"):
            pool = [(sid, key(p)) for sid, p in pool.items()]
            if not pool:
                return None
            top = (min if lowest else max)(v for _, v in pool)
            return {"label": label, "players": [sid for sid, v in pool if v == top][:16], "value": fmt.format(top)}

        stayed = {sid: p for sid, p in played.items() if not p["quit"]}
        full = {sid: p for sid, p in stayed.items() if not length or p["time"] >= length / 2}
        aimed = {sid: p for sid, p in played.items() if p["shots"] >= cfg.get("min_shots", 50)}
        quitters = [sid for sid, p in played.items() if p["quit"]]
        highlights = [h for h in (
            best("Top Damage", lambda p: p["dealt"], played),
            best("Least Damage", lambda p: p["dealt"], full or stayed, lowest=True),
            best("Most Damage Taken", lambda p: p["taken"], played),
            best("Most Frags", lambda p: p["kills"], played),
            best("Highest Accuracy", acc, aimed, fmt="{:.1f}%"),
        ) if h]
        if not teams_on:
            winner = [sid for sid, p in stayed.items() if p.get("rank") == 1]
            if winner:
                highlights.insert(0, {"label": "Winner", "players": winner[:16]})
        highlights.append({"label": "Quitters", "players": quitters[:16]} if quitters else {"label": "Quitters", "value": "None"})

        order = sorted(played.items(), key=lambda kv: (kv[1]["quit"], -kv[1]["score"]))
        out = {
            "version": 1, "match_uid": str(report.get("MATCH_GUID") or "") or None, "game": "Quake Live",
            "map": str(report.get("MAP") or "") or None, "mode": mode.upper() or None,
            "duration": length or None, "server": cfg.get("server") or None, "queue": cfg.get("queue") or None,
            "players": [{
                "id": sid, "id_type": "steam", "name": p["name"], "quit": p["quit"],
                "team": TEAMS.get(p["team"]) if teams_on else None,
                "stats": {"Score": p["score"], "K": p["kills"], "D": p["deaths"], "Dmg": p["dealt"],
                          "Taken": p["taken"], "Acc": f"{acc(p):.0f}%" if p["shots"] else "-"},
            } for sid, p in order],
            "highlights": highlights,
            "table": ["Score", "K", "D", "Dmg", "Acc"],
        }
        if teams_on:
            red, blue = _int(report.get("TSCORE0"), 0), _int(report.get("TSCORE1"), 0)
            out["teams"] = [{"name": "Red", "score": red}, {"name": "Blue", "score": blue}]
            out["winner"] = "Red" if red > blue else "Blue" if blue > red else None
        return out

    def _send_results(self, cfg):
        now = time.time()
        for item in list(self._outbox):
            payload, attempts, next_try = item
            if now < next_try:
                continue
            data, error, status = self._request(cfg, "POST", "/results", payload)
            stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            if error is None:
                self._outbox.remove(item)
                where = f"match #{data.get('match_id')}" if data.get("match_id") else "no FragQ match"
                message = f"{data.get('status')} ({where})"
            elif 400 <= status < 500 and status not in (408, 429):
                self._outbox.remove(item)   # FragQ refused it: sending it again won't help
                message = error + "; result dropped"
            elif attempts >= len(RESULT_RETRIES):
                self._outbox.remove(item)
                message = error + "; result dropped after retries"
            else:
                item[1], item[2] = attempts + 1, now + RESULT_RETRIES[attempts]
                message = error + f"; retrying in {RESULT_RETRIES[attempts]}s"
            with self._lock:
                self._last = {"time": stamp, "message": message}
            (self.logger.info if error is None else self.logger.warning)(f"fragq: match results: {message}")

    # ------------------------------------------------------------ voice moves

    def _run_voice(self, cfg):
        with self._lock:
            due = self._voice_due and time.time() >= self._voice_due
            if due:
                self._voice_due = 0.0
            item, self._voice_out = self._voice_out, None
        if due:
            self._voice_snapshot()   # comes back through _voice_out
        if not item:
            return
        payload, label = item
        stamp = time.strftime('%H:%M')
        if not cfg.get("voice"):
            self._voice_last = f"{stamp} {label}: not sent, qlx_fragqVoice is 0"
            return
        data, error, _ = self._request(cfg, "POST", "/voice", _with_queue(payload, cfg))
        if error:
            error = _voice_error(error, cfg)
            self.logger.warning(f"fragq: voice move request ({label}) failed: {error}")
            self._voice_last = f"{stamp} {label} failed: {error}"
            return
        moved, total, queue, rest = _voice_counts(data)
        summary = f"{moved} of {total} moved ({queue})" + (f": {rest}" if rest else "")
        self.logger.info(f"fragq: voice request ({label}): {summary}")
        self._voice_last = f"{stamp} {label}: {summary}"

    @ql.thread
    def _manual_voice(self, reply_to, payload, label):
        """!voice: one request now, whatever qlx_fragqVoice says."""
        cfg = self._config()
        data, error, _ = self._request(cfg, "POST", "/voice", _with_queue(payload, cfg))
        stamp = time.strftime('%H:%M')
        if error:
            error = _voice_error(error, cfg, manual=True)
            self._voice_last = f"{stamp} !voice {label} failed: {error}"
            self._reply(reply_to, f"^1FragQ:^7 voice move failed: {error}")
            return
        moved, total, queue, rest = _voice_counts(data)
        self._voice_last = f"{stamp} !voice {label}: {moved} of {total} moved ({queue})" + (f": {rest}" if rest else "")
        self._reply(reply_to, f"^1FragQ:^7 {'^2' if moved else '^3'}{moved} of {total} moved^7 ({queue})"
                              + (f": {rest}." if rest else "."))

    # ------------------------------------------------------------ linked players

    def _run_lookups(self, cfg):
        now = time.time()
        ids = []
        while self._lookups and len(ids) < LOOKUP_BATCH:
            sid = self._lookups.popleft()
            linked, at = self._linked.get(sid, (False, 0))
            ttl = LINKED_TTL if linked else UNLINKED_TTL
            if sid not in ids and (now - at >= ttl or sid in self._watch):
                ids.append(sid)
        if not ids:
            return
        data, error, _ = self._request(cfg, "POST", "/players/linked", {"steam_ids": ids})
        if error:
            self.logger.warning(f"fragq: linked-player check failed: {error}")
            with self._lock:
                for sid in ids:
                    self._linked[sid] = (None, now)   # don't keep players out while FragQ can't be asked
            return
        unlinked, confirmed = [], []
        with self._lock:
            for p in data.get("players") or []:
                sid = str(p.get("steam_id"))
                self._linked[sid] = (bool(p.get("linked")), now)
                if p.get("linked") and sid in self._watch:
                    confirmed.append((self._watch.pop(sid)[0], sid, p.get("discord_name") or "Discord"))
                elif not p.get("linked"):
                    unlinked.append(sid)
            if len(self._linked) > 2000:
                self._linked = {k: v for k, v in self._linked.items() if now - v[1] < LINKED_TTL}
        for client_id, sid, name in confirmed:
            self._tell_players([(client_id, sid)], _text(f"^1FragQ:^7 ^2linked^7 to {name}. You can join a team now."))
        if unlinked and cfg.get("enforce"):
            self._enforce(unlinked)

    @ql.next_frame
    def _enforce(self, steam_ids):
        """Move unlinked players who are playing to spectator, with a warning (game thread)."""
        if not self._cfg.get("enforce"):
            return
        now = time.time()
        wanted = set(steam_ids)
        for p in self.players():
            sid = str(p.steam_id)
            if sid not in wanted:
                continue
            if _team(p.team) != "spectator":
                try:
                    p.put("spectator")
                except Exception:  # noqa: BLE001 - minqlxtended may want its Team member
                    p.put(ql.Team.SPECTATOR)
            if now - self._warned.get(sid, 0) >= WARN_COOLDOWN:
                self._warned[sid] = now
                p.tell(_text(self._warning(sid, now)))
                invite = self._cfg.get("invite")
                p.center_print("^1Link your Steam account to play: ^7!link <your Discord id>" + (f"\n^7Discord: ^5{invite}" if invite else ""))

    @ql.thread
    def _request_link(self, reply_to, who, name, discord):
        client_id, sid = who
        data, error, _ = self._request(self._config(), "POST", "/link", {"steam_id": sid, "name": name, "discord": discord})
        if error:
            self._reply(reply_to, f"^1FragQ:^7 couldn't reach FragQ: {error}")
            return
        message = data.get("message") or data.get("status") or "done"
        if data.get("status") == "sent":
            self._watch[sid] = (client_id, time.time() + LINK_WATCH)
            self._wake.set()
        elif data.get("status") == "already_linked":
            with self._lock:
                self._linked[sid] = (True, time.time())
        colour = "^2" if data.get("ok") else "^3"
        lines = [f"^1FragQ:^7 {colour}{message}"]
        if data.get("status") == "not_member" and self._join_hint():
            lines.append(self._join_hint())
        self._reply(reply_to, *lines)

    @ql.thread
    def _test(self, reply_to):
        data, error, _ = self._request(self._config(), "GET", "/status")
        if error:
            self._reply(reply_to, f"^1FragQ:^7 connection failed: {error}")
            return
        c = data.get("connector") or {}
        can = c.get("can") or {}
        missing = [what for what, ok in (("results", can.get("results")), ("linked-player checks", can.get("check")),
                                         ("!link", can.get("link"))) if not ok]
        if self._config().get("voice") and not can.get("voice"):
            missing.append("voice moves")
        warn = f" ^3This key isn't allowed: {', '.join(missing)}.^7" if missing else ""
        queue = self._config().get("queue")
        names = [str(n) for n in c.get("queues") or []]
        if queue:
            same = [n for n in names if n.casefold() == queue.casefold()]
            if not same:
                warn += f" ^3qlx_fragqQueue is '{queue}', but this key has no queue of that name.^7"
            elif len(same) > 1:
                warn += f" ^3This key has {len(same)} queues named '{queue}'; give each server its own connector.^7"
        elif can.get("voice") and len(_voice_queues(c) or []) > 1:
            warn += (" ^3Several of this key's queues have voice moves on; set qlx_fragqQueue so voice moves "
                     "know which one to use (^5!fragq queue^3 lists them).^7")
        self._reply(reply_to, f"^1FragQ:^7 connected to FragQ {data.get('fragq_version')} as '{c.get('name')}' "
                              f"({c.get('game')}), queues: {', '.join(c.get('queues') or []) or 'none'}.{warn}")

    @ql.thread
    def _list_queues(self, reply_to):
        """!fragq queue: the key's queues and the Discord server's others, from GET /status."""
        cfg = self._config()
        data, error, _ = self._request(cfg, "GET", "/status")
        if error:
            self._reply(reply_to, f"^1FragQ:^7 connection failed: {error}")
            return
        c = data.get("connector") or {}
        mine = c.get("queue_list")
        if not isinstance(mine, list):   # an older FragQ: names only
            mine = [{"name": n} for n in c.get("queues") or []]
        mine = [q for q in mine if isinstance(q, dict)]
        others = [q for q in c.get("other_queues") or [] if isinstance(q, dict)]
        want = (cfg.get("queue") or "").casefold()
        lines = [f"^1FragQ:^7 queues of the key ^5{_plain(c.get('name'), 60)}^7:" if mine else
                 "^1FragQ:^7 this key has no queues. Tick them on the connector in FragQ's Connectors page."]
        for q in mine[:20]:
            line = f"  ^5{_plain(q.get('name'))}^7"
            if q.get("channel"):
                line += f" in #{_plain(q['channel'])}"
            if "voice" in q:
                line += f", voice moves {'^2on' if q['voice'] else '^1off'}^7"
            if want and str(q.get("name", "")).casefold() == want:
                line += " ^3<- qlx_fragqQueue^7"
            lines.append(line)
        if want and not any(str(q.get("name", "")).casefold() == want for q in mine):
            lines.append(f"^3qlx_fragqQueue is '{_plain(cfg['queue'])}', which isn't one of the key's queues.^7")
        elif not want and len(_voice_queues(c) or []) > 1:
            lines.append("^3qlx_fragqQueue isn't set, and several of these queues have voice moves on: voice moves "
                         "only work for players in a FragQ match. Set it to the queue this server plays.^7")
        if others:
            names = ", ".join(f"^5{_plain(q.get('name'))}^7" + (f" (#{_plain(q['channel'])})" if q.get("channel") else "")
                              for q in others[:10])
            more = f" and {len(others) - 10} more" if len(others) > 10 else ""
            lines.append(f"Not on this key: {names}{more}. Tick a queue on the connector in FragQ's Connectors page to use it.")
        self._reply(reply_to, *lines)

    # ------------------------------------------------------------ back on the game thread: tells only

    @ql.next_frame
    def _reply(self, reply_to, *lines):
        self._reply_lines(reply_to, lines)

    def _reply_lines(self, reply_to, lines):
        """_reply when already on the game thread. Colour codes are kept; only % is made safe."""
        if reply_to[0] == "console":
            for line in lines:
                reply_to[1].reply(_text(line))
            return
        self._tell_now([reply_to[1:]], lines)

    @ql.next_frame
    def _tell_players(self, targets, line):
        self._tell_now(targets, [line])

    def _tell_now(self, targets, lines):
        for client_id, steam_id in targets:
            p = self._slot_player(client_id, steam_id)
            if p is not None:
                for line in lines:
                    p.tell(_text(line))

    def _slot_player(self, client_id, steam_id):
        """The player in this client slot if it's still the same Steam account, else None (game thread)."""
        try:
            p = self.player(client_id)
        except Exception:  # noqa: BLE001 - NonexistentPlayerError: they left
            return None
        return p if p is not None and str(p.steam_id) == str(steam_id) else None   # else: the slot changed hands

    def _client(self, arg):
        """The player with a Steam account in client slot `arg` (a string from chat), or None (game thread)."""
        cid = _int(arg, -1)
        if not 0 <= cid < 64 or not str(arg).strip().isdigit():
            return None
        try:
            p = self.player(cid)
        except Exception:  # noqa: BLE001 - NonexistentPlayerError: empty slot
            return None
        return p if p is not None and _is_steam_id(p.steam_id) else None

    # ------------------------------------------------------------ !queueverify, !sub, !unsub

    def _qv_allowed(self, player):
        level = self._cfg.get("qverify_level", self._cfg.get("admin_level", 3))
        if self.db.has_permission(player, level):
            return True
        player.tell(f"{QV_TAG} that needs permission level {level}.")
        return False

    def _qv_snapshot(self):
        """[(client id, Steam ID, raw name, team)] of everyone on the server (game thread). The name keeps its
        colours: _colored() it for chat, _clean() it for logs."""
        return [(p.id, str(p.steam_id), str(p.name or ""), _team(p.team))
                for p in self.players() if _is_steam_id(p.steam_id)]

    def _qv_start(self, player, channel, cfg, players, mode, extra=()):
        """Hand one check to a worker thread, unless one is running (game thread). True when started."""
        with self._lock:
            if self._qv_busy:
                player.tell(f"{QV_TAG} a check is already running, try again in a moment.")
                return False
            self._qv_busy = True
        self._qverify_job(self._reply_target(player, channel), cfg, players, mode, list(extra))
        return True

    def cmd_queueverify(self, player, msg, channel):
        if not self._qv_allowed(player):
            return STOP_ALL
        sub = msg[1].lower() if len(msg) > 1 else ""
        if sub and sub not in ("status", "dry", "check", "test"):
            player.tell(f"{QV_TAG} usage: ^5!queueverify^7 (check and fix the teams), ^5!queueverify dry^7 (only report), "
                        "^5!queueverify status^7 (the key's queues and permissions).")
            return STOP_ALL
        mode = "status" if sub == "status" else "dry" if sub else "fix"
        cfg = self.load_config()
        if not cfg.get("url") or not cfg.get("key"):
            player.tell(f"{QV_TAG} FragQ address or connector key not set (^5!fragq url^7 / ^5!fragq key^7).")
            return STOP_ALL
        players = self._qv_snapshot()
        if not players and mode != "status":
            player.tell(f"{QV_TAG} nobody to check.")
            return STOP_ALL
        # Replaced players are looked up too, so a sub keeps their FragQ team after they disconnect.
        replaced = [rep for _, rep, _ in self._subs.values() if rep]
        if self._qv_start(player, channel, cfg, players, mode, replaced):
            player.tell(f"{QV_TAG} asking FragQ..." if mode == "status" else
                        f"{QV_TAG} checking the teams against FragQ" +
                        (f" (queue {_text(cfg['queue'])})..." if cfg.get("queue") else "..."))
        return STOP_ALL

    def _sub_label(self, sid):
        name, _, rep_name = self._subs[sid]
        return f"{_colored(name)} (for {_colored(rep_name)})" if rep_name else _colored(name)

    def cmd_sub(self, player, msg, channel):
        """!sub <id> [<id2>]: <id> is subbing in the current PUG (for <id2>). See the module docstring."""
        if not self._qv_allowed(player):
            return STOP_ALL
        usage = (f"{QV_TAG} usage: ^5!sub <player id>^7 (a sub: never moved), ^5!sub <player id> <id of the player they "
                 "replace>^7, ^5!sub off <player id>^7, ^5!sub clear^7, or ^5!sub^7 to list. Ids are shown by /players.")
        args = [a.lower() for a in msg[1:]]
        if not args:
            listed = ", ".join(self._sub_label(sid) for sid in self._subs) or "none"
            player.tell(f"{QV_TAG} subs: {listed}.")
            return STOP_ALL
        if args[0] == "clear":
            self._subs.clear()
            player.tell(f"{QV_TAG} subs cleared.")
            return STOP_ALL
        remove = args[0] in ("off", "remove", "del")
        if (remove and len(args) != 2) or (not remove and len(args) > 2):
            player.tell(usage)
            return STOP_ALL
        target_arg = args[1] if remove else args[0]
        target = self._client(target_arg)
        if target is None:
            player.tell(_text(f"{QV_TAG} no player with id {target_arg[:10]}. Player ids are shown by /players."))
            return STOP_ALL
        sid, name = str(target.steam_id), str(target.name or "")
        if remove:
            player.tell(self._unsub(sid, name))
            return STOP_ALL
        rep_sid = rep_name = None
        if len(args) > 1:
            replaced = self._client(args[1])
            if replaced is None:
                player.tell(_text(f"{QV_TAG} no player with id {args[1][:10]}. Player ids are shown by /players."))
                return STOP_ALL
            rep_sid, rep_name = str(replaced.steam_id), str(replaced.name or "")
            if rep_sid == sid:
                player.tell(f"{QV_TAG} a player can't sub for themselves.")
                return STOP_ALL
        # A player who is in the PUG needs no protection: ask FragQ first, then add on the game thread.
        cfg = self.load_config()
        request = (sid, name, target.id, rep_sid, rep_name)
        if self._qv_start(player, channel, cfg, self._qv_snapshot(), "sub", [request]):
            player.tell(f"{QV_TAG} checking whether {_colored(name)} is already in the PUG...")
        return STOP_ALL

    def cmd_unsub(self, player, msg, channel):
        if not self._qv_allowed(player):
            return STOP_ALL
        if len(msg) != 2:
            player.tell(f"{QV_TAG} usage: ^5!unsub <player id>^7 (the sub, or the player they replaced).")
            return STOP_ALL
        target = self._client(msg[1])
        if target is None:
            player.tell(_text(f"{QV_TAG} no player with id {msg[1][:10]}. Player ids are shown by /players."))
            return STOP_ALL
        player.tell(self._unsub(str(target.steam_id), str(target.name or "")))
        return STOP_ALL

    @ql.next_frame
    def _finish_sub(self, reply_to, request, found):
        """Add the sub unless FragQ says they're already in the PUG (game thread)."""
        sid, name, _, rep_sid, rep_name = request
        if isinstance(found, str):   # couldn't check: add anyway, extra protection does no harm
            self._add_sub(reply_to, request, f" (couldn't check the PUG: {found.rstrip('.')})")
            return
        roster, discord_of, info = found
        if discord_of.get(sid) in roster:
            self.logger.info("fragq: qverify: %s (%s) is in FragQ match %s; not added as a sub.",
                             _clean(name), sid, info["match_id"])
            why = (f"; to take {_colored(rep_name)}'s place they'd have to leave it" if rep_sid else
                   ": !queueverify already keeps them on their team")
            self._reply_lines(reply_to, [f"{QV_TAG} {_colored(name)} is in the PUG (FragQ match #{info['match_id']}), "
                                         f"so they don't need sub protection{why}."])
            return
        self._add_sub(reply_to, request, "")

    def _add_sub(self, reply_to, request, note):
        sid, name, client_id, rep_sid, rep_name = request
        if rep_sid:
            # The replaced player gives up their place: they're no longer a sub, and nobody else subs for them.
            self._subs.pop(rep_sid, None)
            for other, (_, other_rep, _) in list(self._subs.items()):
                if other_rep == rep_sid and other != sid:
                    del self._subs[other]
        self._subs[sid] = (name, rep_sid, rep_name)
        if rep_sid:
            self.logger.info("fragq: qverify: %s (%s) subs for %s (%s).", _clean(name), sid, _clean(rep_name), rep_sid)
            line = (f"{QV_TAG} {_colored(name)} subs for {_colored(rep_name)}: !queueverify keeps {_colored(name)} in the "
                    f"PUG and takes {_colored(rep_name)} out (switching them if they're still on a team){note}.")
        else:
            self.logger.info("fragq: qverify: %s (%s) marked as a sub.", _clean(name), sid)
            line = (f"{QV_TAG} {_colored(name)} is a sub: !queueverify won't move them, and switches the next player who "
                    f"doesn't belong instead{note}.")
        self._reply_lines(reply_to, [line])
        if not (reply_to[0] == "player" and reply_to[1] == client_id):
            self._tell_now([(client_id, sid)], [f"{QV_TAG} you're subbing in this PUG" +
                                                (f" for {_colored(rep_name)}" if rep_name else "") +
                                                ": you won't be moved off your team."])

    def _unsub(self, sid, name):
        """Undo a sub (game thread). Returns the reply. `sid` is the sub, or the player someone subs for. The
        player they subbed for gets protection back, as a plain sub."""
        if sid not in self._subs:
            sid = next((s for s, (_, rep, _) in self._subs.items() if rep == sid), None)
            if sid is None:
                return f"{QV_TAG} {_colored(name)} isn't a sub, and nobody subs for them."
        sub_name, rep_sid, rep_name = self._subs.pop(sid)
        if rep_sid is None:
            self.logger.info("fragq: qverify: %s (%s) is no longer a sub.", _clean(sub_name), sid)
            return f"{QV_TAG} {_colored(sub_name)} is no longer a sub: !queueverify can move them again."
        self._subs[rep_sid] = (rep_name, None, None)
        self.logger.info("fragq: qverify: %s (%s) no longer subs for %s (%s).",
                         _clean(sub_name), sid, _clean(rep_name), rep_sid)
        for p in self.players():
            if str(p.steam_id) == sid:
                p.tell(f"{QV_TAG} you're no longer subbing in this PUG.")
            elif str(p.steam_id) == rep_sid:
                p.tell(f"{QV_TAG} you're back in this PUG: you won't be moved off your team.")
        return (f"{QV_TAG} {_colored(sub_name)} no longer subs for {_colored(rep_name)}: {_colored(rep_name)} is "
                f"protected again, and !queueverify can move {_colored(sub_name)}.")

    # ---- worker thread: HTTP only

    @ql.thread
    def _qverify_job(self, reply_to, cfg, players, mode, extra):
        try:
            if mode == "status":
                self._qv_status(reply_to, cfg)
            elif mode == "sub":
                request = extra[0]
                self._finish_sub(reply_to, request, self._qv_lookup(cfg, players, [s for s in (request[0], request[3]) if s]))
            else:
                found = self._qv_lookup(cfg, players, extra)
                if isinstance(found, str):
                    self._reply(reply_to, f"{QV_TAG} {found} Nothing was changed.")
                else:
                    self._qv_apply(reply_to, *found, mode == "dry")
        except Exception:  # noqa: BLE001 - whatever a reply contains, answer and free the slot
            self.logger.exception("fragq: qverify: check failed")
            self._reply(reply_to, f"{QV_TAG} ^1the check failed unexpectedly^7; see the server log.")
        finally:
            with self._lock:
                self._qv_busy = False

    def _qv_fragq_status(self, cfg):
        """(queue names, {capability: bool}) from FragQ GET /status, or (None, error)."""
        data, error, _ = self._request(cfg, "GET", "/status")
        if error:
            return None, error
        c = data.get("connector") if isinstance(data.get("connector"), dict) else {}
        return [str(q) for q in c.get("queues") or []], (c.get("can") if isinstance(c.get("can"), dict) else {})

    def _qv_status(self, reply_to, cfg):
        queues, can = self._qv_fragq_status(cfg)
        if queues is None:
            self._reply(reply_to, f"{QV_TAG} ^1couldn't reach FragQ^7: {can}.")
            return
        allowed = ", ".join(k for k, v in sorted(can.items()) if v) or "none"
        wanted = cfg.get("queue")
        if wanted:
            match = next((q for q in queues if q.casefold() == wanted.casefold()), None)
            qline = (f"qlx_fragqQueue '{wanted}' is queue '{match}'." if match else
                     f"^1qlx_fragqQueue '{wanted}' isn't one of this key's queues.^7")
        else:
            qline = "qlx_fragqQueue is empty: every queue of the key is checked."
        self._reply(reply_to, f"{QV_TAG} key queues: {', '.join(queues) or 'none'}. Permissions: {allowed}.",
                    f"{QV_TAG} {qline}" + ("" if can.get("check") else
                                           " ^1!queueverify needs the key's 'Check linked players' permission.^7"))

    def _qv_failure(self, cfg, error, status):
        """One sentence that says which failure this is: unreachable, bad key, missing permission, bad queue."""
        queue = cfg.get("queue")
        if status == 0:
            return f"^1couldn't reach FragQ^7: {error}"
        if status == 401:
            return f"^1FragQ refused the key^7 ({error}); check qlx_fragqKey"
        if status == 404:
            return "this FragQ has no POST /match yet; update FragQ"
        if status == 403:
            queues, can = self._qv_fragq_status(cfg)
            if queues is not None and not can.get("check"):
                return "^1the FragQ key can't read live matches^7: give it the 'Check linked players' permission"
            return f"^1FragQ refused the request^7 ({error})"
        if status == 400 and queue:
            queues, _ = self._qv_fragq_status(cfg)
            if queues is not None and not any(q.casefold() == queue.casefold() for q in queues):
                return f"FragQ has no queue named {queue}; this key's queues: {', '.join(queues) or 'none'}"
        return f"FragQ answered {error}"

    def _qv_lookup(self, cfg, players, extra_ids=()):
        """The FragQ match this server is playing and everyone's Discord ID (worker thread): (roster {discord_id:
        team}, discord_of {steam_id: discord_id}, info), or a sentence saying why not."""
        data, error, status = self._request(cfg, "POST", "/match", _with_queue({}, cfg))
        if error:
            self.logger.warning("fragq: qverify: FragQ match lookup failed: %s", error)
            return f"{self._qv_failure(cfg, error, status)}."
        where = f" for queue {cfg['queue']}" if cfg.get("queue") else ""
        matches = [m for m in data.get("matches") or [] if isinstance(m, dict)]
        playing = [m for m in matches if m.get("state") in QV_PLAYING]
        if not playing:   # a valid answer, not a failure
            pre = [m for m in matches if m.get("state") in QV_PRE_GAME]
            if pre:
                return (f"^3FragQ match #{pre[0].get('match_id')}{where} is still in "
                        f"{str(pre[0].get('state')).replace('_', '-')}^7, so there's nothing to check yet.")
            return f"^3no active FragQ match{where}^7."

        discord_of, fragdex_error = self._fragdex_discord_ids(cfg, [sid for _, sid, _, _ in players] + list(extra_ids))
        # FragQ's own Steam links fill the gaps Fragdex leaves (or everything, if Fragdex is down).
        for m in playing:
            for p in m.get("players") or []:
                if isinstance(p, dict) and _is_steam_id(p.get("steam_id")) and str(p.get("discord_id", "")).isdigit():
                    discord_of.setdefault(str(p["steam_id"]), str(p["discord_id"]))
        if fragdex_error and not discord_of:
            return (f"^1Fragdex couldn't be asked for Discord IDs^7 ({fragdex_error}) and FragQ has no Steam links "
                    "for these players.")

        # Like FragQ's own result matching: at least half of the match's players here, then the newest.
        here_ids = {discord_of[sid] for _, sid, _, _ in players if sid in discord_of}

        def overlap(m):
            ids = [str(p.get("discord_id")) for p in m.get("players") or [] if isinstance(p, dict)]
            return sum(i in here_ids for i in ids), len(ids)

        candidates = [m for m in playing if overlap(m)[0] >= max(1, -(-overlap(m)[1] // 2))]
        if not candidates:
            here, total = overlap(playing[0])
            return (f"^3the newest FragQ match{where} (#{playing[0].get('match_id')}) has only {here} of its {total} "
                    "players on this server^7, so it isn't this game.")
        match = max(candidates, key=lambda m: _int(m.get("started_at"), 0))
        roster, names = {}, {}
        for p in match.get("players") or []:
            if isinstance(p, dict) and str(p.get("discord_id", "")).isdigit():
                did = str(p["discord_id"])
                roster[did] = p.get("team") if p.get("team") in (0, 1) else None
                names[did] = str(p.get("discord_name") or did)   # a Discord name: no QL colour codes in it
        if not roster:
            return f"FragQ match #{match.get('match_id')} has no players."
        info = dict(match_id=match.get("match_id"), queue=str(match.get("queue") or ""), names=names,
                    team_names=match.get("team_names") or ["team 1", "team 2"], fragdex_error=fragdex_error)
        return roster, discord_of, info

    def _fragdex_discord_ids(self, cfg, steam_ids):
        """{steam_id: discord_id} of the linked players, from Fragdex POST /players/lookup in batches of 100, and an
        error (None when every batch was answered). Unlinked players are simply absent."""
        if not cfg.get("fragdex_url") or not cfg.get("fragdex_key"):
            return {}, "qlx_fragdexUrl / qlx_fragdexKey not set"
        out, error = {}, None
        ids = list(dict.fromkeys(steam_ids))
        for i in range(0, len(ids), FRAGDEX_BATCH):
            data, err, _ = self._fragdex(cfg, "POST", "/players/lookup", {"steam_ids": ids[i:i + FRAGDEX_BATCH]})
            if err:
                self.logger.warning("fragq: qverify: Fragdex lookup failed: %s", err)
                error = err
                continue
            for p in data.get("players") or []:
                if isinstance(p, dict) and p.get("known") and str(p.get("discord_id") or "").isdigit():
                    out[str(p.get("steam_id"))] = str(p["discord_id"])
        return out, error

    # ---- back on the game thread: the moves

    @ql.next_frame
    def _qv_apply(self, reply_to, roster, discord_of, info, dry):
        # Read the teams again: players may have joined, left or switched while FragQ and Fragdex answered.
        lines = [f"{QV_TAG} FragQ match #{info['match_id']} ({_text(info['queue'])}), {len(roster)} players."]
        if self._subs_match != info["match_id"]:   # subs belong to one PUG
            if self._subs and self._subs_match is not None:
                lines.append(f"{QV_TAG} new FragQ match: subs cleared "
                             f"({', '.join(self._sub_label(x) for x in self._subs)}).")
                self._subs.clear()
            self._subs_match = info["match_id"]
        result = qverify_plan(roster, self._qv_snapshot(), discord_of, lookup_ok=not info["fragdex_error"],
                              protected={sid: rep for sid, (_, rep, _) in self._subs.items()})
        names = info["names"]
        if info["fragdex_error"]:
            lines.append(f"{QV_TAG} ^3Fragdex: {info['fragdex_error']}^7; using FragQ's Steam links only, and players "
                         "without one are left alone.")

        def who(entries):
            return ", ".join(_colored(e[2]) for e in entries)

        switch, evict, place, wait = result["switch"], result["evict"], result["place"], result["wait"]
        if not switch and not evict and not place and not wait:
            lines.append(f"{QV_TAG} ^2the roster is clean: the teams match the PUG.")
        if result["subs"]:
            lines.append(f"{QV_TAG} subs kept on their team: {who(result['subs'])}")
        named = [self._sub_label(sid) for sid in self._subs if self._subs[sid][1]]
        if named:
            lines.append(f"{QV_TAG} subbing in: " + ", ".join(named))
        if result["covered"]:
            lines.append(f"{QV_TAG} not brought in, a sub has their slot: {who(result['covered'])}")
        if result["unverified"]:
            lines.append(f"{QV_TAG} ^3not checked (Fragdex down, no FragQ link), left alone:^7 {who(result['unverified'])}")
        if result["missing"]:
            lines.append(f"{QV_TAG} PUG players not on the server: " + ", ".join(names[d] for d in result["missing"]))
        if dry:
            if switch:
                lines.append(f"{QV_TAG} would switch: " +
                             ", ".join(f"{_colored(i[2])} in for {_colored(o[2])} ({o[3]})" for o, i in switch))
            if evict:
                lines.append(f"{QV_TAG} would move to spectator: {who(evict)}")
            if place:
                lines.append(f"{QV_TAG} would put on their team: " +
                             ", ".join(f"{_colored(e[2])} -> {s}" for e, s in place))
            if wait:
                lines.append(f"{QV_TAG} would ask to join ({wait[0][1]}): {who(e for e, _ in wait)}")
            self._reply_lines(reply_to, lines)
            return

        moves, failed, switched = [], [], []
        out_line = f"{QV_TAG} you're not in the current FragQ PUG, so you were moved to spectator."
        for out_entry, in_entry in switch:
            team = out_entry[3]
            error = self._qv_switch(out_entry, in_entry)
            if error is None:
                moves += [(out_entry, "spectator"), (in_entry, team)]
                switched.append(f"{_colored(in_entry[2])} in for {_colored(out_entry[2])} ({team})")
                self._qv_tell(out_entry, out_line)
                self._qv_tell(in_entry, f"{QV_TAG} you're in the FragQ PUG: you were put on {team.capitalize()}.", True)
            else:
                failed.append(f"{_colored(in_entry[2])} <-> {_colored(out_entry[2])} ({error})")
        # Evict the rest before putting anyone in, so a team never holds more than its players.
        for entry in evict:
            error = self._qv_put(entry, "spectator")
            if error is None:
                moves.append((entry, "spectator"))
                self._qv_tell(entry, out_line)
            elif error != "left":
                failed.append(f"{_colored(entry[2])} ({error})")
        for entry, side in place:
            error = self._qv_put(entry, side)
            if error is None:
                moves.append((entry, side))
                self._qv_tell(entry, f"{QV_TAG} you're in the FragQ PUG: you were put on {side.capitalize()}.", True)
            elif error != "left":
                failed.append(f"{_colored(entry[2])} ({error})")
        snapshot = self._qv_snapshot() if wait else []
        for entry, _ in wait:
            fq = result["member_fq"].get(entry[1])
            if fq in (0, 1):
                team_name = str(info["team_names"][fq])
                mates = [_colored(n) for _, s, n, t in snapshot
                         if t in ("red", "blue") and result["member_fq"].get(s) == fq]
                hint = f"join your team {team_name}" + (f" (with {', '.join(mates)})" if mates else "")
            else:
                hint = "join a team"
            self._qv_tell(entry, f"{QV_TAG} you're in the FragQ PUG: {hint} now: /team r or /team b.", True)

        out_n = sum(1 for _, t in moves if t == "spectator")
        put_in = [f"{_colored(e[2])} -> {t}" for e, t in moves[2 * len(switched):] if t != "spectator"]
        lines.append(f"{QV_TAG} moved {out_n} non-PUG player(s) to spectator." +
                     (f" Switched in {len(switched)} PUG member(s): {', '.join(switched)}." if switched else "") +
                     (f" Put {len(put_in)} PUG member(s) on their team: {', '.join(put_in)}." if put_in else ""))
        if wait:
            lines.append(f"{QV_TAG} {len(wait)} PUG member(s) told to join: {who(e for e, _ in wait)} "
                         f"({'; '.join(dict.fromkeys(r for _, r in wait))}).")
        if failed:
            lines.append(f"{QV_TAG} ^1couldn't move:^7 " + ", ".join(failed))
        self.logger.info("fragq: qverify: match %s: %d switched, %d to spectator, %d put on a team, %d prompted, "
                         "%d failed.", info["match_id"], len(switched), out_n, len(put_in), len(wait), len(failed))
        if moves:
            self._qv_confirm(reply_to, moves, lines)   # report once we've seen the moves stick
        else:
            self._reply_lines(reply_to, lines)

    @ql.delay(QV_CONFIRM_DELAY)
    def _qv_confirm(self, reply_to, moves, lines):
        """A put can be undone by another plugin (a queue or balance plugin reacting to it): check (game thread)."""
        undone = []
        for entry, team in moves:
            p = self._slot_player(entry[0], entry[1])
            if p is not None and _team(p.team) != team:
                undone.append(f"{_colored(entry[2])} (now {_team(p.team)}, wanted {team})")
        if undone:
            self.logger.warning("fragq: qverify: moves undone after %.1fs: %s", QV_CONFIRM_DELAY, _clean(", ".join(undone)))
            lines = lines + [f"{QV_TAG} ^1moved back by the server or another plugin:^7 " + ", ".join(undone)]
        self._reply_lines(reply_to, lines)

    def _qv_switch(self, out_entry, in_entry):
        """Swap a non-PUG player on a team with a PUG spectator by client id (game thread): Player.switch puts each
        in the other's place. None when done, else the error. If one of them left, the other half is a put."""
        p_out, p_in = self._slot_player(*out_entry[:2]), self._slot_player(*in_entry[:2])
        if p_in is None:
            error = self._qv_put(out_entry, "spectator")
            return None if error in (None, "left") else error
        if p_out is None:
            return self._qv_put(in_entry, out_entry[3])
        try:
            p_out.switch(p_in)
            return None
        except Exception as e:  # noqa: BLE001 - the game rejected it: fall back to the two puts it stands for
            self.logger.warning("fragq: qverify: switch %s <-> %s failed (%s); trying put.",
                                _clean(out_entry[2]), _clean(in_entry[2]), e)
        return self._qv_put(out_entry, "spectator") or self._qv_put(in_entry, out_entry[3])

    def _qv_put(self, entry, team):
        """Move the player in this slot (game thread). None when done, 'left' when the slot changed hands, else the
        error. Like _enforce: the team name first, then minqlxtended's Team member."""
        p = self._slot_player(entry[0], entry[1])
        if p is None:
            return "left"
        try:
            p.put(team)
            return None
        except Exception:  # noqa: BLE001 - minqlxtended may want its Team member
            pass
        try:
            p.put(getattr(ql, "Team")[team.upper()])
            return None
        except Exception as e:  # noqa: BLE001 - team full, game state: report, don't stop the others
            self.logger.warning("fragq: qverify: couldn't put %s on %s: %s", _clean(entry[2]), team, e)
            return str(e)[:80] or type(e).__name__

    def _qv_tell(self, entry, line, center=False):
        p = self._slot_player(entry[0], entry[1])
        if p is None:
            return
        p.tell(_text(line))
        if center:
            p.center_print(_text(line.replace(QV_TAG, "").strip()))   # colours kept

    # ------------------------------------------------------------ !whois

    def cmd_whois(self, player, msg, channel):
        cfg = self._cfg
        level = cfg.get("whois_level", 0)
        if level and not self.db.has_permission(player, level):
            player.tell(f"^1FragQ:^7 !whois needs permission level {level}.")
            return STOP_ALL
        if len(msg) < 2:
            player.tell("^1FragQ:^7 usage: ^5!whois <who>^7, where <who> is a player id (from /players), a Steam ID, "
                        "a Discord user id or username, or part of an in-game name.")
            return STOP_ALL
        if not cfg.get("fragdex_url") or not cfg.get("fragdex_key"):
            self.logger.warning("fragq: !whois unavailable: qlx_fragdexUrl / qlx_fragdexKey not set")
            player.tell("^1FragQ:^7 !whois needs Fragdex, which isn't set up on this server "
                        "(qlx_fragdexUrl / qlx_fragdexKey).")
            return STOP_ALL
        sid_self = str(player.steam_id)
        now = time.time()
        if getattr(channel, "name", "") != "console" and now - self._whois_at.get(sid_self, 0) < WHOIS_COOLDOWN:
            player.tell(f"^1FragQ:^7 wait {int(WHOIS_COOLDOWN - (now - self._whois_at[sid_self])) + 1}s.")
            return STOP_ALL
        query = " ".join(msg[1:]).strip()
        shown = _text(query[:40])

        # Work out what was typed, on the game thread where the player list can be read.
        target = None   # (steam_id, in-game name or None) or ("discord", text)
        if query.isdigit() and len(query) <= 2:
            found = self._client(query)
            if found is None:
                player.tell(f"^1FragQ:^7 no player with id {shown}. Player ids are shown by /players.")
                return STOP_ALL
            target = (str(found.steam_id), str(found.name or ""))
        elif _steam64(query):
            sid = _steam64(query)
            here = next((p for p in self.players() if str(p.steam_id) == sid), None)
            target = (sid, str(here.name or "") if here else None)
        elif query.isdigit():
            target = ("discord", query)   # a Discord user id
        else:
            low = _clean(query).casefold()
            on_server = [p for p in self.players() if _is_steam_id(p.steam_id)]
            exact = [p for p in on_server if _clean(p.name).casefold() == low]
            partial = exact or [p for p in on_server if low and low in _clean(p.name).casefold()]
            if len(partial) == 1:
                target = (str(partial[0].steam_id), str(partial[0].name or ""))
            elif len(partial) > 1:
                player.tell(f"^1FragQ:^7 {len(partial)} players match '{shown}': " +
                            ", ".join(f"{_colored(p.name)} ({p.id})" for p in partial[:6]) +
                            ". Use the player id: ^5!whois <id>^7.")
                return STOP_ALL
            else:
                target = ("discord", query.lstrip("@"))   # nobody here by that name: try it as a Discord username
        self._whois_at[sid_self] = now
        self._whois(self._reply_target(player, channel), dict(cfg), target, query)
        return STOP_ALL

    @ql.thread
    def _whois(self, reply_to, cfg, target, query):
        try:
            lines = self._whois_lines(cfg, target, query)
        except Exception:  # noqa: BLE001 - never let a bad answer pass silently
            self.logger.exception("fragq: !whois %s failed", _clean(query))
            lines = ["^1FragQ:^7 ^1the lookup failed unexpectedly^7; see the server log."]
        self._reply(reply_to, *lines)

    def _whois_lines(self, cfg, target, query):
        """The reply to !whois (worker thread). Fragdex POST /players/lookup for a Steam ID (Discord link, Steam
        persona and last in-game name in one request), GET /discord/{id or username} for a Discord account."""
        shown = _text(query[:40])
        if target[0] == "discord":
            data, error, status = self._fragdex(cfg, "GET", "/discord/" + urllib.parse.quote(target[1], safe=""))
            if status == 400:   # Fragdex: not a Discord user id or username
                return [f"^1FragQ:^7 ^3nobody matches '{shown}'^7: no player on the server has that name, and it "
                        "isn't a Discord user id or username."]
            if error:
                return [self._fragdex_failure(error, status)]
            rows = [p for p in data.get("players") or [] if isinstance(p, dict) and _is_steam_id(p.get("steam_id"))]
            if not rows:
                return [f"^1FragQ:^7 ^3no Steam account is linked to Discord '{shown}'^7, and no player on the server "
                        "has that name."]
            accounts = {str(p.get("discord_id")) for p in rows if p.get("discord_id")}
            if len(accounts) > 1:
                return [f"^1FragQ:^7 ^3'{shown}' matches {len(accounts)} Discord accounts^7; use the Discord user id."]
            lines = [self._whois_line(p, None) for p in rows[:3]]
            if len(rows) > 1:
                lines.insert(0, f"^1FragQ:^7 Discord '{shown}' is linked to {len(rows)} Steam accounts:")
                if len(rows) > 3:
                    lines.append(f"^1FragQ:^7 ...and {len(rows) - 3} more.")
            return lines

        sid, ingame = target
        data, error, status = self._fragdex(cfg, "POST", "/players/lookup", {"steam_ids": [sid]})
        if error:
            # Fragdex is down: FragQ's own linked check still says whether there is a Discord link.
            fq, fq_error, _ = self._request(cfg, "POST", "/players/linked", {"steam_ids": [sid]})
            row = next((p for p in (fq or {}).get("players") or [] if isinstance(p, dict)), None)
            lines = [self._fragdex_failure(error, status)]
            if not fq_error and row is not None:
                name = f"{_colored(ingame)} " if ingame else ""
                lines.append(f"^1FragQ:^7 from FragQ instead: {name}Steam ^5{sid}^7 " +
                             (f"is ^2linked^7 to Discord ^5{_text(row.get('discord_name') or 'a member')}^7."
                              if row.get("linked") else "^3has no Discord link^7."))
            return lines
        row = next((p for p in data.get("players") or [] if isinstance(p, dict) and str(p.get("steam_id")) == sid), None)
        if row is None or not row.get("known"):
            who = f"{_colored(ingame)} (Steam ^5{sid}^7)" if ingame else f"Steam ^5{sid}^7"
            return [f"^1FragQ:^7 ^3Fragdex has no record of^7 {who}, so no Discord link."]
        return [self._whois_line(row, ingame)]

    @staticmethod
    def _whois_line(row, ingame):
        """One Fragdex player summary -> a chat line: in-game name, Steam ID and persona, Discord link."""
        sid = str(row.get("steam_id"))
        last = str(row.get("name_raw") or row.get("name") or "")   # Fragdex keeps the raw name: colours intact
        steam = row.get("steam") if isinstance(row.get("steam"), dict) else {}
        persona = _clean(steam.get("persona") or "").strip()   # a Steam name: QL colour codes there are noise
        head = _colored(ingame) if ingame else (_colored(last) if last else "?")
        parts = [f"^1FragQ:^7 {head} - Steam ^5{sid}^7"]
        if persona:
            parts.append(f" ({_text(persona)})")
        did, dname = row.get("discord_id"), row.get("discord_name")
        if did or dname:
            parts.append(f" <-> Discord ^5{_text(dname or did)}^7" + (f" ({did})" if did and dname else "") + ".")
        else:
            parts.append(" ^3has no Discord link^7.")
        if ingame and last and _clean(last) != _clean(ingame):
            parts.append(f" Last seen as {_colored(last)}.")
        return "".join(parts)

    @staticmethod
    def _fragdex_failure(error, status):
        if status == 0:
            return f"^1FragQ:^7 ^1couldn't reach Fragdex^7 ({error}); try again later."
        if status in (401, 403):
            return f"^1FragQ:^7 ^1Fragdex refused the key^7 ({error}); check qlx_fragdexKey."
        if status == 429:
            return f"^1FragQ:^7 ^3Fragdex is rate limiting this server^7 ({error})."
        return f"^1FragQ:^7 ^1Fragdex answered^7 {error}."
