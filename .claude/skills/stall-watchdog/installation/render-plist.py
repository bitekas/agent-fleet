#!/usr/bin/env python3
"""render-plist.py - render one agent's launchd job: its stall watchdog, or its session.

    python3 render-plist.py [--job watchdog] --agent <agent> --agents-root <dir> \\
        --checkout <dir> --state-dir <dir> --tmux-dir <dir> --form system|user --out <file> \\
        [--config <file>]
    python3 render-plist.py --job session --agent <agent> --name <Agent-Name> \\
        --agents-root <dir> --project-dir <dir> --watch-job <job> --watch-config-env <var> \\
        --auth-mode token|login|api-key --form system|user --out <file>

`--job watchdog` (the default) renders agent-stall-watchdog.plist.example beside this
file; `--job session` renders the fleet's templates/claude-agent.plist.example, the
agent's own session. Run it AS THE USER THE JOB RUNS AS, on the Mac the job runs on:
`/adding-an-agent` section 5 steps 6 and 7 run it on the target as the agents user,
and launchd-daemon.smoke.sh runs it as the invoking user. Silent on success; on a
refusal it prints ONE line starting `NOT RENDERED:`, exits 1, and writes nothing.

What it fills, besides the placeholders its arguments name:

  <launchd-prefix>  fleetlib.services.prefix() (host.json's launchd_prefix)
  <user>, <agents-user>
                    the user running this, which is the job's UserName in the system
                    form (the user form, a LaunchAgent, carries no UserName)
  <fleet>           the fleet tree this file is in
  <python>          the interpreter every fleet job runs: `agent-daemons.py jobs
                    --json`'s `python` (FLEET_PYTHON, else host.json's python, else
                    launchd's default), the one place the fleet writes it down
  <path>            the directory of each command the job runs by a bare name, as found
                    on THIS process's PATH - tmux for the watchdog; tmux, then claude,
                    for the session - then <python>'s directory, then
                    /usr/bin:/bin:/usr/sbin:/sbin

THE FORMS. The system form is a LaunchDaemon whose UserName is the user running this;
the user form a LaunchAgent without one. The watchdog example carries UserName and the
user form drops it; the session template carries it inside a `<!--system: ... -->`
comment, which the system form uncomments (the systemd template's `#system: ` lines'
counterpart) and the user form drops with every other comment. Either way the job is
read back after the fill: a system-form job whose UserName is not this user - the
marker missing or misspelled, which would run the session as root - is refused.

LOAD-BEARING PROPERTIES - each one is here because removing it brings back a job
that is up and blind, or one that does not start:

  * THE JOB'S PATH IS DERIVED FROM WHERE ITS COMMANDS ARE, NEVER WRITTEN DOWN.
    watchdog.py runs a bare `tmux`, and the session supervisor runs a bare `tmux` and
    puts the job's PATH in front of the login shell's that starts `claude`, so each job
    sees exactly the programs its PATH reaches, and launchd's own PATH
    (/usr/bin:/bin:/usr/sbin:/sbin) reaches none of them on a Mac. A hardcoded
    Homebrew directory is right on one layout only: a tmux in ~/.local/bin, MacPorts
    or Intel Homebrew's /usr/local/bin leaves every capture failing with
    FileNotFoundError while launchd shows the job running (measured: the LaunchDaemon
    smoke on a Mac without Homebrew, tmux in ~/.local/bin, read "up and blind"), and a
    session plist naming Homebrew's python3 on a Mac without it does not start at all.
    Resolved for the user running this because that user is the job's UserName.

  * NO COMMAND, NO PLIST. A job rendered without one of its commands on its PATH is a
    watchdog that supervises nothing and reports healthy, or a session that never
    starts, so the absence is a refusal naming the command and the PATH searched,
    never a render with a guess in it.

  * THE RENDERED PATH IS PROVED, NOT ASSUMED: each command (`tmux -V`, `claude
    --version`) and the interpreter run here under an environment holding ONLY that
    PATH. launchd gives the job that PATH and adds HOME, USER and the like, so this is
    stricter than the job's start: an interpreter that needs HOME to start at all (a
    pyenv shim) is refused - name the real interpreter instead. A command that is
    found but does not run (a broken link, a missing library) and an interpreter that
    is not there both refuse. Checking that the files exist would pass both.

  * COMMENTS ARE DROPPED BEFORE THE FILL. A value carrying a double hyphen inside the
    template's XML comment would end the comment early and the plist would not
    parse; the comment is documentation for the reader of the example, not of the
    rendered job. Values are XML-escaped, so a display name with an ampersand fills.

What it does not check: that the watchdog's tmux is the one the session itself runs
(each plist's PATH decides that; a different tmux build can refuse the session's
server), and who can change the tmux or the PATH directories. That is
install-agent-fleet's verify-privileges.py's, which FAILs a watchdog whose tmux,
or a directory searched before it, the agents user can change: a tmux in that
user's own ~/.local/bin renders here and FAILs there. Homebrew's, installed as
the administrator, passes both. The session's PATH is not a privilege question:
the session runs as the agents user, which may change its own programs.

Exit codes: 0 rendered; 1 refused, nothing written; 2 usage.
"""
import argparse
import json
import os
import plistlib
import pwd
import re
import shutil
import subprocess
import sys
import tempfile
from xml.sax.saxutils import escape

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.realpath(__file__))
FLEET = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
SYSTEM_PATH = ("/usr/bin", "/bin", "/usr/sbin", "/sbin")
# Per job: its template, the arguments it needs, and each command it runs by a bare
# name with the arguments that prove it runs.
JOBS = {
    "watchdog": (os.path.join(HERE, "agent-stall-watchdog.plist.example"),
                 ("checkout", "state-dir", "tmux-dir"), (("tmux", "-V"),)),
    "session": (os.path.join(FLEET, "templates", "claude-agent.plist.example"),
                ("name", "project-dir", "watch-job", "watch-config-env", "auth-mode"),
                (("tmux", "-V"), ("claude", "--version"))),
}
SYSTEM_MARKER = re.compile(r"<!--system: (.*?) -->")


