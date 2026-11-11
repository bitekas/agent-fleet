#!/usr/bin/env python3
"""verify-privileges.py - can the agents user escape its supervision? Read only.

Usage, run AS the agents user on the target (install-agent-fleet step 8 and
adding-an-agent section 5 step 10 run it over SSH as that user):

    python3 verify-privileges.py [--no-admin] [--agent <agent-name>]... [--identities <file>]

The fleet's privilege split: a dedicated agents user WITHOUT sudo runs the
agents, and an administrator installs, as system units the agents user cannot
stop, disable or edit, each agent's session (claude-agent-<agent>.service,
User=<agents user>) and its stall watchdog
(claude-agent-<agent>-stall-watchdog.service). The agents run Claude Code with
every permission prompt off, so whatever this user may do, an agent may do.

One line per fact, then a verdict line. Facts, never a secret: no file is read,
only its owner and access. Checks:

  host   `sudo -n true` succeeds                          FAIL
         `sudo -n -l` lists a command it may run          FAIL
         the user is in group sudo, admin or wheel        FAIL
         polkit authorizes managing system units (the
         actions manage-units and manage-unit-files) with
         no password, or with the user's own              FAIL
         the user can change ANY file or directory of the
         fleet checkout (host.json's fleet_checkout), or
         a directory above it                             FAIL
         the user can change the identities the checkout
         owner's `fleet upgrade` trusts (--identities,
         else <owner's home>/.config/agent-fleet/
         identities.json)                                 FAIL
  agent  the session unit is not a system unit            FAIL
         either unit runs as someone other than the user  FAIL
         the user can change a unit file or a drop-in     FAIL
         the user can change the watchdog's config        FAIL
         the user can change the program the watchdog
         runs, or the interpreter that runs it            FAIL
         the user can change the tmux the watchdog runs,
         or a directory searched before it on the
         watchdog's PATH                                  FAIL

UNDER LAUNCHD (macOS; fleetlib.services' backend) the same split holds with
launchd's words: each agent's session (<prefix>.session.<agent>) and watchdog
(<prefix>.stall-watchdog.<agent>) are LaunchDaemons in the system domain with
UserName the agents user, their plists in /Library/LaunchDaemons
($FLEET_LAUNCHD_SYSTEM_DIR), root's. The agent checks there:

  agent  the session is not loaded in the system domain  FAIL
         (a LaunchAgent in the user's own gui domain, or
         no job at all: the user controls it)
         either job runs as someone other than the user  FAIL
         (its plist's UserName; none is root)
         the user can change the job's plist             FAIL
         the user can change the watchdog's config        FAIL
         the user can change the program the watchdog
         runs, or the interpreter that runs it            FAIL
         the user can change the tmux the watchdog runs,
         or a directory searched before it on the
         watchdog's PATH                                  FAIL

and the polkit check has no counterpart: launchd lets only root bootstrap, boot
out, disable or edit a job of the system domain. The plist is read, never
written: it is mode 644, and holds no secret (the credential stays in the
file its session supervisor sources).

--no-admin is the form with no separate administrator: the login user has no
sudo at all, the agents run as that user and their units are user units. There
every finding but the sudo ones prints UNPROTECTED instead of FAIL, because
nothing on the machine can protect the units from their own user; a sudo
finding still FAILs, since that form is only for a user with none.

Exit codes: 0 PROTECTED; 1 a FAIL
line; 2 usage, or run as root; 3 NO VERDICT, nothing failed but a fact could not
be measured (the line names it); 4 UNPROTECTED (--no-admin).

LOAD-BEARING PROPERTIES - each one is here because removing it opens a hole:

  * "CAN CHANGE" IS OWNERSHIP AND THE DIRECTORY CHAIN, NOT `test -w`. An owner
    may chmod its own read-only file and then write it, and a user who may write
    or owns any directory above a path may rename the entry away and put another
    in its place. A check by access(2) on the file alone passes a config that is
    mode 444 in the user's own directory, which is exactly how the fleet's
    read-only checkout looks. So a path is changeable when the user owns it or
    any directory above it, may write it, or may write a directory above it -
    except in a sticky directory, where only an entry's owner may rename it.
    Both the path as written and its realpath are walked. Write access is
    the user's own, its groups included: the administrator reads the agents
    root as a member of the agents user's group, and a file of the
    administrator's that group may write is a FAIL like any other. The rule is
    fleetlib.paths.changeable, the one `fleet install --part agents` refuses
    by. The test's owned, read-only fixture is the control: it must FAIL naming
    ownership.

  * THE CHECKOUT IS THE AGENTS' CODE, SO ALL OF IT IS CHECKED. Every session,
    daemon and watchdog runs a program from the fleet checkout, and the
    agents user's own sessions load its skills. A user that could change one
    file in it - or rename the checkout away from a directory above it - could
    run its own code inside the supervision meant to contain it. So the whole
    tree is walked (fleetlib.paths.tree_changeable), .git and node_modules
    included, and the watchdog's program is a FAIL like its unit.

  * THE WATCHDOG'S INTERPRETER IS CHECKED WITH ITS PROGRAM. The watchdog runs
    as `<interpreter> watchdog.py`; an agents user that can change the
    interpreter runs its own code as the watchdog as surely as one that can
    change the script. On macOS the interpreter is Homebrew's python3, and
    Homebrew's files belong to whoever installed it: an install that made the
    agents user its owner hands that user the interpreter, which is why
    bootstrap-target.sh installs Homebrew as the administrator. So the
    executable the job starts - systemd's
    ExecStart path=, launchd's ProgramArguments[0] - is checked by the same
    rule as the script, its symlinks followed and every directory above it;
    one ok line covers the pair, and a finding names which of the two it is.
    An interpreter named by a relative path cannot be checked: NO VERDICT.

  * THE WATCHDOG'S TMUX AND ITS PATH ARE CHECKED TOO. watchdog.py starts one
    program by a bare name, `tmux` (WATCHDOG_COMMANDS; its re-exec runs
    sys.executable, an absolute path), so the tmux it runs is the first
    `<entry>/tmux` on the job's PATH that is an executable file - the lookup
    Python's subprocess makes, where a missing file, a directory or a file
    without execute permission is passed over. An agents user that can change
    that tmux, or create a `tmux` in a directory searched before it, runs its
    own program wherever the watchdog runs tmux: one that answers every capture
    with an idle pane switches the watchdog off. So the resolved tmux is checked
    by the rule above (path and realpath), and every earlier entry by the same
    rule applied to `<entry>/tmux`, which catches a directory the user may
    write, one it owns or can rename away, and a non-executable `tmux` it owns
    and may chmod. The job's PATH is the one it runs with: under systemd the
    unit's Environment=PATH, else the system manager's environment block
    (`systemctl show-environment`, which systemd.exec(5) says every unit's
    environment starts from), else systemd's fixed default
    /usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin (systemd.exec(5), $PATH);
    a unit with an EnvironmentFile= is NO VERDICT, because a PATH there wins
    and no file is read. Under launchd the plist's EnvironmentVariables PATH,
    else launchd's default /usr/bin:/bin:/usr/sbin:/sbin (_PATH_STDPATH in
    macOS's <paths.h>; render-plist.py writes the same four after the tmux's
    and the interpreter's). A relative or empty entry reached before a tmux is
    the working directory's: NO VERDICT, as is a PATH that reaches no tmux.
    A layout passes when tmux sits in a directory the administrator owns
    (Homebrew's /opt/homebrew/bin installed as the administrator, the system's
    /usr/bin) and every entry before it is out of the user's reach. A tmux in
    the agents user's own ~/.local/bin - the layout of a Mac whose agents user
    installed tmux and Python itself, as on the fleet's own macOS CI runner
    (CONTRIBUTING.md section 9) - FAILs, and so does its interpreter there.

  * THE POLKIT QUESTION CARRIES NO UNIT. systemd authorizes a non-root
    `systemctl stop` through polkit's org.freedesktop.systemd1.manage-units, and
    an unprivileged caller may not pass --detail to pkcheck (polkit answers
    "Only trusted callers ... can pass details", exit 127 - measured 2026-11-06,
    polkit on Ubuntu 26.04). So the answer is for unit management in general;
    a polkit rule that grants one unit by name is NOT seen here. `systemctl show
    -p CanStop` is no substitute: it is the unit's RefuseManualStop= for every
    caller, root included, not this user's permission. Without polkit at all,
    systemd refuses unit management to every caller but root (its
    bus-polkit.c), which is why pkcheck absent AND polkit.service not-found is
    ok, and pkcheck absent with polkit present is NO VERDICT.

  * NOTHING UNMEASURED IS GREEN. A systemctl that does not answer, a pkcheck
    error, a watchdog unit naming no STALL_WATCHDOG_CONFIG: each is a NO
    VERDICT line, and the run exits 3 unless a FAIL outranks it. A protected
    verdict needs positive evidence that every subject was reached.

  * A ROOT RUN IS REFUSED. Root may write every path and run sudo, so its
    findings say nothing about the agents user.

What this does not claim: the watchdog runs AS the agents user, so that user
can still signal its process (Restart=always, launchd's KeepAlive, brings it
back) or hold its lock file; the split protects the units' definitions, not the
running process. Under launchd the refusal of an unprivileged bootout is
launchd's own rule for the system domain, not tried here (a run that tried it
and succeeded would stop the agent): what is checked is that each job IS a
system-domain job whose definition the user cannot change.

It imports fleetlib from the checkout it sits in, like every fleet script: the
checkout check is about that same tree, so a user able to change one could
change the other, and that is the finding it reports.
"""
import argparse
import json
import os
import plistlib
import pwd
import re
import shlex
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(os.path.realpath(__file__)).parents[3] / "lib"))
from fleetlib import services  # noqa: E402
from fleetlib.paths import changeable, host_config_path, tree_changeable  # noqa: E402

