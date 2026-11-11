#!/usr/bin/env python3
"""render-plist.test.py - installation/render-plist.py offline, on Linux and macOS.

The renderer runs as a subprocess, as its callers run it, with a PATH this test
builds: a directory holding a stand-in `tmux` (a script answering `-V`) and nothing
else the job could reach, so which tmux the rendered PATH reaches is decided by this
test and not by the machine. FLEET_PYTHON names the interpreter, and a temp host
settings file the label prefix, as `fleet install` gives them. No launchctl, no
sudo, no write outside a temp directory.

WHAT EACH CHECK IS FOR
  R  it renders: every placeholder filled, the label from the host's prefix,
     UserName the running user (system form) and none (user form), the config
     given, ProgramArguments[0] the fleet's interpreter, and a PATH that is the
     tmux's directory, then the interpreter's, then the system directories - and
     under an environment holding ONLY that PATH, as launchd runs the job, a bare
     `tmux` is the stand-in, the one the renderer was given.
  N  it refuses, printing ONE `NOT RENDERED` line and writing nothing: no tmux on
     its PATH (naming tmux and the PATH searched); a tmux that is found but does
     not run; an interpreter that does not exist.
  S  launchd-daemon.smoke.sh renders through this renderer and has no render of its
     own, prints the job's watchdog.log on a failed run before its cleanup removes
     it, and does not read a state file alone as capture. The smoke needs sudo and
     a real launchd, so CI never runs it: its TEXT is what is checked here, which
     is what keeps it testing the job an install produces. S runs first and does
     not depend on the renderer, so its verdict stands whatever R finds.

THE CONTROL. R is the positive evidence that the renderer was reached and can
render in this rig; if it does not render, every N case would pass by failing for
any reason at all, so the run is NO VERDICT (exit 3).

Exit codes: 0 every check passed; 1 a check failed; 3 NO VERDICT.
"""
import json
import os
import plistlib
import pwd
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
RENDER = os.path.join(HERE, "render-plist.py")
SMOKE = os.path.join(HERE, "launchd-daemon.smoke.sh")
SYSTEM = "/usr/bin:/bin:/usr/sbin:/sbin"
ME = pwd.getpwuid(os.getuid()).pw_name
PY = sys.executable
PLACEHOLDER = re.compile(r"<[A-Za-z][A-Za-z0-9 -]*>")

_failures = []


def check(name, cond, detail=""):
    print(("[PASS] " if cond else "[FAIL] ") + name + (" - " + detail if detail and not cond else ""))
    if not cond:
        _failures.append(name)


def stand_in(d, body):
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "tmux")
    with open(path, "w") as f:
        f.write("#!/bin/sh\n" + body)
    os.chmod(path, 0o755)
    return path


def render(tmp, name, path_var, form="system", python=PY):
    out = os.path.join(tmp, name + ".plist")
    host = os.path.join(tmp, "host.json")
    env = {"PATH": path_var, "HOME": os.path.join(tmp, "home"), "FLEET_PYTHON": python,
           "FLEET_HOST_CONFIG": host, "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8"}
    argv = [PY, RENDER, "--agent", "ada", "--agents-root", os.path.join(tmp, "agents"),
            "--checkout", os.path.join(tmp, "agents", "ada", "work"),
            "--state-dir", os.path.join(tmp, "agents", "ada", "state", "stall-watchdog"),
            "--tmux-dir", os.path.join(tmp, "agents", "run", "claude-tmux-ada"),
            "--config", "/etc/agent-fleet/stall-watchdog/ada.json", "--form", form, "--out", out]
    p = subprocess.run(argv, env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120)
    return p, out


def smoke_checks():
    """S: the smoke's text. Independent of the renderer, so it runs first and its
    verdict stands whatever the control below finds."""
    smoke = open(SMOKE, encoding="utf-8").read()
    # Comments dropped (the header names what the code must not do), continued
    # lines joined, so a command reads as one line.
    code = "\n".join(ln for ln in smoke.splitlines() if not ln.lstrip().startswith("#"))
    code = code.replace("\\\n", " ")
    check("S: the smoke renders its job with render-plist.py",
          re.search(r'"\$HERE/render-plist\.py"[^\n]*--form system', code) is not None)
    check("S: the smoke has no render of its own (it never reads the plist example)",
          "agent-stall-watchdog.plist.example" not in code and not re.search(r"\bsed\b[^\n]*<agent>", code))
    cleanup = re.search(r"^cleanup\(\) \{\n(.*?)^\}", code, re.M | re.S)
    body = cleanup.group(1) if cleanup else ""
    check("S: a failed run prints the job's watchdog.log before the cleanup removes it",
          re.search(r'tail -n 20 "\$T/state/watchdog\.log"', body) is not None
          and body.find("tail -n 20") < body.find('rm -rf "$T"'), body[:300])
    check("S: the smoke's capture property reads capture_error, not the state file alone",
          "capture_error" in code)


