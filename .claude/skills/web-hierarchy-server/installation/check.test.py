#!/usr/bin/env python3
"""Regression guard for web-hierarchy-server/installation/check: its LAST line
names every leg that did not pass, and the transcripts leg's cause.

`fleet check-all` shows each check's last line and nothing else, so a verdict
line that only says NOT INSTALLED leaves the operator with no cause; the failing
legs are on earlier lines nobody is shown.

HOW IT RUNS. The real check runs as a subprocess against a throwaway install
(FLEET_CONTEXT_ROOT) under a temp directory: the fixture install's manifest, and
a config.json whose transcript root is a temp directory and whose one server
entry names a unit and a port no host has (port 1, a unit name made for this
test). Nothing outside the temp directory is written. Whether node, ss and
systemctl exist here changes WHICH legs fail, never the property tested: the
oracle is the check's own leg lines, read independently of its verdict line.

THE CONTROL. The same install with a session transcript under its root must
pass the transcripts leg and must NOT name it in the last line. Without it, a
verdict line that listed every leg name whatever happened would pass the
failing case.

THE LAUNCHD LEG (macOS), with FLEET_SERVICE_BACKEND=launchd and the fleet's fake
launchctl, so it runs the same on both systems. The server is a stand-in: a python
listener on a free 127.0.0.1 port whose argv names this skill's serve.mjs, and the
job's pid is that listener's, so who holds the port is read for real (ss on Linux,
lsof on macOS, the argv through fleetlib.services). A job not loaded is NEEDS
ATTENTION naming the LaunchAgent install; loaded and serving is OK; loaded and not
running is NOT INSTALLED. Its control is the same running job with a listener whose
argv names no serve.mjs: a foreign holder, never OK, so the OK above is the argv
deciding.

Run: python3 .claude/skills/web-hierarchy-server/installation/check.test.py
Exits 0 when every case passes, 1 on a failure, 3 on NO VERDICT.
"""
import json
import os
import plistlib
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.realpath(__file__))
CHECK = os.path.join(HERE, "check")
FLEET_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
FIXTURE = os.path.join(FLEET_ROOT, "tests", "fixtures", "install")
FAKE = os.path.join(FLEET_ROOT, "tests", "fixtures", "launchd", "fake-launchctl")
SERVE = os.path.join(os.path.dirname(HERE), "serve.mjs")
LABEL = "com.agent-fleet-test.web-hierarchy.ada"
LISTENER = ("import socket, sys, time; s = socket.socket(); "
            "s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); "
            "s.bind(('127.0.0.1', int(sys.argv[1]))); s.listen(); time.sleep(300)")
LEG = re.compile(r"^\s+\[(OK|NEEDS ATTENTION|NOT INSTALLED)\] ([^:]+):", re.M)

_failures = []


def check(name, cond, detail=""):
    print(("[PASS] " if cond else "[FAIL] ") + name + (" - " + detail if detail and not cond else ""))
    if not cond:
        _failures.append(name)


