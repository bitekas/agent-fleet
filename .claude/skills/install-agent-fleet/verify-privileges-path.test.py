#!/usr/bin/env python3
"""verify-privileges-path.test.py - verify-privileges.py checks the TMUX the protected
stall watchdog runs, and every directory searched before it on the job's PATH.

Usage: python3 .claude/skills/install-agent-fleet/verify-privileges-path.test.py
       (tests/run-all.sh discovers and runs it; no real sudo, polkit, systemd or launchd)

watchdog.py runs a bare `tmux`, so the tmux the job runs is the first one its PATH
reaches. An agents user that can change that file, or put a `tmux` in a directory
searched before it, runs its own program wherever the watchdog runs tmux - and a tmux
that answers every capture with an idle pane switches the protected watchdog off. On
macOS the renderer writes the job's PATH from where tmux and the interpreter are, so a
tmux in the agents user's own ~/.local/bin (the CI Mac mini's layout) puts that
directory first on the job's PATH.

THE HARNESS is verify-privileges.test.py's, imported, not copied: its fake systemctl,
sudo, pkcheck and id, its World of real files, and its stand-in for a root-owned
directory holding a tmux (World.tmux_bin: no test that must not run as root can make a
root-owned tmux, and macOS has none at all). Every EXPOSED tmux and directory below is
a real file or directory this user owns or may write, judged by the real rule
(fleetlib.paths.changeable).

WHAT EACH CHECK IS FOR
  D  the bare command names: verify-privileges' WATCHDOG_COMMANDS equals the set this
     test derives from watchdog.py's own source (every subprocess or exec call whose
     program is a bare name). A watchdog that starts running a second bare command
     reds here instead of going unchecked. The derivation is proved on a synthetic
     source first (a bare call found, through subprocess and through a runner
     imported by name; an absolute one and sys.executable not), and it must find
     tmux in watchdog.py, or there is no verdict.
  S  systemd, end to end through the script:
     S1 (control) no PATH in the unit, so the system manager's environment block's,
        whose first directory is the stand-in: PROTECTED, the ok line naming the tmux
        and that source.
     S2 the unit's own Environment=PATH wins over the manager's (whose PATH here
        reaches no tmux): ok, naming Environment= as the source.
     S3 the CI Mac mini's layout, on systemd: tmux in a ~/.local/bin this user owns:
        FAIL naming "the tmux the watchdog runs", exit 1; UNPROTECTED, exit 4, with
        --no-admin.
     S4 a directory this user may write, searched before a protected tmux: FAIL naming
        that directory, and no finding about the tmux itself. Root's directories and
        one that does not exist under root's / before the same tmux: PROTECTED.
     S5 a relative entry, or an empty one (the working directory), before any tmux:
        NO VERDICT, exit 3. A relative entry AFTER the tmux is never searched: still
        PROTECTED.
     S6 no tmux on the PATH: NO VERDICT, exit 3.
     S7 the manager's environment block names no PATH: the line names systemd's fixed
        default as the source (its verdict depends on this machine's /usr/bin).
     S8 the unit names an EnvironmentFile, whose PATH would win and is not read:
        NO VERDICT, exit 3.
     S9 systemctl show-environment fails: NO VERDICT, exit 3.
  L  launchd, in process (verify-privileges.test.py section 7's stand-in for root's
     directory):
     L1 (control) the plist's PATH reaches a protected tmux: five ok lines, the tmux's
        naming the plist's EnvironmentVariables as the source.
     L2 no PATH key: the line names launchd's default PATH as the source.
     L3 the CI Mac mini's layout as render-plist.py renders it there: python3 and tmux
        in this user's own ~/.local/bin, PATH=<that>:/usr/bin:/bin:/usr/sbin:/sbin:
        FAIL for the tmux AND for the interpreter.
     L4 a directory this user may write, searched before a protected tmux: FAIL
        naming the directory.
     L5 a relative entry before any tmux: NO VERDICT.

THE CONTROLS. S1 and L1: a protected tmux must pass, or no FAIL here proves anything,
and the run is NO VERDICT (exit 3). D: the derivation must find the bare call in its
synthetic source and nothing else there, and must find tmux in watchdog.py; else NO
VERDICT, because an empty derivation would agree with an emptied WATCHDOG_COMMANDS.

Run as root it is NO VERDICT: root may write every path.
Exit codes: 0 pass; 1 a check failed; 3 NO VERDICT.
"""
import ast
import importlib.util
import os
import plistlib
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(os.path.realpath(__file__)).parent
SCRIPT = HERE / "verify-privileges.py"
WATCHDOG = HERE.parent / "stall-watchdog" / "watchdog.py"
_spec = importlib.util.spec_from_file_location("verify_privileges_test", HERE / "verify-privileges.test.py")
vt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vt)

