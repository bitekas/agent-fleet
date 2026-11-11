#!/usr/bin/env python3
"""fleet.test.py - the `fleet` command's contract, run against temporary fleet trees.

Usage: python3 bin/fleet.test.py [-k <substring>]

Every case builds its own world under one temporary directory:
  * an ORIGIN repository whose commits carry bin/fleet and lib/fleetlib/ copied
    from the tree under test, plus synthetic skills, a systemd/agent-daemons.py
    whose render-units is fake and whose job table (`jobs --json`) is the real
    one, and a fake tools/leak-gate/leak_gate.py;
  * a host checkout cloned from it, an agents root with agent homes and install
    manifests, and a temporary HOME;
  * fakes selected through the command's own seams (FLEET_SYSTEMCTL, FLEET_GH,
    FLEET_NPM, FLEET_PROC) AND named after the programs they replace in a
    directory that comes first on PATH, with a fake `curl` that serves the
    gitleaks release tarball to the commit gate's real install-gitleaks.sh.
The environment of every run is built from nothing (PATH, HOME, the seams), so
no case reads or writes the real ~/.config, ~/.local, any systemd unit, any
GitHub API or the network. The PATH entry is the second fence: a seam the
command stopped honouring would still reach a fake, never the host's systemctl.

WHY THE COMMAND RUNS FROM A CLONE AND NOT FROM THIS TREE. A fleet tree's
transport registry, its tags and its read-only mode are all properties the
command reads from the tree it runs from. Running it from this checkout would
make every verdict depend on whatever skills and tags this checkout happens to
hold; a clone of a synthetic origin makes them constants of the test.

THE ORACLES ARE INDEPENDENT OF THE SUBJECT. The read-only mode is measured here
with this file's own ls-files walk, link targets with os.readlink, unit-file
state through the fake systemctl's snapshot of the unit directory taken at the
moment of each call. A test that asked the subject whether it had done its job
would pass on a subject that lies.

EVERY REFUSAL IS CHECKED THREE WAYS: exit 2, the reason named in stderr (a
crash that happens to exit 2 does not name it), and a snapshot of everything
the command could have touched, taken before and after, being identical.

MUTATION RUNS. FLEET_TEST_SUBJECT=<path> tests that file instead of
bin/fleet; it exists so a deliberately broken copy can be shown to turn the
cases that guard each property red.
"""
import ast
import hashlib
import io
import itertools
import json
import os
import plistlib
import pwd
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import traceback
from pathlib import Path

REPO = Path(os.path.realpath(__file__)).parents[1]
SUBJECT = Path(os.environ.get("FLEET_TEST_SUBJECT") or REPO / "bin" / "fleet")
LIB = REPO / "lib" / "fleetlib"
PY = sys.executable
MAINT = ("Ada Maintainer", "maint@example.com")
OUTSIDER = ("Grace Outside", "grace@example.org")
SPOOF = ("Grace Outside", MAINT[1])        # an outsider writing the maintainers' public address
GITHUB_WEB = ("GitHub", "noreply@github.com")  # the committer of every web-interface merge
SKILLS = ["chat-transport", "slack-communication", "scheduled-tasks", "demo-skill"]
LOCK = ".claude/skills/agent-revive/signin_driver/package-lock.json"
TABLE_PYTHON = "/opt/table-python/bin/python3"  # the origin's job table (see populate)
TABLE_LOG_DIR = "state/table-daemons"
# Under /tmp and through realpath: bin/fleet compares realpaths, and on macOS the
# default temp directory is a long /var/folders path that is /private/var/folders
# underneath, which breaks path equality.
SCRATCH = Path(os.path.realpath(tempfile.mkdtemp(prefix="fleet-test-", dir="/tmp")))
GITCONFIG = SCRATCH / "gitconfig"
OUTSIDE_FILE = SCRATCH / "outside.txt"  # a tracked symlink in the origin points here

CASES = []


def case(fn):
    CASES.append(fn)
    return fn


# ------------------------------------------------------------------ helpers

def write(path, text, mode=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text if isinstance(text, bytes) else text.encode())
    if mode is not None:
        path.chmod(mode)
    return path


def git_env(who=MAINT, committer=MAINT):
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(SCRATCH),
            "LANG": "C.UTF-8", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": str(GITCONFIG),
            "GIT_AUTHOR_NAME": who[0], "GIT_AUTHOR_EMAIL": who[1],
            "GIT_COMMITTER_NAME": committer[0], "GIT_COMMITTER_EMAIL": committer[1]}


def git(cwd, *args, who=MAINT, committer=MAINT):
    p = subprocess.run(["git", "-C", str(cwd), *map(str, args)], env=git_env(who, committer),
                       capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if p.returncode:
        raise AssertionError(f"git {' '.join(map(str, args))} in {cwd}: {p.stderr.strip()}")
    return p.stdout.strip()


def tracked_paths(tree):
    names = [n for n in git(tree, "ls-files", "-z").split("\0") if n]
    out = {Path(tree)}
    for n in names:
        out.add(Path(tree) / n)
        out.update(Path(tree) / p for p in Path(n).parents)
    return sorted(p for p in out if os.path.lexists(p))


def chmod_tracked(tree, write_bits):
    for p in tracked_paths(tree):
        st = os.lstat(p)
        if not stat.S_ISLNK(st.st_mode):
            m = stat.S_IMODE(st.st_mode)
            os.chmod(p, m | 0o200 if write_bits else m & ~0o222)


def writable_tracked(tree):
    return [p for p in tracked_paths(tree)
            if not stat.S_ISLNK(os.lstat(p).st_mode) and os.lstat(p).st_mode & 0o222]


def snap(*roots):
    """Everything under each root (no .git): type, mode, link target, content hash."""
    out = {}
    for root in map(Path, roots):
        if not os.path.lexists(root):
            out[str(root)] = None
            continue
        st = os.lstat(root)
        if not stat.S_ISDIR(st.st_mode):
            out[str(root)] = _entry(root)
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d != ".git")
            out[dirpath] = ("dir", stat.S_IMODE(os.lstat(dirpath).st_mode))
            for n in sorted(filenames) + [d for d in dirnames if os.path.islink(Path(dirpath) / d)]:
                out[str(Path(dirpath) / n)] = _entry(Path(dirpath) / n)
    return out


def same(before, after, what="state"):
    diff = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    assert not diff, f"{what} changed at: " + ", ".join(
        f"{k} {before.get(k)} -> {after.get(k)}" for k in diff[:5])


def _entry(p):
    st = os.lstat(p)
    if stat.S_ISLNK(st.st_mode):
        return ("link", os.readlink(p))
    if stat.S_ISDIR(st.st_mode):
        return ("dir", stat.S_IMODE(st.st_mode))
    return ("file", stat.S_IMODE(st.st_mode), hashlib.sha256(p.read_bytes()).hexdigest())


def ok(r, code=0):
    assert r.returncode == code, f"exit {r.returncode}, wanted {code}\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}"


def refused(r, reason):
    ok(r, 2)
    assert reason in r.stderr, f"stderr does not name {reason!r}:\n{r.stderr}"


def force_rmtree(path):
    for dirpath, _, _ in os.walk(path):
        if not os.path.islink(dirpath):
            os.chmod(dirpath, stat.S_IMODE(os.lstat(dirpath).st_mode) | 0o700)
    shutil.rmtree(path)


# ------------------------------------------------------------------ fakes

FAKE_SYSTEMCTL = r'''#!@PY@
import json, os, re, sys
from pathlib import Path
args = sys.argv[1:]
user = args[:1] == ["--user"]
rest = args[1:] if user else args
udir = Path(os.environ["HOME"]) / ".config" / "systemd" / "user"
units = {p.name: ("link" if p.is_symlink() else "file")
         for p in (sorted(udir.glob("agent-*")) if udir.is_dir() else []) if not p.name.endswith(".d")}
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps({"tool": "systemctl", "argv": args, "units": units,
                        "xdg": os.environ.get("XDG_RUNTIME_DIR")}) + "\n")
if rest[:1] == ["show"]:
    # Answered as systemd does, from the unit's properties: each `-p P` prints
    # P=<value> (the value alone with --value); a unit nobody set is not-found.
    answers = json.loads(Path(os.environ["FAKE_SYSTEMCTL_SHOW"]).read_text())
    props = [rest[i + 1] for i, a in enumerate(rest) if a == "-p"]
    unit = next(a for i, a in enumerate(rest[1:], 1) if not a.startswith("-") and rest[i - 1] != "-p")
    u = answers.get(("user:" if user else "system:") + unit,
                    {"LoadState": "not-found", "ActiveState": "inactive", "MainPID": "0"})
    for p in props:
        sys.stdout.write(f"{u.get(p, '')}\n" if "--value" in rest else f"{p}={u.get(p, '')}\n")
elif rest[:1] == ["disable"]:
    for d in [*udir.glob("*.wants"), *udir.glob("*.requires")]:
        for name in rest[1:]:
            if os.path.lexists(d / name):
                (d / name).unlink()
elif rest[:1] == ["enable"]:
    for name in [n for n in rest[1:] if not n.startswith("-")]:
        unit = re.sub(r"@[^.]+\.", "@.", name)
        for wanted in re.findall(r"^WantedBy=(\S+)", (udir / unit).read_text(), re.M):
            d = udir / f"{wanted}.wants"
            d.mkdir(parents=True, exist_ok=True)
            if os.path.lexists(d / name):
                (d / name).unlink()
            (d / name).symlink_to(udir / unit)
'''

FAKE_GH = r'''#!@PY@
import json, os, re, sys
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps({"tool": "gh", "argv": args}) + "\n")
m = re.fullmatch(r"repos/[^/]+/[^/]+/commits/([0-9a-f]{40})/check-runs(\?.*)?", args[1]) if args[:1] == ["api"] else None
if not m:
    sys.exit("fake gh: unexpected call")
state = json.load(open(os.environ["FAKE_GH_STATE"])).get(m.group(1), {})
runs = [{"id": i + 1, "name": n, "status": "completed", "conclusion": state.get(n, "success")}
        for i, n in enumerate(("test", "gates", "leak", "commit-hygiene")) if state.get(n) != "missing"]
print(json.dumps({"total_count": len(runs), "check_runs": runs}))
'''

FAKE_NPM = r'''#!@PY@
import json, os, shutil, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps({"tool": "npm", "argv": args, "cwd": os.getcwd(),
                        "browsers": os.environ.get("PLAYWRIGHT_BROWSERS_PATH")}) + "\n")
if args[:1] == ["ci"]:
    shutil.rmtree("node_modules", ignore_errors=True)
    for dep in json.loads(Path("package.json").read_text()).get("dependencies", {}):
        Path("node_modules", dep).mkdir(parents=True)
elif args[:1] == ["exec"]:
    Path(os.environ["PLAYWRIGHT_BROWSERS_PATH"]).mkdir(exist_ok=True)
'''

FAKE_CURL = r'''#!@PY@
import json, os, shutil, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps({"tool": "curl", "argv": args}) + "\n")
prefix = "https://github.com/gitleaks/gitleaks/releases/download/"
src = Path(os.environ["FAKE_RELEASES"]) / args[-1][len(prefix):]
if not args[-1].startswith(prefix) or not src.is_file():
    sys.exit(22)
shutil.copyfile(src, args[args.index("-o") + 1])
'''

FAKE_RENDER = r'''#!/usr/bin/env python3
"""Fake render-units for bin/fleet.test.py: writes deterministic unit files
from the host settings it is handed through FLEET_HOST_CONFIG. Every other mode
(`jobs --json`, the job table pin-daemons and status read) is the REAL
agent-daemons.py, copied beside this file, so those cases are judged against
the real table of this synthetic tree."""
import argparse, json, os, sys
from pathlib import Path
if sys.argv[1:2] != ["render-units"]:
    real = Path(os.path.realpath(__file__)).with_name("real-agent-daemons.py")
    os.execv(sys.executable, [sys.executable, "-B", str(real), *sys.argv[1:]])
ap = argparse.ArgumentParser()
ap.add_argument("cmd", choices=["render-units"])
ap.add_argument("--units", choices=["refresh", "all"], required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--host-config")
a = ap.parse_args()
h = json.loads(Path(os.environ["FLEET_HOST_CONFIG"]).read_text())
if os.environ.get("FLEET_SERVICE_BACKEND") == "launchd":
    # The launchd shape: the refresh plist under the host's prefix, and with
    # --units all a re-render of every job plist already installed. FAKE_RENDER_REV
    # changes the bytes, as a new tree's templates would.
    import plistlib
    pfx, rev = h.get("launchd_prefix", "com.agent-fleet"), os.environ.get("FAKE_RENDER_REV", "1")
    shim = f"{h['fleet_checkout']}/systemd/agent-daemons.py"
    def plist(label, argv):
        (Path(a.out) / f"{label}.plist").write_bytes(plistlib.dumps(
            {"Label": label, "ProgramArguments": argv, "FakeRender": f"{rev} {h['agents_root']}"}))
    plist(f"{pfx}.daemons-refresh", [sys.executable, shim, "refresh"])
    la = Path(os.environ["HOME"]) / "Library" / "LaunchAgents"
    for f in sorted(la.glob(f"{pfx}.*.*.plist")) if a.units == "all" else []:
        job, agent = f.name[len(pfx) + 1:-len(".plist")].split(".")
        if job not in ("session", "stall-watchdog"):
            plist(f.name[:-len(".plist")], [sys.executable, shim, "exec", "--log", f"{agent}.log", "--",
                                            sys.executable, "-u", f"{h['fleet_checkout']}/{job}.py"])
    sys.exit(0)
def unit(name, text):
    (Path(a.out) / name).write_text(f"# Rendered by the fake render-units for agents_root={h['agents_root']}\n" + text)
unit("agent-daemons-refresh.service",
     f"[Service]\nType=oneshot\nExecStart=/usr/bin/python3 {h['fleet_checkout']}/systemd/agent-daemons.py refresh\n")
unit("agent-daemons-refresh.timer", "[Timer]\nOnBootSec=5min\n[Install]\nWantedBy=timers.target\n")
if a.units == "all":
    unit("agent-sched@.service", "[Service]\nExecStart=/usr/bin/python3 -u sched.py\n[Install]\nWantedBy=default.target\n")
    unit("agent-slack-watch@.service", "[Service]\nExecStart=/usr/bin/python3 -u watch.py\n[Install]\nWantedBy=default.target\n")
'''

# The gitleaks installer picks its pin by `uname -s`-`uname -m`. Every case runs
# it as on Linux x86_64, so the same assertions hold on a Mac; the platform-pick
# case sets FAKE_UNAME_S and FAKE_UNAME_M.
FAKE_UNAME = r'''#!/bin/sh
case "$1" in
  -s) echo "${FAKE_UNAME_S:-Linux}" ;;
  -m) echo "${FAKE_UNAME_M:-x86_64}" ;;
  *) echo "${FAKE_UNAME_S:-Linux}" ;;
esac
'''

FAKE_GATE = r'''#!/usr/bin/env python3
"""Fake leak gate for bin/fleet.test.py: a commit whose subject holds LEAKME is a
deny finding, printed in the real gate's `<sha12>:<where> <class>` form."""
import json, os, subprocess, sys
GATE = "@GATE@"
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps({"tool": "leak_gate", "gate": GATE, "argv": args, "cwd": os.getcwd()}) + "\n")
if os.environ.get("FAKE_LEAK_RC"):
    sys.exit(int(os.environ["FAKE_LEAK_RC"]))
if args[:1] == ["--range"]:
    log = subprocess.run(["git", "log", "--format=%H %s", args[1]], capture_output=True, text=True, check=True).stdout
    hits = [ln.split()[0] for ln in log.splitlines() if "LEAKME" in ln]
    for sha in hits:
        print(f"{sha[:12]}:(message):1 deny#7")
    print(f"leak-gate: {len(hits)} finding(s)" if hits else "leak-gate: clean")
    sys.exit(1 if hits else 0)
'''

# The daemon config variables a check reads to find ITS agent's daemon config:
# the scheduler's, each transport's watcher's (relay is working and not enabled
# for ada) and the stall watchdog's.
DAEMON_VARS = ("SCHED_CONFIG", "SLACK_WATCH_CONFIG", "RELAY_WATCH_CONFIG", "STALL_WATCHDOG_CONFIG")

# The synthetic scheduled-tasks check: its last line names the context it ran
# in, and with FAKE_CHECK_ENV set it records the daemon config variables it was
# handed, so check-all's environment is read from the check's own process.
FAKE_SCHED_CHECK = r'''#!/usr/bin/env python3
import json, os
print('installed: scheduled-tasks v1')
if os.environ.get("FAKE_CHECK_ENV"):
    with open(os.environ["FAKE_CHECK_ENV"], "w") as f:
        json.dump({k: os.environ.get(k) for k in @VARS@}, f)
print(f"ctx={os.environ.get('FLEET_CONTEXT_ROOT')} cfg={os.environ.get('CLAUDE_CONFIG_DIR')}")
'''

SLACK = {"schema": 1, "name": "slack", "status": "working", "line_prefix": "SLACK",
         "kinds": ["channel", "dm", "thread"],
         "ids": {"user": "^U[A-Z0-9]{6,}$", "conversation": "^[CDG][A-Z0-9]{2,20}$",
                 "message": "^[0-9]{9,10}\\.[0-9]{6}$"},
         "watch": {"script": "watch.py", "job": "slack-watch", "config_env": "SLACK_WATCH_CONFIG",
                   "follow_include": "^SLACK |^DAEMON-"}}
# A WORKING transport ada's install does not enable: no daemon of ada's may be
# expected (status) or pinned (pin-daemons) for it.
RELAY = {**SLACK, "name": "relay", "line_prefix": "RELAY",
         "watch": {**SLACK["watch"], "job": "relay-watch", "config_env": "RELAY_WATCH_CONFIG",
                   "follow_include": "^RELAY "}}
DISCORD = {"schema": 1, "name": "discord", "status": "placeholder", "line_prefix": "DISCORD",
           "kinds": ["channel", "dm", "thread"],
           "ids": {"user": "^[0-9]{17,20}$", "conversation": "^[0-9]{17,20}$", "message": "^[0-9]{17,20}$"},
           "watch": {"script": "watch.py", "job": "discord-watch", "config_env": "DISCORD_WATCH_CONFIG",
                     "follow_include": "^DISCORD "}}


def gitleaks_tgz(body=b"#!/bin/sh\necho 8.30.1\n"):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data, mode in (("LICENSE", b"MIT\n", 0o644), ("gitleaks", body, 0o755)):
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), mode
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


TGZ = gitleaks_tgz()


# The synthetic agent-revive's numbered steps, for status's charter rows: steps 1
# to 3, each a `### N.` heading, and a `### 4.1` that is a sub-heading and no step 4.
# The heading forms are the real skills' (agent-revive's and agent-health's `###
# N.`); tests/fixtures/charters/ holds the charters that point at them.
REVIVE_STEPS = ("\n## The path\n\n### 1. Connect\n\ntext\n\n### 2. Triage\n\ntext\n\n"
                "### 3. Sign in\n\ntext\n\n### 4.1 A sub-heading, not a step\n\ntext\n")
