#!/usr/bin/env python3
"""Regression guard for stall-watchdog/installation/check under launchd (macOS):
the LaunchDaemon form reads OK, the LaunchAgent form reads UNPROTECTED, and every
state in between names its own leg.

HOW IT RUNS. The real check, as a subprocess, with FLEET_SERVICE_BACKEND=launchd
and the fleet's fake launchctl (tests/fixtures/launchd/fake-launchctl, through
FLEET_LAUNCHCTL), so it runs the same on Linux and macOS and never reaches a real
launchd. The job is agent-stall-watchdog.plist.example with every placeholder
filled; the system domain's directory is a temp one
(FLEET_LAUNCHD_SYSTEM_DIR, fleetlib's seam) and HOME is a temp one, so neither
/Library/LaunchDaemons nor a real ~/Library/LaunchAgents is read. The job's pid is
a real `sleep` this test starts, so the check reads a real start time through
fleetlib.services. The install context is a temp copy of the fixture manifest with
an install record for this config, so the version leg can pass too.

THE CONTROL. The protected form with every leg made to pass must exit 0 with OK:
it is the positive evidence that every leg was reached and can pass. If it does
not, no case below can say which leg its verdict is about: NO VERDICT (exit 3).

THE BLIND CASES ARE WRITTEN BY THE REAL watchdog.py, never by this file: `--once`
with this config and a PATH that holds no tmux (the job a PATH without tmux
renders), and with tmux's own directory as PATH against a socket directory with no
server. Each writes the state file as the daemon does, and the check must print
the cause the daemon recorded - the PATH for the first, the TMUX_TMPDIR hint only
for the second, where it is right. A state file hand-written here would pin a shape
the daemon may no longer write; the pair is the contract between the two files.
The second needs a tmux binary; without one the run is NO VERDICT.

Run: python3 .claude/skills/stall-watchdog/installation/check.test.py
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
import time

HERE = os.path.dirname(os.path.realpath(__file__))
SKILL = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(os.path.dirname(SKILL)))
CHECK = os.path.join(HERE, "check")
EXAMPLE = os.path.join(HERE, "agent-stall-watchdog.plist.example")
FAKE = os.path.join(REPO, "tests", "fixtures", "launchd", "fake-launchctl")
MANIFEST = os.path.join(REPO, "tests", "fixtures", "install", ".claude", "fleet.json")
LABEL = "com.agent-fleet-test.stall-watchdog.ada"

_failures = []


def check(name, cond, detail=""):
    print(("[PASS] " if cond else "[FAIL] ") + name + (" - " + detail if detail and not cond else ""))
    if not cond:
        _failures.append(name)


def declared_version():
    with open(os.path.join(SKILL, "SKILL.md"), encoding="utf-8") as f:
        m = re.search(r"^version:\s*(\d+)\s*$", f.read(4096), re.M)
    return int(m.group(1))


class Rig:
    def __init__(self, tmp):
        self.tmp = tmp
        self.state_dir = os.path.join(tmp, "state")
        os.makedirs(self.state_dir, mode=0o700)
        self.tmux_dir = os.path.join(tmp, "run", "claude-tmux-ada")
        os.makedirs(self.tmux_dir)
        with open(os.path.join(SKILL, "config.example.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        cfg["tmux"]["tmpdir"] = self.tmux_dir
        cfg["state"]["dir"] = self.state_dir
        cfg["owner"]["claude_config_dir"] = None
        # Two polls fit inside the second the rig waits after starting the job, so
        # "too early to tell" never answers for a case that needs a verdict.
        cfg["stall"]["poll_secs"] = 0.5
        self.config = os.path.join(tmp, "stall-watchdog.json")
        with open(self.config, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        self.state_file = os.path.join(self.state_dir, cfg["state"]["prefix"] + ".json")
        self.system_dir = os.path.join(tmp, "LaunchDaemons")
        self.home = os.path.join(tmp, "home")
        self.user_dir = os.path.join(self.home, "Library", "LaunchAgents")
        os.makedirs(self.system_dir)
        os.makedirs(self.user_dir)
        install = os.path.join(tmp, "install")
        os.makedirs(os.path.join(install, ".claude", "skills", "stall-watchdog", "installation"))
        shutil.copy(MANIFEST, os.path.join(install, ".claude", "fleet.json"))
        with open(os.path.join(install, ".claude", "skills", "stall-watchdog", "installation",
                               ".install-state.json"), "w", encoding="utf-8") as f:
            json.dump({"hosts": {socket.gethostname(): {self.config: {"version": declared_version()}}}}, f)
        self.sleeper = subprocess.Popen(["sleep", "600"], stdin=subprocess.DEVNULL)
        self.lstate = os.path.join(tmp, "launchd.json")
        self.env = dict(os.environ, FLEET_SERVICE_BACKEND="launchd", FLEET_LAUNCHCTL=FAKE,
                        FAKE_LAUNCHD_STATE=self.lstate, FAKE_LAUNCHD_CALLS=os.path.join(tmp, "calls"),
                        HOME=self.home, FLEET_LAUNCHD_SYSTEM_DIR=self.system_dir,
                        FLEET_CONTEXT_ROOT=install, FLEET_HOST_CONFIG=os.path.join(tmp, "no-host.json"),
                        PYTHONDONTWRITEBYTECODE="1")
        self.env.pop("STALL_WATCHDOG_CONFIG", None)

    def plist(self, where):
        with open(EXAMPLE, encoding="utf-8") as f:
            text = f.read()
        values = {"<launchd-prefix>": "com.agent-fleet-test", "<agent>": "ada", "<user>": "ada",
                  "<checkout>": self.tmp, "<fleet>": REPO, "<agents-root>": self.tmp,
                  "<state dir>": self.state_dir, "<tmux-dir>": self.tmux_dir,
                  "<python>": sys.executable, "<path>": "/usr/bin:/bin:/usr/sbin:/sbin"}
        for k, v in values.items():
            text = text.replace(k, v)
        text = text.replace(f"{self.tmp}/ada/config/stall-watchdog.json", self.config)
        path = os.path.join(where, LABEL + ".plist")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def reset(self):
        for d in (self.system_dir, self.user_dir):
            for f in os.listdir(d):
                os.remove(os.path.join(d, f))
        if os.path.exists(self.lstate):
            os.remove(self.lstate)

    def load(self, path, domain, pid):
        with open(self.lstate, "w") as f:
            json.dump({"next_pid": pid}, f)
        r = subprocess.run([FAKE, "bootstrap", domain, path], env=self.env, capture_output=True, text=True)
        return r.returncode == 0

    def job(self, domain, **fields):
        with open(self.lstate) as f:
            st = json.load(f)
        st["loaded"][domain][LABEL].update(fields)
        with open(self.lstate, "w") as f:
            json.dump(st, f)

    def fresh_state(self, age=0.0):
        with open(self.state_file, "w") as f:
            f.write("{}\n")
        t = time.time() - age
        os.utime(self.state_file, (t, t))

    def run(self):
        p = subprocess.run([sys.executable, CHECK, self.config], env=self.env, capture_output=True,
                           text=True, stdin=subprocess.DEVNULL, timeout=60)
        lines = [ln for ln in p.stdout.splitlines() if ln.strip()]
        return p.returncode, (lines[-1] if lines else ""), p.stdout + p.stderr

    def once(self, path_var):
        """The real watchdog.py --once with this config and PATH=path_var: one poll, its
        state file written (or not) exactly as the daemon writes it."""
        if os.path.exists(self.state_file):
            os.remove(self.state_file)
        env = dict(self.env, STALL_WATCHDOG_CONFIG=self.config, PATH=path_var)
        env.pop("TMUX", None)
        return subprocess.run([sys.executable, os.path.join(SKILL, "watchdog.py"), "--once"], env=env,
                              capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)


def main():
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="wdc.", dir="/tmp"))
    rig = None
    try:
        rig = Rig(tmp)
        user_domain = f"gui/{os.getuid()}"
        time.sleep(1.1)                 # the state file below is written AFTER the job started

        # THE CONTROL: the protected form, every leg passing.
        sys_plist = rig.plist(rig.system_dir)
        loaded = rig.load(sys_plist, "system", rig.sleeper.pid)
        rig.fresh_state()
        rc, last, out = rig.run()
        if not (loaded and rc == 0 and last.startswith("OK:")):
            print(out)
            print(f"NO VERDICT: the control did not exit 0 (loaded={loaded}, exit {rc}, last line "
                  f"{last!r}); no case below could say which leg its verdict is about")
            return 3
        print("[PASS] control: a LaunchDaemon job, running and capturing, recorded, exits 0 with OK")
        check("the OK names the launchd label it found by the config's path", LABEL in last, last)

        rig.fresh_state(age=3600)
        rc, last, _ = rig.run()
        check("a state file older than the job's process start: exit 1, up and BLIND",
              rc == 1 and "predates this run" in last, f"rc={rc} last={last!r}")

        # A state file the daemon cannot read: the remedy restarts the job by bootout
        # and bootstrap of its plist, never `kickstart -k` (which reuses the loaded
        # definition).
        os.remove(rig.state_file)
        os.mkdir(rig.state_file)
        rc, last, _ = rig.run()
        os.rmdir(rig.state_file)
        check("an unreadable state file: exit 1, its restart remedy is bootout then bootstrap, no kickstart",
              rc == 1 and "sudo launchctl bootout system/<that label>" in last
              and f"sudo launchctl bootstrap system {rig.system_dir}/<that label>.plist" in last
              and "kickstart" not in last, f"rc={rc} last={last!r}")

        rig.fresh_state()
        rig.job("system", state="not running", pid=0, last_exit=1)
        rc, last, _ = rig.run()
        check("a loaded job that is not running: exit 1 STALE, naming its log",
              rc == 1 and last.startswith("STALE:") and "loaded in system" in last
              and "tail -n 30 " + os.path.join(rig.state_dir, "watchdog.log") in last,
              f"rc={rc} last={last!r}")

        rig.reset()
        rig.plist(rig.system_dir)
        rc, last, _ = rig.run()
        check("a plist that names this config but is not loaded: exit 2, naming the sudo bootstrap",
              rc == 2 and f"sudo launchctl bootstrap system {sys_plist}" in last, f"rc={rc} last={last!r}")

        rig.reset()
        rig.load(rig.plist(rig.system_dir), "system", 999999)
        rig.job("system", pid=2 ** 22 + 12345)
        rc, last, _ = rig.run()
        check("a running job whose process start cannot be read: exit 1 NO VERDICT, never a skipped leg",
              rc == 1 and last.startswith("NO VERDICT:") and "cannot be read" in last, f"rc={rc} last={last!r}")

        rig.reset()
        user_plist = rig.plist(rig.user_dir)
        rig.load(user_plist, user_domain, rig.sleeper.pid)
        rig.fresh_state()
        rc, last, _ = rig.run()
        check("the SAME job as a LaunchAgent, running and capturing: exit 1 UNPROTECTED, naming the "
              "LaunchDaemon install", rc == 1 and last.startswith("UNPROTECTED:")
              and f"{rig.system_dir}/{LABEL}.plist" in last, f"rc={rc} last={last!r}")

        rig.reset()
        rc, last, _ = rig.run()
        check("no plist names this config: exit 2, naming the plist example",
              rc == 2 and "no launchd job names STALL_WATCHDOG_CONFIG" in last
              and "agent-stall-watchdog.plist.example" in last, f"rc={rc} last={last!r}")

        # BLIND, recorded by the real watchdog.py (see the header).
        tmux = shutil.which("tmux")
        if not tmux:
            print("NO VERDICT: no tmux on PATH, so the blind case of a tmux that RAN cannot be written")
            return 3
        rig.reset()
        rig.load(rig.plist(rig.system_dir), "system", rig.sleeper.pid)
        no_tmux = os.path.join(tmp, "no-tmux-bin")
        os.makedirs(no_tmux)
        p = rig.once(no_tmux)
        rc, last, _ = rig.run()
        check("a watchdog whose PATH reaches no tmux: exit 1 BLIND naming tmux, that PATH and the "
              "re-render, never the TMUX_TMPDIR hint",
              rc == 1 and "BLIND" in last and "cannot start tmux" in last and f"on PATH={no_tmux})" in last
              and "render-plist.py" in last and "TMUX_TMPDIR" not in last,
              f"rc={rc} last={last!r} watchdog stderr={p.stderr.strip()!r}")
        p = rig.once(os.path.dirname(tmux))
        rc, last, _ = rig.run()
        check("a watchdog whose tmux RAN and found no server: exit 1 BLIND with tmux's own words, "
              "naming both causes (a session that is down, or the TMUX_TMPDIR hint)",
              rc == 1 and "BLIND" in last and "last tmux call failed" in last and rig.tmux_dir in last
              and "the session is not running" in last and "the job's TMUX_TMPDIR does not match" in last
              and "render-plist" not in last,
              f"rc={rc} last={last!r} watchdog stderr={p.stderr.strip()!r}")

        # A job that has run longer than two polls (the rig's poll is 0.5 s; its pid
        # started over a second ago) and never wrote its state has not completed one
        # poll: the line sends the reader to its log, never to a guessed tmux cause.
        rig.reset()
        if os.path.exists(rig.state_file):
            os.remove(rig.state_file)
        rig.load(rig.plist(rig.system_dir), "system", rig.sleeper.pid)
        rc, last, _ = rig.run()
        check("a job that ran past two polls and never wrote its state: exit 1 BLIND, naming its log, "
              "no tmux guess",
              rc == 1 and "has not completed one poll" in last
              and "tail -n 30 " + os.path.join(rig.state_dir, "watchdog.log") in last
              and "TMUX_TMPDIR" not in last, f"rc={rc} last={last!r}")
    finally:
        if rig is not None:
            rig.sleeper.kill()
            rig.sleeper.wait()
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    if _failures:
        print("FAILED: %d check(s): %s" % (len(_failures), "; ".join(_failures)))
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
