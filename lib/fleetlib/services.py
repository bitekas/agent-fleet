"""The service manager, systemd or launchd, behind one interface.

Every fleet unit is one of four KINDS, named per backend:

  kind      systemd                                    launchd label
  job       agent-<job>@<agent>.service                <prefix>.<job>.<agent>
  refresh   agent-daemons-refresh.timer                <prefix>.daemons-refresh
  session   claude-agent-<agent>.service               <prefix>.session.<agent>
  watchdog  claude-agent-<agent>-stall-watchdog.service <prefix>.stall-watchdog.<agent>

`<prefix>` is host.json's optional `launchd_prefix` (paths.host_option). A
launchd job lives in a plist named `<label>.plist`; systemd has template units
(`agent-<job>@.service`) and launchd has none, so a launchd job is always one
agent's. The job names `session` and `stall-watchdog` are refused: under launchd
they would be the session's and the watchdog's labels.

SCOPES. "user": the user's own manager (`systemctl --user`; launchd's
`<launchd_domain>/<uid>`, gui by default). "system": the system manager
(`systemctl`; launchd's `system` domain), where the stall watchdog runs.

BACKEND. `FLEET_SERVICE_BACKEND=systemd|launchd`, else launchd on macOS and
systemd everywhere else. The process readers (proc_*, boot_time) follow the
PLATFORM, not the backend: a procfs tree when FLEET_PROC or AGENT_DAEMONS_PROC
names one (the test seam, on any OS) or the platform has /proc, the kernel's
sysctl on macOS. Programs: FLEET_SYSTEMCTL (else AGENT_DAEMONS_SYSTEMCTL, else
`systemctl`), FLEET_LAUNCHCTL (else /bin/launchctl). FLEET_LAUNCHD_SYSTEM_DIR
replaces /Library/LaunchDaemons, launchd's system unit directory (the test seam;
the user one moves with HOME).

status() answers in systemd's vocabulary on both backends, so a caller has one
set of words: load (loaded | not-found | unknown), active (active | inactive |
failed | activating | unknown), sub, result (success | exit-code | signal),
restarts, pid, error. last_exit() adds the exit code or signal that goes with
the last result.

LOAD-BEARING PROPERTIES - each is here because removing it opens a hole:

  * A LAUNCHD RESTART IS BOOTOUT THEN BOOTSTRAP, NEVER `kickstart -k`. kickstart
    restarts the process from the definition launchd LOADED, so a plist that
    changed since (a pinned tree, a new interpreter) would never take effect,
    while the restart reported success. services.test.py runs restart() against
    a mutant that uses kickstart -k and must see it fail.

  * THE PROCESS ENVIRONMENT IS UNKNOWN ON MACOS, NOT EMPTY. macOS gives another
    process's argv but not its environment (KERN_PROCARGS2 and `ps -E` both
    return argv only, even for the caller's own child: measured on macOS
    27.0.1). proc_env() is None there, never {}: an empty dict reads as "the
    variable is unset" and sends a caller to a default path silently. What a
    launchd job was started with is definition(), from what launchd LOADED.

  * THE LABEL PREFIX COMES FROM THE HOST. A test install and a real one on the
    same Mac differ only by prefix; a backend that ignored it would bootout the
    real fleet's jobs from a test run.

  * STATUS IS READ FROM THE TOP LEVEL OF `launchctl print` ONLY. Its nested
    blocks (resource coalition, jetsam coalition) carry their own `state =` and
    `active count =` lines.

  * A LAUNCHD `state = running` WITH NO `pid` LINE IS THE THROTTLE, NOT ACTIVE.
    launchd can print it for a KeepAlive job that just exited, before `spawn
    scheduled`. Read as active, the follower's next check after its not-active
    alert prints a DAEMON-OK for a job with no process, and `agent-daemons.py
    status` prints an ok row with pid=0.

  * A LAUNCHD BOOTSTRAP AFTER A BOOTOUT WAITS UNTIL THE LABEL IS GONE. bootout
    stops the process; a bootstrap that runs while launchd still holds the label
    fails, and a restart would then leave the job unloaded.

  * A SYSTEMD COMMAND RUNS TO ITS ` ; ignore_errors=`, NOT TO ITS FIRST `;`, AND
    EVERY LINE OF A REPEATED EXEC KEY IS A COMMAND. `systemctl show` prints each
    command as `Key={ path=P ; argv[]=A ; ignore_errors=... }`, A being the
    argv words joined by spaces with no quoting, one line per command (three
    ExecStartPre= lines print three ExecStartPre= lines). The agent unit's boot
    handshake is a `bash -c` script full of `;`, with the follower path the boot
    message names past its first one (measured on a live agent unit: the first
    `;` at offset 79, the follower at ~1050). A reader that stops at the first
    `;`, or keeps one line per key, hands `fleet status` a command without the
    follower, and its follower row then checks nothing. services.test.py pins
    both (controls C and L); bin/fleet.test.py pins the row on the agent unit
    template itself, serialized as systemd prints it.
"""