CHARTER_FIXTURES = REPO / "tests" / "fixtures" / "charters"


def skill(tree, name, extra=(), body=""):
    write(tree / ".claude/skills" / name / "SKILL.md",
          f"---\nname: {name}\nversion: 1\ndescription: >\n  Synthetic {name} for the fleet command's tests.\n---\n"
          + body)
    for rel, text in extra:
        write(tree / ".claude/skills" / name / rel, text)


def populate(o):
    write(o / "bin/fleet", SUBJECT.read_bytes(), 0o755)
    write(o / "bin/claude-attach", "#!/bin/sh\necho claude-attach stub\n", 0o755)
    for p in sorted(LIB.glob("*.py")):
        if not p.name.endswith(".test.py"):
            write(o / "lib/fleetlib" / p.name, p.read_bytes())
    write(o / ".gitignore", "node_modules/\n__pycache__/\n*.pyc\nbrowsers/\n")
    write(o / "README.md", "synthetic fleet\n")
    skill(o, "chat-transport")
    skill(o, "slack-communication", [("transport.json", json.dumps(SLACK)), ("watch.py", "print('stub')\n")])
    skill(o, "discord-communication", [("transport.json", json.dumps(DISCORD)), ("watch.py", "raise SystemExit(2)\n")])
    skill(o, "relay-communication", [("transport.json", json.dumps(RELAY)), ("watch.py", "print('stub')\n")])
    skill(o, "scheduled-tasks", [
        ("sched.py", "print('stub')\n"),
        ("installation/check", FAKE_SCHED_CHECK.replace("@VARS@", repr(DAEMON_VARS)))])
    skill(o, "stall-watchdog")
    skill(o, "demo-skill", [("installation/check", "#!/bin/sh\necho \"${FAKE_DEMO_LINE:-installed, but an older version}\"\n"
                                                   "exit \"${FAKE_DEMO_RC:-1}\"\n")])
    skill(o, "agent-revive", [("signin_driver/package.json", json.dumps({"name": "driver", "dependencies": {"playwright": "1.0.0"}})),
                              ("signin_driver/package-lock.json", '{"lockfileVersion": 3, "rev": 1}\n')],
          body=REVIVE_STEPS)
    # The REAL account picker: status's share rows are its answer, never a copy of its rule.
    skill(o, "agent-health", [(f, (REPO / ".claude/skills/agent-health" / f).read_text())
                              for f in ("pool_pick.py", "parse_usage.py")])
    write(o / "systemd/agent-daemons.py", FAKE_RENDER, 0o755)
    # The real job table, with an interpreter and a log directory no real unit
    # uses: a bin/fleet that wrote its own /usr/bin/python3 or state/daemons into
    # a drop-in instead of the table's would match an oracle holding the real
    # values, and only these make pin-daemons' case see that.
    real = (REPO / "systemd/agent-daemons.py").read_text()
    for old, new in (('PYTHON = "/usr/bin/python3"', f'PYTHON = "{TABLE_PYTHON}"'),
                     ('LOG_DIR = os.path.join("state", "daemons")', f'LOG_DIR = "{TABLE_LOG_DIR}"')):
        assert real.count(old) == 1, f"systemd/agent-daemons.py no longer holds {old!r} once: re-point this fixture"
        real = real.replace(old, new)
    write(o / "systemd/real-agent-daemons.py", real, 0o755)
    write(o / "tools/leak-gate/leak_gate.py", FAKE_GATE.replace("@GATE@", "v1.0.0-gate"), 0o755)
    write(o / "tools/leak-gate/gitleaks.version", f"v8.30.1 linux_x64 {hashlib.sha256(TGZ).hexdigest()}\n")
    write(o / "tools/leak-gate/install-gitleaks.sh", (REPO / "tools/leak-gate/install-gitleaks.sh").read_bytes(), 0o755)
    write(o / "templates/fleet.example.json", (REPO / "templates/fleet.example.json").read_bytes())
    os.symlink(OUTSIDE_FILE, o / "outside-link")


class Origin:
    """main: v1.0.0, U (untagged), A v1.1.0 (lockfile + gate change), B v1.2.0 (LIGHTWEIGHT),
    C v1.3.0 (CI fails), D v1.4.0 (LEAKME), E v1.5.0 (outside author), F v1.6.0 (LEAKME),
    G v1.7.0 (spoofed author, committed by GitHub's web interface), H v1.8.0 (spoofed
    author, committed by the outsider); side: S v1.9.0 off A (not on main)."""

    def __init__(self):
        self.path = o = SCRATCH / "origin"
        populate(o)
        git(o, "init", "-q", "-b", "main")
        git(o, "add", "-A")
        git(o, "commit", "-q", "-m", "base")
        git(o, "tag", "-a", "v1.0.0", "-m", "v1.0.0")
        self.base = git(o, "rev-parse", "HEAD")
        self.U = self.commit("untagged step", {"notes/u.txt": "u\n"})
        self.A = self.commit("lockfile and gate change", {
            LOCK: '{"lockfileVersion": 3, "rev": 2}\n',
            "tools/leak-gate/leak_gate.py": FAKE_GATE.replace("@GATE@", "v1.1.0-gate")}, tag="v1.1.0")
        self.B = self.commit("ordinary b", {"notes/b.txt": "b\n"})
        git(o, "tag", "v1.2.0")
        self.C = self.commit("ordinary c", {"notes/c.txt": "c\n"}, tag="v1.3.0")
        self.D = self.commit("LEAKME one", {"notes/d.txt": "d\n"}, tag="v1.4.0")
        self.E = self.commit("outside work", {"notes/e.txt": "e\n"}, tag="v1.5.0", who=OUTSIDER)
        self.F = self.commit("LEAKME two", {"notes/f.txt": "f\n"}, tag="v1.6.0")
        self.G = self.commit("spoofed, merged on the web", {"notes/g.txt": "g\n"}, tag="v1.7.0",
                             who=SPOOF, committer=GITHUB_WEB)
        self.H = self.commit("spoofed, pushed as committed", {"notes/h.txt": "h\n"}, tag="v1.8.0",
                             who=SPOOF, committer=OUTSIDER)
        git(o, "checkout", "-q", "-b", "side", self.A)
        self.S = self.commit("side work", {"notes/s.txt": "s\n"}, tag="v1.9.0")
        git(o, "checkout", "-q", "main")
        self.gh_state = {self.C: {"test": "failure"}}

    def commit(self, msg, files, tag=None, who=MAINT, committer=MAINT):
        for rel, text in files.items():
            write(self.path / rel, text)
        git(self.path, "add", "-A")
        git(self.path, "commit", "-q", "-m", msg, who=who, committer=committer)
        if tag:
            git(self.path, "tag", "-a", tag, "-m", tag)
        return git(self.path, "rev-parse", "HEAD")


def manifest_doc(skills=SKILLS, min_tag="v1.0.0", email=MAINT[1]):
    return {"schema": 1, "fleet": {"repo": "git@github.com:example/agent-fleet.git", "min_tag": min_tag},
            "skills": list(skills), "transports": {"enabled": ["slack"], "default": "slack"},
            "upstream": {"identity": {"name": MAINT[0], "email": email}, "deny_list": None,
                         "outside_pr_reviewer": "Ada"}}


class World:
    def __init__(self, tag="v1.0.0", host=True, readonly=True, manifest=None):
        self.root = Path(tempfile.mkdtemp(dir=SCRATCH, prefix="w-"))
        self.home = self.root / "home"
        self.agents = self.root / "agents"
        self.fleet = self.agents / "fleet"
        self.log = self.root / "calls.log"
        self.proc = self.root / "proc"
        self.show = write(self.root / "show.json", "{}")
        self.gh_state = write(self.root / "gh.json", json.dumps(ORIGIN.gh_state))
        self.host_json = self.home / ".config/agent-fleet/host.json"
        self.udir = self.home / ".config/systemd/user"
        write(self.root / "releases/v8.30.1/gitleaks_8.30.1_linux_x64.tar.gz", TGZ)
        self.fakes = self.root / "fakes"
        for name, text in (("systemctl", FAKE_SYSTEMCTL), ("gh", FAKE_GH), ("npm", FAKE_NPM),
                           ("curl", FAKE_CURL), ("uname", FAKE_UNAME)):
            write(self.fakes / name, text.replace("@PY@", PY), 0o755)
        self.home.mkdir()
        (self.agents / "claims").mkdir(parents=True)
        (self.agents / "claims").chmod(0o700)
        git(self.root, "clone", "-q", ORIGIN.path, self.fleet)
        git(self.fleet, "checkout", "-q", "--detach", tag)
        sub = self.fleet / Path(LOCK).parent
        write(sub / "node_modules" / ".fleet-lock.sha256",
              hashlib.sha256((sub / "package-lock.json").read_bytes()).hexdigest() + "\n")
        if readonly:
            chmod_tracked(self.fleet, False)
        if host:
            self.write_host()
        self.add_agent("ada", manifest)

    def write_host(self):
        write(self.host_json, json.dumps({"schema": 1, "agents_root": str(self.agents),
                                          "fleet_checkout": str(self.fleet),
                                          "claims_dir": str(self.agents / "claims")}))

    def add_agent(self, name, manifest=None):
        home = self.agents / name
        (home / ".claude").mkdir(parents=True, exist_ok=True)
        write(home / "project/.claude/fleet.json", json.dumps(manifest or manifest_doc()))
        return home

    def env(self, **extra):
        e = {"PATH": f"{self.fakes}:{os.environ.get('PATH', '/usr/bin:/bin')}", "LANG": "C.UTF-8",
             "HOME": str(self.home), "FAKE_RELEASES": str(self.root / "releases"),
             "USER": "tester", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": str(GITCONFIG),
             "FLEET_HOST_CONFIG": str(self.host_json),
             "FLEET_SERVICE_BACKEND": "systemd",
             "FLEET_SYSTEMCTL": str(self.fakes / "systemctl"), "FLEET_GH": str(self.fakes / "gh"),
             "FLEET_NPM": str(self.fakes / "npm"), "FLEET_PROC": str(self.proc),
             "FAKE_LOG": str(self.log), "FAKE_SYSTEMCTL_SHOW": str(self.show),
             "FAKE_GH_STATE": str(self.gh_state)}
        for k, v in extra.items():
            if v is None:
                e.pop(k, None)
            else:
                e[k] = str(v)
        return e

    def fleet_cmd(self, *args, tree=None, **extra):
        return subprocess.run([PY, str((tree or self.fleet) / "bin" / "fleet"), *map(str, args)],
                              cwd=self.root, env=self.env(**extra), capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=300)

    def calls(self, tool):
        if not self.log.exists():
            return []
        rows = [json.loads(ln) for ln in self.log.read_text().splitlines()]
        return [r for r in rows if r["tool"] == tool]

    def head(self):
        return git(self.fleet, "rev-parse", "HEAD")

    def worktree(self, name, tag):
        path = self.root / name
        git(self.fleet, "worktree", "add", "-q", "--detach", path, tag)
        return path

    def upgrades_log(self):
        return self.home / ".local/state/agent-fleet/upgrades.log"


# ------------------------------------------------------------------ link / unlink

@case
def link_creates_every_link_then_a_repeat_changes_nothing():
    w = World()
    skills = w.agents / "ada/.claude/skills"
    r = w.fleet_cmd("link", "ada")
    ok(r)
    for n in SKILLS:
        assert os.readlink(skills / n) == str(w.fleet / ".claude/skills" / n), n
    assert r.stdout.count("\nlinked ") + r.stdout.startswith("linked ") == len(SKILLS), r.stdout
    assert "NOTICE" in r.stdout and "/reload-skills" in r.stdout, "created the directory, so the notice is due"
    r = w.fleet_cmd("link", "ada")
    ok(r)
    assert r.stdout.strip() == "nothing changed", r.stdout


@case
def link_into_an_existing_skills_dir_keeps_synced_and_prints_no_notice():
    w = World()
    skills = w.agents / "ada/.claude/skills"
    write(skills / "synced/note.md", "harness-managed\n")
    before = snap(skills / "synced")
    r = w.fleet_cmd("link", "ada")
    ok(r)
    assert "NOTICE" not in r.stdout, r.stdout
    same(before, snap(skills / "synced"))
    assert all((skills / n).is_symlink() for n in SKILLS)


@case
def link_refuses_an_entry_that_is_not_a_fleet_link():
    for kind in ("directory", "foreign-symlink"):
        w = World()
        skills = w.agents / "ada/.claude/skills"
        if kind == "directory":
            write(skills / "demo-skill/SKILL.md", "an agent's own copy\n")
        else:
            (w.root / "elsewhere").mkdir()
            skills.mkdir(parents=True)
            os.symlink(w.root / "elsewhere", skills / "demo-skill")
        before = snap(w.agents / "ada/.claude")
        refused(w.fleet_cmd("link", "ada"), "is not a symlink into a fleet tree")
        same(before, snap(w.agents / "ada/.claude"), kind)


@case
def link_refuses_a_listed_skill_without_skill_md():
    w = World(manifest=manifest_doc(skills=SKILLS + ["ghost-skill"]))
    before = snap(w.agents / "ada/.claude")
    refused(w.fleet_cmd("link", "ada"), "skill ghost-skill: no SKILL.md")
    same(before, snap(w.agents / "ada/.claude"))


@case
def link_refuses_when_chat_transport_or_the_transport_skill_is_missing():
    for drop in ("chat-transport", "slack-communication"):
        w = World(manifest=manifest_doc(skills=[s for s in SKILLS if s != drop]))
        before = snap(w.agents / "ada/.claude")
        r = w.fleet_cmd("link", "ada")
        refused(r, drop)
        assert "skills" in r.stderr, r.stderr
        same(before, snap(w.agents / "ada/.claude"), drop)


@case
def link_refuses_a_tree_older_than_the_install_floor():
    w = World(manifest=manifest_doc(min_tag="v9.0.0"))
    before = snap(w.agents / "ada/.claude")
    refused(w.fleet_cmd("link", "ada"), "older than the install's min_tag v9.0.0")
    same(before, snap(w.agents / "ada/.claude"))


@case
def link_config_dir_form_links_a_person_config_dir():
    w = World()
    person = w.root / "person/.claude"
    person.mkdir(parents=True)
    ok(w.fleet_cmd("link", "--config-dir", person, "--install", w.agents / "ada/project"))
    for n in SKILLS:
        assert os.readlink(person / "skills" / n) == str(w.fleet / ".claude/skills" / n), n


@case
def link_from_a_canary_tree_retargets_and_unlink_removes():
    w = World()
    canary = w.worktree("canary", "v1.1.0")
    skills = w.agents / "ada/.claude/skills"
    ok(w.fleet_cmd("link", "ada", "--from", canary))
    assert all(os.readlink(skills / n) == str(canary / ".claude/skills" / n) for n in SKILLS)
    r = w.fleet_cmd("link", "ada")
    ok(r)
    assert r.stdout.count("retargeted ") == len(SKILLS), r.stdout
    assert all(os.readlink(skills / n) == str(w.fleet / ".claude/skills" / n) for n in SKILLS)


@case
def unlink_removes_only_fleet_links_then_a_repeat_changes_nothing():
    w = World()
    skills = w.agents / "ada/.claude/skills"
    ok(w.fleet_cmd("link", "ada"))
    write(skills / "synced/note.md", "harness-managed\n")
    (w.root / "elsewhere").mkdir()
    os.symlink(w.root / "elsewhere", skills / "foreign")
    write(skills / "plain.txt", "mine\n")
    keep = snap(skills / "synced", skills / "foreign", skills / "plain.txt")
    r = w.fleet_cmd("unlink", "ada")
    ok(r)
    assert r.stdout.count("unlinked ") == len(SKILLS), r.stdout
    assert not any(os.path.lexists(skills / n) for n in SKILLS)
    same(keep, snap(skills / "synced", skills / "foreign", skills / "plain.txt"))
    r = w.fleet_cmd("unlink", "ada")
    ok(r)
    assert r.stdout.strip() == "nothing changed", r.stdout


# ------------------------------------------------------------------ pin-daemons

DROPIN = """# Written by `fleet pin-daemons ada --from {src}`: this instance runs that
# fleet tree's code. `fleet pin-daemons ada --clear` removes this file.
[Service]
ExecStartPre=
ExecStartPre={python} {src}/systemd/agent-daemons.py rotate {agents}/ada/{logdir}/{job}.log
ExecStart=
ExecStart={python} -u {src}/.claude/skills/{skill}/{script}
"""
JOBS = [("sched", "scheduled-tasks", "sched.py"), ("slack-watch", "slack-communication", "watch.py")]


def inst(job, agent="ada"):
    """An instance unit name. Built, never written out: `<unit>@<agent>.service`
    has the shape of an e-mail address and trips the commit gate's public pattern."""
    return f"agent-{job}@{agent}.service"


UNITS = [inst("sched"), inst("slack-watch")]


@case
def pin_daemons_writes_the_exact_dropins_and_restarts_only_those_units():
    w = World()
    canary = w.worktree("canary", "v1.0.0")
    r = w.fleet_cmd("pin-daemons", "ada", "--from", canary)
    ok(r)
    for job, sk, script in JOBS:
        got = (w.udir / f"agent-{job}@ada.service.d/50-fleet.conf").read_text()
        assert got == DROPIN.format(src=canary, agents=w.agents, job=job, skill=sk, script=script,
                                    python=TABLE_PYTHON, logdir=TABLE_LOG_DIR), got
    assert sorted(p.name for p in w.udir.iterdir()) == [f"{u}.d" for u in UNITS], \
        "only the scheduler and the ENABLED transport's watcher are pinned"
    assert [c["argv"] for c in w.calls("systemctl")] == [["--user", "daemon-reload"], ["--user", "restart", *UNITS]]
    r = w.fleet_cmd("pin-daemons", "ada", "--from", canary)
    ok(r)
    assert r.stdout.strip() == "nothing changed" and len(w.calls("systemctl")) == 2, r.stdout


@case
def pin_daemons_clear_removes_the_dropins_then_a_repeat_changes_nothing():
    w = World()
    ok(w.fleet_cmd("pin-daemons", "ada", "--from", w.fleet))
    r = w.fleet_cmd("pin-daemons", "ada", "--clear")
    ok(r)
    assert not list(w.udir.glob("agent-*@ada.service.d")), list(w.udir.iterdir())
    assert [c["argv"] for c in w.calls("systemctl")][2:] == [["--user", "daemon-reload"], ["--user", "restart", *UNITS]]
    r = w.fleet_cmd("pin-daemons", "ada", "--clear")
    ok(r)
    assert r.stdout.strip() == "nothing changed" and len(w.calls("systemctl")) == 4


@case
def systemctl_gets_the_user_runtime_dir_when_the_caller_has_none():
    # `systemctl --user` finds the user's bus through XDG_RUNTIME_DIR. A shell
    # without a login session (su, ssh with no PAM session, a cron job) has none,
    # and then every --user call fails: the command defaults it to the user's
    # /run/user/<uid>, as systemd/agent-daemons.py does. A value the caller does
    # set is kept, never replaced.
    w = World()
    ok(w.fleet_cmd("pin-daemons", "ada", "--from", w.fleet, XDG_RUNTIME_DIR=None))
    seen = {c["xdg"] for c in w.calls("systemctl")}
    assert w.calls("systemctl") and seen == {f"/run/user/{os.getuid()}"}, seen
    w = World()
    ok(w.fleet_cmd("pin-daemons", "ada", "--from", w.fleet, XDG_RUNTIME_DIR="/tmp/fleet-test-xdg"))
    assert {c["xdg"] for c in w.calls("systemctl")} == {"/tmp/fleet-test-xdg"}


