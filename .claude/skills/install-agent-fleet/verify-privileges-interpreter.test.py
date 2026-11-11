#!/usr/bin/env python3
"""verify-privileges-interpreter.test.py - verify-privileges.py checks the
INTERPRETER the protected stall watchdog runs, not only its script.

Usage: python3 .claude/skills/install-agent-fleet/verify-privileges-interpreter.test.py
       (tests/run-all.sh discovers and runs it; no real sudo, polkit, systemd or launchd)

The watchdog runs as `<interpreter> watchdog.py`. An agents user that can change
the interpreter - on macOS, Homebrew's python3 in a Homebrew that user owns -
runs its own code as the job meant to supervise it, exactly as one that can
change the script. So the executable the job starts (systemd's ExecStart path=,
launchd's Program or ProgramArguments[0]) must be out of the user's reach, by
the same rule as every other path the script checks (fleetlib.paths.changeable:
ownership and the directory chain, symlinks followed).

THE HARNESS is verify-privileges.test.py's: its fake sudo, pkcheck, systemctl
and id, its World of real files (root-owned /etc files stand for protected
paths, files this test creates for exposed ones), and the fleet's fake
launchctl. It is imported, not copied, so the two cannot drift apart.

What it proves:
  systemd  a watchdog whose interpreter and script are both root's is PROTECTED,
           exit 0, and its ok line names the interpreter; an interpreter this
           user owns FAILs naming "the interpreter the watchdog runs" (exit 1;
           UNPROTECTED, exit 4, with --no-admin); an interpreter reached through
           a symlink in a directory this user owns FAILs (the link can be
           replaced), though its target is root's.
  launchd  (in process, as verify-privileges.test.py section 7 does: a stand-in
           directory answers "cannot change" for root's files) both jobs with a
           protected interpreter give four ok lines, the program line naming the
           interpreter; an interpreter this user owns FAILs; a `Program` key
           this user owns FAILs even when ProgramArguments[0] is protected,
           because launchd runs Program; an interpreter named by a relative
           path is NO VERDICT.

THE CONTROL: each protected case must pass. An exposed interpreter failing is
evidence only when the same harness, with the interpreter protected, passes;
if a protected case does not pass, the run is NO VERDICT (exit 3).

Run as root it is NO VERDICT: root may write every path.
Exit codes: 0 pass; 1 a check failed; 3 NO VERDICT.
"""
import importlib.util
import os
import plistlib
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(os.path.realpath(__file__)).parent
SCRIPT = HERE / "verify-privileges.py"
_spec = importlib.util.spec_from_file_location("verify_privileges_test", HERE / "verify-privileges.test.py")
vt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vt)

failures, noverdict = [], []
WD = "claude-agent-ada-stall-watchdog.service"


def check(cond, what):
    print(("ok    " if cond else "FAIL  ") + what)
    if not cond:
        failures.append(what)


def execstart(interp, prog):
    return "{ path=%s ; argv[]=%s %s ; ignore_errors=no ; start_time=[n/a] ; pid=0 }" % (interp, interp, prog)


def systemd(base):
    w = vt.World(base)
    try:
        r, _ = w.run("--agent", "ada", units=vt.protected_units(**{WD: {"ExecStart": execstart("/etc/hosts", "/etc/services")}}))
        protected = r.returncode == 0 and "== PROTECTED" in r.stdout
        check(protected, f"systemd: interpreter and script both root's: PROTECTED, exit 0 (got {r.returncode}: {vt.tail(r)})")
        check(vt.line(r, "ok", "/etc/services", "interpreter /etc/hosts"),
              f"systemd: the protected watchdog's ok line names its interpreter ({vt.tail(r)})")
        if not protected:
            noverdict.append("systemd: the protected interpreter did not pass, so a FAIL below proves nothing")
        own = base / "ada-python3"
        own.write_text("#!/bin/sh\n")
        units = vt.protected_units(**{WD: {"ExecStart": execstart(own, "/etc/services")}})
        r, _ = w.run("--agent", "ada", units=units)
        check(r.returncode == 1 and vt.line(r, "FAIL", str(own), "the interpreter the watchdog runs")
              and not vt.line(r, "FAIL", "the program the watchdog runs"),
              f"systemd: an interpreter ada owns FAILs naming the interpreter, not the program, exit 1 "
              f"(got {r.returncode}: {vt.tail(r)})")
        r, _ = w.run("--agent", "ada", "--no-admin", units=units)
        check(r.returncode == 4 and vt.line(r, "UNPROTECTED", str(own), "the interpreter the watchdog runs"),
              f"systemd, --no-admin: the same interpreter is UNPROTECTED, exit 4 (got {r.returncode}: {vt.tail(r)})")
        links = base / "ada-bin"
        links.mkdir()
        (links / "python3").symlink_to("/etc/hosts")
        r, _ = w.run("--agent", "ada", units=vt.protected_units(**{WD: {"ExecStart": execstart(links / "python3", "/etc/services")}}))
        check(r.returncode == 1 and vt.line(r, "FAIL", "the interpreter the watchdog runs"),
              f"systemd: an interpreter linked from a directory ada owns FAILs, though its target is root's "
              f"(got {r.returncode}: {vt.tail(r)})")
    finally:
        w.cleanup()