import functools
import os
import plistlib
import re
import shlex
import struct
import subprocess
import sys
import time
from pathlib import Path
from xml.sax.saxutils import escape

from . import EnvironmentFault, Refused
from . import paths
from .transports import RESERVED_JOBS
from .transports import _NAME as _JOB_NAME

BACKENDS = ("systemd", "launchd")
KINDS = ("job", "refresh", "session", "watchdog")
SCOPES = ("user", "system")
JOB_RE = _JOB_NAME                                  # a transport's watch.job rule
AGENT_RE = paths.AGENT_NAME
PLACEHOLDER = re.compile(r"@[A-Z][A-Z_]*@")
NOT_FOUND = "Could not find service"
BOOTOUT_WAIT_SECS = 30.0


# ------------------------------------------------------------------ selection

def backend():
    """'systemd' or 'launchd': $FLEET_SERVICE_BACKEND, else by platform."""
    name = os.environ.get("FLEET_SERVICE_BACKEND") or (
        "launchd" if sys.platform == "darwin" else "systemd")
    if name not in BACKENDS:
        raise EnvironmentFault(f"FLEET_SERVICE_BACKEND={name!r} is not one of {', '.join(BACKENDS)}",
                               variable="FLEET_SERVICE_BACKEND")
    return name


def _launchd():
    return backend() == "launchd"


def _scope(scope):
    if scope not in SCOPES:
        raise Refused(f"not a service scope: {scope!r} (one of {', '.join(SCOPES)})")
    return scope


def prefix():
    return paths.host_option("launchd_prefix")


# ------------------------------------------------------------------ names

def unit(kind, agent=None, job=None):
    """The unit name (systemd) or label (launchd) of a fleet unit. A systemd job
    with no agent is the template `agent-<job>@.service`."""
    if agent and not AGENT_RE.fullmatch(agent):
        raise Refused(f"not an agent name: {agent!r}")
    p = prefix() if _launchd() else None
    if kind == "job":
        if not isinstance(job, str) or not JOB_RE.fullmatch(job):
            raise Refused(f"not a job name: {job!r}")
        if job in RESERVED_JOBS:
            raise Refused(f"the job name {job!r} is reserved: under launchd it is the "
                          f"{job} unit's label")
        if p is None:
            return f"agent-{job}@{agent or ''}.service"
        if not agent:
            raise Refused("launchd has no template units: a job unit names its agent")
        return f"{p}.{job}.{agent}"
    if kind == "refresh":
        return f"{p}.daemons-refresh" if p else "agent-daemons-refresh.timer"
    if kind not in KINDS:
        raise Refused(f"not a unit kind: {kind!r} (one of {', '.join(KINDS)})")
    if not agent:
        raise Refused(f"a {kind} unit names its agent")
    if kind == "session":
        return f"{p}.session.{agent}" if p else f"claude-agent-{agent}.service"
    return f"{p}.stall-watchdog.{agent}" if p else f"claude-agent-{agent}-stall-watchdog.service"