def install(tmp):
    root = os.path.join(tmp, "install")
    os.makedirs(os.path.join(root, ".claude", "skills", "web-hierarchy-server"))
    shutil.copy(os.path.join(FIXTURE, ".claude", "fleet.json"), os.path.join(root, ".claude", "fleet.json"))
    with open(os.path.join(FIXTURE, ".claude", "skills", "web-hierarchy-server", "config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    transcripts = os.path.join(tmp, "agent-config")
    cfg["transcripts"]["config_dir"] = transcripts
    cfg["servers"] = {"fleet-check-test-no-such-unit.service": {"config_dir": transcripts, "port": 1}}
    with open(os.path.join(root, ".claude", "skills", "web-hierarchy-server", "config.json"), "w",
              encoding="utf-8") as f:
        json.dump(cfg, f)
    return root, transcripts


def run(root, tmp, **extra):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8",
           "HOME": os.path.join(tmp, "home"), "FLEET_CONTEXT_ROOT": root,
           "FLEET_HOST_CONFIG": os.path.join(FLEET_ROOT, "tests", "fixtures", "host.json"),
           "PYTHONDONTWRITEBYTECODE": "1", **extra}
    p = subprocess.run([sys.executable, CHECK], capture_output=True, text=True, env=env,
                       stdin=subprocess.DEVNULL, timeout=300)
    lines = [ln.strip() for ln in p.stdout.splitlines() if ln.strip()]
    legs = LEG.findall(p.stdout)
    return p.returncode, (lines[-1] if lines else ""), legs, p.stdout + p.stderr


def listener(port, *argv):
    p = subprocess.Popen([sys.executable, "-c", LISTENER, str(port), *argv], stdin=subprocess.DEVNULL)
    for _ in range(100):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return p
        except OSError:
            time.sleep(0.05)
    return p


def launchd_cases(root, tmp):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    cfg_path = os.path.join(root, ".claude", "skills", "web-hierarchy-server", "config.json")
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["servers"] = {LABEL: {"config_dir": cfg["transcripts"]["config_dir"], "port": port}}
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    agents = os.path.join(tmp, "home", "Library", "LaunchAgents")
    os.makedirs(agents)
    plist = os.path.join(agents, LABEL + ".plist")
    with open(plist, "wb") as f:
        plistlib.dump({"Label": LABEL, "ProgramArguments": ["/bin/bash", "-lc", f"exec node {SERVE} --port={port}"],
                       "RunAtLoad": True, "KeepAlive": True}, f)
    state = os.path.join(tmp, "launchd.json")
    env = {"FLEET_SERVICE_BACKEND": "launchd", "FLEET_LAUNCHCTL": FAKE, "FAKE_LAUNCHD_STATE": state,
           "FAKE_LAUNCHD_CALLS": os.path.join(tmp, "launchctl.calls")}
    domain = f"gui/{os.getuid()}"

    def launchd_leg(out):
        return [(st, line) for st, line in re.findall(r"^\s+\[(OK|NEEDS ATTENTION|NOT INSTALLED)\] (launchd: .*)$",
                                                     out, re.M)]

    procs = []
    try:
        rc, last, legs, out = run(root, tmp, **env)
        got = launchd_leg(out)
        check("launchd: a job that is not loaded is NEEDS ATTENTION naming the LaunchAgent install",
              len(got) == 1 and got[0][0] == "NEEDS ATTENTION" and "is not loaded" in got[0][1]
              and "LaunchAgent" in got[0][1], repr(got) + out[-600:])

        mine = listener(port, SERVE)
        procs.append(mine)
        with open(state, "w") as f:
            json.dump({"next_pid": mine.pid}, f)
        r = subprocess.run([FAKE, "bootstrap", domain, plist], capture_output=True, text=True,
                           env=dict(os.environ, **env))
        rc, last, legs, out = run(root, tmp, **env)
        got = launchd_leg(out)
        check("launchd: loaded, running, and its port held by this skill's serve.mjs: OK",
              r.returncode == 0 and len(got) == 1 and got[0][0] == "OK"
              and f"held by pid {mine.pid}, this skill's serve.mjs" in got[0][1], repr(got) + out[-600:])

        mine.kill()
        mine.wait()
        foreign = listener(port, "not-a-server")
        procs.append(foreign)
        with open(state) as f:
            st = json.load(f)
        st["loaded"][domain][LABEL]["pid"] = foreign.pid
        with open(state, "w") as f:
            json.dump(st, f)
        rc, last, legs, out = run(root, tmp, **env)
        got = launchd_leg(out)
        check("launchd CONTROL: the same running job with a listener that is not serve.mjs is never OK",
              len(got) == 1 and got[0][0] == "NOT INSTALLED" and "running but port" in got[0][1],
              repr(got) + out[-600:])

        st["loaded"][domain][LABEL].update(state="not running", pid=0, last_exit=1)
        with open(state, "w") as f:
            json.dump(st, f)
        rc, last, legs, out = run(root, tmp, **env)
        got = launchd_leg(out)
        check("launchd: loaded but not running is NOT INSTALLED, naming its last result",
              len(got) == 1 and got[0][0] == "NOT INSTALLED" and "is loaded but" in got[0][1]
              and "launchd" in last, repr(got) + f" last={last!r}")
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()
                p.wait()


def main():
    tmp = tempfile.mkdtemp(prefix="web-hierarchy-check-test-")
    try:
        root, transcripts = install(tmp)

        # A fresh agent's host: no session has ever run, so the transcript root
        # cannot be listed (a NOT INSTALLED leg), and no unit is installed.
        rc, last, legs, out = run(root, tmp)
        failing = sorted({name for state, name in legs if state != "OK"})
        if not legs or "transcripts" not in failing:
            print(out)
            print("NO VERDICT: the check printed no transcripts failure for an absent transcript "
                  "root, so the case below has no known failing leg to look for")
            return 3
        check("absent transcripts: exit 2 and the last line is the NOT INSTALLED verdict",
              rc == 2 and last.startswith("verdict: NOT INSTALLED"), f"rc={rc} last={last!r}")
        check("the last line names every leg that did not pass",
              all(name in last for name in failing), f"failing={failing} last={last!r}")
        # ...and says WHY the transcripts leg failed, because the leg line that does
        # is not shown by `fleet check-all`. A config_dir that does not exist is a
        # wrong path; an existing one with no session under it is an agent that has
        # not signed in and run yet. The two causes have two different fixes.
        check("a config_dir that does not exist: the last line says so",
              f"transcripts (config_dir {transcripts} does not exist)" in last, f"last={last!r}")
        os.makedirs(transcripts)
        rc, last, legs, out = run(root, tmp)
        check("an existing config_dir with no session: the last line says no signed-in session has run",
              rc == 2 and f"transcripts (no signed-in session has run under {transcripts} yet" in last,
              f"rc={rc} last={last!r}")
        os.makedirs(os.path.join(transcripts, "projects", "slug"))
        rc, last, legs, out = run(root, tmp)
        check("a project slug with no transcript yet: the same cause, at NEEDS ATTENTION",
              "transcripts (no signed-in session has run under" in last and "NEEDS ATTENTION] transcripts" in out,
              f"rc={rc} last={last!r}")

        # Control: a session transcript makes the transcripts leg pass; the last line
        # must stop naming it.
        with open(os.path.join(transcripts, "projects", "slug", "session.jsonl"), "w", encoding="utf-8") as f:
            f.write("{}\n")
        rc, last, legs, out = run(root, tmp)
        passed = {name for state, name in legs if state == "OK"}
        failing = sorted({name for state, name in legs if state != "OK"})
        only_passed = sorted(passed - set(failing))
        check("control: with a session the transcripts leg passes", "transcripts" in passed, out)
        check("control: no leg that passed is named in the last line, every failing one is",
              only_passed and not any(name in last for name in only_passed)
              and all(name in last for name in failing),
              f"passed={only_passed} failing={failing} last={last!r}")
        launchd_cases(root, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    if _failures:
        print("FAILED: %d check(s): %s" % (len(_failures), "; ".join(_failures)))
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