@case
def pin_daemons_refuses_a_source_that_is_not_a_fleet_tree():
    w = World()
    (w.root / "elsewhere").mkdir()
    before = snap(w.home)
    refused(w.fleet_cmd("pin-daemons", "ada", "--from", w.root / "elsewhere"), "not a fleet tree")
    same(before, snap(w.home))
    assert not w.calls("systemctl")


# ------------------------------------------------------------------ install

@case
def install_on_a_fresh_host_then_a_repeat_changes_nothing():
    write(OUTSIDE_FILE, "outside the tree\n", 0o644)
    w = World(host=False, readonly=False)
    assert writable_tracked(w.fleet), "control: a fresh clone has write bits to remove"
    r = w.fleet_cmd("install", "--agents-root", w.agents, FLEET_HOST_CONFIG=None)
    ok(r)
    assert json.loads(w.host_json.read_text()) == {
        "schema": 1, "agents_root": str(w.agents), "fleet_checkout": str(w.fleet),
        "claims_dir": str(w.agents / "claims")}
    assert git(w.fleet, "config", "--get", "core.hooksPath") == ".githooks"
    assert writable_tracked(w.fleet) == [], writable_tracked(w.fleet)
    assert OUTSIDE_FILE.stat().st_mode & 0o200, "chmod followed a tracked symlink: its TARGET lost its write bits"
    sub = w.fleet / Path(LOCK).parent
    assert [(c["argv"], c["cwd"]) for c in w.calls("npm")] == [] , "the stamp matches: no npm ci"
    gl = w.home / ".local/bin/gitleaks"
    assert subprocess.run([gl, "version"], capture_output=True, text=True).stdout.strip() == "8.30.1"
    assert [c["argv"][-1] for c in w.calls("curl")] == [
        "https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_linux_x64.tar.gz"]
    for n in ("fleet", "claude-attach"):
        assert os.readlink(w.home / ".local/bin" / n) == str(w.fleet / "bin" / n), n
    assert not w.calls("systemctl"), "--units none renders nothing"
    r = w.fleet_cmd("install", "--agents-root", w.agents, FLEET_HOST_CONFIG=None)
    ok(r)
    assert r.stdout.strip() == "nothing changed", r.stdout
    assert not w.calls("npm") and not w.calls("systemctl") and len(w.calls("curl")) == 1
    assert sub.is_dir()


@case
def install_runs_npm_ci_and_the_browser_install_when_the_stamp_is_stale():
    w = World(host=False, readonly=False)
    sub = w.fleet / Path(LOCK).parent
    write(sub / "node_modules/.fleet-lock.sha256", "0" * 64 + "\n")
    ok(w.fleet_cmd("install", "--agents-root", w.agents))
    assert [(c["argv"], c["cwd"], c["browsers"]) for c in w.calls("npm")] == [
        (["ci"], str(sub), None),
        (["exec", "--yes", "--", "playwright", "install", "chromium"], str(sub), str(sub / "browsers"))]
    assert writable_tracked(w.fleet) == []
    r = w.fleet_cmd("install", "--agents-root", w.agents)
    ok(r)
    assert r.stdout.strip() == "nothing changed" and len(w.calls("npm")) == 2, r.stdout


@case
def install_refuses_from_a_linked_worktree():
    w = World(host=False, readonly=False)
    wt = w.worktree("wt", "v1.0.0")
    before = snap(w.home, wt)
    refused(w.fleet_cmd("install", "--agents-root", w.agents, tree=wt), "linked worktree")
    same(before, snap(w.home, wt))
    assert not w.host_json.exists()
    assert not w.calls("npm") and not w.calls("systemctl")


@case
def install_refuses_a_claims_dir_that_is_not_mode_700():
    w = World(host=False, readonly=False)
    (w.agents / "claims").chmod(0o755)
    before = snap(w.home, w.fleet)
    refused(w.fleet_cmd("install", "--agents-root", w.agents), "mode 700")
    same(before, snap(w.home, w.fleet))
    # A claims path that is not a directory is refused the same way, never replaced.
    (w.agents / "claims").rmdir()
    write(w.agents / "claims", "not a directory\n")
    refused(w.fleet_cmd("install", "--agents-root", w.agents), "mode 700")
    assert (w.agents / "claims").read_text() == "not a directory\n"
    # ...and a symlink, even to a mode-700 directory: a link can be repointed
    # under running agents, which splits them into two claim spaces.
    (w.agents / "claims").unlink()
    (w.root / "real-claims").mkdir(mode=0o700)
    os.symlink(w.root / "real-claims", w.agents / "claims")
    refused(w.fleet_cmd("install", "--agents-root", w.agents), "mode 700")
    assert (w.agents / "claims").is_symlink()


@case
def install_creates_a_missing_claims_dir_with_mode_700():
    # The claims directory is the host's, at the path host.json records, so the
    # install that writes host.json creates it; claim.py never does. Run under
    # umask 022, where a plain mkdir would leave the directory 755.
    w = World(host=False, readonly=False)
    (w.agents / "claims").rmdir()
    old = os.umask(0o022)
    try:
        r = w.fleet_cmd("install", "--agents-root", w.agents)
    finally:
        os.umask(old)
    ok(r)
    claims = w.agents / "claims"
    assert claims.is_dir() and not claims.is_symlink(), "no claims directory after install"
    assert stat.S_IMODE(claims.stat().st_mode) == 0o700, oct(claims.stat().st_mode)
    assert f"created {claims}" in r.stdout, r.stdout
    r = w.fleet_cmd("install", "--agents-root", w.agents)
    ok(r)
    assert r.stdout.strip() == "nothing changed", r.stdout


@case
def install_refuses_a_gitleaks_download_that_fails_its_sha256():
    w = World(host=False, readonly=False)
    write(w.root / "releases/v8.30.1/gitleaks_8.30.1_linux_x64.tar.gz", gitleaks_tgz(b"#!/bin/sh\necho evil\n"))
    r = w.fleet_cmd("install", "--agents-root", w.agents)
    ok(r, 3)
    assert "checksum mismatch" in r.stderr, r.stderr
    assert not os.path.lexists(w.home / ".local/bin/gitleaks")


def old_units(w, names):
    old = w.root / "oldrepo"
    texts = {"agent-daemons-refresh.service": "OLD refresh service\n",
             "agent-daemons-refresh.timer": "OLD timer\n[Install]\nWantedBy=timers.target\n",
             "agent-sched@.service": "OLD sched\n[Install]\nWantedBy=default.target\n",
             "agent-slack-watch@.service": "OLD watch\n[Install]\nWantedBy=default.target\n"}
    w.udir.mkdir(parents=True)
    for n in names:
        write(old / n, texts[n])
        os.symlink(old / n, w.udir / n)
    return old


def wants(w, target, name, unit):
    d = w.udir / f"{target}.wants"
    d.mkdir(exist_ok=True)
    os.symlink(w.root / "oldrepo" / unit, d / name)


@case
def install_renders_over_a_symlink_replacing_the_link_and_leaving_its_target_alone():
    w = World(host=False, readonly=False)
    old = old_units(w, ["agent-daemons-refresh.service", "agent-daemons-refresh.timer"])
    wants(w, "timers.target", "agent-daemons-refresh.timer", "agent-daemons-refresh.timer")
    before = snap(old)
    ok(w.fleet_cmd("install", "--agents-root", w.agents, "--units", "refresh"))
    same(before, snap(old), "the old repository's files")
    for n in ("agent-daemons-refresh.service", "agent-daemons-refresh.timer"):
        dest = w.udir / n
        assert not dest.is_symlink(), n
        assert dest.read_text().startswith(f"# Rendered by the fake render-units for agents_root={w.agents}\n"), n
    calls = w.calls("systemctl")
    assert [c["argv"] for c in calls] == [
        ["--user", "disable", "agent-daemons-refresh.timer"],
        ["--user", "daemon-reload"],
        ["--user", "enable", "--now", "agent-daemons-refresh.timer"]], [c["argv"] for c in calls]
    assert calls[0]["units"]["agent-daemons-refresh.timer"] == "link", "disabled BEFORE the write"
    assert calls[2]["units"]["agent-daemons-refresh.timer"] == "file", "enabled AFTER the write"


@case
def install_disables_before_and_enables_after_and_never_starts_stops_or_restarts():
    w = World(host=False, readonly=False)
    names = ["agent-daemons-refresh.service", "agent-daemons-refresh.timer",
             "agent-sched@.service", "agent-slack-watch@.service"]
    old = old_units(w, names)
    for agent in ("ada", "grace"):
        wants(w, "default.target", f"agent-sched@{agent}.service", "agent-sched@.service")
    wants(w, "default.target", inst("slack-watch"), "agent-slack-watch@.service")
    wants(w, "timers.target", "agent-daemons-refresh.timer", "agent-daemons-refresh.timer")
    before = snap(old)
    ok(w.fleet_cmd("install", "--agents-root", w.agents, "--units", "all"))
    instances = [inst("sched"), inst("sched", "grace"), inst("slack-watch")]
    calls = w.calls("systemctl")
    assert [c["argv"] for c in calls] == [
        ["--user", "disable", "agent-daemons-refresh.timer", *instances],
        ["--user", "daemon-reload"],
        ["--user", "enable", *instances],
        ["--user", "enable", "--now", "agent-daemons-refresh.timer"]], [c["argv"] for c in calls]
    assert set(calls[0]["units"].values()) == {"link"}, calls[0]["units"]
    assert set(calls[2]["units"].values()) == {"file"}, calls[2]["units"]
    assert not [c for c in calls if {"start", "stop", "restart"} & set(c["argv"])]
    for n in instances:
        tgt = os.readlink(w.udir / "default.target.wants" / n)
        assert tgt.startswith(str(w.udir)), f"{n} still names {tgt}"
    same(before, snap(old), "the old repository's files")
    r = w.fleet_cmd("install", "--agents-root", w.agents, "--units", "all")
    ok(r)
    assert r.stdout.strip() == "nothing changed" and len(w.calls("systemctl")) == 4, r.stdout


# The cases below judge what the rendered units SAY, which the fake render-units
# cannot show: it writes units of its own. real_render() puts this tree's real
# systemd/ (agent-daemons.py, the templates, the README the units cite) into the
# world's host checkout, and the units are rendered by `fleet install` itself.
REAL_UNITS = ["agent-daemons-refresh.service", "agent-daemons-refresh.timer", "agent-relay-watch@.service",
              "agent-sched@.service", "agent-slack-watch@.service"]
# systemd's own PATH for a user unit: the refresh job is run with it, never this shell's.
SYSTEMD_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
# The paths a rendered unit or plist names that NOTHING creates before its daemon
# first runs, so they need not exist when install returns. Every other path it
# names must exist then, or the daemon starts against a missing file the way
# T20c-8's refresh job did. Each entry is (pattern, why); an entry added here
# without its reason, or broadened past it, hides that class of defect.
RUNTIME_PATHS = [
    (r"{agents}/[^/]+/state/daemons(/[^/]+\.log)?",
     "a daemon's log and its directory: agent-daemons.py --install makes the directory, after "
     "fleet install, and the service manager creates the log at the daemon's first start"),
    (r"{home}/\.local/state/agent-fleet/daemons-refresh\.log",
     "the launchd refresh job's log: launchd creates it at the job's first run (install makes its directory)"),
    (r"{agents}/[^/]+/config/[^/]+\.env",
     "an agent's optional tunables: systemd's EnvironmentFile=- and the exec shim's --env-file "
     "read the file only when it is there"),
]
# The agent configs this world gives ada, as a host where her daemons run has
# them (the person writes them; `agent-daemons.py --install` starts no job without
# its config). Her install enables slack, so relay-watch has no instance of hers.
ADA_CONFIGS = ("config/scheduler.json", "config/slack-watch.json")
# The host settings forms each install case runs: FLEET_HOST_CONFIG unset (a
# host: the default file under HOME) and set to another file, relative to the
# directory install runs in (fleet_cmd's, the world root). The second is the
# one that sees bin/fleet name a fixed path instead of the file it writes, which
# the first cannot tell apart from the right answer. Inside HOME, so the
# temporary-directory sweep reads it as the world's own.
HOST_SETTINGS_FORMS = (None, "home/elsewhere/host.json")


def real_render(w):
    d = w.fleet / "systemd"
    for src in sorted((REPO / "systemd").iterdir()):
        if src.is_file() and not src.name.endswith(".test.py"):
            write(d / src.name, src.read_bytes(), 0o755 if src.suffix == ".py" else 0o644)
    for rel in ADA_CONFIGS:
        write(w.agents / "ada" / rel, "{}\n")


def install_tmpdir(w):
    """The TMPDIR install runs with: a directory of the world's that nothing else
    uses, so a rendered value taken from install's temporary files (the candidate
    host settings, the render's output directory, one added later) shows as a
    path under it."""
    tmp = w.root / "tmpdir"
    tmp.mkdir()
    return tmp


def unit_paths(text, agents):
    """Every absolute path a rendered systemd unit names, in any line but a
    comment: Exec* arguments, Environment= values, EnvironmentFile=-,
    append: and file:// targets, PATH-like lists. `%i` is expanded for each agent
    in `agents` (the template's instances); a `%i` path of a template with no
    instance in the world names nothing that runs."""
    out = set()
    for line in text.splitlines():
        if not line or line.startswith(("#", "[")) or "=" not in line:
            continue
        for tok in line.split("=", 1)[1].split():
            tok = tok.split("=", 1)[1] if "=" in tok else tok
            tok = tok.removeprefix("-").removeprefix("append:").removeprefix("file://")
            for p in (tok.split(":") if tok.startswith("/") else ()):
                if p.startswith("/"):
                    out.update({p.replace("%i", a) for a in agents} if "%i" in p else {p})
    return out


def plist_paths(d):
    """Every absolute path a rendered plist names: each string value starting
    with /, PATH-like lists split."""
    if isinstance(d, dict):
        return set().union(set(), *(plist_paths(v) for v in d.values()))
    if isinstance(d, list):
        return set().union(set(), *(plist_paths(v) for v in d))
    return {p for p in d.split(":") if p.startswith("/")} if isinstance(d, str) and d.startswith("/") else set()


def check_rendered_paths(w, texts, referenced, tmp, must_name):
    """The T20c-8 class, swept: (1) no rendered file names a path under a
    temporary directory - tempfile's, /tmp, /private/tmp, /var/folders, this
    test's $TMPDIR and install's own - except inside the world's HOME and agents
    root, which every test world keeps under /tmp, and this test's interpreter
    (FLEET_PYTHON, which CI keeps in a venv under its RUNNER_TEMP); nothing may be
    under install's own TMPDIR at all; (2) every path named exists after install
    returns, but RUNTIME_PATHS. `must_name` is positive evidence that the sweep saw
    the units: paths each rendered file set must name, so an extraction that
    found nothing cannot pass as a clean sweep."""
    for name, text in texts.items():
        assert str(tmp) not in text, f"{name} names a path under install's temporary directory {tmp}:\n{text}"
    absent = sorted(set(map(str, must_name)) - referenced)
    assert not absent, f"the path sweep did not see {absent} in the rendered files: {sorted(referenced)}"
    roots = [r for r in (tempfile.gettempdir(), "/tmp", "/private/tmp", "/var/folders",
                         os.environ.get("TMPDIR"), str(tmp)) if r]

    def under(p, root):
        return any(x == r or x.startswith(r.rstrip("/") + "/")
                   for x in (p, os.path.realpath(p)) for r in (root, os.path.realpath(root)))
    world = (str(w.home), str(w.agents))
    temporary = [p for p in sorted(referenced) if under(p, str(tmp)) or (
        any(under(p, r) for r in roots) and not any(under(p, x) for x in world)
        and p not in (PY, os.path.dirname(PY)))]
    assert not temporary, f"rendered files name paths under a temporary directory: {temporary}"
    runtime = [(re.compile(pat.format(agents=re.escape(str(w.agents)), home=re.escape(str(w.home)))), why)
               for pat, why in RUNTIME_PATHS]
    missing = [p for p in sorted(referenced) if not os.path.exists(p) and not any(rx.fullmatch(p) for rx, _ in runtime)]
    assert not missing, f"rendered files name paths that do not exist after install returns: {missing}"


@case
def install_renders_units_that_name_the_host_settings_it_writes():
    # T20c-8. The rendered units carry FLEET_HOST_CONFIG, and their daemons read
    # that file at every start. Install renders while READING a candidate host
    # settings file in a temporary directory (REFUSE BEFORE THE FIRST WRITE), so
    # a unit naming the file the render read names a file that is gone when
    # install returns, and the refresh timer exits 3 every five minutes. With no
    # FLEET_HOST_CONFIG set, as on a host, the file install writes is the default
    # path under HOME, and every unit must name THAT file, which must exist; with
    # it set to another file, relative or not, every unit names that file.
    for form in HOST_SETTINGS_FORMS:
        install_names_the_host_settings_under_systemd(form)


def install_names_the_host_settings_under_systemd(form):
    w = World(host=False, readonly=False)
    real_render(w)
    tmp = install_tmpdir(w)
    r = w.fleet_cmd("install", "--agents-root", w.agents, "--units", "all", FLEET_HOST_CONFIG=form, TMPDIR=tmp,
                    FLEET_PYTHON=PY)
    ok(r)
    permanent = w.root / form if form else w.home / ".config/agent-fleet/host.json"
    assert permanent.is_file(), f"FLEET_HOST_CONFIG={form}: install wrote no {permanent}"
    rendered = {p.name: p.read_text() for p in sorted(w.udir.iterdir()) if p.is_file()}
    assert sorted(rendered) == REAL_UNITS, sorted(rendered)
    for name, text in rendered.items():
        named = [l.split("=", 2)[2] for l in text.splitlines() if l.startswith("Environment=FLEET_HOST_CONFIG=")]
        if name.endswith(".service"):
            assert named == [str(permanent)], \
                f"FLEET_HOST_CONFIG={form}: {name}: FLEET_HOST_CONFIG {named}, wanted [{permanent}]"
    instances = {"agent-sched@.service": ["ada"], "agent-slack-watch@.service": ["ada"]}
    referenced = set().union(*(unit_paths(t, instances.get(n, [])) for n, t in rendered.items()))
    check_rendered_paths(w, rendered, referenced, tmp, must_name=[
        permanent, w.fleet / "systemd/agent-daemons.py", w.fleet / ".claude/skills/scheduled-tasks/sched.py",
        w.agents / "ada/.claude", w.agents / "ada/config/scheduler.json", w.agents / "ada/state/daemons/sched.log"])
    # The refresh job itself, run as its unit runs it (the T20c-8 repro): the
    # unit's Environment= lines over systemd's PATH and HOME, nothing of this
    # shell's. Before the fix this is exit 3, "the fleet is not installed on this
    # host (no <tmp>/fleet-host-.../host.json)". With the non-default form, a unit
    # that named no host settings would fall back to HOME's default file, which
    # is not there, so this run also sees the Environment= line go missing.
    unit = rendered["agent-daemons-refresh.service"].splitlines()
    env = dict(l[len("Environment="):].split("=", 1) for l in unit if l.startswith("Environment="))
    argv = next(l for l in unit if l.startswith("ExecStart=")).split("=", 1)[1].split()
    script = next(t for t in argv if t.endswith("/agent-daemons.py"))
    assert argv[argv.index(script) + 1:] == ["refresh"], argv
    seen = len(w.calls("systemctl"))
    p = subprocess.run([PY, script, "refresh", "--dry-run"], cwd=w.root, capture_output=True, text=True,
                       stdin=subprocess.DEVNULL, timeout=120,
                       env={"PATH": SYSTEMD_PATH, "HOME": str(w.home), "LANG": "C.UTF-8",
                            "FLEET_SERVICE_BACKEND": "systemd", "FLEET_SYSTEMCTL": str(w.fakes / "systemctl"),
                            "FLEET_PROC": str(w.proc), "FAKE_LOG": str(w.log), "FAKE_SYSTEMCTL_SHOW": str(w.show),
                            **env})
    assert p.returncode == 0, f"FLEET_HOST_CONFIG={form}: refresh as its unit runs it: exit {p.returncode}\n" \
                              f"{p.stdout}{p.stderr}"
    # Positive evidence the job got past its host settings: it asked for its jobs.
    assert [c for c in w.calls("systemctl")[seen:] if c["argv"][1:2] == ["list-units"]], \
        f"refresh exited 0 without listing its jobs: {w.calls('systemctl')[seen:]}"


