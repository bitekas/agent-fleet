#!/usr/bin/env python3
"""Offline test for agent-daemons.py.

Run:  python3 systemd/agent-daemons.test.py

Nothing here reaches a real unit, log, cursor, process or host setting:
  - systemctl is a FAKE written into a temp directory (AGENT_DAEMONS_SYSTEMCTL)
    that answers from a JSON file and records every call; no unit is rendered
    into the real user unit directory, linked, enabled or started;
  - the agents root is a temp tree, named by a temp host settings file
    (FLEET_HOST_CONFIG), and HOME is a temp directory;
  - /proc is a fake tree (AGENT_DAEMONS_PROC) holding the processes `refresh`
    inspects;
  - the transport registry is the fixture descriptors in
    tests/fixtures/systemd/transports/ (FLEET_TRANSPORTS_DIR): a working Slack
    descriptor with the contract's values and a placeholder Discord one;
  - launchctl, in section LD, is tests/fixtures/launchd/fake-launchctl
    (FLEET_LAUNCHCTL), pinned to a capture of the real one's output.
The one exception is section LIVE, which runs in a macOS CI job only
(sys.platform darwin and GITHUB_ACTIONS=true), on the repository owner's own
runner: it bootstraps one temporary LaunchAgent, labelled
com.agent-fleet-test.smoke<pid>.sched.smoke, in the runner user's gui domain
(its user domain when there is none), from a plist under a temp directory, kills
it, and boots it out; anywhere else it prints NOT RUN. A run killed before its finally (a cancelled or timed-out job)
leaves that job loaded, and its finally is the only one that names its pid, so
LIVE first boots out every com.agent-fleet-test.smoke* label the domain holds
(stale_smoke_labels, checked offline). On that runner it never reports a pass it did not reach: a
bootstrap that fails is a failed check, not a skip.

Exit 0 every check passed; 1 a check failed (a failure is a finding whatever
the controls say); 3 NO VERDICT: no check failed, but a negative control did not
fail either, so at least one green is unproven and no pass is claimed.

NEGATIVE CONTROLS. Each check that pins a property this file exists for is run
a second time against a MUTANT of agent-daemons.py (or of a template) that
breaks exactly that property, and it must FAIL there:

  K  the follower saves the cursor before printing         kill-mid-delivery
  J  a transport's config file named <name>-watch, not      jobs derived from
     after its watch.job                                    the descriptors
  Q  jobs --json reports a log path the units do not       the job table fleet
     write                                                  reads
  P  the line prefix escaped together with its ' DM '      the priority regex
  F  the descriptor's follow_include not applied            follow's default filter
  X  refresh reads the job's own script path instead of     refresh reads the
     the process's cmdline                                  RUNNING script
  D  --dry-run ignored                                      dry run restarts nothing
  L  the unit file written through the existing path        render replaces a link
  T  RestartPreventExitStatus=0 deleted from the watch      rendered unit equals
     template                                               today's unit
  I  the scheduler template names the agents root as        ...and writes the literal
     %h/agents on one line                                  agents root where the host
                                                            unit has %h/agents
  O  the fixture's %h/agents de-identified to /srv/agents   ...and that %h-to-literal
     again (a mutant of the FIXTURE, not the subject)       change stays named, never
                                                            hidden by the reference
  A  the fleet tree found with abspath, not realpath        run through a link
  G  the systemd interpreter default changed                Linux units are v1.0.3's,
                                                            byte for byte
  E  `exec` imports fleetlib                                the shim runs with no lib/
  V  the unreadable macOS environment read as empty         refresh reads the launchd
                                                            job's definition
  B  PYTHONDONTWRITEBYTECODE deleted from the watch         no unit or plist writes
     template                                               bytecode into the checkout
  C  FLEET_HOST_CONFIG deleted from the refresh service     every systemd unit names
     template                                               the render's host settings
  R  a rise in launchd's `runs` after a check that saw the  the kickstart a GUARD alert
     unit stopped counted as a restart of its own           names reads as recovery
  S  that stopped mark dropped on every arm                 ...also across a re-arm
  W  every rise after a not-active check excused            a crash in launchd's
                                                            throttle is still alerted
  H  the refresh plist names no FLEET_HOST_CONFIG           the refresh job finds the
                                                            install under launchd's HOME
  N  refresh does not read the host settings first          no host.json is exit 3 and
                                                            one line, not a silent 0
  Y  render-units ignores --host-config                     every unit and plist names
                                                            the file install WRITES,
                                                            not the candidate it read
  Z  refresh does not ask whether the process writes to     refresh restarts a daemon
     the log (log_drift dropped)                            whose log was replaced
  U  the reader's inode comparison dropped                  ...and keeps one whose log
                                                            is appended to normally
  M  status does not count a DEAF job in its exit code      status names a daemon
                                                            writing to a replaced log
  SV the salvaged lines counted in the note but never       refresh appends what the
     written into the log                                   daemon wrote to the replaced
                                                            log, and the follower
                                                            delivers it once
  SA the boundary ignored, the whole replaced file          ...only what nobody has:
     salvaged                                               never a duplicate
  SC the follower keeps no record of the file it left      ...an empty new file falls
     at a replacement                                       back to the follower's place
  SH rewritten() without its unchanged-start-and-end rule   ...a rewrite that changes a
                                                            line's word count is still
                                                            recognised as one
  SW rewritten() without its word rule                      ...and so is one that edits
                                                            both ends of a line
  SD refresh's own lines kept in the comparison             ...a repeated salvage adds
                                                            only what is new since
  SI the reader's inode check dropped                       a name that now holds another
                                                            file is never read as the
                                                            daemon's
  SR1 the boundary's rule 1 (the new file's last line)      ...with the follower behind,
      dropped                                               the FILES give the boundary:
  SR2 rule 2 (a rewritten prefix) giving 0                  each rule measured, never
                                                            hidden by the follower's place
  SN the block appended with no newline before it           the block starts a line of
                                                            its own after a copy that
                                                            lost its last newline
  S1 <log>.1 the follower still names salvaged as if gone   a live rotation is drained by
                                                            the follower alone: no double
  SL refresh without its lock                               two refresh runs never salvage
                                                            the same lines twice
  SY the dry run takes the lock too                         ...a dry run takes none: it
                                                            writes nothing, and runs
                                                            while another refresh does
  SU a lock refresh cannot make stops the run               ...and a lock it cannot make
                                                            never leaves a deaf daemon deaf
  SX the word rule counting words, not the characters       rewritten() refuses a line
     they hold                                              that shares one short word
  SG the follower's record trusted whatever file its        an old record never meets a
     cursor names                                           reused inode number

Section 11b is the one that runs a REAL process: a child writing to its log,
which the test then replaces the way `sed -i` does (a new file renamed over the
path). Only a real descriptor shows a deleted inode; a fake /proc of symlinks
follows the path to the new file and cannot. On Linux the child's fds are read
through the fake /proc (its `fd` entry links to the real /proc/<pid>/fd), so
the subject runs exactly as `refresh` does; macOS has no /proc, so there the
platform's own reader (lsof) is driven on the same child and the refresh run
prints NOT RUN. Both platforms also run lsof's parser on a real lsof's output.
Section 11c runs real processes too: a child that writes the lines the test
sends it, a REAL `sed -i` over its log, more lines that reach only the deleted
file, then refresh and real follower passes; each case states exactly which
lines must come back, once. Its refresh runs are Linux-only for the same
reason; its reader checks run on both platforms.

A check that passes against its mutant cannot see the defect it is there for,
so every green it reports is decoration: the run then ends NO VERDICT (exit 3)
instead of reporting a pass. Deleting a control() call turns its check back into
one that cannot fail for its reason; the list above is what each one is for.
A control that cannot be BUILT, because the text it
mutates no longer occurs exactly once, is NO VERDICT too: re-point the control
at the new text, never delete it.
"""

import difflib
import fcntl
import importlib.util
import io
import json
import os
import plistlib
import re
import select
import shutil
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True     # importing the subject must leave nothing in the repo

HERE = os.path.dirname(os.path.realpath(__file__))
FLEET = os.path.dirname(HERE)
SCRIPT = os.path.join(HERE, "agent-daemons.py")
FIX = os.path.join(FLEET, "tests", "fixtures", "systemd")
REGISTRY = os.path.join(FIX, "transports")
TEMPLATES = ("agent-sched@.service.in", "agent-watch@.service.in",
             "agent-daemons-refresh.service.in", "agent-daemons-refresh.timer",
             "agent-sched.plist.in", "agent-watch.plist.in", "agent-daemons-refresh.plist.in")
SLACK_PRIORITY = r"^(SCHED due|SCHED alert|SLACK DM |DAEMON-)"
_failures, _no_verdict = [], []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" - {detail}" if detail and not cond else ""))
    if not cond:
        _failures.append(name)


def control(name, subject, probe):
    """`probe(subject)` must be False: the check fails against the mutant."""
    if subject is None:
        print(f"[NO VERDICT] CONTROL {name}: the mutant could not be built")
        _no_verdict.append(name)
    elif probe(subject):
        print(f"[NO VERDICT] CONTROL {name}: the check PASSED against a subject that breaks it")
        _no_verdict.append(name)
    else:
        print(f"[PASS] CONTROL {name}: the check fails against the mutant")


TMP = tempfile.mkdtemp(prefix="agent-daemons-test-")
ROOT = os.path.join(TMP, "agents")
HOST = os.path.join(TMP, "host.json")
FAKE = os.path.join(TMP, "systemctl")
STATE = os.path.join(TMP, "units.json")
CALLS = os.path.join(TMP, "calls.log")
PROC = os.path.join(TMP, "proc")
UNITDIR = os.path.join(TMP, "home", ".config", "systemd", "user")

with open(HOST, "w") as f:
    json.dump({"schema": 1, "agents_root": ROOT, "fleet_checkout": FLEET,
               "claims_dir": os.path.join(TMP, "claims")}, f)

with open(FAKE, "w") as f:
    f.write(r'''#!/usr/bin/env python3
import fnmatch, json, os, sys
state_p, calls_p = os.environ["FAKE_STATE"], os.environ["FAKE_CALLS"]
args = sys.argv[1:]
with open(calls_p, "a") as f:
    f.write(" ".join(args) + "\n")
if args and args[0] == "--user":
    args = args[1:]
try:
    state = json.load(open(state_p))
except (OSError, ValueError):
    state = {}
if args[:1] == ["show"]:
    u = state.get(args[1], {"LoadState": "not-found", "ActiveState": "inactive",
                            "SubState": "dead", "Result": "success", "NRestarts": "0",
                            "MainPID": "0"})
    props = [args[i + 1] for i, a in enumerate(args) if a == "-p"]
    for p in props:
        print(f"{p}={u.get(p, '')}")
elif args[:1] == ["list-units"]:
    pats = [a for a in args[1:] if not a.startswith("-")]
    for name in state:
        if any(fnmatch.fnmatch(name, p) for p in pats):
            print(f"{name} loaded active running x")
elif args[:1] == ["restart"]:
    state.setdefault(args[1], {})["NRestarts"] = "0"
    json.dump(state, open(state_p, "w"))
''')
os.chmod(FAKE, 0o755)


def set_units(d):
    with open(STATE, "w") as f:
        json.dump(d, f)


def calls():
    try:
        return open(CALLS).read().splitlines()
    except FileNotFoundError:
        return []


# The test's environment, and nothing inherited that could point the subject at
# a real host: every AGENT_DAEMONS_* and FLEET_* variable of the caller is dropped.
# Sections 1-13 test the systemd backend, forced, so they run unchanged on macOS;
# section LD below runs the same subject under launchd with the fake launchctl.
# XDG_CONFIG_HOME is dropped with the fleet's own variables: the user unit
# directory is $XDG_CONFIG_HOME/systemd/user when it is set (a CI runner sets
# it), and an inherited one would point the subject at a real directory.
ENV = {k: v for k, v in os.environ.items()
       if not k.startswith(("AGENT_DAEMONS_", "FLEET_")) and k != "XDG_CONFIG_HOME"}
ENV.update({"FLEET_HOST_CONFIG": HOST, "FLEET_TRANSPORTS_DIR": REGISTRY,
            "AGENT_DAEMONS_SYSTEMCTL": FAKE, "AGENT_DAEMONS_PROC": PROC,
            "FLEET_SERVICE_BACKEND": "systemd",
            "FAKE_STATE": STATE, "FAKE_CALLS": CALLS, "HOME": os.path.join(TMP, "home")})
for k in [k for k in os.environ if k.startswith(("AGENT_DAEMONS_", "FLEET_")) or k == "XDG_CONFIG_HOME"]:
    del os.environ[k]
os.environ.update({k: ENV[k] for k in ("FLEET_HOST_CONFIG", "FLEET_TRANSPORTS_DIR",
                                       "AGENT_DAEMONS_SYSTEMCTL", "AGENT_DAEMONS_PROC",
                                       "FLEET_SERVICE_BACKEND", "FAKE_STATE", "FAKE_CALLS")})

_n = [0]


def fresh(name, base=None):
    """A path no other call has returned: <base or TMP>/<name><n>."""
    _n[0] += 1
    return os.path.join(base or TMP, f"{name}{_n[0]}")