def launchd(base):
    prot, home, mine = base / "root-standin", base / "lhome", base / "mine"
    sysdir = prot / "LaunchDaemons"
    for d in (sysdir, home / "Library" / "LaunchAgents", mine):
        d.mkdir(parents=True)
    cfg_p, prog_p, py_p = prot / "stall-watchdog.json", prot / "watchdog.py", prot / "python3"
    for q in (cfg_p, prog_p, py_p):
        q.write_text("#\n")
    own_py = mine / "python3"
    own_py.write_text("#!/bin/sh\n")
    state, calls = base / "launchd.json", base / "launchctl.calls"
    env = {"FLEET_SERVICE_BACKEND": "launchd", "FLEET_LAUNCHCTL": str(vt.FAKE_LAUNCHCTL),
           "FAKE_LAUNCHD_STATE": str(state), "FAKE_LAUNCHD_CALLS": str(calls),
           "FLEET_LAUNCHD_SYSTEM_DIR": str(sysdir), "HOME": str(home), "FLEET_HOST_CONFIG": str(base / "host.json")}
    S, W = "com.agent-fleet.session.ada", "com.agent-fleet.stall-watchdog.ada"

    def job(label, interp=py_p, program=None):
        d = {"Label": label, "UserName": "ada", "ProgramArguments": [str(interp), str(prog_p)],
             "RunAtLoad": True, "KeepAlive": True}
        if program:
            d["Program"] = str(program)
        if label == W:
            d["EnvironmentVariables"] = {"STALL_WATCHDOG_CONFIG": str(cfg_p)}
        path = sysdir / f"{label}.plist"
        with open(path, "wb") as f:
            plistlib.dump(d, f)
        return path

    def world(**watchdog):
        if state.exists():
            state.unlink()
        for label, path in ((S, job(S)), (W, job(W, **watchdog))):
            subprocess.run([str(vt.FAKE_LAUNCHCTL), "bootstrap", "system", str(path)], env=dict(os.environ, **env),
                           check=True, capture_output=True)

    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        spec = importlib.util.spec_from_file_location("verify_privileges", SCRIPT)
        vp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(vp)
        real, root = vp.changeable, os.path.realpath(prot)
        vp.changeable = lambda q: None if os.path.realpath(q).startswith(root + os.sep) else real(q)

        def checks():
            vp.lines.clear()
            vp.launchd_agent_checks("ada", "ada", "FAIL")
            return list(vp.lines)

        def has(got, status, *words):
            return any(s == status and all(x in text for x in words) for s, text in got)

        world()
        got = checks()
        protected = len(got) == 4 and all(s == "ok" for s, _ in got)
        check(protected, f"launchd: a protected interpreter: four ok lines ({got})")
        check(has(got, "ok", "watchdog's program", str(prog_p), f"interpreter {py_p}"),
              f"launchd: the program line names the interpreter ({got})")
        if not protected:
            noverdict.append("launchd: the protected interpreter did not pass, so a FAIL below proves nothing")
        world(interp=own_py)
        got = checks()
        check(has(got, "FAIL", str(own_py), "the interpreter the watchdog runs")
              and not has(got, "FAIL", "the program the watchdog runs"),
              f"launchd: ProgramArguments[0] owned by ada FAILs naming the interpreter ({got})")
        world(program=own_py)
        got = checks()
        check(has(got, "FAIL", str(own_py), "the interpreter the watchdog runs"),
              f"launchd: a Program key owned by ada FAILs, though ProgramArguments[0] is protected ({got})")
        world(interp="python3")
        got = checks()
        check(has(got, "NO VERDICT", "relative path", "python3"),
              f"launchd: an interpreter named by a relative path is NO VERDICT ({got})")
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def main():
    if os.geteuid() == 0:
        print("NO VERDICT: run as root, which may write every path")
        return 3
    bad = [p for p in ("/etc/passwd", "/etc/hosts", "/etc/services", "/etc/pam.d")
           if not os.path.exists(p) or os.stat(p).st_uid != 0]
    if bad:
        print(f"NO VERDICT: the root-owned fixtures are missing or not root's here: {bad}")
        return 3
    with tempfile.TemporaryDirectory(prefix="verify-privileges-interpreter-test-") as tmp:
        (Path(tmp) / "s").mkdir()
        (Path(tmp) / "l").mkdir()
        systemd(Path(tmp) / "s")
        launchd(Path(tmp) / "l")
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