# ------------------------------------------------------------------ upgrade

def refused_upgrade(w, args, reason, **extra):
    head, before = w.head(), snap(w.fleet)
    r = w.fleet_cmd("upgrade", *args, **extra)
    refused(r, reason)
    assert w.head() == head, "HEAD moved"
    same(before, snap(w.fleet), "the host checkout")
    assert not w.upgrades_log().exists(), "an upgrade was logged"
    return r


@case
def upgrade_refuses_a_dirty_tree_and_a_broken_mode():
    w = World()
    readme = w.fleet / "README.md"
    readme.chmod(0o644)
    write(readme, "edited through a link\n")
    readme.chmod(0o444)
    refused_upgrade(w, ["v1.1.0"], "not clean")
    w = World()
    (w.fleet / "README.md").chmod(0o644)
    refused_upgrade(w, ["v1.1.0"], "read-only mode is broken")


@case
def upgrade_refuses_an_unannotated_tag():
    refused_upgrade(World(), ["v1.2.0"], "not an annotated tag")


@case
def upgrade_refuses_a_tag_not_on_origin_main():
    refused_upgrade(World(), ["v1.9.0"], "not reachable from origin/main")


@case
def upgrade_refuses_a_tag_whose_ci_did_not_succeed():
    w = World()
    r = refused_upgrade(w, ["v1.3.0"], "CI has not succeeded")
    assert "test: completed/failure" in r.stderr, r.stderr
    assert w.calls("gh")[-1]["argv"] == ["api", f"repos/example/agent-fleet/commits/{ORIGIN.C}/check-runs?per_page=100"]


@case
def upgrade_refuses_a_tag_older_than_an_install_floor_even_with_rollback():
    w = World(tag="v1.1.0", manifest=manifest_doc(min_tag="v1.1.0"))
    refused_upgrade(w, ["v1.0.0", "--rollback"], "older than ada's install min_tag v1.1.0")


@case
def upgrade_refuses_an_older_tag_without_rollback_and_rolls_back_with_it():
    w = World(tag="v1.1.0")
    refused_upgrade(w, ["v1.0.0"], "older than the current v1.1.0")
    r = w.fleet_cmd("upgrade", "v1.0.0", "--rollback")
    ok(r)
    assert w.head() == ORIGIN.base and writable_tracked(w.fleet) == []
    assert w.upgrades_log().read_text().rstrip().endswith("v1.1.0 -> v1.0.0 by tester rollback")


@case
def upgrade_refuses_a_leak_finding_in_the_range():
    w = World()
    r = refused_upgrade(w, ["v1.4.0"], "leak backstop found 1 finding(s)")
    assert f"{ORIGIN.D[:12]}:(message):1 deny#7" in r.stdout, r.stdout
    assert [c["gate"] for c in w.calls("leak_gate")] == ["v1.0.0-gate"], "the CURRENT gate judged"


@case
def upgrade_refuses_a_leak_gate_without_a_verdict():
    # 3 is the gate's own "no verdict"; 1 with no finding line is a crash (Python
    # exits 1 on an uncaught exception), which an empty finding list would pass.
    for rc in ("3", "1"):
        w = World()
        head, before = w.head(), snap(w.fleet)
        r = w.fleet_cmd("upgrade", "v1.1.0", FAKE_LEAK_RC=rc)
        ok(r, 3)
        assert "no verdict" in r.stderr and w.head() == head, f"gate exit {rc}: {r.stderr}"
        same(before, snap(w.fleet), "the host checkout")


@case
def upgrade_proceeds_over_an_acked_leak_only():
    w = World()
    r = w.fleet_cmd("upgrade", "v1.4.0", "--ack-leak", ORIGIN.D[:10],
                    CLAUDE_CONFIG_DIR=w.agents / "ada/.claude")
    ok(r)
    assert w.head() == ORIGIN.D
    assert w.upgrades_log().read_text().rstrip().endswith(f"v1.0.0 -> v1.4.0 by ada ack-leak={ORIGIN.D}")
    w = World()
    r = refused_upgrade(w, ["v1.6.0", "--ack-leak", ORIGIN.D, "--reviewed-outside"], "1 finding(s)")
    assert f"{ORIGIN.F[:12]}:(message)" in r.stdout, r.stdout
    refused_upgrade(World(), ["v1.1.0", "--ack-leak", "0123456789abcdef"], "not a commit")


@case
def upgrade_refuses_outside_work_unless_reviewed():
    w = World()
    r = refused_upgrade(w, ["v1.5.0", "--ack-leak", ORIGIN.D],
                        "not authored and committed by a local install's upstream identity")
    assert f"{ORIGIN.E} {OUTSIDER[1]} {MAINT[1]}" in r.stderr, r.stderr
    assert not [c for c in w.calls("gh") if "pulls" in " ".join(c["argv"])]
    r = w.fleet_cmd("upgrade", "v1.5.0", "--ack-leak", ORIGIN.D, "--reviewed-outside")
    ok(r)
    assert w.head() == ORIGIN.E
    assert " reviewed-outside " in w.upgrades_log().read_text()


@case
def upgrade_refuses_a_spoofed_author_unless_reviewed():
    # The author field is text the outsider writes, and the maintainers' address is
    # public in every commit. A merge in GitHub's web interface is committed by
    # GitHub, and a contributor's own commit keeps the contributor as committer, so
    # the committer half of the check sends both to --reviewed-outside.
    for start, tag, sha, committer in (("v1.6.0", "v1.7.0", ORIGIN.G, GITHUB_WEB),
                                       ("v1.7.0", "v1.8.0", ORIGIN.H, OUTSIDER)):
        w = World(tag=start)
        assert git(w.fleet, "log", "-1", "--format=%ae", sha) == MAINT[1], "control: the author IS the maintainers' address"
        r = refused_upgrade(w, [tag], "upstream identity")
        assert f"{sha} {MAINT[1]} {committer[1]}" in r.stderr, r.stderr
        r = w.fleet_cmd("upgrade", tag, "--reviewed-outside")
        ok(r)
        assert w.head() == sha
        assert w.upgrades_log().read_text().rstrip().endswith(f"{start} -> {tag} by tester reviewed-outside")


@case
def upgrade_refuses_a_tag_that_origin_does_not_publish():
    # The host checkout's tags are shared with every development worktree, so any of
    # them can put an annotated tag on an origin/main commit: a release nobody
    # published. A tag counts only when origin lists the same tag object.
    w = World()
    git(w.fleet, "tag", "-a", "v3.0.0", "-m", "local only", ORIGIN.A)
    assert not git(ORIGIN.path, "tag", "-l", "v3.0.0"), "control: origin has no v3.0.0"
    refused_upgrade(w, ["v3.0.0"], "not published on origin")


@case
def ci_checks_are_exactly_the_ci_workflows_jobs():
    # `upgrade` requires every CI_CHECKS run to have succeeded on the tag: a ci.yml
    # job renamed without this tuple refuses every upgrade ("missing"), and a job
    # added there and not here is never required. Read from the source with ast,
    # never by running the subject.
    checks = [ast.literal_eval(n.value) for n in ast.parse(SUBJECT.read_text()).body
              if isinstance(n, ast.Assign) and [getattr(t, "id", None) for t in n.targets] == ["CI_CHECKS"]]
    assert len(checks) == 1, f"expected one CI_CHECKS assignment in {SUBJECT}, found {len(checks)}"
    lines = (REPO / ".github/workflows/ci.yml").read_text().splitlines()
    body = itertools.takewhile(lambda ln: not re.match(r"[^\s#]", ln), lines[lines.index("jobs:") + 1:])
    jobs = [m.group(1) for ln in body if (m := re.fullmatch(r"  ([A-Za-z0-9_-]+):\s*", ln))]
    assert "test" in jobs, f"control: the ci.yml parse finds its `test` job: {jobs}"
    assert sorted(checks[0]) == sorted(jobs), f"CI_CHECKS {checks[0]} != ci.yml jobs {jobs}"


def private_services_names(source):
    """Every `services._<name>` the source reads, by ast."""
    return sorted({n.attr for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Attribute)
                   and isinstance(n.value, ast.Name) and n.value.id == "services" and n.attr.startswith("_")})


@case
def fleet_reads_the_service_manager_through_the_librarys_public_functions_only():
    # A private fleetlib.services function is free to change shape under the
    # library's own tests, and a caller of one breaks with nothing red there: the
    # refresh rows read the last run's exit code through services.last_exit().
    # The control plants a private call in a copy of the source, so an empty
    # answer is the subject and not a walk that finds nothing.
    src = SUBJECT.read_text()
    assert private_services_names(src + "\nservices._print('x', 'user')\n") == \
        sorted(set(private_services_names(src)) | {"_print"}), "control: the walk finds a planted services._print"
    assert private_services_names(src) == [], f"{SUBJECT} calls private services names: {private_services_names(src)}"


@case
def upgrade_succeeds_restores_the_mode_and_a_second_run_changes_nothing():
    w = World()
    assert writable_tracked(w.fleet) == [], "control: the host checkout starts read-only"
    r = w.fleet_cmd("upgrade", "v1.1.0")
    ok(r)
    assert w.head() == ORIGIN.A
    assert writable_tracked(w.fleet) == [], writable_tracked(w.fleet)
    assert w.upgrades_log().read_text().rstrip().endswith("v1.0.0 -> v1.1.0 by tester")
    assert [c["argv"] for c in w.calls("gh")] == [
        ["api", f"repos/example/agent-fleet/commits/{ORIGIN.A}/check-runs?per_page=100"]]
    assert [c["gate"] for c in w.calls("leak_gate")] == ["v1.0.0-gate"], "the target's gate never ran"
    sub = w.fleet / Path(LOCK).parent
    assert [c["argv"][:1] for c in w.calls("npm")] == [["ci"], ["exec"]], "the lockfile changed"
    assert "lockfile and gate change" in r.stdout and "untagged step" in r.stdout, r.stdout
    assert (sub / "node_modules/playwright").is_dir()
    r = w.fleet_cmd("upgrade", "v1.1.0")
    ok(r)
    assert r.stdout.strip().endswith("nothing changed"), r.stdout
    assert len(w.upgrades_log().read_text().splitlines()) == 1


# ------------------------------------------------------------------ status

# The fake systemctl's `show` answers, keyed "<manager>:<unit>" (see FAKE_SYSTEMCTL).
WATCHDOG_SHOW = "system:claude-agent-ada-stall-watchdog.service"
AGENT_SHOW = "claude-agent-ada.service"
TIMER_SHOW = "user:agent-daemons-refresh.timer"
REFRESH_SHOW = "user:agent-daemons-refresh.service"
AGENT_UNIT = REPO / "templates" / "claude-agent.service.example"
# The boot message's sentence that names the follower; agent_unit_show(follower=False)
# deletes it, which is a unit whose follower path is genuinely missing.
FOLLOWER_SENTENCE = re.compile(r"Arm each under a persistent Monitor.*?follow <agent-name> <watch-job> 2>&1 \. ")


def systemd_show_value(command, runtime_dir):
    """What systemd prints under `systemctl show` for one Exec*= line of a unit
    file: the command split as systemd splits it (its quoting is the shell's for
    these lines), %t replaced by the manager's runtime directory, the words joined
    by single spaces with no quoting, between path= and ignore_errors=. Checked
    against a live agent unit on systemd 259: for each of its ExecStartPre,
    ExecStart and ExecStartPost lines this text's argv equals the one the manager
    printed, byte for byte."""
    words = shlex.split(command.lstrip("-@:+!").replace("%t", runtime_dir))
    return (f"{{ path={words[0]} ; argv[]={' '.join(words)} ; ignore_errors={'yes' if command.startswith('-') else 'no'}"
            " ; start_time=[n/a] ; stop_time=[n/a] ; pid=0 ; code=(null) ; status=0/0 }")


def agent_unit_show(w, fleet=None, form="system", follower=True):
    """The fake manager's answer for ada's agent unit: THE REAL TEMPLATE
    (templates/claude-agent.service.example) in `form`, every placeholder filled
    for this world, its Exec lines serialized as systemd prints them. `fleet`
    stands for <fleet> in the boot message (default: the agents root's systemd/
    link into the host checkout, as status_world lays it out). follower=False
    deletes the boot message's follower sentence. Raises when the template no
    longer has the shape this relies on, so a case built on it cannot go green on
    a fixture that lost its subject."""
    keep, drop = (f"#{form}: ", "#user: " if form == "system" else "#system: ")
    text = AGENT_UNIT.read_text()
    if not follower:
        assert len(FOLLOWER_SENTENCE.findall(text)) == 1, "the template's follower sentence is not there exactly once"
        text = FOLLOWER_SENTENCE.sub("", text)
    subs = {"<agent-name>": "ada", "<Agent-Name>": "Ada", "<agents-root>": str(w.agents),
            "<fleet>": str(fleet or w.agents), "<project-dir>": "project", "<watch-job>": "slack-watch",
            "<watch-config-env>": "SLACK_WATCH_CONFIG", "<uid>": str(os.getuid()), "<agents-user>": "ada",
            "<auth-mode>": "login"}
    answer = {"LoadState": "loaded"}
    for line in text.splitlines():
        line = line[len(keep):] if line.startswith(keep) else line
        if line.startswith(drop) or line.startswith("#"):
            continue
        for k, v in subs.items():
            line = line.replace(k, v)
        assert not re.search(r"<[A-Za-z][A-Za-z-]*>", line), f"an unfilled placeholder: {line[:80]}"
        key, _, cmd = line.partition("=")
        if key in ("ExecStartPre", "ExecStart", "ExecStartPost"):
            assert key not in answer, f"the template has two {key} lines; the fake answers one"
            answer[key] = systemd_show_value(cmd, "/run" if form == "system" else f"/run/user/{os.getuid()}")
    post = answer.get("ExecStartPost", "")
    assert ";" in post and (not follower or post.index(";") < post.index("agent-daemons.py")), \
        "the boot message no longer names the follower after a `;`: this case no longer guards that class"
    return answer


def status_world(**kw):
    w = World(**kw)
    git(w.fleet, "config", "core.hooksPath", ".githooks")
    ok(w.fleet_cmd("link", "ada"))
    ok(w.fleet_cmd("adopt", w.agents / "ada/project"))
    (w.agents / "systemd").mkdir()
    os.symlink(w.fleet / "systemd/agent-daemons.py", w.agents / "systemd/agent-daemons.py")
    w.set_proc = lambda pid, script: write(w.proc / str(pid) / "cmdline",
                                           b"/usr/bin/python3\0-u\0" + str(script).encode() + b"\0")
    w.set_proc(4242, w.fleet / ".claude/skills/scheduled-tasks/sched.py")
    w.set_proc(4243, w.fleet / ".claude/skills/slack-communication/watch.py")
    # Each daemon's stdout and stderr: the job's log, as its unit opens it. The
    # status row reads them through the job table's own `status --json`.
    w.log_of = lambda job: w.agents / "ada" / TABLE_LOG_DIR / f"{job}.log"

    def set_fds(pid, target):
        fd = w.proc / str(pid) / "fd"
        if fd.is_symlink():
            fd.unlink()
        else:
            shutil.rmtree(fd, ignore_errors=True)
        fd.mkdir(parents=True)
        for n in ("1", "2"):
            os.symlink(target, fd / n)
    w.set_fds = set_fds
    for pid, job in ((4242, "sched"), (4243, "slack-watch")):
        write(w.log_of(job), "")
        w.set_fds(pid, w.log_of(job))
    w.answers = {
        f"user:{inst('sched')}": {"LoadState": "loaded", "ActiveState": "active", "MainPID": "4242"},
        f"user:{inst('slack-watch')}": {"LoadState": "loaded", "ActiveState": "active", "MainPID": "4243"},
        WATCHDOG_SHOW: {"LoadState": "loaded", "ExecStart": "{ path=/usr/bin/python3 ; argv[]=/usr/bin/python3 "
                        f"{w.fleet}/.claude/skills/stall-watchdog/watchdog.py ; ignore_errors=no }}"},
        "system:" + AGENT_SHOW: agent_unit_show(w),
        # The refresh timer waiting for its next run, and its oneshot's last run a success.
        TIMER_SHOW: {"LoadState": "loaded", "ActiveState": "active"},
        REFRESH_SHOW: {"LoadState": "loaded", "ActiveState": "inactive", "Result": "success", "ExecMainStatus": "0"}}
    w.save = lambda: write(w.show, json.dumps(w.answers))
    w.save()
    return w


def drift_lines(r):
    return [ln for ln in r.stdout.splitlines() if ln.startswith("DRIFT")]


@case
def status_is_green_on_a_host_with_nothing_drifted():
    w = status_world()
    r = w.fleet_cmd("status")
    ok(r)
    assert not drift_lines(r), r.stdout
    assert f"ok     ada: demo-skill -> {w.fleet}/.claude/skills/demo-skill" in r.stdout, r.stdout
    # T20c-9: the refresh job has rows of its own, so its failure is never silent.
    for line in ("ok     refresh timer agent-daemons-refresh.timer is active",
                 "ok     refresh job agent-daemons-refresh.service: last result success"):
        assert line in r.stdout, f"{line!r} not in\n{r.stdout}"
    # Each daemon's stdout and stderr were read, so no row says a replaced log
    # went unchecked; with one daemon's descriptors unreadable its row says so
    # (an unread descriptor is never an ok by silence) and nothing is drift.
    assert "not looked for" not in r.stdout, r.stdout
    shutil.rmtree(w.proc / "4242" / "fd")
    r = w.fleet_cmd("status", "ada")
    ok(r)
    assert (f"{inst('sched')} runs {w.fleet}/.claude/skills/scheduled-tasks/sched.py; its stdout and stderr were "
            "not read here, so a replaced log is not looked for") in r.stdout, r.stdout
    w.answers[WATCHDOG_SHOW] = {"LoadState": "not-found"}
    w.save()
    r = w.fleet_cmd("status", "ada")
    ok(r)
    assert "no watchdog unit" in r.stdout, r.stdout