failures, noverdict = [], []
WD = "claude-agent-ada-stall-watchdog.service"
ENV = "TMUX_TMPDIR=/run/claude-tmux-ada STALL_WATCHDOG_CONFIG=/etc/hosts"


def check(cond, what):
    print(("ok    " if cond else "FAIL  ") + what)
    if not cond:
        failures.append(what)


# --------------------------------------------------------------------- D. the names

RUNNERS = {"run", "Popen", "call", "check_call", "check_output", "getoutput", "getstatusoutput",
           "system", "popen", "execv", "execve", "execvp", "execvpe", "execl", "execle", "execlp",
           "execlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe", "spawnl", "spawnlp", "posix_spawn",
           "posix_spawnp"}


def bare_commands(source):
    """(bare names, calls seen, unreadable calls) of every subprocess/os call in `source`
    that starts a program: the program's name when it is a bare word, nothing when it is
    an absolute path or sys.executable, and an unreadable entry when this cannot tell."""
    names, seen, unreadable = set(), 0, []
    tree = ast.parse(source)
    # A runner imported by name (`from subprocess import run as go`) is called bare.
    aliases = {a.asname or a.name: a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
               and n.module in ("subprocess", "os") for a in n.names if a.name in RUNNERS}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        f = node.func
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in ("subprocess", "os"):
            name = f.attr
        elif isinstance(f, ast.Name):
            # an exec function passed in as a parameter (maybe_reexec's execv), or one imported by name
            name = aliases.get(f.id, f.id)
        else:
            continue
        if name not in RUNNERS:
            continue
        seen += 1
        a = node.args[0]
        a = a.left if isinstance(a, ast.BinOp) else a           # ("tmux",) + args
        if isinstance(a, (ast.Tuple, ast.List)) and a.elts:
            a = a.elts[0]
        if isinstance(a, ast.Constant) and isinstance(a.value, str):
            word = a.value.split()[0] if a.value.split() else ""
            if word and not os.path.isabs(word):
                names.add(word)
        elif not (isinstance(a, ast.Attribute) and isinstance(a.value, ast.Name)
                  and (a.value.id, a.attr) == ("sys", "executable")):
            unreadable.append(f"line {node.lineno}: {ast.unparse(node)[:80]}")
    return names, seen, unreadable


def derivation():
    synth = ("import os, subprocess, sys\nfrom subprocess import run as go\nsubprocess.run(('tmuxish',) + a)\n"
             "subprocess.run(['/usr/bin/true'])\nos.execv(sys.executable, [sys.executable])\n"
             "def f(execv=os.execv):\n    execv(sys.executable, [])\ngo(['bareword', '-x'])\nprint('not a runner')\n")
    names, seen, unreadable = bare_commands(synth)
    if (names, seen, unreadable) != ({"tmuxish", "bareword"}, 5, []):
        noverdict.append(f"D: the derivation misreads its synthetic source ({names}, {seen} calls, {unreadable})")
        return
    names, seen, unreadable = bare_commands(WATCHDOG.read_text(encoding="utf-8"))
    if "tmux" not in names:
        noverdict.append(f"D: the derivation finds no tmux in {WATCHDOG} ({names}, {seen} calls), so it reads nothing")
        return
    vp = load()
    check(not unreadable, f"D: every program watchdog.py starts is readable here ({unreadable})")
    check(set(getattr(vp, "WATCHDOG_COMMANDS", ())) == names,
          f"D: WATCHDOG_COMMANDS {getattr(vp, 'WATCHDOG_COMMANDS', None)} is exactly the bare names watchdog.py "
          f"runs, derived from its source ({sorted(names)}, {seen} calls)")


def load():
    spec = importlib.util.spec_from_file_location("verify_privileges", SCRIPT)
    vp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vp)
    return vp


# --------------------------------------------------------------------- S. systemd

def tmux_in(d, body=vt.TMUX_STANDIN):
    d.mkdir(parents=True, exist_ok=True)
    (d / "tmux").write_text(body)
    (d / "tmux").chmod(0o755)
    return d / "tmux"