def main():
    smoke_checks()
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="wrp.", dir="/tmp"))
    try:
        os.makedirs(os.path.join(tmp, "home"))
        with open(os.path.join(tmp, "host.json"), "w") as f:
            json.dump({"schema": 1, "agents_root": os.path.join(tmp, "agents"), "fleet_checkout": "/tmp/x",
                       "claims_dir": "/tmp/x/claims", "launchd_prefix": "com.agent-fleet-test"}, f)
        tbin = os.path.join(tmp, "tmux-bin")
        tmux = stand_in(tbin, 'echo "tmux 9.9-stand-in"\n')
        pydir = os.path.dirname(PY)

        # R. the control: it renders.
        p, out = render(tmp, "system", tbin)
        if p.returncode != 0 or not os.path.isfile(out):
            print(f"NO VERDICT: the renderer did not render in this rig (exit {p.returncode}: "
                  f"{(p.stdout + p.stderr).strip()[-400:]}); no refusal below could be told from that")
            return 3
        print("[PASS] control: it renders with a tmux on its PATH")
        check("R: it prints nothing on success", p.stdout == "" and p.stderr == "", repr(p.stdout + p.stderr))
        text = open(out, encoding="utf-8").read()
        check("R: no placeholder is left", not PLACEHOLDER.findall(
            re.sub(r"</?(plist|dict|key|string|array|integer|true|false)\b[^>]*>|<!DOCTYPE[^>]*>|<\?xml[^>]*>", "", text)),
            text[:200])
        d = plistlib.loads(text.encode())
        env = d.get("EnvironmentVariables", {})
        want_path = ":".join(dict.fromkeys([tbin, pydir, *SYSTEM.split(":")]))
        check("R: the label is the host's prefix, the agent's watchdog label",
              d.get("Label") == "com.agent-fleet-test.stall-watchdog.ada", repr(d.get("Label")))
        check("R: UserName is the user running the renderer (system form)", d.get("UserName") == ME,
              repr(d.get("UserName")))
        check("R: ProgramArguments runs watchdog.py with the fleet's interpreter (FLEET_PYTHON)",
              d["ProgramArguments"][0] == PY and d["ProgramArguments"][1].endswith(
                  "/.claude/skills/stall-watchdog/watchdog.py"), repr(d["ProgramArguments"]))
        check("R: PATH is the tmux's directory, the interpreter's, then the system directories",
              env.get("PATH") == want_path, f"{env.get('PATH')!r} vs {want_path!r}")
        check("R: the config given, the session's tmux directory",
              env.get("STALL_WATCHDOG_CONFIG") == "/etc/agent-fleet/stall-watchdog/ada.json"
              and env.get("TMUX_TMPDIR") == os.path.join(tmp, "agents", "run", "claude-tmux-ada"), repr(env))
        r = subprocess.run(["tmux", "-V"], env={"PATH": env.get("PATH", "")}, capture_output=True, text=True)
        check("R: under an environment of ONLY the job's PATH, a bare tmux is the one the renderer found",
              r.returncode == 0 and "stand-in" in r.stdout
              and shutil.which("tmux", path=env.get("PATH")) == tmux, f"{r.returncode} {r.stdout!r}")
        p, out_u = render(tmp, "user", tbin, form="user")
        du = plistlib.load(open(out_u, "rb")) if p.returncode == 0 else {}
        check("R: the user form renders a LaunchAgent: no UserName, the same job otherwise",
              p.returncode == 0 and "UserName" not in du and du.get("Label") == d.get("Label"),
              (p.stdout + p.stderr).strip())

        # N. the refusals: one NOT RENDERED line, nothing written.
        empty = os.path.join(tmp, "empty-bin")
        os.makedirs(empty)
        p, out_n = render(tmp, "no-tmux", empty)
        lines = p.stdout.splitlines()
        check("N: no tmux on its PATH: ONE NOT RENDERED line naming tmux and the PATH searched, nothing written",
              p.returncode == 1 and len(lines) == 1 and lines[0].startswith("NOT RENDERED: no tmux on PATH")
              and f"({empty})" in lines[0] and not os.path.exists(out_n), f"rc={p.returncode} {lines!r}")
        broken = os.path.join(tmp, "broken-bin")
        stand_in(broken, "echo 'error while loading shared libraries' >&2\nexit 127\n")
        p, out_b = render(tmp, "broken-tmux", broken)
        lines = p.stdout.splitlines()
        check("N: a tmux that is found but does not run under the job's PATH: refused, nothing written",
              p.returncode == 1 and len(lines) == 1 and lines[0].startswith("NOT RENDERED: tmux -V")
              and not os.path.exists(out_b), f"rc={p.returncode} {lines!r}")
        gone = os.path.join(tmp, "no-such-dir", "python3")
        p, out_g = render(tmp, "no-python", tbin, python=gone)
        lines = p.stdout.splitlines()
        check("N: an interpreter that does not exist: refused naming it, nothing written",
              p.returncode == 1 and len(lines) == 1 and lines[0].startswith("NOT RENDERED:")
              and gone in lines[0] and not os.path.exists(out_g), f"rc={p.returncode} {lines!r}")

    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    if _failures:
        print(f"FAILED: {len(_failures)} check(s): " + "; ".join(_failures))
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