SUDO_GROUPS = ("sudo", "admin", "wheel")
POLKIT_ACTIONS = ("org.freedesktop.systemd1.manage-units", "org.freedesktop.systemd1.manage-unit-files")
NAME = re.compile(r"[a-z][a-z0-9-]{1,30}")
# Every program watchdog.py starts by a bare name, looked up on its PATH (the module
# docstring, THE WATCHDOG'S TMUX AND ITS PATH). verify-privileges-path.test.py derives
# this set from watchdog.py's source and fails when the two differ.
WATCHDOG_COMMANDS = ("tmux",)
# The PATH a job runs with when it names none. Vendor facts, each with its source:
SYSTEMD_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"  # systemd.exec(5), $PATH, system manager
LAUNCHD_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"                      # _PATH_STDPATH, macOS <paths.h>

lines = []  # (status, text)


def say(status, text):
    lines.append((status, text))
    print(f"{status:<12}{text}")


def run(*argv):
    """(exit, stdout, stderr), or None when the program is not installed."""
    try:
        p = subprocess.run(argv, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60,
                           env=dict(os.environ, LC_ALL="C"))
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired:
        return (124, "", f"{argv[0]} did not answer in 60 s")
    return p.returncode, p.stdout, p.stderr


def show(unit, *props):
    """The unit's properties from the SYSTEM manager, or a reason it gave none."""
    argv = ["systemctl", "show"]
    for p in props:
        argv += ["-p", p]
    r = run(*argv, unit)
    if r is None:
        return None, "systemctl is not installed"
    code, out, err = r
    got = dict(l.split("=", 1) for l in out.splitlines() if "=" in l)
    if code != 0 or "LoadState" not in got:
        return None, f"systemctl show {unit} gave no answer (exit {code}: {(err or out).strip()[:120]})"
    return got, None