@case
def status_reads_the_follower_from_the_agent_units_real_boot_message():
    # The follower path is in the agent unit's boot message, a `bash -c` script
    # in ExecStartPost with `;` long before the path. The manager's answer is the
    # REAL template rendered for ada and serialized as systemd prints it
    # (agent_unit_show), so the row is judged on the shape installed units have:
    # a reader that stops at the first `;` sees no follower in it. The follower
    # sentence deleted is a unit whose follower path is genuinely missing, and
    # that must be DRIFT: a row that cannot go red checks nothing. The control is
    # no agent unit at all, which has no follower to check and is not drift.
    w = status_world()
    r = w.fleet_cmd("status", "ada")
    ok(r)
    want = f"ok     ada: follower {w.agents}/systemd/agent-daemons.py -> {w.fleet}/systemd/agent-daemons.py"
    assert want in r.stdout.splitlines(), f"{want!r} not in\n{r.stdout}"
    w.answers["system:" + AGENT_SHOW] = agent_unit_show(w, follower=False)
    w.save()
    r = w.fleet_cmd("status", "ada")
    lines = drift_lines(r)
    assert r.returncode == 1 and lines == [f"DRIFT  ada: {AGENT_SHOW} names no follower path: its boot message "
                                           "arms no follower"], f"exit {r.returncode}: {lines}\n{r.stdout}"
    del w.answers["system:" + AGENT_SHOW]
    w.save()
    r = w.fleet_cmd("status", "ada")
    ok(r)
    assert f"ok     ada: no agent unit {AGENT_SHOW} is loaded, so no follower path to check" in r.stdout, \
        f"control: {r.stdout}"


@case
def status_has_no_refresh_row_on_a_host_without_agents_or_units():
    # An install with --units none and no agent (a personal computer, a trial)
    # has no refresh job by choice: no row, no exit 1, and no service manager
    # call (a host may have none). The control: the same host with the refresh
    # timer's unit file rendered gets the rows, so their absence above is the
    # missing file and nothing else.
    w = status_world()
    (w.agents / "ada/project/.claude/fleet.json").unlink()
    w.answers[TIMER_SHOW] = {"LoadState": "not-found"}
    w.save()
    r = w.fleet_cmd("status")
    ok(r)
    assert "refresh" not in r.stdout and "ada:" not in r.stdout, r.stdout
    assert not [c for c in w.calls("systemctl") if "agent-daemons-refresh.timer" in c["argv"]], w.calls("systemctl")
    write(w.udir / "agent-daemons-refresh.timer", "[Timer]\nOnBootSec=5min\n")
    r = w.fleet_cmd("status")
    lines = drift_lines(r)
    assert r.returncode == 1 and len(lines) == 1 and "agent-daemons-refresh.timer is not installed" in lines[0], \
        f"control: exit {r.returncode}: {lines}\n{r.stdout}"


@case
def status_prints_one_line_per_shared_account_and_drifts_on_a_refused_share():
    # Agents sharing an account must never be silent: one account for two agents
    # is a shared lease the picker allows, and status prints it as ok. Two
    # accounts for the same two agents make the same share one the picker
    # refuses, which is DRIFT. The control is one lease per agent: no line at all,
    # so the lines above are the share and nothing else in the world.
    w = status_world()
    pool, leases = w.root / "pool/pool.json", w.root / "pool/leases.json"
    acct = lambda u: {"username": u, "password": "fixture-not-real"}
    write(pool, json.dumps([acct("x@example.com")]))
    write(leases, json.dumps({"x@example.com": {"agents": ["ada", "bob"], "since": "2026-11-06T00:00Z"}}))
    write(w.agents / "ada/project" / SHARE_CONFIG,
          json.dumps({"accounts": {"pool_file": str(pool), "lease_file": str(leases)}}))
    r = w.fleet_cmd("status", "ada")
    ok(r)
    assert "ok     account pool: 2 agents share account x@example.com (ada, bob)" in r.stdout, r.stdout
    write(pool, json.dumps([acct("x@example.com"), acct("y@example.com")]))
    r = w.fleet_cmd("status", "ada")
    lines = drift_lines(r)
    assert r.returncode == 1 and len(lines) == 1 and "2 agents share account x@example.com" in lines[0] \
        and "REFUSED" in lines[0], f"exit {r.returncode}: {lines}"
    write(leases, json.dumps({"x@example.com": {"agent": "ada", "since": "2026-11-06T00:00Z"},
                              "y@example.com": {"agent": "bob", "since": "2026-11-06T00:00Z"}}))
    r = w.fleet_cmd("status", "ada")
    ok(r)
    assert "account pool" not in r.stdout, f"control: {r.stdout}"


SHARE_CONFIG = ".claude/skills/agent-revive/config.json"


@case
def status_reports_a_missing_watchdog_unit_as_drift_when_the_install_links_stall_watchdog():
    # stall-watchdog's own check says NOT INSTALLED for an agent with no watchdog
    # unit; status must not call the same state ok. The loaded unit is the
    # control: the same world is green with it, so the DRIFT below is the
    # missing unit and nothing else.
    w = status_world(manifest=manifest_doc(skills=SKILLS + ["stall-watchdog"]))
    r = w.fleet_cmd("status", "ada")
    ok(r)
    assert not drift_lines(r), r.stdout
    w.answers[WATCHDOG_SHOW] = {"LoadState": "not-found"}
    w.save()
    r = w.fleet_cmd("status", "ada")
    lines = drift_lines(r)
    assert r.returncode == 1, f"exit {r.returncode}\n{r.stdout}{r.stderr}"
    assert len(lines) == 1 and "claude-agent-ada-stall-watchdog.service" in lines[0] \
        and "not installed" in lines[0], lines


@case
def status_reads_the_agent_unit_from_the_user_manager_too():
    # The agent unit template has a user form. With the system manager knowing no
    # such unit, the follower row must come from the user manager: a follower path
    # outside the host checkout there is DRIFT, and the same path inside it is ok.
    # The control is the system-only read: with the user answer removed, the row
    # says no unit is loaded, so the DRIFT below is the user manager's answer.
    w = status_world()
    stale = w.agents / "old"
    write(stale / "systemd/agent-daemons.py", "old copy\n")
    del w.answers["system:" + AGENT_SHOW]
    w.answers["user:" + AGENT_SHOW] = agent_unit_show(w, fleet=stale, form="user")
    w.save()
    r = w.fleet_cmd("status", "ada")
    lines = drift_lines(r)
    assert r.returncode == 1 and len(lines) == 1 and f"follower {stale}/systemd/agent-daemons.py" in lines[0], \
        f"exit {r.returncode}: {lines}\n{r.stdout}{r.stderr}"
    w.answers["user:" + AGENT_SHOW] = agent_unit_show(w, fleet=w.fleet, form="user")
    w.save()
    r = w.fleet_cmd("status", "ada")
    ok(r)
    assert not drift_lines(r) and f"ok     ada: follower {w.fleet}/systemd/agent-daemons.py" in r.stdout, r.stdout
    del w.answers["user:" + AGENT_SHOW]
    w.save()
    r = w.fleet_cmd("status", "ada")
    ok(r)
    assert f"no agent unit {AGENT_SHOW} is loaded" in r.stdout, f"control: {r.stdout}"


@case
def status_checks_each_charter_step_pointer_against_the_host_checkouts_skill():
    # An install's charters point into fleet skills by step number, and an upgrade
    # that renumbers a skill strands them silently. The resolving charter is the
    # POSITIVE CONTROL: its two pointers at agent-revive (one wrapped across a line
    # break, one `'s` form) are found and counted, and its pointer at /release, a
    # skill the fleet tree does not carry, is not; a reader that found nothing
    # would print 0 and fail here rather than pass. The dangling charter names a
    # step 4 that exists only as the sub-heading 4.1 and a step of a skill that
    # numbers none: one DRIFT row each, naming the charter and its line. The last
    # leg is no charters directory: one ok row that says it checked nothing.
    w = status_world()
    agents_dir = w.agents / "ada/project/.claude/agents"
    write(agents_dir / "ada.md", (CHARTER_FIXTURES / "resolving.md").read_text())
    r = w.fleet_cmd("status", "ada")
    ok(r)
    want = (f"ok     ada: 2 step pointer(s) at fleet skills in 1 charter(s) under {agents_dir}, "
            "each a numbered step of its skill")
    assert want in r.stdout.splitlines(), f"{want!r} not in\n{r.stdout}"
    dangling = (CHARTER_FIXTURES / "dangling.md").read_text()
    write(agents_dir / "grace.md", dangling)
    line = lambda needle: dangling[:dangling.index(needle)].count("\n") + 1
    r = w.fleet_cmd("status", "ada")
    lines = drift_lines(r)
    assert r.returncode == 1 and lines == [
        f"DRIFT  ada: charter grace.md:{line('`/agent-revive` step 4')} points at /agent-revive step 4, which "
        "agent-revive's SKILL.md does not number (its steps: 1, 2, 3)",
        f"DRIFT  ada: charter grace.md:{line('`/demo-skill` step 1')} points at /demo-skill step 1, which "
        "demo-skill's SKILL.md does not number (its steps: none)"], f"exit {r.returncode}: {lines}\n{r.stdout}"
    assert "step pointer(s) at fleet skills" not in r.stdout, f"an ok summary beside the DRIFT rows:\n{r.stdout}"
    force_rmtree(agents_dir)
    r = w.fleet_cmd("status", "ada")
    ok(r)
    assert f"ok     ada: 0 step pointer(s) at fleet skills in 0 charter(s) under {agents_dir}, " \
           "each a numbered step of its skill" in r.stdout.splitlines(), r.stdout


def _host_off_tag(w):
    chmod_tracked(w.fleet, True)
    git(w.fleet, "checkout", "-q", "--detach", ORIGIN.U)
    chmod_tracked(w.fleet, False)


def _untracked(w):
    w.fleet.chmod(0o755)
    write(w.fleet / "stray.txt", "x\n")
    w.fleet.chmod(0o555)


def _canary(w):
    canary = w.worktree("canary", "v1.0.0")
    link = w.agents / "ada/.claude/skills/demo-skill"
    link.unlink()
    os.symlink(canary / ".claude/skills/demo-skill", link)


DRIFTS = [
    ("host checkout not at a tag", _host_off_tag, "at no release tag"),
    ("host checkout dirty", _untracked, "changed path"),
    ("host checkout writable", lambda w: (w.fleet / "README.md").chmod(0o644), "writable tracked path"),
    ("hooks path unset", lambda w: git(w.fleet, "config", "--unset", "core.hooksPath"), "core.hooksPath=<unset>"),
    ("link missing", lambda w: (w.agents / "ada/.claude/skills/demo-skill").unlink(), "demo-skill is not linked"),
    ("link into another tree", _canary, "demo-skill -> "),
    ("extra fleet link", lambda w: os.symlink(w.fleet / ".claude/skills/discord-communication",
                                              w.agents / "ada/.claude/skills/discord-communication"),
     "does not list"),
    ("min_tag above the host", lambda w: write(w.agents / "ada/project/.claude/fleet.json",
                                               json.dumps(manifest_doc(min_tag="v1.1.0"))), "min_tag v1.1.0"),
    ("daemon not running", lambda w: (w.answers[f"user:{inst('sched')}"].update(MainPID="0"),
                                      w.save()), f"{inst('sched')} is not running"),
    ("daemon runs the product copy", lambda w: w.set_proc(4243, w.agents / "ada/project/.claude/skills/slack-communication/watch.py"),
     f"{inst('slack-watch')} runs"),
    # The log moved away under a running watcher: it writes to the moved file,
    # and the follower reads the path. (The unlinked-inode form, which only a
    # real descriptor can show, is status_names_a_daemon_writing_to_a_replaced_log.)
    ("daemon writes to a moved log", lambda w: (write(w.log_of("slack-watch").with_name("moved.log"), ""),
                                                w.set_fds(4243, w.log_of("slack-watch").with_name("moved.log"))),
     f"{inst('slack-watch')} writes to a replaced log ("),
    ("watchdog runs the product copy", lambda w: (w.answers.update({WATCHDOG_SHOW: {
        "LoadState": "loaded", "ExecStart": f"{{ argv[]=/usr/bin/python3 {w.agents}/ada/project/watchdog.py ; }}"}}),
        w.save()), "stall-watchdog.service runs"),
    ("follower path outside the host checkout", lambda w: (
        (w.agents / "systemd/agent-daemons.py").unlink(),
        write(w.agents / "systemd/agent-daemons.py", "old copy\n")), "follower "),
    ("install without the session check", lambda w: write(w.agents / "ada/project/.claude/settings.json",
                                                          '{"attribution": {"commit": "", "pr": ""}}\n'),
     f"run `fleet adopt "),
    # T20c-9: a refresh timer that is not there, or not running, and a last
    # refresh that failed (T20c-8's exit 3), each one DRIFT row naming it.
    ("refresh timer not installed", lambda w: (w.answers.update({TIMER_SHOW: {"LoadState": "not-found"}}), w.save()),
     "agent-daemons-refresh.timer is not installed"),
    ("refresh timer stopped", lambda w: (w.answers[TIMER_SHOW].update(ActiveState="inactive"), w.save()),
     "agent-daemons-refresh.timer is inactive"),
    ("refresh service missing", lambda w: (w.answers.update({REFRESH_SHOW: {"LoadState": "not-found",
                                                                             "Result": "success"}}), w.save()),
     "agent-daemons-refresh.service is not installed"),
    ("last refresh failed", lambda w: (w.answers[REFRESH_SHOW].update(
        ActiveState="failed", Result="exit-code", ExecMainStatus="3"), w.save()),
     "agent-daemons-refresh.service: last run failed (exit-code, exit code 3)"),
]


@case
def status_exits_1_on_each_drift_kind_and_names_it():
    for name, mutate, needle in DRIFTS:
        w = status_world()
        mutate(w)
        r = w.fleet_cmd("status")
        lines = drift_lines(r)
        assert r.returncode == 1, f"{name}: exit {r.returncode}\n{r.stdout}{r.stderr}"
        assert len(lines) == 1 and needle in lines[0], f"{name}: {lines}"


@case
def status_names_a_daemon_writing_to_a_replaced_log():
    # The case: a `sed -i` over an agent's state/ rewrites the daemon logs, the
    # daemons keep appending to the old unlinked inodes, and the agent hears
    # nothing with every unit active. A REAL child appends to the scheduler's log
    # as a unit's StandardOutput=append: does; the fake /proc links its `fd` to the
    # child's real descriptors, because only a real descriptor shows an unlinked
    # inode. CONTROL: before the replacement the same world has no drift row. The
    # row must name the log, the deleted inode and the remedy.
    if not os.path.isdir("/proc/self/fd"):
        print("      NOT RUN: no /proc on this platform to link the fake one to; the moved-log row of "
              "status_exits_1_on_each_drift_kind_and_names_it runs here")
        return
    w = status_world()
    log = w.log_of("sched")
    with open(log, "a") as f:
        child = subprocess.Popen([PY, "-c", "import time\nwhile True:\n print('SCHED tick', flush=True)\n"
                                            " time.sleep(0.1)"], stdout=f, stderr=subprocess.STDOUT)
    try:
        fd = w.proc / "4242" / "fd"
        shutil.rmtree(fd)
        os.symlink(f"/proc/{child.pid}/fd", fd)
        deadline = time.monotonic() + 10
        while log.stat().st_size == 0 and time.monotonic() < deadline:
            time.sleep(0.05)
        r = w.fleet_cmd("status", "ada")
        ok(r)
        assert not drift_lines(r), f"control: the log appended to normally is no drift\n{r.stdout}"
        text = log.read_text()
        tmp = log.with_name(".sedXXXX")
        tmp.write_text(text.replace("tick", "tock"))
        os.replace(tmp, log)                      # what `sed -i` does
        r = w.fleet_cmd("status", "ada")
        # The remedy is refresh, never a plain restart: refresh first appends what
        # the daemon wrote to the replaced file, and a plain restart loses it. It is
        # named as agent-daemons.py's own DEAF row names it, with the units'
        # interpreter, which the job table reports.
        py = json.loads(subprocess.run([PY, "-B", str(w.fleet / "systemd/agent-daemons.py"), "jobs", "--json"],
                                       env=w.env(), capture_output=True, text=True, timeout=120).stdout)["python"]
        want = (f"DRIFT  ada: {inst('sched')} writes to a replaced log ({log}: the daemon's fd points at a "
                f"deleted inode); run refresh, which salvages what it wrote there and restarts it "
                f"({py} {w.fleet}/systemd/agent-daemons.py refresh)")
        assert r.returncode == 1 and drift_lines(r) == [want], f"exit {r.returncode}: {drift_lines(r)}\n{r.stdout}"
    finally:
        child.kill()
        child.wait()


# ------------------------------------------------------------------ resolvers

@case
def where_prints_paths_in_the_install_context():
    w = World()
    root = w.agents / "ada/project"
    r = w.fleet_cmd("where", "slack-communication", "config.json", FLEET_CONTEXT_ROOT=root)
    ok(r)
    assert r.stdout == f"{root}/.claude/skills/slack-communication/config.json\n", r.stdout
    r = w.fleet_cmd("where", "slack-communication", FLEET_CONTEXT_ROOT=root)
    assert r.stdout == f"{root}/.claude/skills/slack-communication\n", r.stdout
    refused(w.fleet_cmd("where", "slack-communication", "../../x", FLEET_CONTEXT_ROOT=root), "relative")
    ok(w.fleet_cmd("where", "slack-communication", FLEET_CONTEXT_ROOT=w.root), 3)


@case
def settings_prints_resolved_values_and_one_key():
    w = World()
    env = {"FLEET_CONTEXT_ROOT": w.agents / "ada/project"}
    r = w.fleet_cmd("settings", **env)
    ok(r)
    s = json.loads(r.stdout)
    assert s["house_rules"]["questions_per_message"] == 1 and s["conventions"]["release"] is None, s
    assert w.fleet_cmd("settings", "fleet.min_tag", **env).stdout == "v1.0.0\n"
    assert w.fleet_cmd("settings", "house_rules.times.cities.0.tz", **env).stdout == "UTC\n"
    assert json.loads(w.fleet_cmd("settings", "transports", **env).stdout) == {"enabled": ["slack"], "default": "slack"}
    refused(w.fleet_cmd("settings", "no.such.key", **env), "no setting no.such.key")


@case
def settings_refuses_the_unedited_template_naming_the_key():
    # SETUP step 4's first move is copying the template; `fleet settings` is how
    # the result is checked, so an unedited copy must not pass it. The control
    # is settings_prints_resolved_values_and_one_key: the same world loads a
    # filled-in manifest, so this refusal is the template's placeholders.
    w = World()
    root = w.agents / "ada/project"
    write(root / ".claude/fleet.json", (REPO / "templates/fleet.example.json").read_text())
    refused(w.fleet_cmd("settings", FLEET_CONTEXT_ROOT=root), "`fleet.repo`")