def load(path, name=None):
    spec = importlib.util.spec_from_file_location(name or os.path.basename(fresh("mod")), path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def tree(script_text=None, template_edits=None):
    """A throwaway fleet tree: systemd/ holding the subject (or `script_text`) and
    the templates (with `template_edits` applied), lib/ linked to the real library.
    None when an edit's text does not occur exactly once."""
    d = fresh("tree")
    os.makedirs(os.path.join(d, "systemd"))
    os.symlink(os.path.join(FLEET, "lib"), os.path.join(d, "lib"))
    for t in TEMPLATES:
        text = open(os.path.join(HERE, t)).read()
        for old, new in (template_edits or {}).get(t, ()):
            if text.count(old) != 1:
                return None
            text = text.replace(old, new)
        with open(os.path.join(d, "systemd", t), "w") as f:
            f.write(text)
    p = os.path.join(d, "systemd", "agent-daemons.py")
    with open(p, "w") as f:
        f.write(open(SCRIPT).read() if script_text is None else script_text)
    return p


def mutant(old, new):
    src = open(SCRIPT).read()
    return tree(src.replace(old, new)) if src.count(old) == 1 else None


def run(script, *args, env=None):
    return subprocess.run([sys.executable, script, *args], capture_output=True, text=True,
                          env=env or ENV)


ad = load(SCRIPT, "agent_daemons")
LOG = os.path.join(ROOT, "fake", "state", "daemons", "sched.log")
AGENT = "fake"
# Unit names are built, never written as literals: `<job>@<agent>.service` has the
# shape of an e-mail address, which the commit gate's public patterns refuse.
UNIT = f"agent-sched@{AGENT}.service"
WUNIT = f"agent-slack-watch@{AGENT}.service"
ACTIVE = {"LoadState": "loaded", "ActiveState": "active", "SubState": "running",
          "Result": "success", "NRestarts": "0"}
os.makedirs(os.path.dirname(LOG))
os.makedirs(os.path.join(ROOT, "fake", "product", ".claude"))
with open(os.path.join(ROOT, "fake", "product", ".claude", "fleet.json"), "w") as f:
    f.write("{}\n")                 # render-units finds the install checkout by this file
set_units({UNIT: dict(ACTIVE)})


def append(text, path=LOG):
    with open(path, "a") as f:
        f.write(text)


def follow_once(*extra, log=LOG, script=SCRIPT, job="sched", env=None):
    """One follower PROCESS: load cursor, deliver, one unit check, exit. A fresh
    process per call is the restart the cursor has to survive."""
    r = run(script, "follow", "fake", job, "--once", "--log", log, "--unit", UNIT, *extra,
            env=env)
    return r.stdout.splitlines(), r


# === 1. first run starts at the end ==========================================
print("--- 1. no cursor: start at end of file ---")
append("old 1\nold 2\nold 3\n")
out, _ = follow_once()
check("a first run with no cursor prints nothing that was already there", out == [], str(out))
check("...and leaves a cursor beside the log", os.path.exists(LOG + ".cursor"))

# === 2. resume across a restart ==============================================
print("--- 2. resume across follower restarts ---")
append("a\nb\n")
out1, _ = follow_once()
append("c\n")
out2, _ = follow_once()
out3, _ = follow_once()
check("lines written while no follower ran are delivered on the next run",
      out1 == ["a", "b"], str(out1))
check("a restart delivers only what is new - nothing doubled", out2 == ["c"], str(out2))
check("a run with nothing new prints nothing", out3 == [], str(out3))

# === 3. partial line =========================================================
print("--- 3. a partial line waits until it is complete ---")
append("SCHED due [tsk_1] run=1 half")
out, _ = follow_once()
check("a line with no newline yet is NOT printed", out == [], str(out))
append(" and the rest\n")
out, _ = follow_once()
check("...and is printed once, whole, when it completes",
      out == ["SCHED due [tsk_1] run=1 half and the rest"], str(out))

# === 4. truncation ===========================================================
print("--- 4. truncation ---")
with open(LOG, "w") as f:
    f.write("x1\n")
out, _ = follow_once()
check("a log shorter than the cursor is announced in ONE line and read from 0",
      len(out) == 2 and out[0].startswith("DAEMON-FOLLOW") and "truncated" in out[0]
      and out[1] == "x1", str(out))

# === 5. rotation =============================================================
print("--- 5. rotation ---")
append("before-rotate\n")
subprocess.run([sys.executable, SCRIPT, "rotate", LOG, "--max-bytes", "1"], env=ENV, check=True)
check("rotate moves an oversized log to .1", os.path.exists(LOG + ".1") and not os.path.exists(LOG))
append("after-rotate\n")
out, _ = follow_once()
check("an undelivered tail in .1 is drained before the new file, with no notice",
      out == ["before-rotate", "after-rotate"], str(out))
subprocess.run([sys.executable, SCRIPT, "rotate", LOG, "--max-bytes", "10000"], env=ENV, check=True)
check("rotate leaves a small log alone", os.path.exists(LOG))
append("lost-with-old\n")
os.replace(LOG, LOG + ".gone")
append("fresh\n")
out, _ = follow_once()
check("a replaced log whose old file is gone is announced once and read from 0",
      len(out) == 2 and out[0].startswith("DAEMON-FOLLOW") and "replaced" in out[0]
      and out[1] == "fresh", str(out))
# rotate is every unit's ExecStartPre: it must work with no host settings and no
# transport registry, or a broken fleet install keeps every daemon from starting.
broken = {**ENV, "FLEET_HOST_CONFIG": os.path.join(TMP, "absent.json"),
          "FLEET_TRANSPORTS_DIR": os.path.join(TMP, "absent-registry")}
big = os.path.join(TMP, "rotate-alone.log")
append("x" * 100 + "\n", path=big)
r = run(SCRIPT, "rotate", big, "--max-bytes", "10", env=broken)
check("rotate works with no host settings and no transport registry",
      r.returncode == 0 and os.path.exists(big + ".1"), r.stderr)
r = run(SCRIPT, "follow", "fake", "sched", "--once", env=broken)
check("...where follow, which needs both, exits 3 naming `fleet install` "
      "(control: that environment really is broken)",
      r.returncode == 3 and "fleet install" in r.stderr, f"{r.returncode} {r.stderr}")

# === 6. backlog cap ==========================================================
print("--- 6. a long gap is condensed, not dumped ---")
lines = [f"SLACK #general message [ts {i}] chatter {i}" for i in range(100)]
lines[5] = "SCHED due [tsk_old] run=9 the one that matters"
lines[50] = "SLACK DM message [ts 50] U1: are you there"
append("\n".join(lines) + "\n")
out, _ = follow_once("--replay-max", "10")
check("a backlog over --replay-max prints a header plus exactly M lines",
      len(out) == 11 and out[0].startswith("DAEMON-BACKLOG") and "100 lines since" in out[0],
      f"{len(out)} lines, first={out[:1]}")
check("the due line and the DM survive the cap (the default --priority)",
      lines[5] in out and lines[50] in out, str(out))
check("the rest are the NEWEST lines, in log order",
      out[3:] == lines[92:], str(out[3:]))
check("the header says where the dropped lines are", LOG in out[0], out[0])
out, _ = follow_once()
check("the condensed backlog is consumed - the next run prints nothing", out == [], str(out))

# === 7. filters ==============================================================
print("--- 7. include / exclude ---")
append("SLACK DM keep\nWATCH-INFO retired DM DEXAMPLE1 noise\nSLACK #c keep2\n")
out, _ = follow_once("--exclude", r"retired DM DEXAMPLE1")
check("--exclude drops the matching line and keeps the rest",
      out == ["SLACK DM keep", "SLACK #c keep2"], str(out))
append("SCHED-INFO tick\nSCHED due [t] x\n")
out, _ = follow_once("--include", r"^SCHED due")
check("--include prints only matching lines", out == ["SCHED due [t] x"], str(out))
out, _ = follow_once()
check("filtered lines are consumed, not re-offered", out == [], str(out))

# === 8. unit checks ==========================================================
print("--- 8. unit checks ---")
out, _ = follow_once()
check("an active unit with no new restarts prints nothing", out == [], str(out))
set_units({UNIT: {**ACTIVE, "NRestarts": "2"}})
out, _ = follow_once()
check("a restart count that rose gives ONE alert",
      len(out) == 1 and out[0].startswith("DAEMON-ALERT") and "2 time(s)" in out[0], str(out))
out, _ = follow_once()
check("...and no second alert for the same count", out == [], str(out))
set_units({UNIT: {"LoadState": "loaded", "ActiveState": "inactive", "SubState": "dead",
                  "Result": "success", "NRestarts": "0"}})
out, _ = follow_once()
check("a unit that is down is alerted on arm, naming the GUARD case",
      len(out) == 1 and out[0].startswith("DAEMON-ALERT") and "GUARD" in out[0], str(out))
f = ad.Follower(LOG, UNIT, out=io.StringIO())
f.load()
f.cur.pop("was_active", None)      # what run() does on every arm
f.check_unit(time.time())          # the arm's first check, then a minute later, still down
f.check_unit(time.time() + 60)
check("a follower that already alerted stays quiet while the unit stays down",
      f.out.getvalue().count("DAEMON-ALERT") == 1, f.out.getvalue())
f.check_unit(time.time() + ad.REALERT_SECS + 61)
check("...and re-announces it once the re-alert interval has passed",
      f.out.getvalue().count("DAEMON-ALERT") == 2, f.out.getvalue())
set_units({UNIT: dict(ACTIVE)})
f.check_unit(time.time() + ad.REALERT_SECS + 120)
check("recovery prints one DAEMON-OK", "DAEMON-OK" in f.out.getvalue(), f.out.getvalue())
set_units({})
out, _ = follow_once()
check("a unit that is not installed says so",
      len(out) == 1 and "not installed" in out[0], str(out))
set_units({UNIT: dict(ACTIVE)})

# === 9. killed mid-delivery, and its negative control (K) ====================
print("--- 9. killed mid-delivery: repeat, never lose ---")


class DiesAfter(io.StringIO):
    def __init__(self, n):
        super().__init__()
        self.n = n

    def write(self, s):
        if self.getvalue().count("\n") >= self.n:
            raise BrokenPipeError(32, "Broken pipe")
        return super().write(s)


def kill_case(mod):
    """Deliver l1..l4 to a reader that dies after two lines, then restart. The
    union of what the reader saw must be l1..l4: nothing missing."""
    log = fresh("kill-", os.path.join(ROOT, "fake", "state", "daemons")) + ".log"
    open(log, "w").close()
    f0 = mod.Follower(log, UNIT, out=io.StringIO()); f0.load()
    append("l1\nl2\nl3\nl4\n", path=log)
    dead = DiesAfter(2)
    f1 = mod.Follower(log, UNIT, out=dead); f1.load()
    try:
        f1.poll_log()
    except BrokenPipeError:
        pass
    f2 = mod.Follower(log, UNIT, out=io.StringIO()); f2.load()
    f2.poll_log()
    return dead.getvalue().splitlines() + f2.out.getvalue().splitlines()


seen = kill_case(ad)
check("a reader killed after two lines: the restart delivers the rest, nothing lost",
      [l for l in ["l1", "l2", "l3", "l4"] if l not in seen] == [], str(seen))
check("...and nothing the dead reader already printed is repeated",
      seen == ["l1", "l2", "l3", "l4"], str(seen))
control("K: a follower that saves the cursor before printing LOSES a line",
        mutant('            self.emit(text)\n            self.cur["offset"] = pos\n'
               '            self.save()\n',
               '            self.cur["offset"] = pos\n            self.save()\n'
               '            self.emit(text)\n'),
        lambda s: [l for l in ["l1", "l2", "l3", "l4"] if l not in kill_case(load(s))] == [])

# === 9b. the follower ends itself before the Monitor's kill ==================
print("--- 9b. self-stop before the harness kill ---")
blog = os.path.join(ROOT, "fake", "state", "daemons", "bound.log")
open(blog, "w").close()
follow_once(log=blog)                                   # cursor at the (empty) end
p = subprocess.Popen([sys.executable, SCRIPT, "follow", "fake", "sched", "--log", blog,
                      "--unit", UNIT, "--max-secs", "1.5", "--poll-secs", "0.1",
                      "--check-secs", "999"],
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=ENV)
time.sleep(0.5)
append("before-stop\n", path=blog)
try:
    bout, _ = p.communicate(timeout=10)
    brc = p.returncode
except subprocess.TimeoutExpired:
    p.kill(); bout, brc = p.communicate()[0], "timeout"
blines = bout.splitlines()
check("a follower past --max-secs exits on its own with 0", brc == 0, str(brc))
check("...having delivered the line written before it stopped",
      "before-stop" in blines, str(blines))
check("...and its LAST line says it stopped and to re-arm",
      bool(blines) and blines[-1].startswith("DAEMON-FOLLOW follow fake sched: stopping")
      and "re-arm" in blines[-1], str(blines))
append("after-stop\n", path=blog)
nout, _ = follow_once(log=blog)
check("a line written after the self-stop is delivered by the next arm",
      "after-stop" in nout and "before-stop" not in nout, str(nout))
p = subprocess.Popen([sys.executable, SCRIPT, "follow", "fake", "sched", "--log", blog,
                      "--unit", UNIT, "--max-secs", "0", "--poll-secs", "0.1",
                      "--check-secs", "999"],
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=ENV)
try:
    p.wait(timeout=3); still = False
except subprocess.TimeoutExpired:
    still = True
p.kill(); p.communicate()
check("--max-secs 0 never self-stops (control: the bound is what ended the first one)", still)

# === 10. one follower per log ================================================
print("--- 10. duplicate follower ---")
p = subprocess.Popen([sys.executable, SCRIPT, "follow", "fake", "sched", "--log", LOG,
                      "--unit", UNIT, "--check-secs", "3600"],
                     stdout=subprocess.PIPE, text=True, env=ENV)
time.sleep(0.6)
append("live line\n")
ready, _, _ = select.select([p.stdout], [], [], 5)
live = p.stdout.readline().strip() if ready else None
check("a running follower delivers a line appended while it runs, within its poll",
      live == "live line", repr(live))
out, r = follow_once()
p.terminate(); p.wait()
check("a second follower on the same log exits 0 with one DAEMON-FOLLOW line",
      r.returncode == 0 and len(out) == 1 and "another follower" in out[0], str(out))

# === 10b. where the agents root comes from ===================================
print("--- 10b. the agents root: host.json, or AGENT_DAEMONS_ROOT ---")
alt = os.path.join(TMP, "alt-root")
run(SCRIPT, "follow", "rootcheck", "sched", "--once", "--unit", UNIT)
check("with no override the log lives under host.json's agents_root",
      os.path.exists(os.path.join(ROOT, "rootcheck", "state", "daemons", "sched.log.cursor")))
run(SCRIPT, "follow", "rootcheck2", "sched", "--once", "--unit", UNIT,
    env={**ENV, "AGENT_DAEMONS_ROOT": alt})
check("...and AGENT_DAEMONS_ROOT overrides it (and only it is written)",
      os.path.exists(os.path.join(alt, "rootcheck2", "state", "daemons", "sched.log.cursor"))
      and not os.path.exists(os.path.join(ROOT, "rootcheck2")))

# === J. jobs come from the transport descriptors =============================
print("--- J. jobs: sched plus one per working transport ---")
js = ad.jobs()
check("the fixture registry (Slack working, Discord placeholder) gives exactly sched and "
      "slack-watch: a placeholder gets no job", list(js) == ["sched", "slack-watch"], str(list(js)))
sw = js.get("slack-watch", {})
check("the Slack job's names are today's, literally",
      ad.unit_name("slack-watch", "") == "agent-slack-watch@.service"
      and sw.get("config") == "config/slack-watch.json"
      and sw.get("config_env") == "SLACK_WATCH_CONFIG"
      and ad.log_path("fake", "slack-watch")
      == os.path.join(ROOT, "fake", "state", "daemons", "slack-watch.log"), str(sw))

# A second working transport whose watch.job is NOT <name>-watch, so a derivation
# that guessed the names from the transport name cannot pass by coincidence.
REG2 = os.path.join(TMP, "registry2")
for d in os.listdir(REGISTRY):
    shutil.copytree(os.path.join(REGISTRY, d), os.path.join(REG2, d))
os.makedirs(os.path.join(REG2, "example-communication"))
with open(os.path.join(REG2, "example-communication", "transport.json"), "w") as f:
    json.dump({"schema": 1, "name": "example", "status": "working", "line_prefix": "EXAMPLE",
               "kinds": ["channel", "dm"],
               "ids": {"user": "^E[0-9]{3}$", "conversation": "^C[0-9]{3}$",
                       "message": "^[0-9]+$"},
               "watch": {"script": "poll.py", "job": "example-relay",
                         "config_env": "EXAMPLE_RELAY_CONFIG",
                         "follow_include": "^EXAMPLE |^DAEMON-"}}, f)


def render_all(script, registry=REGISTRY, units="all", out=None, env=None):
    out = out or fresh("render")
    r = run(script, "render-units", "--units", units, "--out", out,
            env={**(env or ENV), "FLEET_TRANSPORTS_DIR": registry})
    files = ({n: open(os.path.join(out, n)).read() for n in sorted(os.listdir(out))}
             if os.path.isdir(out) else {})
    return r, files


def probe_jobs(script):
    r, files = render_all(script, REG2)
    want = ["agent-daemons-refresh.service", "agent-daemons-refresh.timer",
            "agent-example-relay@.service", "agent-sched@.service", "agent-slack-watch@.service"]
    problems = [] if r.returncode == 0 else [f"exit {r.returncode}: {r.stderr.strip()}"]
    if sorted(files) != want:
        problems.append(f"unit files {sorted(files)}")
    for unit, job, var in (("agent-slack-watch@.service", "slack-watch", "SLACK_WATCH_CONFIG"),
                           ("agent-example-relay@.service", "example-relay",
                            "EXAMPLE_RELAY_CONFIG")):
        have = files.get(unit, "").splitlines()
        for line in (f"Environment={var}={ROOT}/%i/config/{job}.json",
                     f"EnvironmentFile=-{ROOT}/%i/config/{job}.env",
                     f"StandardOutput=append:{ROOT}/%i/state/daemons/{job}.log"):
            if line not in have:
                problems.append(f"{unit} has no line {line}")
    return not problems, "; ".join(problems)


check("a second working transport gets its own unit, config file, config variable and log, "
      "all named from its descriptor; the placeholder still gets none", *probe_jobs(SCRIPT))
control("J: config file named <name>-watch instead of the descriptor's watch.job",
        mutant('"config": f"config/{job}.json"', '"config": f"config/{t[\'name\']}-watch.json"'),
        lambda s: probe_jobs(s)[0])

# === Q. the job table `fleet` reads ==========================================
print("--- Q. jobs --json is the table the units are rendered from ---")


def probe_jobs_json(script):
    """`fleet pin-daemons` writes drop-ins from jobs --json, so every job it names
    must be a rendered unit whose ExecStart runs the table's python on the table's
    script, logging to the table's log. Judged against the units rendered from the
    same tree and registry, not against values written here. No host settings."""
    r = run(script, "jobs", "--json", env={**ENV, "FLEET_TRANSPORTS_DIR": REG2,
                                           "FLEET_HOST_CONFIG": os.path.join(TMP, "absent.json")})
    try:
        table = json.loads(r.stdout)
        jobs_ = table["jobs"]
    except (ValueError, KeyError, TypeError):
        return False, f"exit {r.returncode}, not a job table: {r.stdout}{r.stderr}"
    _, files = render_all(script, REG2)
    want = sorted(n for n in files if "@" in n)
    problems = [] if sorted(j["unit"] for j in jobs_.values()) == want else [
        f"units {sorted(j['unit'] for j in jobs_.values())} != rendered {want}"]
    if "sched" not in jobs_:      # the positive control: an empty table matching an empty render
        problems.append(f"no sched job in {sorted(jobs_)}")
    for j in jobs_.values():
        have = files.get(j["unit"], "").splitlines()
        for line in (f"ExecStart={table['python']} -u {j['script']}",
                     f"StandardOutput=append:{ROOT}/%i/{j['log']}",
                     f"Environment={j['config_env']}={ROOT}/%i/{j['config']}"):
            if line not in have:
                problems.append(f"{j['unit']} has no line {line}")
    return not problems, "; ".join(problems)


check("jobs --json, with no host settings, names exactly the rendered job units, and each "
      "one's interpreter, script, log and config are the rendered unit's", *probe_jobs_json(SCRIPT))
control("Q: jobs --json reports a log path the units do not write",
        mutant('"log": log_rel(job)}', '"log": f"{job}.log"}'),
        lambda s: probe_jobs_json(s)[0])

# === P. the priority regex ===================================================
print("--- P. the default --priority ---")


def priority_of(script, registry=REGISTRY):
    os.environ["FLEET_TRANSPORTS_DIR"] = registry
    try:
        return load(script).priority_default()
    finally:
        os.environ["FLEET_TRANSPORTS_DIR"] = REGISTRY


check(f"with Slack the only working transport it is exactly {SLACK_PRIORITY}",
      priority_of(SCRIPT) == SLACK_PRIORITY, priority_of(SCRIPT))
check("each further working transport adds its own '<PREFIX> DM '",
      priority_of(SCRIPT, REG2) == r"^(SCHED due|SCHED alert|EXAMPLE DM |SLACK DM |DAEMON-)",
      priority_of(SCRIPT, REG2))
control("P: the prefix escaped together with ' DM ' (re.escape escapes the spaces)",
        mutant('re.escape(j["line_prefix"]) + " DM |"', 're.escape(j["line_prefix"] + " DM ") + "|"'),
        lambda s: priority_of(s) == SLACK_PRIORITY)

# === F. follow's default filter ==============================================
print("--- F. follow with no --include applies the descriptor's filter ---")
F_LINES = ["SLACK #general message [ts 1.000001] Ada: hello",
           "WATCH-ERROR conversations.history CEXAMPLE1: HTTP 429 Too Many Requests",
           "WATCH-ERROR discovery: users.conversations failed",
           "some unrelated chatter",
           f"DAEMON-REFRESH restarting {WUNIT}: daily restart"]
F_KEPT = [F_LINES[0], F_LINES[2], F_LINES[4]]


def follow_fresh(script, job, *extra):
    log = fresh("filter-", os.path.join(ROOT, "fake", "state", "daemons")) + ".log"
    open(log, "w").close()
    follow_once(log=log, script=script, job=job)        # cursor at the (empty) end
    append("\n".join(F_LINES) + "\n", path=log)
    return follow_once(*extra, log=log, script=script, job=job)[0]


def probe_follow_filter(script):
    out = follow_fresh(script, "slack-watch")
    return out == F_KEPT, str(out)


check("follow <agent> slack-watch with no --include delivers only what follow_include "
      "keeps (the per-conversation 429 and the chatter are dropped)", *probe_follow_filter(SCRIPT))
out = follow_fresh(SCRIPT, "slack-watch", "--include", "")
check("...while --include '' delivers all five (control: the lines reach the follower, and "
      "the filter is what dropped two)", out == F_LINES, str(out))
out = follow_fresh(SCRIPT, "sched")
check("...and the sched job, which has no descriptor, gets no default filter",
      out == F_LINES, str(out))
control("F: --include left as given, the descriptor's filter never applied",
        mutant('include = js[a.job]["include"] if a.include is None else a.include',
               'include = a.include'),
        lambda s: probe_follow_filter(s)[0])

# === 11. refresh reads the running process ===================================
print("--- 11. refresh: staleness from /proc, and the daily restart ---")
CLK = os.sysconf("SC_CLK_TCK")
NOW = time.time()
BTIME = int(NOW) - 3 * 86400
STARTED = NOW - 3600             # both fake processes started an hour ago
OLD = NOW - 7200                 # every input file is older than that
HOME_ = os.path.join(ROOT, "fake")
CANARY = os.path.join(TMP, "canary", "scheduled-tasks", "sched.py")   # what the process runs
PRODUCT = os.path.join(HOME_, "product", ".claude", "skills", "scheduled-tasks", "sched.py")
ALT_CFG = os.path.join(TMP, "alt-config", "scheduler.json")          # what its environ names
DEFAULT_CFG = os.path.join(HOME_, "config", "scheduler.json")
ENVFILE = os.path.join(HOME_, "config", "sched.env")
W_SCRIPT = os.path.join(TMP, "canary", "slack-communication", "watch.py")
W_CFG = os.path.join(TMP, "alt-config", "slack-watch.json")
INPUTS = (CANARY, PRODUCT, ALT_CFG, DEFAULT_CFG, ENVFILE, W_SCRIPT, W_CFG)
for pth in INPUTS:
    os.makedirs(os.path.dirname(pth), exist_ok=True)
    with open(pth, "w") as f:
        f.write("x\n")
os.makedirs(PROC)
with open(os.path.join(PROC, "stat"), "w") as f:
    f.write(f"cpu  1 2 3 4\nbtime {BTIME}\nprocesses 1\n")


def fake_process(pid, argv, environ, cwd, started):
    d = os.path.join(PROC, str(pid))
    os.makedirs(d)
    fields = ["S"] + ["0"] * 18 + [str(int((started - BTIME) * CLK))] + ["0"] * 20
    with open(os.path.join(d, "stat"), "w") as f:
        f.write(f"{pid} (python3 (x)) " + " ".join(fields) + "\n")
    for name, items in (("cmdline", argv), ("environ", environ)):
        with open(os.path.join(d, name), "wb") as f:
            f.write(b"".join(x.encode() + b"\0" for x in items))
    os.symlink(cwd, os.path.join(d, "cwd"))


fake_process(4242, ["/usr/bin/python3", "-u", CANARY],
             ["CLAUDE_CONFIG_DIR=" + os.path.join(HOME_, ".claude"), "SCHED_CONFIG=" + ALT_CFG],
             os.path.join(HOME_, "product"), STARTED)
fake_process(4243, ["/usr/bin/python3", "-u", W_SCRIPT], ["SLACK_WATCH_CONFIG=" + W_CFG],
             os.path.join(HOME_, "product"), STARTED)
UNITS_UP = {UNIT: {**ACTIVE, "MainPID": "4242"}, WUNIT: {**ACTIVE, "MainPID": "4243"}}


def age_all():
    for pth in INPUTS:
        os.utime(pth, (OLD, OLD))
    set_units(UNITS_UP)


def refresh(*extra, script=SCRIPT):
    open(CALLS, "w").close()
    r = run(script, "refresh", *extra)
    return [c for c in calls() if c.startswith("--user restart")], r


age_all()
got, r = refresh()
check("no input newer than either process, both young: no restart",
      got == [] and r.returncode == 0, f"{got} {r.stderr}")
size0 = os.path.getsize(LOG)


def probe_running_script(script):
    age_all()
    os.utime(CANARY, None)
    return refresh(script=script)[0] == [f"--user restart {UNIT}"]


check("the script named in /proc/<pid>/cmdline changed: its unit restarts",
      probe_running_script(SCRIPT), str(calls()))
tail = open(LOG).read()[size0:]
check("...and the reason is written into the log the session reads",
      f"DAEMON-REFRESH restarting {UNIT}: {CANARY} changed after the process started" in tail,
      tail)
age_all()
os.utime(PRODUCT, None)
check("a copy of the script the process does NOT run changed: no restart (control: the "
      "decision comes from the process, not from a path the code assumes)",
      refresh()[0] == [], str(calls()))
control("X: refresh checks the job's own script path, not the process's cmdline",
        mutant('script = next((x for x in argv[1:] if not x.startswith("-")), None)',
               'script = j["script"]'),
        probe_running_script)
age_all()
os.utime(ALT_CFG, None)
check("the config file named by the process's SCHED_CONFIG changed: restart",
      refresh()[0] == [f"--user restart {UNIT}"], str(calls()))
age_all()
os.utime(DEFAULT_CFG, None)
check("the agent's default config changed while the process names another: no restart",
      refresh()[0] == [], str(calls()))
age_all()
os.utime(ENVFILE, None)
size1 = os.path.getsize(LOG)
check("<home>/config/<job>.env changed: restart",
      refresh()[0] == [f"--user restart {UNIT}"], str(calls()))
check("...its reason names the file relative to the agent home, as the reasons always have",
      "config/sched.env changed after the process started\n" in open(LOG).read()[size1:])
age_all()
os.utime(W_CFG, None)
check("a watch job's config comes from its descriptor's config_env (SLACK_WATCH_CONFIG) in "
      "the process environment", refresh()[0] == [f"--user restart {WUNIT}"], str(calls()))
age_all()
got = refresh("--max-age-hours", "0")[0]
check("a process older than --max-age-hours is restarted (the daily restart)",
      sorted(got) == sorted([f"--user restart {UNIT}", f"--user restart {WUNIT}"]), str(got))
set_units({UNIT: {"LoadState": "loaded", "ActiveState": "inactive", "MainPID": "0"},
           WUNIT: {**ACTIVE, "MainPID": "4243"}})
got = refresh("--max-age-hours", "0")[0]
check("a unit that is down is left to the follower's alert, never started by refresh",
      got == [f"--user restart {WUNIT}"], str(got))

# === D. refresh --dry-run ====================================================
print("--- D. refresh --dry-run restarts nothing ---")


def probe_dry_run(script):
    age_all()
    os.utime(CANARY, None)
    size = os.path.getsize(LOG)
    got, r = refresh("--dry-run", script=script)
    problems = []
    if got:
        problems.append(f"restarted {got}")
    if f"DRY-RUN restart {UNIT}: " not in r.stdout:
        problems.append("no DRY-RUN restart line for the stale unit")
    if f"DRY-RUN keep {WUNIT}: " not in r.stdout:
        problems.append("no DRY-RUN keep line for the fresh unit")
    if os.path.getsize(LOG) != size:
        problems.append("it wrote into the log")
    return not problems, "; ".join(problems) + f" | {r.stdout}{r.stderr}"


check("a stale unit under --dry-run: a decision line for every unit, no restart, nothing "
      "written to the log", *probe_dry_run(SCRIPT))
age_all()
os.utime(CANARY, None)
check("...where the same state without --dry-run restarts it (control: the state is stale)",
      refresh()[0] == [f"--user restart {UNIT}"], str(calls()))
set_units({UNIT: {"LoadState": "loaded", "ActiveState": "inactive", "MainPID": "0"}})
got, r = refresh("--dry-run")
check("--dry-run names a unit that is down as skipped",
      got == [] and f"DRY-RUN skip {UNIT}: not active" in r.stdout, r.stdout)
control("D: --dry-run ignored", mutant('dry = "DRY-RUN " if a.dry_run else ""', 'dry = ""'),
        lambda s: probe_dry_run(s)[0])

# === 11b. a daemon writing to a replaced log =================================
print("--- 11b. refresh restarts a daemon whose log was replaced (a real process) ---")
DEAF = "deaf"
DUNIT = f"agent-sched@{DEAF}.service"
DLOG = os.path.join(ROOT, DEAF, "state", "daemons", "sched.log")
os.makedirs(os.path.dirname(DLOG))
os.makedirs(os.path.join(ROOT, DEAF, "config"))
with open(os.path.join(ROOT, DEAF, "config", "scheduler.json"), "w") as f:
    f.write("{}\n")             # the scheduler is configured for this agent: status counts it
CHILD = ("import sys, time\n"
         "while True:\n"
         "    print('SCHED tick', flush=True)\n"
         "    time.sleep(0.1)\n")


def start_child(log, out=None):
    """A process writing to `log` as a unit's StandardOutput=append: does, or to a pipe."""
    if out is None:
        with open(log, "a") as f:
            return subprocess.Popen([sys.executable, "-c", CHILD], stdout=f, stderr=subprocess.STDOUT)
    return subprocess.Popen([sys.executable, "-c", CHILD], stdout=out, stderr=subprocess.STDOUT)


def replace_like_sed(log):
    """What `sed -i` does: write the edited text to a new file, rename it over the path."""
    with open(log) as f:
        text = f.read().replace("tick", "tock")
    tmp = os.path.join(os.path.dirname(log), ".sedXXXX")
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, log)


