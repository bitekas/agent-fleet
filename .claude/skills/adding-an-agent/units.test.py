#!/usr/bin/env python3
"""units.test.py - the six target blocks of SKILL.md, run as written.

Offline: no systemctl, no sudo, no tmux server, no claude, no real unit, no write
outside a temp directory. Prints one line per check and ALL CHECKS PASSED, or
names every failure.

THE SUBJECT IS THE TEXT OF SKILL.md. Each block is found by its fence info
string (`bash auth-file`, `bash take-lease`, `bash first-run`, `bash
status-line`, `bash agent-unit`, `bash watchdog-unit`), its FIRST
line is filled with synthetic values exactly as the skill tells Claude to fill
it, and the block runs under bash, as `ssh <target> bash -s` runs it. A copy of
the commands kept here would stay green while the skill's own lines drifted;
reading the skill is what makes this test about the skill. A first line that
still holds a placeholder after the fill is a hand-filled value this test does
not know: NO VERDICT, never a guess.

WHAT EACH CHECK IS FOR

A. The agent unit (templates/claude-agent.service.example through the
   `agent-unit` block), in both forms (`form=system` and `form=user`). The
   block's own control grep prints a count above 0 and its second grep prints
   nothing - no placeholder and no `#system: `/`#user: ` form marker left;
   `systemd-analyze verify` exits 0, in the scope of the form; TMUX_TMPDIR,
   RuntimeDirectory and the boot handshake's T= all name
   %t/claude-tmux-<agent>, so the session's socket directory follows whichever
   service manager runs the unit (a literal path in one of them is a session the
   watchdog and the handshake cannot reach); the user form installs to
   default.target with no User= line and prints no root command, and the system
   form carries exactly User=<the agents user> and WantedBy=multi-user.target
   and prints ONE `sudo sh -c` that installs the rendered file to
   /etc/systemd/system, reloads and starts it with --no-block; it records the
   sign-in mode and reads the credential file, required (no `-`), and sets
   PYTHONDONTWRITEBYTECODE=1 for the whole session; and the boot
   message holds none of the characters the template forbids in it. `verify`
   sees an ODD number of apostrophes and passes an even number, so the message
   check is the only thing here that sees the even case.
B. The watchdog unit (the stall-watchdog example through the `watchdog-unit`
   block), in both forms. It prints EXACTLY ONE line, and that line is ONE `sudo
   sh -c` whose commands are, in the system form, the install of the staged
   config to /etc/agent-fleet/stall-watchdog/<agent>.json (root-owned, where the
   agents user cannot change it), and in both the install of the rendered file,
   `daemon-reload` and `enable --now`, with the staged config and the rendered
   file the only paths outside /etc/systemd/system and /etc/agent-fleet; the
   rendered unit has no placeholder, names the session's tmux directory (the
   system form's /run/claude-tmux-<agent>, the user form's
   /run/user/<uid>/claude-tmux-<agent>) in TMUX_TMPDIR and ReadWritePaths and
   the form's config path in STALL_WATCHDOG_CONFIG, and passes `systemd-analyze
   verify` as a system unit; the staged config is mode 600 and names the same
   directory, the session target and the state directory; the state directory
   exists, mode 700.
D. The first run (`first-run` block), against a fake tmux that records what it
   is asked to start. The session is started on its own socket, in the agent's
   checkout, with exactly the unit's environment: `env -i`, the agent's config
   directory, the credential file sourced, `claude` through `bash -l` with the
   unit's flags. For `token` an onboarding-complete .claude.json is seeded, for
   `login` none, and an existing one is never overwritten.
E. The credential file (`auth-file` block), read the way the agent-health and
   agent-revive skills read it: `pool_pick.py --read-auth-file` must name the
   auth mode and the account from the header, and the shell's `set -a; .`, what
   the first run does, must set the variable to exactly the handed-over value -
   with or without a trailing newline, as safe-box and a paste each leave it.
   The file is mode 600 and the bare copy is removed; `login` gets an empty file;
   a token with no account is refused and nothing is written. Reading the file
   through F15's own reader is the coupling: a header this block writes and that
   reader cannot parse reds here, not at the first account switch.
G. The lease (`take-lease` block), against a pool fixture pool_pick.py reads
   through AGENT_REVIVE_CONFIG. Two agents and ONE account, held by grace: the
   block passes --share, and the lease names both, the agent's credential file
   is the account's token file (header and mode 600), and the block prints
   "2 agents share account x". Two accounts, one free: the free one is taken,
   unshared, and nothing is printed about sharing. Without --share the take of
   a held account is refused, which control C16 plants in the block's own text.
F. The status line (`status-line` block): the token agent's settings get
   usage_statusline.py as their statusLine, every other key kept, an older status
   line replaced, a missing file created, and a file that is not valid JSON left
   exactly as it was.

THE CONTROLS, AND WHY A GREEN ONE IS NO VERDICT. Each control runs the same
block with ONE fault planted - in a copy of the fleet files, in the block's own
text, or in the agents root it is given - and the checks must name that fault.
A control that comes back with no finding means the check cannot see that
fault, so the run exits 3 (NO VERDICT) instead of reporting a pass it cannot
back:
  C1 a placeholder planted in the agent template       -> the block's grep prints it
  C2 one apostrophe in the boot message                 -> verify exits non-zero
  C3 two apostrophes in the boot message (verify-clean)  -> the message check
  C4 a literal TMUX_TMPDIR instead of %t                -> the %t check
  C5 the watchdog example's TMUX_TMPDIR a literal path  -> NOT RENDERED, no root command
     (the system form's own, which the user form must not take)
  C6 a placeholder planted in the watchdog example      -> NOT RENDERED, no root command
  C7 an agents root holding a space                     -> NOT RENDERED, no root command
  C8 the first run started without `env -i`             -> the command check
  C9 the credential file's account line misspelled      -> the header pool_pick.py reads
  C10 the status-line merge starting from an empty dict -> the kept-keys check
  C11 the system form's User= marker misspelled           -> NOT RENDERED, no root command
  C12 the user form's WantedBy= marker dropped            -> NOT RENDERED (two WantedBy=)
  C13 form= neither system nor user                        -> nothing rendered
  C14 the watchdog example's config variable renamed       -> NOT RENDERED, no root command
  C15 the system form's root command without the config    -> the root-command check
  C16 the take-lease block without its --share             -> the shared-lease check

`systemd-analyze verify` checks that every Exec command exists. A host without
/usr/bin/tmux cannot pass the real agent unit for that reason alone, so there
(and only there) the verify reads a copy whose tmux path names a stub, the
rendered unit itself is asserted to name /usr/bin/tmux, and the line printed
says which form was verified. Every other line verify reads is the rendered one.

Exit codes: 0 every check passed and every control went red; 1 a check failed;
3 NO VERDICT (a control stayed green, a block is missing or ambiguous, a first
line kept a placeholder, or systemd-analyze is not installed).
"""
import json
import os
import pwd
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
FLEET = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
SKILL = os.path.join(HERE, "SKILL.md")
AGENT_TEMPLATE = "templates/claude-agent.service.example"
WD_DIR = ".claude/skills/stall-watchdog"
WD_EXAMPLE = WD_DIR + "/installation/agent-stall-watchdog.service.example"
WD_CONFIG = WD_DIR + "/config.example.json"
PLACEHOLDER = re.compile(r"<[A-Za-z][A-Za-z0-9 -]*>")
UID = os.getuid()
AGENT, DISPLAY, PROJECT = "ada", "Ada Lovelace", "project"
JOB, VAR = "slack-watch", "SLACK_WATCH_CONFIG"
FORBIDDEN = "'$%\\`"     # the boot-message characters the agent template forbids
# A tmux stand-in: one JSON line per call, the argv it was handed. A call without
# FAKE_TMUX_LOG is the stall watchdog's renderer proving `tmux -V` runs under an
# environment of ONLY the job's PATH (plists.test.py): it logs nowhere and exits 0.
ME = pwd.getpwuid(os.getuid()).pw_name
FAKE_TMUX = "#!/usr/bin/env python3\nimport json, os, sys\nwith open(os.environ.get('FAKE_TMUX_LOG', os.devnull), 'a') as f:\n    f.write(json.dumps(sys.argv[1:]) + '\\n')\n"

