#!/usr/bin/env python3
"""agent-session.py - one agent's Claude Code session, supervised in the foreground.

The macOS form of templates/claude-agent.service.example. launchd has no forking
service type, no ExecStartPre or ExecStartPost, no RuntimeDirectory and no
EnvironmentFile, so the agent's LaunchAgent (templates/claude-agent.plist.example)
runs THIS process, which stays in the foreground for the life of the session and
does what each line of the systemd unit does:

  systemd unit                          here
  RuntimeDirectory=claude-tmux-<agent>  creates $TMUX_TMPDIR, mode 0700
  ExecStartPre=/bin/sleep 60            --pre-sleep before a NEW session (default 60)
  EnvironmentFile=<auth file>           --env-file, required; the session's login shell
                                        sources it, so the credential reaches claude and
                                        never this process's argv or the job definition
  ExecStart=tmux new-session -d ...     the same command: `bash -lc` for the login
                                        PATH, `claude --update`, then --continue or fresh;
                                        the job's PATH is put back IN FRONT of the login
                                        PATH (see the properties)
  ExecStartPost (readiness, boot)       polls the pane for the ready status bar, then
                                        types --boot once; never ready in --ready-secs:
                                        the BOOT MESSAGE NOT SENT line, session kept
  Restart=always                        exits 1 when the session ends; the plist's
                                        KeepAlive relaunches this process
  ExecStop=tmux kill-session            SIGTERM (launchctl bootout) kills the session
                                        and exits 0

Usage:
  agent-session.py --agent <name> --env-file <file> --boot <message>
                   [--pre-sleep S] [--ready-secs S] [--interval S]

Environment: PYTHONDONTWRITEBYTECODE is 1 for the session whatever the job set, so
no Python it runs writes a __pycache__ into the fleet checkout, which is the
administrator's and read-only to the agents. TMUX_TMPDIR (required, absolute) is the
session's socket directory,
<agents_root>/run/claude-tmux-<agent> by the fleet's convention; it comes from the
plist's EnvironmentVariables, where bin/claude-attach, the stall watchdog and
agent-revive read the same value. PATH must reach tmux; the session's login shell
puts it in front of its own PATH, where `claude` is found. The plist's PATH is
rendered from where tmux, claude and the interpreter are, then /opt/homebrew/bin,
/usr/local/bin and the system directories, which every command the agent runs
inherits (stall-watchdog's installation/render-plist.py --job session).

Output: one timestamped line per event on stdout, which the plist points at
<home>/state/session.log.

Exit codes: 0 stopped by SIGTERM/SIGINT/SIGHUP (the session is killed first); 1 the
session ended, or it could not be started, or the arguments or environment are
unusable (launchd relaunches; see CONFIG ERRORS); 2 usage.

LOAD-BEARING PROPERTIES - each is here because removing it opens a hole, and
agent-session.test.py holds each one with a case that fails without it:

  * AN EXISTING SESSION IS ADOPTED, NEVER RE-BRIEFED. The tmux server daemonizes, so
    it outlives this process: launchd relaunching a killed or crashed supervisor
    finds the session still running. Re-typing the boot message there lands it in
    the middle of whatever the agent is doing; starting a second session is not
    possible (same name) and killing the first drops the agent's in-flight work. So
    an existing `claude-<agent>` session is watched as it is, with no pre-sleep.

  * THE SUPERVISOR EXITS WHEN THE SESSION ENDS. That exit is the only signal launchd
    has: a supervisor that kept running over a dead session would leave the agent
    down with its job reported as running, and nothing would restart it.

  * SIGTERM KILLS THE SESSION. `launchctl bootout` (stopping or uninstalling the
    agent, a restart through fleetlib.services) sends SIGTERM; without the kill the
    daemonized session would survive its own job, and the next start would adopt an
    orphan instead of starting fresh.

  * A STALE SERVER IS KILLED BEFORE A NEW SESSION. A tmux server already running on
    the socket with no `claude-<agent>` session would host the new session with ITS
    global environment, not this job's: an edited plist's EnvironmentVariables
    (CLAUDE_CONFIG_DIR, the daemons' configs) would never reach claude. (The env
    file is safe either way: the session's shell sources it.)

  * THE JOB'S PATH COMES FIRST IN THE SESSION. macOS's login shell runs path_helper,
    which rebuilds PATH with /usr/bin ahead of everything the job passed in, so a
    session would find Xcode's /usr/bin/python3 (older than the fleet's floor)
    before Homebrew's, and every `python3` and `#!/usr/bin/env python3` the agent
    runs would break. The session's shell exports the job's PATH in front of what
    the profile built, so the plist decides the order and the login profile only
    adds (claude's own directory, nvm).

CONFIG ERRORS (no TMUX_TMPDIR, no env file, no tmux) are logged and then the
supervisor waits the pre-sleep before exiting 1, so launchd's relaunch loop runs at
the pre-sleep's pace rather than every ThrottleInterval.

Stdlib only; imports nothing from the fleet library, so a broken library cannot keep
an agent's session from starting.
"""

import argparse
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time

READY_MARKER = "bypass permissions on"
AGENT_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")


class Stop(Exception):
    """A stop signal arrived."""


def log(msg):
    print(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} agent-session: {msg}", flush=True)


def parser():
    p = argparse.ArgumentParser(prog="agent-session.py",
                                description="Run and supervise one agent's Claude Code session in tmux.")
    p.add_argument("--agent", required=True, help="the agent's name: session claude-<agent>")
    p.add_argument("--env-file", required=True,
                   help="KEY=value lines the session's login shell sources (the credential file)")
    p.add_argument("--boot", required=True, help="the boot message, typed once the session is ready")
    p.add_argument("--pre-sleep", type=float, default=60.0,
                   help="seconds to wait before starting a new session (default 60)")
    p.add_argument("--ready-secs", type=float, default=180.0,
                   help="how long to wait for the ready status bar (default 180)")
    p.add_argument("--interval", type=float, default=3.0,
                   help="seconds between pane and session polls (default 3)")
    return p