def parse(name):
    """(kind, job, agent) of a fleet unit name, or None for any other name."""
    if _launchd():
        p = prefix() + "."
        if not name.startswith(p):
            return None
        rest = name[len(p):].removesuffix(".plist")
        if rest == "daemons-refresh":
            return ("refresh", None, None)
        parts = rest.split(".")
        if len(parts) != 2 or not AGENT_RE.fullmatch(parts[1]):
            return None
        if parts[0] == "session":
            return ("session", None, parts[1])
        if parts[0] == "stall-watchdog":
            return ("watchdog", None, parts[1])
        return ("job", parts[0], parts[1]) if JOB_RE.fullmatch(parts[0]) else None
    if name in ("agent-daemons-refresh.timer", "agent-daemons-refresh.service"):
        return ("refresh", None, None)
    m = re.fullmatch(rf"claude-agent-({AGENT_RE.pattern}?)(-stall-watchdog)?\.service", name)
    if m:
        return ("watchdog" if m.group(2) else "session", None, m.group(1))
    m = re.fullmatch(rf"agent-({JOB_RE.pattern})@({AGENT_RE.pattern})?\.service", name)
    return ("job", m.group(1), m.group(2)) if m else None


def unit_file(name):
    """The file a unit lives in, under unit_dir(): the unit name itself
    (systemd), `<label>.plist` (launchd)."""
    return f"{name}.plist" if _launchd() else name


def unit_dir(scope="user"):
    """Where the scope's unit files are."""
    _scope(scope)
    if _launchd():
        if scope == "user":
            return Path.home() / "Library" / "LaunchAgents"
        return Path(os.environ.get("FLEET_LAUNCHD_SYSTEM_DIR") or "/Library/LaunchDaemons")
    if scope == "system":
        return Path("/etc/systemd/system")
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "systemd" / "user"


def domain_exists(scope="user"):
    """Whether the scope's manager is there to talk to: launchd answers `print`
    for the domain (no `gui/<uid>` without a logged-in user: on a host, the
    automatic login). systemd: always True here; its user manager's reach is
    the caller's XDG_RUNTIME_DIR and lingering."""
    return not _launchd() or _launchctl("print", domain(scope)).returncode == 0


def domain(scope="user"):
    """The launchd domain target of a scope: `gui/<uid>` (or host.json's
    launchd_domain), or `system`."""
    return f"{paths.host_option('launchd_domain')}/{os.getuid()}" if _scope(scope) == "user" else "system"


# ------------------------------------------------------------------ programs

def _run(argv, what, check):
    try:
        p = subprocess.run([str(a) for a in argv], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=120,
                           env={**os.environ,
                                "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR")
                                or f"/run/user/{os.getuid()}"})
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EnvironmentFault(f"{what} could not run: {type(exc).__name__}: {exc}") from None
    if check and p.returncode:
        tail = (p.stderr.strip() or p.stdout.strip()).splitlines()[-3:]
        raise EnvironmentFault(f"{what} failed (exit {p.returncode}): " + " | ".join(tail))
    return p


def _systemctl(scope, *args, check=False):
    # `systemctl --user` finds the user's bus through XDG_RUNTIME_DIR, which a
    # shell without a login session (su, cron, ssh without PAM) lacks; _run
    # supplies the default when it is unset.
    exe = os.environ.get("FLEET_SYSTEMCTL") or os.environ.get("AGENT_DAEMONS_SYSTEMCTL") or "systemctl"
    flag = ["--user"] if _scope(scope) == "user" else []
    return _run([exe, *flag, *args], "systemctl " + " ".join([*flag, *args[:2]]), check)


def _launchctl(*args, check=False):
    exe = os.environ.get("FLEET_LAUNCHCTL") or "/bin/launchctl"
    return _run([exe, *args], "launchctl " + " ".join(args[:2]), check)


# ------------------------------------------------------------------ launchctl print

def parse_print(text):
    """`launchctl print <domain>/<label>` -> (scalars, blocks) of its TOP level:
    `key = value` lines one tab deep, and `key = {` blocks one tab deep as a list
    of their inner lines, stripped. Deeper lines are a nested block's own."""
    scalars, blocks, block = {}, {}, None
    for line in text.splitlines():
        if block is not None:
            if line == "\t}":
                block = None
            elif line.startswith("\t\t") and line.strip():
                blocks[block].append(line.strip())
            continue
        if not line.startswith("\t") or line.startswith("\t\t"):
            continue
        key, sep, value = line[1:].partition(" = ")
        if not sep:
            continue
        if value == "{":
            block = key
            blocks[key] = []
        else:
            scalars.setdefault(key, value)
    return scalars, blocks