FAILS = []


class NoVerdict(Exception):
    pass


def check(ok, what):
    print(("ok    " if ok else "FAIL  ") + what)
    if not ok:
        FAILS.append(what)


def block(info):
    """The body of the one fenced block in SKILL.md whose info string is `bash <info>`."""
    text = open(SKILL, encoding="utf-8").read()
    found = re.findall(r"^( *)```bash " + re.escape(info) + r"\n(.*?)^\1```", text, re.M | re.S)
    if len(found) != 1:
        raise NoVerdict(f"SKILL.md has {len(found)} blocks fenced `bash {info}`; expected exactly one")
    indent, body = found[0]
    return "\n".join(line[len(indent):] for line in body.splitlines()) + "\n"


def fill(body, values):
    """Fill the first line only, as the skill says; the rest runs as written."""
    first, rest = body.split("\n", 1)
    for key, value in values.items():
        first = first.replace(f"<{key}>", value)
    if PLACEHOLDER.search(first):
        raise NoVerdict(f"the block's first line still holds {PLACEHOLDER.findall(first)} after the "
                        f"fill: the skill asks for a value this test does not know")
    return first + "\n" + rest


def fleet_copy(tmp, name, mutate=None):
    """A fleet tree holding the three files the blocks read, one of them mutated."""
    root = os.path.join(tmp, name)
    for rel in (AGENT_TEMPLATE, WD_EXAMPLE, WD_CONFIG):
        os.makedirs(os.path.dirname(os.path.join(root, rel)), exist_ok=True)
        shutil.copyfile(os.path.join(FLEET, rel), os.path.join(root, rel))
    if mutate:
        rel, old, new = mutate
        path = os.path.join(root, rel)
        text = open(path, encoding="utf-8").read()
        if old not in text:
            raise NoVerdict(f"control {name}: {old!r} is not in {rel}, so the fault cannot be planted")
        open(path, "w", encoding="utf-8").write(text.replace(old, new, 1))
    return root


