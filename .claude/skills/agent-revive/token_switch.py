#!/usr/bin/env python3
"""Move a TOKEN agent onto another pool account: install that account's token as
the agent's auth file and restart the agent's session through its own unit.

    token_switch.py <agent> --to USER (--package PATH | --no-package)
                    [--why TEXT] [--config C] [--now EPOCH]

Prints ONE JSON object. Exit 0 = the token is installed, the lease moved and the
restart is queued; 1 = refused before anything was written; 2 = a fault, which
says what had already changed.

WHY A RESTART, WHEN A LOGIN AGENT'S SWITCH IS FORBIDDEN TO RESTART
------------------------------------------------------------------
A login agent switches in-session (/login, agent-revive SKILL.md step 5), and a
restart is forbidden there because it drops the session's in-flight work. A
token agent CANNOT switch in-session: its session reads CLAUDE_CODE_OAUTH_TOKEN
from its environment once, at start, and keeps that token over any sign-in
typed into it (Claude Code 2.1.317 binary: "OAuth 401: keeping the
user-supplied CLAUDE_CODE_OAUTH_TOKEN instead of adopting the stored
credential. Mint a fresh token with `claude setup-token` and restart with it").
A running process's environment cannot be changed from outside, so the new
token reaches the session only through a new process: the unit's restart,
which re-reads its EnvironmentFile= and resumes the conversation (`--continue`
in the unit template). The in-flight work is protected the same way a login
agent's is - by the handover BEFORE the switch (agent-health SKILL.md steps
6-8) - which is why this script refuses to run without the handover package
the agent wrote (`--package`), unless the caller says there is none to write
(`--no-package`: a session whose token is already dead holds no work).

WHAT IT DOES, IN ORDER, AND WHY THE ORDER
-----------------------------------------
1. `tmux_triage.sh <agent> --facts`: the agent's auth mode, auth file, unit and
   the service manager running it. Refused unless the mode is `token` and a
   manager answered - every check that can refuse runs before any write.
2. `pool_pick.py --take USER --agent <agent> --install-token <auth file>`: the
   token copy (0600, atomic) and the lease move, under one lock, token first, so
   the lease and the token move together or not at all, and the handover
   ledger's row. A refusal there (USER leased elsewhere, no token file, a token
   file readable by others or naming another account) changes nothing.
3. The restart of ONLY this agent's unit, on the manager --facts named
   (unit_manager, unit_scope), without waiting for the session (the
   pre-sleep and readiness wait take minutes; agent-health SKILL.md step 11
   confirms it came back):
     systemd  `systemctl [--user] restart --no-block <unit>`; $FLEET_SYSTEMCTL
              replaces `systemctl`.
     launchd  fleetlib.services.restart: bootout, which sends the session
              supervisor SIGTERM so it kills the session, then bootstrap from
              the plist. NEVER `kickstart -k`: should it kill the supervisor
              with no chance to clean up, the restarted supervisor ADOPTS the
              session still running on the OLD token, and the switch reports
              success with nothing switched.
   A system-manager unit needs privileges this agent may not have: the fault
   then names the command a person runs, and says that the token and the
   lease have already moved.

The token's bytes go from the pool's token file to the agent's auth file
inside pool_pick.py and nowhere else: this script never opens either file.
"""

import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
FLEET_LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))), "lib")
TRIAGE = os.path.join(HERE, "tmux_triage.sh")
PICKER = os.path.join(os.path.dirname(HERE), "agent-health", "pool_pick.py")


def emit(rc, obj):
    print(json.dumps(obj, indent=2))
    return rc


