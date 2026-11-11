#!/usr/bin/env python3
"""plists.test.py - the [launchd] target blocks of SKILL.md, run as written.

Offline, on Linux and macOS alike: no launchctl, no sudo, no real job, no write
outside a temp directory. THE SUBJECT IS THE TEXT OF SKILL.md, as in
units.test.py, whose block reader, first-line fill and world this file uses
(imported, not copied): each block is found by its fence info string (`bash
agent-plist`, `bash watchdog-plist`), its first line filled with synthetic
values, and run under bash. fleetlib answers the label and the directories under
FLEET_SERVICE_BACKEND=launchd, with FLEET_LAUNCHD_SYSTEM_DIR standing in for
/Library/LaunchDaemons and the run's HOME for ~/Library/LaunchAgents.
`plutil` is the real one where it exists (macOS); elsewhere a stand-in that
lints with plistlib, which reads the same XML.

WHAT EACH CHECK IS FOR
H. The session job (`agent-plist`, from templates/claude-agent.plist.example).
   System form: ONE root command that installs the rendered file root:wheel 644
   into the system directory and bootstraps it in the system domain, and a
   rendered LaunchDaemon whose label is fleetlib's, whose UserName is the agents
   user, which runs systemd/agent-session.py for this agent with its credential
   file and keeps the session socket under <agents-root>/run, no form marker
   left; <agents-root>/run and the session log exist before the start. A full
   login (auth login) is REFUSED in the system form, nothing rendered, because a
   LaunchDaemon has no window server and no login Keychain. User form: a
   LaunchAgent, no UserName, the agents user's own command that installs it
   into ~/Library/LaunchAgents and bootstraps it in its gui domain, no sudo, and
   login allowed (the no-admin form signs in like a Linux agent). In both forms
   the block renders into the agent's config directory and nothing is in
   ~/Library/LaunchAgents until that command runs: launchd loads every plist
   there at the next login, a refused one included. The job runs the fleet's
   interpreter (FLEET_PYTHON), which its boot message's three follower commands
   name too, nothing in it names /opt/homebrew, and its PATH is the block's tmux
   and claude directory, the interpreter's, then the system directories: under
   that PATH a bare tmux and a bare claude are the block's own stand-ins. Without
   claude, or without tmux, on the block's PATH the block prints ONE `NOT
   RENDERED` line naming it, no command, and writes no plist: a session whose
   PATH reaches no claude never starts.
I. The watchdog job (`watchdog-plist`). System form: ONE root command that
   installs the staged config to /etc/agent-fleet/stall-watchdog/<agent>.json
   (root's) and the rendered LaunchDaemon, and bootstraps it; the rendered job
   runs as the agents user, names the session's tmux directory and the root's
   config. User form: the agents user's own two commands, no sudo, a LaunchAgent
   with the staged config. The staged config names the tmux directory, the
   session target and the state directory; it is mode 600 and the state
   directory 700. The job runs the fleet's interpreter (FLEET_PYTHON, which the
   run sets), and its PATH is the block's tmux's directory, the interpreter's,
   then the system directories: under that PATH a bare `tmux` is the block's own
   stand-in, so the job reaches the tmux the block was run with. A hardcoded
   Homebrew PATH reaches the machine's tmux or none, which is the job that ran up
   and blind on a Mac without Homebrew. Without a tmux on the block's PATH the
   block prints ONE `NOT RENDERED: no tmux on PATH` line, no command, and writes
   no plist: a job whose PATH reaches no tmux supervises nothing and looks healthy.

THE CONTROLS - each runs a block with ONE fault planted and must be seen red,
or the run is NO VERDICT (exit 3):
  K1 the template's system: marker misspelled        -> NOT RENDERED, no root command
  K2 a placeholder planted in the session template    -> NOT RENDERED (does not parse)
  K3 an agents root whose socket path macOS cannot bind -> NOT RENDERED
  K4 the system form's login refusal disarmed in the block -> the refusal check
  K5 a placeholder planted in the watchdog example     -> NOT RENDERED, no root command

Exit codes: 0 every check passed and every control went red; 1 a check failed;
3 NO VERDICT.
"""
import importlib.util
import json
import os
import plistlib
import shutil
import stat
import sys
import tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
spec = importlib.util.spec_from_file_location("units_test", os.path.join(HERE, "units.test.py"))
U = importlib.util.module_from_spec(spec)
spec.loader.exec_module(U)

