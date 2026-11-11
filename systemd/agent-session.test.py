#!/usr/bin/env python3
"""agent-session.test.py - the macOS session supervisor against a real tmux and a
fake claude, and the fleet's plist examples against the parser.

Usage: python3 systemd/agent-session.test.py

HOW IT RUNS. Every case runs systemd/agent-session.py as launchd would: a child
process with TMUX_TMPDIR, PATH and the job's variables in its environment, on a
private tmux socket under a short /tmp directory (macOS limits a socket path to 104
bytes). `claude` is a stand-in that the session's login shell finds through the env
file the supervisor makes it source: it logs its start (with the credential and the
CLAUDE_CONFIG_DIR it was given), draws the ready status bar unless told not to, and
logs every line typed into it. Nothing outside the temp directory is read or
written. Runs the same on Linux and macOS; it needs tmux on PATH.

WHAT EACH CASE HOLDS (the supervisor's LOAD-BEARING PROPERTIES, plus the plists):
  fresh      a new session starts, sources the env file, waits for the ready bar
             and types the boot message ONCE; the socket directory is mode 0700;
             the job's PATH is first in the session although the login profile
             (standing in for macOS's path_helper) put /usr/bin in front
  adopt      after the supervisor is killed with SIGKILL the session survives (the
             CONTROL that makes the case mean anything), and a second supervisor
             adopts it: no second start, no second boot message
  ended      killing the session makes the supervisor exit 1 (launchd's cue)
  sigterm    SIGTERM kills the session and exits 0
  stale      a tmux server already on the socket with no agent session, started
             with another CLAUDE_CONFIG_DIR, is killed first: claude gets the job's
  not-ready  no ready bar within --ready-secs: BOOT MESSAGE NOT SENT, nothing typed,
             the session kept
  config     no env file: exit 1 naming it
  plists     every *.plist.example the fleet ships (templates/ and each skill's
             installation/, discovered, so a new one is covered with no edit here),
             every placeholder filled with a synthetic value, parses (plistlib;
             `plutil -lint` too on macOS), and an unfilled one does NOT (a missed
             placeholder cannot load); a placeholder with no test value fails. The
             session plist's label is fleetlib.services' label for the session, its
             arguments parse with agent-session.py's own parser, its socket path
             fits in 104 bytes, and its interpreter (the job's and the boot
             message's) and PATH are the rendered <python> and <path>, never
             Homebrew's; the stall watchdog's is services' watchdog label, a
             LaunchDaemon running as the session's user; the web hierarchy
             server's is a LaunchAgent running serve.mjs through a login shell
  boot       the boot message of templates/claude-agent.service.example and of
             templates/claude-agent.plist.example claims nothing that is false on
             an agent's FIRST start (no "just restarted", no "previous
             conversation was resumed", no "re-read"): the same text is typed on
             every start, a brand-new agent's included, and an agent told it was
             resumed looks for a conversation it never had. The two templates are
             two copies of one opening, so their text up to "Your scheduler" must
             be the same; a boot message the pattern cannot find in either file
             is a failure, never a pass

Exit codes: 0 every case passed; 1 a case failed; 3 NO VERDICT (no tmux).
"""
import importlib.util
import json
import os
import plistlib
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(os.path.realpath(__file__)).parents[1]
SUPERVISOR = REPO / "systemd" / "agent-session.py"
PLISTS = {p.name.removesuffix(".plist.example"): p
          for p in sorted([*REPO.glob("templates/*.plist.example"),
                           *REPO.glob(".claude/skills/*/installation/*.plist.example")])}
PLIST_TAGS = {"plist", "dict", "key", "string", "array", "integer", "real", "true", "false",
              "date", "data"}