def run(argv, env=None):
    p = subprocess.run(argv, capture_output=True, text=True, stdin=subprocess.DEVNULL, env=env)
    try:
        out = json.loads(p.stdout)
    except ValueError:
        out = None
    return p.returncode, out, p.stderr.strip()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="token_switch.py", description=__doc__.split("\n")[0])
    ap.add_argument("agent")
    ap.add_argument("--to", required=True, metavar="USER", help="the pool account to move to")
    pkg = ap.add_mutually_exclusive_group(required=True)
    pkg.add_argument("--package", metavar="PATH",
                     help="the handover package the agent wrote (HANDOVER-READY)")
    pkg.add_argument("--no-package", action="store_true",
                     help="no package: the session holds no work (its token is already dead)")
    ap.add_argument("--why", default="-", help="the handover ledger's Why column")
    ap.add_argument("--config", help="agent-revive's config.json")
    ap.add_argument("--now", help="override the clock, epoch seconds (tests)")
    a = ap.parse_args(argv)
    cfg = ["--config", a.config] if a.config else []
    base = {"agent": a.agent, "to": a.to, "token_installed": None, "restart": None}

    if a.package and not (os.path.isfile(a.package) and os.path.getsize(a.package) > 0):
        return emit(1, dict(base, reason="no handover package at %s - the restart drops "
                                         "every subagent and monitor the session holds, so it "
                                         "runs only once the agent has written its package "
                                         "(agent-health SKILL.md steps 6-8)" % a.package))

    rc, facts, err = run(["bash", TRIAGE, a.agent, "--facts"] + cfg)
    if facts is None:
        return emit(2, dict(base, reason="tmux_triage.sh --facts gave no answer (exit %d): %s"
                                         % (rc, err)))
    if facts.get("auth") != "token":
        return emit(1, dict(base, facts=facts,
                            reason="auth mode is %s, not token - %s"
                                   % (facts.get("auth"), facts.get("auth_problem") or
                                      "a login agent switches in-session (agent-revive "
                                      "SKILL.md step 5), and an api-key agent is in no pool")))
    scope, unit = facts.get("unit_scope"), facts.get("unit")
    if scope not in ("user", "system"):
        return emit(1, dict(base, facts=facts,
                            reason="no service manager runs %s, so there is no unit to restart "
                                   "the session through - nothing changed" % unit))

    take = ["python3", PICKER, "--take", a.to, "--agent", a.agent,
            "--install-token", facts["auth_file"], "--why", a.why] + cfg
    if a.now:
        take += ["--now", a.now]
    rc, took, err = run(take)
    if rc != 0 or not took or not took.get("taken"):
        return emit(1 if rc == 1 else 2, dict(base, take=took,
                                              reason="pool_pick.py --take refused or failed "
                                                     "(exit %d) - nothing changed: %s"
                                                     % (rc, (took or {}).get("reason") or err)))

    out = dict(base, released=took.get("released"), token_installed=took.get("token_installed"),
               unit=unit, unit_scope=scope, handover_ledger=took.get("handover_ledger"))
    if facts.get("unit_manager") == "launchd":
        return restart_launchd(out, unit, scope)

    systemctl = os.environ.get("FLEET_SYSTEMCTL") or "systemctl"
    env = dict(os.environ)
    env.setdefault("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid())
    cmd = [systemctl] + (["--user"] if scope == "user" else []) + ["restart", "--no-block", unit]
    p = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, env=env)
    if p.returncode != 0:
        by_hand = " ".join((["sudo"] if scope == "system" else []) + cmd)
        return emit(2, dict(out, restart="failed",
                            reason="the token is installed and the lease moved, but the restart "
                                   "failed (exit %d: %s) - the session still runs on the OLD "
                                   "token until `%s` runs" % (p.returncode, p.stderr.strip(), by_hand)))
    return emit(0, dict(out, restart="queued"))


def restart_launchd(out, unit, scope):
    """Restart a launchd job through fleetlib.services (WHAT IT DOES, step 3)."""
    root = "sudo " if scope == "system" else ""
    by_hand = "launchctl bootout, then launchctl bootstrap of its plist"
    try:
        sys.path.insert(0, FLEET_LIB)
        from fleetlib import services
        by_hand = (f"{root}launchctl bootout {services.domain(scope)}/{unit}; "
                   f"{root}launchctl bootstrap {services.domain(scope)} "
                   f"{services.unit_dir(scope) / services.unit_file(unit)}")
        services.restart(unit, scope=scope)
    except Exception as exc:  # noqa: BLE001 - fleetlib's faults and an unimportable library alike
        return emit(2, dict(out, restart="failed",
                            reason="the token is installed and the lease moved, but the restart "
                                   "failed (%s: %s) - the session still runs on the OLD token until "
                                   "`%s` runs" % (type(exc).__name__, exc, by_hand)))
    return emit(0, dict(out, restart="queued"))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - a crash must never read as a switch
        print(json.dumps({"restart": None, "fault": "%s: %s" % (type(exc).__name__, exc)}))
        sys.exit(2)