def wait_growth(log, size, secs=10.0):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        if os.path.exists(log) and os.path.getsize(log) > size:
            return True
        time.sleep(0.05)
    return False


def native_reader(pid):
    """The platform's own reader, as a refresh outside this test reads it: no fake /proc."""
    saved = os.environ.pop("AGENT_DAEMONS_PROC")
    try:
        return ad.stdio_files(pid)
    finally:
        os.environ["AGENT_DAEMONS_PROC"] = saved


def real_lsof(pid):
    lsof = shutil.which("lsof") or (ad.LSOF if os.path.exists(ad.LSOF) else None)
    if not lsof:
        return None
    r = subprocess.run([lsof, "-n", "-P", "+L", "-a", "-p", str(pid), "-d", "1,2", "-F", "ftikn"],
                       capture_output=True, text=True, timeout=30)
    return r.stdout


# lsof's -F output as macOS and Linux print it, for a live file and an unlinked one.
LSOF_LIVE = "p77\nf1\ntREG\ni1234\nk1\nn/x/sched.log\nf2\ntREG\ni1234\nk1\nn/x/sched.log\n"
LSOF_GONE = "p77\nf1\ntREG\ni1234\nk0\nn/x/sched.log (deleted)\nf2\ntPIPE\ni55\nnpipe\n"
check("lsof's fields parse into the regular files with their inode and link count",
      ad.parse_lsof(LSOF_LIVE) == {1: ("/x/sched.log", 1234, None, False), 2: ("/x/sched.log", 1234, None, False)}
      and ad.parse_lsof(LSOF_GONE) == {1: ("/x/sched.log", 1234, None, True)}, str(ad.parse_lsof(LSOF_GONE)))

linux = os.path.isdir("/proc/self/fd")
child = start_child(DLOG)
pipe_child = start_child(DLOG, out=subprocess.PIPE)
try:
    check("the child appends to its log (the fixture runs)", wait_growth(DLOG, 0), DLOG)
    files = native_reader(child.pid)
    check("the platform's reader sees the child's stdout and stderr on the log, and no drift",
          sorted(files) == [1, 2] and ad.replaced_log(files, DLOG) is None, f"{files}")
    check("a stdout that is a pipe is not judged at all (a daemon run by hand never starts a restart loop)",
          native_reader(pipe_child.pid) == {}, str(native_reader(pipe_child.pid)))
    lsof_before = real_lsof(child.pid)
    lsof_before = None if lsof_before is None else ad.replaced_log(ad.parse_lsof(lsof_before), DLOG) or ""

    def probe_kept_reader(script):
        got = load(script).replaced_log(native_reader(child.pid), DLOG)
        return got is None, str(got)

    control("U: the reader's inode comparison dropped (every file then reads as another)",
            mutant("if not (here and e[1] == here[0] and e[2] in (None, here[1]))]", "]"),
            lambda s: probe_kept_reader(s)[0])
    if linux:
        fake_process(child.pid, ["/usr/bin/python3", "-u", CANARY],
                     ["CLAUDE_CONFIG_DIR=" + os.path.join(ROOT, DEAF, ".claude"), "SCHED_CONFIG=" + ALT_CFG],
                     os.path.join(HOME_, "product"), STARTED)
        os.symlink(f"/proc/{child.pid}/fd", os.path.join(PROC, str(child.pid), "fd"))

    def deaf_refresh(*extra, script=SCRIPT):
        age_all()
        set_units({DUNIT: {**ACTIVE, "MainPID": str(child.pid)}})
        return refresh(*extra, script=script)

    def probe_kept(script):
        got, r = deaf_refresh(script=script)
        return got == [], f"{got} {r.stdout}{r.stderr}"

    def probe_replaced(script):
        size = os.path.getsize(DLOG)
        got, r = deaf_refresh(script=script)
        tail = open(DLOG).read()[size:]
        want = (f"DAEMON-REFRESH restarting {DUNIT}: writes to a replaced log ({DLOG}: "
                "the daemon's fd points at a deleted inode")
        return got == [f"--user restart {DUNIT}"] and want in tail, f"{got} | log tail {tail!r} | {r.stderr}"

    def deaf_status(script=SCRIPT):
        """(exit, the sched job's log_replaced, its text row) of `status deaf`."""
        set_units({DUNIT: {**ACTIVE, "MainPID": str(child.pid)}})
        rj = run(script, "status", DEAF, "--json")
        rt = run(script, "status", DEAF)
        try:
            field = json.loads(rj.stdout)["jobs"]["sched"].get("log_replaced", "<absent>")
        except (ValueError, KeyError) as e:
            field = f"<no reading: {e}>"
        row = next((ln for ln in rt.stdout.splitlines() if f"\t{DUNIT}\t" in ln), "")
        return rt.returncode, field, row

    def probe_deaf_status(script):
        rc, field, row = deaf_status(script)
        want = (f"writes to a replaced log ({DLOG}: the daemon's fd points at a deleted inode)")
        return (rc == 1 and field == want and row.startswith("DEAF  sched\t") and want in row
                and "; run refresh, which salvages what it wrote there and restarts it (" in row
                and row.endswith(f" {os.path.realpath(script)} refresh)")), f"exit {rc} | {field!r} | {row!r}"

    if linux:
        check("CONTROL: the log appended to normally: refresh keeps the unit", *probe_kept(SCRIPT))
        rc, field, row = deaf_status()
        check("CONTROL: status of the same job: log_replaced false, an ok row, exit 0",
              rc == 0 and field is False and row.startswith("ok    sched\t"), f"exit {rc} | {field!r} | {row!r}")
    size = os.path.getsize(DLOG)
    replace_like_sed(DLOG)
    time.sleep(0.5)
    check("after the replacement the child writes on, and the file at the path never grows (the deaf state)",
          not wait_growth(DLOG, os.path.getsize(DLOG), secs=1.0) and child.poll() is None, str(size))
    files = native_reader(child.pid)
    check("the platform's reader names the deleted inode",
          ad.replaced_log(files, DLOG) == "the daemon's fd points at a deleted inode", f"{files}")
    lsof_after = real_lsof(child.pid)
    if lsof_before is None:
        print("[NOT RUN] no lsof on this machine: its parser is checked on the fixture text above only")
    else:
        check("lsof's route, on a real lsof's output: no drift before the replacement, a deleted inode after",
              lsof_before == ""
              and ad.replaced_log(ad.parse_lsof(lsof_after), DLOG) == "the daemon's fd points at a deleted inode",
              f"before {lsof_before!r} after {lsof_after!r}")
    if linux:
        got, r = deaf_refresh("--dry-run")
        check("refresh --dry-run names the replaced log and restarts nothing",
              got == [] and f"DRY-RUN restart {DUNIT}: writes to a replaced log ({DLOG}: the daemon's fd points "
                            "at a deleted inode)" in r.stdout, r.stdout + r.stderr)
        check("refresh restarts it, with the reason written into the file the follower reads",
              *probe_replaced(SCRIPT))
        control("Z: refresh that does not ask whether the process writes to its log",
                mutant("drift = log_drift(pid, agent, job)\n", "drift = None\n"),
                       lambda s: probe_replaced(s)[0])
        check("status names it: log_replaced is the reason, the row is DEAF with the remedy, exit 1",
              *probe_deaf_status(SCRIPT))
        control("M: status that does not count a DEAF job in its exit code",
                mutant('down += configured and (s["active"] != "active" or isinstance(drift, str))',
                       'down += configured and s["active"] != "active"'),
                lambda s: probe_deaf_status(s)[0])
    else:
        print("[NOT RUN] refresh against the replaced log: no /proc to link the fake one to on this platform; "
              "the platform's reader is checked on the same child above")