@case
def settings_refuses_a_convention_or_deny_list_that_names_no_file():
    # A convention skill, a convention doc or a deny list that is not in the install
    # passes every schema check; `fleet settings` is where SETUP step 4 checks the
    # manifest, so it is where the pointer is followed. Each refusal is followed by
    # creating the file it named and the next one appearing, and the last state is
    # the control: every file present, exit 0. A doc path with a read-time
    # placeholder is never followed, so its absence never refuses.
    m = manifest_doc()
    m["conventions"] = {"release": {"skill": "example-release"},
                        "branch_naming": {"doc": "docs/process.md", "section": "Branch names"},
                        "feature_checklist": {"doc": "docs/checklists/<feature-slug>.md"}}
    m["upstream"]["deny_list"] = ".claude/fleet/deny.txt"
    w = World(manifest=m)
    root = w.agents / "ada/project"
    env = {"FLEET_CONTEXT_ROOT": root}
    refused(w.fleet_cmd("settings", **env), "`conventions.release.skill`")
    write(root / ".claude/skills/example-release/SKILL.md", "---\nname: example-release\n---\n")
    refused(w.fleet_cmd("settings", **env), "`conventions.branch_naming.doc`")
    write(root / "docs/process.md", "# Process\n")
    refused(w.fleet_cmd("settings", **env), "`upstream.deny_list`")
    write(root / ".claude/fleet/deny.txt", "")
    ok(w.fleet_cmd("settings", **env))
    assert not (root / "docs/checklists").exists(), "the placeholder doc's directory exists, so the control proves nothing about it"


@case
def check_all_runs_every_linked_check_with_the_agent_context():
    w = World()
    ok(w.fleet_cmd("link", "ada"))
    r = w.fleet_cmd("check-all", "ada")
    ok(r, 1)
    rows = {ln.split()[0]: ln for ln in r.stdout.splitlines()[1:]}
    assert set(rows) == set(SKILLS), r.stdout
    assert "no check" in rows["chat-transport"]
    assert rows["demo-skill"].split()[1:3] == ["1", "stale"], rows["demo-skill"]
    assert rows["scheduled-tasks"].split()[1:3] == ["0", "installed"], rows["scheduled-tasks"]
    assert f"ctx={w.agents}/ada/project cfg={w.agents}/ada/.claude" in rows["scheduled-tasks"]
    ok(w.fleet_cmd("check-all", "ada", FAKE_DEMO_RC="0"))


@case
def check_all_prints_a_long_last_line_whole():
    # The agent skill's OK line runs past 160 characters into a NOT COVERED:
    # caveat. A row cut there ends in a bare "NOT", which reads as a failure on
    # an exit-0 row. The line is built so that a cut at 160 lands inside it.
    w = World()
    ok(w.fleet_cmd("link", "ada"))
    line = "OK - " + "x" * 151 + " NOT COVERED: whether the hourly timer is set"
    assert line[:160].endswith(" NOT"), "control: a cut at 160 would end the row in a bare NOT"
    r = w.fleet_cmd("check-all", "ada", FAKE_DEMO_RC="0", FAKE_DEMO_LINE=line)
    ok(r)
    row = next(ln for ln in r.stdout.splitlines() if ln.startswith("demo-skill "))
    assert row.endswith("  " + line), row


@case
def check_all_for_an_agent_reads_that_agents_daemon_configs_never_the_callers():
    # The caller is itself an agent whose session exports its own daemon
    # configs. A row for ada must be measured against ada's: the path each of
    # ada's units sets (<home>/config/<job>.json, the stall watchdog's unit
    # template's <home>/config/stall-watchdog.json), and nothing for a working
    # transport ada does not enable.
    # host.json names the agents root through a symlink: the units are rendered
    # from it AS WRITTEN and the watchdog check keys its record by the config
    # path string, so the realpath form would be a different, unrecorded file.
    w = World()
    written = w.root / "agents-as-written"
    os.symlink(w.agents, written)
    write(w.host_json, json.dumps({"schema": 1, "agents_root": str(written),
                                   "fleet_checkout": str(w.fleet), "claims_dir": str(w.agents / "claims")}))
    ok(w.fleet_cmd("link", "ada"))
    seen = w.root / "check-env.json"
    caller = {v: f"/tmp/fleet-caller/{v.lower()}.json" for v in DAEMON_VARS}
    ok(w.fleet_cmd("check-all", "ada", FAKE_CHECK_ENV=seen, **caller), 1)
    home = f"{written}/ada"
    assert json.loads(seen.read_text()) == {
        "SCHED_CONFIG": f"{home}/config/scheduler.json",
        "SLACK_WATCH_CONFIG": f"{home}/config/slack-watch.json",
        "RELAY_WATCH_CONFIG": None,
        "STALL_WATCHDOG_CONFIG": f"{home}/config/stall-watchdog.json"}, seen.read_text()
    # The stall watchdog's path is a fact of its unit template, not of bin/fleet.
    unit = (REPO / ".claude/skills/stall-watchdog/installation/agent-stall-watchdog.service.example").read_text()
    assert "\nEnvironment=STALL_WATCHDOG_CONFIG=<agents-root>/<agent>/config/stall-watchdog.json\n" in unit, \
        "the watchdog unit template moved its config: re-point bin/fleet's WATCHDOG_CONFIG and this case"
    # The skill lets an install put the watchdog config anywhere; a unit that
    # names one is the authority over the template's path.
    write(w.show, json.dumps({WATCHDOG_SHOW: {"LoadState": "loaded", "Environment":
                                              "TMUX_TMPDIR=/run/claude-tmux-ada "
                                              "STALL_WATCHDOG_CONFIG=/tmp/fleet-elsewhere/ada-watchdog.json"}}))
    ok(w.fleet_cmd("check-all", "ada", FAKE_CHECK_ENV=seen, **caller), 1)
    assert json.loads(seen.read_text())["STALL_WATCHDOG_CONFIG"] == "/tmp/fleet-elsewhere/ada-watchdog.json"
    # Control: with no agent named the caller checks its OWN install, so its own
    # values reach the check. This is also what proves the dump above is read
    # from the check's process: the same plumbing carries the caller's values here.
    seen.unlink()
    ok(w.fleet_cmd("check-all", FAKE_CHECK_ENV=seen, FLEET_CONTEXT_ROOT=w.agents / "ada/project", **caller), 1)
    assert json.loads(seen.read_text()) == caller, seen.read_text()


@case
def leak_scan_delegates_to_the_gate_and_passes_its_exit_code():
    w = World()
    ok(w.fleet_cmd("leak-scan", "--tree", w.root / "home"))
    assert w.calls("leak_gate")[-1]["argv"] == ["--tree", str(w.root / "home")]
    ok(w.fleet_cmd("leak-scan", "--history", FAKE_LEAK_RC="1"), 1)
    assert w.calls("leak_gate")[-1]["argv"] == ["--history"]
    w.host_json.unlink()
    r = w.fleet_cmd("leak-scan", "--history")
    ok(r, 3)
    assert len(w.calls("leak_gate")) == 2, "off a fleet host the gate is not run at all"


# ------------------------------------------------------------------ session-check / adopt
#
# `fleet session-check` runs as a project's SessionStart hook, and Claude Code
# adds a SessionStart hook's stdout to the session's context. So the contract
# is read off stdout alone: SILENT when the fleet is present, ONE notice naming
# its cause otherwise, exit 0 and nothing on stderr in every state (stderr and a
# non-zero exit reach the person at most, never the model). Each cause is
# asserted by its own needle AND by the absence of every other cause's needle,
# so a notice that fires for the wrong reason reds; the silent present-fleet
# world is the control that makes each notice mean its cause and nothing else.

REPO_URL = manifest_doc()["fleet"]["repo"]
INTEGRAL = "integral part of this repository's workflow"
BOOT = f"To install it, open Claude Code and say: Install agent-fleet from {REPO_URL} following its SETUP.md"
REPORT = "An agent reports this to the person who runs the host"
CAUSES = {"absent": "the agent-fleet repository is missing",
          "floor": "below this repository's fleet.min_tag",
          "unlinked": "not linked for the config dir",
          "generic": "the session check could not complete"}
SESSION_MARK = "agent-fleet:session-check"


def session_check(w, *args, cwd=None, **extra):
    """`fleet session-check` as the hook runs it; asserts exit 0 and an empty
    stderr, whatever the state, and returns stdout."""
    env = w.env(**{"CLAUDE_CONFIG_DIR": w.agents / "ada/.claude", **extra})
    r = subprocess.run([PY, str(w.fleet / "bin/fleet"), "session-check", *map(str, args)],
                       cwd=cwd or w.root, env=env, capture_output=True, text=True,
                       stdin=subprocess.DEVNULL, timeout=60)
    ok(r)
    assert r.stderr == "", f"stderr reaches the person at most, never the session:\n{r.stderr}"
    return r.stdout


def only_cause(out, cause):
    """`out` is one notice, naming `cause` and no other, with the two lines every notice carries."""
    assert CAUSES[cause] in out, f"no {cause} notice:\n{out!r}"
    for other, needle in CAUSES.items():
        assert other == cause or needle not in out, f"the {cause} notice also names {other}:\n{out}"
    assert INTEGRAL in out and REPORT in out, out
    assert out.count("agent-fleet: ") == 1, f"not ONE notice:\n{out}"


def present(w):
    """The control world: ada's skills linked, the checkout at the manifest's min_tag."""
    ok(w.fleet_cmd("link", "ada"))
    assert session_check(w, "--project", w.agents / "ada/project") == ""
    return w.agents / "ada/project"


@case
def session_check_is_silent_with_the_fleet_present_and_names_a_missing_fleet():
    w = World()
    project = present(w)
    # No host settings: the fleet was never installed on this host.
    w.host_json.unlink()
    out = session_check(w, "--project", project)
    only_cause(out, "absent")
    assert BOOT in out, out
    assert f"git clone {REPO_URL} <agents-root>/fleet" in out and "fleet install" in out \
        and "fleet link" in out and "checkout --detach v1.0.0" in out, out
    assert str(w.host_json) in out, "the cause names the host settings path it looked at"
    # Host settings that name a checkout which is not there.
    gone = w.root / "gone-fleet"
    write(w.host_json, json.dumps({"schema": 1, "agents_root": str(w.agents), "fleet_checkout": str(gone),
                                   "claims_dir": str(w.agents / "claims")}))
    out = session_check(w, "--project", project)
    only_cause(out, "absent")
    assert BOOT in out and f"git clone {REPO_URL} {gone}" in out and str(gone) in out.split("\n")[0], out


@case
def session_check_names_a_checkout_below_min_tag_and_the_upgrade():
    w = World(manifest=manifest_doc(min_tag="v1.1.0"))
    ok(w.fleet_cmd("link", "ada", "--from", w.worktree("canary", "v1.1.0")))
    out = session_check(w, "--project", w.agents / "ada/project")
    only_cause(out, "floor")
    assert "fleet upgrade v1.1.0" in out and "v1.0.0" in out, out


@case
def session_check_names_unlinked_skills_and_the_link_command_for_the_config_dir():
    w = World()
    project = present(w)
    skills = w.agents / "ada/.claude/skills"
    # One skill not linked: the agent form of the remedy.
    (skills / "demo-skill").unlink()
    out = session_check(w, "--project", project)
    only_cause(out, "unlinked")
    assert "fleet link ada" in out and "demo-skill" in out and "scheduled-tasks" not in out, out
    # A link that resolves outside every fleet tree is not linked either.
    write(w.root / "elsewhere/demo-skill/SKILL.md", "---\nname: demo-skill\n---\n")
    os.symlink(w.root / "elsewhere/demo-skill", skills / "demo-skill")
    out = session_check(w, "--project", project)
    only_cause(out, "unlinked")
    assert "demo-skill" in out, out
    # A link into a fleet tree whose target holds no SKILL.md is not linked either.
    (skills / "demo-skill").unlink()
    os.symlink(w.fleet / "systemd", skills / "demo-skill")
    out = session_check(w, "--project", project)
    only_cause(out, "unlinked")
    assert "demo-skill" in out, out
    # A config dir that is no agent's: the --config-dir form, every name capped.
    person = w.root / "person/.claude"
    out = session_check(w, "--project", project, CLAUDE_CONFIG_DIR=person)
    only_cause(out, "unlinked")
    assert f"fleet link --config-dir {person} --install {project}" in out, out
    assert f"{len(SKILLS)} agent-fleet skill" in out and "more" in out, out


@case
def session_check_never_blocks_and_finds_the_project_as_the_hook_does():
    w = World()
    project = present(w)
    # The project root: $CLAUDE_PROJECT_DIR, else the git top level of the cwd.
    (project / "deep/er").mkdir(parents=True)
    git(project, "init", "-q")
    (w.agents / "ada/.claude/skills/demo-skill").unlink()
    only_cause(session_check(w, CLAUDE_PROJECT_DIR=project), "unlinked")
    only_cause(session_check(w, cwd=project / "deep/er"), "unlinked")
    # A directory with no install manifest: nothing at all.
    other = w.root / "unrelated"
    other.mkdir()
    assert session_check(w, CLAUDE_PROJECT_DIR=other) == ""
    assert session_check(w, "--project", w.root / "no-such-dir") == ""
    # A corrupt manifest, and a manifest missing its fleet block: the generic
    # notice, exit 0 (session_check asserts it).
    for text in ("{not json", json.dumps({"schema": 1})):
        write(project / ".claude/fleet.json", text)
        only_cause(session_check(w, "--project", project), "generic")
    # Host settings that are not JSON: the fleet is absent as far as this host can tell.
    write(project / ".claude/fleet.json", json.dumps(manifest_doc()))
    write(w.host_json, "{")
    only_cause(session_check(w, "--project", project), "absent")


@case
def session_check_present_path_is_fast():
    # The budget is ~100 ms on a host (measured and reported with the task);
    # this bound is loose enough for a loaded CI runner and still catches a
    # check that started doing seconds of work.
    import statistics
    import time
    w = World()
    project = present(w)
    env = w.env(CLAUDE_CONFIG_DIR=w.agents / "ada/.claude")
    runs = []
    for _ in range(7):
        t = time.monotonic()
        r = subprocess.run([PY, str(w.fleet / "bin/fleet"), "session-check", "--project", str(project)],
                           env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
        runs.append(time.monotonic() - t)
        assert r.returncode == 0 and r.stdout == "" and r.stderr == "", r
    assert statistics.median(runs) < 1.0, f"median {statistics.median(runs):.3f}s over {runs}"


def adopt_hook(settings_path):
    """The command of the one SessionStart hook carrying the fleet's marker."""
    data = json.loads(Path(settings_path).read_text())
    found = [h for g in data.get("hooks", {}).get("SessionStart", []) for h in g.get("hooks", [])
             if SESSION_MARK in h.get("command", "")]
    assert len(found) == 1, f"{len(found)} fleet SessionStart hooks in {data}"
    return found[0]


def run_hook(command, home, **env):
    """The hook command as Claude Code runs a command hook: `sh -c`, with the
    session's environment (here: PATH, HOME and what the case passes)."""
    e = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home), "LANG": "C.UTF-8",
         **{k: str(v) for k, v in env.items()}}
    r = subprocess.run(["sh", "-c", command], env=e, capture_output=True, text=True,
                       stdin=subprocess.DEVNULL, timeout=60)
    assert r.returncode == 0, f"the hook exited {r.returncode}:\n{r.stdout}{r.stderr}"
    return r.stdout


@case
def adopt_creates_the_manifest_and_settings_then_a_repeat_changes_nothing():
    w = World()
    project = w.root / "fresh"
    project.mkdir()
    r = w.fleet_cmd("adopt", project)
    ok(r)
    man, settings = project / ".claude/fleet.json", project / ".claude/settings.json"
    assert man.read_bytes() == (REPO / "templates/fleet.example.json").read_bytes()
    assert stat.S_IMODE(man.stat().st_mode) == 0o644, oct(man.stat().st_mode)
    hook = adopt_hook(settings)
    assert set(json.loads(settings.read_text())) == {"hooks"}
    assert hook["type"] == "command" and isinstance(hook.get("timeout"), int) and 0 < hook["timeout"] <= 30, hook
    assert str(w.fleet) not in hook["command"] and str(w.root) not in hook["command"], \
        "the hook carries no install's or host's path"
    assert str(man) in r.stdout and str(settings) in r.stdout, r.stdout
    before = snap(project)
    r = w.fleet_cmd("adopt", project)
    ok(r)
    assert r.stdout.strip().split("\n")[-1] == "nothing changed", r.stdout
    assert "kept" in r.stdout and "never overwrites" in r.stdout, r.stdout
    same(before, snap(project))