def claude_command(agent, env_file, path):
    """The shell command the session runs: the systemd unit's ExecStart, with the
    job's PATH put back in front of the login PATH and the env file sourced by the
    login shell (launchd has no EnvironmentFile)."""
    base = f"claude --dangerously-skip-permissions --name {agent} --agent {agent}"
    script = (f"export PATH={shlex.quote(path)}:\"$PATH\"; set -a; . {shlex.quote(env_file)}; set +a; "
              f"claude --update; {base} --continue || {base}")
    return f"/bin/bash -lc {shlex.quote(script)}"


class Session:
    def __init__(self, tmux, agent):
        self.tmux, self.name = tmux, f"claude-{agent}"

    def run(self, *args, check=False):
        env = {k: v for k, v in os.environ.items() if k != "TMUX"}
        return subprocess.run([self.tmux, *args], capture_output=True, text=True, env=env,
                              stdin=subprocess.DEVNULL, timeout=30, check=check)

    def exists(self):
        return self.run("has-session", "-t", f"={self.name}").returncode == 0

    def server_up(self):
        return self.run("list-sessions").returncode == 0

    def pane(self):
        r = self.run("capture-pane", "-p", "-t", f"={self.name}:0")
        return r.stdout if r.returncode == 0 else None

    def kill(self):
        return self.run("kill-session", "-t", f"={self.name}").returncode == 0


def sleep_or_stop(secs):
    """time.sleep that a stop signal interrupts (the handler raises Stop)."""
    end = time.monotonic() + secs
    while (left := end - time.monotonic()) > 0:
        time.sleep(min(left, 1.0))


def config_error(msg, pre_sleep):
    log(f"CONFIG ERROR: {msg}. Not starting; exiting 1 after {pre_sleep:.0f} s so launchd's "
        f"relaunch runs at that pace")
    sleep_or_stop(pre_sleep)
    return 1


def supervise(a):
    if not AGENT_RE.fullmatch(a.agent):
        log(f"not an agent name: {a.agent!r}")
        return 2
    tmpdir = os.environ.get("TMUX_TMPDIR", "")
    if not os.path.isabs(tmpdir):
        return config_error("TMUX_TMPDIR is not set to an absolute path (the plist's "
                            "EnvironmentVariables names the socket directory)", a.pre_sleep)
    if not os.path.isfile(a.env_file):
        return config_error(f"no env file at {a.env_file} (a login agent's is empty; a token "
                            f"agent's holds its credential)", a.pre_sleep)
    tmux = shutil.which("tmux")
    if not tmux:
        return config_error(f"tmux is not on PATH ({os.environ.get('PATH', '')})", a.pre_sleep)
    os.makedirs(tmpdir, mode=0o700, exist_ok=True)
    os.chmod(tmpdir, 0o700)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"     # inherited by the tmux server it starts
    s = Session(tmux, a.agent)

    if s.exists():
        log(f"adopted the running session {s.name} in {tmpdir}; the boot message is not retyped")
    else:
        if s.server_up():
            log(f"a tmux server in {tmpdir} has no {s.name} session: killing it, so the new "
                f"session gets this job's environment")
            s.run("kill-server")
        if a.pre_sleep > 0:
            log(f"waiting {a.pre_sleep:.0f} s before starting {s.name}")
            sleep_or_stop(a.pre_sleep)
        r = s.run("new-session", "-d", "-s", s.name, "-c", os.getcwd(),
                  claude_command(a.agent, a.env_file, os.environ.get("PATH", "")))
        if r.returncode != 0:
            log(f"could not start {s.name}: tmux exit {r.returncode}: {r.stderr.strip()}")
            return 1
        log(f"started {s.name} in {tmpdir}")
        deadline, ready = time.monotonic() + a.ready_secs, False
        while time.monotonic() < deadline:
            text = s.pane()
            if text is None:
                log(f"{s.name} ended before it was ready")
                return 1
            if READY_MARKER in text:
                ready = True
                break
            sleep_or_stop(a.interval)
        if ready:
            s.run("send-keys", "-t", f"={s.name}:0", "-l", a.boot)
            sleep_or_stop(1.0)
            s.run("send-keys", "-t", f"={s.name}:0", "Enter")
            log(f"boot message sent to {s.name}")
        else:
            log(f"BOOT MESSAGE NOT SENT: {s.name} did not reach a ready status bar within "
                f"{a.ready_secs:.0f}s. The session is up but unbriefed - its followers are NOT "
                f"armed. Check the pane for a start-up dialog: TMUX_TMPDIR={tmpdir} tmux "
                f"capture-pane -p -t {s.name}")

    while s.exists():
        sleep_or_stop(a.interval)
    log(f"{s.name} ended; exiting 1 so launchd starts it again")
    return 1


def main(argv=None):
    a = parser().parse_args(argv)

    def stop(signum, _frame):
        raise Stop(signal.Signals(signum).name)

    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, stop)
    try:
        return supervise(a)
    except Stop as exc:
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(sig, signal.SIG_IGN)      # a second signal must not cut the cleanup short
        tmux = shutil.which("tmux")
        killed = Session(tmux, a.agent).kill() if tmux and AGENT_RE.fullmatch(a.agent) else False
        log(f"{exc}: {'killed' if killed else 'no running'} session claude-{a.agent}; exiting 0")
        return 0


if __name__ == "__main__":
    sys.exit(main())
