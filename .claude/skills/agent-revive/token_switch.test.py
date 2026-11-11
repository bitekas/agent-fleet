#!/usr/bin/env python3
"""Offline guard for the TOKEN agent path through agent-revive: the user-manager
unit read, the auth facts, the token switch and the dead-token report.

    python3 token_switch.test.py

Synthetic agents and accounts in a temp directory. The service manager is a FAKE
`systemctl` ($FLEET_SYSTEMCTL) that answers `cat` from unit files this test
writes - some only to the USER manager, one only to the SYSTEM manager - and
records every `restart` it is asked for, so nothing here reads or restarts a real
unit. No tmux, no network.

WHAT EACH PART IS FOR
  A. THE USER MANAGER IS READ. tmux_triage.sh --facts and --bootstrap-prompt
     find a unit only `systemctl --user cat` knows, report scope `user`, expand
     the unit's `%t` to the user runtime dir, and read FLEET_AGENT_AUTH and the
     EnvironmentFile= off it. An unreadable unit is auth `unknown`, never login.
  B. THE TOKEN SWITCH. token_switch.py installs the target account's token over
     the agent's auth file (byte for byte, 0600), moves the lease, writes the
     handover-ledger row, and restarts EXACTLY that agent's unit on the manager
     that runs it. Every refusal changes nothing and restarts nothing.
  D. MACOS: THE LAUNCHD JOB. Under FLEET_SERVICE_BACKEND=launchd --facts reads
     the agent's job plist from ~/Library/LaunchAgents and names the manager
     (unit_manager launchd), and the switch restarts the job through
     fleetlib.services against the fleet's fake launchctl
     (tests/fixtures/launchd/fake-launchctl): a bootout, then a bootstrap of the
     plist, and no systemctl call at all. A failed bootstrap is exit 2 naming
     the bootout and bootstrap a person runs. Every other part runs under
     FLEET_SERVICE_BACKEND=systemd, so this file reads the same on macOS.
  C. A DEAD TOKEN IS REPORTED, NOT REVIVED. The measured pane of a session whose
     env token was refused (fixtures/token-invalid.txt, captured 2026-11-06 from
     Claude Code 2.1.317) reads `token-invalid` on a token agent - whose note
     forbids /login - and `login-expired` on a login agent.

EXIT CODES: 0 PASS, 1 FAIL, 3 NO VERDICT (a control misbehaved: not a pass).

WHY EACH CONTROL IS LOAD-BEARING - read before deleting one
  * Each part runs a deliberately BROKEN COPY of the real script and requires
    the check to go red on it: the user-manager read removed (the agent's unit
    must stop being found), the token installed somewhere other than the auth
    file the unit names (the "right file" check must fail), every agent unit
    restarted by a glob instead of one (the "only that agent" check must fail),
    the token-invalid branch removed (the token agent must read login-expired),
    the launchd restart removed (a launchd agent's switch must stop reaching
    launchctl).
    A check a broken copy also passes cannot see what it is named for.
  * The login agent on the SAME dead pane must read `login-expired`: without it
    `token-invalid` could be a pane nobody would read as a dead login at all.
  * Positive evidence the fake manager was reached: its log must show the `cat`
    calls the facts made, so a scope reported `user` is the fake's answer.
  * No token reaches any output, with a control that the search strings are the
    registered tokens.
"""

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
TRIAGE = os.path.join(HERE, "tmux_triage.sh")
SWITCH = os.path.join(HERE, "token_switch.py")
PICK = os.path.join(os.path.dirname(HERE), "agent-health", "pool_pick.py")
PANE = os.path.join(HERE, "fixtures", "token-invalid.txt")
UID = os.getuid()
TOK = {"x@example.com": "sk-ant-oat01-" + "X" * 80, "y@example.com": "sk-ant-oat01-" + "Y" * 80,
       "w@example.com": "sk-ant-oat01-" + "W" * 80}

passed, failed, broken, outputs = 0, [], [], []