def systemd(base):
    w = vt.World(base)
    std = w.tmux_bin

    def go(path=None, *args, manager=None, **props):
        env = ENV + (f" PATH={path}" if path is not None else "")
        units = vt.protected_units(**{WD: dict({"Environment": env}, **props)})
        extra = {} if manager is None else {"FAKE_MANAGER_PATH": manager}
        r, _ = w.run("--agent", "ada", *args, units=units, **extra)
        return r

    try:
        r = go()
        s1 = r.returncode == 0 and "== PROTECTED" in r.stdout and vt.line(
            r, "ok", "watchdog's tmux", str(std / "tmux"), "system manager's environment")
        check(s1, f"S1 control: the manager's PATH reaches a protected tmux: PROTECTED, the ok line names "
                  f"the tmux and its source (got {r.returncode}: {vt.tail(r)})")
        if not s1:
            noverdict.append("S1: a protected tmux did not pass, so no FAIL below proves anything")
        empty = base / "no-tmux-bin"
        empty.mkdir()
        r = go(f"{std}:/usr/bin", manager=f"{empty}")
        check(r.returncode == 0 and vt.line(r, "ok", "watchdog's tmux", str(std / "tmux"), "Environment="),
              f"S2: the unit's Environment=PATH wins over the manager's: ok, naming Environment= (got "
              f"{r.returncode}: {vt.tail(r)})")

        mine = tmux_in(base / "ada-home" / ".local" / "bin")
        layout = f"{mine.parent}:/usr/bin:/bin:/usr/sbin:/sbin"
        r = go(layout)
        check(r.returncode == 1 and vt.line(r, "FAIL", "the tmux the watchdog runs", str(mine)),
              f"S3: the CI Mac mini's layout: a tmux in a ~/.local/bin ada owns FAILs, exit 1 "
              f"(got {r.returncode}: {vt.tail(r)})")
        r = go(layout, "--no-admin")
        check(r.returncode == 4 and vt.line(r, "UNPROTECTED", "the tmux the watchdog runs", str(mine)),
              f"S3, --no-admin: UNPROTECTED, exit 4 (got {r.returncode}: {vt.tail(r)})")

        shadow = base / "shadow-bin"
        shadow.mkdir()
        r = go(f"{shadow}:{std}:/usr/bin")
        check(r.returncode == 1 and vt.line(r, "FAIL", str(shadow), "searched before", str(std / "tmux"))
              and not vt.line(r, "FAIL", "the tmux the watchdog runs"),
              f"S4: a directory ada may write, before a protected tmux, FAILs naming that directory and not "
              f"the tmux (got {r.returncode}: {vt.tail(r)})")
        r = go(f"/usr/sbin:/sbin:/agent-fleet-test-absent/bin:{std}:/usr/bin")
        check(r.returncode == 0 and vt.line(r, "ok", "watchdog's tmux", str(std / "tmux")),
              f"S4: root's directories, and one that does not exist under root's /, before a protected tmux: "
              f"PROTECTED (got {r.returncode}: {vt.tail(r)})")

        for path, what in ((f"bin:{std}", "a relative entry"), (f":{std}", "an empty entry")):
            r = go(path)
            check(r.returncode == 3 and vt.line(r, "NO VERDICT", "relative") and "== NO VERDICT" in r.stdout,
                  f"S5: {what} before any tmux: NO VERDICT, exit 3 (got {r.returncode}: {vt.tail(r)})")
        r = go(f"{std}:bin")
        check(r.returncode == 0, f"S5: a relative entry after the tmux is never searched: PROTECTED "
                                 f"(got {r.returncode}: {vt.tail(r)})")
        r = go(f"{empty}:/agent-fleet-test-absent/bin")
        check(r.returncode == 3 and vt.line(r, "NO VERDICT", "no tmux on"),
              f"S6: no tmux on the PATH: NO VERDICT, exit 3 (got {r.returncode}: {vt.tail(r)})")
        r = go(manager="-")
        check(any(l.split()[0] in ("ok", "FAIL", "NO") and "systemd's fixed default" in l
                  for l in r.stdout.splitlines() if l.strip()),
              f"S7: no PATH in the manager's environment block: the line names systemd's fixed default "
              f"({vt.tail(r)})")
        r = go(None, EnvironmentFiles="/etc/hosts (ignore_errors=no)")
        check(r.returncode == 3 and vt.line(r, "NO VERDICT", "EnvironmentFile", "/etc/hosts"),
              f"S8: an EnvironmentFile, whose PATH would win, is NO VERDICT (got {r.returncode}: {vt.tail(r)})")
        r = go(manager="fail")
        check(r.returncode == 3 and vt.line(r, "NO VERDICT", "show-environment"),
              f"S9: systemctl show-environment fails: NO VERDICT, exit 3 (got {r.returncode}: {vt.tail(r)})")
    finally:
        w.cleanup()


# --------------------------------------------------------------------- L. launchd