@case
def adopt_merges_into_existing_settings_and_keeps_the_manifest():
    w = World()
    project = w.agents / "ada/project"
    mine = {"attribution": {"commit": "", "pr": ""},
            "hooks": {"SessionStart": [{"matcher": "startup", "hooks": [{"type": "command", "command": "echo mine"}]}],
                      "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "true"}]}]},
            "permissions": {"allow": ["Bash(git status)"]}}
    write(project / ".claude/settings.json", json.dumps(mine))
    man_before = snap(project / ".claude/fleet.json")
    r = w.fleet_cmd("adopt", project)
    ok(r)
    got = json.loads((project / ".claude/settings.json").read_text())
    added = got["hooks"]["SessionStart"].pop()
    assert got == mine, f"an existing key or hook changed:\n{got}"
    assert [h["command"] for h in added["hooks"]] == [adopt_hook_text(w)], added
    same(man_before, snap(project / ".claude/fleet.json"), "the existing manifest")
    assert "kept" in r.stdout, r.stdout


def adopt_hook_text(w):
    project = w.root / "probe-project"
    project.mkdir(exist_ok=True)
    ok(w.fleet_cmd("adopt", project))
    return adopt_hook(project / ".claude/settings.json")["command"]


@case
def adopt_refuses_settings_that_are_not_json_and_writes_nothing():
    w = World()
    project = w.root / "broken"
    write(project / ".claude/settings.json", '{"attribution": {"commit": ""},}\n')
    before = snap(project)
    refused(w.fleet_cmd("adopt", project), "not valid JSON")
    same(before, snap(project))
    assert not (project / ".claude/fleet.json").exists(), "refused, so the manifest was not written either"
    refused(w.fleet_cmd("adopt", w.root / "no-such-project"), "not a directory")


@case
def the_adopted_hook_falls_back_in_plain_sh_and_delegates_to_a_checkout():
    w = World()
    project = w.agents / "ada/project"
    ok(w.fleet_cmd("adopt", project))
    command = adopt_hook(project / ".claude/settings.json")["command"]
    bare = w.root / "bare-home"
    bare.mkdir()
    # No host settings anywhere this hook looks: the shell fallback, naming the
    # manifest's fleet.repo, with no Python on the way.
    out = run_hook(command, bare, CLAUDE_PROJECT_DIR=project)
    assert CAUSES["absent"] in out and INTEGRAL in out and BOOT in out and REPORT in out, out
    # Host settings naming a checkout that is gone: the same fallback.
    gone = write(w.root / "gone-host.json", json.dumps({"fleet_checkout": str(w.root / "gone")}))
    assert run_hook(command, bare, CLAUDE_PROJECT_DIR=project, FLEET_HOST_CONFIG=gone) == out
    # A manifest the shell cannot read a repo from: the generic wording.
    out2 = run_hook(command, bare, CLAUDE_PROJECT_DIR=w.root)
    assert CAUSES["absent"] in out2 and "Install agent-fleet from its repository" in out2, out2
    # A real checkout: the hook delegates to its session-check. Silent when
    # present; the session-check's own notice (not the fallback's) when a
    # skill is unlinked.
    ok(w.fleet_cmd("link", "ada"))
    host = dict(CLAUDE_PROJECT_DIR=project, FLEET_HOST_CONFIG=w.host_json, CLAUDE_CONFIG_DIR=w.agents / "ada/.claude")
    assert run_hook(command, bare, **host) == ""
    (w.agents / "ada/.claude/skills/demo-skill").unlink()
    out3 = run_hook(command, bare, **host)
    only_cause(out3, "unlinked")


# ------------------------------------------------------------------ main

# ------------------------------------------------------------------ launchd (macOS)

LPFX = "com.agent-fleet-test"


def lenv(w, **extra):
    """fleet_cmd keywords for the launchd backend: the fake launchctl of
    tests/fixtures/launchd (its state and calls under the world), and this
    interpreter as the jobs' one, so the Python floor holds."""
    return {"FLEET_SERVICE_BACKEND": "launchd", "FLEET_LAUNCHCTL": REPO / "tests/fixtures/launchd/fake-launchctl",
            "FAKE_LAUNCHD_STATE": w.root / "launchd.json", "FAKE_LAUNCHD_CALLS": w.root / "launchd-calls.log",
            "FLEET_PYTHON": PY, **extra}


def lcalls(w):
    f = w.root / "launchd-calls.log"
    return [c for c in f.read_text().splitlines() if not c.startswith("print")] if f.exists() else []


def lstate(w):
    f = w.root / "launchd.json"
    return json.loads(f.read_text()) if f.exists() else {}


def job_plist(w, job, agent="ada", pinned_from=None):
    """A job plist as agent-daemons.py --install leaves it: the exec shim, then the job."""
    label = f"{LPFX}.{job}.{agent}"
    argv = [PY, f"{w.fleet}/systemd/agent-daemons.py", "exec", "--log", f"{agent}.log", "--",
            PY, "-u", f"{w.fleet}/{job}.py"]
    data = plistlib.dumps({"Label": label, "ProgramArguments": argv, "RunAtLoad": True})
    if pinned_from:
        decl, _, rest = data.decode().partition("\n")
        data = f"{decl}\n<!-- fleet-pin: {pinned_from} -->\n{rest}".encode()
    return write(w.home / "Library/LaunchAgents" / f"{label}.plist", data), label


@case
def install_under_launchd_writes_plists_and_bootstraps_only_the_refresh_job():
    w = World(host=False, readonly=False)
    path, label = job_plist(w, "sched")
    r = w.fleet_cmd("install", "--agents-root", w.agents, "--units", "all", "--label-prefix", LPFX, **lenv(w))
    ok(r)
    h = json.loads(w.host_json.read_text())
    assert h.get("launchd_prefix") == LPFX, h
    refresh = w.home / "Library/LaunchAgents" / f"{LPFX}.daemons-refresh.plist"
    assert plistlib.loads(refresh.read_bytes())["ProgramArguments"][-1] == "refresh"
    assert b"FakeRender" in path.read_bytes(), "the installed job plist is re-rendered"
    assert lcalls(w) == [f"bootstrap gui/{os.getuid()} {refresh}"], lcalls(w)
    assert f"bootstrapped {LPFX}.daemons-refresh" in r.stdout, r.stdout
    assert not w.calls("systemctl"), "nothing reaches systemctl under launchd"
    # A repeat changes nothing. Without --label-prefix the prefix is KEPT: a
    # repeat that dropped it would rename every launchd job on the host.
    r = w.fleet_cmd("install", "--agents-root", w.agents, "--units", "all", **lenv(w))
    ok(r)
    assert r.stdout.strip() == "nothing changed" and json.loads(w.host_json.read_text()) == h, r.stdout
    # New templates (a new tree): the refresh job is booted out and in again, so
    # launchd reads its new plist; a job plist is rewritten and its job left alone.
    r = w.fleet_cmd("install", "--agents-root", w.agents, "--units", "all", **lenv(w, FAKE_RENDER_REV="2"))
    ok(r)
    assert lcalls(w)[1:] == [f"bootout gui/{os.getuid()}/{LPFX}.daemons-refresh",
                             f"bootstrap gui/{os.getuid()} {refresh}"], lcalls(w)
    assert b"<string>2 " in path.read_bytes() and f"rendered {path}" in r.stdout, r.stdout


@case
def install_under_launchd_keeps_a_pinned_plist():
    w = World(host=False, readonly=False)
    path, _ = job_plist(w, "sched", pinned_from="/tmp/fleet-canary")
    before = path.read_bytes()
    r = w.fleet_cmd("install", "--agents-root", w.agents, "--units", "all", "--label-prefix", LPFX, **lenv(w))
    ok(r)
    assert path.read_bytes() == before and f"kept {path}: pinned" in r.stdout, r.stdout
    # The control: the same plist unpinned is re-rendered, so the keep above is the pin.
    job_plist(w, "sched")
    r = w.fleet_cmd("install", "--agents-root", w.agents, "--units", "all", **lenv(w))
    ok(r)
    assert f"rendered {path}" in r.stdout, r.stdout


@case
def install_under_launchd_refuses_a_mac_the_jobs_cannot_run_on():
    w = World(host=False, readonly=False)
    (w.home / "Documents/agents/claims").mkdir(parents=True)
    (w.home / "Documents/agents/claims").chmod(0o700)
    old_python = write(w.root / "python3.9", "#!/bin/sh\necho 3 9\n", 0o755)
    for why, extra, args in (
            ("no gui domain", {}, ()),
            ("in a TCC folder", {}, ("--agents-root", w.home / "Documents/agents")),
            ("Python 3.9", {"FLEET_PYTHON": old_python}, ()),
            ("a bad prefix", {}, ("--label-prefix", "agentfleet"))):
        if why == "no gui domain":
            write(w.root / "launchd.json", json.dumps({"absent_domains": [f"gui/{os.getuid()}"]}))
        else:
            (w.root / "launchd.json").unlink(missing_ok=True)
        before = snap(w.home)
        r = w.fleet_cmd("install", *(args if "--agents-root" in args else ("--agents-root", w.agents, *args)),
                        "--units", "refresh", **lenv(w, **extra))
        assert r.returncode == 2, f"{why}: exit {r.returncode}\n{r.stdout}{r.stderr}"
        assert {"no gui domain": "automatic login", "in a TCC folder": "privacy protection",
                "Python 3.9": "is 3.9", "a bad prefix": "reverse-DNS"}[why] in r.stderr, f"{why}: {r.stderr}"
        same(before, snap(w.home), why)
        assert not lcalls(w), f"{why}: {lcalls(w)}"
    # The control: the same world with none of the four installs.
    ok(w.fleet_cmd("install", "--agents-root", w.agents, "--units", "refresh", **lenv(w)))


@case
def install_under_launchd_renders_plists_that_name_the_host_settings_it_writes():
    # T20c-8, launchd form: the refresh plist and every job plist install
    # re-renders name the host settings install WRITES, never the candidate the
    # render read; and the refresh job, run with its plist's environment, finds
    # the install (its job list comes from the prefix in those settings).
    for form in HOST_SETTINGS_FORMS:
        install_names_the_host_settings_under_launchd(form)


def install_names_the_host_settings_under_launchd(form):
    w = World(host=False, readonly=False)
    real_render(w)
    job_plist(w, "sched")
    tmp = install_tmpdir(w)
    r = w.fleet_cmd("install", "--agents-root", w.agents, "--units", "all", "--label-prefix", LPFX,
                    **lenv(w, FLEET_HOST_CONFIG=form, TMPDIR=tmp))
    ok(r)
    permanent = w.root / form if form else w.home / ".config/agent-fleet/host.json"
    assert permanent.is_file(), f"FLEET_HOST_CONFIG={form}: install wrote no {permanent}"
    la = w.home / "Library/LaunchAgents"
    plists = {p.name: p for p in sorted(la.glob(f"{LPFX}.*.plist"))}
    assert sorted(plists) == [f"{LPFX}.daemons-refresh.plist", f"{LPFX}.sched.ada.plist"], sorted(plists)
    for name, p in plists.items():
        named = plistlib.loads(p.read_bytes()).get("EnvironmentVariables", {}).get("FLEET_HOST_CONFIG")
        assert named == str(permanent), f"FLEET_HOST_CONFIG={form}: {name}: FLEET_HOST_CONFIG {named}, wanted {permanent}"
    referenced = set().union(*(plist_paths(plistlib.loads(p.read_bytes())) for p in plists.values()))
    check_rendered_paths(w, {n: p.read_text() for n, p in plists.items()}, referenced, tmp, must_name=[
        permanent, w.fleet / "systemd/agent-daemons.py", w.fleet / ".claude/skills/scheduled-tasks/sched.py",
        w.agents / "ada/.claude", w.agents / "ada/config/scheduler.json", w.agents / "ada/state/daemons/sched.log",
        w.home / ".local/state/agent-fleet/daemons-refresh.log"])
    refresh = plistlib.loads(plists[f"{LPFX}.daemons-refresh.plist"].read_bytes())
    assert refresh["ProgramArguments"][-1] == "refresh", refresh["ProgramArguments"]
    # launchd runs the job with the plist's environment and the user's HOME. The
    # fake launchctl through an absolute interpreter: the plist's PATH is not
    # this shell's, and on macOS its python3 may be the system's 3.9.
    launchctl = write(w.root / "launchctl", f"#!/bin/sh\nexec '{PY}' '{REPO}/tests/fixtures/launchd/fake-launchctl' \"$@\"\n", 0o755)
    p = subprocess.run([*refresh["ProgramArguments"], "--dry-run"], cwd=w.root, capture_output=True, text=True,
                       stdin=subprocess.DEVNULL, timeout=120,
                       env={"HOME": str(w.home), "LANG": "C.UTF-8", "FLEET_SERVICE_BACKEND": "launchd",
                            "FLEET_LAUNCHCTL": str(launchctl), "FAKE_LAUNCHD_STATE": str(w.root / "launchd.json"),
                            "FAKE_LAUNCHD_CALLS": str(w.root / "launchd-calls.log"),
                            **refresh["EnvironmentVariables"]})
    assert p.returncode == 0, f"FLEET_HOST_CONFIG={form}: refresh as its plist runs it: exit {p.returncode}\n" \
                              f"{p.stdout}{p.stderr}"
    # Positive evidence it read THOSE settings: their prefix found the job plist.
    assert f"DRY-RUN skip {LPFX}.sched.ada: not active" in p.stdout, f"refresh found no job:\n{p.stdout}{p.stderr}"


@case
def pin_daemons_under_launchd_pins_the_plists_and_restarts_by_bootout_then_bootstrap():
    w = World()
    write(w.host_json, json.dumps({**json.loads(w.host_json.read_text()), "launchd_prefix": LPFX}))
    canary = w.worktree("canary", "v1.0.0")
    paths_ = {job: job_plist(w, job)[0] for job in ("sched", "slack-watch")}
    for job in ("sched", "slack-watch"):
        subprocess.run([str(REPO / "tests/fixtures/launchd/fake-launchctl"), "bootstrap", f"gui/{os.getuid()}",
                        str(paths_[job])], env={**os.environ, **{k: str(v) for k, v in lenv(w).items()}}, check=True)
    (w.root / "launchd-calls.log").unlink()
    r = w.fleet_cmd("pin-daemons", "ada", "--from", canary, **lenv(w))
    ok(r)
    for job, sk, script in JOBS:
        d = plistlib.loads(paths_[job].read_bytes())
        argv = d["ProgramArguments"]
        assert argv[argv.index("--") + 1:] == [PY, "-u", f"{os.path.realpath(canary)}/.claude/skills/{sk}/{script}"], argv
        assert argv[1] == f"{w.fleet}/systemd/agent-daemons.py", "the exec shim stays the host checkout's"
        assert f"fleet-pin: {os.path.realpath(canary)}" in paths_[job].read_text()
    labels = [f"{LPFX}.sched.ada", f"{LPFX}.slack-watch.ada"]
    assert lcalls(w) == [x for lb in labels for x in (f"bootout gui/{os.getuid()}/{lb}",
                                                      f"bootstrap gui/{os.getuid()} {paths_[lb.split('.')[-2]]}")], lcalls(w)
    assert not [c for c in lcalls(w) if c.startswith("kickstart")], "a pin never restarts from the loaded plist"
    loaded = lstate(w)["loaded"][f"gui/{os.getuid()}"]
    assert loaded[labels[0]]["argv"][-1] == f"{os.path.realpath(canary)}/.claude/skills/scheduled-tasks/sched.py", \
        "launchd runs the pinned plist"
    r = w.fleet_cmd("pin-daemons", "ada", "--from", canary, **lenv(w))
    ok(r)
    assert r.stdout.strip() == "nothing changed", r.stdout
    r = w.fleet_cmd("pin-daemons", "ada", "--clear", **lenv(w))
    ok(r)
    for job in ("sched", "slack-watch"):
        assert "fleet-pin" not in paths_[job].read_text() and b"FakeRender" in paths_[job].read_bytes()
    r = w.fleet_cmd("pin-daemons", "ada", "--clear", **lenv(w))
    ok(r)
    assert r.stdout.strip() == "nothing changed", r.stdout


@case
def status_under_launchd_reads_jobs_watchdog_and_session_through_launchctl():
    w = status_world()
    write(w.host_json, json.dumps({**json.loads(w.host_json.read_text()), "launchd_prefix": LPFX}))
    uid = os.getuid()
    def job(dom, label, argv, pid):
        return {"path": f"/tmp/{label}.plist", "state": "running", "pid": pid, "runs": 1, "argv": argv, "env": {}}
    st = {"loaded": {f"gui/{uid}": {
        f"{LPFX}.sched.ada": job("gui", "s", [PY, "-u", str(w.fleet / ".claude/skills/scheduled-tasks/sched.py")], 4242),
        f"{LPFX}.slack-watch.ada": job("gui", "w", [PY, "-u", str(w.fleet / ".claude/skills/slack-communication/watch.py")], 4243),
        f"{LPFX}.session.ada": job("gui", "x", [PY, str(w.agents / "systemd/agent-daemons.py"), "follow", "ada", "sched"], 4300),
        # The refresh job between two runs (StartInterval): loaded, not running, its last exit 0.
        f"{LPFX}.daemons-refresh": {**job("gui", "r", [PY, str(w.fleet / "systemd/agent-daemons.py"), "refresh"], 0),
                                    "state": "not running", "last_exit": 0}},
        "system": {f"{LPFX}.stall-watchdog.ada": job("system", "y", [PY, str(w.fleet / ".claude/skills/stall-watchdog/watchdog.py")], 4400)}}}
    write(w.root / "launchd.json", json.dumps(st))
    r = w.fleet_cmd("status", "ada", **lenv(w))
    ok(r)
    assert not drift_lines(r), r.stdout
    for line in (f"ok     ada: {LPFX}.sched.ada runs {w.fleet}/.claude/skills/scheduled-tasks/sched.py",
                 f"ok     ada: {LPFX}.stall-watchdog.ada runs {w.fleet}/.claude/skills/stall-watchdog/watchdog.py",
                 f"ok     ada: follower {w.agents}/systemd/agent-daemons.py",
                 f"ok     refresh job {LPFX}.daemons-refresh is loaded",
                 f"ok     refresh job {LPFX}.daemons-refresh: last result success"):
        assert line in r.stdout, f"{line!r} not in\n{r.stdout}"
    del st["loaded"][f"gui/{uid}"][f"{LPFX}.sched.ada"]
    write(w.root / "launchd.json", json.dumps(st))
    r = w.fleet_cmd("status", "ada", **lenv(w))
    lines = drift_lines(r)
    assert r.returncode == 1 and len(lines) == 1 and f"{LPFX}.sched.ada is not running" in lines[0], lines
    # T20c-9 under launchd: the refresh job's last exit code, read from launchctl.
    st["loaded"][f"gui/{uid}"][f"{LPFX}.sched.ada"] = job("gui", "s", [PY, "-u", str(w.fleet / ".claude/skills/scheduled-tasks/sched.py")], 4242)
    st["loaded"][f"gui/{uid}"][f"{LPFX}.daemons-refresh"]["last_exit"] = 3
    write(w.root / "launchd.json", json.dumps(st))
    r = w.fleet_cmd("status", "ada", **lenv(w))
    lines = drift_lines(r)
    assert r.returncode == 1 and len(lines) == 1 \
        and f"refresh job {LPFX}.daemons-refresh: last run failed (exit-code, exit code 3)" in lines[0], \
        f"exit {r.returncode}: {lines}\n{r.stdout}{r.stderr}"
    del st["loaded"][f"gui/{uid}"][f"{LPFX}.daemons-refresh"]
    write(w.root / "launchd.json", json.dumps(st))
    r = w.fleet_cmd("status", "ada", **lenv(w))
    lines = drift_lines(r)
    assert r.returncode == 1 and len(lines) == 1 and f"refresh job {LPFX}.daemons-refresh is not installed" in lines[0], \
        f"exit {r.returncode}: {lines}\n{r.stdout}{r.stderr}"


@case
def gitleaks_installer_takes_the_pin_of_this_platform():
    # One line, one <platform> <sha256> pair per platform; the tag stays the
    # file's first word for its other readers. A platform with no pair is
    # refused naming the ones there are.
    w = World(host=False, readonly=False)
    builds = {p: gitleaks_tgz(f"#!/bin/sh\necho 8.30.1\n# {p} build\n".encode())
              for p in ("darwin_arm64", "linux_arm64")}
    for p, tgz in builds.items():
        write(w.root / f"releases/v8.30.1/gitleaks_8.30.1_{p}.tar.gz", tgz)
    gl = w.root / "gl"
    write(gl / "install-gitleaks.sh", (REPO / "tools/leak-gate/install-gitleaks.sh").read_bytes(), 0o755)
    write(gl / "gitleaks.version", f"v8.30.1 linux_x64 {hashlib.sha256(TGZ).hexdigest()} "
                                   f"linux_arm64 {hashlib.sha256(builds['linux_arm64']).hexdigest()} "
                                   f"darwin_arm64 {hashlib.sha256(builds['darwin_arm64']).hexdigest()}\n")
    for uname_s, uname_m, want in (("Darwin", "arm64", "darwin_arm64"), ("Linux", "x86_64", "linux_x64"),
                                   ("Linux", "aarch64", "linux_arm64"), ("Darwin", "x86_64", None)):
        dest = w.root / f"bin-{uname_s}-{uname_m}"
        n = len(w.calls("curl"))
        r = subprocess.run(["bash", str(gl / "install-gitleaks.sh"), str(dest)], capture_output=True, text=True,
                           env=w.env(FAKE_UNAME_S=uname_s, FAKE_UNAME_M=uname_m), timeout=120)
        if want is None:
            assert r.returncode == 3 and "pins linux_x64 linux_arm64 darwin_arm64" in r.stderr, r.stderr
            assert not (dest / "gitleaks").exists() and len(w.calls("curl")) == n
            continue
        assert r.returncode == 0, f"{uname_s}-{uname_m}: {r.stderr}"
        assert w.calls("curl")[-1]["argv"][-1].endswith(f"gitleaks_8.30.1_{want}.tar.gz")
        body = (dest / "gitleaks").read_bytes()
        for p in builds:
            assert (f"# {p} build".encode() in body) == (want == p), \
                f"{uname_s}-{uname_m}: the platform's own tarball is installed"
    # A pair whose sha256 is wrong for its tarball is refused on that platform only.
    write(gl / "gitleaks.version", f"v8.30.1 linux_x64 {hashlib.sha256(TGZ).hexdigest()} darwin_arm64 {'0' * 64}\n")
    r = subprocess.run(["bash", str(gl / "install-gitleaks.sh"), str(w.root / "bin-bad")], capture_output=True,
                       text=True, env=w.env(FAKE_UNAME_S="Darwin", FAKE_UNAME_M="arm64"), timeout=120)
    assert r.returncode == 3 and "checksum mismatch" in r.stderr and not (w.root / "bin-bad/gitleaks").exists(), r.stderr
    # A tarball whose binary reports another version, or cannot run on this machine at
    # all, passes its checksum and is still refused with exit 3, before anything
    # reaches <dest-dir>: nothing is installed.
    problems = []
    for n, (label, body) in enumerate((("another version", b"#!/bin/sh\necho 8.29.0\n"),
                                       ("cannot run here", b"\x7fELF\x02\x01\x01\x00\x00\x00\x00 other machine\n"))):
        tgz = gitleaks_tgz(body)
        write(w.root / "releases/v8.30.1/gitleaks_8.30.1_linux_arm64.tar.gz", tgz)
        write(gl / "gitleaks.version", f"v8.30.1 linux_arm64 {hashlib.sha256(tgz).hexdigest()}\n")
        dest = w.root / f"bin-refused-{n}"
        r = subprocess.run(["bash", str(gl / "install-gitleaks.sh"), str(dest)], capture_output=True, text=True,
                           env=w.env(FAKE_UNAME_S="Linux", FAKE_UNAME_M="aarch64"), timeout=120)
        if (dest / "gitleaks").exists():
            problems.append(f"{label}: a binary that failed its version check was installed")
        if r.returncode != 3 or "not 8.30.1: refusing to install" not in r.stderr:
            problems.append(f"{label}: exit {r.returncode}, not 3 refusing the version: {r.stderr.strip()}")
    assert not problems, "\n".join(problems)


# ------------------------------------------------------------------ the two-user install (F17)

OTHER_UID = os.getuid() + 4242


def as_other(w, *args, tree=None, **extra):
    """bin/fleet run believing it is the user OTHER_UID: os.geteuid answers that
    (so the checkout, which this test owns, is another user's), while every
    access check stays real. No second uid exists without root; this is the
    seam's whole reach, and it lives in the test, not in bin/fleet."""
    code = ("import os, runpy, sys; uid = int(sys.argv[1]); os.geteuid = lambda: uid; sys.argv = sys.argv[2:]; "
            "runpy.run_path(sys.argv[0], run_name='__main__')")
    return subprocess.run([PY, "-c", code, str(OTHER_UID), str((tree or w.fleet) / "bin" / "fleet"), *map(str, args)],
                          cwd=w.root, env=w.env(**extra), capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=300)


def lock_down(w, tree, chain):
    """The checkout as an administrator leaves it for the agents user: nothing in
    it writable (.git included), and the directories `chain` above it read-only
    (/tmp, above SCRATCH, is sticky). Returns the undo."""
    w.log.touch()   # the fakes append to it; the world root may be read-only
    for d, dirs, files in os.walk(tree):
        for q in [d] + [os.path.join(d, f) for f in files]:
            if not os.path.islink(q):
                os.chmod(q, stat.S_IMODE(os.lstat(q).st_mode) & ~0o222)
    for d in chain:
        d.chmod(0o555)

    def undo():
        for d in chain:
            d.chmod(0o755)
        chmod_tracked(tree, True)
        for d, dirs, files in os.walk(tree / ".git"):
            for q in [d] + [os.path.join(d, f) for f in files]:
                os.chmod(q, stat.S_IMODE(os.lstat(q).st_mode) | 0o200)
    return undo


@case
def install_parts_refuse_the_wrong_user_and_change_nothing():
    w = World(host=False)
    git(w.fleet, "config", "core.hooksPath", ".githooks")
    before = snap(w.home, w.fleet)
    for args, who, needle in (
            (("--part", "checkout"), "other", "its part runs as that user"),
            (("--part", "all"), "other", "--part checkout, then the agents user --part agents"),
            (("--part", "agents"), "owner", "is yours"),
            (("--part", "agents"), "other", "change nothing in the fleet checkout")):
        r = (as_other(w, "install", "--agents-root", w.agents, *args) if who == "other"
             else w.fleet_cmd("install", "--agents-root", w.agents, *args))
        refused(r, needle)
        same(before, snap(w.home, w.fleet), f"{args} as the {who}")
    # The control for the last refusal: it is the CHECKOUT the other user can
    # change (here: its parent chain and .git), not something else - locked down,
    # the same part goes through (next case).


def admin_checkout(w):
    """A second clone where an administrator keeps it: OUTSIDE the agents root
    (<world>/opt/agent-fleet, as /opt/agent-fleet on a host), its part done."""
    opt = w.root / "opt" / "agent-fleet"
    opt.parent.mkdir()
    git(w.root, "clone", "-q", ORIGIN.path, opt)
    git(opt, "checkout", "-q", "--detach", "v1.0.0")
    git(opt, "config", "core.hooksPath", ".githooks")
    sub = opt / Path(LOCK).parent
    write(sub / "node_modules" / ".fleet-lock.sha256",
          hashlib.sha256((sub / "package-lock.json").read_bytes()).hexdigest() + "\n")
    return opt


@case
def install_part_agents_writes_only_the_agents_users_files():
    w = World(host=False)
    opt = admin_checkout(w)
    # The control first: the World's own checkout sits IN the agents root, which
    # the agents user may write, so it could be renamed away - refused even locked
    # down. The same part on the checkout outside the root goes through.
    git(w.fleet, "config", "core.hooksPath", ".githooks")
    undo = lock_down(w, w.fleet, [w.root, SCRATCH])   # the agents root stays the agents user's
    try:
        refused(as_other(w, "install", "--agents-root", w.agents, "--part", "agents"),
                f"may write {w.agents}, so it can replace fleet")
    finally:
        undo()
    undo = lock_down(w, opt, [opt.parent, w.root, SCRATCH])
    try:
        before = snap(opt)
        r = as_other(w, "install", "--agents-root", w.agents, "--part", "agents", tree=opt)
        ok(r)
        assert json.loads(w.host_json.read_text())["fleet_checkout"] == str(opt), r.stdout
        assert os.readlink(w.home / ".local/bin/fleet") == str(opt / "bin/fleet")
        assert (w.home / ".local/bin/gitleaks").is_file(), "gitleaks is the agents user's"
        same(before, snap(opt), "the checkout")
        assert not w.calls("npm"), "npm ci is the checkout part's"
    finally:
        undo()
    # The checkout's part not done (its hooks unset) is refused, naming who does it.
    git(opt, "config", "--unset", "core.hooksPath")
    undo = lock_down(w, opt, [opt.parent, w.root, SCRATCH])
    try:
        refused(as_other(w, "install", "--agents-root", w.agents, "--part", "agents", tree=opt), "core.hooksPath")
    finally:
        undo()


@case
def install_part_checkout_does_the_owners_part_only():
    w = World(host=False, readonly=False)
    r = w.fleet_cmd("install", "--agents-root", w.agents, "--part", "checkout")
    ok(r)
    assert git(w.fleet, "config", "--get", "core.hooksPath") == ".githooks"
    assert writable_tracked(w.fleet) == [], "the checkout is read-only"
    assert not os.path.lexists(w.home / ".local/bin/fleet") and not w.calls("curl"), \
        "links and gitleaks are the agents part's"
    assert json.loads(w.host_json.read_text())["fleet_checkout"] == str(w.fleet), \
        "the owner's own host settings, for fleet upgrade and status"


@case
def upgrade_refuses_anyone_but_the_checkouts_owner():
    w = World()
    before = snap(w.fleet)
    r = as_other(w, "upgrade", "v1.1.0")
    refused(r, f"runs as the fleet checkout's owner, {pwd.getpwuid(os.getuid()).pw_name}")
    same(before, snap(w.fleet))
    assert not w.calls("gh"), "nothing is asked of GitHub before the owner check"


@case
def upgrade_faults_on_an_install_it_cannot_read():
    # An agent home the upgrading user cannot read holds a manifest whose min_tag
    # would be skipped in silence: a fault, nothing changed. The floor case is the
    # proof the floor is real: the same world, readable, refuses by it.
    w = World(tag="v1.1.0", manifest=manifest_doc(min_tag="v1.1.0"))
    refused_upgrade(w, ["v1.0.0", "--rollback"], "older than ada's install min_tag v1.1.0")
    home = w.agents / "ada"
    head, before = w.head(), snap(w.fleet)
    home.chmod(0o000)
    try:
        r = w.fleet_cmd("upgrade", "v1.0.0", "--rollback")
    finally:
        home.chmod(0o755)
    ok(r, 3)
    assert f"cannot be read" in r.stderr and str(home) in r.stderr, r.stderr
    assert w.head() == head
    same(before, snap(w.fleet), "the host checkout")


@case
def fleet_reads_an_administrators_checkout_through_safe_directory():
    # git refuses a repository another user owns unless safe.directory names it;
    # GIT_TEST_ASSUME_DIFFERENT_OWNER makes this test's own clone look like one.
    # The control: plain git in that state refuses, so status's ok is the
    # safe.directory bin/fleet passes and nothing else.
    w = status_world()
    plain = subprocess.run(["git", "-C", str(w.fleet), "status", "--porcelain"], capture_output=True, text=True,
                           env=w.env(GIT_TEST_ASSUME_DIFFERENT_OWNER="1"))
    assert plain.returncode != 0 and "dubious ownership" in plain.stderr, f"control: {plain.stderr}"
    r = w.fleet_cmd("status", "ada", GIT_TEST_ASSUME_DIFFERENT_OWNER="1")
    ok(r)
    assert "dubious" not in r.stderr and f"ok     host checkout {w.fleet} at v1.0.0" in r.stdout, r.stdout + r.stderr


# ------------------------------------------------------------------ trusted identities, the python key (F18)

def identities_file(w):
    return w.host_json.parent / "identities.json"


@case
def upgrade_ignores_an_identity_an_agent_added_to_its_manifest():
    # bob's install manifest names the outsider as its upstream identity: an edit
    # an agent can make. The identities file (the checkout owner's) lists only the
    # maintainers, so the outsider's commit is still outside work - refused, and
    # the ignored identity named. The control: with no file (the one-user form,
    # where the manifests are trusted) the same world goes through, so the refusal
    # is the file's doing and nothing else's.
    w = World()
    w.add_agent("bob", manifest_doc(email=OUTSIDER[1]))
    write(identities_file(w), json.dumps([MAINT[1]]))
    r = refused_upgrade(w, ["v1.5.0", "--ack-leak", ORIGIN.D], "upstream identity as this upgrade trusts them")
    assert f"WARNING: ignored {OUTSIDER[1]}, the upstream identity in the install manifest of bob" in r.stdout, r.stdout
    identities_file(w).unlink()
    r = w.fleet_cmd("upgrade", "v1.5.0", "--ack-leak", ORIGIN.D)
    ok(r)
    assert w.head() == ORIGIN.E and "NOTE: no " in r.stdout, r.stdout


@case
def upgrade_without_an_identities_file_is_refused_when_another_user_owns_the_agents_root():
    # The agents root is someone else's (another uid, faked for this one stat),
    # so its manifests are not this user's to trust and there is no file: refused,
    # naming the file and both ways to write it, before anything is asked of GitHub.
    w = World()
    code = ("import os, runpy, sys; real = os.stat; root = os.path.realpath(sys.argv[1]); other = int(sys.argv[2])\n"
            "def fake(p, *a, **k):\n"
            "    st = real(p, *a, **k)\n"
            "    if os.path.realpath(p) != root: return st\n"
            "    t = list(st[:10]); t[4] = other; return os.stat_result(t)\n"
            "os.stat = fake; sys.argv = sys.argv[3:]; runpy.run_path(sys.argv[0], run_name='__main__')")
    head, before = w.head(), snap(w.fleet)
    r = subprocess.run([PY, "-c", code, str(w.agents), str(OTHER_UID), str(w.fleet / "bin/fleet"), "upgrade", "v1.1.0"],
                       cwd=w.root, env=w.env(), capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=300)
    refused(r, "fleet identities --add <email>")
    assert w.head() == head and not w.calls("gh")
    same(before, snap(w.fleet))


def not_contributing():
    """An install manifest with no `upstream`: its agents do not commit to the fleet."""
    return {k: v for k, v in manifest_doc().items() if k != "upstream"}


@case
def upgrade_on_a_host_that_does_not_contribute_skips_the_outside_work_check():
    # The stranger's host: no install declares upstream, and the first install
    # wrote an empty identities file. Every release commit is the maintainers',
    # in no file of this host's, and the upgrade goes through without
    # --reviewed-outside, saying why it did not look. The controls show the skip
    # is the non-contributing state's doing: the same world with an install that
    # declares upstream, or with the checkout owner's file naming an identity,
    # refuses (an agent cannot switch the check off by deleting its upstream).
    w = World(manifest=not_contributing())
    write(identities_file(w), "[]\n")
    r = w.fleet_cmd("upgrade", "v1.1.0")
    ok(r)
    assert w.head() == ORIGIN.A, r.stdout
    assert "outside-work check skipped: no local install declares upstream" in r.stdout, r.stdout
    assert w.upgrades_log().read_text().rstrip().endswith("v1.0.0 -> v1.1.0 by tester")
    w = World(manifest=not_contributing())
    write(identities_file(w), json.dumps([MAINT[1]]))
    r = refused_upgrade(w, ["v1.5.0", "--ack-leak", ORIGIN.D], "upstream identity as this upgrade trusts them")
    assert "skipped" not in r.stdout, r.stdout


@case
def upgrade_on_a_contributing_host_refuses_outside_work_and_trusts_no_empty_file():
    # ada declares upstream. With the owner's file naming the maintainers, the
    # outsider's commit is outside work. With the file empty, the upgrade trusts
    # nobody: refused before GitHub is asked, naming how to add an identity.
    w = World()
    write(identities_file(w), json.dumps([MAINT[1]]))
    r = refused_upgrade(w, ["v1.5.0", "--ack-leak", ORIGIN.D], "upstream identity as this upgrade trusts them")
    assert f"{ORIGIN.E} {OUTSIDER[1]} {MAINT[1]}" in r.stderr and "skipped" not in r.stdout, r.stdout + r.stderr
    w = World()
    write(identities_file(w), "[]\n")
    refused_upgrade(w, ["v1.1.0"], "fleet identities --add <email>")
    assert not w.calls("gh"), "refused after GitHub was asked"


@case
def install_writes_the_trusted_identities_once_and_never_merges_a_manifest_again():
    w = World(host=False, readonly=False)
    ok(w.fleet_cmd("install", "--agents-root", w.agents))
    assert json.loads(identities_file(w).read_text()) == [MAINT[1]], identities_file(w).read_text()
    write(w.agents / "ada/project/.claude/fleet.json", json.dumps(manifest_doc(email=OUTSIDER[1])))
    r = w.fleet_cmd("install", "--agents-root", w.agents)
    ok(r)
    assert json.loads(identities_file(w).read_text()) == [MAINT[1]], "an edited manifest reaches no identities file"
    assert r.stdout.strip() == "nothing changed", r.stdout


@case
def identities_lists_and_adds_for_the_checkout_owner_only():
    w = World()
    r = w.fleet_cmd("identities", "--add", "grace@example.com")
    ok(r)
    assert json.loads(identities_file(w).read_text()) == ["grace@example.com"]
    assert r.stdout.splitlines() == ["added grace@example.com to " + str(identities_file(w)), "grace@example.com"]
    r = w.fleet_cmd("identities", "--add", "grace@example.com")
    ok(r)
    assert r.stdout.strip() == "grace@example.com", "a repeat adds nothing"
    refused(w.fleet_cmd("identities", "--add", "not-an-address"), "not an e-mail address")
    before = snap(w.home)
    refused(as_other(w, "identities", "--add", "alan@example.com"), "runs as the fleet checkout's owner")
    same(before, snap(w.home))


@case
def install_records_the_interpreter_and_keeps_it():
    w = World(host=False, readonly=False)
    py = "/opt/fleet-test/bin/python3"
    ok(w.fleet_cmd("install", "--agents-root", w.agents, FLEET_PYTHON=py))
    assert json.loads(w.host_json.read_text()).get("python") == py
    r = w.fleet_cmd("install", "--agents-root", w.agents)
    ok(r)
    assert json.loads(w.host_json.read_text()).get("python") == py and r.stdout.strip() == "nothing changed", \
        "a repeat without FLEET_PYTHON keeps it"
    refused(w.fleet_cmd("install", "--agents-root", w.agents, FLEET_PYTHON="python3"), "not an absolute path")


def main():
    # The subject runs on fleetlib and on the commit gate's gitleaks installer.
    # Without them every case would fail on an import or a missing file, which
    # says nothing about bin/fleet: that is NO VERDICT (exit 2), never a FAIL.
    missing = [str(p) for p in (SUBJECT, LIB / "__init__.py", REPO / "tools/leak-gate/install-gitleaks.sh")
               if not p.is_file()]
    if missing:
        print(f"NO VERDICT: the subject or what it needs is absent: {', '.join(missing)}")
        return 2
    pick = sys.argv[sys.argv.index("-k") + 1] if "-k" in sys.argv else ""
    write(GITCONFIG, "[init]\n\tdefaultBranch = main\n[advice]\n\tdetachedHead = false\n"
                     "[commit]\n\tgpgSign = false\n[tag]\n\tgpgSign = false\n")
    write(OUTSIDE_FILE, "outside the tree\n", 0o644)
    global ORIGIN
    ORIGIN = Origin()
    failed, ran = [], 0
    for fn in CASES:
        if pick not in fn.__name__:
            continue
        ran += 1
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed.append(fn.__name__)
            print(f"FAIL  {fn.__name__}\n" + "".join("      " + ln for ln in traceback.format_exc().splitlines(True)))
    print(f"{ran - len(failed)}/{ran} passed (subject {SUBJECT})")
    if ran == 0:
        print("NO VERDICT: no case ran")
        return 2
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        force_rmtree(SCRATCH)
    sys.exit(code)