VALUES = {
    "agent-name": "ada", "Agent-Name": "Ada", "agents-root": "/tmp/fleet-fixture/agents",
    "fleet": "/tmp/fleet-fixture/agents/fleet", "project-dir": "work",
    "watch-job": "slack-watch", "watch-config-env": "SLACK_WATCH_CONFIG", "auth-mode": "token",
    "launchd-prefix": "com.agent-fleet-test", "uid": "501",
    "agent": "ada", "user": "ada", "checkout": "/tmp/fleet-fixture/agents/ada/work",
    "state dir": "/tmp/fleet-fixture/agents/ada/state/stall-watchdog",
    "tmux-dir": "/tmp/fleet-fixture/agents/run/claude-tmux-ada",
    "install-checkout": "/tmp/fleet-fixture/agents/ada/work", "n": "1", "port": "8091",
    "python": "/tmp/fleet-fixture/bin/python3", "path": "/tmp/fleet-fixture/bin:/usr/bin:/bin:/usr/sbin:/sbin",
}
BOOT = "You are Ada, just restarted & briefed: arm <both> followers."
SERVICE = REPO / "templates" / "claude-agent.service.example"
# Claims the boot message must not make: each is false the first time an agent starts.
FIRST_START_FALSE = ("just restarted", "previous conversation was resumed", "re-read")
FAKE_CLAUDE = r"""#!/bin/bash
log="$FAKE_CLAUDE_LOG"
case " $* " in *" --update "*) echo "update" >> "$log"; exit 0 ;; esac
echo "start token=${FAKE_TOKEN:-unset} config=${CLAUDE_CONFIG_DIR:-unset} nobytecode=${PYTHONDONTWRITEBYTECODE:-unset}" >> "$log"
echo "path1 ${PATH%%:*}" >> "$log"
if [ "${FAKE_NO_READY:-}" != 1 ]; then sleep 1; echo "  >> bypass permissions on (shift+tab to cycle)"; fi
while IFS= read -r line; do echo "typed: $line" >> "$log"; done
"""

_failures = []


def check(name, cond, detail=""):
    print(("[PASS] " if cond else "[FAIL] ") + name + (f" - {detail}" if detail and not cond else ""))
    if not cond:
        _failures.append(name)


def wait_for(pred, secs, step=0.2):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(step)
    return pred()