def program(execstart):
    """(the script the unit's interpreter runs, else the program itself; the
    executable systemd starts, its path= else argv[0]) of the first command."""
    for argv in re.findall(r"argv\[\]=([^;]*)", execstart):
        words = argv.split()
        rest = [w for w in words[1:] if not w.startswith("-")]
        path = re.search(r"path=([^ ;]+)", execstart)
        return (rest[0] if rest else (words[0] if words else None)), (path.group(1) if path else
                                                                     (words[0] if words else None))
    return None, None


def exec_checks(agent, user, guard, job, prog, interp):
    """The program the watchdog runs and the interpreter that runs it (the
    module docstring, THE WATCHDOG'S INTERPRETER): one ok line for the pair, a
    finding per path the user can change, NO VERDICT for what cannot be read."""
    if not prog:
        say("NO VERDICT", f"{agent}: {job} names no program")
        return
    subjects = [(prog, "the program the watchdog runs")]
    if interp and interp != prog:
        if os.path.isabs(interp):
            subjects.append((interp, "the interpreter the watchdog runs"))
        else:
            say("NO VERDICT", f"{agent}: {job} names its interpreter {interp!r} by a relative path, "
                              "so it cannot be checked")
            interp = None
    found = [(why, what) for why, what in ((changeable(q), what) for q, what in subjects) if why]
    for why, what in found:
        say(guard, f"{agent}: {user} {why}: {what}")
    if not found:
        also = f" or its interpreter {interp}" if interp and interp != prog else ""
        say("ok", f"{agent}: {user} cannot change the watchdog's program {prog}{also}")


