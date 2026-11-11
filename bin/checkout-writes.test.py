#!/usr/bin/env python3
"""checkout-writes.test.py - nothing the fleet runs writes into the fleet checkout.

Usage: python3 bin/checkout-writes.test.py      (tests/run-all.sh runs it)

With an administrator the fleet checkout is the administrator's, read-only, and
the agents user only reads it; in the one-user form it is still the code every
agent runs. A file the agents user leaves in it - a __pycache__ is the usual one
- is refused there, or, where it can write, is its own code inside the code it
runs. So each command below runs against a COPY of this tree's tracked files
(its own git repository, tagged v9.9.9), plainly, with no PYTHONDONTWRITEBYTECODE
of the caller's, and the copy is compared before and after:

  systemd/agent-daemons.py   jobs --json; follow ada sched --once;
                             refresh --dry-run; status ada
  bin/fleet                  session-check; status ada; check-all ada (every
                             linked skill's installation/check)

THE TWO COPIES, and why both. Python writes bytecode silently wherever it can
and skips it silently where it cannot, so a read-only copy alone can never show
an attempted write: the WRITABLE copy is the one with teeth - no path may appear
in it. The READ-ONLY copy (chmod -R a-w, as the administrator's checkout is to
the agents user; access is refused by mode, which is what another owner's
read-only tree gives a non-root user) shows the commands still work there: each
must exit as it did in the writable copy.

THE CONTROL. The snapshot must be able to see the class of write it is for:
importing fleetlib from the writable copy with no flag must make a __pycache__
appear in it. If it does not, the run is NO VERDICT, never a pass.

Everything else is fake or temporary: HOME, the host settings, the agent home
(the fixture install as ada's project), systemctl (answers show with not-found),
the /proc root. Nothing reaches a real unit, host setting or agent.

Exit codes: 0 pass; 1 a check failed; 3 NO VERDICT.
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
REPO = Path(os.path.realpath(__file__)).parents[1]
# The fixture install's skills that ship an installation/check: check-all's rows.
MANIFEST = REPO / "tests" / "fixtures" / "install" / ".claude" / "fleet.json"
failures, noverdict = [], []
FAKE_SYSTEMCTL = """#!/bin/sh
for a in "$@"; do last="$a"; done
case "$*" in
  *show*) for a in "$@"; do [ "$prev" = -p ] && echo "$a=$( [ "$a" = LoadState ] && echo not-found )"; prev="$a"; done ;;
esac
exit 0
"""


def check(cond, what):
    print(("ok    " if cond else "FAIL  ") + what)
    if not cond:
        failures.append(what)


def run(argv, env, cwd):
    return subprocess.run([str(a) for a in argv], capture_output=True, text=True, env=env, cwd=cwd,
                          stdin=subprocess.DEVNULL, timeout=600)


def git(*args, cwd):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(cwd), "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_AUTHOR_NAME": "Ada", "GIT_AUTHOR_EMAIL": "ada@example.com",
           "GIT_COMMITTER_NAME": "Ada", "GIT_COMMITTER_EMAIL": "ada@example.com"}
    subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True)


def copy_tree(dst):
    """This tree's tracked files at `dst`, as a git repository tagged v9.9.9."""
    names = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z"], capture_output=True, check=True,
                           env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")}).stdout
    for n in [x for x in names.decode().split("\0") if x]:
        src, out = REPO / n, dst / n
        if not os.path.lexists(src):
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        if src.is_symlink():
            os.symlink(os.readlink(src), out)
        else:
            shutil.copy2(src, out)
            os.chmod(out, stat.S_IMODE(os.stat(src).st_mode) | 0o200)
    git("init", "-q", "-b", "main", cwd=dst)
    git("add", "-A", cwd=dst)
    git("commit", "-q", "-m", "copy", cwd=dst)
    git("tag", "-a", "v9.9.9", "-m", "v9.9.9", cwd=dst)


def snapshot(root):
    """Every path in the tree, the git directory's own bookkeeping aside (an index
    or lock git refreshes while reading)."""
    out = set()
    for d, dirs, files in os.walk(root):
        rel = os.path.relpath(d, root)
        if rel == ".git" or rel.startswith(".git" + os.sep):
            continue
        out.update(os.path.join(rel, x) for x in dirs + files)
    return out


def set_writable(root, on):
    for d, dirs, files in os.walk(root):
        for p in [d] + [os.path.join(d, f) for f in files]:
            if os.path.islink(p):
                continue
            m = stat.S_IMODE(os.lstat(p).st_mode)
            os.chmod(p, (m | 0o200) if on else (m & ~0o222))