def ok(what, got, want):
    global passed
    if got == want:
        print("ok   - %s" % what)
        passed += 1
    else:
        print("FAIL - %s: expected %r, got %r" % (what, want, got))
        failed.append(what)


def control(what, got, want):
    global passed
    if got == want:
        print("ok   - control: %s" % what)
        passed += 1
    else:
        print("CONTROL BROKEN - %s: expected %r, got %r" % (what, want, got))
        broken.append(what)


tmp = tempfile.mkdtemp(prefix="token-switch-test-")
FAKE_LOG = os.path.join(tmp, "systemctl.log")
FAKE_SC = os.path.join(tmp, "fake-systemctl")
with open(FAKE_SC, "w") as fh:
    fh.write("""#!/bin/sh
echo "$*" >> "%(log)s"
scope=system
[ "$1" = --user ] && { scope=user; shift; }
case "$1" in
  cat) f="%(units)s/$scope/$2"; [ -f "$f" ] && { cat "$f"; exit 0; }; exit 1 ;;
  restart) exit "${FAKE_RESTART_RC:-0}" ;;
esac
exit 1
""" % {"log": FAKE_LOG, "units": os.path.join(tmp, "units")})
os.chmod(FAKE_SC, 0o755)
ENV = dict(os.environ, FLEET_SYSTEMCTL=FAKE_SC, XDG_RUNTIME_DIR=os.path.join(tmp, "xdg"),
           XDG_CONFIG_HOME=os.path.join(tmp, "no-user-unit-files"), FLEET_SERVICE_BACKEND="systemd")
FAKE_LAUNCHCTL = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))),
                              "tests", "fixtures", "launchd", "fake-launchctl")
ENV.pop("AGENT_REVIVE_CONFIG", None)


def run(argv, stdin=None, env=None):
    p = subprocess.run(argv, input=stdin, capture_output=True, text=True, env=env or ENV)
    outputs.append(p.stdout + p.stderr)
    try:
        out = json.loads(p.stdout)
    except ValueError:
        out = None
    return p.returncode, out, p.stdout, p.stderr


def triage(agent, *args, script=TRIAGE, env=None):
    return run(["bash", script, agent, "--config", CFG] + list(args), env=env)


def mutant(name, script, old, new):
    """A fleet-shaped copy - <root>/.claude/skills/{agent-revive,agent-health}, the
    scripts only - with `script` mutated: both scripts find their siblings through
    that layout, so a copy without it would fail on plumbing, not on the mutation."""
    skills = os.path.join(tmp, "mutant-" + name, ".claude", "skills")
    for s in ("agent-revive", "agent-health"):
        src_dir = os.path.join(os.path.dirname(HERE), s)
        os.makedirs(os.path.join(skills, s))
        for f in os.listdir(src_dir):
            if os.path.isfile(os.path.join(src_dir, f)):
                shutil.copy(os.path.join(src_dir, f), os.path.join(skills, s))
    src = open(script, encoding="utf-8").read()
    control("mutation '%s' applies exactly once" % name, src.count(old), 1)
    out = os.path.join(skills, "agent-revive", os.path.basename(script))
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(src.replace(old, new))
    return out


def unit(scope, agent, auth=None, envfile=None):
    home = os.path.join(tmp, "agents", agent)
    lines = ["[Service]", "Environment=CLAUDE_CONFIG_DIR=%s/.claude" % home,
             "Environment=TMUX_TMPDIR=%%t/claude-tmux-%s" % agent]
    if auth:
        lines.append("Environment=FLEET_AGENT_AUTH=%s" % auth)
    if envfile:
        lines.append("EnvironmentFile=%s" % envfile)
    lines.append("ExecStartPost=/bin/bash -c 'tmux send-keys -t claude-%s:0 \"You are %s, just "
                 "restarted.\"; tmux send-keys -t claude-%s:0 Enter'" % (agent, agent, agent))
    d = os.path.join(tmp, "units", scope)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "claude-agent-%s.service" % agent), "w") as fh:
        fh.write("\n".join(lines) + "\n")
    secrets = os.path.join(home, "secrets", "personal")
    os.makedirs(secrets, mode=0o700, exist_ok=True)
    return os.path.join(secrets, "claude-auth.env")