def _print(name, scope):
    """(found, scalars, blocks, error) from launchctl print."""
    r = _launchctl("print", f"{domain(scope)}/{name}")
    text = r.stdout + r.stderr
    if NOT_FOUND in text:
        return False, {}, {}, ""
    if r.returncode or " = {" not in r.stdout:
        return None, {}, {}, (r.stderr or r.stdout).strip()[:200]
    s, b = parse_print(r.stdout)
    return True, s, b, ""


def disabled(scope="user"):
    """{label: True when disabled} from `launchctl print-disabled`; {} on systemd."""
    if not _launchd():
        return {}
    r = _launchctl("print-disabled", domain(scope), check=True)
    return {m.group(1): m.group(2) == "disabled"
            for m in re.finditer(r'^\s*"([^"]+)" => (enabled|disabled)\s*$', r.stdout, re.M)}


# ------------------------------------------------------------------ reading

def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def status(name, scope="user"):
    """{load, active, sub, result, restarts, pid, error}, systemd's words on both
    backends (see the module docstring)."""
    if not _launchd():
        r = _systemctl(scope, "show", name, "-p", "LoadState", "-p", "ActiveState", "-p", "SubState",
                       "-p", "Result", "-p", "NRestarts", "-p", "MainPID")
        props = dict(line.partition("=")[::2] for line in r.stdout.splitlines() if "=" in line)
        if r.returncode and not props:
            return {"load": "unknown", "active": "unknown", "sub": "", "result": "", "restarts": 0,
                    "pid": 0, "error": (r.stderr or "").strip()[:200]}
        return {"load": props.get("LoadState", ""), "active": props.get("ActiveState", ""),
                "sub": props.get("SubState", ""), "result": props.get("Result", ""),
                "restarts": _int(props.get("NRestarts")), "pid": _int(props.get("MainPID")), "error": ""}
    found, s, _, error = _print(name, scope)
    if found is None:
        return {"load": "unknown", "active": "unknown", "sub": "", "result": "", "restarts": 0,
                "pid": 0, "error": error}
    if not found:
        return {"load": "not-found", "active": "inactive", "sub": "dead", "result": "success",
                "restarts": 0, "pid": 0, "error": ""}
    result = _launchd_result(s)
    state = s.get("state", "")
    pid = _int(s.get("pid"))
    if state == "running" and pid <= 0:
        state = "spawn scheduled"     # no pid is no process: the throttle (module docstring)
    active, sub = {"running": ("active", "running"),
                   "spawn scheduled": ("activating", "auto-restart")}.get(
        state, ("failed", "failed") if state == "not running" and result != "success"
        else ("inactive", "dead") if state == "not running" else ("unknown", state))
    return {"load": "loaded", "active": active, "sub": sub, "result": result,
            "restarts": max(_int(s.get("runs")) - 1, 0), "pid": pid, "error": ""}


def _launchd_result(s):
    """status()'s result word from a job's top-level `launchctl print` scalars."""
    last = s.get("last exit code", "")
    return ("signal" if "last terminating signal" in s
            else "success" if last in ("", "0", "(never exited)") else "exit-code")


def last_exit(name, scope="user"):
    """How the unit's last run ended: {result, code}. `result` is status()'s
    word; `code` is what the manager reports with it, as text: the exit code,
    or for `signal` the signal (systemd: its number, ExecMainStatus; launchd: its
    `last terminating signal` text, `Killed: 9`), and "" where it reports none (a
    job that never exited, a unit it does not know)."""
    if not _launchd():
        r = _systemctl(scope, "show", name, "-p", "Result", "-p", "ExecMainStatus")
        props = dict(line.partition("=")[::2] for line in r.stdout.splitlines() if "=" in line)
        return {"result": props.get("Result", ""), "code": props.get("ExecMainStatus", "")}
    found, s, _, _ = _print(name, scope)
    if not found:
        return {"result": "success" if found is False else "", "code": ""}
    result = _launchd_result(s)
    code = s.get("last terminating signal", "") if result == "signal" else s.get("last exit code", "")
    return {"result": result, "code": "" if code == "(never exited)" else code}