def lookup(cmd, path):
    """(the file a bare `cmd` runs on `path`, the entries searched before it, the
    relative entry reached before any `cmd` or None) - Python's subprocess lookup:
    the entries in order, the first `<entry>/<cmd>` that is a file this user may
    execute. An empty entry is the working directory, so it is relative too."""
    before = []
    for entry in path.split(":"):
        if not os.path.isabs(entry):
            return None, before, entry
        cand = os.path.join(entry, cmd)
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand, before, None
        before.append(entry)
    return None, before, None


def path_checks(agent, user, guard, job, path, source):
    """Each bare command the watchdog runs, as the job's PATH resolves it, and every
    entry searched before it (the module docstring, THE WATCHDOG'S TMUX AND ITS PATH):
    one ok line per command, a finding per path the user can change."""
    for cmd in WATCHDOG_COMMANDS:
        found, before, rel = lookup(cmd, path)
        if rel is not None:
            say("NO VERDICT", f"{agent}: {job} runs a bare {cmd} on PATH={path} ({source}), and its entry "
                              f"{rel!r}, reached before any {cmd}, is relative: what it runs depends on the "
                              "working directory")
            continue
        if not found:
            say("NO VERDICT", f"{agent}: no {cmd} on {job}'s PATH={path} ({source}), so the {cmd} it runs "
                              "cannot be checked")
            continue
        subjects = [(found, f"the {cmd} the watchdog runs, {found}")]
        subjects += [(os.path.join(d, cmd), f"{d} is searched before {found} on the watchdog's PATH, "
                                            f"so a {cmd} put there runs instead") for d in dict.fromkeys(before)]
        hits = [(why, what) for why, what in ((changeable(q), what) for q, what in subjects) if why]
        for why, what in hits:
            say(guard, f"{agent}: {user} {why}: {what}")
        if not hits:
            say("ok", f"{agent}: {user} cannot change the watchdog's {cmd} {found} or a directory searched "
                      f"before it (PATH={path}, {source})")