finally:
    for c in (child, pipe_child):
        c.kill()
        c.wait()
    if pipe_child.stdout:
        pipe_child.stdout.close()
set_units({UNIT: dict(ACTIVE)})

# === 11c. refresh salvages what the daemon wrote to the replaced log =========
print("--- 11c. refresh salvages what the daemon wrote to the replaced log (a real process, real sed -i) ---")
# A real child appends every line it is sent to its log (stdout and stderr on one
# O_APPEND file, as a unit's StandardOutput=append: is), so each line exists
# because the test sent it, and a case knows exactly which lines came after the
# replacement. A case: the follower's cursor first (as --install writes it), six
# lines, a follower pass, a REAL `sed -i` over the log (a new inode at the path),
# lines written after it, which reach only the deleted file, a follower pass (the
# armed Monitor; it re-reads the new file from 0, as it always has), then
# refresh --dry-run, refresh, and two follower passes. The scenario needs /proc
# (the child's fd is read through the fake one), so it runs on Linux; the reader
# checks after it run on both platforms.
ECHO = ("import sys\n"
        "for line in sys.stdin:\n"
        "    sys.stdout.write(line)\n"
        "    sys.stdout.flush()\n")
PRE = [f"SCHED due [t-000{i}] run={i} task {i}, before the replacement" for i in range(1, 7)]
POST = [f"SCHED due [t-001{i}] run={i + 6} task {i + 6}, after the replacement" for i in range(1, 4)]
SED = ["sed", "-i", ""] if sys.platform == "darwin" else ["sed", "-i"]     # BSD sed takes a suffix
REPLACED = "the daemon's fd points at a deleted inode"


def echo_child(log):
    with open(log, "ab") as f:
        return subprocess.Popen([sys.executable, "-c", ECHO], stdin=subprocess.PIPE, stdout=f,
                                stderr=subprocess.STDOUT)


def say(child, lines, size_of):
    """Send `lines` to the child; True once the file it writes holds them
    (`size_of()` reads that file's size)."""
    data = "".join(ln + "\n" for ln in lines).encode()
    want = size_of() + len(data)
    child.stdin.write(data)
    child.stdin.flush()
    end = time.monotonic() + 10.0
    while time.monotonic() < end:
        if size_of() >= want:
            return True
        time.sleep(0.02)
    return False


def stop(child):
    child.stdin.close()
    child.kill()
    child.wait()


def _ino_of(path):
    try:
        return os.stat(path).st_ino
    except OSError:
        return None


REFRESH_LOCK = os.path.join(ENV["HOME"], ".local", "state", "agent-fleet", "daemons-refresh.lock")


def salvage_case(script, expr, post=POST, follow_after=True, again=None, lag=len(PRE), late=None,
                 hold_lock=False):
    """One daemon's log through a replacement and a refresh by `script`: what each
    step left (see the section comment). `expr` is a real `sed -i` expression, or
    a function that replaces the log itself. `lag`: the follower's pass before
    the replacement comes after only that many of the six lines (a follower
    behind, so its position cannot hide the boundary the files give). `late`:
    lines the child writes after the follower's pass that follows the
    replacement. `hold_lock`: the test holds refresh's lock during the refresh.
    With `again`, the child then writes those lines too and refresh runs a second
    time: the fake restart left it running, as a restart that failed would, so it
    still writes to the replaced file. seen["again"] is that round's record."""
    agent = os.path.basename(fresh("salv"))
    log = os.path.join(ROOT, agent, "state", "daemons", "sched.log")
    unit = f"agent-sched@{agent}.service"
    os.makedirs(os.path.dirname(log))
    seen = {"log": log, "unit": unit, "fixture": []}

    def follow():
        r = run(script, "follow", agent, "sched", "--once", "--log", log, "--unit", unit,
                "--replay-max", "100")
        return r.stdout.splitlines()

    def refresh_round(rec, delivered):
        """refresh --dry-run, refresh and two follower passes, recorded into `rec`.
        The tail is the lines past the ones the file held before, so a block that
        completes an unfinished last line still reads as the lines it added."""
        age_all()
        set_units({unit: {**ACTIVE, "MainPID": str(child.pid)}})
        with open(log, "rb") as f:
            before = f.read()
        held = None
        if hold_lock:                     # held across the dry run too: a dry run takes no lock
            os.makedirs(os.path.dirname(REFRESH_LOCK), exist_ok=True)
            held = os.open(REFRESH_LOCK, os.O_CREAT | os.O_RDWR, 0o600)
            fcntl.flock(held, fcntl.LOCK_EX)
        try:
            _, dry = refresh("--dry-run", script=script)
            with open(log, "rb") as f:
                rec["dry_wrote"] = f.read() != before
            rec["dry"] = dry.stdout + dry.stderr
            rec["restarts"], r = refresh(script=script)
        finally:
            if held is not None:
                os.close(held)
        rec["refresh"] = r.stdout + r.stderr
        with open(log, "rb") as f:
            text = f.read()
        rec.update(log=log, unit=unit, fixture=rec.get("fixture", []),
                   tail=text.decode().splitlines()[len(before.decode().splitlines()):],
                   file=text.decode().splitlines(), delivered=delivered + follow() + follow())

    set_units({unit: dict(ACTIVE)})
    follow()
    child = echo_child(log)
    try:
        fd1 = f"/proc/{child.pid}/fd/1"

        def size():
            return os.stat(fd1).st_size
        wrote = say(child, PRE[:lag], size)
        follow()
        if not (wrote and say(child, PRE[lag:], size)):
            seen["fixture"].append("the child did not write the lines before the replacement")
            return seen
        ino = os.stat(log).st_ino
        if callable(expr):
            expr(log)
            how = "the replacement"
        else:
            sed = subprocess.run(SED + [expr, log], capture_output=True, text=True)
            how = f"sed -i (exit {sed.returncode}: {sed.stderr.strip()})"
        if _ino_of(log) in (None, ino):
            seen["fixture"].append(f"{how} did not put a new file at the log path")
            return seen
        if post and not say(child, post, size):
            seen["fixture"].append("the child did not write the lines after the replacement")
            return seen
        after = follow() if follow_after else []
        if late and not say(child, late, size):
            seen["fixture"].append("the child did not write the late lines")
            return seen
        entry = os.path.join(PROC, str(child.pid))
        if os.path.isdir(entry):
            shutil.rmtree(entry)          # a pid an earlier child of this test had
        fake_process(child.pid, ["/usr/bin/python3", "-u", CANARY], ["SCHED_CONFIG=" + ALT_CFG],
                     os.path.join(HOME_, "product"), STARTED)
        os.symlink(f"/proc/{child.pid}/fd", os.path.join(entry, "fd"))
        refresh_round(seen, after)
        if again:
            seen["again"] = {"fixture": [] if say(child, again, size) else
                             ["the child did not write the lines after the first refresh"]}
            refresh_round(seen["again"], [])
        return seen
    finally:
        stop(child)


def salvage_problems(seen, lines, heard=None, why=REPLACED):
    """What is wrong with a case whose refresh must salvage exactly `lines` (None:
    the boundary is not found, nothing is salvaged, and the restart says so).
    `heard`: the lines the follower must deliver exactly once (default `lines`),
    salvaged or not. `why`: the replaced-log reason, `{log}` filled in."""
    if seen["fixture"]:
        return seen["fixture"]
    p, log, unit = [], seen["log"], seen["unit"]
    note = "; salvage: none, boundary not found" if lines is None else f"; salvage: {len(lines)} line(s)"
    lines = lines or []
    head = f"DAEMON-SALVAGE {len(lines)} line(s) the daemon wrote to the replaced log {log} before this restart"
    reason = f"writes to a replaced log ({log}: {why.format(log=log)}){note}"
    if f"DRY-RUN restart {unit}: {reason}\n" not in seen["dry"]:
        p.append(f"no `DRY-RUN restart ...{note}` line: {seen['dry']!r}")
    if seen["dry_wrote"]:
        p.append("the dry run wrote into the log")
    if seen["restarts"] != [f"--user restart {unit}"]:
        p.append(f"restart calls {seen['restarts']} ({seen['refresh']!r})")
    want = ([head] if lines else []) + lines + [f"DAEMON-REFRESH restarting {unit}: {reason}"]
    if seen["tail"] != want:
        p.append(f"refresh appended {seen['tail']!r}")
    for ln in lines:
        if seen["file"].count(ln) != 1:
            p.append(f"{ln!r} is in the log {seen['file'].count(ln)} time(s)")
    for ln in lines if heard is None else heard:
        if seen["delivered"].count(ln) != 1:
            p.append(f"the follower delivered {ln!r} {seen['delivered'].count(ln)} time(s)")
    if lines and seen["delivered"].count(head) != 1:
        p.append(f"the follower delivered the header {seen['delivered'].count(head)} time(s)")
    return p


def salvage_findings(seen, lines, again=None, heard=None, why=REPLACED):
    p = salvage_problems(seen, lines, heard, why)
    if again and not p:
        p += [f"second refresh: {x}" for x in salvage_problems(seen["again"], again)]
        p += [f"{ln!r} is in the log {seen['again']['file'].count(ln)} time(s) after the second refresh"
              for ln in lines if seen["again"]["file"].count(ln) != 1]
    return p


def probe_salvage(script, expr, lines=POST, heard=None, why=REPLACED, **kw):
    p = salvage_findings(salvage_case(script, expr, **kw), lines, kw.get("again"), heard, why)
    return not p, "; ".join(p)


def salvage_control(expr, lines=POST, heard=None, why=REPLACED, **kw):
    """A control's probe: the case's check against a mutant. A case whose fixture did
    not run is a FAILED check of its own and never the control's catch: a control
    must fail for its reason, not because its child never wrote."""
    def probe(script):
        seen = salvage_case(script, expr, **kw)
        broken = seen["fixture"] + seen.get("again", {}).get("fixture", [])
        if broken:
            check("the salvage fixture ran against a control's mutant", False, "; ".join(broken))
            return True
        return not salvage_findings(seen, lines, kw.get("again"), heard, why)
    return probe


def rotate_live(log):
    """The log moved to <log>.1 while the daemon writes to it, and an empty log
    created in its place (a rotation run against a live daemon)."""
    os.replace(log, log + ".1")
    open(log, "w").close()


def no_last_newline(log):
    """A replacement the way sed -i makes one (a new file renamed over the path)
    that leaves the copied text without its final newline."""
    with open(log, "rb") as f:
        text = f.read()
    tmp = os.path.join(os.path.dirname(log), ".rewrite")
    with open(tmp, "wb") as f:
        f.write(text.rstrip(b"\n"))
    os.replace(tmp, log)


def probe_lock(script, for_control=False):
    seen = salvage_case(script, IDENTITY, hold_lock=True)
    if seen["fixture"]:
        check("the salvage fixture ran for the lock case", False, "; ".join(seen["fixture"]))
        return for_control, "fixture"     # a failed check, and never the control's catch
    ok = (seen["restarts"] == [] and seen["tail"] == []
          and f"another refresh holds {REFRESH_LOCK}; this one does nothing" in seen["refresh"]
          and f"DRY-RUN restart {seen['unit']}: " in seen["dry"])
    return ok, f"restarts {seen['restarts']} tail {seen['tail']} out {seen['refresh']!r} dry {seen['dry']!r}"


def probe_unlockable(script, for_control=False):
    """A lock refresh can neither make nor open (its directory is a file): the run
    goes on, salvages as ever, and says it ran without the lock."""
    state = os.path.dirname(REFRESH_LOCK)
    os.makedirs(state, exist_ok=True)
    os.rename(state, state + ".aside")
    open(state, "w").close()
    try:
        seen = salvage_case(script, IDENTITY)
    finally:
        os.remove(state)
        os.rename(state + ".aside", state)
    if seen["fixture"]:
        check("the salvage fixture ran for the unlockable case", False, "; ".join(seen["fixture"]))
        return for_control, "fixture"     # a failed check, and never the control's catch
    p = salvage_problems(seen, POST)
    if not seen["fixture"] and f"refresh runs without its lock: {REFRESH_LOCK}" not in seen["refresh"]:
        p.append(f"no `runs without its lock` line: {seen['refresh']!r}")
    return not p, "; ".join(p)


def probe_rewritten(script):
    """rewritten() takes a rewrite and refuses a look-alike: a line sharing one short
    word with another, or nothing at all, is no rewrite of it."""
    m, line = load(script), PRE[0].encode()
    takes = [line.replace(b"t-0001", b"x-9991"), line.replace(b" task ", b" scheduled task "),
             b"JOB" + line[5:].replace(b"replacement", b"swap")]
    refuses = [(b"a " + b"x" * 40, b"a " + b"y" * 40), (line, b"redacted")]
    wrong = ([f"refused {b!r}" for b in takes if not m.rewritten(line, b)]
             + [f"took {b!r} for {a!r}" for a, b in refuses if m.rewritten(a, b)])
    return not wrong, "; ".join(wrong)


def probe_stale_record(script):
    """delivered_offset trusts the follower's `replaced` record only while the file
    its cursor names is the one at the path."""
    m = load(script)
    d = fresh("stale")
    os.makedirs(d)
    log = os.path.join(d, "sched.log")
    open(log, "w").close()
    here, gone = os.stat(log).st_ino, 424242

    def offset(cur_ino):
        with open(log + ".cursor", "w") as f:
            json.dump({"ino": cur_ino, "offset": 0, "replaced": {"ino": gone, "offset": 5}}, f)
        return m.delivered_offset(log, gone, 100)
    current, stale = offset(here), offset(here + 1)
    return current == 5 and stale is None, f"cursor on the file at the path: {current!r}; on another: {stale!r}"


AT_ONE = "the daemon's fd points at {log}.1, not the file at that path"
LATE = ["SCHED due [t-0031] run=12 task 12, after the follower drained the rotated log"]


IDENTITY = r"s/^$//"                                   # rewrites the file, changes no byte
SAME_LEN = r"s/t-000\([0-9]\)/x-999\1/"                # ids renamed to equal-length ids
LONGER = r"s/t-000\([0-9]\)/renamed-task-\1/"          # ids renamed to longer ones
WORDIER = r"s/ task / scheduled task /"                # one more word in every line
BOTH_ENDS = r"s/^SCHED/JOB/;s/replacement$/swap/"      # two edits, at the start and the end
AGAIN = ["SCHED due [t-0021] run=10 task 10, after the first refresh",
         "SCHED alert [t-0022] run=11 task 11, after the first refresh"]