def _exec_commands(show, key):
    """Every command of the Exec property `key` in `systemctl show` output, as
    text: one per `key=` line, each from `argv[]=` to its LAST ` ; ignore_errors=`
    (the module docstring)."""
    out = []
    for line in show.splitlines():
        k, sep, value = line.partition("=")
        if k != key or not sep:
            continue
        head, sep, _ = value.rpartition(" ; ignore_errors=")
        _, found, argv = (head if sep else value.rstrip().removesuffix("}")).partition("argv[]=")
        if found:
            out.append(argv.strip())
    return out


def definition(name, scope="user"):
    """What the manager starts the unit with: {argv, env, workdir, path, log,
    source, commands}, or None when it knows no such unit. `source` is "loaded"
    (what the manager holds now, which is what a running process was started
    with) or "file" (a launchd plist on disk that is not loaded). `log` is the
    launchd job's StandardErrorPath; None on systemd (its daemons name their log
    in the unit, and its own output goes to the journal). `commands` is every
    command line the unit runs, as text: systemd's ExecStartPre, ExecStart and
    ExecStartPost; launchd's ProgramArguments."""
    if not _launchd():
        r = _systemctl(scope, "show", name, "-p", "LoadState", "-p", "ExecStartPre", "-p", "ExecStart",
                       "-p", "ExecStartPost", "-p", "Environment", "-p", "WorkingDirectory",
                       "-p", "FragmentPath")
        props = dict(line.partition("=")[::2] for line in r.stdout.splitlines() if "=" in line)
        if props.get("LoadState") != "loaded":
            return None
        commands = [c for k in ("ExecStartPre", "ExecStart", "ExecStartPost") for c in _exec_commands(r.stdout, k)]
        argv = (_exec_commands(r.stdout, "ExecStart") or [""])[0].split()
        try:
            words = shlex.split(props.get("Environment", ""))
        except ValueError:
            words = props.get("Environment", "").split()
        env = dict(x.partition("=")[::2] for x in words)
        return {"argv": argv, "env": env, "workdir": props.get("WorkingDirectory") or None,
                "path": props.get("FragmentPath") or None, "log": None, "source": "loaded",
                "commands": commands}
    found, s, b, _ = _print(name, scope)
    if found:
        env = dict(line.split(" => ", 1) for line in b.get("environment", []) if " => " in line)
        argv = b.get("arguments", [])
        return {"argv": argv, "env": env, "workdir": s.get("working directory"), "path": s.get("path"),
                "log": s.get("stderr path"), "source": "loaded", "commands": [" ".join(argv)]}
    plist = unit_dir(scope) / unit_file(name)
    try:
        d = plistlib.loads(plist.read_bytes())
    except (OSError, plistlib.InvalidFileException, ValueError):
        return None
    argv = [str(a) for a in d.get("ProgramArguments", [])]
    return {"argv": argv, "env": dict(d.get("EnvironmentVariables", {})), "workdir": d.get("WorkingDirectory"),
            "path": str(plist), "log": d.get("StandardErrorPath"), "source": "file",
            "commands": [" ".join(argv)]}


def log_of(name, scope="user"):
    """The file a launchd job's output goes to; None on systemd (the journal)."""
    d = definition(name, scope) if _launchd() else None
    return d["log"] if d else None


def started_at(name, scope="user"):
    """When the unit's main process started (epoch seconds), or None."""
    pid = status(name, scope)["pid"]
    return proc_start(pid) if pid > 0 else None