def world(tmp, name, root_name="agents"):
    """A home, an agents root and a fake tmux of its own for one run."""
    base = os.path.join(tmp, "w-" + name)
    home, agents = os.path.join(base, "home"), os.path.join(base, root_name)
    for d in (home, os.path.join(agents, AGENT, "config"), os.path.join(agents, AGENT, PROJECT),
              os.path.join(agents, AGENT, ".claude"), os.path.join(agents, AGENT, "secrets", "personal"),
              os.path.join(base, "xdg"), os.path.join(base, "bin")):
        os.makedirs(d, exist_ok=True)
    os.chmod(os.path.join(base, "xdg"), 0o700)
    with open(os.path.join(base, "bin", "tmux"), "w") as f:
        f.write(FAKE_TMUX.replace("/usr/bin/env python3", sys.executable, 1))
    os.chmod(os.path.join(base, "bin", "tmux"), 0o755)
    return base, home, agents


def run_block(info, fleet, tmp, name, auth="token", root_name="agents", edit=None, seed=None,
              account="", files=None, form="user", env_extra=None):
    base, home, agents = world(tmp, name, root_name)
    if seed is not None:
        with open(os.path.join(agents, AGENT, ".claude", ".claude.json"), "w") as f:
            f.write(seed)
    for rel, text in (files or {}).items():
        with open(os.path.join(agents, AGENT, rel), "w") as f:
            f.write(text)
    body = block(info)
    if edit:
        old, new = edit
        if old not in body:
            raise NoVerdict(f"control {name}: {old!r} is not in the {info} block, so the fault cannot be planted")
        body = body.replace(old, new, 1)
    body = fill(body, {"agent-name": AGENT, "Agent-Name": DISPLAY, "agents-root": agents,
                       "fleet": fleet, "project-dir": PROJECT, "watch-job": JOB,
                       "watch-config-env": VAR, "auth-mode": auth, "account": account, "unit-form": form,
                       "home": os.path.join(agents, AGENT)})
    env = {"PATH": os.path.join(base, "bin") + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
           "HOME": home, "LANG": "C.UTF-8", "FAKE_TMUX_LOG": os.path.join(base, "tmux.log")}
    env.update(env_extra or {})
    p = subprocess.run(["bash", "-c", body], cwd=base, env=env, capture_output=True, text=True,
                       stdin=subprocess.DEVNULL, timeout=120)
    return p, base, home, agents


def verify(path, base, user):
    argv = ["systemd-analyze"] + (["--user"] if user else []) + ["verify", path]
    env = dict(os.environ, XDG_RUNTIME_DIR=os.path.join(base, "xdg"))
    p = subprocess.run(argv, env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                       timeout=120)
    # The host's own units can warn about themselves; keep the lines about ours.
    noise = [ln for ln in (p.stdout + p.stderr).splitlines() if os.path.basename(path) in ln]
    return p.returncode, noise


def boot_message(text):
    m = re.search(r'send-keys -t \$S "([^"]*)"', text)
    return m.group(1) if m else None


# ------------------------------------------------------------------ A. agent unit