if linux:
    check("sed -i that changes no byte: only the lines written after it are salvaged, once, under "
          "the header, and the follower delivers them once", *probe_salvage(SCRIPT, IDENTITY))
    check("sed -i renaming ids to equal-length ids: the same", *probe_salvage(SCRIPT, SAME_LEN))
    check("sed -i renaming ids to longer ids (every line changes length): the same",
          *probe_salvage(SCRIPT, LONGER))
    check("sed -i adding a word to every line (the words no longer line up; the unchanged start and "
          "end do): the same", *probe_salvage(SCRIPT, WORDIER))
    check("sed -i editing both ends of every line (start and end both changed; the words in between "
          "line up): the same", *probe_salvage(SCRIPT, BOTH_ENDS))
    check("sed -i deleting a line before the last: the same (the new file's last line is found)",
          *probe_salvage(SCRIPT, "/run=3 /d"))
    check("sed -i deleting every line (an empty new file), the follower having seen the replacement: "
          "the same, from where the follower left the old file", *probe_salvage(SCRIPT, "d"))
    check("...and with no follower pass since the replacement (its cursor still names the old file)",
          *probe_salvage(SCRIPT, "d", follow_after=False))
    check("sed -i rewriting every line beyond recognition: nothing salvaged, and the restart says "
          "`salvage: none, boundary not found`", *probe_salvage(SCRIPT, r"s/.*/redacted/", lines=None))
    check("CONTROL: nothing written after the replacement: 0 lines salvaged, no header",
          *probe_salvage(SCRIPT, IDENTITY, lines=[], post=[]))
    check("a second refresh while the daemon still writes to the deleted file (its restart did not "
          "happen) salvages only the lines written since, and the first ones stay once",
          *probe_salvage(SCRIPT, SAME_LEN, again=AGAIN))
    # The follower behind (its last pass after 2 of the 6 lines): its position is
    # earlier than the boundary, so the boundary the FILES give is what is measured.
    check("the follower behind, ids renamed (the last line rewritten): the new file's lines are "
          "matched as a rewritten prefix, and only the later lines are salvaged",
          *probe_salvage(SCRIPT, SAME_LEN, lag=2))
    check("the follower behind, a line deleted: the new file's last line is found in the old one, "
          "and only the later lines are salvaged", *probe_salvage(SCRIPT, "/run=3 /d", lag=2))
    check("the follower behind, every line deleted: the lines no follower delivered come back, once "
          "(they were never heard), then the later ones", *probe_salvage(SCRIPT, "d", lines=PRE[2:] + POST, lag=2))
    check("a copy without its final newline: the block starts on a line of its own",
          *probe_salvage(SCRIPT, no_last_newline))
    check("the log moved to <log>.1 under a live daemon, no follower pass since: the follower drains "
          "<log>.1 itself, so 0 lines are salvaged and each is delivered once",
          *probe_salvage(SCRIPT, rotate_live, lines=[], heard=POST, why=AT_ONE, follow_after=False))
    check("...and lines the daemon wrote there after the follower drained it are salvaged, once",
          *probe_salvage(SCRIPT, rotate_live, lines=LATE, heard=POST + LATE, why=AT_ONE, late=LATE))
    check("refresh while another refresh holds the lock: it says so, restarts nothing and writes nothing",
          *probe_lock(SCRIPT))
    control("SL: refresh without its lock",
            mutant("    if not dry:\n        # One refresh at a time", "    if False:\n        # One refresh at a time"),
            lambda s: probe_lock(s, for_control=True)[0])
    control("SY: the dry run takes the lock too",
            mutant("    if not dry:\n        # One refresh at a time", "    if True:\n        # One refresh at a time"),
            lambda s: probe_lock(s, for_control=True)[0])
    check("a lock refresh cannot make: it runs without it, salvages as ever, and says so",
          *probe_unlockable(SCRIPT))
    control("SU: a lock refresh cannot make stops the run",
            mutant("# flock needs no write access\n            except OSError as e:",
                   "# flock needs no write access\n            except ZeroDivisionError as e:"),
            lambda s: probe_unlockable(s, for_control=True)[0])
    control("SR1: the boundary's rule 1 (the new file's last line) dropped",
            mutant("if n and o.count(n[-1]) == 1:\n        k = o.index(n[-1]) + 1\n    elif",
                   "if False:\n        k = o.index(n[-1]) + 1\n    elif"),
            salvage_control("/run=3 /d", lag=2))
    control("SR2: the boundary's rule 2 (a rewritten prefix) giving 0",
            mutant("        k = len(n)\n", "        k = 0\n"),
            salvage_control(SAME_LEN, lag=2))
    control("SN: the block appended with no newline before it",
            mutant('if end and os.pread(fd, 1, end - 1) != b"\\n":', "if False:"),
            salvage_control(no_last_newline))
    control("S1: <log>.1 that the follower still names salvaged as if it were gone",
            mutant('return size if _ino(log + ".1") == ino else cur["offset"]', 'return cur["offset"]'),
            salvage_control(rotate_live, lines=[], heard=POST, why=AT_ONE, follow_after=False))
    control("SV: the salvaged lines counted in the note but never written into the log",
            mutant("text, salvaged = salvage(pid, log_path(agent, job))",
                   "_, salvaged = salvage(pid, log_path(agent, job))"),
            salvage_control(IDENTITY))
    control("SA: the boundary ignored, the whole replaced file salvaged",
            mutant("return o[max(k, seen or 0):], None", "return o, None"),
            salvage_control(IDENTITY))
    control("SC: the follower keeps no record of the file it left at a replacement",
            mutant('self.cur = {"ino": st.st_ino, "offset": 0,\n'
                   '                        "replaced": {"ino": ino, "offset": self.cur["offset"]}}',
                   'self.cur = {"ino": st.st_ino, "offset": 0}'),
            salvage_control("d"))
    control("SH: rewritten() without its unchanged-start-and-end rule",
            mutant("    if 4 * (head + min(_common(a, b, True), min(len(a), len(b)) - head)) >= len(a) + len(b):\n"
                   "        return True\n", ""),
            salvage_control(WORDIER))
    control("SW: rewritten() without its word rule",
            mutant("return len(wa) == len(wb) > 0 and 4 * sum(len(x) for x, y in zip(wa, wb) if x == y) >= len(a) + len(b)",
                   "return False"),
            salvage_control(BOTH_ENDS))
    control("SD: refresh's own lines kept in the comparison",
            mutant("return [ln for ln in lines if not ln.startswith(SALVAGE_OWN)]", "return lines"),
            salvage_control(SAME_LEN, again=AGAIN))
else:
    print("[NOT RUN] the salvage scenario: no /proc to link the fake one to on this platform; the reader "
          "checks below run here")

# The reader, on both platforms: a moved log is read through the daemon's fd or by
# the name lsof reports; a deleted one through /proc only. Linux also drives the
# macOS branch (no procfs: the name lsof printed) on a real lsof's output.


def native_read(pid, log):
    """(data, why) from the platform's own reader, as refresh outside this test
    reads it (no fake /proc): the first drifted descriptor of `pid` for `log`."""
    saved = os.environ.pop("AGENT_DAEMONS_PROC")
    try:
        drift = ad.drifted(ad.stdio_files(pid), log)
        return ad.read_replaced(pid, *drift[0], ad.svc()._procfs()) if drift else (None, "no drift seen")
    finally:
        os.environ["AGENT_DAEMONS_PROC"] = saved


def reader_case(replace):
    """{native, mac}: (data, why) read from a child whose log `replace(log)`
    replaced, by the platform's reader and (with lsof) by the macOS branch."""
    log = os.path.join(fresh("reader"), "sched.log")
    os.makedirs(os.path.dirname(log))
    child = echo_child(log)
    try:
        out = {"fixture": say(child, PRE, lambda: os.path.getsize(log)), "log": log,
               "ino": os.stat(log).st_ino}
        replace(log)
        out["native"] = native_read(child.pid, log)
        lsof = real_lsof(child.pid)
        if lsof is not None:
            drift = ad.drifted(ad.parse_lsof(lsof), log)
            out["mac"] = ad.read_replaced(child.pid, *drift[0], None) if drift else (None, "no drift in lsof's output")
        return out
    finally:
        stop(child)


WROTE = "".join(ln + "\n" for ln in PRE).encode()
moved = reader_case(lambda p: os.replace(p, p + ".moved"))
check("the reader fixture's child wrote its lines", moved["fixture"])
check("a moved log: the platform's reader returns what the daemon wrote", moved["native"][0] == WROTE,
      str(moved["native"]))
if "mac" not in moved:
    print("[NOT RUN] no lsof on this machine: the reader's macOS branch is checked on macOS only")
else:
    check("...and so does the macOS branch, by the name lsof reports", moved["mac"][0] == WROTE, str(moved["mac"]))
# SAME_LEN, not IDENTITY: the copy at the path then differs from what the daemon
# wrote, so a reader that opened the path instead of the daemon's file cannot pass.
sedded = reader_case(lambda p: subprocess.run(SED + [SAME_LEN, p], check=True))
check("the reader fixture's child wrote its lines (sed -i case)", sedded["fixture"])


def probe_inode_checked(script):
    """A name that now holds another file (the sed copy at the path) is refused."""
    got = load(script).read_replaced(0, 1, (sedded["log"], sedded["ino"], None, None), None)
    return got[0] is None and "no longer the file" in got[1], str(got)


check("rewritten() takes an id rename, an added word and two edited ends, and refuses a line that "
      "shares only a short word, or nothing", *probe_rewritten(SCRIPT))
control("SX: the word rule counting words instead of the characters they hold",
        mutant("4 * sum(len(x) for x, y in zip(wa, wb) if x == y) >= len(a) + len(b)",
               "2 * sum(x == y for x, y in zip(wa, wb)) >= len(wa)"),
        lambda s: probe_rewritten(s)[0])
check("the follower's record of a replaced file counts only while its cursor's file is the one at "
      "the path (an older record never meets a reused inode number)", *probe_stale_record(SCRIPT))
control("SG: the record trusted whatever file the cursor names",
        mutant('\n            and cur.get("ino") is not None and _ino(log) == cur["ino"]):', "):"),
        lambda s: probe_stale_record(s)[0])
check("a name lsof reported that now holds another file is refused, never read as the daemon's",
      *probe_inode_checked(SCRIPT))
control("SI: the reader's inode check dropped",
        mutant('if os.fstat(f.fileno()).st_ino != ino:\n                return None, f"{path} is no longer',
               'if False:\n                return None, f"{path} is no longer'),
        lambda s: probe_inode_checked(s)[0])
if linux:
    check("a log replaced by sed -i: Linux reads the deleted file through /proc", sedded["native"][0] == WROTE,
          str(sedded["native"]))
else:
    check("a log replaced by sed -i: macOS cannot read the deleted file, and says why",
          sedded["native"][0] is None and "deleted" in sedded["native"][1], str(sedded["native"]))
if "mac" in sedded:
    check("...where the macOS branch (no /proc) refuses it, naming the deleted file",
          sedded["mac"][0] is None and "deleted" in sedded["mac"][1], str(sedded["mac"]))
set_units({UNIT: dict(ACTIVE)})

# === R. render-units =========================================================
print("--- R. render-units ---")
r = run(SCRIPT, "render-units", "--units", "refresh", "--list")
check("--units refresh --list prints the refresh service and timer",
      r.stdout.split() == ["agent-daemons-refresh.service", "agent-daemons-refresh.timer"],
      r.stdout + r.stderr)
ALL = ["agent-daemons-refresh.service", "agent-daemons-refresh.timer",
       "agent-sched@.service", "agent-slack-watch@.service"]
r = run(SCRIPT, "render-units", "--units", "all", "--list")
check("--units all --list adds the scheduler template and one per working transport",
      r.stdout.split() == ALL, r.stdout + r.stderr)


def probe_link_replaced(script):
    out, target = fresh("linkdir"), os.path.join(fresh("linktarget"), "refresh.service")
    os.makedirs(out)
    os.makedirs(os.path.dirname(target))
    with open(target, "w") as f:
        f.write("ORIGINAL\n")
    dest = os.path.join(out, "agent-daemons-refresh.service")
    os.symlink(target, dest)
    r = run(script, "render-units", "--units", "refresh", "--out", out)
    problems = [] if r.returncode == 0 else [f"exit {r.returncode}: {r.stderr.strip()}"]
    if open(target).read() != "ORIGINAL\n":
        problems.append("the link's target was overwritten")
    if os.path.islink(dest):
        problems.append("the destination is still a link")
    elif not open(dest).read().startswith("# Rendered by fleet install from "
                                          "systemd/agent-daemons-refresh.service.in at "):
        problems.append("the destination is not the rendered unit")
    if f"replacing a link to {target}" not in r.stdout:
        problems.append("the replaced link is not reported")
    return not problems, "; ".join(problems)


check("rendering over a symlink replaces the link and leaves its target byte-identical",
      *probe_link_replaced(SCRIPT))
control("L: the unit written through the path instead of renamed over it",
        mutant("os.replace(tmp, path)",
               'open(path, "wb").write(open(tmp, "rb").read()); os.unlink(tmp)'),
        lambda s: probe_link_replaced(s)[0])

out = fresh("render")
r1, files1 = render_all(SCRIPT, out=out)
r2, files2 = render_all(SCRIPT, out=out)
check("a second render into the same directory prints `nothing changed` and changes nothing",
      r1.returncode == 0 and len(r1.stdout.splitlines()) == 4
      and r2.returncode == 0 and r2.stdout.strip() == "nothing changed" and files1 == files2,
      r1.stdout + r2.stdout + r2.stderr)
check("the refresh service runs this tree's agent-daemons.py",
      f"ExecStart=/usr/bin/python3 {FLEET}/systemd/agent-daemons.py refresh"
      in files1.get("agent-daemons-refresh.service", "").splitlines())


# The deliberate changes to the Linux units since the references were taken (the
# golden render of v1.0.3, and the units copied from a running host), each
# applied to a reference before it is compared: insert these lines after the
# anchor line. An anchor that does not occur exactly once is a failure, so the
# list can hide no change it does not name, and a delta the templates lost reds
# the comparison. A unit's deltas apply in order, so an anchor may be a line an
# earlier delta inserted. HOST_TOKEN stands for the host settings file of the
# render each comparison makes (fixture_lines and golden_render put it back).
NO_BYTECODE = ["# No bytecode: the fleet checkout is code the agents user may not write.",
               "Environment=PYTHONDONTWRITEBYTECODE=1"]
HOST_TOKEN = "<host-config>"
HOST_CONFIG_JOB = ["# The host settings file fleet install writes (render-units --host-config), so",
                   "# the daemon reads it whatever HOME is. A path, so never set in the env file below.",
                   f"Environment=FLEET_HOST_CONFIG={HOST_TOKEN}"]
HOST_CONFIG_REFRESH = ["# The host settings file fleet install writes (render-units --host-config):",
                       "# refresh reads it first, and exits 3 with one line naming it when it is missing.",
                       f"Environment=FLEET_HOST_CONFIG={HOST_TOKEN}"]
UNIT_DELTAS = {
    "agent-sched@.service": [("Environment=PYTHONUNBUFFERED=1", NO_BYTECODE),
                             ("Environment=PYTHONDONTWRITEBYTECODE=1", HOST_CONFIG_JOB)],
    "agent-slack-watch@.service": [("Environment=PYTHONUNBUFFERED=1", NO_BYTECODE),
                                   ("Environment=PYTHONDONTWRITEBYTECODE=1", HOST_CONFIG_JOB)],
    "agent-daemons-refresh.service": [("Type=oneshot", NO_BYTECODE),
                                      ("Environment=PYTHONDONTWRITEBYTECODE=1", HOST_CONFIG_REFRESH)],
}


def with_deltas(name, lines):
    """`lines` of the reference unit `name` with UNIT_DELTAS applied; None when an
    anchor does not occur exactly once."""
    out = list(lines)
    for anchor, new in UNIT_DELTAS.get(name, []):
        at = [i for i, l in enumerate(out) if l == anchor]
        if len(at) != 1:
            return None
        out[at[0] + 1:at[0] + 1] = new
    return out


# The host's unit names the agents root through the specifier %h/agents (a user
# unit's %h is its manager's home) on these lines, in this order, and the render
# writes the literal agents_root from host.json there: a deliberate change,
# applied to the reference like UNIT_DELTAS. The fixture keeps %h verbatim and
# this list names every line that carries it, so the specifier-to-literal class
# shows up here, named, instead of vanishing into the fixture's de-identification;
# a `%h` on any other line, or one missing here, fails the comparison.
SPECIFIER_LINES = ["WorkingDirectory", "Environment", "Environment", "EnvironmentFile", "ExecStartPre",
                   "ExecStart", "StandardOutput", "StandardError"]


def fixture_lines(name, fix=FIX):
    """(lines, problem): today's unit (the fixture), its #fixture header dropped, our
    agents root in place of the synthetic one and of the %h/agents SPECIFIER_LINES
    names, the deliberate deltas applied with render_all's host file."""
    raw = [l for l in open(os.path.join(fix, name)).read().splitlines() if not l.startswith("#fixture")]
    spec = [l.split("=", 1)[0] for l in raw if "%h" in l]
    if spec != SPECIFIER_LINES:
        return None, f"the {name} fixture's %h lines are {spec}, not SPECIFIER_LINES {SPECIFIER_LINES}"
    lines = with_deltas(name, [l.replace("%h/agents", ROOT).replace("/srv/agents", ROOT) for l in raw])
    if lines is None:
        return None, f"a UNIT_DELTAS anchor does not occur exactly once in the {name} fixture"
    return [l.replace(HOST_TOKEN, HOST) for l in lines], ""


def same_but_script_dir(a, b):
    """Two Exec lines that are equal except for the directory their script sits in."""
    ta, tb = a.split(), b.split()
    return len(ta) == len(tb) and all(
        x == y or (x.endswith(".py") and x.split("/")[-2:] == y.split("/")[-2:])
        for x, y in zip(ta, tb))


def probe_vs_today(script, unit, template, fix=FIX):
    r, files = render_all(script)
    (want, problem), got = fixture_lines(unit, fix), files.get(unit, "").splitlines()
    if want is None:
        return False, problem
    header = re.compile(rf"# Rendered by fleet install from systemd/{re.escape(template)} at "
                        rf"\S+\. Edit the template, not this file\.")
    only_want, only_got = [], []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=want, b=got, autojunk=False).get_opcodes():
        if op != "equal":
            only_want += want[i1:i2]
            only_got += got[j1:j2]
    problems = [] if r.returncode == 0 else [f"exit {r.returncode}: {r.stderr.strip()}"]
    if not got or not header.fullmatch(got[0]):
        problems.append(f"the first line is not the rendered-by header: {got[:1]}")
    only_got = [l for l in only_got if not header.fullmatch(l)]
    keys = ["Documentation", "ExecStart", "ExecStartPre"]
    if (sorted(l.split("=", 1)[0] for l in only_want) != keys
            or sorted(l.split("=", 1)[0] for l in only_got) != keys):
        problems.append("lines other than Documentation=, ExecStartPre= and ExecStart= differ")
    else:
        for k in ("ExecStartPre=", "ExecStart="):
            a = next(l for l in only_want if l.startswith(k))
            b = next(l for l in only_got if l.startswith(k))
            if not same_but_script_dir(a, b):
                problems.append(f"{k} differs in more than its script's directory")
        if not re.fullmatch(r"Documentation=file:///\S+/systemd/README\.md",
                            next(l for l in only_got if l.startswith("Documentation="))):
            problems.append("Documentation= does not name the tree's systemd/README.md")
    if problems:
        problems.append("diff:\n" + "\n".join(difflib.unified_diff(want, got, "today", "rendered",
                                                                    lineterm="")))
    return not problems, "; ".join(problems)


check("the rendered agent-slack-watch@.service is today's unit except the rendered-by header, "
      "Documentation=, the ExecStartPre=/ExecStart= script paths, and the literal agents root on the "
      "lines where today's unit has %h/agents (SPECIFIER_LINES) (by diff)",
      *probe_vs_today(SCRIPT, "agent-slack-watch@.service", "agent-watch@.service.in"))
check("...and so is the rendered agent-sched@.service",
      *probe_vs_today(SCRIPT, "agent-sched@.service", "agent-sched@.service.in"))
control("T: RestartPreventExitStatus=0 deleted from the watch template",
        tree(template_edits={"agent-watch@.service.in": [("RestartPreventExitStatus=0\n", "")]}),
        lambda s: probe_vs_today(s, "agent-slack-watch@.service", "agent-watch@.service.in")[0])