def world(base, fleet):
    """HOME, host settings, the agent home ada (the fixture install as its
    project), a fake systemctl; the env every command runs with."""
    home, agents = base / "home", base / "agents"
    (home / ".config" / "agent-fleet").mkdir(parents=True)
    shutil.copytree(REPO / "tests" / "fixtures" / "install", agents / "ada" / "project", symlinks=True)
    (agents / "ada" / ".claude").mkdir(parents=True)
    (agents / "ada" / "state" / "daemons").mkdir(parents=True)
    (agents / "claims").mkdir(mode=0o700)
    host = home / ".config" / "agent-fleet" / "host.json"
    host.write_text(json.dumps({"schema": 1, "agents_root": str(agents), "fleet_checkout": str(fleet),
                                "claims_dir": str(agents / "claims")}))
    fake = base / "bin" / "systemctl"
    fake.parent.mkdir()
    fake.write_text(FAKE_SYSTEMCTL)
    fake.chmod(0o755)
    (base / "proc").mkdir()
    keep = ("PATH", "LANG", "LC_ALL", "TMPDIR")
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env.update(HOME=str(home), FLEET_HOST_CONFIG=str(host), FLEET_SERVICE_BACKEND="systemd",
               FLEET_SYSTEMCTL=str(fake), FLEET_PROC=str(base / "proc"),
               CLAUDE_CONFIG_DIR=str(agents / "ada" / ".claude"))
    return env, agents / "ada" / "project"


def commands(fleet, project):
    d, f = fleet / "systemd" / "agent-daemons.py", fleet / "bin" / "fleet"
    return [("jobs --json", [sys.executable, d, "jobs", "--json"]),
            ("follow --once", [sys.executable, d, "follow", "ada", "sched", "--once"]),
            ("refresh --dry-run", [sys.executable, d, "refresh", "--dry-run"]),
            ("daemons status", [sys.executable, d, "status", "ada"]),
            ("session-check", [sys.executable, f, "session-check", "--project", project]),
            ("fleet status", [sys.executable, f, "status", "ada"]),
            ("check-all", [sys.executable, f, "check-all", "ada"])]


def skills_with_checks():
    import re
    text = re.sub(r"^\s*//.*$", "", MANIFEST.read_text(encoding="utf-8"), flags=re.M)
    return [n for n in json.loads(text)["skills"]
            if (REPO / ".claude" / "skills" / n / "installation" / "check").is_file()]


SKILLS_WITH_CHECKS = skills_with_checks()


def main():
    if len(SKILLS_WITH_CHECKS) < 3:
        print(f"NO VERDICT: the fixture install links {len(SKILLS_WITH_CHECKS)} skill(s) with a check")
        return 3
    if os.geteuid() == 0:
        print("NO VERDICT: run as root, which a read-only mode does not stop")
        return 3
    base = Path(os.path.realpath(tempfile.mkdtemp(prefix="fleet-checkout-writes-")))
    fleet = base / "fleet"
    try:
        copy_tree(fleet)
        env, project = world(base, fleet)
        link = run([sys.executable, fleet / "bin" / "fleet", "link", "ada"], env, base)
        if link.returncode != 0:
            print(f"NO VERDICT: fleet link ada failed in the copy: {link.stderr.strip()[-300:]}")
            return 3
        # The control: an import with no flag writes a __pycache__ the snapshot sees.
        before = snapshot(fleet)
        probe = run([sys.executable, "-c", "import sys; sys.path.insert(0, sys.argv[1]); import fleetlib.paths",
                     fleet / "lib"], {k: v for k, v in env.items() if k != "PYTHONDONTWRITEBYTECODE"}, base)
        seen = sorted(snapshot(fleet) - before)
        if probe.returncode != 0 or not any("__pycache__" in p for p in seen):
            noverdict.append(f"an unflagged import made no __pycache__ the snapshot sees ({probe.stderr.strip()[-200:]})")
        shutil.rmtree(fleet / "lib" / "fleetlib" / "__pycache__", ignore_errors=True)

        codes = {}
        before = snapshot(fleet)
        for what, argv in commands(fleet, project):
            r = run(argv, env, project)
            codes[what] = r.returncode
            new = sorted(snapshot(fleet) - before)
            check(not new, f"writable copy, {what} (exit {r.returncode}): nothing new in the checkout {new[:5]}")
            check("Traceback" not in r.stderr, f"writable copy, {what}: no traceback {r.stderr.strip()[-300:]}")
            if what == "check-all":
                # Positive evidence the subject was reached: one row per linked
                # skill with a check, each with its verdict, not a refusal before them.
                rows = [l for l in r.stdout.splitlines()[1:] if l.split()[:1] and l.split()[0] in SKILLS_WITH_CHECKS]
                check(len(rows) == len(SKILLS_WITH_CHECKS),
                      f"check-all ran every linked skill's check ({len(rows)} of {len(SKILLS_WITH_CHECKS)} rows)")
            if what == "fleet status":
                check("ada: " in r.stdout and "host checkout" in r.stdout, f"fleet status reported ada {r.stdout[-300:]}")
        set_writable(fleet, False)
        try:
            before = snapshot(fleet)
            for what, argv in commands(fleet, project):
                r = run(argv, env, project)
                check(r.returncode == codes[what],
                      f"read-only copy, {what}: exit {r.returncode}, as in the writable copy ({codes[what]}) "
                      f"{r.stderr.strip()[-300:]}")
            check(snapshot(fleet) == before, "read-only copy: the tree is as it was")
        finally:
            set_writable(fleet, True)
    finally:
        if fleet.exists():
            set_writable(fleet, True)
        shutil.rmtree(base, ignore_errors=True)
    if noverdict:
        print("NO VERDICT: " + "; ".join(noverdict))
        return 3
    if failures:
        print(f"FAIL: {len(failures)} check(s) failed")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