def restarts():
    if not os.path.exists(FAKE_LOG):
        return []
    return [l.strip() for l in open(FAKE_LOG) if " restart " in " %s " % l]


try:
    CFG = os.path.join(tmp, "config.json")
    state = os.path.join(tmp, "doctor-state")
    os.mkdir(state)
    with open(CFG, "w") as fh:
        json.dump({"fleet": {"agents_home": os.path.join(tmp, "agents"),
                             "tmux": {"tmpdir": "/run/user/<uid>/claude-tmux-<agent>",
                                      "target": "claude-<agent>:0"},
                             "systemd_unit": "claude-agent-<agent>.service"},
                   "accounts": {"pool_file": os.path.join(tmp, "secrets", "pool.json"),
                                "lease_file": os.path.join(state, "leases.json"),
                                "ledger_file": os.path.join(state, "agents.md"),
                                "handover_ledger_file": os.path.join(state, "handover.md")}}, fh)
    for user, tok in TOK.items():
        rc, _, _, _ = run(["python3", PICK, "--config", CFG, "--register", user, "--token-stdin"],
                          stdin=tok + "\n")
        control("register %s through pool_pick.py --register" % user, rc, 0)
    rc, _, _, _ = run(["python3", PICK, "--config", CFG, "--register", "z@example.com",
                       "--password-stdin"], stdin="fixture-password-not-real\n")
    control("register a password-only account z", rc, 0)
    pool = {e["username"]: e for e in json.load(open(os.path.join(tmp, "secrets", "pool.json")))}

    ada_auth = unit("user", "ada", "token", os.path.join(tmp, "agents", "ada", "secrets",
                                                           "personal", "claude-auth.env"))
    alan_auth = unit("system", "alan", "token", os.path.join(tmp, "agents", "alan", "secrets",
                                                               "personal", "claude-auth.env"))
    unit("user", "grace", None, os.path.join(tmp, "agents", "grace", "secrets", "personal",
                                              "claude-auth.env"))
    bob_auth = unit("user", "bob", "api-key", os.path.join(tmp, "agents", "bob", "secrets",
                                                            "personal", "claude-auth.env"))
    with open(bob_auth, "w") as fh:
        fh.write("ANTHROPIC_API_KEY=sk-ant-api03-not-a-real-key\n")
    with open(alan_auth, "w") as fh:
        fh.write("CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-handwritten-no-header\n")
    rc, _, _, _ = run(["python3", PICK, "--config", CFG, "--take", "x@example.com", "--agent", "ada",
                       "--install-token", ada_auth, "--why", "first token"])
    control("ada starts on x, installed through --take --install-token", rc, 0)
    rc, _, _, _ = run(["python3", PICK, "--config", CFG, "--take", "w@example.com", "--agent", "beta"])
    control("w is leased to another agent, beta", rc, 0)

    # ------------------------------------------- A. the user manager is read
    rc, f, _, _ = triage("ada", "--facts")
    control("the facts reached the fake manager (its log shows the user-manager cat)",
            any(l.startswith("--user cat claude-agent-ada.service") for l in open(FAKE_LOG)), True)
    ok("--facts: ada's unit is found on the USER manager", (rc, (f or {}).get("unit_scope")), (0, "user"))
    ok("--facts: auth token, its EnvironmentFile, and the account its header names",
       ((f or {}).get("auth"), (f or {}).get("auth_file"), (f or {}).get("auth_account")),
       ("token", ada_auth, "x@example.com"))
    ok("--facts: %t in the user unit's TMUX_TMPDIR is the user runtime dir",
       (f or {}).get("tmux_tmpdir"), os.path.join(tmp, "xdg", "claude-tmux-ada"))
    ok("--facts: the config dir is the unit's CLAUDE_CONFIG_DIR",
       (f or {}).get("config_dir"), os.path.join(tmp, "agents", "ada", ".claude"))
    rc, _, out, _ = triage("ada", "--bootstrap-prompt")
    ok("--bootstrap-prompt reads the prompt out of a USER unit", (rc, out.strip()),
       (0, "You are ada, just restarted."))
    rc, f, _, _ = triage("alan", "--facts")
    ok("a unit only the SYSTEM manager knows is found there, %t -> /run",
       ((f or {}).get("unit_scope"), (f or {}).get("tmux_tmpdir")), ("system", "/run/claude-tmux-alan"))
    ok("a hand-written auth file with no header names no account",
       ((f or {}).get("auth"), (f or {}).get("auth_account")), ("token", None))
    rc, f, _, _ = triage("grace", "--facts")
    ok("a unit with no FLEET_AGENT_AUTH line is a login agent", (rc, (f or {}).get("auth")), (0, "login"))
    rc, f, _, _ = triage("bob", "--facts")
    ok("FLEET_AGENT_AUTH=api-key is an api-key agent", (f or {}).get("auth"), "api-key")
    with open(os.path.join(tmp, "units", "user", "claude-agent-carol.service"), "w") as fh:
        fh.write("[Service]\nEnvironment=TMUX_TMPDIR=/run/user/%U/claude-tmux-carol\n")
    rc, f, _, _ = triage("carol", "--facts")
    ok("a TMUX_TMPDIR carrying a specifier other than %t falls back to the template",
       (f or {}).get("tmux_tmpdir"), "/run/user/%d/claude-tmux-carol" % UID)
    rc, f, _, _ = triage("nobody", "--facts")
    ok("an UNREADABLE unit is auth unknown and exit 1 - never login",
       (rc, (f or {}).get("auth"), (f or {}).get("unit_scope")), (1, "unknown", None))
    ok("...and the socket dir falls back to the config template, <uid> substituted",
       (f or {}).get("tmux_tmpdir"), "/run/user/%d/claude-tmux-nobody" % UID)
    m = mutant("system-only", TRIAGE,
               '  if text="$(XDG_RUNTIME_DIR="$user_runtime" "$systemctl_bin" --user cat "$unit" 2>/dev/null)" && [ -n "$text" ]; then',
               '  if false; then')
    rc, f, _, _ = triage("ada", "--facts", script=m)
    control("with the user-manager read removed, ada's unit is not found - the check sees it",
            ((f or {}).get("unit_scope"), (f or {}).get("auth")), (None, "unknown"))
    control("...and --bootstrap-prompt exits 2", triage("ada", "--bootstrap-prompt", script=m)[0], 2)

    # ------------------------------------------- C. accounts and the dead token
    rc, _, out, err = triage("ada", "--accounts")
    rows = dict(l.split("\t")[:2] for l in out.strip().splitlines() if "\t" in l)
    ok("--accounts for a token agent: x current, w leased, y next, z (no token) not next",
       (rc, rows.get("x@example.com"), rows.get("w@example.com"), rows.get("y@example.com"),
        rows.get("z@example.com")), (0, "current", "leased-by-beta", "next", "free"))
    ok("--accounts for an api-key agent: exit 1, it is in no pool", triage("bob", "--accounts")[0], 1)
    rc, t, _, _ = triage("ada", "--pane-file", PANE)
    ok("the measured dead-token pane on a TOKEN agent reads token-invalid",
       ((t or {}).get("state"), (t or {}).get("auth")), ("token-invalid", "token"))
    ok("...and its note forbids /login", "do NOT type /login" in (t or {}).get("note", ""), True)
    rc, t, _, _ = triage("grace", "--pane-file", PANE)
    control("the SAME pane on a login agent reads login-expired (it IS a dead login)",
            (t or {}).get("state"), "login-expired")
    m = mutant("no-token-invalid", TRIAGE,
               '     && { [ "$AUTH" = token ] || [ "$AUTH" = api-key ]; }; then',
               '     && false; then')
    control("with the token-invalid branch removed the token agent reads login-expired - "
            "the check sees the branch", (triage("ada", "--pane-file", PANE, script=m)[1] or {}).get("state"),
            "login-expired")

    # ------------------------------------------------------ B. the token switch
    pkg = os.path.join(tmp, "agents", "ada", "state", "handover.md")
    os.makedirs(os.path.dirname(pkg))
    with open(pkg, "w") as fh:
        fh.write("handover package\n")
    leases_path = os.path.join(state, "leases.json")

    def snapshot():
        return (open(leases_path, "rb").read(), open(ada_auth, "rb").read(), restarts())

    before = snapshot()
    rc, o, _, _ = run(["python3", SWITCH, "ada", "--to", "y@example.com", "--config", CFG])
    ok("no --package and no --no-package is a usage error (exit 2), nothing changed",
       (rc, snapshot() == before), (2, True))
    rc, o, _, _ = run(["python3", SWITCH, "ada", "--to", "y@example.com", "--config", CFG,
                       "--package", pkg + ".missing"])
    ok("a missing handover package is refused (exit 1), nothing changed, no restart",
       (rc, snapshot() == before), (1, True))
    rc, o, _, _ = run(["python3", SWITCH, "grace", "--to", "y@example.com", "--config", CFG,
                       "--no-package"])
    ok("a LOGIN agent is refused (exit 1): it switches in-session",
       (rc, "auth mode is login" in (o or {}).get("reason", ""), snapshot() == before), (1, True, True))
    rc, o, _, _ = run(["python3", SWITCH, "ada", "--to", "w@example.com", "--config", CFG,
                       "--package", pkg])
    ok("an account leased to another agent is refused (exit 1), nothing changed",
       (rc, snapshot() == before), (1, True))

    rc, o, _, _ = run(["python3", SWITCH, "ada", "--to", "y@example.com", "--config", CFG,
                       "--package", pkg, "--why", "Current session switch-floor 91%"])
    ok("the switch: exit 0, restart queued", (rc, (o or {}).get("restart")), (0, "queued"))
    ok("the RIGHT file: ada's auth file is now y's token file, byte for byte",
       open(ada_auth, "rb").read() == open(pool["y@example.com"]["token_file"], "rb").read(), True)
    ok("...mode 0600", stat.S_IMODE(os.stat(ada_auth).st_mode), 0o600)
    ok("the lease moved: y is ada's, x is free, w still beta's",
       sorted((u, l["agent"]) for u, l in json.load(open(leases_path)).items()),
       [("w@example.com", "beta"), ("y@example.com", "ada")])
    ok("ONLY that agent restarted, on the user manager, without blocking",
       restarts(), ["--user restart --no-block claude-agent-ada.service"])
    ok("the handover ledger has the row",
       "| ada | x@example.com | y@example.com | Current session switch-floor 91% |"
       in open(os.path.join(state, "handover.md")).read(), True)
    rc, f, _, _ = triage("ada", "--facts")
    ok("--facts now reads ada as running on y", (f or {}).get("auth_account"), "y@example.com")

    m = mutant("restart-all", SWITCH, '["restart", "--no-block", unit]',
               '["restart", "--no-block", "claude-agent-*.service"]')
    open(FAKE_LOG, "w").close()
    run(["python3", m, "ada", "--to", "x@example.com", "--config", CFG, "--package", pkg])
    control("a copy that restarts every agent unit fails the 'only that agent' check",
            restarts() == ["--user restart --no-block claude-agent-ada.service"], False)
    m = mutant("wrong-file", SWITCH, '"--install-token", facts["auth_file"]',
               '"--install-token", facts["auth_file"] + ".new"')
    run(["python3", m, "ada", "--to", "y@example.com", "--config", CFG, "--package", pkg])
    control("a copy that installs the token beside the auth file fails the 'right file' check",
            open(ada_auth, "rb").read() == open(pool["y@example.com"]["token_file"], "rb").read(), False)

    open(FAKE_LOG, "w").close()
    env = dict(ENV, FAKE_RESTART_RC="1")
    rc, o, _, _ = run(["python3", SWITCH, "alan", "--to", "y@example.com", "--config", CFG,
                       "--no-package"], env=env)
    ok("y is leased to ada, so alan's switch to it is refused before any restart",
       (rc, restarts()), (1, []))
    run(["python3", PICK, "--config", CFG, "--take", "x@example.com", "--agent", "ada"])
    open(FAKE_LOG, "w").close()
    rc, o, _, _ = run(["python3", SWITCH, "alan", "--to", "y@example.com", "--config", CFG,
                       "--no-package"], env=env)
    ok("a failed restart is exit 2 and says the token and lease ALREADY moved",
       (rc, (o or {}).get("restart"), "already" in (o or {}).get("reason", "").lower()
        or "installed and the lease moved" in (o or {}).get("reason", "")), (2, "failed", True))
    ok("...naming the one command a person runs for a SYSTEM unit",
       "sudo " in (o or {}).get("reason", "") and "restart --no-block claude-agent-alan.service"
       in (o or {}).get("reason", ""), True)
    ok("...and it asked the SYSTEM manager, not the user's",
       restarts(), ["restart --no-block claude-agent-alan.service"])

    # ------------------------------------------- D. macOS: the launchd job
    TOK.update({"u@example.com": "sk-ant-oat01-" + "U" * 80, "v@example.com": "sk-ant-oat01-" + "V" * 80})
    for user in ("u@example.com", "v@example.com"):
        rc, _, _, _ = run(["python3", PICK, "--config", CFG, "--register", user, "--token-stdin"],
                          stdin=TOK[user] + "\n")
        control("register %s through pool_pick.py --register" % user, rc, 0)
    pool = {e["username"]: e for e in json.load(open(os.path.join(tmp, "secrets", "pool.json")))}
    control("the fleet's fake launchctl is there", os.access(FAKE_LAUNCHCTL, os.X_OK), True)
    lhome = os.path.join(tmp, "lhome")
    label = "com.agent-fleet-test.session.mia"
    plist = os.path.join(lhome, "Library", "LaunchAgents", label + ".plist")
    os.makedirs(os.path.dirname(plist))
    mia_auth = os.path.join(tmp, "agents", "mia", "secrets", "personal", "claude-auth.env")
    os.makedirs(os.path.dirname(mia_auth), mode=0o700)
    import plistlib
    with open(plist, "wb") as fh:
        plistlib.dump({"Label": label,
                       "ProgramArguments": ["/opt/homebrew/bin/python3", "/x/systemd/agent-session.py",
                                            "--agent", "mia", "--env-file", mia_auth,
                                            "--boot", "You are Mia, just restarted."],
                       "EnvironmentVariables": {"CLAUDE_CONFIG_DIR": os.path.join(tmp, "agents", "mia", ".claude"),
                                                "FLEET_AGENT_AUTH": "token",
                                                "TMUX_TMPDIR": os.path.join(tmp, "run", "claude-tmux-mia")},
                       "KeepAlive": {"SuccessfulExit": False}}, fh)
    lcfg = os.path.join(tmp, "config.launchd.json")
    c = json.load(open(CFG))
    c["fleet"]["systemd_unit"] = "com.agent-fleet-test.session.<agent>"
    with open(lcfg, "w") as fh:
        json.dump(c, fh)
    lcalls = os.path.join(tmp, "launchctl.calls")
    LENV = dict(ENV, FLEET_SERVICE_BACKEND="launchd", HOME=lhome, FLEET_LAUNCHCTL=FAKE_LAUNCHCTL,
                FAKE_LAUNCHD_STATE=os.path.join(tmp, "launchd.json"), FAKE_LAUNCHD_CALLS=lcalls)
    domain = "gui/%d" % UID
    rc, _, _, _ = run([FAKE_LAUNCHCTL, "bootstrap", domain, plist], env=LENV)
    control("mia's job is loaded in the fake launchd before the switch", rc, 0)
    rc, _, _, _ = run(["python3", PICK, "--config", lcfg, "--take", "v@example.com", "--agent", "mia",
                       "--install-token", mia_auth, "--why", "first token"])
    control("mia starts on v, installed through --take --install-token", rc, 0)

    def lcall_lines():
        return [l.strip() for l in open(lcalls)] if os.path.exists(lcalls) else []

    rc, f, _, _ = run(["bash", TRIAGE, "mia", "--config", lcfg, "--facts"], env=LENV)
    ok("launchd --facts: the job's plist, on the user's launchd, auth token from its --env-file",
       (rc, (f or {}).get("unit_manager"), (f or {}).get("unit_scope"), (f or {}).get("auth"),
        (f or {}).get("auth_file"), (f or {}).get("auth_account")),
       (0, "launchd", "user", "token", mia_auth, "v@example.com"))
    open(lcalls, "w").close()
    open(FAKE_LOG, "w").close()
    rc, o, _, _ = run(["python3", SWITCH, "mia", "--to", "u@example.com", "--config", lcfg,
                       "--no-package"], env=LENV)
    ok("launchd switch: exit 0, restart queued", (rc, (o or {}).get("restart")), (0, "queued"))
    ok("launchd switch: mia's auth file is now u's token file",
       open(mia_auth, "rb").read() == open(pool["u@example.com"]["token_file"], "rb").read(), True)
    ok("launchd switch: the job was booted out, then bootstrapped from its plist - and only it",
       [l for l in lcall_lines() if l.split()[0] in ("bootout", "bootstrap", "kickstart")],
       ["bootout %s/%s" % (domain, label), "bootstrap %s %s" % (domain, plist)])
    ok("launchd switch: no systemctl was asked", restarts(), [])
    m = mutant("no-launchd-restart", SWITCH, 'if facts.get("unit_manager") == "launchd":', "if False:")
    open(lcalls, "w").close()
    run(["python3", m, "mia", "--to", "v@example.com", "--config", lcfg, "--no-package"], env=LENV)
    control("a copy without the launchd restart fails the 'booted out and bootstrapped' check",
            [l for l in lcall_lines() if l.split()[0] in ("bootout", "bootstrap")] != [], False)
    run(["python3", PICK, "--config", lcfg, "--take", "u@example.com", "--agent", "mia"])
    run([FAKE_LAUNCHCTL, "disable", "%s/%s" % (domain, label)], env=LENV)
    rc, o, _, _ = run(["python3", SWITCH, "mia", "--to", "v@example.com", "--config", lcfg,
                       "--no-package"], env=LENV)
    reason = (o or {}).get("reason", "")
    ok("launchd: a failed bootstrap is exit 2, says the token moved, and names the bootout and bootstrap",
       (rc, (o or {}).get("restart"), "installed and the lease moved" in reason,
        "launchctl bootout %s/%s; launchctl bootstrap %s %s" % (domain, label, domain, plist) in reason),
       (2, "failed", True, True))

    # ------------------------------------------- no token in any output
    control("the scan looks for the registered tokens",
            all(t in open(pool[u]["token_file"]).read() for u, t in TOK.items()), True)
    control("the scan has outputs to search", len(outputs) >= 25, True)
    leaked = sorted(u for u, t in TOK.items() for o in outputs if t in o)
    ok("no token reaches stdout or stderr on any path", leaked, [])
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("")
if broken:
    print("NO VERDICT - %d control(s) misbehaved: %s" % (len(broken), "; ".join(broken)))
    print("Do NOT read this as a pass. Fix the control, then re-run.")
    sys.exit(3)
print("passed %d, failed %d" % (passed, len(failed)))
sys.exit(0 if not failed else 1)