control("I: the scheduler template names the agents root as %h/agents on one line",
        tree(template_edits={"agent-sched@.service.in": [("WorkingDirectory=@AGENTS_ROOT@/",
                                                          "WorkingDirectory=%h/agents/")]}),
        lambda s: probe_vs_today(s, "agent-sched@.service", "agent-sched@.service.in")[0])


def deidentified_fixture():
    """A copy of the unit fixtures with every %h/agents rewritten to /srv/agents:
    the de-identification that once hid the specifier-to-literal class."""
    d = fresh("fixture-deid")
    os.makedirs(d)
    for n in ("agent-sched@.service", "agent-slack-watch@.service"):
        with open(os.path.join(FIX, n)) as src, open(os.path.join(d, n), "w") as dst:
            dst.write(src.read().replace("%h/agents", "/srv/agents"))
    return d


_deid = deidentified_fixture()
control("O: the scheduler fixture's %h/agents de-identified to /srv/agents again", SCRIPT,
        lambda s: probe_vs_today(s, "agent-sched@.service", "agent-sched@.service.in", fix=_deid)[0])

bad = tree(template_edits={"agent-daemons-refresh.service.in": [("[Service]", "[Service]\n@NOPE@")]})
out = fresh("render")
r = run(bad, "render-units", "--units", "refresh", "--out", out)
check("a template placeholder with no value is refused (exit 3) and nothing is written",
      r.returncode == 3 and "@NOPE@" in r.stderr and not os.path.exists(out), r.stderr)
os.makedirs(os.path.join(ROOT, "bob", "other", ".claude"))
with open(os.path.join(ROOT, "bob", "other", ".claude", "fleet.json"), "w") as f:
    f.write("{}\n")
r = run(SCRIPT, "render-units", "--units", "all", "--out", fresh("render"))
check("agent homes whose install checkouts have different names are refused (exit 3), "
      "naming both", r.returncode == 3 and "product" in r.stderr and "other" in r.stderr,
      r.stderr)
r = run(SCRIPT, "render-units", "--units", "refresh", "--out", fresh("render"))
check("...where --units refresh, which needs no checkout name, still renders",
      r.returncode == 0, r.stderr)
shutil.rmtree(os.path.join(ROOT, "bob"))

# === A. run through a symlink ================================================
print("--- A. run through a link from outside the tree ---")


def probe_via_link(script):
    link = os.path.join(fresh("retired-copy"), "agent-daemons.py")
    os.makedirs(os.path.dirname(link))
    os.symlink(script, link)
    r = run(link, "render-units", "--units", "all", "--list")
    return r.returncode == 0 and r.stdout.split() == ALL, f"{r.returncode} {r.stdout}{r.stderr}"


check("invoked through a symlink in another directory it still finds its lib/ and templates",
      *probe_via_link(SCRIPT))
control("A: the fleet tree found through abspath",
        mutant("HERE = os.path.dirname(os.path.realpath(__file__))",
               "HERE = os.path.dirname(os.path.abspath(__file__))"),
        lambda s: probe_via_link(s)[0])

# === 12. install =============================================================
print("--- 12. install (fake systemctl) ---")
open(CALLS, "w").close()
r = run(SCRIPT, "--install", "fake")
check("install refuses (exit 2) while the units are not rendered, naming the fix, and "
      "calls nothing", r.returncode == 2 and "fleet install --units all" in r.stderr
      and calls() == [], f"{r.returncode} {r.stderr} {calls()}")
r = run(SCRIPT, "render-units", "--units", "all", "--out", UNITDIR)
open(CALLS, "w").close()
r = run(SCRIPT, "--install", "fake")
c = calls()
check("install reloads and enables the timer, and links nothing",
      "--user daemon-reload" in c and "--user enable --now agent-daemons-refresh.timer" in c
      and not any(x.startswith("--user link") for x in c), str(c))
check("install enables the job whose config exists", f"--user enable --now {UNIT}" in c, str(c))
check("...and SKIPS the job whose config is missing, saying so",
      f"--user enable --now {WUNIT}" not in c and f"SKIPPED {WUNIT}" in r.stdout, r.stdout)
r = run(SCRIPT, "--install", "nobody")
check("install refuses an agent with no home",
      r.returncode == 2 and "REFUSED" in r.stderr, r.stderr)

# === 13. the rendered units themselves =======================================
print("--- 13. unit files ---")
for job, env_line in (("sched", f"SCHED_CONFIG={ROOT}/%i/config/scheduler.json"),
                      ("slack-watch", f"SLACK_WATCH_CONFIG={ROOT}/%i/config/slack-watch.json")):
    u = open(os.path.join(UNITDIR, f"agent-{job}@.service")).read()
    check(f"agent-{job}@ sets CLAUDE_CONFIG_DIR and its config IN the unit",
          f"Environment=CLAUDE_CONFIG_DIR={ROOT}/%i/.claude" in u
          and f"Environment={env_line}" in u)
    check(f"agent-{job}@ restarts always but never retries a GUARD exit 0",
          "Restart=always" in u and "RestartPreventExitStatus=0" in u
          and "StartLimitIntervalSec=0" in u and "RestartSteps=" in u)
    check(f"agent-{job}@ logs to the path the follower reads",
          f"append:{ROOT}/%i/state/daemons/{job}.log" in u)
    check(f"agent-{job}@ rotates with this tree's agent-daemons.py",
          f"ExecStartPre=/usr/bin/python3 {FLEET}/systemd/agent-daemons.py rotate " in u)


def probe_no_bytecode(script):
    """Every unit and plist render-units writes, both backends, sets
    PYTHONDONTWRITEBYTECODE=1: the checkout is code the agents user may not write."""
    problems = []
    _, files = render_all(script)
    for n in ("agent-daemons-refresh.service", "agent-sched@.service", "agent-slack-watch@.service"):
        if "Environment=PYTHONDONTWRITEBYTECODE=1" not in files.get(n, "").splitlines():
            problems.append(n)
    for t in ("agent-sched.plist.in", "agent-watch.plist.in", "agent-daemons-refresh.plist.in"):
        text = open(os.path.join(os.path.dirname(script), t)).read()
        if "<key>PYTHONDONTWRITEBYTECODE</key>\n    <string>1</string>" not in text:
            problems.append(t)
    return not problems, f"no PYTHONDONTWRITEBYTECODE=1 in: {problems}"


check("every rendered unit (refresh, scheduler, watcher) and every plist template sets "
      "PYTHONDONTWRITEBYTECODE=1", *probe_no_bytecode(SCRIPT))
control("B: PYTHONDONTWRITEBYTECODE deleted from the watch template",
        tree(template_edits={"agent-watch@.service.in": [("Environment=PYTHONDONTWRITEBYTECODE=1\n", "")]}),
        lambda s: probe_no_bytecode(s)[0])

HOST2 = os.path.join(TMP, "host-second.json")
shutil.copy(HOST, HOST2)
HOST_UNITS = ("agent-daemons-refresh.service", "agent-sched@.service", "agent-slack-watch@.service")


def probe_host_config(script):
    """Every systemd unit render-units writes names, in exactly one
    Environment=FLEET_HOST_CONFIG= line, the host settings file of THAT render:
    two renders from two host files must give two values, so a constant fails.
    A render that wrote nothing has no such line and fails too."""
    problems = []
    for host in (HOST, HOST2):
        r, files = render_all(script, env={**ENV, "FLEET_HOST_CONFIG": host})
        if r.returncode != 0:
            problems.append(f"render with {host}: exit {r.returncode}: {r.stderr.strip()}")
        for n in HOST_UNITS:
            got = [l for l in files.get(n, "").splitlines() if l.startswith("Environment=FLEET_HOST_CONFIG=")]
            if got != [f"Environment=FLEET_HOST_CONFIG={host}"]:
                problems.append(f"{n} rendered with {host}: {got}")
    return not problems, "; ".join(problems)


check("every rendered unit (refresh, scheduler, watcher) names the host settings file the render "
      "read, whichever file that was", *probe_host_config(SCRIPT))
control("C: FLEET_HOST_CONFIG deleted from the refresh service template",
        tree(template_edits={"agent-daemons-refresh.service.in": [("Environment=FLEET_HOST_CONFIG=@HOST_CONFIG@\n", "")]}),
        lambda s: probe_host_config(s)[0])

# === G. Linux units are v1.0.3's, byte for byte ==============================
print("--- G. render-units under systemd: byte-identical to v1.0.3 ---")
GOLDEN = os.path.join(FLEET, "tests", "fixtures", "systemd", "golden-v1.0.3")


def golden_render(script_text=None):
    """render-units --units all of `script_text` (default: this tree's script) in a
    tree laid out as the golden fixture was made (README.md there): the registry
    inside the tree, one agent home whose checkout is `product`. Paths and the tag
    normalized as the fixture is. Returns ({name: text}, problems)."""
    g = fresh("golden")
    t, agents = os.path.join(g, "fleet"), os.path.join(g, "agents")
    os.makedirs(os.path.join(t, "systemd"))
    os.symlink(os.path.join(FLEET, "lib"), os.path.join(t, "lib"))
    for name in TEMPLATES:
        shutil.copy(os.path.join(HERE, name), os.path.join(t, "systemd", name))
    with open(os.path.join(t, "systemd", "agent-daemons.py"), "w") as f:
        f.write(open(SCRIPT).read() if script_text is None else script_text)
    for d in os.listdir(REGISTRY):
        os.makedirs(os.path.join(t, ".claude", "skills", d))
        shutil.copy(os.path.join(REGISTRY, d, "transport.json"), os.path.join(t, ".claude", "skills", d))
    os.makedirs(os.path.join(agents, "ada", "product", ".claude"))
    with open(os.path.join(agents, "ada", "product", ".claude", "fleet.json"), "w") as f:
        f.write("{}\n")
    host = os.path.join(g, "host.json")
    with open(host, "w") as f:
        json.dump({"schema": 1, "agents_root": agents, "fleet_checkout": t,
                   "claims_dir": os.path.join(agents, "claims")}, f)
    out = os.path.join(g, "out")
    r = run(os.path.join(t, "systemd", "agent-daemons.py"), "render-units", "--units", "all", "--out", out,
            env={**ENV, "FLEET_HOST_CONFIG": host, "FLEET_TRANSPORTS_DIR": os.path.join(t, ".claude", "skills")})
    if r.returncode != 0:
        return {}, [f"exit {r.returncode}: {r.stderr.strip()}"]
    tag = re.compile(r"(# Rendered by fleet install from systemd/\S+ at )\S+(\. Edit the template)")

    def norm(text):
        # realpath first: the script names its tree through realpath, and on macOS
        # the temp directory /var/folders is /private/var/folders.
        for path, token in ((os.path.realpath(host), HOST_TOKEN), (host, HOST_TOKEN),
                            (os.path.realpath(t), "<fleet>"), (t, "<fleet>"),
                            (os.path.realpath(agents), "<agents-root>"), (agents, "<agents-root>")):
            text = text.replace(path, token)
        return tag.sub(r"\1<tag>\2", text)
    return {n: norm(open(os.path.join(out, n)).read()) for n in sorted(os.listdir(out))}, []


def probe_golden(script_text=None):
    got, problems = golden_render(script_text)
    want = {}
    for n in sorted(os.listdir(GOLDEN)):
        if n == "README.md":
            continue
        lines = with_deltas(n, open(os.path.join(GOLDEN, n)).read().split("\n"))
        if lines is None:
            problems.append(f"a UNIT_DELTAS anchor does not occur exactly once in the golden {n}")
        else:
            want[n] = "\n".join(lines)
    if len(want) != 4:
        problems.append(f"the golden fixture holds {sorted(want)}, not the four units")
    if sorted(got) != sorted(want):
        problems.append(f"rendered {sorted(got)} != golden {sorted(want)}")
    for n in sorted(set(got) & set(want)):
        if got[n] != want[n]:
            problems.append(f"{n} differs:\n" + "\n".join(difflib.unified_diff(
                want[n].splitlines(), got[n].splitlines(), "v1.0.3", "now", lineterm="")))
    return not problems, "; ".join(problems)


check("render-units --units all under systemd writes v1.0.3's four units, byte for byte, but "
      "for the deltas UNIT_DELTAS names (paths and tag normalized)", *probe_golden())
_src = open(SCRIPT).read()
_old = 'PYTHON = "/usr/bin/python3"   '
control("G: the systemd interpreter default changed to the launchd one",
        _src.replace(_old, 'PYTHON = "/opt/homebrew/bin/python3"   ') if _src.count(_old) == 1 else None,
        lambda s: probe_golden(s)[0])

# === E. the exec shim =========================================================
print("--- E. exec: rotate, the log on stdout and stderr, the env file, the same pid ---")
TARGET = os.path.join(TMP, "shim-target.py")
with open(TARGET, "w") as f:
    f.write("import os, sys\nprint('pid', os.getpid())\nprint('tune', os.environ.get('TUNE'))\n"
            "print('quoted', os.environ.get('Q'))\nprint('kept', os.environ.get('KEPT'))\n"
            "print('err-line', file=sys.stderr)\nsys.exit(int(os.environ.get('RC', '0')))\n")


def nolib_tree(script_text=None):
    """A tree holding only systemd/agent-daemons.py: no lib/, no fleetlib."""
    d = fresh("nolib")
    os.makedirs(os.path.join(d, "systemd"))
    p = os.path.join(d, "systemd", "agent-daemons.py")
    with open(p, "w") as f:
        f.write(open(SCRIPT).read() if script_text is None else script_text)
    return p


def probe_shim(script):
    d = fresh("shim")
    os.makedirs(d)
    log, envf = os.path.join(d, "job.log"), os.path.join(d, "job.env")
    with open(log, "w") as f:
        f.write("x" * 50 + "\n")
    with open(envf, "w") as f:
        f.write("# tunables\n\nTUNE=7\n; also a comment\nQ='a b'\n")
    env = {**ENV, "TUNE": "1", "KEPT": "yes", "RC": "5", "FLEET_HOST_CONFIG": os.path.join(TMP, "absent.json")}
    p = subprocess.Popen([sys.executable, script, "exec", "--log", log, "--env-file", envf, "--max-bytes", "10",
                          "--", sys.executable, "-u", TARGET], env=env, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True)
    out, err = p.communicate(timeout=60)
    text = open(log).read() if os.path.exists(log) else ""
    problems = []
    # 5: no exit this script gives itself (2 usage, 3 fault, 127 cannot run), so
    # only the exec'd target can produce it.
    if p.returncode != 5:
        problems.append(f"exit {p.returncode}, not the target's 5 ({err.strip()})")
    if f"pid {p.pid}" not in text.splitlines():
        problems.append("the target did not run as the shim's own pid")
    for line in ("tune 7", "quoted a b", "kept yes", "err-line"):
        if line not in text.splitlines():
            problems.append(f"no line {line!r} in the log")
    if not os.path.exists(log + ".1") or "x" * 50 not in open(log + ".1").read():
        problems.append("the oversized log was not rotated to .1 first")
    if out or err:
        problems.append(f"output escaped the log: {out!r} {err!r}")
    return not problems, "; ".join(problems) + f" | log: {text!r}"


check("exec from a tree with NO lib/: rotates, sends stdout and stderr to the log, applies the "
      "env file over the environment, and becomes the target (same pid, its exit code)",
      *probe_shim(nolib_tree()))
_old = '    log = known["--log"]\n    rotate('
control("E: exec imports fleetlib before it execs",
        nolib_tree(_src.replace(_old, '    log = known["--log"]\n    fleetlib()\n    rotate('))
        if _src.count(_old) == 1 else None,
        lambda s: probe_shim(s)[0])
d = fresh("shim-missing")
os.makedirs(d)
r = run(nolib_tree(), "exec", "--log", os.path.join(d, "l.log"), "--", os.path.join(d, "no-such-python"))
check("a target that cannot run is exit 127, said in the log",
      r.returncode == 127 and "cannot run" in open(os.path.join(d, "l.log")).read(), f"{r.returncode}")
r = run(nolib_tree(), "exec", "--log", os.path.join(d, "l.log"), sys.executable)
check("exec with no `--` is a usage refusal (exit 2)", r.returncode == 2 and "usage" in r.stderr, r.stderr)

# === LD. the launchd backend, against the fake launchctl ======================
print("--- LD. launchd: plists, install, follow, refresh, status, uninstall ---")
PFX = "com.agent-fleet-test"
HOST_L = os.path.join(TMP, "host-launchd.json")
with open(HOST_L, "w") as f:
    json.dump({"schema": 1, "agents_root": ROOT, "fleet_checkout": FLEET,
               "claims_dir": os.path.join(TMP, "claims"), "launchd_prefix": PFX}, f)
HOME_L = os.path.join(TMP, "home-launchd")
LA = os.path.join(HOME_L, "Library", "LaunchAgents")
os.makedirs(LA)
LSTATE, LCALLS = os.path.join(TMP, "launchd.json"), os.path.join(TMP, "launchd-calls.log")
ENV_L = {**ENV, "FLEET_SERVICE_BACKEND": "launchd", "FLEET_HOST_CONFIG": HOST_L, "HOME": HOME_L,
         "FLEET_LAUNCHCTL": os.path.join(FLEET, "tests", "fixtures", "launchd", "fake-launchctl"),
         "FAKE_LAUNCHD_STATE": LSTATE, "FAKE_LAUNCHD_CALLS": LCALLS}