def hint(verb, name, scope="user"):
    """The command a person runs to `verb` (start, restart, stop, status, log)
    the unit, as text for a message."""
    root = "sudo " if _scope(scope) == "system" else ""
    if not _launchd():
        if verb == "log":
            return f"journalctl {'--user ' if scope == 'user' else ''}-u {name} -n 30"
        return f"{root if verb != 'status' else ''}systemctl {'--user ' if scope == 'user' else ''}{verb} {name}"
    target = f"{domain(scope)}/{name}"
    if verb == "log":
        log = log_of(name, scope)
        return f"tail -n 30 {log}" if log else f"launchctl print {target}"
    if verb == "restart":
        # As restart() does it: `kickstart -k` restarts from the definition
        # launchd loaded, and a session supervisor may adopt the old session.
        return (f"{root}launchctl bootout {target} && "
                f"{root}launchctl bootstrap {domain(scope)} {unit_dir(scope) / unit_file(name)}")
    cmd = {"start": "kickstart", "stop": "kill TERM", "status": "print"}.get(verb)
    if cmd is None:
        raise Refused(f"no hint for {verb!r}")
    return f"{root if verb != 'status' else ''}launchctl {cmd} {target}"


def enabled(unit_name, scope="user"):
    """The names enabled for the unit file `unit_name`. systemd: the unit itself
    when a .wants/ or .requires/ link names it; for a template every instance
    so linked or linked into the unit directory. launchd: the label when its
    plist is in unit_dir() and launchd does not list it as disabled."""
    udir = unit_dir(scope)
    if _launchd():
        label = unit_name.removesuffix(".plist")
        on = (udir / unit_file(label)).is_file() and not disabled(scope).get(label, False)
        return {label} if on else set()
    if "@." in unit_name:
        head, tail = unit_name.split("@", 1)[0] + "@", "." + unit_name.rsplit(".", 1)[1]

        def match(n):
            return n.startswith(head) and n.endswith(tail) and len(n) > len(head) + len(tail)
    else:
        def match(n):
            return n == unit_name
    found = set()
    for d in [*udir.glob("*.wants"), *udir.glob("*.requires")]:
        found.update(e.name for e in d.iterdir() if match(e.name))
    if "@." in unit_name and udir.is_dir():
        found.update(e.name for e in udir.iterdir() if e.is_symlink() and match(e.name))
    return found


def instances(jobs, scope="user"):
    """[(job, agent, name)] of the job units of `jobs` the manager knows:
    systemd `list-units --all` of their instances; launchd the plists in
    unit_dir() carrying this host's prefix."""
    jobs = list(jobs)
    out = []
    if _launchd():
        udir = unit_dir(scope)
        for f in sorted(udir.glob(f"{prefix()}.*.plist")) if udir.is_dir() else []:
            p = parse(f.name)
            if p and p[0] == "job" and p[1] in jobs:
                out.append((p[1], p[2], f.name.removesuffix(".plist")))
        return out
    if not jobs:
        return out
    r = _systemctl(scope, "list-units", "--all", "--plain", "--no-legend",
                   *[f"agent-{j}@*.service" for j in jobs])
    for line in r.stdout.splitlines():
        name = line.split()[0] if line.split() else ""
        p = parse(name)
        if p and p[0] == "job" and p[1] in jobs and p[2]:
            out.append((p[1], p[2], name))
    return out


# ------------------------------------------------------------------ changing

def reload(scope="user"):
    """systemd daemon-reload; nothing on launchd, which reads a plist at bootstrap."""
    if not _launchd():
        _systemctl(scope, "daemon-reload", check=True)


def _plist(name, scope):
    path = unit_dir(scope) / unit_file(name)
    if not path.is_file():
        raise EnvironmentFault(f"{path} does not exist: render the unit first")
    return path


def _bootstrap(name, scope):
    _launchctl("bootstrap", domain(scope), _plist(name, scope), check=True)


def _bootout(name, scope):
    """bootout, then wait until launchd no longer holds the label."""
    r = _launchctl("bootout", f"{domain(scope)}/{name}")
    deadline = time.monotonic() + BOOTOUT_WAIT_SECS
    while status(name, scope)["load"] != "not-found":
        if time.monotonic() > deadline:
            raise EnvironmentFault(f"launchctl bootout {domain(scope)}/{name} did not unload it within "
                                   f"{BOOTOUT_WAIT_SECS:.0f} s (exit {r.returncode}: "
                                   f"{(r.stderr or r.stdout).strip()[:160]})")
        time.sleep(0.2)


