#!/usr/bin/env python3
"""agent-daemons.py - each agent's scheduler and chat watchers as user services.

Every standing agent runs the scheduler (`sched.py`, from the scheduled-tasks
skill) and one watcher per WORKING chat transport (the transport's
`watch.script`, from that transport's skill). They run as user services of the
host's service manager, with a restart on every exit but 0, writing to a log
under the agent's own home:

    <agents root>/<agent>/state/daemons/<job>.log     job = sched | <watch.job>

Under systemd each job is a templated user unit, `agent-sched@<agent>.service`
and `agent-<watch.job>@<agent>.service` (for Slack,
`agent-slack-watch@<agent>.service`); under launchd (macOS) each is one
LaunchAgent per agent, `<prefix>.<job>.<agent>` (fleetlib.services names both).

The jobs are `sched` plus one per working transport, read from the transport
registry (`fleetlib.transports.working()`): a transport job's unit, its config
file under the agent home (`config/<watch.job>.json`), the environment variable
naming that file (`watch.config_env`), its script and its default follower
filter (`watch.follow_include`) all come from the transport's `transport.json`.
The agents root is `agents_root` in the host settings (`fleetlib.paths.host()`).

A session does not run the daemons. It runs the FOLLOWER (`follow`) under a
Monitor: the follower prints every complete line of the log it has not delivered
yet, from a byte cursor beside the log, so a line written while no Monitor was
armed is delivered on the next arm instead of being lost.

Modes (one script, one mode argument):

  follow <agent> <job>   print undelivered log lines; alert when the unit is down
  rotate <log>           systemd's ExecStartPre: move a log over --max-bytes aside
                         to <log>.1
  exec --log <log> [--env-file <f>] -- <argv>...
                         launchd's stand-in for ExecStartPre and EnvironmentFile:
                         rotate the log, point stdout and stderr at it, apply
                         <f>'s KEY=VALUE lines over the environment, and exec
                         <argv> (same pid, so the process is the daemon's)
  jobs [--json]          print the job table: one line per job, or with --json
                         the units' interpreter and every job's unit, script,
                         log and config as JSON, which `fleet pin-daemons` and
                         `fleet status` read instead of keeping their own copy;
                         of the host settings it reads only the optional
                         `python`, and runs without them
  status <agent> [--json]  each job's unit, state, pid, restarts and command
                         line, and whether it writes to a replaced log (DEAF;
                         --json: log_replaced, the reason, false, or null when
                         its output cannot be read); exit 1 when a job the
                         agent has a config for is not active or is DEAF. The
                         portable "are my daemons up" check
  refresh [--dry-run]    the timer's job: restart a unit whose process writes to a
                         replaced log (its stdout or stderr is not the file at
                         the job's log path), first appending to the log the
                         lines it wrote to the replaced file that nobody has
                         (SALVAGE below), or whose RUNNING script, config
                         file or <job>.env is newer than its process, or whose
                         process is over a day old; one run at a time (a
                         second exits 0 doing nothing); --dry-run prints every
                         unit's decision, with the lines it would salvage,
                         and restarts nothing
  render-units --units refresh|all (--out <dir> | --list) [--host-config <file>]
                         write the unit files rendered from this tree's
                         templates into <dir>, replacing (never writing through)
                         what is there; --list prints their names and writes
                         nothing. `fleet install` calls it. Under launchd `all`
                         is the refresh job plus a plist for every job instance
                         already installed (there are no template units). Every
                         unit names --host-config as FLEET_HOST_CONFIG, else the
                         host settings file the render reads
  --install <agent>...   enable --now the refresh job and each job whose config
                         file exists for each agent; under systemd the units
                         must already be rendered into the user unit directory,
                         under launchd the refresh plist must be and each
                         agent's job plists are rendered here
  --uninstall [<agent>...]  stop the agents' units; with no agent, also the
                         refresh job, and remove the rendered unit files

Lines the follower prints itself, so a session can tell them from the daemon's:

  DAEMON-ALERT <unit> ...     the unit is not active, or it restarted on its own
  DAEMON-OK <unit> ...        an alerted unit is active again
  DAEMON-BACKLOG <unit> ...   more undelivered lines than --replay-max; header
                              for the condensed replay that follows it
  DAEMON-FOLLOW ...           the follower's own condition (another follower
                              holds the log, the log was truncated or replaced)
  DAEMON-REFRESH ...          written INTO the log by `refresh` before it restarts
                              a unit, so the reason reaches the session in order
  DAEMON-SALVAGE ...          written INTO the log by `refresh` before that line:
                              the header of the lines a daemon wrote to its
                              replaced log, which follow it

Exit codes: 0 ran (or refused as a duplicate follower), 2 usage/refused, 3
environment fault (no host settings, no fleetlib beside this script, a broken
transport descriptor, no install checkout to render the units against).

`rotate` and `exec` read no host settings and import nothing from the fleet:
one runs before every systemd unit and the other IS every launchd job's first
process, so anything they depended on could keep every daemon on the host from
starting. agent-daemons.test.py runs `exec` from a tree with no lib/ to pin it.

This script finds its fleet tree through `realpath(__file__)`, never `abspath`:
it is also run through a symlink from outside the tree (a retired copy's path
kept as a link), and the link's own directory holds neither `lib/` nor the
templates.

Stdlib only, plus fleetlib from this tree's lib/. Environment overrides exist
for the offline test and nothing else: AGENT_DAEMONS_ROOT (the agents root,
instead of host.json's agents_root); the service manager and process seams are
fleetlib.services' (FLEET_SERVICE_BACKEND, AGENT_DAEMONS_SYSTEMCTL or
FLEET_SYSTEMCTL, FLEET_LAUNCHCTL, AGENT_DAEMONS_PROC or FLEET_PROC).
FLEET_PYTHON names the units' interpreter, else host.json's `python` (which
`fleet install` writes from FLEET_PYTHON), else /usr/bin/python3 under systemd
and Homebrew's /opt/homebrew/bin/python3 under launchd, since macOS's own
/usr/bin/python3 is older than the fleet's floor.
"""

import argparse
import datetime
import fcntl
import functools
import glob
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time

# No bytecode from any mode, the follower a session runs included: the fleet
# checkout is code the agents user may not write (the units also set
# PYTHONDONTWRITEBYTECODE for the daemons and whatever they start).
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.realpath(__file__))
FLEET = os.path.dirname(HERE)
# The two systemd units `--units refresh` renders: (template under systemd/, unit file).
TIMER = "agent-daemons-refresh.timer"
REFRESH_UNITS = (("agent-daemons-refresh.service.in", "agent-daemons-refresh.service"),
                 ("agent-daemons-refresh.timer", TIMER))
REFRESH_PLIST = "agent-daemons-refresh.plist.in"
# Job templates per backend: (scheduler, chat watcher).
TEMPLATES = {"systemd": ("agent-sched@.service.in", "agent-watch@.service.in"),
             "launchd": ("agent-sched.plist.in", "agent-watch.plist.in")}
PYTHON = "/usr/bin/python3"                  # systemd units' interpreter (@PYTHON@)
PYTHON_LAUNCHD = "/opt/homebrew/bin/python3"  # launchd jobs': macOS's own python3 is 3.9