def agent_findings(p, base, home, agents, form="user"):
    """Every way the agent-unit block's result is wrong, as named strings."""
    out = []
    lines = p.stdout.splitlines()
    if form == "user":
        unit = os.path.join(home, ".config/systemd/user", f"claude-agent-{AGENT}.service")
    else:
        unit = os.path.join(agents, AGENT, "config", f"claude-agent-{AGENT}.service")
    sudo = [ln for ln in lines if ln.startswith("sudo ")]
    want = [] if form == "user" else [
        f'sudo sh -c "install -m 644 {unit} /etc/systemd/system/claude-agent-{AGENT}.service && '
        f'systemctl daemon-reload && systemctl enable --now --no-block claude-agent-{AGENT}.service"']
    if sudo != want:
        out.append(f"the {form} form's root command is not ONE install + daemon-reload + enable --now "
                   f"--no-block of the rendered unit: {sudo or [ln for ln in lines if 'NOT RENDERED' in ln]}")
    if p.returncode != 0:
        out.append(f"the block exited {p.returncode}: {p.stderr.strip()[-300:]}")
    count = next((int(ln) for ln in lines if ln.strip().isdigit()), None)
    if not count:
        out.append(f"the block's control grep printed {count!r}, not a count above 0: the pattern is blind")
    left = [ln for ln in lines if re.match(r"\d+:", ln)]
    if left:
        out.append(f"placeholder left in the rendered unit: {left[:3]}")
    if f"rendered {unit}" not in lines:
        out.append(f"the block did not print 'rendered {unit}'")
    if not os.path.isfile(unit):
        return out + [f"no rendered unit at {unit}"]
    text = open(unit, encoding="utf-8").read()
    subject = unit
    if "ExecStart=/usr/bin/tmux " not in text or "ExecStop=/usr/bin/tmux " not in text:
        out.append("the rendered unit does not start and stop the session with /usr/bin/tmux")
    # UNITS_TEST_TMUX names the binary whose absence takes the stub path, so the
    # path a CI runner takes can be run on a host that has tmux.
    if not os.access(os.environ.get("UNITS_TEST_TMUX", "/usr/bin/tmux"), os.X_OK):
        stub = os.path.join(base, "stub-tmux")
        with open(stub, "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(stub, 0o755)
        subject = os.path.join(base, f"claude-agent-{AGENT}.service")
        with open(subject, "w", encoding="utf-8") as f:
            f.write(text.replace("/usr/bin/tmux", stub))
        print(f"      (no /usr/bin/tmux on this host: verify reads a copy with {stub} in its place)")
    rc, noise = verify(subject, base, user=(form == "user"))
    if rc != 0:
        out.append(f"systemd-analyze verify exited {rc} ({form} scope): {noise[:4]}")
    want = f"%t/claude-tmux-{AGENT}"
    if f"\nEnvironment=TMUX_TMPDIR={want}\n" not in text:
        out.append(f"TMUX_TMPDIR is not {want}")
    if f"\nRuntimeDirectory=claude-tmux-{AGENT}\n" not in text:
        out.append(f"RuntimeDirectory is not claude-tmux-{AGENT}")
    if f"bash -c 'T={want};" not in text:
        out.append(f"the boot handshake's T= is not {want}")
    wanted = re.findall(r"^WantedBy=(.*)$", text, re.M)
    users = re.findall(r"^User=(.*)$", text, re.M)
    if form == "user" and (wanted != ["default.target"] or users):
        out.append(f"WantedBy={wanted}, User={users}: not a user unit (default.target, no User=)")
    if form == "system" and (wanted != ["multi-user.target"] or users != [ME]):
        out.append(f"WantedBy={wanted}, User={users}: not the system form (multi-user.target, User={ME})")
    if re.search(r"^#(user|system): ", text, re.M):
        out.append("a #user: or #system: form marker is left in the rendered unit")
    if not re.search(r"^Environment=FLEET_AGENT_AUTH=token$", text, re.M):
        out.append("no Environment=FLEET_AGENT_AUTH=token line: the sign-in mode is not recorded")
    if not re.search(r"^Environment=PYTHONDONTWRITEBYTECODE=1$", text, re.M):
        out.append("no Environment=PYTHONDONTWRITEBYTECODE=1 line: the session's Python may write "
                   "bytecode into the read-only fleet checkout")
    cred = os.path.join(agents, AGENT, "secrets", "personal", "claude-auth.env")
    if not re.search("^EnvironmentFile=" + re.escape(cred) + "$", text, re.M):
        out.append(f"no required EnvironmentFile={cred} line")
    msg = boot_message(text)
    if msg is None:
        out.append("no boot message (send-keys -t $S \"...\") in ExecStartPost")
    else:
        if not msg.startswith(f"You are {DISPLAY},") or not msg.endswith("your charter names."):
            out.append(f"the boot message is not whole: {msg[:40]!r} ... {msg[-30:]!r}")
        bad = sorted(set(c for c in msg if c in FORBIDDEN))
        if bad:
            out.append(f"the boot message holds forbidden character(s) {bad}")
    return out


# --------------------------------------------------------------- B. watchdog unit

def watchdog_findings(p, base, agents, form="user"):
    out = []
    name = f"claude-agent-{AGENT}-stall-watchdog.service"
    rendered = os.path.join(agents, AGENT, "config", name)
    cfg = os.path.join(agents, AGENT, "config", "stall-watchdog.json")
    state = os.path.join(agents, AGENT, "state", "stall-watchdog")
    if form == "user":
        tmux_dir, named, put = f"/run/user/{UID}/claude-tmux-{AGENT}", cfg, []
    else:
        named = f"/etc/agent-fleet/stall-watchdog/{AGENT}.json"
        tmux_dir, put = f"/run/claude-tmux-{AGENT}", [["install", "-D", "-m", "644", cfg, named]]
    if p.returncode != 0:
        out.append(f"the block exited {p.returncode}: {p.stderr.strip()[-300:]}")
    lines = [ln for ln in p.stdout.splitlines() if ln.strip()]
    sudo = [ln for ln in lines if ln.startswith("sudo ")]
    if lines != sudo or len(sudo) != 1:
        return out + [f"the block printed {len(lines)} line(s), {len(sudo)} of them root commands, not ONE "
                      f"sudo line: {lines[:3]}"]
    outer = shlex.split(sudo[0])
    if outer[:3] != ["sudo", "sh", "-c"] or len(outer) != 4:
        return out + [f"the root command is not ONE `sudo sh -c \"...\"`: {sudo[0]}"]
    parts = [shlex.split(part) for part in outer[3].split(" && ")]
    want = put + [["install", "-m", "644", rendered, f"/etc/systemd/system/{name}"],
                  ["systemctl", "daemon-reload"],
                  ["systemctl", "enable", "--now", name]]
    if parts != want:
        out.append(f"the root command is not {'the config install + ' if put else ''}install + daemon-reload + "
                   f"enable --now of the rendered file: {sudo[0]}")
    paths = [t for part in parts for t in part
             if t.startswith("/") and not t.startswith(("/etc/systemd/system/", "/etc/agent-fleet/"))]
    if paths != ([cfg] if put else []) + [rendered]:
        out.append(f"the root command names {paths}, not only the staged config and the rendered file")
    if not os.path.isfile(rendered):
        return out + [f"no rendered unit at {rendered}"]
    text = open(rendered, encoding="utf-8").read()
    left = PLACEHOLDER.findall(text)
    if left:
        out.append(f"placeholder left in the rendered watchdog unit: {left[:3]}")
    for line in (f"Environment=TMUX_TMPDIR={tmux_dir}", f"ReadWritePaths={tmux_dir}",
                 f"ReadWritePaths={state}", f"Environment=STALL_WATCHDOG_CONFIG={named}"):
        if not re.search("^" + re.escape(line) + "$", text, re.M):
            out.append(f"the rendered watchdog unit has no line {line}")
    rc, noise = verify(rendered, base, user=False)
    if rc != 0:
        out.append(f"systemd-analyze verify exited {rc}: {noise[:4]}")
    try:
        c = json.load(open(cfg, encoding="utf-8"))
        got = (c["tmux"]["tmpdir"], c["tmux"]["target"], c["state"]["dir"])
        if got != (tmux_dir, f"claude-{AGENT}:0", state):
            out.append(f"the config names {got}, not {(tmux_dir, f'claude-{AGENT}:0', state)}")
        if stat.S_IMODE(os.stat(cfg).st_mode) != 0o600:
            out.append(f"the config is mode {oct(stat.S_IMODE(os.stat(cfg).st_mode))}, not 0o600")
    except (OSError, ValueError, KeyError) as e:
        out.append(f"the config is unreadable: {e}")
    if not os.path.isdir(state) or stat.S_IMODE(os.stat(state).st_mode) != 0o700:
        out.append(f"the state directory {state} is missing or not mode 700")
    return out


# ---------------------------------------------------------------- D. first run

def first_run_findings(p, base, home, agents, auth, seeded=None):
    out = []
    if p.returncode != 0:
        out.append(f"the block exited {p.returncode}: {p.stderr.strip()[-300:]}")
    adir = os.path.join(agents, AGENT)
    try:
        calls = [json.loads(ln) for ln in open(os.path.join(base, "tmux.log"))]
    except OSError:
        calls = []
    cmd = (f"env -i HOME={home} TERM=tmux-256color PATH=/usr/bin:/bin CLAUDE_CONFIG_DIR={adir}/.claude "
           f"/bin/bash -lc 'set -a; . {adir}/secrets/personal/claude-auth.env; set +a; "
           f"claude --dangerously-skip-permissions --name {AGENT} --agent {AGENT}'")
    want = [["-L", f"add-{AGENT}", "new-session", "-d", "-s", "signin", "-c", f"{adir}/{PROJECT}", cmd]]
    if calls != want:
        out.append(f"the first run started {calls}, not the unit's environment and flags: {want}")
    cj = os.path.join(adir, ".claude", ".claude.json")
    have = open(cj).read() if os.path.exists(cj) else None
    expect = seeded if seeded is not None else (
        '{"hasCompletedOnboarding": true}\n' if auth == "token" else None)
    if have != expect:
        out.append(f"{auth}: .claude.json is {have!r}, expected {expect!r}")
    return out


# ----------------------------------------------------------- E. the credential file

POOL_PICK = os.path.join(FLEET, ".claude", "skills", "agent-health", "pool_pick.py")
STATUSLINE = os.path.join(FLEET, ".claude", "skills", "agent-health", "usage_statusline.py")
VALUE = "sk-ant-oat01-stand-in-not-a-token"


def auth_file_findings(p, agents, auth, account, value):
    """The auth-file block's result, read the way /agent-health and /agent-revive
    read it: pool_pick.py --read-auth-file for the header, and the shell's own
    `set -a; .` (what the first run does) for the variable."""
    out = []
    personal = os.path.join(agents, AGENT, "secrets", "personal")
    dst, src = os.path.join(personal, "claude-auth.env"), os.path.join(personal, "claude-credential")
    if p.returncode != 0:
        out.append(f"the block exited {p.returncode}: {p.stderr.strip()[-300:]}")
    if "NOT WRITTEN" in p.stdout:
        return out + [f"{auth}: the block refused: {p.stdout.strip()[:200]}"]
    if not os.path.isfile(dst):
        return out + [f"{auth}: no credential file at {dst}"]
    mode = stat.S_IMODE(os.stat(dst).st_mode)
    if mode != 0o600:
        out.append(f"{auth}: the credential file is mode {oct(mode)}, not 0o600")
    if auth == "login":
        if os.path.getsize(dst) != 0:
            out.append("login: the credential file is not empty")
        return out
    if os.path.exists(src):
        out.append(f"{auth}: the handed-over copy {src} was not removed")
    r = subprocess.run([sys.executable, POOL_PICK, "--read-auth-file", dst], capture_output=True,
                       text=True, stdin=subprocess.DEVNULL, timeout=60)
    try:
        head = json.loads(r.stdout)
    except ValueError:
        head = None
    want = {"file": dst, "auth": auth, "account": account or None}
    if r.returncode != 0 or head != want:
        out.append(f"{auth}: pool_pick.py --read-auth-file reads {head} (exit {r.returncode}), not {want}")
    var = "CLAUDE_CODE_OAUTH_TOKEN" if auth == "token" else "ANTHROPIC_API_KEY"
    s = subprocess.run(["bash", "-c", f'set -a; . "$1"; set +a; printf %s "${{{var}}}"', "x", dst],
                       capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
    if s.stdout != value:
        out.append(f"{auth}: sourcing the file does not set {var} to the handed-over value")
    return out


# ------------------------------------------------------------------ G. the lease

TOKEN = "sk-ant-oat01-stand-in-not-a-token"


def lease_world(tmp, name, accounts, leases):
    """A pool of `accounts` (each with a token file), its leases and an empty
    ledger, and the environment that points pool_pick.py at them."""
    sys.path.insert(0, os.path.dirname(POOL_PICK))
    import parse_usage  # noqa: E402 - agent-health's own ledger preamble
    d = os.path.join(tmp, "pool-" + name)
    os.makedirs(d)
    pool = []
    for a in accounts:
        tf = os.path.join(d, a + ".token")
        with open(tf, "w") as f:
            f.write(f"# fleet-auth: token\n# fleet-account: {a}\nCLAUDE_CODE_OAUTH_TOKEN={TOKEN}\n")
        os.chmod(tf, 0o600)
        pool.append({"username": a, "token_file": tf})
    for f, v in (("pool.json", pool), ("leases.json", leases)):
        with open(os.path.join(d, f), "w") as fh:
            json.dump(v, fh)
    with open(os.path.join(d, "agents.md"), "w") as fh:
        fh.write(parse_usage.LEDGER_PREAMBLE)
    cfg = os.path.join(d, "config.json")
    with open(cfg, "w") as fh:
        json.dump({"accounts": {"pool_file": "pool.json", "lease_file": "leases.json",
                                "ledger_file": "agents.md"}}, fh)
    return {"AGENT_REVIVE_CONFIG": cfg}, os.path.join(d, "leases.json")


def lease_findings(p, agents, lease_path, account, holders, shared):
    out = []
    try:
        lease = json.load(open(lease_path)).get(account) or {}
    except (OSError, ValueError) as e:
        return [f"the lease file is unreadable: {e}"]
    got = sorted(lease.get("agents") or ([lease["agent"]] if lease.get("agent") else []))
    if got != holders:
        out.append(f"the lease on {account} names {got}, not {holders} "
                   f"(exit {p.returncode}: {(p.stdout + p.stderr).strip()[-300:]})")
    dst = os.path.join(agents, AGENT, "secrets", "personal", "claude-auth.env")
    try:
        text = open(dst).read()
        if f"# fleet-account: {account}\n" not in text or stat.S_IMODE(os.stat(dst).st_mode) != 0o600:
            out.append(f"the credential file is not {account}'s token file at mode 600")
    except OSError:
        out.append(f"no credential file at {dst}")
    if p.returncode != 0:
        out.append(f"the block exited {p.returncode}")
    line = f"{len(holders)} agents share account {account}"
    if shared and line not in p.stdout:
        out.append(f"the block did not print '{line}': the share would be silent")
    if not shared and "agents share account" in p.stdout:
        out.append("the block printed a share for an account nobody shares")
    return out


# --------------------------------------------------------------- F. the status line

def status_line_findings(p, agents, before, fleet):
    out = []
    path = os.path.join(agents, AGENT, ".claude", "settings.json")
    want_cmd = os.path.join(fleet, ".claude", "skills", "agent-health", "usage_statusline.py")
    if p.returncode != 0 or "statusLine set" not in p.stdout:
        return out + [f"the block did not set the status line (exit {p.returncode}): {(p.stdout + p.stderr).strip()[-200:]}"]
    try:
        d = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError) as e:
        return out + [f"settings.json is unreadable after the merge: {e}"]
    if d.get("statusLine") != {"type": "command", "command": want_cmd}:
        out.append(f"statusLine is {d.get('statusLine')}, not the command {want_cmd}")
    kept = {k: v for k, v in (before or {}).items() if k != "statusLine"}
    lost = {k: v for k, v in kept.items() if d.get(k) != v}
    if lost:
        out.append(f"the merge lost other keys of settings.json: {sorted(lost)}")
    return out


# ------------------------------------------------------------------------- main

def main():
    if not shutil.which("systemd-analyze"):
        raise NoVerdict("systemd-analyze is not installed: no unit can be verified here")
    with tempfile.TemporaryDirectory(prefix="fleet-units-test-") as tmp:
        print("A. the agent unit, rendered by the skill's agent-unit block, in both forms")
        for form in ("system", "user"):
            p, base, home, agents = run_block("agent-unit", FLEET, tmp, "agent-" + form, form=form)
            found = agent_findings(p, base, home, agents, form)
            for f in found:
                check(False, f"A {form}: " + f)
            check(not found, f"A {form}: the agent unit renders, verifies as a {form} unit, keeps one tmux "
                             "directory through %t and reads its credential file")
        # The template's STATEMENT of the two lines /agent-revive and /agent-health
        # read (tmux_triage.sh's auth facts): the rendered checks above see their
        # values, this sees the lines themselves, one each.
        tmpl = open(os.path.join(FLEET, AGENT_TEMPLATE), encoding="utf-8").read()
        for line in ("Environment=FLEET_AGENT_AUTH=<auth-mode>",
                     "EnvironmentFile=<agents-root>/<agent-name>/secrets/personal/claude-auth.env"):
            n = len(re.findall("^" + re.escape(line) + "$", tmpl, re.M))
            check(n == 1, f"A the template carries `{line}` exactly once (found {n})")

        print("B. the watchdog unit and the one root command, from the watchdog-unit block, in both forms")
        for form in ("system", "user"):
            p, base, _, agents = run_block("watchdog-unit", FLEET, tmp, "watchdog-" + form, form=form)
            found = watchdog_findings(p, base, agents, form)
            for f in found:
                check(False, f"B {form}: " + f)
            check(not found, f"B {form}: one sudo line naming only the staged files, a unit that verifies "
                             f"and points at the {form} form's tmux directory and config")

        print("D. the first run, from the first-run block, against a fake tmux")
        for auth, seed, label in (("token", None, "token seeds onboarding"),
                                  ("login", None, "login seeds nothing"),
                                  ("api-key", None, "api-key seeds nothing"),
                                  ("token", '{"keep": 1}\n', "an existing .claude.json is kept")):
            p, base, home, agents = run_block("first-run", FLEET, tmp, f"first-{auth}-{seed is not None}",
                                              auth=auth, seed=seed)
            found = first_run_findings(p, base, home, agents, auth, seeded=seed)
            for f in found:
                check(False, "D " + f)
            check(not found, f"D {label}, and the session starts with the unit's environment and flags")

        print("E. the credential file, from the auth-file block, read by pool_pick.py --read-auth-file")
        for auth, account, value, label in (
                ("token", "ada-account", VALUE, "token, written as safe-box writes it (no newline)"),
                ("token", "ada-account", VALUE + "\n", "token, pasted with a trailing newline"),
                ("api-key", "", "sk-ant-api03-stand-in-not-a-key", "api-key, no account line"),
                ("login", "", None, "login, an empty file")):
            files = {} if value is None else {"secrets/personal/claude-credential": value}
            p, base, home, agents = run_block("auth-file", FLEET, tmp, f"auth-{label[:12]}-{len(value or '')}",
                                              auth=auth, account=account, files=files)
            found = auth_file_findings(p, agents, auth, account, (value or "").rstrip("\n"))
            for f in found:
                check(False, "E " + f)
            check(not found, f"E {label}: header, mode 600, the variable set, the bare copy removed")
        p, base, home, agents = run_block("auth-file", FLEET, tmp, "auth-noaccount", auth="token",
                                          files={"secrets/personal/claude-credential": VALUE})
        dst = os.path.join(agents, AGENT, "secrets", "personal", "claude-auth.env")
        check("NOT WRITTEN" in p.stdout and not os.path.exists(dst)
              and os.path.exists(os.path.join(agents, AGENT, "secrets", "personal", "claude-credential")),
              "E a token with no account is refused: no credential file, the handed-over copy kept")

        print("G. the lease, from the take-lease block, against a pool fixture")
        x, y = "x@example.com", "y@example.com"
        for name, accounts, holders, account, shared in (
                ("lease-share", [x], ["ada", "grace"], x, True),
                ("lease-free", [x, y], ["ada"], y, False)):
            env, lp = lease_world(tmp, name, accounts, {x: {"agent": "grace", "since": "2026-11-01T00:00Z"}})
            p, base, home, agents = run_block("take-lease", FLEET, tmp, name, env_extra=env)
            found = lease_findings(p, agents, lp, account, holders, shared)
            for f in found:
                check(False, "G " + f)
            check(not found, "G " + ("one account for two agents: taken as a SHARED lease naming both, "
                                     "the token installed, the share printed" if shared else
                                     "a free account: taken unshared, nothing printed about sharing"))

        print("F. the token agent's status line, from the status-line block")
        for before, label in (({"skipDangerousModePermissionPrompt": True}, "merged into the first run's settings"),
                              (None, "a settings file created"),
                              ({"statusLine": {"type": "command", "command": "/x"}, "a": 1},
                               "an older status line replaced, other keys kept")):
            files = {} if before is None else {".claude/settings.json": json.dumps(before)}
            p, base, home, agents = run_block("status-line", FLEET, tmp, f"sl-{len(json.dumps(before))}",
                                              files=files)
            found = status_line_findings(p, agents, before, FLEET)
            for f in found:
                check(False, "F " + f)
            check(not found, f"F {label}")
        p, base, home, agents = run_block("status-line", FLEET, tmp, "sl-broken",
                                          files={".claude/settings.json": "{not json"})
        left = open(os.path.join(agents, AGENT, ".claude", "settings.json")).read()
        check("statusLine set" not in p.stdout and left == "{not json",
              "F a settings file that is not valid JSON stops the block with nothing written")

        print("C. controls - each must be seen red, or there is no verdict")
        boot = "You are <Agent-Name>, started by your service"
        controls = [
            ("C1", "agent-unit", dict(mutate=(AGENT_TEMPLATE, "[Install]", "# <zz-planted>\n[Install]")),
             "placeholder left"),
            ("C2", "agent-unit", dict(mutate=(AGENT_TEMPLATE, boot, "You are <Agent-Name>s' started by your service")),
             "verify exited"),
            ("C3", "agent-unit", dict(mutate=(AGENT_TEMPLATE, boot, "You are '<Agent-Name>', started by your service")),
             "forbidden character"),
            ("C4", "agent-unit", dict(mutate=(AGENT_TEMPLATE, "Environment=TMUX_TMPDIR=%t/",
                                              "Environment=TMUX_TMPDIR=/run/")), "TMUX_TMPDIR is not"),
            ("C5", "watchdog-unit", dict(mutate=(WD_EXAMPLE, "Environment=TMUX_TMPDIR=<tmux-dir>",
                                                 "Environment=TMUX_TMPDIR=/run/claude-tmux-<agent>")),
             "not ONE sudo line"),
            ("C6", "watchdog-unit", dict(mutate=(WD_EXAMPLE, "[Install]", "# <zz planted>\n[Install]")),
             "not ONE sudo line"),
            ("C7", "watchdog-unit", dict(root_name="agents dir"), "not ONE sudo line"),
            ("C8", "first-run", dict(edit=('"env -i HOME=', '"env HOME=')), "not the unit's environment"),
            ("C9", "auth-file", dict(edit=("'# fleet-account: %s\\n'", "'# fleet-acct: %s\\n'"),
                                     run=dict(auth="token", account="ada-account",
                                              files={"secrets/personal/claude-credential": VALUE})),
             # The reader ran (exit 0) and read the mode, and only the account is
             # missing: a reader that is absent or failing is exit 2, not this.
             "'auth': 'token', 'account': None} (exit 0)"),
            ("C10", "status-line", dict(edit=('d = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}',
                                              'd = {}'),
                                        run=dict(files={".claude/settings.json": '{"skipDangerousModePermissionPrompt": true}'})),
             "lost other keys"),
            ("C11", "agent-unit", dict(mutate=(AGENT_TEMPLATE, "#system: User=", "#sytem: User="),
                                       run=dict(form="system"), refuses="agent"), "root command is not ONE"),
            ("C12", "agent-unit", dict(mutate=(AGENT_TEMPLATE, "#user: WantedBy=default.target",
                                               "WantedBy=default.target"),
                                       run=dict(form="system"), refuses="agent"), "root command is not ONE"),
            ("C13", "agent-unit", dict(run=dict(form="sytem"), expect="system"), "no rendered unit"),
            ("C14", "watchdog-unit", dict(mutate=(WD_EXAMPLE, "Environment=STALL_WATCHDOG_CONFIG=",
                                                  "Environment=STALL_WATCHDOG_CFG="),
                                          run=dict(form="system"), refuses="watchdog"), "not ONE sudo line"),
            ("C15", "watchdog-unit", dict(edit=('put="install -D -m 644 $staged $cfg && "', 'put=""'),
                                          run=dict(form="system")), "root command is not the config install"),
            ("C16", "take-lease", dict(edit=(' ${2:+"$2"} ', ' ')), "names ['grace'], not ['ada', 'grace']"),
        ]
        for cid, info, how, needle in controls:
            if info == "watchdog-unit" and needle == "not ONE sudo line":
                how.setdefault("refuses", "watchdog")
        green = []
        for cid, info, how, needle in controls:
            # The credential and status-line blocks read the real tree's
            # agent-health scripts; the unit blocks read a copy a fault is planted in.
            fleet = (FLEET if info in ("auth-file", "status-line", "take-lease")
                     else fleet_copy(tmp, "fleet-" + cid, how.get("mutate")))
            run = dict(how.get("run", {}))
            if info == "take-lease":
                run["env_extra"], lp = lease_world(tmp, cid, ["x@example.com"],
                                                   {"x@example.com": {"agent": "grace", "since": "2026-11-01T00:00Z"}})
            p, base, home, agents = run_block(info, fleet, tmp, cid, root_name=how.get("root_name", "agents"),
                                              edit=how.get("edit"), **run)
            form = how.get("expect", how.get("run", {}).get("form", "user"))
            found = (agent_findings(p, base, home, agents, form) if info == "agent-unit"
                     else watchdog_findings(p, base, agents, form) if info == "watchdog-unit"
                     else auth_file_findings(p, agents, "token", "ada-account", VALUE) if info == "auth-file"
                     else status_line_findings(p, agents, {"skipDangerousModePermissionPrompt": True}, FLEET)
                     if info == "status-line"
                     else lease_findings(p, agents, lp, "x@example.com", ["ada", "grace"], True)
                     if info == "take-lease"
                     else first_run_findings(p, base, home, agents, "token"))
            hit = [f for f in found if needle in f]
            where = (how.get("mutate") or ("block text",))[0] if "root_name" not in how else "agents root"
            print(f"{'red   ' if hit else 'GREEN '}{cid} {where}: {hit[0] if hit else found or 'no finding'}")
            if not hit:
                green.append(cid)
            # A refusal counts only when it names the real rendered file: then the
            # block's variables were set and the refusal is its own checks', not a
            # first line that broke before them.
            unit = {"watchdog": f"claude-agent-{AGENT}-stall-watchdog.service",
                    "agent": f"claude-agent-{AGENT}.service"}.get(how.get("refuses"))
            refused = f"NOT RENDERED: {agents}/{AGENT}/config/{unit} "
            if unit and refused not in p.stdout:
                print(f"GREEN {cid}: no NOT RENDERED line naming {refused.split(': ', 1)[1].strip()}")
                green.append(cid)
        if green:
            raise NoVerdict(f"control(s) {', '.join(sorted(set(green)))} stayed green: the checks cannot "
                            f"see that fault, so their passes above mean nothing")
    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except NoVerdict as e:
        print(f"NO VERDICT: {e}")
        sys.exit(3)