def manager_path():
    """(PATH, its source) for a system unit that sets none, or (None, why not)."""
    r = run("systemctl", "show-environment")
    if r is None:
        return None, "systemctl is not installed"
    code, out, err = r
    if code != 0:
        return None, f"systemctl show-environment gave no answer (exit {code}: {(err or out).strip()[:120]})"
    env = dict(l.split("=", 1) for l in out.splitlines() if "=" in l)
    if "PATH" in env:
        return env["PATH"], "the system manager's environment block, systemctl show-environment"
    return SYSTEMD_PATH, "systemd's fixed default, the manager's environment block naming none"


def host_checks(user, guard, identities=None, launchd=False):
    r = run("sudo", "-n", "true")
    if r is None:
        say("ok", "sudo is not installed")
    else:
        if r[0] == 0:
            say("FAIL", f"sudo -n true succeeds for {user}: it runs anything as root with no password")
        else:
            say("ok", f"sudo -n true is refused for {user} (exit {r[0]})")
        r = run("sudo", "-n", "-l")
        if r[0] == 0 and "may run the following commands" in r[1]:
            say("FAIL", f"sudo -n -l lists commands {user} may run as another user with no password")
        else:
            say("ok", f"sudo -n -l lists no command {user} may run with no password")
    r = run("id", "-nG")
    groups = r[1].split() if r and r[0] == 0 else None
    if groups is None:
        say("NO VERDICT", f"id -nG did not name {user}'s groups")
    elif set(groups) & set(SUDO_GROUPS):
        bad = " ".join(g for g in groups if g in SUDO_GROUPS)
        say("FAIL", f"{user} is in group {bad}, which the distribution's sudoers lets run anything as root")
    else:
        say("ok", f"{user} is in none of the groups {', '.join(SUDO_GROUPS)}")
    if launchd:
        say("ok", "launchd: only root bootstraps, boots out, disables or edits a job of the system domain")
    for action in () if launchd else POLKIT_ACTIONS:
        r = run("pkcheck", "--action-id", action, "--process", str(os.getpid()))
        if r is None:
            got, why = show("polkit.service", "LoadState")
            if got and got.get("LoadState") == "not-found":
                say("ok", f"{action}: no polkit, so systemd lets only root manage system units")
            else:
                say("NO VERDICT", f"{action}: pkcheck is not installed and polkit.service is "
                                  f"{got.get('LoadState') if got else why}")
            continue
        code, out = r[0], r[1]
        result = (re.findall(r"result=(\w+)", out) or [""])[0]
        if code == 0:
            say(guard, f"polkit authorizes {user} for {action} with no password")
        elif code == 2 and result.startswith("auth_self"):
            say(guard, f"polkit authorizes {user} for {action} with its own password ({result})")
        elif code == 1 or (code == 2 and result.startswith("auth_admin")):
            say("ok", f"polkit: {action} needs an administrator's password for {user} "
                      f"({result or 'not authorized'})")
        else:
            say("NO VERDICT", f"pkcheck {action} exit {code}: {(r[2] or out).strip()[:120]}")
    checkout_check(user, guard, identities)