def enable(*names, now=False, scope="user"):
    """systemd `enable [--now]`. launchd: `launchctl enable` for a label it lists
    as disabled (only then: it leaves a permanent override entry behind), and
    with `now` a bootstrap of the plist when it is not loaded (RunAtLoad starts
    it). A plist in unit_dir() is otherwise loaded at the next login anyway."""
    if not names:
        return
    if not _launchd():
        _systemctl(scope, "enable", *(["--now"] if now else []), *names, check=True)
        return
    off = disabled(scope)
    for name in names:
        _plist(name, scope)
        if off.get(name):
            _launchctl("enable", f"{domain(scope)}/{name}", check=True)
        if now and status(name, scope)["load"] != "loaded":
            _bootstrap(name, scope)


def disable(*names, now=False, scope="user"):
    """systemd `disable [--now]`. launchd: bootout (stop and unload) whatever
    `now` says, since launchd has no enabled-but-stopped state for a plist that
    stays; the plist is kept, and loads again at the next login unless the
    caller removes it."""
    if not names:
        return
    if not _launchd():
        _systemctl(scope, "disable", *(["--now"] if now else []), *names, check=True)
        return
    for name in names:
        if status(name, scope)["load"] != "not-found":
            _bootout(name, scope)


def restart(*names, scope="user"):
    """systemd `restart`. launchd: bootout, then bootstrap from the plist, so the
    process starts from the file as it is now (THE module docstring's first
    property)."""
    if not names:
        return
    if not _launchd():
        _systemctl(scope, "restart", *names, check=True)
        return
    for name in names:
        _plist(name, scope)
        if status(name, scope)["load"] != "not-found":
            _bootout(name, scope)
        _bootstrap(name, scope)


def start(*names, scope="user"):
    """systemd `start`; launchd `kickstart` of a loaded label."""
    if not names:
        return
    if not _launchd():
        _systemctl(scope, "start", *names, check=True)
        return
    for name in names:
        _launchctl("kickstart", f"{domain(scope)}/{name}", check=True)


# ------------------------------------------------------------------ rendering

def render(src, text, subs, tag):
    """A unit file rendered from the template `systemd/<src>` with `@KEY@` ->
    subs[KEY], headed by a rendered-by line naming the template and `tag`.

    A `.plist.in` template is XML: each value is XML-escaped, the header is an
    XML comment after the declaration, and the result must parse as a plist.
    Any other template gets the values as they are and a `#` header line.
    A placeholder left without a value is EnvironmentFault (exit 3)."""
    plist = src.endswith(".plist.in")
    for k, v in subs.items():
        text = text.replace(f"@{k}@", escape(v) if plist else v)
    left = sorted(set(PLACEHOLDER.findall(text)))
    if left:
        raise EnvironmentFault(f"systemd/{src}: no value for {', '.join(left)}")
    header = f"Rendered by fleet install from systemd/{src} at {tag}. Edit the template, not this file."
    if not plist:
        return f"# {header}\n{text}".encode()
    decl, _, rest = text.partition("\n")
    if not decl.startswith("<?xml"):
        raise EnvironmentFault(f"systemd/{src}: a plist template starts with its <?xml ...?> declaration")
    data = f"{decl}\n<!-- {header.replace('--', '- -')} -->\n{rest}".encode()
    try:
        plistlib.loads(data)
    except Exception as exc:  # plistlib raises ExpatError, InvalidFileException or ValueError
        raise EnvironmentFault(f"systemd/{src}: the rendered plist does not parse: {exc}") from None
    return data


# ------------------------------------------------------------------ processes

def _procfs():
    env = os.environ.get("FLEET_PROC") or os.environ.get("AGENT_DAEMONS_PROC")
    if env:
        return env
    return None if sys.platform == "darwin" else "/proc"


