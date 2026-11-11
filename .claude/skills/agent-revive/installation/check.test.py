#!/usr/bin/env python3
"""Regression guard for agent-revive/installation/check: its LAST line names the
leg that failed.

`fleet check-all` shows each check's last line and nothing else, so that line is
the only place an operator reads the cause. A verdict line that names a generic
cause ("the install record is stale") while the real gap is one absent file sends
the operator to redo a step that was already done.

HOW IT RUNS. The real check is copied into a throwaway fleet tree under a temp
directory, with every leg it measures made to pass by a fake of the program or
file that leg reads: tmux, node (and its redaction test), x11vnc, websockify and
tailscale are scripts first on PATH; jq, python3 and the coreutils are the host's;
`uname` is a script too, so the platform the check believes it is on is the case's
choice (Linux unless a case says Darwin) and every case runs the same on both
systems;
the sign-in driver's installed modules and browser are empty directories in the
copied tree; the pool picker and the minter are files beside it; PyJWT and
cryptography are importable stubs. Nothing outside the temp directory is read or
written, and no real tailscale, X server or account pool is reached.

THE CONTROL. With every leg made to pass, the check must exit 0. Each case below
then breaks exactly the legs it names, so the verdict line can be compared
against a known set of failing legs. If the control does not exit 0, the harness
has not built a clean host and no case can say which leg its verdict is about:
that is NO VERDICT (exit 3), never a pass or a fail of the check.

THE MACOS CASES. On Darwin the check asks the Aqua session (`launchctl print
gui/<uid>`, through a fake named by FLEET_LAUNCHCTL) instead of DISPLAY, does not run
the share's legs or require its config keys (the share does not exist on macOS), and
reads a file's mode with BSD `stat -f`, which a fake `stat` that refuses GNU's `-c`
forces. Their control is the Darwin host with every leg passing: exit 0, from a
config with no share block at all.

Run: python3 .claude/skills/agent-revive/installation/check.test.py
Exits 0 when every case passes, 1 on a failure, 3 on NO VERDICT.
"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
SKILL = os.path.dirname(HERE)
CHECK = os.path.join(HERE, "check")

_failures = []
# The legs that pass in the first case, by the labels their lines carry; none may
# appear in a verdict that is about the pool file alone.
PASSING_LEGS = ("tmux", "jq", "config", "install-state", "install record", "node", "display",
                "driver deps", "driver browser", "redaction test", "x11vnc", "websockify",
                "noVNC", "tailscale", "recovery", "pool picker", "lease_file", "ledger_file",
                "unnamed leg")


def check(name, cond, detail=""):
    print(("[PASS] " if cond else "[FAIL] ") + name + (" - " + detail if detail and not cond else ""))
    if not cond:
        _failures.append(name)


def write(path, text="", mode=0o644):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(path, mode)
    return path


def tool(fakes, name, body):
    return write(os.path.join(fakes, name), "#!/bin/sh\n" + body, 0o755)


def build(tmp):
    """A fleet tree holding a copy of the real check, and a host where every leg passes."""
    fleet = os.path.join(tmp, "fleet")
    skill = os.path.join(fleet, ".claude", "skills", "agent-revive")
    shutil.copy(CHECK, write(os.path.join(skill, "installation", "check"), mode=0o755))
    shutil.copy(os.path.join(SKILL, "SKILL.md"), os.path.join(skill, "SKILL.md"))
    drv = os.path.join(skill, "signin_driver")
    write(os.path.join(drv, "redaction.test.mjs"), "// run by the fake node\n")
    os.makedirs(os.path.join(drv, "node_modules", "playwright-extra"))
    os.makedirs(os.path.join(drv, "node_modules", "puppeteer-extra-plugin-stealth"))
    write(os.path.join(drv, "browsers", "chromium-1", "chrome-linux64", "chrome"), mode=0o755)
    picker = write(os.path.join(fleet, ".claude", "skills", "agent-health", "pool_pick.py"))
    write(os.path.join(fleet, ".claude", "skills", "google-spreadsheet", "gsheets.py"))

    fakes = os.path.join(tmp, "fakes")
    tool(fakes, "tmux", 'echo "tmux 3.6"\n')
    tool(fakes, "node", '[ "$1" = --version ] && { echo v22.0.0; exit 0; }\necho "ok 1 - stub"\n')
    tool(fakes, "x11vnc", 'echo "x11vnc: 0.9.17"\nexit "${FAKE_X11VNC_RC:-0}"\n')
    tool(fakes, "websockify", "exit 0\n")
    tool(fakes, "uname", 'echo "${FAKE_UNAME:-Linux}"\n')
    tool(fakes, "launchctl", '[ "$1 $2" = "print gui/$(id -u)" ] || exit 64\n'
         'echo "gui/$(id -u) = {"\nexit "${FAKE_LAUNCHCTL_RC:-0}"\n')
    # BSD stat: no -c, and -f %Lp prints the permission bits in octal.
    bsd = os.path.join(tmp, "bsd")
    tool(bsd, "stat", '[ "$1" = -f ] && [ "$2" = %Lp ] || { echo "stat: illegal option -- ${1#-}" >&2; exit 1; }\n'
         'exec python3 -c \'import os, sys; print(format(os.stat(sys.argv[1]).st_mode & 0o7777, "o"))\' "$3"\n')
    tailscale = tool(fakes, "tailscale", "echo '" + json.dumps({"Self": {
        "DNSName": "fixture-node.example.",
        "CapMap": {"funnel": [], "https://tailscale.com/cap/funnel-ports?ports=10000": []}}}) + "'\n")
    state = write(os.path.join(tmp, "install", "installation", ".install-state.json"), json.dumps(
        {"hosts": {socket.gethostname(): {"version": declared_version()}}}))
    tool(fakes, "fleet", f'echo "{state}"\n')
    pylib = os.path.join(tmp, "pylib")
    write(os.path.join(pylib, "jwt.py"))
    write(os.path.join(pylib, "cryptography.py"))
    novnc = os.path.dirname(write(os.path.join(tmp, "novnc", "vnc.html"), "<html></html>\n"))

    secrets = os.path.join(tmp, "secrets")
    accounts = {"pool_file": os.path.join(secrets, "pool.json"),
                "lease_file": os.path.join(secrets, "leases.json"),
                "ledger_file": os.path.join(tmp, "ledger.md"),
                "profiles_dir": os.path.join(secrets, "profiles")}
    for k in ("pool_file", "lease_file", "ledger_file"):
        write(accounts[k], "{}\n", 0o600)
    config = write(os.path.join(tmp, "install", "config.json"), json.dumps({
        "fleet": {"agents_home": os.path.join(tmp, "agents"),
                  "tmux": {"tmpdir": "/run/claude-tmux-<agent>", "target": "claude-<agent>:0"},
                  "systemd_unit": "claude-agent-<agent>.service"},
        "accounts": accounts,
        "recovery": {"mailbox": "recovery@example.com"},
        "share": {"vnc_port": 5901, "web_port": 6081, "funnel_port": 10000, "novnc_dir": novnc,
                  "page": "vnc.html", "minutes": 10, "tailscale": [tailscale]}}))
    # The fakes first; then this test's own interpreter's directory (the check runs
    # `python3`), then the system directories for jq and the coreutils.
    path = f"{fakes}:{os.path.dirname(sys.executable)}:/usr/bin:/bin"
    env = {"PATH": path, "HOME": os.path.join(tmp, "home"), "LANG": "C.UTF-8",
           "DISPLAY": ":99", "FLEET_BIN": os.path.join(fakes, "fleet"), "PYTHONPATH": pylib,
           "PYTHONDONTWRITEBYTECODE": "1"}
    darwin_config = write(os.path.join(tmp, "install", "config.darwin.json"), json.dumps({
        "fleet": {"agents_home": os.path.join(tmp, "agents"),
                  "tmux": {"tmpdir": "<agents-root>/run/claude-tmux-<agent>", "target": "claude-<agent>:0"},
                  "systemd_unit": "com.agent-fleet.session.<agent>"},
        "accounts": accounts,
        "recovery": {"mailbox": "recovery@example.com"}}))
    darwin_env = dict(env, PATH=f"{bsd}:{path}", FAKE_UNAME="Darwin",
                      FLEET_LAUNCHCTL=os.path.join(fakes, "launchctl"))
    darwin_env.pop("DISPLAY")
    return {"check": os.path.join(skill, "installation", "check"), "config": config, "env": env,
            "pool": accounts["pool_file"], "picker": picker,
            "darwin": {"check": os.path.join(skill, "installation", "check"), "config": darwin_config,
                       "env": darwin_env}}


def declared_version():
    with open(os.path.join(SKILL, "SKILL.md"), encoding="utf-8") as f:
        for line in f:
            if line.startswith("version:"):
                return int(line.split(":", 1)[1])
    raise SystemExit("NO VERDICT: SKILL.md declares no version")


def run(w, **extra):
    env = dict(w["env"], **extra)
    p = subprocess.run(["bash", w["check"], w["config"]], capture_output=True, text=True, env=env,
                       stdin=subprocess.DEVNULL, timeout=120)
    lines = [ln.strip() for ln in (p.stdout + "\n" + p.stderr).splitlines() if ln.strip()]
    return p.returncode, (lines[-1] if lines else ""), p.stdout + p.stderr


def pairing():
    """Every `bump` call in the check shares its line with, and follows, its own
    `note "<leg>: ..."`: the verdict names a failed leg by the note before its
    bump, so a bump without one would name whichever leg was noted last."""
    with open(CHECK, encoding="utf-8") as f:
        lines = [ln for ln in f if re.search(r"\bbump [0-9]", ln)]
    paired = [ln for ln in lines if re.search(r'\bnote "[^":]+:[^"]*"[^\n]*\bbump [0-9]', ln)]
    check("every bump follows its own `note \"<leg>: ...\"` on the same line "
          f"({len(paired)} of {len(lines)} bump call(s))", lines and paired == lines,
          "unpaired: " + " | ".join(ln.strip()[:120] for ln in lines if ln not in paired))


def main():
    pairing()
    tmp = tempfile.mkdtemp(prefix="agent-revive-check-test-")
    try:
        w = build(tmp)
        rc, last, out = run(w)
        if rc != 0 or not last.startswith("OK:"):
            print(out)
            print(f"NO VERDICT: the control did not exit 0 (exit {rc}, last line {last!r}); the "
                  "harness did not build a host where every leg passes, so no case below could "
                  "say which leg its verdict is about")
            return 1 if _failures else 3  # the pairing check needs no control
        print("[PASS] control: every leg made to pass exits 0 with OK")

        # macOS. The control first: every leg passes from a config with no share block.
        d = w["darwin"]
        rc, last, out = run(d)
        check("macos control: every leg passing exits 0 with OK, from a config with no share block",
              rc == 0 and last.startswith("OK:"), f"rc={rc} last={last!r}\n{out}")
        check("macos: the display leg is the Aqua session, and the share is not on macOS",
              "display: the Aqua session gui/" in out and "share: not on macOS" in out
              and not re.search(r"^  (x11vnc|websockify|noVNC|tailscale|xvfb-run):", out, re.M), out)
        check("macos: a file's mode comes from BSD stat -f when stat -c is refused",
              "(mode 600)" in out and "(mode ?)" not in out, out)
        rc, last, out = run(d, FAKE_X11VNC_RC="1")
        check("macos: a broken x11vnc changes nothing (the share's legs are not run)",
              rc == 0 and last.startswith("OK:"), f"rc={rc} last={last!r}")
        rc, last, out = run(d, FAKE_LAUNCHCTL_RC="113")
        check("macos: no Aqua session: exit 1, and the last line names the display leg",
              rc == 1 and "display" in last and "accounts" not in last, f"rc={rc} last={last!r}")

        # A fresh install's host: the account pool file is the one leg missing.
        os.rename(w["pool"], w["pool"] + ".away")
        rc, last, out = run(w)
        check("only the pool file missing: exit 1, and the last line names accounts.pool_file "
              "and no leg that passed",
              rc == 1 and "accounts.pool_file" in last
              and not any(s in last for s in PASSING_LEGS),
              f"rc={rc} last={last!r}")

        # Two legs at the same level: both are named.
        rc, last, out = run(w, FAKE_X11VNC_RC="1")
        check("pool file and x11vnc failing: the last line names both",
              rc == 1 and "accounts.pool_file" in last and "x11vnc" in last, f"rc={rc} last={last!r}")

        # A level-2 leg decides the verdict and is named first; the stale leg is still named.
        os.rename(w["picker"], w["picker"] + ".away")
        rc, last, out = run(w)
        check("pool picker missing too: exit 2 NOT INSTALLED naming the pool picker, and the "
              "stale pool file after it",
              rc == 2 and last.startswith("NOT INSTALLED") and "pool picker" in last
              and "accounts.pool_file" in last and last.index("pool picker") < last.index("accounts.pool_file"),
              f"rc={rc} last={last!r}")
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