UID = os.getuid()
SLABEL, WLABEL, RLABEL = f"{PFX}.sched.{AGENT}", f"{PFX}.slack-watch.{AGENT}", f"{PFX}.daemons-refresh"
PY_L = "/opt/homebrew/bin/python3"


def lcalls(clear=False):
    got = open(LCALLS).read().splitlines() if os.path.exists(LCALLS) else []
    if clear:
        open(LCALLS, "w").close()
    return got


def lstate():
    return json.load(open(LSTATE)) if os.path.exists(LSTATE) else {}


def lstate_put(st):
    with open(LSTATE, "w") as f:
        json.dump(st, f)


r = run(SCRIPT, "render-units", "--units", "refresh", "--list", env=ENV_L)
check("under launchd --units refresh is one plist named by the host's prefix",
      r.stdout.split() == [f"{RLABEL}.plist"], r.stdout + r.stderr)
age_all()
r = run(SCRIPT, "--install", AGENT, env=ENV_L)
check("--install refuses (exit 2) while the refresh plist is not rendered, and calls launchctl for "
      "nothing", r.returncode == 2 and "fleet install --units" in r.stderr and lcalls() == [],
      f"{r.returncode} {r.stderr} {lcalls()}")
r = run(SCRIPT, "render-units", "--units", "refresh", "--out", LA, env=ENV_L)
rp = plistlib.load(open(os.path.join(LA, f"{RLABEL}.plist"), "rb")) if r.returncode == 0 else {}
check("the refresh plist runs this tree's refresh every 300 s, logging beside upgrades.log, with "
      "Homebrew first on PATH",
      rp.get("Label") == RLABEL and rp.get("StartInterval") == 300
      and rp.get("ProgramArguments") == [PY_L, f"{FLEET}/systemd/agent-daemons.py", "refresh"]
      and rp.get("StandardOutPath") == os.path.join(HOME_L, ".local", "state", "agent-fleet",
                                                    "daemons-refresh.log")
      and rp.get("EnvironmentVariables", {}).get("PATH", "").startswith("/opt/homebrew/bin:")
      and "RunAtLoad" not in rp, f"{r.stderr} {rp}")
r = run(SCRIPT, "--install", AGENT, env=ENV_L)
c = lcalls(clear=True)
sp_path = os.path.join(LA, f"{SLABEL}.plist")
sp = plistlib.load(open(sp_path, "rb")) if os.path.exists(sp_path) else {}
check("--install bootstraps the refresh job and renders and bootstraps the configured job's plist",
      r.returncode == 0 and f"bootstrap gui/{UID} {os.path.join(LA, RLABEL + '.plist')}" in c
      and f"bootstrap gui/{UID} {sp_path}" in c and f"enabled {SLABEL}" in r.stdout, f"{r.stdout}{r.stderr} {c}")
check("...and SKIPS the job whose config is missing, rendering nothing for it",
      f"SKIPPED {WLABEL}" in r.stdout and not os.path.exists(os.path.join(LA, f"{WLABEL}.plist")), r.stdout)
LOGL = os.path.join(ROOT, AGENT, "state", "daemons", "sched.log")
check("the job plist runs the exec shim, which rotates the job's log, applies its .env and execs "
      "the scheduler",
      sp.get("ProgramArguments") == [PY_L, f"{FLEET}/systemd/agent-daemons.py", "exec", "--log", LOGL,
                                     "--env-file", os.path.join(ROOT, AGENT, "config", "sched.env"), "--",
                                     PY_L, "-u", f"{FLEET}/.claude/skills/scheduled-tasks/sched.py"], str(sp))
check("...sets CLAUDE_CONFIG_DIR and its config IN the job, runs in the install checkout and logs "
      "where the follower reads",
      sp.get("EnvironmentVariables", {}).get("CLAUDE_CONFIG_DIR") == os.path.join(ROOT, AGENT, ".claude")
      and sp.get("EnvironmentVariables", {}).get("SCHED_CONFIG") == os.path.join(ROOT, AGENT, "config",
                                                                               "scheduler.json")
      and sp.get("WorkingDirectory") == os.path.join(ROOT, AGENT, "product")
      and sp.get("StandardOutPath") == LOGL == sp.get("StandardErrorPath"), str(sp))
check("...and restarts every exit but the GUARD's 0, 10 s apart, with a 15 s stop",
      sp.get("KeepAlive") == {"SuccessfulExit": False} and sp.get("RunAtLoad") is True
      and sp.get("ThrottleInterval") == 10 and sp.get("ExitTimeOut") == 15, str(sp))
check("...headed by the rendered-by comment after the XML declaration",
      open(sp_path).read().splitlines()[1].startswith(
          "<!-- Rendered by fleet install from systemd/agent-sched.plist.in at "), open(sp_path).read()[:300])
r = run(SCRIPT, "render-units", "--units", "all", "--list", env=ENV_L)
check("--units all under launchd lists the refresh plist and every installed job instance",
      r.stdout.split() == [f"{RLABEL}.plist", f"{SLABEL}.plist"], r.stdout + r.stderr)
r = run(SCRIPT, "jobs", "--json", env={**ENV_L, "FLEET_HOST_CONFIG": os.path.join(TMP, "absent.json")})
jt = json.loads(r.stdout) if r.returncode == 0 else {}
check("jobs --json under launchd reads no host settings, names the Homebrew interpreter and no "
      "shared unit", jt.get("python") == PY_L and all(j["unit"] is None for j in jt.get("jobs", {}).values())
      and "sched" in jt.get("jobs", {}), r.stdout + r.stderr)

HOST_PY = os.path.join(TMP, "host-python.json")
with open(HOST_PY, "w") as f:
    json.dump({**json.load(open(HOST_L)), "python": "/opt/fleet-test/bin/python3"}, f)
r = run(SCRIPT, "jobs", "--json", env={**ENV_L, "FLEET_HOST_CONFIG": HOST_PY})
r2 = run(SCRIPT, "jobs", "--json", env={**ENV_L, "FLEET_HOST_CONFIG": HOST_PY, "FLEET_PYTHON": "/opt/other/python3"})
out_py = fresh("render-py")
r3 = run(SCRIPT, "render-units", "--units", "refresh", "--out", out_py, env={**ENV_L, "FLEET_HOST_CONFIG": HOST_PY})
rp_py = plistlib.load(open(os.path.join(out_py, f"{RLABEL}.plist"), "rb")) if r3.returncode == 0 else {}
check("host.json's python is every render's interpreter (so FLEET_PYTHON is set once, at install), and "
      "FLEET_PYTHON still wins",
      json.loads(r.stdout or "{}").get("python") == "/opt/fleet-test/bin/python3"
      and json.loads(r2.stdout or "{}").get("python") == "/opt/other/python3"
      and rp_py.get("ProgramArguments", [""])[0] == "/opt/fleet-test/bin/python3",
      f"{r.stdout[:80]} {r2.stdout[:80]} {r3.stderr} {rp_py}")


def host_env(p):
    return p.get("EnvironmentVariables", {}).get("FLEET_HOST_CONFIG")


check("the refresh plist and the job plist name the host settings the render read, whichever file "
      "that was (launchd starts a job with the user's real HOME)",
      host_env(rp) == HOST_L and host_env(sp) == HOST_L and host_env(rp_py) == HOST_PY,
      f"{host_env(rp)} {host_env(sp)} {host_env(rp_py)}")


RENDER_FAILED = "render did not run"


def probe_host_config_named(script):
    """render-units --host-config <file>: every systemd unit and the refresh plist
    name THAT file as FLEET_HOST_CONFIG, while the settings are still READ from
    FLEET_HOST_CONFIG: `fleet install` reads a candidate in a temporary
    directory, gone when it returns, and names the file it writes. The named file
    does not exist yet, as on a first install. Two named files must give two
    values (a constant fails); the agents root and the label prefix are the ones
    read (the units carry ROOT, the plist is named after HOST_L's prefix); the
    file read is named nowhere."""
    problems = []
    for named in (os.path.join(TMP, "named-one", "host.json"), os.path.join(TMP, "named-two", "host.json")):
        out = fresh("render-named")
        r = run(script, "render-units", "--units", "all", "--out", out, "--host-config", named,
                env={**ENV, "FLEET_HOST_CONFIG": HOST2, "FLEET_TRANSPORTS_DIR": REGISTRY})
        if r.returncode != 0:
            problems.append(f"{RENDER_FAILED}: systemd, naming {named}: exit {r.returncode}: {r.stderr.strip()}")
            continue
        for n in HOST_UNITS:
            text = open(os.path.join(out, n)).read() if os.path.exists(os.path.join(out, n)) else ""
            got = [l for l in text.splitlines() if l.startswith("Environment=FLEET_HOST_CONFIG=")]
            if got != [f"Environment=FLEET_HOST_CONFIG={named}"] or HOST2 in text:
                problems.append(f"{n} naming {named}: {got}")
        if f"WorkingDirectory={ROOT}/%i/" not in open(os.path.join(out, "agent-sched@.service")).read():
            problems.append("agent-sched@.service does not carry the agents root read")
        out = fresh("render-named-launchd")
        r = run(script, "render-units", "--units", "refresh", "--out", out, "--host-config", named, env=ENV_L)
        plist = os.path.join(out, f"{RLABEL}.plist")
        if r.returncode != 0 or not os.path.exists(plist):
            problems.append(f"{RENDER_FAILED}: launchd, naming {named}: exit {r.returncode}: {r.stderr.strip()}")
        elif host_env(plistlib.load(open(plist, "rb"))) != named or HOST_L in open(plist).read():
            problems.append(f"{RLABEL}.plist names {host_env(plistlib.load(open(plist, 'rb')))}, not {named}")
    return not problems, "; ".join(problems)


check("render-units --host-config: every unit and plist names that file while the settings are read "
      "from FLEET_HOST_CONFIG (fleet install names the file it writes, not its temporary candidate)",
      *probe_host_config_named(SCRIPT))
# The mutant must fail by NAMING the wrong file: one whose render does not run
# at all fails the probe too, and counting that as caught would let a control
# that measures a crash pass for this one.
control("Y: render-units ignores --host-config",
        mutant("substitutions(job, agent, a.host_config)", "substitutions(job, agent)"),
        lambda s: (lambda good, why: good or RENDER_FAILED in why)(*probe_host_config_named(s)))


def follow_l(*extra):
    r = run(SCRIPT, "follow", AGENT, "sched", "--once", "--log", LOGL, "--unit", SLABEL, *extra, env=ENV_L)
    return r.stdout.splitlines()


follow_l()
out = follow_l()
check("a running job with no restarts: the follower is silent", out == [], str(out))
subprocess.run([ENV_L["FLEET_LAUNCHCTL"], "kickstart", "-k", f"gui/{UID}/{SLABEL}"], env=ENV_L, check=True)
out = follow_l()
check("launchd's respawn after a crash (its `runs` count) is a restart the follower alerts on",
      len(out) == 1 and out[0].startswith(f"DAEMON-ALERT {SLABEL} restarted on its own 1 time(s)"), str(out))
st = lstate()
job = st["loaded"][f"gui/{UID}"][SLABEL]
job.update(state="not running", last_exit="0")
job.pop("pid", None)
lstate_put(st)
out = follow_l()
check("a job that exited 0 and stays down is the GUARD alert, naming launchctl kickstart",
      len(out) == 1 and "inactive/dead, result=success" in out[0] and "GUARD" in out[0]
      and f"launchctl kickstart gui/{UID}/{SLABEL}" in out[0], str(out))
subprocess.run([ENV_L["FLEET_LAUNCHCTL"], "kickstart", f"gui/{UID}/{SLABEL}"], env=ENV_L, check=True)
r = run(SCRIPT, "status", AGENT, "--json", env=ENV_L)
sj = json.loads(r.stdout) if r.stdout.strip().startswith("{") else {}
check("status <agent> --json under launchd: the configured job active with its pid, the "
      "unconfigured one reported and not counted, exit 0",
      r.returncode == 0 and sj.get("jobs", {}).get("sched", {}).get("active") == "active"
      and sj["jobs"]["sched"]["pid"] > 0 and sj["jobs"]["slack-watch"]["configured"] is False,
      r.stdout + r.stderr)

# The follower's restart arithmetic against CAPTURED `launchctl print` layouts
# (tests/fixtures/launchd/print-*.txt, canned into the fake one at a time).
# launchd counts every spawn in `runs`, a manual kickstart included; systemd's
# NRestarts counts only Restart='s. The capture sequence is the macOS runbook's:
# a kill -9 respawn, the GUARD's exit 0, then the kickstart the alert names.
LFIX = os.path.join(FLEET, "tests", "fixtures", "launchd")
LPRINT = f"print gui/{UID}/{SLABEL}"
LENV_KEYS = ("FLEET_SERVICE_BACKEND", "FLEET_HOST_CONFIG", "HOME", "FLEET_LAUNCHCTL",
             "FAKE_LAUNCHD_STATE", "FAKE_LAUNCHD_CALLS")


def canned_print(fixture):
    st = lstate()
    if fixture is None:
        st.get("canned", {}).pop(LPRINT, None)
    else:
        st.setdefault("canned", {})[LPRINT] = {"file": os.path.join(LFIX, fixture), "exit": 0}
    lstate_put(st)


def checks_in_one_arm(script, prints):
    """One in-process Follower of `script` under launchd, ONE arm: a unit check
    per captured print, a minute apart. [the lines each check printed]."""
    m = load(script)
    saved = dict(os.environ)
    os.environ.update({k: ENV_L[k] for k in LENV_KEYS})
    f = m.Follower(fresh("ld-arm") + ".log", SLABEL, out=io.StringIO())
    outs = []
    try:
        f.load()
        f.cur.pop("was_active", None)          # what run() does on every arm
        for i, fixture in enumerate(prints):
            canned_print(fixture)
            before = len(f.out.getvalue())
            f.check_unit(time.time() + 60 * i)
            outs.append(f.out.getvalue()[before:].splitlines())
    finally:
        canned_print(None)
        os.environ.clear()
        os.environ.update(saved)
    return outs


def checks_one_arm_each(script, prints):
    """A fresh `follow --once` PROCESS per captured print, so every check is a new
    arm (the Monitor re-arms the follower every 30 minutes)."""
    log, outs = fresh("ld-arms") + ".log", []
    try:
        for fixture in prints:
            canned_print(fixture)
            outs.append(run(script, "follow", AGENT, "sched", "--once", "--log", log, "--unit", SLABEL,
                            env=ENV_L).stdout.splitlines())
    finally:
        canned_print(None)
    return outs


OK_LINE = f"DAEMON-OK {SLABEL} is active again"
RECOVERY = ["print-respawned-signal.txt", "print-guard-exit.txt", "print-kickstarted.txt"]


def probe_kickstart_recovers(script):
    o = checks_in_one_arm(script, RECOVERY)
    return (len(o) == 3 and o[0] == [] and len(o[1]) == 1 and "GUARD" in o[1][0]
            and "inactive/dead, result=success" in o[1][0] and o[2] == [OK_LINE])


def probe_kickstart_across_arms(script):
    o = checks_one_arm_each(script, RECOVERY)
    return len(o) == 3 and o[0] == [] and len(o[1]) == 1 and "GUARD" in o[1][0] and o[2] == []


def probe_throttled_crash_alerts(script):
    o = checks_in_one_arm(script, ["print-running.txt", "print-spawn-scheduled.txt",
                                   "print-respawned-signal.txt"])
    return (len(o) == 3 and o[0] == []
            and o[1] == [f"DAEMON-ALERT {SLABEL} is not active (activating/auto-restart, result=exit-code)"]
            and len(o[2]) == 1 and o[2][0].startswith(f"DAEMON-ALERT {SLABEL} restarted on its own 1 time(s)"))


def probe_killed_alerts(script):
    o = checks_in_one_arm(script, ["print-running.txt", "print-respawned-signal.txt"])
    return (len(o) == 2 and o[0] == [] and len(o[1]) == 1
            and o[1][0].startswith(f"DAEMON-ALERT {SLABEL} restarted on its own 1 time(s) since the last "
                                   f"check (active/running, result=signal)"))


check("after the GUARD stop, the kickstart its alert names is recovery: DAEMON-OK, not a restart "
      "(captured prints: runs 2 -> 3 -> 4)", probe_kickstart_recovers(SCRIPT),
      str(checks_in_one_arm(SCRIPT, RECOVERY)))
control("R: a rise after a stopped check counted as the unit's own restart", mutant(
    'and not self.cur.get("stopped")', ""), probe_kickstart_recovers)
check("...and a kickstart made while no follower ran (a new arm between) raises no restart alert",
      probe_kickstart_across_arms(SCRIPT), str(checks_one_arm_each(SCRIPT, RECOVERY)))
control("S: the stopped mark dropped on every arm, as was_active is", mutant(
    'self.cur.pop("was_active", None)\n', 'self.cur.pop("was_active", None)\n'
    '        self.cur.pop("stopped", None)\n'), probe_kickstart_across_arms)
check("a crash held in launchd's throttle (spawn scheduled) is alerted as not active, and its respawn "
      "as a restart of its own", probe_throttled_crash_alerts(SCRIPT))
control("W: every rise after a not-active check excused, launchd's own respawn included", mutant(
    'self.cur["stopped"] = s["active"] in ("inactive", "failed")', 'self.cur["stopped"] = not active'),
    probe_throttled_crash_alerts)
check("a kill -9 that launchd respawned between two checks is a restart of its own, result=signal",
      probe_killed_alerts(SCRIPT))

# refresh: the process's environment is unreadable (no environ file, macOS's
# shape), so the config the job was started with comes from its definition.
SPID = lstate()["loaded"][f"gui/{UID}"][SLABEL]["pid"]