class Rig:
    def __init__(self, tmp, tmux):
        self.tmp, self.tmux = tmp, tmux
        self.bin = os.path.join(tmp, "bin")
        os.makedirs(self.bin)
        with open(os.path.join(self.bin, "claude"), "w") as f:
            f.write(FAKE_CLAUDE)
        os.chmod(os.path.join(self.bin, "claude"), 0o755)
        self.tmpdir = os.path.join(tmp, "run", "claude-tmux-ada")
        self.log = os.path.join(tmp, "claude.log")
        self.work = os.path.join(tmp, "work")
        os.makedirs(self.work)
        self.procs = []
        # The login profile of the session's `bash -l`: what macOS's path_helper does,
        # the system directories put in front of the PATH the job passed in.
        with open(os.path.join(tmp, ".bash_profile"), "w") as f:
            f.write('PATH="/usr/bin:/bin:$PATH"\n')

    def env_file(self, name, **extra):
        path = os.path.join(self.tmp, name)
        lines = {"FAKE_TOKEN": "tok-1", "FAKE_CLAUDE_LOG": self.log, **extra}
        with open(path, "w") as f:
            f.write("# fleet-account: ada@example.com\n")
            f.writelines(f"{k}={v}\n" for k, v in lines.items())
        return path

    def env(self, **extra):
        # PYTHONDONTWRITEBYTECODE is dropped: the supervisor must set it itself, and an
        # inherited one would pass the check that it does with the line deleted.
        e = {k: v for k, v in os.environ.items() if k not in ("TMUX", "PYTHONDONTWRITEBYTECODE")}
        e.update(HOME=self.tmp, TMUX_TMPDIR=self.tmpdir, CLAUDE_CONFIG_DIR="/tmp/fleet-fixture/ada/.claude",
                 PATH=f"{self.bin}:{os.path.dirname(self.tmux)}:{os.environ.get('PATH', '')}")
        e.update(extra)
        return e

    def start(self, env_file, *args, **env):
        out = open(os.path.join(self.tmp, f"session-{len(self.procs)}.log"), "w")
        p = subprocess.Popen([sys.executable, str(SUPERVISOR), "--agent", "ada", "--env-file", env_file,
                              "--boot", BOOT, "--pre-sleep", "0", "--ready-secs", "15",
                              "--interval", "0.3", *args],
                             cwd=self.work, env=self.env(**env), stdout=out, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL)
        p.out = out.name
        self.procs.append(p)
        return p

    def tm(self, *args, **env):
        return subprocess.run([self.tmux, *args], env=self.env(**env), capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=30)

    def alive(self):
        return self.tm("has-session", "-t", "=claude-ada").returncode == 0

    def lines(self, prefix):
        try:
            return [ln for ln in open(self.log).read().splitlines() if ln.startswith(prefix)]
        except OSError:
            return []

    def reset(self):
        self.tm("kill-server")
        wait_for(lambda: not self.alive(), 10)
        if os.path.exists(self.log):
            os.remove(self.log)

    def close(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
                p.wait()
        self.tm("kill-server")


def read(path):
    try:
        return open(path).read()
    except OSError:
        return ""


def live_cases(rig):
    ef = rig.env_file("claude-auth.env")

    # fresh
    p = rig.start(ef)
    typed = lambda: [ln for ln in rig.lines("typed: ") if ln == f"typed: {BOOT}"]
    check("fresh: the boot message is typed once the ready bar is drawn",
          wait_for(lambda: typed(), 30), read(p.out) + read(rig.log))
    check("fresh: claude got the env file's credential, the job's CLAUDE_CONFIG_DIR and "
          "PYTHONDONTWRITEBYTECODE=1 (set by the supervisor: the rig does not pass it)",
          rig.lines("start ") == ["start token=tok-1 config=/tmp/fleet-fixture/ada/.claude nobytecode=1"],
          repr(rig.lines("start ")))
    check("fresh: the socket directory is mode 0700",
          os.path.isdir(rig.tmpdir) and (os.stat(rig.tmpdir).st_mode & 0o777) == 0o700)
    check("fresh: claude --update ran before the session", rig.lines("update") == ["update"])
    check("fresh: the job's PATH is first in the session, ahead of the login profile's /usr/bin",
          rig.lines("path1 ") == [f"path1 {rig.bin}"], repr(rig.lines("path1 ")))

    # adopt
    p.kill()
    p.wait()
    check("adopt CONTROL: the session survives its supervisor's SIGKILL", rig.alive())
    p2 = rig.start(ef)
    wait_for(lambda: "adopted" in read(p2.out), 15)
    time.sleep(2)
    check("adopt: a second supervisor adopts the session and says so",
          "adopted the running session claude-ada" in read(p2.out) and p2.poll() is None, read(p2.out))
    check("adopt: no second start and no second boot message",
          len(rig.lines("start ")) == 1 and len(typed()) == 1,
          f"starts={rig.lines('start ')} boots={len(typed())}")

    # ended
    rig.tm("kill-session", "-t", "=claude-ada")
    check("ended: the supervisor exits 1 when the session ends",
          wait_for(lambda: p2.poll() is not None, 15) and p2.returncode == 1,
          f"rc={p2.poll()} {read(p2.out)}")

    # sigterm
    rig.reset()
    p3 = rig.start(ef)
    wait_for(lambda: typed(), 30)
    check("sigterm CONTROL: the session runs before the signal", rig.alive())
    p3.send_signal(signal.SIGTERM)
    check("sigterm: the supervisor exits 0", wait_for(lambda: p3.poll() is not None, 15)
          and p3.returncode == 0, f"rc={p3.poll()} {read(p3.out)}")
    check("sigterm: the session is gone", wait_for(lambda: not rig.alive(), 10))

    # stale
    rig.reset()
    keep = rig.tm("new-session", "-d", "-s", "keeper", "sleep 300", CLAUDE_CONFIG_DIR="/tmp/stale/.claude")
    check("stale CONTROL: a server runs on the socket with no claude-ada session",
          keep.returncode == 0 and not rig.alive(), keep.stderr)
    p4 = rig.start(ef)
    wait_for(lambda: rig.lines("start "), 30)
    check("stale: the stale server is killed, so claude gets the job's CLAUDE_CONFIG_DIR",
          rig.lines("start ") == ["start token=tok-1 config=/tmp/fleet-fixture/ada/.claude nobytecode=1"]
          and "killing it" in read(p4.out), f"{rig.lines('start ')} {read(p4.out)}")
    p4.send_signal(signal.SIGTERM)
    p4.wait(timeout=15)

    # not-ready
    rig.reset()
    p5 = rig.start(rig.env_file("no-ready.env", FAKE_NO_READY="1"), "--ready-secs", "2")
    check("not-ready: BOOT MESSAGE NOT SENT is logged after --ready-secs",
          wait_for(lambda: "BOOT MESSAGE NOT SENT" in read(p5.out), 20), read(p5.out))
    check("not-ready: nothing was typed, and the session and supervisor are kept",
          not rig.lines("typed: ") and rig.alive() and p5.poll() is None)
    p5.send_signal(signal.SIGTERM)
    p5.wait(timeout=15)

    # config
    rig.reset()
    p6 = rig.start(os.path.join(rig.tmp, "absent.env"))
    check("config: no env file is exit 1, naming the file",
          wait_for(lambda: p6.poll() is not None, 15) and p6.returncode == 1
          and "no env file at " + os.path.join(rig.tmp, "absent.env") in read(p6.out),
          f"rc={p6.poll()} {read(p6.out)}")


def fill(text):
    for k, v in VALUES.items():
        text = text.replace(f"<{k}>", v)
    return text


def leftover(text):
    """Placeholders left: <name> tokens that are not plist tags, outside comments."""
    body = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    return sorted({t for t in re.findall(r"<([A-Za-z][A-Za-z0-9 -]*)>", body) if t not in PLIST_TAGS})


def services_label(kind="session"):
    """fleetlib.services' launchd label of ada's `kind` unit, under the test prefix."""
    tmp = tempfile.mkdtemp(prefix="fas-host.")
    try:
        host = os.path.join(tmp, "host.json")
        with open(host, "w") as f:
            json.dump({"schema": 1, "agents_root": VALUES["agents-root"], "fleet_checkout": VALUES["fleet"],
                       "claims_dir": "/tmp/fleet-fixture/claims",
                       "launchd_prefix": VALUES["launchd-prefix"]}, f)
        code = ("import sys; sys.path.insert(0, sys.argv[1]); from fleetlib import services; "
                "print(services.unit(sys.argv[2], 'ada'))")
        r = subprocess.run([sys.executable, "-c", code, str(REPO / "lib"), kind], capture_output=True, text=True,
                           env={**os.environ, "FLEET_SERVICE_BACKEND": "launchd", "FLEET_HOST_CONFIG": host})
        return r.stdout.strip()
    finally:
        shutil.rmtree(tmp)


def plist_cases():
    spec = importlib.util.spec_from_file_location("agent_session", SUPERVISOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for name, path in PLISTS.items():
        raw = path.read_text(encoding="utf-8")
        comments = re.findall(r"<!--(.*?)-->", raw, flags=re.S)
        check(f"{name} plist: no double hyphen inside a comment (XML ends the comment there)",
              not any("--" in c for c in comments))
        try:
            plistlib.loads(raw.encode())
            unfilled_loads = True
        except Exception:  # noqa: BLE001 - expat, InvalidFileException or ValueError
            unfilled_loads = False
        check(f"{name} plist: the UNFILLED template does not parse (a missed placeholder cannot load)",
              not unfilled_loads)
        filled = fill(raw)
        check(f"{name} plist: every placeholder has a test value", not leftover(filled), repr(leftover(filled)))
        try:
            d = plistlib.loads(filled.encode())
        except Exception as exc:  # noqa: BLE001
            check(f"{name} plist: the filled template parses", False, f"{type(exc).__name__}: {exc}")
            continue
        check(f"{name} plist: the filled template parses", True)
        if sys.platform == "darwin":
            out = os.path.join(tempfile.mkdtemp(prefix="fas-lint."), f"{name}.plist")
            with open(out, "w") as f:
                f.write(filled)
            r = subprocess.run(["plutil", "-lint", out], capture_output=True, text=True)
            check(f"{name} plist: plutil -lint accepts it", r.returncode == 0, r.stdout + r.stderr)
            shutil.rmtree(os.path.dirname(out))
        yield name, d, mod


def session_plist(d, mod):
    check("session plist: the label is fleetlib.services' session label",
          d["Label"] == services_label() == "com.agent-fleet-test.session.ada",
          f"{d['Label']!r} vs {services_label()!r}")
    argv = d["ProgramArguments"]
    check("session plist: it runs systemd/agent-session.py", argv[1].endswith("/systemd/agent-session.py"))
    try:
        a = mod.parser().parse_args(argv[2:])
        ok = a.agent == "ada" and a.env_file.endswith("/ada/secrets/personal/claude-auth.env") and a.boot
    except SystemExit:
        ok = False
    check("session plist: its arguments parse with agent-session.py's own parser", ok, repr(argv[2:]))
    boot = argv[argv.index("--boot") + 1]
    check("session plist: the boot message decodes its XML escapes", "2>&1" in boot and "&amp;" not in boot)
    env = d["EnvironmentVariables"]
    sock = f"{env['TMUX_TMPDIR']}/tmux-{VALUES['uid']}/default"
    check("session plist: the socket is <agents-root>/run/claude-tmux-<agent>, under 104 bytes",
          env["TMUX_TMPDIR"] == "/tmp/fleet-fixture/agents/run/claude-tmux-ada" and len(sock.encode()) < 104)
    check("session plist: the credential is not in the job's environment",
          not any("TOKEN" in k or "KEY" in k for k in env))
    check("session plist: KeepAlive relaunches every exit but 0",
          d["KeepAlive"] == {"SuccessfulExit": False} and d["RunAtLoad"] is True)
    check("session plist: its interpreter and the boot message's three follower commands are <python> and its "
          "PATH is <path>, all rendered (installation/render-plist.py --job session), never a hardcoded "
          "Homebrew directory",
          argv[0] == VALUES["python"] and boot.count(VALUES["python"] + " ") == 3 and env["PATH"] == VALUES["path"]
          and "/opt/homebrew" not in PLISTS["claude-agent"].read_text(encoding="utf-8"), repr(argv[:1]) + env["PATH"])
    check("session plist: no Python the session runs writes bytecode", env.get("PYTHONDONTWRITEBYTECODE") == "1")


def watchdog_plist(d):
    check("stall-watchdog plist: the label is fleetlib.services' watchdog label",
          d["Label"] == services_label("watchdog") == "com.agent-fleet-test.stall-watchdog.ada",
          f"{d['Label']!r} vs {services_label('watchdog')!r}")
    env = d["EnvironmentVariables"]
    check("stall-watchdog plist: a LaunchDaemon that runs watchdog.py as the session's user, "
          "with the config and the socket directory in its environment",
          d.get("UserName") == "ada" and d["ProgramArguments"][1].endswith("/stall-watchdog/watchdog.py")
          and env.get("STALL_WATCHDOG_CONFIG", "").endswith("/ada/config/stall-watchdog.json")
          and env.get("TMUX_TMPDIR") == VALUES["tmux-dir"] and "CLAUDE_CONFIG_DIR" not in env, repr(d))
    check("stall-watchdog plist: KeepAlive restarts every exit (the 75 of a failed re-exec included)",
          d["KeepAlive"] is True and d["RunAtLoad"] is True)
    check("stall-watchdog plist: its interpreter is <python> and its PATH is <path>, both rendered "
          "(installation/render-plist.py), never a hardcoded Homebrew directory",
          d["ProgramArguments"][0] == VALUES["python"] and env.get("PATH") == VALUES["path"], repr(d))


def web_hierarchy_plist(d):
    argv = d["ProgramArguments"]
    check("web-hierarchy-server plist: a LaunchAgent (no UserName) running serve.mjs on its port "
          "through a login shell, for one agent's config dir",
          d["Label"] == "com.agent-fleet-test.web-hierarchy.1" and "UserName" not in d
          and argv[:2] == ["/bin/bash", "-lc"] and argv[2].endswith("/serve.mjs --port=8091")
          and d["EnvironmentVariables"]["CLAUDE_CONFIG_DIR"] == "/tmp/fleet-fixture/agents/ada/.claude"
          and d["KeepAlive"] is True, repr(d))


def boot_texts():
    """The boot message of each session template, as written (placeholders kept)."""
    import html
    svc = re.search(r'tmux send-keys -t \$S "([^"]*)"; sleep 1', SERVICE.read_text(encoding="utf-8"))
    pl = re.search(r"<string>--boot</string>\s*<string>(.*?)</string>",
                   PLISTS["claude-agent"].read_text(encoding="utf-8"), flags=re.S)
    return {"service": svc and svc.group(1), "plist": pl and html.unescape(pl.group(1))}


def boot_cases():
    texts = boot_texts()
    for name, text in texts.items():
        check(f"boot: the {name} template's boot message is found", bool(text))
        bad = [c for c in FIRST_START_FALSE if text and c in text.lower()]
        check(f"boot: the {name} template's boot message is true on a first start", not bad, repr(bad))
    heads = {n: t.split(" Your scheduler")[0] for n, t in texts.items() if t and " Your scheduler" in t}
    check("boot: both templates open with the same text, up to \"Your scheduler\"",
          len(heads) == 2 and heads["service"] == heads["plist"], repr(heads))


def main():
    boot_cases()
    seen = []
    for name, d, mod in plist_cases():
        seen.append(name)
        if name == "claude-agent":
            session_plist(d, mod)
        elif name == "agent-stall-watchdog":
            watchdog_plist(d)
        elif name == "web-hierarchy-server":
            web_hierarchy_plist(d)
    check("plists CONTROL: discovery found the session and the stall-watchdog examples",
          {"claude-agent", "agent-stall-watchdog"} <= set(seen), repr(seen))
    tmux = shutil.which("tmux")
    if not tmux:
        print("NO VERDICT: tmux is not on PATH, so the supervisor cannot be run")
        return 3
    tmp = tempfile.mkdtemp(prefix="fas.", dir="/tmp")
    rig = Rig(tmp, tmux)
    try:
        live_cases(rig)
    finally:
        rig.close()
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    if _failures:
        print(f"FAILED: {len(_failures)} check(s): " + "; ".join(_failures))
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