def launchd(base):
    prot, home, mine = base / "root-standin", base / "lhome", base / "mine"
    sysdir = prot / "LaunchDaemons"
    for d in (sysdir, home / "Library" / "LaunchAgents", mine):
        d.mkdir(parents=True)
    cfg_p, prog_p, py_p = prot / "stall-watchdog.json", prot / "watchdog.py", prot / "python3"
    for q in (cfg_p, prog_p, py_p):
        q.write_text("#\n")
    ptmux = tmux_in(prot / "bin")
    state, calls = base / "launchd.json", base / "launchctl.calls"
    env = {"FLEET_SERVICE_BACKEND": "launchd", "FLEET_LAUNCHCTL": str(vt.FAKE_LAUNCHCTL),
           "FAKE_LAUNCHD_STATE": str(state), "FAKE_LAUNCHD_CALLS": str(calls),
           "FLEET_LAUNCHD_SYSTEM_DIR": str(sysdir), "HOME": str(home), "FLEET_HOST_CONFIG": str(base / "host.json")}
    S, W = "com.agent-fleet.session.ada", "com.agent-fleet.stall-watchdog.ada"

    def job(label, interp=py_p, path=None):
        d = {"Label": label, "UserName": "ada", "ProgramArguments": [str(interp), str(prog_p)],
             "RunAtLoad": True, "KeepAlive": True}
        if label == W:
            d["EnvironmentVariables"] = {"STALL_WATCHDOG_CONFIG": str(cfg_p)}
            if path is not None:
                d["EnvironmentVariables"]["PATH"] = path
        p = sysdir / f"{label}.plist"
        with open(p, "wb") as f:
            plistlib.dump(d, f)
        return p

    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        vp = load()
        real, root = vp.changeable, os.path.realpath(prot)
        vp.changeable = lambda q: None if os.path.realpath(q).startswith(root + os.sep) else real(q)

        def checks(**watchdog):
            if state.exists():
                state.unlink()
            for label, path in ((S, job(S)), (W, job(W, **watchdog))):
                subprocess.run([str(vt.FAKE_LAUNCHCTL), "bootstrap", "system", str(path)],
                               env=dict(os.environ, **env), check=True, capture_output=True)
            vp.lines.clear()
            vp.launchd_agent_checks("ada", "ada", "FAIL")
            return list(vp.lines)

        def has(got, status, *words):
            return any(s == status and all(x in text for x in words) for s, text in got)

        got = checks(path=f"{ptmux.parent}:/usr/bin:/bin:/usr/sbin:/sbin")
        l1 = len(got) == 5 and all(s == "ok" for s, _ in got) and has(
            got, "ok", "watchdog's tmux", str(ptmux), "EnvironmentVariables")
        check(l1, f"L1 control: the plist's PATH reaches a protected tmux: five ok lines, the tmux's naming "
                  f"its source ({got})")
        if not l1:
            noverdict.append("L1: a protected tmux did not pass, so no FAIL below proves anything")
        got = checks()
        check(any("launchd's default" in text for _, text in got),
              f"L2: no PATH key: the line names launchd's default PATH ({got})")
        local = mine / ".local" / "bin"
        mtmux = tmux_in(local)
        (local / "python3").write_text("#!/bin/sh\n")
        (local / "python3").chmod(0o755)
        got = checks(interp=local / "python3", path=f"{local}:/usr/bin:/bin:/usr/sbin:/sbin")
        check(has(got, "FAIL", "the tmux the watchdog runs", str(mtmux))
              and has(got, "FAIL", "the interpreter the watchdog runs", str(local / "python3")),
              f"L3: the CI Mac mini's layout, as render-plist.py renders it: FAIL for the tmux and for the "
              f"interpreter ({got})")
        shadow = mine / "shadow-bin"
        shadow.mkdir()
        got = checks(path=f"{shadow}:{ptmux.parent}:/usr/bin")
        check(has(got, "FAIL", str(shadow), "searched before", str(ptmux))
              and not has(got, "FAIL", "the tmux the watchdog runs"),
              f"L4: a directory ada may write, before a protected tmux, FAILs naming that directory ({got})")
        got = checks(path=f"bin:{ptmux.parent}")
        check(has(got, "NO VERDICT", "relative", "'bin'"), f"L5: a relative entry before any tmux: NO VERDICT ({got})")
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
    bad = [p for p in vt.PROTECTED if not os.path.exists(p) or os.stat(p).st_uid != 0]
    if bad:
        print(f"NO VERDICT: the root-owned fixtures are missing or not root's here: {bad}")
        return 3
    derivation()
    with tempfile.TemporaryDirectory(prefix="verify-privileges-path-test-") as tmp:
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