FLEET, AGENT, ME = U.FLEET, U.AGENT, U.ME
SESSION_TEMPLATE = "templates/claude-agent.plist.example"
WD_PLIST = U.WD_DIR + "/installation/agent-stall-watchdog.plist.example"
WD_RENDER = U.WD_DIR + "/installation/render-plist.py"
PREFIX = "com.agent-fleet"
FAKE_PLUTIL = ("#!PYTHON\nimport plistlib, sys\ntry:\n    plistlib.load(open(sys.argv[-1], 'rb'))\n"
               "    print(sys.argv[-1] + ': OK')\nexcept Exception as e:\n    print(sys.argv[-1] + ': ' + str(e))\n"
               "    sys.exit(1)\n")


def fleet_copy(tmp, name, mutate=None):
    """The files the blocks read - the two plist examples, the watchdog config, the
    watchdog's renderer and the job table it reads its interpreter from, and
    lib/fleetlib - with one of them mutated."""
    root = os.path.join(tmp, name)
    for rel in (SESSION_TEMPLATE, WD_PLIST, U.WD_CONFIG, WD_RENDER, "systemd/agent-daemons.py"):
        os.makedirs(os.path.dirname(os.path.join(root, rel)), exist_ok=True)
        shutil.copyfile(os.path.join(FLEET, rel), os.path.join(root, rel))
    shutil.copytree(os.path.join(FLEET, "lib"), os.path.join(root, "lib"),
                    ignore=shutil.ignore_patterns("__pycache__", "*.test.py"))
    if mutate:
        rel, old, new = mutate
        path = os.path.join(root, rel)
        text = open(path, encoding="utf-8").read()
        if old not in text:
            raise U.NoVerdict(f"control {name}: {old!r} is not in {rel}, so the fault cannot be planted")
        open(path, "w", encoding="utf-8").write(text.replace(old, new, 1))
    return root


SYSTEM_PATH = ["/usr/bin", "/bin", "/usr/sbin", "/sbin"]
# The interpreter FLEET_PYTHON names: a wrapper of this test's own Python, in a
# directory of its own (main() writes it). ⚠️ NEVER sys.executable ITSELF: on a host
# whose Python is /usr/bin/python3 that is also a plausible hardcoded default, and a
# block that ignored FLEET_PYTHON for /usr/bin/python3 would pass the interpreter
# check there (measured: that mutant stayed green with sys.executable).
INTERP = None