REALERT_SECS = 1800       # a unit that stays down is re-announced at most this often
MAX_LOG_BYTES = 10 * 1024 * 1024
FIRST_CHECK_SECS = 10.0   # the first unit check after an arm
# The Monitor harness kills its command at 30 minutes. A line printed and flushed
# into the pipe in the moment before that kill is never read by the harness, and
# the cursor is already past it, so it is lost. The follower therefore ends ITSELF
# before the kill: what it printed is read to EOF, and a line written after it
# stops waits past the cursor for the next arm.
MAX_SECS_DEFAULT = 1740.0


class Fault(Exception):
    """The host or the fleet tree is not in a state this mode can work from (exit 3)."""


def refuse(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)
    sys.exit(2)


def fleetlib():
    lib = os.path.join(FLEET, "lib")
    if lib not in sys.path:
        sys.path.insert(0, lib)
    try:
        import fleetlib.paths
        import fleetlib.services
        import fleetlib.transports
    except ImportError as e:
        raise Fault(f"fleetlib is not importable from {lib} ({e}): "
                    f"run this script from a fleet tree") from None
    return fleetlib


def svc():
    """fleetlib.services: the service manager and the process readers."""
    return fleetlib().services


def python() -> str:
    """Every unit's interpreter, @PYTHON@ in the templates: $FLEET_PYTHON, else
    host.json's `python` (`fleet install` writes it from FLEET_PYTHON), else the
    backend's default."""
    return (os.environ.get("FLEET_PYTHON") or fleetlib().paths.host_option("python")
            or (PYTHON if svc().backend() == "systemd" else PYTHON_LAUNCHD))


@functools.cache
def root() -> str:
    env = os.environ.get("AGENT_DAEMONS_ROOT")
    if env:
        return env
    return os.path.expanduser(fleetlib().paths.host()["agents_root"]).rstrip("/")


@functools.cache
def jobs() -> dict:
    """job -> what runs it. `sched`, then one job per working transport (by name)."""
    sched_t, watch_t = TEMPLATES[svc().backend()]
    out = {"sched": {"template": sched_t,
                     "script": os.path.join(FLEET, ".claude", "skills", "scheduled-tasks",
                                            "sched.py"),
                     "config": "config/scheduler.json", "config_env": "SCHED_CONFIG",
                     "include": None, "transport": None, "line_prefix": None}}
    for t in fleetlib().transports.working():
        w = t["watch"]
        job = w["job"]
        if job in out:
            raise Fault(f"two daemon jobs are named {job!r} (transport {t['name']} and "
                        f"{out[job]['transport'] or 'the scheduler'}); a watch.job is unique")
        out[job] = {"template": watch_t,
                    "script": os.path.join(t["skill_dir"], w["script"]),
                    "config": f"config/{job}.json", "config_env": w["config_env"],
                    "include": w["follow_include"], "transport": t["name"],
                    "line_prefix": t["line_prefix"]}
    return out


def priority_default() -> str:
    """A backlog keeps these first: a due task and a direct message are the lines a
    condensed replay must not drop in favour of channel chatter. One `<PREFIX> DM `
    per working transport, so with Slack alone this is exactly
    ^(SCHED due|SCHED alert|SLACK DM |DAEMON-)."""
    dms = "".join(re.escape(j["line_prefix"]) + " DM |" for j in jobs().values()
                  if j["transport"])
    return f"^(SCHED due|SCHED alert|{dms}DAEMON-)"


def unit_name(job: str, agent: str) -> str:
    """The job's unit (systemd; the template when `agent` is empty) or label (launchd)."""
    return svc().unit("job", agent or None, job)


LOG_DIR = os.path.join("state", "daemons")    # under the agent home; --install creates it


def log_rel(job: str) -> str:
    """The job's log, relative to the agent home."""
    return os.path.join(LOG_DIR, f"{job}.log")


def log_path(agent: str, job: str) -> str:
    return os.path.join(root(), agent, log_rel(job))