def _proc_strings(proc, pid, name):
    try:
        data = (Path(proc) / str(pid) / name).read_bytes()
    except OSError:
        return None
    return [x.decode("utf-8", "surrogateescape") for x in data.split(b"\0") if x]


@functools.cache
def _libc():
    import ctypes
    import ctypes.util
    return ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)


def _sysctl(mib, size=None):
    """The bytes a sysctl MIB answers, or None. Without `size` the length is
    asked for first."""
    import ctypes
    libc = _libc()
    arr = (ctypes.c_int * len(mib))(*mib)
    sz = ctypes.c_size_t(size or 0)
    if size is None and libc.sysctl(arr, len(mib), None, ctypes.byref(sz), None, 0) != 0:
        return None
    buf = ctypes.create_string_buffer(sz.value)
    if libc.sysctl(arr, len(mib), buf, ctypes.byref(sz), None, 0) != 0 or sz.value == 0:
        return None
    return buf.raw[:sz.value]


# macOS sysctl MIBs (sys/sysctl.h): CTL_KERN=1, KERN_PROC=14, KERN_PROC_PID=1,
# KERN_BOOTTIME=21, KERN_PROCARGS2=49. struct kinfo_proc is 648 bytes on arm64
# and x86_64, and starts with kp_proc.p_un.__p_starttime, a struct timeval:
# measured on macOS 27.0.1 to equal `ps -o lstart=` for pid 1 and a LaunchAgent.
KINFO_PROC_SIZE = 648


def parse_timeval(raw):
    """Epoch seconds from a buffer that starts with a struct timeval (a
    kinfo_proc's start time, KERN_BOOTTIME), or None."""
    if not raw or len(raw) < 12:
        return None
    sec, usec = struct.unpack_from("qi", raw, 0)
    return sec + usec / 1e6 if sec > 0 else None


def parse_procargs2(raw):
    """argv from a KERN_PROCARGS2 buffer: int argc, the executable path, NUL
    padding, then argc NUL-terminated strings (and, for some processes, the
    environment, which nothing here reads)."""
    if not raw or len(raw) < 4:
        return None
    argc = struct.unpack_from("i", raw, 0)[0]
    _, _, rest = raw[4:].partition(b"\0")
    parts = rest.lstrip(b"\0").split(b"\0")
    return [x.decode("utf-8", "surrogateescape") for x in parts[:argc]]


def proc_start(pid):
    """When process `pid` started (epoch seconds), or None."""
    proc = _procfs()
    if proc:
        try:
            fields = (Path(proc) / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()
            return boot_time() + int(fields[19]) / os.sysconf("SC_CLK_TCK")
        except (OSError, IndexError, ValueError, TypeError):
            return None
    if sys.platform == "darwin":
        return parse_timeval(_sysctl((1, 14, 1, int(pid)), KINFO_PROC_SIZE))
    return None


def proc_argv(pid):
    """Process `pid`'s argv, or None when it cannot be read (on macOS, another
    user's process)."""
    proc = _procfs()
    if proc:
        return _proc_strings(proc, pid, "cmdline")
    if sys.platform == "darwin":
        return parse_procargs2(_sysctl((1, 49, int(pid))))
    return None


def proc_cwd(pid):
    """Process `pid`'s working directory, or None (always None on macOS: use the
    definition's workdir)."""
    proc = _procfs()
    if not proc:
        return None
    try:
        return os.readlink(Path(proc) / str(pid) / "cwd")
    except OSError:
        return None


def proc_env(pid):
    """Process `pid`'s environment as a dict, or None when it cannot be read:
    always None on macOS (the module docstring's second property)."""
    proc = _procfs()
    if not proc:
        return None
    items = _proc_strings(proc, pid, "environ")
    return None if items is None else dict(x.partition("=")[::2] for x in items)


def boot_time():
    """When this host booted (epoch seconds), or None."""
    proc = _procfs()
    if proc:
        try:
            with open(Path(proc) / "stat") as f:
                return next(float(line.split()[1]) for line in f if line.startswith("btime "))
        except (OSError, StopIteration, IndexError, ValueError):
            return None
    if sys.platform == "darwin":
        return parse_timeval(_sysctl((1, 21), 16))
    return None