def refuse(msg):
    print(f"NOT RENDERED: {msg}")
    sys.exit(1)


def interpreter():
    """The fleet's job interpreter, as agent-daemons.py's job table states it for launchd."""
    env = dict(os.environ, FLEET_SERVICE_BACKEND="launchd", PYTHONDONTWRITEBYTECODE="1")
    argv = [sys.executable, os.path.join(FLEET, "systemd", "agent-daemons.py"), "jobs", "--json"]
    try:
        p = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        refuse(f"agent-daemons.py jobs --json did not run ({type(e).__name__}: {e})")
    try:
        return json.loads(p.stdout)["python"]
    except (ValueError, KeyError, TypeError):
        refuse(f"agent-daemons.py jobs --json names no interpreter (exit {p.returncode}: "
               f"{p.stderr.strip()[-300:]})")


def runs(argv, path):
    """None when argv runs and exits 0 under an environment holding only PATH=path."""
    try:
        r = subprocess.run(argv, env={"PATH": path}, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        return f"{type(e).__name__}: {e}"
    return None if r.returncode == 0 else f"exit {r.returncode}: {(r.stderr or r.stdout).strip()[:200]}"


def job_path(commands, py):
    """The job's PATH, proved: each command's directory as found on this process's PATH,
    then the interpreter's, then the system directories; refused when a command is not
    found, or it or the interpreter does not run under that PATH alone."""
    found = []
    for cmd, *_ in commands:
        where = shutil.which(cmd)
        if not where:
            refuse(f"no {cmd} on PATH ({os.environ.get('PATH', '')}), so the job would start "
                   f"{'blind' if cmd == 'tmux' else 'without it'}. Run this with the directory of the "
                   f"{cmd} the job runs on PATH: PATH=<that directory>:$PATH")
        found.append(os.path.abspath(where))
    path = ":".join(dict.fromkeys([*(os.path.dirname(f) for f in found), os.path.dirname(py), *SYSTEM_PATH]))
    for (cmd, *proof), where in zip(commands, found):
        why = runs([cmd, *proof], path)
        if why:
            refuse(f"{cmd} {' '.join(proof)} under the job's PATH ({path}) does not run ({why}): it found {where}")
    why = runs([py, "-I", "-c", "pass"], path)
    if why:
        refuse(f"the fleet's interpreter {py} does not run ({why}): set FLEET_PYTHON, or "
               f"host.json's python, to one that does")
    return path


def main():
    ap = argparse.ArgumentParser(description="Render one agent's launchd job: its stall watchdog, or its session.")
    ap.add_argument("--job", choices=tuple(JOBS), default="watchdog")
    for opt in ("agent", "agents-root", "out"):
        ap.add_argument(f"--{opt}", required=True)
    ap.add_argument("--form", required=True, choices=("system", "user"))
    for opt in ("checkout", "state-dir", "tmux-dir", "name", "project-dir", "watch-job", "watch-config-env"):
        ap.add_argument(f"--{opt}")
    ap.add_argument("--auth-mode", choices=("token", "login", "api-key"))
    ap.add_argument("--config", help="the watchdog's STALL_WATCHDOG_CONFIG, when not the template's "
                    "<agents-root>/<agent>/config/stall-watchdog.json")
    a = ap.parse_args()
    template, needs, commands = JOBS[a.job]
    missing = [f"--{o}" for o in needs if getattr(a, o.replace("-", "_")) is None]
    if missing:
        ap.error(f"--job {a.job} needs {' '.join(missing)}")

    py = interpreter()
    if not os.path.isabs(py):
        refuse(f"the fleet's interpreter {py!r} is not an absolute path")
    path = job_path(commands, py)

    sys.path.insert(0, os.path.join(FLEET, "lib"))
    try:
        from fleetlib import services
        prefix = services.prefix()
    except Exception as e:  # noqa: BLE001 - fleetlib's refusal is the whole finding
        refuse(f"fleetlib names no launchd prefix ({type(e).__name__}: {e})")

    try:
        user = pwd.getpwuid(os.getuid()).pw_name
    except KeyError:
        refuse(f"uid {os.getuid()} has no passwd entry, so the job has no UserName to run as")
    values = {"launchd-prefix": prefix, "user": user, "agents-user": user, "fleet": FLEET,
              "agents-root": a.agents_root, "python": py, "path": path}
    if a.job == "watchdog":
        values.update({"agent": a.agent, "checkout": a.checkout, "state dir": a.state_dir, "tmux-dir": a.tmux_dir})
    else:
        values.update({"agent-name": a.agent, "Agent-Name": a.name, "project-dir": a.project_dir,
                       "watch-job": a.watch_job, "watch-config-env": a.watch_config_env, "auth-mode": a.auth_mode})
    with open(template, encoding="utf-8") as f:
        text = f.read()
    if a.form == "system":
        text = SYSTEM_MARKER.sub(r"\1", text)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    for k, v in values.items():
        text = text.replace(f"<{k}>", escape(v))
    try:
        job = plistlib.loads(text.encode("utf-8"))
    except Exception as e:  # noqa: BLE001 - any parse failure is a placeholder left or a bad value
        refuse(f"{template} does not parse once filled, a placeholder this renderer does not "
               f"know is left in it ({type(e).__name__}: {e})")
    if a.config and a.job == "watchdog":
        job["EnvironmentVariables"]["STALL_WATCHDOG_CONFIG"] = a.config
    if a.form == "user":
        job.pop("UserName", None)
    elif job.get("UserName") != user:
        refuse(f"the rendered {a.job} job runs as {job.get('UserName') or 'root'}, not as {user}: "
               f"{template} lost its UserName (a misspelled system: marker, in the session template)")

    out_dir = os.path.dirname(os.path.abspath(a.out))
    try:
        fd, tmp = tempfile.mkstemp(prefix=".render-plist.", dir=out_dir)
    except OSError as e:
        refuse(f"cannot write in {out_dir} ({type(e).__name__}: {e})")
    try:
        with os.fdopen(fd, "wb") as f:
            plistlib.dump(job, f)
        os.chmod(tmp, 0o644)
        os.replace(tmp, a.out)
    except BaseException as e:
        os.unlink(tmp)
        if isinstance(e, OSError):
            refuse(f"cannot write {a.out} ({type(e).__name__}: {e})")
        raise


if __name__ == "__main__":
    main()
