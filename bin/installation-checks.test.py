#!/usr/bin/env python3
"""installation-checks.test.py - every skill's installation/check runs to a verdict
against the fleet's fixture install, without crashing against the library.

Usage: python3 bin/installation-checks.test.py

`fleet check-all` runs these checks on a live host; this is the same sweep in CI,
so a fleetlib change that breaks a check reds here instead of on the first host
that runs it. It asks whether each check RUNS, not whether anything is
installed: every verdict a check is allowed to give passes.

Discovery is the glob .claude/skills/*/installation/check, so a new skill's check
is covered with no edit here. Each check is executed directly (its #! line, the
way skill prose invokes it) from the fixture install's root, the way `fleet
check-all` runs it, under an environment built from nothing:
  FLEET_CONTEXT_ROOT=tests/fixtures/install, FLEET_HOST_CONFIG=tests/fixtures/host.json,
  HOME=<a fresh temporary directory>, PATH, LANG, PYTHONDONTWRITEBYTECODE=1,
  PYTHONPROFILEIMPORTTIME=1, plus that check's entry in SUBJECTS.
So no caller's CLAUDE_CONFIG_DIR, SCHED_CONFIG, STALL_WATCHDOG_CONFIG, opt-in
network switch or secrets directory reaches a check, and no check is given
--online: the network legs stay in their documented not-measured state.

Each check must, or the row fails:
  exit     exit with a code of claude-skill's check contract: 0, 1 or 2 (there
           is no fourth code); a timeout, a signal or 126/127 is not a verdict
  reason   print a non-empty line on stdout (the last one is the reason shown)
  crash    print no Python traceback, Node stack frame or bash runtime error
  library  not swallow a fleetlib name-resolution error into a verdict: a check
           that catches ImportError and prints it as NOT INSTALLED or NO VERDICT
           has crashed against the library as surely as one that tracebacks
  reach    import fleetlib (seen through PYTHONPROFILEIMPORTTIME, in the check's
           process or any Python child it starts), unless UNREACHED names the
           check and why; a check that exits before the library is touched says
           nothing about the library, so it is listed, never silently counted

SUBJECTS gives the checks that select their subject from the environment rather
than from the install context a throwaway subject under the temporary HOME, so
they reach their library leg. UNREACHED lists the checks that cannot reach
fleetlib hermetically, each with its reason; an entry for a check that does
reach it is itself a failure, so the list cannot go stale silently.

The positive control, the reason a PASS means anything. Before judging the real
tree, the same discover/run/judge path runs over a temporary skills tree of
planted checks: one per fault class (a Python traceback, a Node crash, a bash
unbound variable, a swallowed fleetlib ImportError, an undocumented exit code,
no output, no fleetlib import, a stale UNREACHED entry) and a decoy that must
pass. Each must come back with exactly the failures it planted, no more and no
fewer; otherwise the instrument is not established and the run is NO VERDICT.

Exit codes: 0 PASS; 1 FAIL, every failing row named; 3 NO VERDICT (the control
misfired, or no check was discovered). A non-zero exit is never green.
"""
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(os.path.realpath(__file__)).parents[1]
SKILLS = REPO / ".claude" / "skills"
LIB = REPO / "lib"
FIXTURE_INSTALL = REPO / "tests" / "fixtures" / "install"
FIXTURE_HOST = REPO / "tests" / "fixtures" / "host.json"
DOCUMENTED_EXITS = (0, 1, 2)
TIMEOUT = 180

UNREACHED = {
    "stall-watchdog": "it reads the install record through fleetlib only after the legs "
                      "that need a systemd unit naming the session's config to be enabled "
                      "and active, which no hermetic run has; with no session selected it "
                      "exits 2 at its first leg",
}

CRASH = [
    ("Python traceback", re.compile(r"^Traceback \(most recent call last\):", re.M)),
    ("Node stack frame", re.compile(r"^\s+at .+:\d+:\d+\)?$|^Node\.js v\d+", re.M)),
    ("bash runtime error", re.compile(
        r": line \d+: .*(unbound variable|command not found|syntax error|bad substitution)")),
]
SWALLOWED = re.compile(r"cannot import name .* from 'fleetlib|No module named 'fleetlib"
                       r"|module 'fleetlib[\w.]*' has no attribute")
