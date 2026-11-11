#!/usr/bin/env python3
"""render-plist.py - render agent-stall-watchdog.plist.example for one session.

    python3 render-plist.py --agent <agent> --agents-root <dir> --checkout <dir> \\
        --state-dir <dir> --tmux-dir <dir> --form system|user --out <file> [--config <file>]

Run it AS THE USER THE JOB RUNS AS, on the Mac the job runs on: `/adding-an-agent`
section 5 step 7 runs it on the target as the agents user, and
launchd-daemon.smoke.sh runs it as the invoking user. Silent on success; on a
refusal it prints ONE line starting `NOT RENDERED:`, exits 1, and writes nothing.

What it fills, besides the placeholders its arguments name:

  <launchd-prefix>  fleetlib.services.prefix() (host.json's launchd_prefix)
  <user>            the user running this, which is the job's UserName (the system
                    form; the user form, a LaunchAgent, carries no UserName)
  <fleet>           the fleet tree this file is in
  <python>          the interpreter every fleet job runs: `agent-daemons.py jobs
                    --json`'s `python` (FLEET_PYTHON, else host.json's python, else
                    launchd's default), the one place the fleet writes it down
  <path>            the directory of the tmux found on THIS process's PATH, then
                    <python>'s directory, then /usr/bin:/bin:/usr/sbin:/sbin

LOAD-BEARING PROPERTIES - each one is here because removing it brings back a job
that is up and blind:

  * THE JOB'S PATH IS DERIVED FROM WHERE TMUX IS, NEVER WRITTEN DOWN. watchdog.py
    runs a bare `tmux`, so the job sees exactly the tmux its PATH reaches, and
    launchd's own PATH (/usr/bin:/bin:/usr/sbin:/sbin) reaches none on a Mac. A
    hardcoded Homebrew directory is right on one layout only: a tmux in ~/.local/bin,
    MacPorts or Intel Homebrew's /usr/local/bin leaves every capture failing with
    FileNotFoundError while launchd shows the job running (measured: the LaunchDaemon
    smoke on a Mac without Homebrew, tmux in ~/.local/bin, read "up and blind").
    Resolved for the user running this because that user is the job's UserName.

  * NO TMUX, NO PLIST. A job rendered without a tmux on its PATH is a watchdog that
    supervises nothing and reports healthy, so the absence is a refusal naming the
    PATH searched, never a render with a guess in it.

  * THE RENDERED PATH IS PROVED, NOT ASSUMED: `tmux -V` and the interpreter run here
    under an environment holding ONLY that PATH, which is what launchd gives the
    job. A tmux that is found but does not run (a broken link, a missing library)
    and an interpreter that is not there both refuse. Checking that the files exist
    would pass both.

  * COMMENTS ARE DROPPED BEFORE THE FILL. A value carrying a double hyphen inside the
    template's XML comment would end the comment early and the plist would not
    parse; the comment is documentation for the reader of the example, not of the
    rendered job.

What it does not check: that this tmux is the one the session itself runs (the
session plist's PATH decides that), and who can change the tmux or the PATH
directories (install-agent-fleet's verify-privileges.py audits the job's
interpreter, program and plist).

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
TEMPLATE = os.path.join(HERE, "agent-stall-watchdog.plist.example")
SYSTEM_PATH = ("/usr/bin", "/bin", "/usr/sbin", "/sbin")


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


def main():
    ap = argparse.ArgumentParser(description="Render the stall watchdog's launchd job.")
    for opt in ("agent", "agents-root", "checkout", "state-dir", "tmux-dir", "out"):
        ap.add_argument(f"--{opt}", required=True)
    ap.add_argument("--form", required=True, choices=("system", "user"))
    ap.add_argument("--config", help="STALL_WATCHDOG_CONFIG, when not the template's "
                    "<agents-root>/<agent>/config/stall-watchdog.json")
    a = ap.parse_args()

    found = shutil.which("tmux")
    if not found:
        refuse(f"no tmux on PATH ({os.environ.get('PATH', '')}), so the job would start blind. "
               f"Run this with the directory of the tmux the session runs on PATH: "
               f"PATH=<that directory>:$PATH")
    tmux = os.path.abspath(found)
    py = interpreter()
    if not os.path.isabs(py):
        refuse(f"the fleet's interpreter {py!r} is not an absolute path")
    dirs = []
    for d in (os.path.dirname(tmux), os.path.dirname(py), *SYSTEM_PATH):
        if d not in dirs:
            dirs.append(d)
    path = ":".join(dirs)
    why = runs(["tmux", "-V"], path)
    if why:
        refuse(f"tmux -V under the job's PATH ({path}) does not run ({why}): it found {tmux}")
    why = runs([py, "-I", "-c", "pass"], path)
    if why:
        refuse(f"the fleet's interpreter {py} does not run ({why}): set FLEET_PYTHON, or "
               f"host.json's python, to one that does")

    sys.path.insert(0, os.path.join(FLEET, "lib"))
    try:
        from fleetlib import services
        prefix = services.prefix()
    except Exception as e:  # noqa: BLE001 - fleetlib's refusal is the whole finding
        refuse(f"fleetlib names no launchd prefix ({type(e).__name__}: {e})")

    values = {"launchd-prefix": prefix, "agent": a.agent, "user": pwd.getpwuid(os.getuid()).pw_name,
              "checkout": a.checkout, "fleet": FLEET, "agents-root": a.agents_root,
              "state dir": a.state_dir, "tmux-dir": a.tmux_dir, "python": py, "path": path}
    with open(TEMPLATE, encoding="utf-8") as f:
        text = re.sub(r"<!--.*?-->", "", f.read(), flags=re.S)
    for k, v in values.items():
        text = text.replace(f"<{k}>", escape(v))
    try:
        job = plistlib.loads(text.encode("utf-8"))
    except Exception as e:  # noqa: BLE001 - any parse failure is a placeholder left or a bad value
        refuse(f"{TEMPLATE} does not parse once filled, a placeholder this renderer does not "
               f"know is left in it ({type(e).__name__}: {e})")
    if a.config:
        job["EnvironmentVariables"]["STALL_WATCHDOG_CONFIG"] = a.config
    if a.form == "user":
        job.pop("UserName", None)

    out_dir = os.path.dirname(os.path.abspath(a.out))
    fd, tmp = tempfile.mkstemp(prefix=".render-plist.", dir=out_dir)
    try:
        with os.fdopen(fd, "wb") as f:
            plistlib.dump(job, f)
        os.chmod(tmp, 0o644)
        os.replace(tmp, a.out)
    except BaseException:
        os.unlink(tmp)
        raise


if __name__ == "__main__":
    main()
