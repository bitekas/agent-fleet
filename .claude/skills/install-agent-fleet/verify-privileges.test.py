#!/usr/bin/env python3
"""verify-privileges.test.py - verify-privileges.py against fake machines, offline.

Usage: python3 .claude/skills/install-agent-fleet/verify-privileges.test.py
       (tests/run-all.sh discovers and runs it; no real sudo, polkit or systemd)

Each scenario runs the script with a PATH holding ONLY fakes - sudo, pkcheck,
systemctl and id - so the machine running the test can never answer for the
fake one. The fake systemctl serves `show` from a table of units the scenario
writes; the fake sudo answers `-n true` and `-n -l` as the scenario says; the
fake pkcheck answers as polkit does for an unprivileged caller (exit 0
authorized, 1 not, 2 needs authentication with its polkit.result line, 127 an
error); the fake id names the agents user `ada` and its groups.

The FILES are real, because the property under test is real ownership and
access: a protected unit or config is a root-owned file every Linux and macOS
machine has (/etc/passwd, /etc/hosts, /etc/services), and the protected fleet
checkout a root-owned tree they all have (/etc/pam.d), named by a host settings
file the test writes (FLEET_HOST_CONFIG: the machine's own is never read); an
exposed one is a file this test creates, which this user owns. So the test must not run as root (root
may write every path, and the protected half would mean nothing): as root, or
when one of those files is not root-owned, it is NO VERDICT.

What it proves:
  1. Everything protected: exit 0, PROTECTED, a line per fact.
  2. Each FAIL of the ruling: `sudo -n true` succeeds; `sudo -n -l` lists a
     command; the user is in group sudo; polkit authorizes unit management with
     no password or with the user's own; a unit file, a drop-in or the config
     the user can write, OWNS (read-only by mode, still the owner's to chmod), or
     can create in a directory it may write; a session unit that is not a system
     unit, or runs as another user. Each exits 1 and its line names the path or
     the fact.
  3. The watchdog's program in a tree the user owns FAILs, exit 1, and so does
     a fleet checkout the user owns, or reaches through a directory it may
     write (a link it can replace), and an identities file the user owns or
     may create; no host settings is NO VERDICT. The protected checkout's
     owner is root, whose identities file sits in a home this user cannot
     search: unreachable, so ok.
  4. --no-admin: the same findings print UNPROTECTED, exit 4; a sudo finding
     still FAILs (that form is for a user with no sudo at all).
  5. Nothing measured is never green: systemctl that does not answer, a pkcheck
     error, pkcheck absent with polkit installed, a watchdog unit naming no
     config - exit 3, NO VERDICT.
  6. An absent watchdog unit is n/a (the person may decline one), exit 0.
  7. Under launchd (FLEET_SERVICE_BACKEND=launchd, the fleet's fake launchctl,
     FLEET_LAUNCHD_SYSTEM_DIR and a temp HOME): the host checks ask no polkit;
     the session and the watchdog as LaunchDaemons with UserName ada, their
     plists, config and program out of ada's reach, are all ok; a plist ada
     owns, a job with no UserName (root), a config ada owns FAIL; the session
     only as a LaunchAgent in ada's own domain, or not loaded at all, FAILs
     (UNPROTECTED with --no-admin, end to end through the script); an absent
     watchdog is n/a; launchctl giving no answer is NO VERDICT. Every other
     scenario runs under FLEET_SERVICE_BACKEND=systemd, so this file reads the
     same on macOS.

THE LAUNCHD PROTECTED CASE NEEDS ROOT-OWNED PLISTS, which a test that must not
run as root cannot make. So that one case runs the launchd checks in this
process, with fleetlib's changeable() answering "cannot change" for one fixture
directory standing in for root's (/Library/LaunchDaemons and the watchdog's
config, program and interpreter) and the real rule everywhere else;
changeable() itself is fleetlib's, tested there. Its control is the exposed
cases beside it, on the real rule: a plist in a directory ada owns must FAIL.
The interpreter is a stand-in too, never /opt/homebrew/bin/python3: the
script checks the interpreter, and a real Homebrew belongs to whoever
installed it, which on a developer's Mac is the user running this test.

THE CONTROLS. "Protected" is an absence of findings, and it proves something
only if the same run sees a presence: the owned-but-read-only config must FAIL
naming ownership (a check by `test -w` alone passes it, which is why the
fixture is built read-only: os.access is asserted False on it first), the
writable unit file must FAIL, and the owned checkout must FAIL. If any does
not, the run is NO VERDICT.

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

HERE = Path(os.path.realpath(__file__)).parent
SCRIPT = HERE / "verify-privileges.py"
PROTECTED = ["/etc/passwd", "/etc/hosts", "/etc/services", "/etc/pam.d"]
CHECKOUT = "/etc/pam.d"
failures, noverdict = [], []

FAKE = r'''#!PYTHON
import json, os, sys
name = os.path.basename(sys.argv[0])
args = sys.argv[1:]
E = os.environ
with open(E["FAKE_LOG"], "a") as f:
    f.write(json.dumps([name] + args) + "\n")
if name == "id":
    print(E.get("FAKE_GROUPS", "ada") if args == ["-nG"] else "ada")
elif name == "sudo":
    if args == ["-n", "true"]:
        if E.get("FAKE_SUDO_TRUE") == "yes":
            sys.exit(0)
        sys.stderr.write("sudo: a password is required\n")
        sys.exit(1)
    if args == ["-n", "-l"]:
        if E.get("FAKE_SUDO_LIST") == "rules":
            print("User ada may run the following commands on fakehost:\n    (root) NOPASSWD: /usr/bin/systemctl")
            sys.exit(0)
        sys.stderr.write("sudo: a password is required\n")
        sys.exit(1)
    sys.exit(97)
elif name == "pkcheck":
    if "--detail" in args:
        sys.stderr.write("Only trusted callers (e.g. uid 0 or an action owner) can use CheckAuthorization() and pass details\n")
        sys.exit(127)
    how = E.get("FAKE_PKCHECK", "auth_admin")
    if how == "yes":
        sys.exit(0)
    if how == "no":
        sys.exit(1)
    if how == "error":
        sys.stderr.write("Error checking for authorization: GDBus.Error\n")
        sys.exit(127)
    print("polkit\\56result=" + how)
    sys.stderr.write("Authorization requires authentication and -u wasn't passed.\n")
    sys.exit(2)
elif name == "systemctl":
    if E.get("FAKE_SYSTEMCTL") == "down":
        sys.stderr.write("System has not been booted with systemd as init system (PID 1). Can't operate.\n")
        sys.exit(1)
    if args[:1] != ["show"] or "--user" in args:
        sys.exit(98)
    units = json.loads(open(E["FAKE_UNITS"]).read())
    unit = args[-1]
    props = units.get(unit, {"LoadState": "not-found"})
    want = [args[i + 1] for i, a in enumerate(args) if a == "-p"]
    for p in want:
        print(p + "=" + props.get(p, ""))
'''


def check(cond, what):
    print(("ok    " if cond else "FAIL  ") + what)
    if not cond:
        failures.append(what)


def unit(user="ada", frag="/etc/passwd", dropins="", env="", argv=""):
    u = {"LoadState": "loaded", "FragmentPath": frag, "DropInPaths": dropins, "User": user, "Environment": env}
    if argv:
        u["ExecStart"] = "{ path=%s ; argv[]=%s ; ignore_errors=no ; start_time=[n/a] ; pid=0 }" % (
            argv.split()[0], argv)
    return u


def protected_units(**override):
    units = {
        "claude-agent-ada.service": unit(),
        "claude-agent-ada-stall-watchdog.service": unit(
            dropins="/etc/hosts", env="TMUX_TMPDIR=/run/claude-tmux-ada STALL_WATCHDOG_CONFIG=/etc/hosts",
            argv="/usr/bin/python3 /etc/services"),
        "polkit.service": {"LoadState": "loaded"},
    }
    for name, props in override.items():
        if props is None:
            units.pop(name, None)
        else:
            units[name] = dict(units[name], **props)
    return units


class World:
    def __init__(self, base):
        self.dir = base
        self.bin = base / "bin"
        self.bin.mkdir()
        for n in ("id", "sudo", "pkcheck", "systemctl"):
            (self.bin / n).write_text(FAKE.replace("PYTHON", sys.executable))
            (self.bin / n).chmod(0o755)
        self.log = base / "calls.jsonl"
        # The exposed fixtures: a file this user may write, and one it may not
        # write but owns, in a directory it may not write either.
        self.writable = base / "unit.service"
        self.writable.write_text("[Service]\n")
        ro = base / "ro"
        ro.mkdir()
        self.owned = ro / "stall-watchdog.json"
        self.owned.write_text("{}\n")
        self.owned.chmod(0o444)
        ro.chmod(0o555)
        self.absent_here = base / "absent.json"
        # The exposed checkouts: a tree this user owns (read-only, as an install
        # leaves it), and the protected tree reached through a link in a
        # directory this user may write, which it could replace.
        self.own_checkout = base / "own-fleet"
        (self.own_checkout / "bin").mkdir(parents=True)
        (self.own_checkout / "bin" / "fleet").write_text("#!/bin/sh\n")
        for q in (self.own_checkout / "bin" / "fleet", self.own_checkout / "bin", self.own_checkout):
            q.chmod(0o555 if q.is_dir() else 0o444)
        self.linked_checkout = base / "fleet-link"
        self.linked_checkout.symlink_to(CHECKOUT)

    def run(self, *args, units=None, no_pkcheck=False, checkout=CHECKOUT, **env):
        if self.log.exists():
            self.log.unlink()
        table = self.dir / "units.json"
        table.write_text(json.dumps(protected_units() if units is None else units))
        if no_pkcheck:
            (self.bin / "pkcheck").rename(self.bin / "pkcheck.off")
        host = self.dir / "host.json"
        if checkout is None:
            host.unlink(missing_ok=True)
        else:
            host.write_text(json.dumps({"schema": 1, "agents_root": str(self.dir), "fleet_checkout": str(checkout),
                                        "claims_dir": str(self.dir / "claims")}))
        e = {"PATH": str(self.bin), "FAKE_LOG": str(self.log), "FAKE_UNITS": str(table), "LANG": "C",
             "FLEET_HOST_CONFIG": str(host), "FLEET_SERVICE_BACKEND": "systemd"}
        e.update(env)
        try:
            r = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=e,
                               stdin=subprocess.DEVNULL, timeout=120)
        finally:
            if no_pkcheck:
                (self.bin / "pkcheck.off").rename(self.bin / "pkcheck")
        calls = [json.loads(l) for l in self.log.read_text().splitlines()] if self.log.exists() else []
        return r, calls

    def cleanup(self):
        (self.dir / "ro").chmod(0o755)
        for q in (self.own_checkout, self.own_checkout / "bin"):
            q.chmod(0o755)


def line(r, status, *words):
    """Whether one output line starts with `status` and holds every word."""
    return any(l.startswith(status + " ") and all(w in l for w in words) for l in r.stdout.splitlines())


def tail(r):
    return (r.stdout + r.stderr).strip()[-400:]


def scenarios(w):
    wd = "claude-agent-ada-stall-watchdog.service"
    sess = "claude-agent-ada.service"

    r, calls = w.run("--agent", "ada")
    check(r.returncode == 0 and "== PROTECTED" in r.stdout,
          f"everything protected: exit 0, PROTECTED (got {r.returncode}: {tail(r)})")
    check(line(r, "ok", "sudo -n true") and line(r, "ok", "polkit") and line(r, "ok", "/etc/passwd")
          and line(r, "ok", "/etc/hosts") and line(r, "ok", "/etc/services")
          and line(r, "ok", "fleet checkout", CHECKOUT),
          "the protected run prints a line per fact: sudo, polkit, checkout, unit file, drop-in, config, program")
    pk = [c for c in calls if c[0] == "pkcheck"]
    check(pk and all("--detail" not in c for c in pk)
          and {c[c.index("--action-id") + 1] for c in pk} == {"org.freedesktop.systemd1.manage-units",
                                                             "org.freedesktop.systemd1.manage-unit-files"},
          f"polkit is asked about manage-units and manage-unit-files, with no --detail ({pk})")
    check(not any(c[0] == "systemctl" and c[1:2] != ["show"] for c in calls)
          and not any(c[0] == "sudo" and c[1:] not in (["-n", "true"], ["-n", "-l"]) for c in calls),
          "the run only reads: systemctl show, sudo -n true, sudo -n -l")

    for env, what in ((dict(FAKE_SUDO_TRUE="yes"), "sudo -n true succeeds"),
                      (dict(FAKE_SUDO_LIST="rules"), "sudo -n -l lists a command"),
                      (dict(FAKE_GROUPS="ada sudo"), "ada is in group sudo"),
                      (dict(FAKE_PKCHECK="yes"), "polkit authorizes unit management with no password"),
                      (dict(FAKE_PKCHECK="auth_self"), "polkit lets ada authenticate as itself")):
        r, _ = w.run("--agent", "ada", **env)
        check(r.returncode == 1 and line(r, "FAIL"), f"{what}: FAIL, exit 1 (got {r.returncode}: {tail(r)})")
    r, _ = w.run("--agent", "ada", FAKE_PKCHECK="no")
    check(r.returncode == 0 and line(r, "ok", "polkit"), f"polkit exit 1 (not authorized) is ok (got {r.returncode})")

    cases = [
        ("the watchdog unit file is writable", protected_units(**{wd: {"FragmentPath": str(w.writable)}}),
         ("may write", str(w.writable))),
        ("a drop-in is writable", protected_units(**{wd: {"DropInPaths": f"/etc/hosts {w.writable}"}}),
         ("may write", str(w.writable))),
        ("the config is read-only but owned", protected_units(**{wd: {"Environment": f"STALL_WATCHDOG_CONFIG={w.owned}"}}),
         ("owns", str(w.owned))),
        ("the config is absent in a directory ada may write",
         protected_units(**{wd: {"Environment": f"STALL_WATCHDOG_CONFIG={w.absent_here}"}}),
         ("may write", str(w.dir))),
        ("the session unit file is writable", protected_units(**{sess: {"FragmentPath": str(w.writable)}}),
         ("may write", str(w.writable))),
        ("the session unit is not a system unit", protected_units(**{sess: None}), ("not a system unit",)),
        ("the session unit runs as root", protected_units(**{sess: {"User": ""}}), ("runs as root",)),
        ("the watchdog runs as another user", protected_units(**{wd: {"User": "alan"}}), ("runs as alan",)),
    ]
    reds = {}
    for what, units, words in cases:
        r, _ = w.run("--agent", "ada", units=units)
        reds[what] = r.returncode == 1 and line(r, "FAIL", *words)
        check(reds[what], f"{what}: FAIL naming {words}, exit 1 (got {r.returncode}: {tail(r)})")
        r, _ = w.run("--agent", "ada", "--no-admin", units=units)
        if "runs as" in words[0]:
            # A unit running as anyone but the agents user is never a form's
            # trade-off: as root it IS root for the agent.
            check(r.returncode == 1 and line(r, "FAIL", *words),
                  f"--no-admin, {what}: still FAIL, exit 1 (got {r.returncode}: {tail(r)})")
        else:
            check(r.returncode == 4 and line(r, "UNPROTECTED", *words) and not line(r, "FAIL"),
                  f"--no-admin, {what}: UNPROTECTED, exit 4 (got {r.returncode}: {tail(r)})")
    if not reds["the config is read-only but owned"] or not reds["the watchdog unit file is writable"]:
        noverdict.append("an exposed fixture did not FAIL, so the protected run's PASS proves nothing")

    r, _ = w.run("--agent", "ada", units=protected_units(**{wd: {"ExecStart": "{ path=/usr/bin/python3 ; argv[]=/usr/bin/python3 %s ; ignore_errors=no }" % w.owned}}))
    check(r.returncode == 1 and line(r, "FAIL", "owns", str(w.owned), "the program the watchdog runs"),
          f"the watchdog's program in a tree ada owns FAILs, exit 1 (got {r.returncode}: {tail(r)})")
    r, _ = w.run(checkout=w.own_checkout)
    reds["the checkout is ada's"] = r.returncode == 1 and line(r, "FAIL", "owns", str(w.own_checkout))
    check(reds["the checkout is ada's"],
          f"a fleet checkout ada owns, read-only, FAILs naming ownership, exit 1 (got {r.returncode}: {tail(r)})")
    r, _ = w.run(checkout=w.linked_checkout)
    check(r.returncode == 1 and line(r, "FAIL", str(w.linked_checkout)),
          f"the protected tree reached through a link ada could replace FAILs, exit 1 (got {r.returncode}: {tail(r)})")
    r, _ = w.run("--no-admin", checkout=w.own_checkout)
    check(r.returncode == 4 and line(r, "UNPROTECTED", "owns", str(w.own_checkout)),
          f"--no-admin, an owned checkout is UNPROTECTED, exit 4 (got {r.returncode}: {tail(r)})")
    r, _ = w.run()
    check(line(r, "ok", "the identities fleet upgrade trusts"),
          f"the protected checkout's owner's identities file is out of ada's reach: ok ({tail(r)})")
    for what, ids, words in (("an identities file ada owns", w.owned, ("owns", str(w.owned))),
                             ("an identities file ada may create", w.absent_here, ("may write", "absent.json"))):
        r, _ = w.run("--identities", ids)
        reds[what] = r.returncode == 1 and line(r, "FAIL", *words, "the identities fleet upgrade trusts")
        check(reds[what], f"{what}: FAIL, exit 1 (got {r.returncode}: {tail(r)})")
    r, _ = w.run("--no-admin", "--identities", w.owned)
    check(r.returncode == 4 and line(r, "UNPROTECTED", "owns", str(w.owned)),
          f"--no-admin, an owned identities file is UNPROTECTED, exit 4 (got {r.returncode}: {tail(r)})")
    r, _ = w.run(checkout=None)
    check(r.returncode == 3 and line(r, "NO VERDICT", "fleet_checkout"),
          f"no host settings: the checkout cannot be checked, NO VERDICT, exit 3 (got {r.returncode}: {tail(r)})")
    if not reds["the checkout is ada's"]:
        noverdict.append("the owned checkout did not FAIL, so the protected checkout's ok proves nothing")
    r, _ = w.run("--agent", "ada", units=protected_units(**{wd: None}))
    check(r.returncode == 0 and line(r, "n/a", wd), f"no watchdog unit is n/a, exit 0 (got {r.returncode})")
    absent ="/etc/agent-fleet-verify-test-absent/stall-watchdog.json"
    r2, _ = w.run("--agent", "ada", units=protected_units(**{wd: {"Environment": f"STALL_WATCHDOG_CONFIG={absent}"}}))
    check(r2.returncode == 0 and line(r2, "ok", absent), f"an absent config ada cannot create is ok (got {r2.returncode})")

    for what, kw in (("a watchdog unit naming no config", dict(units=protected_units(**{wd: {"Environment": "TMUX_TMPDIR=/run/x"}}))),
                     ("systemctl does not answer", dict(FAKE_SYSTEMCTL="down")),
                     ("pkcheck errs", dict(FAKE_PKCHECK="error")),
                     ("pkcheck absent, polkit installed", dict(no_pkcheck=True))):
        r, _ = w.run("--agent", "ada", **kw)
        check(r.returncode == 3 and line(r, "NO VERDICT") and "== NO VERDICT" in r.stdout,
              f"{what}: NO VERDICT, exit 3 (got {r.returncode}: {tail(r)})")
    r, _ = w.run("--agent", "ada", units=protected_units(**{"polkit.service": None}), no_pkcheck=True)
    check(r.returncode == 0 and line(r, "ok", "no polkit"), f"no pkcheck and no polkit.service is ok (got {r.returncode})")
    r, _ = w.run("--agent", "ada", FAKE_SUDO_TRUE="yes", FAKE_SYSTEMCTL="down")
    check(r.returncode == 1, f"a FAIL outranks a NO VERDICT elsewhere: exit 1 (got {r.returncode})")

    r, _ = w.run("--agent", "ada", "--no-admin", units={})
    check(r.returncode == 4 and line(r, "UNPROTECTED", "not a system unit") and line(r, "n/a", wd)
          and "== UNPROTECTED" in r.stdout,
          f"--no-admin with user units and no watchdog: UNPROTECTED, exit 4 (got {r.returncode}: {tail(r)})")
    r, _ = w.run("--agent", "ada", "--no-admin", units={}, FAKE_SUDO_TRUE="yes")
    check(r.returncode == 1 and line(r, "FAIL", "sudo -n true"),
          f"--no-admin still FAILs a user with sudo: that form is for a user with none (got {r.returncode})")
    r, calls = w.run()
    check(r.returncode == 0 and not any(c[0] == "systemctl" and "claude-agent" in " ".join(c) for c in calls),
          f"no --agent: the host-level checks only, exit 0 (got {r.returncode}: {tail(r)})")
    for bad in (["--agent", "Ada!"], ["--agent"], ["--bogus"]):
        r, _ = w.run(*bad)
        check(r.returncode == 2, f"{' '.join(bad)} is refused, exit 2 (got {r.returncode})")


FAKE_LAUNCHCTL = HERE.parents[2] / "tests" / "fixtures" / "launchd" / "fake-launchctl"


def launchd_scenarios(base, w):
    """Section 7 of the docstring."""
    import importlib.util
    import plistlib
    prot, home, mine = base / "root-standin", base / "lhome", base / "mine"
    sysdir = prot / "LaunchDaemons"
    for d in (sysdir, home / "Library" / "LaunchAgents", mine):
        d.mkdir(parents=True)
    cfg_p, prog_p, py_p = prot / "stall-watchdog.json", prot / "watchdog.py", prot / "python3"
    cfg_p.write_text("{}\n")
    prog_p.write_text("# watchdog\n")
    py_p.write_text("# interpreter\n")
    state, calls = base / "launchd.json", base / "launchctl.calls"
    env = {"FLEET_SERVICE_BACKEND": "launchd", "FLEET_LAUNCHCTL": str(FAKE_LAUNCHCTL),
           "FAKE_LAUNCHD_STATE": str(state), "FAKE_LAUNCHD_CALLS": str(calls),
           "FLEET_LAUNCHD_SYSTEM_DIR": str(sysdir), "HOME": str(home), "FLEET_HOST_CONFIG": str(base / "host.json")}
    domain = f"gui/{os.getuid()}"

    def job(where, label, user="ada", cfg=None, prog=None):
        d = {"Label": label, "ProgramArguments": [str(py_p), str(prog or prog_p)],
             "RunAtLoad": True, "KeepAlive": True}
        if user:
            d["UserName"] = user
        if "stall-watchdog" in label:
            d["EnvironmentVariables"] = {"STALL_WATCHDOG_CONFIG": str(cfg or cfg_p)}
        path = where / f"{label}.plist"
        with open(path, "wb") as f:
            plistlib.dump(d, f)
        return path

    def world(**jobs):
        """Load the named jobs in the fake launchd: {label: (domain, plist)}."""
        if state.exists():
            state.unlink()
        for label, (dom, path) in jobs.items():
            subprocess.run([str(FAKE_LAUNCHCTL), "bootstrap", dom, str(path)], env=dict(os.environ, **env),
                           check=True, capture_output=True)

    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        spec = importlib.util.spec_from_file_location("verify_privileges", SCRIPT)
        vp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(vp)
        real = vp.changeable
        root = os.path.realpath(prot)
        vp.changeable = lambda q: None if os.path.realpath(q).startswith(root + os.sep) else real(q)
        S, W = "com.agent-fleet.session.ada", "com.agent-fleet.stall-watchdog.ada"

        def checks(guard="FAIL"):
            vp.lines.clear()
            vp.launchd_agent_checks("ada", "ada", guard)
            return list(vp.lines)

        def has(got, status, *words):
            return any(s == status and all(x in text for x in words) for s, text in got)

        world(**{S: ("system", job(sysdir, S)), W: ("system", job(sysdir, W))})
        got = checks()
        check(not any(s != "ok" for s, _ in got) and len(got) == 4 and has(got, "ok", str(sysdir / f"{S}.plist"))
              and has(got, "ok", "the watchdog's config", str(cfg_p)) and has(got, "ok", "watchdog's program", str(prog_p)),
              f"launchd: both LaunchDaemons with UserName ada, out of ada's reach: four ok lines ({got})")
        exposed = job(mine, S)
        world(**{S: ("system", exposed), W: ("system", job(sysdir, W))})
        got = checks()
        red = has(got, "FAIL", str(exposed), S)
        check(red, f"launchd: a session plist in a directory ada owns FAILs naming it ({got})")
        world(**{S: ("system", job(sysdir, S, user=None)), W: ("system", job(sysdir, W))})
        got = checks()
        check(has(got, "FAIL", S, "runs as root"), f"launchd: a job with no UserName runs as root: FAIL ({got})")
        world(**{S: ("system", job(sysdir, S)), W: ("system", job(sysdir, W, cfg=w.owned))})
        got = checks()
        check(has(got, "FAIL", "owns", str(w.owned), "the watchdog's config"),
              f"launchd: a watchdog config ada owns FAILs ({got})")
        world(**{S: (domain, job(home / "Library" / "LaunchAgents", S))})
        got = checks()
        check(has(got, "FAIL", S, "LaunchAgent", domain) and has(got, "n/a", W),
              f"launchd: the session only as a LaunchAgent in ada's own domain FAILs; no watchdog is n/a ({got})")
        got = checks("UNPROTECTED")
        check(has(got, "UNPROTECTED", S, "LaunchAgent"), f"launchd, no administrator: the LaunchAgent is UNPROTECTED ({got})")
        world()
        got = checks()
        check(has(got, "FAIL", S, "not loaded in launchd's system domain"),
              f"launchd: no session job at all FAILs ({got})")
        bad = base / "bad-print.txt"
        bad.write_text("Bad request.\nlaunchctl: an unexpected error\n")
        state.write_text(json.dumps({"canned": {f"print system/{S}": {"file": str(bad), "exit": 5}}}))
        got = checks()
        check(has(got, "NO VERDICT", S), f"launchd: launchctl giving no answer is NO VERDICT ({got})")
        if not red:
            noverdict.append("launchd: the exposed session plist did not FAIL, so the protected case proves nothing")
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    # End to end through the script, no stand-in: the wiring picks the launchd half.
    world(**{"com.agent-fleet.session.ada": (domain, job(home / "Library" / "LaunchAgents", "com.agent-fleet.session.ada"))})
    for args, code, status in ((["--agent", "ada"], 1, "FAIL"), (["--agent", "ada", "--no-admin"], 4, "UNPROTECTED")):
        # The fake launchctl is a python3 script: the interpreter's directory comes
        # AFTER the fakes, which still answer for sudo, id and pkcheck.
        r, fake_calls = w.run(*args, PATH=f"{w.bin}:{os.path.dirname(sys.executable)}",
                              **{k: v for k, v in env.items() if k != "FLEET_HOST_CONFIG"})
        check(r.returncode == code and line(r, status, "com.agent-fleet.session.ada", "LaunchAgent")
              and line(r, "ok", "launchd: only root") and not any(c[0] == "pkcheck" for c in fake_calls),
              f"launchd end to end {' '.join(args)}: {status}, exit {code}, no polkit asked (got {r.returncode}: {tail(r)})")


def main():
    if os.geteuid() == 0:
        print("NO VERDICT: run as root, which may write every path; the protected half would mean nothing")
        return 3
    bad = [p for p in PROTECTED if not os.path.exists(p) or os.stat(p).st_uid != 0]
    if bad:
        print(f"NO VERDICT: the root-owned fixtures are missing or not root's here: {bad}")
        return 3
    with tempfile.TemporaryDirectory(prefix="verify-privileges-test-") as tmp:
        w = World(Path(tmp))
        try:
            if os.access(w.owned, os.W_OK):
                noverdict.append(f"{w.owned} is writable by mode, so it cannot show ownership being caught")
            scenarios(w)
            launchd_scenarios(Path(tmp) / "launchd", w)
        finally:
            w.cleanup()
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