IMPORTTIME = re.compile(r"^import time:.*$\n?", re.M)
FLEETLIB_IMPORTED = re.compile(r"^import time:\s+\d+\s+\|\s+\d+\s+\|\s+fleetlib(\.\w+)*\s*$", re.M)


def sched_subject(home):
    """scheduled-tasks reads SCHED_CONFIG, the per-agent config the agent's unit sets
    (one scheduler per agent; the install context holds none). The three keys it
    requires, with the modes it requires, under the temporary HOME."""
    db_dir = home / "scheduler"
    db_dir.mkdir(mode=0o700)
    db_dir.chmod(0o700)
    cfg = home / "sched.json"
    cfg.write_text(json.dumps({"owner": {"claude_config_dir": str(home / ".claude")},
                               "db": {"path": str(db_dir / "tasks.db")},
                               "defaults": {"tz": "UTC"}}))
    cfg.chmod(0o600)
    return {"SCHED_CONFIG": str(cfg)}


SUBJECTS = {"scheduled-tasks": sched_subject}


def discover(skills_dir):
    return sorted(p for p in Path(skills_dir).glob("*/installation/check") if p.is_file())


def run(check, home, cwd):
    """(exit code or a reason it has none, stdout, stderr) for one check."""
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home),
           "LANG": "C.UTF-8", "FLEET_CONTEXT_ROOT": str(FIXTURE_INSTALL),
           "FLEET_HOST_CONFIG": str(FIXTURE_HOST), "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONPROFILEIMPORTTIME": "1"}
    if os.environ.get("TMPDIR"):
        env["TMPDIR"] = os.environ["TMPDIR"]
    skill = check.parents[1].name
    if skill in SUBJECTS:
        env.update(SUBJECTS[skill](home))
    try:
        p = subprocess.run([str(check)], cwd=cwd, env=env, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=TIMEOUT)
    except subprocess.TimeoutExpired as e:
        return f"timed out after {TIMEOUT}s", e.stdout or "", e.stderr or ""
    except OSError as e:
        return f"could not be executed ({type(e).__name__}: {e})", "", ""
    return p.returncode, p.stdout, p.stderr


def judge(skill, rc, stdout, stderr, unreached):
    """(failures, reason line, reached fleetlib) for one run."""
    reached = bool(FLEETLIB_IMPORTED.search(stderr))
    stderr = IMPORTTIME.sub("", stderr)
    text = stdout + "\n" + stderr
    lines = [ln.strip() for ln in stdout.splitlines() if ln.strip()]
    reason = lines[-1] if lines else ""
    bad = []
    if not isinstance(rc, int) or rc not in DOCUMENTED_EXITS:
        bad.append(f"exit: {rc if not isinstance(rc, int) else f'exit {rc}'} is not one of "
                   f"the check contract's codes {DOCUMENTED_EXITS}")
    if not reason:
        bad.append("reason: printed nothing on stdout")
    for name, pattern in CRASH:
        m = pattern.search(text)
        if m:
            bad.append(f"crash: {name}: {m.group(0).strip()[:160]}")
    m = SWALLOWED.search(text)
    if m and not any(b.startswith("crash:") for b in bad):
        bad.append(f"library: a fleetlib error swallowed into a verdict: {m.group(0)[:160]}")
    if not reached and skill not in unreached:
        bad.append("reach: never imported fleetlib, so the library was not exercised; give it "
                   "a subject in SUBJECTS or list it in UNREACHED with the reason")
    if reached and skill in unreached:
        bad.append("reach: UNREACHED lists it, but it imported fleetlib; remove the entry")
    return bad, reason, reached


def sweep(skills_dir, unreached):
    """[(skill, rc, failures, reason, reached)] for every discovered check."""
    rows = []
    for check in discover(skills_dir):
        skill = check.parents[1].name
        with tempfile.TemporaryDirectory(prefix="fleet-installation-checks-home-") as home:
            rc, out, err = run(check, Path(home), FIXTURE_INSTALL)
        bad, reason, reached = judge(skill, rc, out, err, unreached)
        rows.append((skill, rc, bad, reason, reached))
    return rows


# ------------------------------------------------------------ the control