def checkout_check(user, guard, identities=None):
    """The fleet checkout the host settings name: nothing in it, and no directory
    above it, may be the agents user's to change."""
    path = host_config_path()
    try:
        checkout = json.loads(path.read_text(encoding="utf-8"))["fleet_checkout"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        say("NO VERDICT", f"the host settings {path} name no fleet_checkout ({type(e).__name__}), "
                          "so the checkout cannot be checked")
        return
    checkout = os.path.expanduser(checkout)
    if not os.path.isdir(checkout):
        say("NO VERDICT", f"the fleet checkout {checkout} the host settings name is not a directory")
        return
    why = tree_changeable(checkout)
    say(guard, f"{user} {why}: the fleet checkout's code runs every agent") if why else \
        say("ok", f"{user} can change nothing in the fleet checkout {checkout} or above it")
    if identities is None:
        try:
            home = pwd.getpwuid(os.stat(checkout).st_uid).pw_dir
        except KeyError:
            say("NO VERDICT", f"the fleet checkout's owner (uid {os.stat(checkout).st_uid}) has no passwd entry, "
                              "so its identities file cannot be found")
            return
        identities = os.path.join(home, ".config", "agent-fleet", "identities.json")
    why = changeable(identities)
    say(guard, f"{user} {why}: the identities fleet upgrade trusts for outside work") if why else \
        say("ok", f"{user} cannot change {identities}, the identities fleet upgrade trusts")


def agent_checks(agent, user, guard):
    session, watchdog = f"claude-agent-{agent}.service", f"claude-agent-{agent}-stall-watchdog.service"
    for unit in (session, watchdog):
        got, why = show(unit, "LoadState", "FragmentPath", "DropInPaths", "User", "Environment",
                        "EnvironmentFiles", "ExecStart")
        if got is None:
            say("NO VERDICT", f"{agent}: {why}")
            continue
        if got["LoadState"] != "loaded":
            if unit == session:
                say(guard, f"{agent}: {unit} is not a system unit (LoadState={got['LoadState']}), "
                           f"so {user} controls it")
            else:
                say("n/a", f"{agent}: no {unit} (LoadState={got['LoadState']}): declined, or not installed yet")
            continue
        runs_as = got.get("User", "")
        if runs_as != user:
            say("FAIL", f"{agent}: {unit} runs as {runs_as or 'root'}, not as {user}")
        paths = [p for p in [got.get("FragmentPath", "")] + got.get("DropInPaths", "").split() if p]
        if not paths:
            say("NO VERDICT", f"{agent}: {unit} names no unit file")
        for p in paths:
            why = changeable(p)
            say(guard, f"{agent}: {user} {why} ({unit})") if why else \
                say("ok", f"{agent}: {user} cannot change {p} ({unit})")
        if unit != watchdog:
            continue
        env = dict(w.split("=", 1) for w in shlex.split(got.get("Environment", "")) if "=" in w)
        cfg = env.get("STALL_WATCHDOG_CONFIG")
        if not cfg:
            say("NO VERDICT", f"{agent}: {unit} names no STALL_WATCHDOG_CONFIG, so there is no config to check")
        else:
            why = changeable(cfg)
            say(guard, f"{agent}: {user} {why}: the watchdog's config") if why else \
                say("ok", f"{agent}: {user} cannot change the watchdog's config {cfg}")
        prog, interp = program(got.get("ExecStart", ""))
        exec_checks(agent, user, guard, f"{unit}'s ExecStart", prog, interp)
        if got.get("EnvironmentFiles", "").strip():
            say("NO VERDICT", f"{agent}: {unit} names an EnvironmentFile ({got['EnvironmentFiles'].strip()}), "
                              "whose PATH would win and is not read, so the tmux it runs cannot be checked")
            continue
        path, source = (env["PATH"], "the unit's Environment=") if "PATH" in env else manager_path()
        if path is None:
            say("NO VERDICT", f"{agent}: {unit} sets no PATH and {source}, so the tmux it runs cannot be checked")
        else:
            path_checks(agent, user, guard, unit, path, source)


def launchd_agent_checks(agent, user, guard):
    """The agent's session and watchdog as launchd jobs (the module docstring)."""
    for kind in ("session", "watchdog"):
        label = services.unit(kind, agent)
        st = services.status(label, "system")
        if st["load"] == "unknown":
            say("NO VERDICT", f"{agent}: launchctl could not report system/{label} ({st['error']})")
            continue
        if st["load"] != "loaded":
            if services.status(label, "user")["load"] == "loaded":
                say(guard, f"{agent}: {label} is a LaunchAgent in {user}'s own domain "
                           f"({services.domain('user')}), so {user} can boot it out, disable or delete it")
            elif kind == "session":
                say(guard, f"{agent}: {label} is not loaded in launchd's system domain, so {user} "
                           f"controls the session, or nothing supervises it")
            else:
                say("n/a", f"{agent}: no {label} in the system domain: declined, or not installed yet")
            continue
        path = (services.definition(label, "system") or {}).get("path") or \
            str(services.unit_dir("system") / services.unit_file(label))
        try:
            with open(path, "rb") as f:
                job = plistlib.load(f)
        except (OSError, plistlib.InvalidFileException, ValueError) as e:
            say("NO VERDICT", f"{agent}: the plist of system/{label}, {path}, cannot be read ({type(e).__name__})")
            continue
        runs_as = job.get("UserName") or ""
        if runs_as != user:
            say("FAIL", f"{agent}: {label} runs as {runs_as or 'root'}, not as {user}")
        why = changeable(path)
        say(guard, f"{agent}: {user} {why} ({label})") if why else \
            say("ok", f"{agent}: {user} cannot change {path} ({label})")
        if kind != "watchdog":
            continue
        cfg = (job.get("EnvironmentVariables") or {}).get("STALL_WATCHDOG_CONFIG")
        if not cfg:
            say("NO VERDICT", f"{agent}: {label} names no STALL_WATCHDOG_CONFIG, so there is no config to check")
        else:
            why = changeable(cfg)
            say(guard, f"{agent}: {user} {why}: the watchdog's config") if why else \
                say("ok", f"{agent}: {user} cannot change the watchdog's config {cfg}")
        args = [str(x) for x in job.get("ProgramArguments") or []]
        prog = next((x for x in args[1:] if not x.startswith("-")), args[0] if args else None)
        exec_checks(agent, user, guard, f"{label}'s ProgramArguments", prog,
                    str(job.get("Program") or (args[0] if args else "")) or None)
        path = (job.get("EnvironmentVariables") or {}).get("PATH")
        path_checks(agent, user, guard, label, str(path) if path is not None else LAUNCHD_PATH,
                    "the plist's EnvironmentVariables" if path is not None else
                    "launchd's default PATH, the plist naming none")


def main():
    ap = argparse.ArgumentParser(description="Can the agents user escape its supervision? Read only.")
    ap.add_argument("--no-admin", action="store_true", help="no separate administrator: user units, UNPROTECTED")
    ap.add_argument("--agent", action="append", default=[], help="an agent whose units to check (repeatable)")
    ap.add_argument("--identities", help="the identities file the checkout owner's fleet upgrade trusts "
                                         "(default: <owner's home>/.config/agent-fleet/identities.json)")
    a = ap.parse_args()
    for agent in a.agent:
        if not NAME.fullmatch(agent):
            ap.error(f"--agent {agent!r}: not an agent name")
    if os.geteuid() == 0:
        print("REFUSED: run as root, which may write every path; run it as the agents user")
        return 2
    r = run("id", "-un")
    user = r[1].strip() if r and r[0] == 0 else str(os.geteuid())
    form = "no separate administrator (--no-admin)" if a.no_admin else "an administrator installs the system units"
    print(f"== verify-privileges: agents user {user}, {form}")
    guard = "UNPROTECTED" if a.no_admin else "FAIL"
    launchd = services.backend() == "launchd"
    host_checks(user, guard, a.identities, launchd)
    for agent in a.agent:
        (launchd_agent_checks if launchd else agent_checks)(agent, user, guard)
    count = {s: sum(1 for st, _ in lines if st == s) for s in ("ok", "FAIL", "NO VERDICT", "UNPROTECTED")}
    tally = ", ".join(f"{n} {s.lower()}" for s, n in count.items() if n)
    if count["FAIL"]:
        verdict, code = "FAIL", 1
    elif count["NO VERDICT"]:
        verdict, code = "NO VERDICT", 3
    elif count["UNPROTECTED"]:
        verdict, code = "UNPROTECTED", 4
    else:
        verdict, code = "PROTECTED", 0
    print(f"== {verdict}: {tally}")
    return code


if __name__ == "__main__":
    sys.exit(main())