def utc_iso(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# follow
# ---------------------------------------------------------------------------


class Follower:
    def __init__(self, log, unit, include=None, exclude=None, priority=None,
                 replay_max=20, check_secs=60.0, poll_secs=0.5, out=None,
                 max_secs=MAX_SECS_DEFAULT, label=None):
        self.log = log
        self.unit = unit
        self.cursor_path = log + ".cursor"
        self.include = re.compile(include) if include else None
        self.exclude = re.compile(exclude) if exclude else None
        self.priority = re.compile(priority) if priority else None
        self.replay_max = max(1, replay_max)
        self.check_secs = check_secs
        self.poll_secs = poll_secs
        self.out = out or sys.stdout
        self.max_secs = max_secs
        self.label = label or unit
        self.cur = None

    # -- cursor ---------------------------------------------------------------

    def load(self) -> None:
        try:
            with open(self.cursor_path) as f:
                self.cur = json.load(f)
        except (OSError, ValueError):
            self.cur = None
        if self.cur is None:
            # No cursor: start at the end of what is there now. A log that does not
            # exist yet starts at 0, so nothing the daemon writes after this is skipped.
            try:
                st = os.stat(self.log)
                self.cur = {"ino": st.st_ino, "offset": st.st_size}
            except FileNotFoundError:
                self.cur = {"ino": None, "offset": 0}
            self.save()

    def save(self) -> None:
        self.cur["saved_at"] = time.time()
        tmp = self.cursor_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.cur, f)
        os.replace(tmp, self.cursor_path)

    def emit(self, line: str) -> None:
        """Print, flush, THEN the caller saves. A follower killed between the two
        repeats the line on the next arm; it can never skip one."""
        self.out.write(line + "\n")
        self.out.flush()

    # -- lines ----------------------------------------------------------------

    def wanted(self, line: str) -> bool:
        if not line.strip():
            return False
        if self.include and not self.include.search(line):
            return False
        if self.exclude and self.exclude.search(line):
            return False
        return True

    def drain(self, path: str, ino: int) -> bool:
        """Deliver every complete line of `path` past the cursor. False if the file
        is not the one the cursor names (gone, or a different inode)."""
        try:
            f = open(path, "rb")
        except FileNotFoundError:
            return False
        with f:
            if os.fstat(f.fileno()).st_ino != ino:
                return False
            start = self.cur["offset"]
            f.seek(start)
            data = f.read()
        end = data.rfind(b"\n")
        if end < 0:
            return True                      # nothing complete yet; a partial waits
        items, pos = [], start
        for raw in data[:end + 1].split(b"\n")[:-1]:
            pos += len(raw) + 1
            text = raw.decode("utf-8", "replace").rstrip("\r")
            if self.wanted(text):
                items.append((text, pos))
        last = start + end + 1
        if len(items) > self.replay_max:
            items = self.condense(items, start)
        for text, pos in items:
            self.emit(text)
            self.cur["offset"] = pos
            self.save()
        if self.cur["offset"] != last:       # filtered or dropped tail
            self.cur["offset"] = last
            self.save()
        return True

    def condense(self, items, start):
        n, m = len(items), self.replay_max
        pri = [i for i, (t, _) in enumerate(items) if self.priority and self.priority.search(t)]
        keep = set(pri[-m:])
        for i in range(n - 1, -1, -1):
            if len(keep) >= m:
                break
            keep.add(i)
        since = utc_iso(self.cur.get("saved_at") or time.time())
        kept_pri = len(keep.intersection(pri))
        self.emit(f"DAEMON-BACKLOG {self.unit}: {n} lines since {since}, showing the "
                  f"newest {m}" + (f" ({kept_pri} priority lines kept first)" if kept_pri else "")
                  + f"; all {n} are in {self.log} from byte {start}")
        return [items[i] for i in sorted(keep)]

    def poll_log(self) -> None:
        try:
            st = os.stat(self.log)
        except FileNotFoundError:
            return
        ino = self.cur.get("ino")
        if ino is None:
            self.cur = {"ino": st.st_ino, "offset": 0}
            self.save()
            ino = st.st_ino
        if st.st_ino != ino:
            # Rotated: finish the old file first if `rotate` moved it to .1.
            if not self.drain(self.log + ".1", ino):
                self.emit(f"DAEMON-FOLLOW {self.log} was replaced and the file the cursor "
                          f"named is gone; reading the new one from the start")
            # How far the old file was delivered: refresh's salvage reads it
            # (delivered_offset) when a daemon still writes to that file.
            self.cur = {"ino": st.st_ino, "offset": 0,
                        "replaced": {"ino": ino, "offset": self.cur["offset"]}}
            self.save()
        elif st.st_size < self.cur["offset"]:
            self.emit(f"DAEMON-FOLLOW {self.log} is shorter than the saved position "
                      f"({st.st_size} < {self.cur['offset']}): truncated; reading from the start")
            self.cur["offset"] = 0
            self.save()
        if st.st_size > self.cur["offset"] or st.st_ino != ino:
            self.drain(self.log, self.cur["ino"])

    # -- the unit -------------------------------------------------------------

    def check_unit(self, now: float) -> None:
        s = svc().status(self.unit)
        active = s["active"] == "active"
        nr = s["restarts"]
        prev_nr = self.cur.get("nrestarts")
        # A unit the last check saw STOPPED - inactive or failed, with nothing
        # going to restart it (a restart the manager has scheduled reads
        # activating) - can only be running again because something outside
        # started it: the start the GUARD alert below names, or a person's.
        # launchd counts that start in `runs` (restarts are runs - 1, kickstart
        # included), so without this the recovery the alert asked for reads as a
        # crash and its DAEMON-OK never comes. So that rise is no restart of the
        # unit's own. `stopped` is kept across arms (`was_active` is not), so a
        # start made while no follower ran is not misread either. The price: a
        # crash in the same interval as that start reads as the recovery too; its
        # lines are in the log the follower delivers, and the next one is counted.
        rose = prev_nr is not None and nr > prev_nr and not self.cur.get("stopped")
        desc = (f"{s['active']}/{s['sub']}, result={s['result']}"
                + (f", load={s['load']}" if s["load"] != "loaded" else ""))
        msg = None
        if not active:
            hint = ""
            if s["load"] == "not-found":
                hint = " - the unit is not installed (agent-daemons.py --install)"
            elif s["active"] == "inactive" and s["result"] == "success":
                hint = (" - a clean exit is a GUARD refusal (another copy holds the lock, "
                        "or CLAUDE_CONFIG_DIR is not the owner); its line is in the log; "
                        "fix that, then " + svc().hint("start", self.unit))
            due = (self.cur.get("was_active") is not False
                   or now - self.cur.get("alerted_at", 0) >= REALERT_SECS or rose)
            if due:
                msg = f"DAEMON-ALERT {self.unit} is not active ({desc}){hint}"
        elif rose:
            msg = (f"DAEMON-ALERT {self.unit} restarted on its own {nr - prev_nr} time(s) "
                   f"since the last check ({desc}); the reason is in {self.log}")
        elif self.cur.get("was_active") is False:
            msg = f"DAEMON-OK {self.unit} is active again"
        if msg:
            self.emit(msg)
            self.cur["alerted_at"] = now
        self.cur["was_active"] = active
        self.cur["stopped"] = s["active"] in ("inactive", "failed")
        self.cur["nrestarts"] = nr
        self.save()

    def run(self, once=False) -> None:
        self.load()
        # Forget the last arm's verdict: a session that just armed is told about a
        # unit that is down now, whatever an earlier follower already said.
        self.cur.pop("was_active", None)
        started = time.monotonic()
        next_check = started + min(self.check_secs, FIRST_CHECK_SECS)
        while True:
            if not once and self.max_secs and time.monotonic() - started >= self.max_secs:
                self.emit(f"DAEMON-FOLLOW {self.label}: stopping after {self.max_secs:.0f} s, "
                          f"before the Monitor's 30-minute kill; nothing undelivered is "
                          f"lost - re-arm the follower to keep receiving")
                return
            self.poll_log()
            if once or time.monotonic() >= next_check:
                self.check_unit(time.time())
                next_check = time.monotonic() + self.check_secs
            if once:
                return
            time.sleep(self.poll_secs)


def cmd_follow(a) -> None:
    js = jobs()
    if a.job not in js:
        refuse(f"unknown job {a.job!r}; one of {', '.join(js)}")
    # A watch job with no --include gets its transport's follow_include; an
    # explicit --include (an empty one included, which means no filter) wins.
    include = js[a.job]["include"] if a.include is None else a.include
    priority = priority_default() if a.priority is None else a.priority
    log = a.log or log_path(a.agent, a.job)
    unit = a.unit or unit_name(a.job, a.agent)
    os.makedirs(os.path.dirname(log), exist_ok=True)
    lock = os.open(log + ".follow.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print(f"DAEMON-FOLLOW another follower already delivers {log}; not following",
              flush=True)
        sys.exit(0)
    f = Follower(log, unit, include, a.exclude, priority, a.replay_max,
                 a.check_secs, a.poll_secs, max_secs=a.max_secs,
                 label=f"follow {a.agent} {a.job}")
    try:
        f.run(once=a.once)
    except BrokenPipeError:
        # The Monitor went away mid-line. The cursor was not advanced past it.
        os._exit(0)
    except KeyboardInterrupt:
        pass


# ---------------------------------------------------------------------------
# rotate, exec: no host settings, nothing from fleetlib
# ---------------------------------------------------------------------------


def rotate(log: str, max_bytes: int) -> None:
    try:
        size = os.path.getsize(log)
    except FileNotFoundError:
        return
    if size > max_bytes:
        os.replace(log, log + ".1")


def cmd_rotate(a) -> None:
    rotate(a.log, a.max_bytes)


def read_env_file(path: str) -> dict:
    """KEY=VALUE lines as systemd's EnvironmentFile reads them: blank lines and
    lines starting with # or ; skipped, one pair of matching outer quotes
    removed. A missing file is no variables (the units' EnvironmentFile=-)."""
    try:
        with open(path) as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return {}
    out = {}
    for line in lines:
        line = line.strip()
        if not line or line[0] in "#;" or "=" not in line:
            continue
        k, v = (x.strip() for x in line.split("=", 1))
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            v = v[1:-1]
        out[k] = v
    return out