def fake_process_noenv(pid):
    shutil.rmtree(os.path.join(PROC, str(pid)), ignore_errors=True)
    fake_process(pid, [PY_L, "-u", CANARY], [], os.path.join(HOME_, "product"), STARTED)
    os.remove(os.path.join(PROC, str(pid), "environ"))


def loaded_env(config):
    st = lstate()
    st["loaded"][f"gui/{UID}"][SLABEL]["env"]["SCHED_CONFIG"] = config
    lstate_put(st)


def refresh_l(*extra, script=SCRIPT):
    lcalls(clear=True)
    r = run(script, "refresh", *extra, env=ENV_L)
    return [c for c in lcalls() if c.split()[0] in ("bootout", "bootstrap", "kickstart")], r


def probe_definition_env(script):
    age_all()
    pid = lstate()["loaded"][f"gui/{UID}"][SLABEL]["pid"]
    fake_process_noenv(pid)
    loaded_env(ALT_CFG)
    os.utime(ALT_CFG, None)
    got, r = refresh_l(script=script)
    return got == [f"bootout gui/{UID}/{SLABEL}", f"bootstrap gui/{UID} {sp_path}"], f"{got} {r.stderr}"


fake_process_noenv(SPID)
loaded_env(ALT_CFG)
age_all()
got, r = refresh_l("--dry-run")
check("refresh --dry-run under launchd keeps a fresh job and says its config came from the job "
      "definition", got == [] and f"DRY-RUN keep {SLABEL}: " in r.stdout
      and "(config from job definition)" in r.stdout, r.stdout + r.stderr)
check("the config the launchd job was started with changed: refresh restarts it by bootout then "
      "bootstrap, never kickstart", *probe_definition_env(SCRIPT))
check("...and notes why in the job's log", f"DAEMON-REFRESH restarting {SLABEL}: " in open(LOGL).read())
_old = '    env, source, defn = S.proc_env(pid), "process", None\n'
control("V: the unreadable macOS process environment read as empty",
        mutant(_old, '    env, source, defn = S.proc_env(pid) or {}, "process", None\n'),
        lambda s: probe_definition_env(s)[0])
age_all()
fake_process_noenv(lstate()["loaded"][f"gui/{UID}"][SLABEL]["pid"])
loaded_env(ALT_CFG)
os.utime(DEFAULT_CFG, None)
got, _ = refresh_l()
check("...while the default config, which the job does not run with, changing restarts nothing "
      "(control: the decision is the definition's)", got == [], str(got))

# The refresh job as launchd runs it: the plist's EnvironmentVariables over the
# user's REAL home, which holds the LaunchAgents but, on a host whose host.json
# lives elsewhere, no host settings at the default path (HOME_L has none: HOST_L
# is outside it). Only this test's seams are added; FLEET_HOST_CONFIG comes from
# the plist or not at all.
LD_SEAMS = ("FLEET_SERVICE_BACKEND", "FLEET_LAUNCHCTL", "FAKE_LAUNCHD_STATE", "FAKE_LAUNCHD_CALLS",
            "FLEET_TRANSPORTS_DIR", "AGENT_DAEMONS_PROC")


def probe_refresh_as_launchd_runs_it(script):
    out = fresh("ld-refresh-plist")
    r = run(script, "render-units", "--units", "refresh", "--out", out, env=ENV_L)
    if r.returncode != 0:
        return False, f"render: {r.stderr}"
    p = plistlib.load(open(os.path.join(out, f"{RLABEL}.plist"), "rb"))
    env = {**{k: ENV_L[k] for k in LD_SEAMS}, "HOME": HOME_L, **p.get("EnvironmentVariables", {})}
    r = subprocess.run([sys.executable, script, "refresh", "--dry-run"], capture_output=True, text=True,
                       env=env)
    return r.returncode == 0 and SLABEL in r.stdout, f"exit {r.returncode}: {r.stdout}{r.stderr}"


def probe_refresh_without_host(script):
    absent = os.path.join(TMP, "no-such-host.json")
    r = run(script, "refresh", env={**ENV_L, "FLEET_HOST_CONFIG": absent})
    lines = r.stderr.splitlines()
    return (r.returncode == 3 and r.stdout == "" and len(lines) == 1 and absent in lines[0],
            f"exit {r.returncode}: {r.stdout!r} {r.stderr!r}")


check("the refresh job, run with its plist's environment and the user's real HOME, finds this "
      "install's jobs through the FLEET_HOST_CONFIG the plist names",
      *probe_refresh_as_launchd_runs_it(SCRIPT))
_hc = "    <key>FLEET_HOST_CONFIG</key>\n    <string>@HOST_CONFIG@</string>\n"
control("H: the refresh plist names no FLEET_HOST_CONFIG",
        tree(template_edits={"agent-daemons-refresh.plist.in": [(_hc, "")]}),
        lambda s: probe_refresh_as_launchd_runs_it(s)[0])
check("refresh with no host settings exits 3 with ONE line naming the file it looked for, and "
      "prints nothing else", *probe_refresh_without_host(SCRIPT))
control("N: refresh that does not read the host settings first",
        mutant("    fleetlib().paths.host()\n    S = svc()\n", "    S = svc()\n"),
        lambda s: probe_refresh_without_host(s)[0])

st = lstate()
st["loaded"][f"gui/{UID}"][SLABEL].update(state="not running", last_exit="1")
st["loaded"][f"gui/{UID}"][SLABEL].pop("pid", None)
lstate_put(st)
r = run(SCRIPT, "status", AGENT, env=ENV_L)
check("status <agent> exits 1 naming the configured job that is down",
      r.returncode == 1 and any(l.startswith("DOWN") and "sched" in l for l in r.stdout.splitlines()),
      r.stdout + r.stderr)
lcalls(clear=True)
r = run(SCRIPT, "--uninstall", AGENT, env=ENV_L)
check("--uninstall <agent> boots its jobs out and removes their plists; the refresh job stays",
      r.returncode == 0 and f"bootout gui/{UID}/{SLABEL}" in lcalls() and not os.path.exists(sp_path)
      and os.path.exists(os.path.join(LA, f"{RLABEL}.plist")), f"{r.stdout}{r.stderr} {lcalls()}")
r = run(SCRIPT, "--uninstall", env=ENV_L)
check("--uninstall with no agent also boots out and removes the refresh job: nothing is left",
      r.returncode == 0 and os.listdir(LA) == [] and not lstate()["loaded"].get(f"gui/{UID}"),
      f"{r.stdout}{r.stderr} {os.listdir(LA)} {lstate()}")
set_units({UNIT: {**ACTIVE, "MainPID": "4242"}})
r = run(SCRIPT, "status", AGENT, env=ENV)
check("status <agent> under systemd reads the same table: the configured scheduler active, exit 0",
      r.returncode == 0 and f"agent-sched@{AGENT}.service\tactive/running pid=4242" in r.stdout, r.stdout + r.stderr)
set_units({})
r = run(SCRIPT, "status", AGENT, env=ENV)
check("...and exit 1 naming it once its unit is gone",
      r.returncode == 1 and f"DOWN  sched\tagent-sched@{AGENT}.service" in r.stdout, r.stdout + r.stderr)

# === LIVE. a real LaunchAgent, in a macOS CI job only =========================
print("--- LIVE. launchd on this machine ---")
# A LIVE run killed before its finally leaves its job loaded, and KeepAlive keeps
# it running in the runner's session. Its label carries that run's pid, so no later
# run's finally reaches it: LIVE starts by booting out every smoke label in the
# domain, whatever its pid. The check below runs everywhere; it fails both a
# matcher keyed on one pid and one that takes any com.agent-fleet-test job.
SMOKE_LABEL = re.compile(r"\bcom\.agent-fleet-test\.smoke[\w.-]*")


def stale_smoke_labels(domain_print):
    return sorted(set(SMOKE_LABEL.findall(domain_print)))


_dp = ("gui/501 = {\n\tservices = {\n\t\t     598      -   \tcom.apple.Finder\n"
       "\t\t     812      -   \tcom.agent-fleet-test.smoke4242.sched.smoke\n"
       "\t\t       0     78   \tcom.agent-fleet-test.smoke77.sched.smoke\n"
       "\t\t     900      -   \tcom.agent-fleet-test.sched.ada\n\t}\n}\n")
check("LIVE's start finds every smoke job an earlier run left loaded, whatever its pid, and no other job",
      stale_smoke_labels(_dp) == ["com.agent-fleet-test.smoke4242.sched.smoke",
                                  "com.agent-fleet-test.smoke77.sched.smoke"], str(stale_smoke_labels(_dp)))


def live_smoke():
    import signal
    sys.path.insert(0, os.path.join(FLEET, "lib"))
    from fleetlib import services as S
    lhome = os.path.join(TMP, "live-home")
    os.makedirs(os.path.join(lhome, "Library", "LaunchAgents"))
    prefix = f"com.agent-fleet-test.smoke{os.getpid()}"
    lc = "/bin/launchctl"
    dom = "gui" if subprocess.run([lc, "print", f"gui/{UID}"], capture_output=True).returncode == 0 else "user"
    host = os.path.join(TMP, "live-host.json")
    with open(host, "w") as f:
        json.dump({"schema": 1, "agents_root": os.path.join(TMP, "live-agents"), "fleet_checkout": FLEET,
                   "claims_dir": os.path.join(TMP, "claims"), "launchd_prefix": prefix,
                   "launchd_domain": dom}, f)
    saved = dict(os.environ)
    os.environ.update({"FLEET_SERVICE_BACKEND": "launchd", "FLEET_HOST_CONFIG": host, "HOME": lhome})
    for k in ("FLEET_LAUNCHCTL", "AGENT_DAEMONS_PROC", "FLEET_PROC"):
        os.environ.pop(k, None)
    agents = os.path.join(TMP, "live-agents")
    os.makedirs(os.path.join(agents, "smoke", "product"))
    os.makedirs(os.path.join(agents, "smoke", "state", "daemons"))
    flag, smoke = os.path.join(TMP, "live-exit0"), os.path.join(TMP, "live-smoke.py")
    with open(smoke, "w") as f:
        f.write("import os, sys, time\nprint('up', os.getpid(), os.environ.get('SCHED_CONFIG'), flush=True)\n"
                f"while not os.path.exists({flag!r}):\n    time.sleep(0.2)\nsys.exit(0)\n")
    label = S.unit("job", "smoke", "sched")
    log = os.path.join(agents, "smoke", "state", "daemons", "sched.log")
    subs = live_subs(agents, smoke, label, host)
    plist = os.path.join(str(S.unit_dir()), S.unit_file(label))
    with open(plist, "wb") as f:
        f.write(S.render("agent-sched.plist.in", open(os.path.join(HERE, "agent-sched.plist.in")).read(),
                         subs, "smoke"))

    def wait(pred, secs):
        end = time.time() + secs
        while time.time() < end:
            s = S.status(label)
            if pred(s):
                return s
            time.sleep(0.25)
        return S.status(label)

    def raw():
        return subprocess.run([lc, "print", S.domain() + "/" + label], capture_output=True, text=True).stdout

    for stale in stale_smoke_labels(subprocess.run([lc, "print", S.domain()], capture_output=True, text=True).stdout):
        r = subprocess.run([lc, "bootout", S.domain() + "/" + stale], capture_output=True, text=True)
        print(f"LIVE: booted out {stale}, left by an earlier run (exit {r.returncode})")
    try:
        S.enable(label, now=True)
        s1 = wait(lambda s: s["active"] == "active" and s["pid"] > 0, 15)
        check(f"LIVE ({dom} domain): bootstrap starts the job", s1["active"] == "active", f"{s1} {raw()}")
        # The shim execs the script a moment after launchd reports the pid: wait for
        # the script's own line. argv[0] is not compared: a framework Python (the
        # runner's, Homebrew's) re-execs itself as its Python.app binary, which
        # rewrites argv[0] and keeps the pid and the rest of argv.
        up = f"up {s1['pid']} {agents}/smoke/config/scheduler.json"
        end = time.time() + 15
        while time.time() < end and not (os.path.exists(log) and up in open(log).read()):
            time.sleep(0.2)
        argv = S.proc_argv(s1["pid"])
        check("LIVE: the exec shim became the job: the pid runs the script, with the plist's config, "
              "its output in the log",
              bool(argv) and argv[1:] == ["-u", smoke] and up in open(log).read(),
              f"{argv} {open(log).read() if os.path.exists(log) else '<no log>'}")
        d = S.definition(label)
        check("LIVE: the definition read from launchctl print carries the job's environment",
              d and d["source"] == "loaded" and d["env"].get("SCHED_CONFIG") == f"{agents}/smoke/config/scheduler.json",
              f"{d} {raw()}")
        os.kill(s1["pid"], signal.SIGKILL)
        s2 = wait(lambda s: s["active"] == "active" and s["pid"] not in (0, s1["pid"]), 25)
        check("LIVE: KeepAlive respawns the job after kill -9, and status counts the restart",
              s2["active"] == "active" and s2["pid"] != s1["pid"] and s2["restarts"] >= 1, f"{s2} {raw()}")
        open(flag, "w").close()
        s3 = wait(lambda s: s["active"] != "active", 15)
        time.sleep(12)
        s3 = S.status(label)
        check("LIVE: an exit 0 (the GUARD's) is not respawned: inactive, result success, 12 s later",
              s3["active"] == "inactive" and s3["result"] == "success" and s3["pid"] == 0, f"{s3} {raw()}")
        os.remove(flag)
        S.restart(label)
        s4 = wait(lambda s: s["active"] == "active" and s["pid"] > 0, 15)
        check("LIVE: restart (bootout, then bootstrap) brings it back", s4["active"] == "active", f"{s4} {raw()}")
        S.disable(label)
        os.remove(plist)
        gone = subprocess.run([lc, "print", S.domain() + "/" + label], capture_output=True, text=True)
        check("LIVE: disable boots it out; launchd holds nothing of it",
              S.status(label)["load"] == "not-found" and "Could not find service" in gone.stdout + gone.stderr,
              gone.stdout + gone.stderr)
    finally:
        subprocess.run([lc, "bootout", S.domain() + "/" + label], capture_output=True)
        os.environ.clear()
        os.environ.update(saved)


def live_subs(agents, smoke, label, host):
    """LIVE's own values for every placeholder of agent-sched.plist.in. They are
    LIVE's, not agent-daemons.py's (its script is the smoke script), so a placeholder
    a template gains needs a value here too: the check below renders with them on
    every system, because LIVE itself runs in a macOS CI job only."""
    return {"FLEET": FLEET, "PYTHON": sys.executable, "LABEL": label, "AGENTS_ROOT": agents, "AGENT": "smoke",
            "PROJECT_DIR": "product", "JOB": "sched", "SCRIPT": smoke, "CONFIG": "config/scheduler.json",
            "CONFIG_ENV": "SCHED_CONFIG", "HOST_CONFIG": host,
            "PATH": f"{os.path.dirname(sys.executable)}:/usr/bin:/bin:/usr/sbin:/sbin"}


def live_render(subs):
    sys.path.insert(0, os.path.join(FLEET, "lib"))
    from fleetlib import services
    try:
        return plistlib.loads(services.render("agent-sched.plist.in", open(os.path.join(HERE, "agent-sched.plist.in"))
                                              .read(), subs, "smoke")), ""
    except Exception as e:
        return {}, f"{type(e).__name__}: {e}"


_lp, _lerr = live_render(live_subs(os.path.join(TMP, "live-agents"), os.path.join(TMP, "live-smoke.py"),
                                   "com.agent-fleet-test.smoke1.sched.smoke", os.path.join(TMP, "live-host.json")))
check("LIVE's substitutions fill every placeholder of agent-sched.plist.in, its host settings included",
      _lp.get("EnvironmentVariables", {}).get("FLEET_HOST_CONFIG") == os.path.join(TMP, "live-host.json"),
      _lerr or str(_lp))


if sys.platform == "darwin" and os.environ.get("GITHUB_ACTIONS") == "true":
    live_smoke()
else:
    print("[NOT RUN] LIVE: a real LaunchAgent is bootstrapped in a macOS CI job only "
          "(sys.platform darwin and GITHUB_ACTIONS=true)")

# === S. the production Slack descriptor, once this tree has one ==============
print("--- S. this tree's own Slack descriptor ---")
sys.path.insert(0, os.path.join(FLEET, "lib"))
from fleetlib import transports  # noqa: E402

real = [t for t in transports.all(os.path.join(FLEET, ".claude", "skills")) if t["name"] == "slack"]
if real:
    w = real[0]["watch"]
    check("the Slack transport this tree ships keeps today's job, config variable, script and "
          "line prefix, so the units it renders are the ones already enabled",
          (w["job"], w["config_env"], w["script"], real[0]["line_prefix"])
          == ("slack-watch", "SLACK_WATCH_CONFIG", "watch.py", "SLACK"), str(real[0]))
else:
    print("[NOT RUN] this tree has no .claude/skills/*/transport.json named slack: nothing "
          "to compare (no verdict either way)")

shutil.rmtree(TMP)
print()
if _no_verdict:
    print(f"NO VERDICT for {len(_no_verdict)} control(s), not built or passed against "
          f"their mutant: {', '.join(_no_verdict)} - the checks they guard are not shown "
          "to see the defect they are for")
if _failures:
    print(f"FAILED: {len(_failures)} check(s): {', '.join(_failures)}")
    sys.exit(1)
if _no_verdict:
    print("NO VERDICT: no check failed, and no pass is claimed")
    sys.exit(3)
print("ALL CHECKS PASSED")