IMPORT_FLEETLIB = f"import sys; sys.path.insert(0, {str(LIB)!r}); from fleetlib import paths\n"
SH_IMPORT_FLEETLIB = "python3 -c " + shlex.quote(IMPORT_FLEETLIB.strip()) + "\n"
PY = "#!/usr/bin/env python3\n" + IMPORT_FLEETLIB
SH = "#!/usr/bin/env bash\nset -u\n" + SH_IMPORT_FLEETLIB
PLANTED = {
    # skill name: (check source, the failure prefixes it must produce - exactly these)
    "decoy-ok": (PY + "print('NO VERDICT: no install context (FleetError: none); a Traceback "
                      "is named here and is not one')\nsys.exit(1)\n", ()),
    "py-traceback": (PY + "print('about to fail')\nfrom fleetlib import no_such_name\n",
                     ("crash: Python traceback",)),
    "node-crash": (SH + "echo 'NOT INSTALLED: node said no'\n"
                        "node -e 'throw new Error(\"planted\")'\nexit 2\n",
                   ("crash: Node stack frame",)),
    "bash-unbound": (SH + "echo 'NOT INSTALLED: about to read'\necho \"$planted_unset\"\nexit 0\n",
                     ("crash: bash runtime error",)),
    "swallowed": (PY + "try:\n    from fleetlib import no_such_name\nexcept ImportError as e:\n"
                       "    print(f'NOT INSTALLED: watch.py does not load "
                       "({type(e).__name__}: {e})')\n    sys.exit(2)\n", ("library:",)),
    "exit-four": (PY + "print('INCONCLUSIVE: a fourth state')\nsys.exit(4)\n", ("exit:",)),
    "silent": (PY + "sys.exit(0)\n", ("reason:",)),
    "no-library": ("#!/usr/bin/env python3\nprint('OK: installed, says a check that never "
                   "looked')\n", ("reach: never imported",)),
    "stale-listing": (PY + "print('STALE: listed as unreached, and reaches')\nsys.exit(1)\n",
                      ("reach: UNREACHED lists it",)),
}


def control():
    """None when every planted fault is reported under its own rule and the decoy is
    clean, else the reason the instrument is not established."""
    with tempfile.TemporaryDirectory(prefix="fleet-installation-checks-control-") as tmp:
        for name, (src, _) in PLANTED.items():
            check = Path(tmp) / name / "installation" / "check"
            check.parent.mkdir(parents=True)
            check.write_text(src)
            check.chmod(0o755)
        rows = {r[0]: r for r in sweep(tmp, {"stale-listing": "planted: it does reach"})}
    missed = []
    for name, (_, want) in PLANTED.items():
        if name not in rows:
            missed.append(f"{name}: not discovered by the glob")
            continue
        bad = rows[name][2]
        got = [w for w in want if any(b.startswith(w) for b in bad)]
        extra = [b for b in bad if not any(b.startswith(w) for w in want)]
        if len(got) != len(want) or extra:
            missed.append(f"{name}: planted {list(want) or 'no fault'}, reported {bad or 'nothing'}")
    return "; ".join(missed) or None


def main():
    why = control()
    if why:
        print(f"NO VERDICT: the positive control did not fire as planted: {why}")
        return 3
    print(f"control: {len(PLANTED) - 1} planted faulty checks each reported with exactly "
          f"their own rule; the decoy passed")
    rows = sweep(SKILLS, UNREACHED)
    if not rows:
        print(f"NO VERDICT: no installation/check discovered under {SKILLS}")
        return 3
    print(f"census: {len(rows)} check(s) under .claude/skills/*/installation/check")
    failed = 0
    for skill, rc, bad, reason, reached in rows:
        lib = "fleetlib" if reached else "no fleetlib (UNREACHED: listed)" if skill in UNREACHED \
            else "no fleetlib"
        print(f"{'PASS' if not bad else 'FAIL'}  {skill}  exit={rc}  {lib}  | {reason[:200]}")
        for b in bad:
            print(f"      - {b}")
        failed += bool(bad)
    for skill, reason in UNREACHED.items():
        print(f"note: {skill} does not reach fleetlib here: {reason}")
    print(f"== {len(rows)} check(s), {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