def cmd_exec(argv) -> None:
    """exec --log <log> [--env-file <f>] [--max-bytes N] -- <argv>..."""
    usage = "usage: agent-daemons.py exec --log <log> [--env-file <f>] [--max-bytes N] -- <argv>..."
    if "--" not in argv:
        refuse(usage)
    i = argv.index("--")
    opts, target = argv[:i], argv[i + 1:]
    known = {"--log": None, "--env-file": None, "--max-bytes": str(MAX_LOG_BYTES)}
    while opts:
        if opts[0] not in known or len(opts) < 2:
            refuse(usage)
        known[opts[0]] = opts[1]
        opts = opts[2:]
    if not known["--log"] or not target:
        refuse(usage)
    log = known["--log"]
    rotate(log, int(known["--max-bytes"]))
    # launchd opened stdout and stderr on the log before this ran; after a
    # rotation those descriptors name <log>.1, so both are pointed at <log> again.
    fd = os.open(log, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    os.dup2(fd, 1)
    os.dup2(fd, 2)
    if fd > 2:
        os.close(fd)
    env = dict(os.environ)
    if known["--env-file"]:
        env.update(read_env_file(known["--env-file"]))
    try:
        os.execve(target[0], target, env)
    except OSError as e:
        print(f"agent-daemons.py exec: cannot run {target[0]}: {e}", file=sys.stderr, flush=True)
        sys.exit(127)


# ---------------------------------------------------------------------------
# jobs
# ---------------------------------------------------------------------------


def cmd_jobs(a) -> None:
    """The job table: jobs() plus each job's unit file and log (relative to the
    agent home). `fleet` reads the --json form, so this table is the only place
    the job list, the unit and log names and the interpreter are written down.
    Under launchd a job has no unit shared by every agent: `unit` is null, and
    each agent's label is fleetlib.services.unit("job", agent, job)."""
    templated = svc().backend() == "systemd"
    table = {job: {**j, "unit": unit_name(job, "") if templated else None, "log": log_rel(job)}
             for job, j in jobs().items()}
    if a.json:
        print(json.dumps({"python": python(), "jobs": table}, indent=2))
        return
    for job, j in table.items():
        print(f"{job}\t{j['unit'] or '-'}\t{j['script']}")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def cmd_status(a) -> None:
    S = svc()
    rows, down = {}, 0
    for job, j in jobs().items():
        unit = unit_name(job, a.agent)
        s = S.status(unit)
        configured = os.path.exists(os.path.join(root(), a.agent, j["config"]))
        argv = S.proc_argv(s["pid"]) if s["pid"] > 0 else None
        # A daemon writing to a replaced log runs and is not heard: DEAF, exit 1.
        drift = log_drift(s["pid"], a.agent, job) if s["pid"] > 0 else None
        rows[job] = {"unit": unit, "configured": configured, **s, "argv": argv,
                     "log": log_path(a.agent, job), "log_replaced": drift}
        down += configured and (s["active"] != "active" or isinstance(drift, str))
    if a.json:
        print(json.dumps({"agent": a.agent, "backend": S.backend(), "jobs": rows}, indent=2))
    else:
        for job, r in rows.items():
            state = (f"{r['active']}/{r['sub']} pid={r['pid']} restarts={r['restarts']}"
                     if r["configured"] else f"no {jobs()[job]['config']}: not installed")
            flag = "ok  " if r["active"] == "active" or not r["configured"] else "DOWN"
            if r["configured"] and flag == "ok  " and isinstance(r["log_replaced"], str):
                # refresh, not a plain restart: refresh salvages what the daemon
                # wrote to the replaced file first, and a plain restart loses it.
                flag = "DEAF"
                state += (f"; {r['log_replaced']}; run refresh, which salvages what it wrote there and "
                          f"restarts it ({python()} {os.path.join(HERE, 'agent-daemons.py')} refresh)")
            print(f"{flag}  {job}\t{r['unit']}\t{state}")
    sys.exit(1 if down else 0)


# ---------------------------------------------------------------------------
# refresh
# ---------------------------------------------------------------------------


# The log a unit names is opened ONCE, when the process starts: systemd's
# StandardOutput=append:<log>, launchd's StandardOutPath plus the `exec` shim's
# reopen. A tool that rewrites the log in place (`sed -i`, any write-a-copy-
# and-rename) gives the path a new inode while the daemon keeps appending to the
# old one, now unlinked: the follower reads a file that never grows, and the
# agent is deaf with every unit active and every pid unchanged. Moving the log
# away does the same with the old inode still named. Only a restart reopens the
# path, so `refresh` restarts such a process and `status` reports it.
#
# The path compared is the job table's (log_path), not one read from the unit:
# systemd does not report an append: target (`systemctl show` prints
# `StandardOutput=append` and nothing else - measured on systemd 259), and the
# table is what the follower reads and what the units are rendered from
# (agent-daemons.test.py control Q). A unit edited by hand to write elsewhere
# is restarted on every refresh, each restart announced by a DAEMON-REFRESH line
# in the log the follower reads: loud, which that misconfiguration should be.
# A descriptor that is not a regular file (a pipe, a socket, a terminal: a
# daemon run by hand, or a unit writing to the journal) is not this check's to
# judge, so it can never start a restart loop.
LSOF = "/usr/sbin/lsof"   # macOS ships it there; launchd's PATH would find it too


def parse_lsof(text: str) -> dict:
    """{fd: (name, ino, dev, deleted)} for the regular files in `lsof -F ftikn`
    output (one field per line, a letter then the value; `f` starts a file).
    lsof gives no comparable device number, so dev is None; `deleted` is True
    when the link count (`k`, with +L) is 0, None when lsof printed none."""
    out, cur = {}, None
    for line in text.splitlines():
        key, val = line[:1], line[1:]
        if key == "f":
            cur = {}
            if val.isdigit():
                out[int(val)] = cur
        elif cur is not None and key in "tikn":
            cur[key] = val
    files = {}
    for fd, c in out.items():
        if c.get("t") != "REG" or not c.get("i", "").isdigit():
            continue
        name = c.get("n", "")
        k = c.get("k")
        deleted = (k == "0") if k is not None and k.isdigit() else None
        files[fd] = (name.removesuffix(" (deleted)"), int(c["i"]), None,
                     True if name.endswith(" (deleted)") else deleted)
    return files


def stdio_files(pid: int) -> dict:
    """{fd: (name, ino, dev, deleted)} for each of process `pid`'s stdout and
    stderr that is a regular file; an fd that cannot be read is left out, so {}
    is "nothing to judge", never "fine". A procfs (Linux, or the test seam on
    any OS): readlink and stat of <proc>/<pid>/fd/<n>; stat follows the fd to the
    open file even when no name is left (`st_nlink` 0, the link text ending in
    ` (deleted)`). macOS has no procfs: lsof, which ships with the system and
    reads the descriptors of the caller's own processes. fleetlib.services
    owns the choice of procfs, so it is asked for it."""
    proc = svc()._procfs()
    if proc:
        files = {}
        for fd in (1, 2):
            p = os.path.join(proc, str(pid), "fd", str(fd))
            try:
                name, st = os.readlink(p), os.stat(p)
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode):
                files[fd] = (name.removesuffix(" (deleted)"), st.st_ino, st.st_dev,
                             name.endswith(" (deleted)") or st.st_nlink == 0)
        return files
    if sys.platform != "darwin":
        return {}
    try:
        r = subprocess.run([LSOF, "-n", "-P", "+L", "-a", "-p", str(pid), "-d", "1,2", "-F", "ftikn"],
                           capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    return parse_lsof(r.stdout)


def drifted(files: dict, log: str) -> list:
    """[(fd, entry)] of `files` (stdio_files) whose file is not the one at `log`
    (inode, and device where known), in fd order."""
    try:
        st = os.stat(log)
        here = (st.st_ino, st.st_dev)
    except OSError:
        here = None
    return [(fd, e) for fd, e in sorted(files.items())
            if not (here and e[1] == here[0] and e[2] in (None, here[1]))]


def replaced_log(files: dict, log: str):
    """Why the output in `files` (stdio_files) does not reach `log`, or None."""
    for _fd, (name, _ino, _dev, deleted) in drifted(files, log):
        if deleted or (deleted is None and name == log):
            return "the daemon's fd points at a deleted inode"
        return f"the daemon's fd points at {name}, not the file at that path"
    return None


def log_drift(pid: int, agent: str, job: str):
    """`writes to a replaced log (<log>: <why>)` for a running job; False when
    its output reaches the log; None when there is nothing to judge (no
    readable stdout or stderr that is a regular file). `status --json` carries
    the three as its `log_replaced`, and None is never read as False."""
    files = stdio_files(pid)
    if not files:
        return None
    log = log_path(agent, job)
    why = replaced_log(files, log)
    return f"writes to a replaced log ({log}: {why})" if why else False


# SALVAGE. Between the replacement and the restart the daemon writes into the
# replaced file, which no follower reads: exactly the lines the agent never
# heard. Before refresh restarts such a daemon it reads that file through the
# daemon's own descriptor (<proc>/<pid>/fd/<n>, which opens a file with no name
# left) and appends to the file at the log path, before its DAEMON-REFRESH line,
# the lines nobody has, under one header:
#   DAEMON-SALVAGE <n> line(s) the daemon wrote to the replaced log <log> before this restart
# They land after the follower's cursor, so its next pass delivers them like any
# line (more than --replay-max arrive condensed, as any backlog does). The
# DAEMON-REFRESH line ends `; salvage: <n> line(s)` or `; salvage: none, <why>`.
#
# THE BOUNDARY: how many leading lines of the replaced file (OLD) somebody
# already has. The replacing tool usually copied them into the new file (NEW),
# often edited (sed -i renames ids, changes lengths, deletes lines), and the
# follower delivered some of them from OLD before it lost it. refresh's own
# lines (DAEMON-SALVAGE, DAEMON-REFRESH) are left out of both files first, so a
# salvage repeated after a failed restart adds only what is new since.
#   1. NEW's last line occurs exactly once in OLD: everything up to it. Exact and
#      unique, it holds whatever the tool deleted or inserted above it.
#   2. Else NEW is OLD's first len(NEW) lines, each the same or a rewrite of it
#      (rewritten(): its unchanged start and end hold half the characters, or
#      the words unchanged in place do): that prefix. This is the case of a
#      rewritten last line.
#   3. NEW is empty (every line deleted, or the log moved away): the files hold
#      no evidence, so only the follower's position counts.
# The follower's position in OLD counts in every case (its cursor names OLD's
# inode, or records it as the file it left at the replacement): the boundary is
# the later of the two, which also covers lines it delivered from OLD after the
# tool read it. OLD at <log>.1 with the cursor still naming it is the
# follower's to drain whole (a rotation's path), so none of it is salvaged.
# NEW with lines and neither 1 nor 2, or NEW empty and no cursor naming OLD:
# nothing is salvaged, `salvage: none, boundary not found`.
# One refresh at a time (cmd_refresh's lock): two runs reading NEW before either
# appends would each salvage the same lines.
# Where it errs:
#   - rule 1 over- or under-includes when the tool rewrote NEW's last line into
#     exactly one other line of OLD (it anchors there);
#   - rule 2 on lines that look alike: a deleted or inserted line can pass as a
#     rewrite of its neighbour, so the salvage is off by that many lines - a
#     duplicate, which the follower's position corrects when it is later, or a
#     lost line;
#   - rule 3 includes lines written before the replacement that no follower had
#     delivered: heard once, for the first time, though the tool removed them;
#   - a second replacement after the follower's last pass leaves its `replaced`
#     record untrusted (the cursor's file is no longer at the path), so an empty
#     NEW then reads `boundary not found`;
#   - the lines the daemon writes between this read and its stop (and what it
#     prints on SIGTERM) are not salvaged.
# stdout and stderr are one file under every unit the fleet renders (systemd
# shares the descriptor, launchd's exec shim dups one fd to both), so the first
# descriptor that drifted is the file read.
# macOS has no /proc, and no unprivileged way to read a file another process
# holds once its last name is gone: lsof names the fd, nothing reads it. A
# moved log is read by the name lsof reports (its inode checked); a deleted one
# is not salvaged, and the DAEMON-REFRESH line says so.
SALVAGE_OWN = (b"DAEMON-SALVAGE ", b"DAEMON-REFRESH ")


def log_lines(data: bytes) -> list:
    """`data`'s lines without their newline, refresh's own lines left out; a last
    line with no newline counts (the restart ends it unfinished)."""
    lines = data.split(b"\n")
    if lines and not lines[-1]:
        lines.pop()
    return [ln for ln in lines if not ln.startswith(SALVAGE_OWN)]


def _common(a: bytes, b: bytes, tail: bool) -> int:
    """The length of the longest common prefix (or, with `tail`, suffix) of a and
    b, by bisection over slice comparisons: O(n log n) in C, not a Python loop."""
    lo, hi = 0, min(len(a), len(b))
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if (a[len(a) - mid:] == b[len(b) - mid:]) if tail else (a[:mid] == b[:mid]):
            lo = mid
        else:
            hi = mid - 1
    return lo


def rewritten(a: bytes, b: bytes) -> bool:
    """`b` is `a`, or `a` with part of it rewritten: the unchanged start and end
    hold half the characters (one edited stretch between them, as one sed s///
    makes), or the words unchanged in place do (several edits). Half means
    4 * kept >= len(a) + len(b), difflib's ratio 0.5. Near-linear in the line
    (bisection over slices), so a log rewritten end to end costs well under a
    second, not minutes."""
    if a == b:
        return True
    head = _common(a, b, False)
    if 4 * (head + min(_common(a, b, True), min(len(a), len(b)) - head)) >= len(a) + len(b):
        return True
    wa, wb = a.split(), b.split()
    return len(wa) == len(wb) > 0 and 4 * sum(len(x) for x, y in zip(wa, wb) if x == y) >= len(a) + len(b)


def salvage_lines(old: bytes, new: bytes, delivered=None):
    """(the lines of `old` nobody has, None) or (None, why): THE BOUNDARY above.
    `delivered` is the follower's byte offset in `old`, or None."""
    o, n = log_lines(old), log_lines(new)
    k = None
    if n and o.count(n[-1]) == 1:
        k = o.index(n[-1]) + 1
    elif n and len(n) <= len(o) and all(rewritten(x, y) for x, y in zip(n, o)):
        k = len(n)
    seen = (len(log_lines(old[:delivered]))
            if isinstance(delivered, int) and 0 <= delivered <= len(old) else None)
    if k is None:
        if n or seen is None:
            return None, "boundary not found"
        k = 0
    return o[max(k, seen or 0):], None


def _ino(path: str):
    try:
        return os.stat(path).st_ino
    except OSError:
        return None


def delivered_offset(log: str, ino: int, size: int):
    """How far the follower has delivered, or will deliver by itself, the file with
    inode `ino` and `size` bytes; None when its cursor does not say.
    - The cursor names that inode: its offset - or `size` when the file is
      <log>.1, which the follower drains whole on its next pass (poll_log), so
      nothing of it is the salvage's;
    - its `replaced` record names it (the follower left that file at a
      replacement): that offset, trusted only while the file the cursor names is
      still the one at the path, so a record from an older replacement never
      meets a reused inode number."""
    try:
        with open(log + ".cursor") as f:
            cur = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(cur, dict):
        return None
    if cur.get("ino") == ino and isinstance(cur.get("offset"), int):
        return size if _ino(log + ".1") == ino else cur["offset"]
    rep = cur.get("replaced")
    if (isinstance(rep, dict) and rep.get("ino") == ino and isinstance(rep.get("offset"), int)
            and cur.get("ino") is not None and _ino(log) == cur["ino"]):
        return rep["offset"]
    return None


def read_replaced(pid: int, fd: int, entry: tuple, proc):
    """(bytes, None) of the file process `pid` holds as `fd` (`entry` is
    stdio_files' (name, ino, dev, deleted)), or (None, why). Through
    <proc>/<pid>/fd/<fd> when there is a procfs; else (macOS) by the name lsof
    reported, which exists only while the file has one."""
    name, ino, _dev, deleted = entry
    if proc:
        path = os.path.join(proc, str(pid), "fd", str(fd))
    elif not deleted and name:
        path = name
    else:
        return None, "the replaced file is deleted, and without /proc (macOS) nothing can read it"
    try:
        with open(path, "rb") as f:
            if os.fstat(f.fileno()).st_ino != ino:
                return None, f"{path} is no longer the file the daemon writes"
            return f.read(), None
    except OSError as e:
        return None, f"the replaced file cannot be read ({e.strerror})"


def salvage(pid: int, log: str) -> tuple:
    """(what to append before the DAEMON-REFRESH line, the note that line ends
    with) for process `pid`, whose output goes to a replaced log: SALVAGE above."""
    drift = drifted(stdio_files(pid), log)
    if not drift:
        return b"", "salvage: none, the replaced file was not found again"
    fd, entry = drift[0]
    old, why = read_replaced(pid, fd, entry, svc()._procfs())
    if old is None:
        return b"", f"salvage: none, {why}"
    try:
        with open(log, "rb") as f:
            new = f.read()
    except FileNotFoundError:
        new = b""
    except OSError as e:
        return b"", f"salvage: none, {log} cannot be read ({e.strerror})"
    lines, why = salvage_lines(old, new, delivered_offset(log, entry[1], len(old)))
    if lines is None:
        return b"", f"salvage: none, {why}"
    head = (f"DAEMON-SALVAGE {len(lines)} line(s) the daemon wrote to the replaced log {log} "
            f"before this restart\n").encode()
    return (head + b"".join(ln + b"\n" for ln in lines) if lines else b""), f"salvage: {len(lines)} line(s)"


def process_inputs(pid: int, agent: str, job: str, unit: str) -> tuple:
    """(script, config, source) of the RUNNING process: the script is the first
    argument after the interpreter that is not an option (its argv), the config
    is the job's config variable in its environment, else the agent's
    config/<file>. Read from the process, so the answer is right whether it runs
    the product copy, the fleet copy or a canary tree. Where the environment
    cannot be read (macOS: always), the config comes from what the service
    manager started the job with (its definition), and `source` says so."""
    j = jobs()[job]
    S = svc()
    argv = S.proc_argv(pid) or []
    script = next((x for x in argv[1:] if not x.startswith("-")), None)
    env, source, defn = S.proc_env(pid), "process", None
    if env is None:
        defn = S.definition(unit)
        env, source = (defn["env"], "job definition") if defn else ({}, "default")
        if script is None and defn:
            # argv unreadable too: the definition's command, past the exec shim's `--`.
            tail = defn["argv"][defn["argv"].index("--") + 1:] if "--" in defn["argv"] else defn["argv"]
            script = next((x for x in tail[1:] if not x.startswith("-")), None)
    config = env.get(j["config_env"])
    if not config:
        config, source = os.path.join(root(), agent, j["config"]), "default"
    cwd = S.proc_cwd(pid) or (defn or {}).get("workdir")

    def absolute(p):
        return p if p is None or os.path.isabs(p) or cwd is None else os.path.join(cwd, p)
    return absolute(script), absolute(config), source


def _shown(path: str, home: str) -> str:
    """A path under the agent home is shown relative to it, as the reasons always were."""
    return os.path.relpath(path, home) if path.startswith(home + os.sep) else path


def stale_reason(agent: str, job: str, inputs: tuple, started: float, now: float,
                 max_age: float):
    home = os.path.join(root(), agent)
    script, config, _ = inputs
    for path in (script, config, os.path.join(home, "config", f"{job}.env")):
        if not path:
            continue
        try:
            if os.path.getmtime(path) > started:
                return f"{_shown(path, home)} changed after the process started"
        except OSError:
            continue
    if now - started > max_age:
        return f"daily restart (process up {(now - started) / 3600:.0f} h)"
    return None


def cmd_refresh(a) -> None:
    # The host settings first, or exit 3 with one line naming the path read. Without
    # them the label prefix falls back to its default, no job is found, and the run
    # would end 0 having refreshed nothing, which is all a timer's log could show.
    fleetlib().paths.host()
    S = svc()
    now = time.time()
    dry = "DRY-RUN " if a.dry_run else ""
    if not dry:
        # One refresh at a time on the host: the timer's and one run by hand would
        # otherwise each salvage the same lines (SALVAGE). The second one does
        # nothing and exits 0, as a duplicate follower does. A dry run writes
        # nothing, this file included. A lock that cannot be made is no reason to
        # leave every deaf daemon deaf: the run goes on without it, and says so.
        lock = refresh_lock()
        held = None
        try:
            os.makedirs(os.path.dirname(lock), exist_ok=True)
            held = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
        except OSError:
            try:
                held = os.open(lock, os.O_RDONLY)       # flock needs no write access
            except OSError as e:
                print(f"refresh runs without its lock: {lock}: {e.strerror}", file=sys.stderr, flush=True)
        if held is not None:
            try:
                fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print(f"another refresh holds {lock}; this one does nothing", flush=True)
                return
            except OSError as e:
                # Not held by anyone: flock itself failed (a filesystem without locks).
                print(f"refresh runs without its lock: flock on {lock}: {e.strerror}", file=sys.stderr, flush=True)
    for job, agent, unit in S.instances(jobs()):
        s = S.status(unit)
        pid = s["pid"]
        if s["active"] != "active" or pid <= 0:
            # A unit that is down is the follower's alert, never started from here.
            if dry:
                print(f"{dry}skip {unit}: not active ({s['active']})", flush=True)
            continue
        started = S.proc_start(pid)
        if started is None:
            if dry:
                print(f"{dry}skip {unit}: no start time for pid {pid}", flush=True)
            continue
        inputs = process_inputs(pid, agent, job, unit)
        drift = log_drift(pid, agent, job)
        reason = drift or stale_reason(agent, job, inputs, started, now, a.max_age_hours * 3600)
        if not reason:
            if dry:
                home = os.path.join(root(), agent)
                script, config, source = inputs
                print(f"{dry}keep {unit}: up {(now - started) / 3600:.1f} h, script "
                      f"{_shown(script or '?', home)}, config {_shown(config, home)}"
                      + ("" if source == "process" else f" (config from {source})"), flush=True)
            continue
        # A daemon writing to a replaced log: the lines it wrote there go first (SALVAGE).
        text = b""
        if isinstance(drift, str):
            text, salvaged = salvage(pid, log_path(agent, job))
            reason = f"{reason}; {salvaged}"
        if dry:
            # Nothing is written to the log: a session would read it as a restart.
            print(f"{dry}restart {unit}: {reason}", flush=True)
            continue
        note = f"DAEMON-REFRESH restarting {unit}: {reason}"
        print(note, flush=True)
        # Into the file AT the log path, which is the one the follower reads; for a
        # replaced log that is the new file, so the salvage and the reason reach the
        # session, after its cursor and in order.
        try:
            data = text + (note + "\n").encode()
            fd = os.open(log_path(agent, job), os.O_RDWR | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                # On a line of its own: a file that ends mid-line (a tool that
                # dropped the last newline, a daemon cut off mid-write) would
                # otherwise glue the block to it, and `^DAEMON-` would match nothing.
                end = os.fstat(fd).st_size
                if end and os.pread(fd, 1, end - 1) != b"\n":
                    data = b"\n" + data
                while data:
                    data = data[os.write(fd, data):]
            finally:
                os.close(fd)
        except OSError as e:
            print(f"could not note the restart in the log: {e}", file=sys.stderr)
        try:
            S.restart(unit)
        except fleetlib().FleetError as e:
            print(f"restart of {unit} failed: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# render-units
# ---------------------------------------------------------------------------


def unit_plan(units: str) -> list:
    """[(template under systemd/, unit file name, job or None, agent or None)] for --units."""
    S = svc()
    if S.backend() == "systemd":
        plan = [(src, name, None, None) for src, name in REFRESH_UNITS]
        if units == "all":
            plan += [(j["template"], unit_name(job, ""), job, None) for job, j in jobs().items()]
        return plan
    plan = [(REFRESH_PLIST, S.unit_file(S.unit("refresh")), None, None)]
    if units == "all":
        js = jobs()
        plan += [(js[job]["template"], S.unit_file(name), job, agent)
                 for job, agent, name in S.instances(js)]
    return plan


@functools.cache
def project_dir() -> str:
    """The install checkout's directory name under each agent home: the one
    directory holding .claude/fleet.json, required identical across every agent
    home under the agents root (the fleet tree itself is not an agent home)."""
    found = {}
    for m in glob.glob(os.path.join(glob.escape(root()), "*", "*", ".claude", "fleet.json")):
        checkout = os.path.dirname(os.path.dirname(m))
        home = os.path.dirname(checkout)
        if os.path.realpath(home) != FLEET:
            found.setdefault(home, []).append(os.path.basename(checkout))
    several = sorted(f"{h} ({', '.join(sorted(n))})" for h, n in found.items() if len(n) > 1)
    if several:
        raise Fault(f"more than one install checkout in an agent home: {'; '.join(several)}")
    names = sorted({n[0] for n in found.values()})
    if len(names) != 1:
        raise Fault(f"the agent homes under {root()} must hold their install checkout "
                    f"(<home>/<dir>/.claude/fleet.json) under ONE directory name; found "
                    + (", ".join(f"{h}: {n[0]}" for h, n in sorted(found.items())) or "none"))
    return names[0]


def refresh_log() -> str:
    """The launchd refresh job's log, beside the fleet's upgrades.log."""
    return os.path.join(os.path.expanduser("~"), ".local", "state", "agent-fleet", "daemons-refresh.log")


def refresh_lock() -> str:
    """The lock one refresh run holds, beside refresh_log()."""
    return os.path.join(os.path.dirname(refresh_log()), "daemons-refresh.lock")


def substitutions(job, agent=None, host_config=None) -> dict:
    S = svc()
    # Every unit and plist names a host settings file as FLEET_HOST_CONFIG: launchd
    # starts a job with the user's real HOME, and on both backends a daemon then
    # reads the file the install wrote, wherever it is. That file is `host_config`
    # (render-units --host-config) when given, else the one this render reads.
    # `fleet install` READS a candidate in a temporary directory, which is gone
    # when it returns, and names the file it writes; a unit naming the candidate
    # starts every daemon against a missing file (refresh exits 3).
    subs = {"FLEET": FLEET, "PYTHON": python(),
            "HOST_CONFIG": os.path.abspath(os.path.expanduser(host_config or fleetlib().paths.host_config_path()))}
    if S.backend() == "launchd":
        # launchd's own PATH lacks Homebrew, where the interpreter and tmux live.
        subs["PATH"] = f"{os.path.dirname(python())}:/usr/bin:/bin:/usr/sbin:/sbin"
        subs["LABEL"] = S.unit("refresh") if job is None else S.unit("job", agent, job)
        if job is None:
            subs["REFRESH_LOG"] = refresh_log()
    if job is None:
        return subs
    j = jobs()[job]
    subs.update(AGENTS_ROOT=root(), PROJECT_DIR=project_dir(), JOB=job,
                SCRIPT=j["script"], CONFIG=j["config"], CONFIG_ENV=j["config_env"])
    if agent:
        subs["AGENT"] = agent
    if j["transport"]:
        subs["DESC"] = f"{j['transport'].capitalize()} watcher ({os.path.basename(j['script'])})"
        subs["ENV_PREFIX"] = j["config_env"].removesuffix("_CONFIG")
    return subs


def fleet_tag() -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    try:
        r = subprocess.run(["git", "-C", FLEET, "describe", "--tags", "--always"],
                           capture_output=True, text=True, timeout=20, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else "unknown"


def render(src: str, subs: dict, tag: str) -> bytes:
    with open(os.path.join(HERE, src)) as f:
        text = f.read()
    return svc().render(src, text, subs, tag)


def replace_file(path: str, data: bytes) -> None:
    """Put `data` at `path` by renaming a temp file in the same directory over it.
    A symlink at `path` is REPLACED, never written through: an open(path, 'w')
    follows the link and overwrites the file it points at, which for a unit linked
    from another repository is that repository's file."""
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path),
                               prefix=f".{os.path.basename(path)}.")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def cmd_render(a) -> None:
    plan = unit_plan(a.units)
    if a.list:
        for _, name, _, _ in plan:
            print(name)
        return
    if not a.out:
        refuse("render-units: give --out <dir> or --list")
    out = os.path.abspath(os.path.expanduser(a.out))
    tag = fleet_tag()
    # Every file is rendered before the first is written: a fault in one leaves
    # the directory as it was.
    rendered = [(src, os.path.join(out, name), render(src, substitutions(job, agent, a.host_config), tag))
                for src, name, job, agent in plan]
    os.makedirs(out, exist_ok=True)
    changed = 0
    for src, dest, data in rendered:
        link = os.readlink(dest) if os.path.islink(dest) else None
        if link is None:
            try:
                with open(dest, "rb") as f:
                    if f.read() == data:
                        continue
            except FileNotFoundError:
                pass
        replace_file(dest, data)
        changed += 1
        print(f"rendered {dest} from systemd/{src}"
              + (f", replacing a link to {link}" if link else ""), flush=True)
    if not changed:
        print("nothing changed")


# ---------------------------------------------------------------------------
# install / uninstall
# ---------------------------------------------------------------------------


def cmd_install(agents) -> None:
    for agent in agents:
        if not os.path.isdir(os.path.join(root(), agent)):
            refuse(f"REFUSED: {os.path.join(root(), agent)} is not an agent home")
    S = svc()
    unit_dir = str(S.unit_dir())
    launchd = S.backend() == "launchd"
    need = unit_plan("refresh" if launchd else "all")
    missing = [name for _, name, _, _ in need if not os.path.exists(os.path.join(unit_dir, name))]
    if missing:
        refuse(f"REFUSED: {', '.join(missing)} not in {unit_dir}: render the units first "
               f"(fleet install --units all)")
    if launchd:
        os.makedirs(os.path.dirname(refresh_log()), exist_ok=True)
        S.enable(S.unit("refresh"), now=True)
    else:
        S.reload()
        S.enable(TIMER, now=True)
    tag = fleet_tag() if launchd else None
    for agent in agents:
        os.makedirs(os.path.join(root(), agent, LOG_DIR), mode=0o700, exist_ok=True)
        for job, j in jobs().items():
            unit = unit_name(job, agent)
            if not os.path.exists(os.path.join(root(), agent, j["config"])):
                print(f"SKIPPED {unit}: {agent} has no {j['config']}")
                continue
            # A cursor BEFORE the first start, so the first follower delivers the
            # unit's output from its first line rather than from wherever the log
            # had got to by the time a session armed it.
            Follower(log_path(agent, job), unit).load()
            if launchd:
                replace_file(os.path.join(unit_dir, S.unit_file(unit)),
                             render(j["template"], substitutions(job, agent), tag))
            S.enable(unit, now=True)
            print(f"enabled {unit}")


def cmd_uninstall(agents) -> None:
    S = svc()
    FleetError = fleetlib().FleetError
    launchd = S.backend() == "launchd"
    every = not agents
    if every:
        units = [name for _, _, name in S.instances(jobs())]
    else:
        units = [unit_name(j, a) for a in agents for j in jobs()]
    if every:
        units.append(S.unit("refresh") if launchd else TIMER)
    for unit in units:
        try:
            S.disable(unit, now=True)
        except FleetError as e:
            print(f"could not disable {unit}: {e}", file=sys.stderr)
        if launchd:
            try:
                os.remove(os.path.join(str(S.unit_dir()), S.unit_file(unit)))
            except FileNotFoundError:
                pass
        print(f"disabled {unit}")
    if every and not launchd:
        unit_dir = str(S.unit_dir())
        for _, name, _, _ in unit_plan("all"):
            try:
                os.remove(os.path.join(unit_dir, name))
            except FileNotFoundError:
                pass
        try:
            S.reload()
        except FleetError as e:
            print(f"daemon-reload failed: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------


def run(argv) -> None:
    if argv and argv[0] == "exec":
        cmd_exec(argv[1:])          # before anything that could import fleetlib
        return
    if argv and argv[0] in ("--install", "--uninstall"):
        if argv[0] == "--install":
            if len(argv) < 2:
                refuse("usage: agent-daemons.py --install <agent> [<agent>...]")
            cmd_install(argv[1:])
        else:
            cmd_uninstall(argv[1:])
        return
    p = argparse.ArgumentParser(prog="agent-daemons.py", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("follow", help="print undelivered daemon log lines (run under a Monitor)")
    f.add_argument("agent")
    f.add_argument("job", help="sched, or a working transport's watch.job (slack-watch)")
    f.add_argument("--include", help="print only lines matching this regex (default for a "
                                     "watch job: its transport's follow_include; '' = no filter)")
    f.add_argument("--exclude", help="never print lines matching this regex")
    f.add_argument("--priority", help="lines a condensed backlog keeps first (default: "
                                      "SCHED due, SCHED alert, '<PREFIX> DM ' of each working "
                                      "transport, DAEMON-)")
    f.add_argument("--replay-max", type=int, default=20,
                   help="most lines printed from one backlog (default: %(default)s)")
    f.add_argument("--check-secs", type=float, default=60.0)
    f.add_argument("--poll-secs", type=float, default=0.5)
    f.add_argument("--max-secs", type=float, default=MAX_SECS_DEFAULT,
                   help="exit on its own after this long, before the Monitor's "
                        "30-minute kill (0 = never)")
    f.add_argument("--log", help=argparse.SUPPRESS)
    f.add_argument("--unit", help=argparse.SUPPRESS)
    f.add_argument("--once", action="store_true", help=argparse.SUPPRESS)
    f.set_defaults(fn=cmd_follow)
    r = sub.add_parser("rotate", help="ExecStartPre: move an oversized log to <log>.1")
    r.add_argument("log")
    r.add_argument("--max-bytes", type=int, default=MAX_LOG_BYTES)
    r.set_defaults(fn=cmd_rotate)
    sub.add_parser("exec", help="launchd's stand-in for ExecStartPre and EnvironmentFile: "
                                "exec --log <log> [--env-file <f>] -- <argv>...")
    j = sub.add_parser("jobs", help="print the job table (runs without host settings)")
    j.add_argument("--json", action="store_true", help="as JSON: the table `fleet` reads")
    j.set_defaults(fn=cmd_jobs)
    s = sub.add_parser("status", help="each job's unit, state and pid for one agent; "
                                      "exit 1 when a configured job is down")
    s.add_argument("agent")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_status)
    h = sub.add_parser("refresh", help="restart units whose code/config changed or that are a day old")
    h.add_argument("--max-age-hours", type=float, default=24.0)
    h.add_argument("--dry-run", action="store_true",
                   help="print every unit's decision; restart nothing, write nothing")
    h.set_defaults(fn=cmd_refresh)
    u = sub.add_parser("render-units", help="render the unit files from this tree's templates")
    u.add_argument("--units", required=True, choices=("refresh", "all"),
                   help="refresh: the refresh job; all: that, and the job units (systemd: "
                        "the scheduler template and one watch template per working "
                        "transport; launchd: every installed job instance's plist)")
    u.add_argument("--out", help="directory to write into (created when absent)")
    u.add_argument("--host-config", help="the host settings file every unit names as FLEET_HOST_CONFIG "
                                         "(default: the one this render reads); it need not exist yet")
    u.add_argument("--list", action="store_true", help="print the unit file names; write nothing")
    u.set_defaults(fn=cmd_render)
    a = p.parse_args(argv)
    a.fn(a)


def main(argv=None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    try:
        run(argv)
    except Fault as e:
        print(f"agent-daemons.py: {e}", file=sys.stderr, flush=True)
        sys.exit(3)
    except Exception as e:
        lib = sys.modules.get("fleetlib")
        if lib is not None and isinstance(e, lib.FleetError):
            print(f"agent-daemons.py: {e}", file=sys.stderr, flush=True)
            sys.exit(e.exit_code)
        raise


if __name__ == "__main__":
    main()