def fleet_python(tmp):
    d = os.path.join(tmp, "fleet-python", "bin")
    os.makedirs(d)
    path = os.path.join(d, "python3")
    with open(path, "w") as f:
        f.write(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    os.chmod(path, 0o755)
    return path


FAKE_CLAUDE = '#!/bin/sh\necho "9.9.9 (Claude Code stand-in)"\n'


def bin_without(base, missing):
    """A bin directory holding the commands the plist blocks run but NOT `missing`
    (tmux or claude): each a wrapper exec'ing the real one, plutil the stand-in where
    there is none, tmux and claude the stand-ins. Nothing else is on the block's PATH."""
    d = os.path.join(base, "bin-no-" + missing)
    os.makedirs(d, exist_ok=True)
    for tool, target in (("bash", shutil.which("bash")), ("python3", sys.executable), ("id", shutil.which("id")),
                         ("install", shutil.which("install")), ("sed", shutil.which("sed")),
                         ("touch", shutil.which("touch")), ("plutil", shutil.which("plutil"))):
        with open(os.path.join(d, tool), "w") as f:
            if target:
                f.write(f'#!/bin/sh\nexec "{target}" "$@"\n')
            else:
                f.write(FAKE_PLUTIL.replace("PYTHON", sys.executable))
        os.chmod(os.path.join(d, tool), 0o755)
    for tool, body in (("tmux", 'echo "tmux 9.9-stand-in"\n'), ("claude", FAKE_CLAUDE.split("\n", 1)[1])):
        if tool != missing:
            with open(os.path.join(d, tool), "w") as f:
                f.write("#!/bin/sh\n" + body)
            os.chmod(os.path.join(d, tool), 0o755)
    return d


def run(info, fleet, tmp, name, form, auth="token", root_name="agents", edit=None, missing=None):
    sysdir = os.path.join(tmp, "w-" + name, "LaunchDaemons")
    env = {"FLEET_SERVICE_BACKEND": "launchd", "FLEET_LAUNCHD_SYSTEM_DIR": sysdir,
           "FLEET_HOST_CONFIG": os.path.join(FLEET, "tests", "fixtures", "host.json"),
           "FLEET_PYTHON": INTERP, "PYTHONDONTWRITEBYTECODE": "1"}
    base = os.path.join(tmp, "w-" + name)
    os.makedirs(os.path.join(base, "bin"), exist_ok=True)
    if not shutil.which("plutil"):
        with open(os.path.join(base, "bin", "plutil"), "w") as f:
            f.write(FAKE_PLUTIL.replace("PYTHON", sys.executable))
        os.chmod(os.path.join(base, "bin", "plutil"), 0o755)
    # The world's bin holds units.test.py's tmux stand-in; the session job needs a claude too.
    with open(os.path.join(base, "bin", "claude"), "w") as f:
        f.write(FAKE_CLAUDE)
    os.chmod(os.path.join(base, "bin", "claude"), 0o755)
    if missing:
        env["PATH"] = bin_without(base, missing)
    p, base, home, agents = U.run_block(info, fleet, tmp, name, auth=auth, form=form, root_name=root_name,
                                        edit=edit, env_extra=env)
    return p, base, home, agents, sysdir


def load(path):
    with open(path, "rb") as f:
        return plistlib.load(f)


def session_findings(p, home, agents, sysdir, form, auth="token"):
    out = []
    label = f"{PREFIX}.session.{AGENT}"
    lines = [ln for ln in p.stdout.splitlines() if ln.strip()]
    if form == "system" and auth == "login":
        if p.returncode == 0 or not any(ln.startswith("REFUSED:") and "token or an API key" in ln for ln in lines):
            out.append(f"login in the system form was not REFUSED naming the token route: {lines[:3]}")
        if os.path.exists(os.path.join(agents, AGENT, "config", f"{label}.plist")):
            out.append("a refused render still wrote the plist")
        return out
    rendered = os.path.join(agents, AGENT, "config", f"{label}.plist")
    if form == "system":
        dest = os.path.join(sysdir, f"{label}.plist")
        want = f'sudo sh -c "install -m 644 -o root -g wheel {rendered} {dest} && launchctl bootstrap system {dest}"'
    else:
        dest = os.path.join(home, "Library", "LaunchAgents", f"{label}.plist")
        want = f"install -m 644 {rendered} {dest} && launchctl bootstrap gui/{os.getuid()} {dest}"
    if os.path.exists(dest):
        out.append(f"the block itself put {dest} where launchd loads it")
    if p.returncode != 0 or lines != [want]:
        # A refused render is not read further: what is left on disk is not the subject.
        return out + [f"the block exited {p.returncode} and printed {lines[:3]}, not ONE line {want!r}: "
                      f"{p.stderr.strip()[-200:]}"]
    if not os.path.isfile(rendered):
        return out + [f"no rendered plist at {rendered}"]
    if "<!--system:" in open(rendered, encoding="utf-8").read():
        out.append("a system: form marker is left in the rendered plist")
    d = load(rendered)
    argv, env = d.get("ProgramArguments", []), d.get("EnvironmentVariables", {})
    if d.get("Label") != label:
        out.append(f"the label is {d.get('Label')!r}, not {label}")
    if form == "system" and d.get("UserName") != ME:
        out.append(f"UserName is {d.get('UserName')!r}, not {ME}")
    if form == "user" and "UserName" in d:
        out.append("a LaunchAgent carries UserName")
    if not (argv[1:2] and argv[1].endswith("/systemd/agent-session.py") and argv[2:4] == ["--agent", AGENT]
            and argv[4:6] == ["--env-file", os.path.join(agents, AGENT, "secrets", "personal", "claude-auth.env")]):
        out.append(f"it does not run agent-session.py for {AGENT} with its credential file: {argv[:6]}")
    if env.get("TMUX_TMPDIR") != os.path.join(agents, "run", f"claude-tmux-{AGENT}"):
        out.append(f"TMUX_TMPDIR is {env.get('TMUX_TMPDIR')!r}")
    if env.get("FLEET_AGENT_AUTH") != auth or env.get("PYTHONDONTWRITEBYTECODE") != "1":
        out.append(f"FLEET_AGENT_AUTH={env.get('FLEET_AGENT_AUTH')!r}, PYTHONDONTWRITEBYTECODE="
                   f"{env.get('PYTHONDONTWRITEBYTECODE')!r}")
    boot = argv[argv.index("--boot") + 1] if "--boot" in argv else ""
    if argv[:1] != [INTERP] or boot.count(f"{INTERP} ") != 3:
        out.append(f"the job runs {argv[:1]} and its boot message names the interpreter "
                   f"{boot.count(f'{INTERP} ')} time(s), not the fleet's {INTERP} (FLEET_PYTHON) for the job and "
                   f"its three follower commands")
    if "/opt/homebrew" in open(rendered, encoding="utf-8").read():
        out.append("the rendered session job names /opt/homebrew")
    block_bin = os.path.join(os.path.dirname(agents), "bin")
    want_path = ":".join(dict.fromkeys([block_bin, os.path.dirname(INTERP), *SYSTEM_PATH]))
    if env.get("PATH") != want_path:
        out.append(f"the job's PATH is {env.get('PATH')!r}, not {want_path!r}")
    for cmd in ("tmux", "claude"):
        reached = shutil.which(cmd, path=env.get("PATH", ""))
        if reached != os.path.join(block_bin, cmd):
            out.append(f"under the job's PATH a bare {cmd} is {reached!r}, not the block's own "
                       f"{os.path.join(block_bin, cmd)}")
    run_dir = os.path.join(agents, "run")
    if not os.path.isdir(run_dir) or stat.S_IMODE(os.stat(run_dir).st_mode) != 0o755:
        out.append(f"{run_dir} is not a directory of mode 755 before the start")
    if not os.path.isfile(os.path.join(agents, AGENT, "state", "session.log")):
        out.append("the session log does not exist before the start")
    return out


def watchdog_findings(p, home, agents, sysdir, form):
    out = []
    label = f"{PREFIX}.stall-watchdog.{AGENT}"
    rendered = os.path.join(agents, AGENT, "config", f"{label}.plist")
    staged = os.path.join(agents, AGENT, "config", "stall-watchdog.json")
    state = os.path.join(agents, AGENT, "state", "stall-watchdog")
    tmux_dir = os.path.join(agents, "run", f"claude-tmux-{AGENT}")
    lines = [ln for ln in p.stdout.splitlines() if ln.strip()]
    if p.returncode != 0 or len(lines) != 1:
        return out + [f"the block exited {p.returncode} and printed {len(lines)} line(s), not ONE: {lines[:3]}"]
    if form == "system":
        cfg, dest = f"/etc/agent-fleet/stall-watchdog/{AGENT}.json", os.path.join(sysdir, f"{label}.plist")
        want = (f'sudo sh -c "install -d -m 755 /etc/agent-fleet/stall-watchdog && install -m 644 {staged} {cfg} '
                f'&& install -m 644 -o root -g wheel {rendered} {dest} && launchctl bootstrap system {dest}"')
    else:
        cfg, dest = staged, os.path.join(home, "Library", "LaunchAgents", f"{label}.plist")
        want = f"install -m 644 {rendered} {dest} && launchctl bootstrap gui/{os.getuid()} {dest}"
    if lines[0] != want:
        out.append(f"the command is {lines[0]!r}, not {want!r}")
    if not os.path.isfile(rendered):
        return out + [f"no rendered plist at {rendered}"]
    d = load(rendered)
    env = d.get("EnvironmentVariables", {})
    if d.get("Label") != label or env.get("TMUX_TMPDIR") != tmux_dir or env.get("STALL_WATCHDOG_CONFIG") != cfg:
        out.append(f"the job names {d.get('Label')}, {env.get('TMUX_TMPDIR')}, {env.get('STALL_WATCHDOG_CONFIG')}")
    if (d.get("UserName") == ME) != (form == "system"):
        out.append(f"UserName is {d.get('UserName')!r} in the {form} form")
    argv = d.get("ProgramArguments", [])
    if argv[:1] != [INTERP]:
        out.append(f"the job runs {argv[:1]}, not the fleet's interpreter {INTERP} (FLEET_PYTHON)")
    block_bin = os.path.join(os.path.dirname(agents), "bin")
    want_path = ":".join(dict.fromkeys([block_bin, os.path.dirname(INTERP), *SYSTEM_PATH]))
    if env.get("PATH") != want_path:
        out.append(f"the job's PATH is {env.get('PATH')!r}, not {want_path!r}")
    reached = shutil.which("tmux", path=env.get("PATH", ""))
    if reached != os.path.join(block_bin, "tmux"):
        out.append(f"under the job's PATH a bare tmux is {reached!r}, not the block's own "
                   f"{os.path.join(block_bin, 'tmux')}")
    c = json.load(open(staged, encoding="utf-8"))
    if (c["tmux"]["tmpdir"], c["tmux"]["target"], c["state"]["dir"]) != (tmux_dir, f"claude-{AGENT}:0", state):
        out.append(f"the staged config names {c['tmux']}, {c['state']['dir']}")
    if stat.S_IMODE(os.stat(staged).st_mode) != 0o600 or stat.S_IMODE(os.stat(state).st_mode) != 0o700:
        out.append("the staged config is not 600 or the state directory not 700")
    return out


def no_command_findings(p, agents, job="stall-watchdog", cmd="tmux"):
    label = f"{PREFIX}.{job}.{AGENT}"
    rendered = os.path.join(agents, AGENT, "config", f"{label}.plist")
    lines = [ln for ln in p.stdout.splitlines() if ln.strip()]
    out = []
    if p.returncode != 1 or len(lines) != 1 or not lines[0].startswith(f"NOT RENDERED: no {cmd} on PATH"):
        out.append(f"with no {cmd} on its PATH the block exited {p.returncode} and printed {lines[:3]}, "
                   f"not ONE 'NOT RENDERED: no {cmd} on PATH' line")
    if any("launchctl" in ln for ln in lines):
        out.append(f"with no {cmd} on its PATH the block printed a command: {lines[:3]}")
    if os.path.exists(rendered):
        out.append(f"with no {cmd} on its PATH the block wrote {rendered}")
    return out


def main():
    # Under /tmp, never $TMPDIR: the block refuses a session socket of 104 bytes or
    # more, and macOS's $TMPDIR (/var/folders/<2>/<28>/T/) alone puts every
    # world's socket past that, so H would read NOT RENDERED on the one system the
    # block is for. K3 plants the long root on purpose.
    global INTERP
    tmp = tempfile.mkdtemp(prefix="fpl-", dir="/tmp")
    INTERP = fleet_python(tmp)
    green = []
    try:
        print("H. the session job, from the agent-plist block")
        for form, auth in (("system", "token"), ("system", "login"), ("user", "token"), ("user", "login")):
            p, base, home, agents, sysdir = run("agent-plist", FLEET, tmp, f"s-{form}-{auth}", form, auth)
            found = session_findings(p, home, agents, sysdir, form, auth)
            for f in found:
                U.check(False, f"H {form} {auth}: {f}")
            U.check(not found, f"H {form} form, {auth}: " + (
                "REFUSED, nothing rendered" if (form, auth) == ("system", "login") else
                "a LaunchDaemon running as the agents user, ONE root command" if form == "system" else
                "a LaunchAgent, no UserName, the agents user's own command")
                + ("" if (form, auth) == ("system", "login") else
                   ", the fleet's interpreter, a PATH that reaches the block's tmux and claude"))
        for cmd in ("claude", "tmux"):
            p, base, home, agents, sysdir = run("agent-plist", FLEET, tmp, f"s-no-{cmd}", "system", missing=cmd)
            found = no_command_findings(p, agents, "session", cmd)
            for f in found:
                U.check(False, f"H no {cmd}: {f}")
            U.check(not found, f"H system form, no {cmd} on the block's PATH: NOT RENDERED naming {cmd}, "
                               f"no command, no plist")
        print("I. the watchdog job, from the watchdog-plist block")
        for form in ("system", "user"):
            p, base, home, agents, sysdir = run("watchdog-plist", FLEET, tmp, f"w-{form}", form)
            found = watchdog_findings(p, home, agents, sysdir, form)
            for f in found:
                U.check(False, f"I {form}: {f}")
            U.check(not found, f"I {form} form: " + ("ONE root command, root's config, a LaunchDaemon as the agents user"
                                                     if form == "system" else "the agents user's own commands, a LaunchAgent")
                    + ", the fleet's interpreter, a PATH that reaches the block's tmux")
        p, base, home, agents, sysdir = run("watchdog-plist", FLEET, tmp, "w-no-tmux", "system", missing="tmux")
        found = no_command_findings(p, agents)
        for f in found:
            U.check(False, f"I no tmux: {f}")
        U.check(not found, "I system form, no tmux on the block's PATH: NOT RENDERED naming tmux, no command, "
                           "no plist")
        print("K. controls - each must be seen red, or there is no verdict")
        controls = [
            ("K1", "agent-plist", "system", "token", dict(mutate=(SESSION_TEMPLATE, "<!--system: ", "<!--sytem: ")),
             "lost its UserName"),
            ("K2", "agent-plist", "user", "token", dict(mutate=(SESSION_TEMPLATE, "<key>RunAtLoad</key>",
                                                                "<zz-planted/><zz-left><key>RunAtLoad</key>")),
             "does not parse"),
            ("K3", "agent-plist", "user", "token", dict(root_name="a" * 60), "socket"),
            ("K4", "agent-plist", "system", "login",
             dict(edit=('[ "$auth" != login ] || {', '[ "$auth" = "$auth" ] || {')), "not REFUSED"),
            ("K5", "watchdog-plist", "system", "token", dict(mutate=(WD_PLIST, "<key>RunAtLoad</key>",
                                                                     "<zz-left><key>RunAtLoad</key>")),
             "does not parse"),
        ]
        for cid, info, form, auth, how, needle in controls:
            fleet = fleet_copy(tmp, "fleet-" + cid, how.get("mutate")) if "mutate" in how else FLEET
            p, base, home, agents, sysdir = run(info, fleet, tmp, cid, form, auth,
                                                root_name=how.get("root_name", "agents"), edit=how.get("edit"))
            found = (session_findings(p, home, agents, sysdir, form, auth) if info == "agent-plist"
                     else watchdog_findings(p, home, agents, sysdir, form))
            hit = [f for f in found if needle in f]
            print(f"{'red   ' if hit else 'GREEN '}{cid}: {hit[0][:160] if hit else found or 'no finding'}")
            if not hit:
                green.append(cid)
    except U.NoVerdict as e:
        print(f"NO VERDICT: {e}")
        return 3
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    if green:
        print(f"NO VERDICT: control(s) {', '.join(green)} stayed green: the checks cannot see that fault")
        return 3
    if U.FAILS:
        print(f"FAILED: {len(U.FAILS)} check(s)")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
