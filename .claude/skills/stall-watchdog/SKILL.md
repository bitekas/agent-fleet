---
name: stall-watchdog
version: 1
description: >
  Install procedure for the stall watchdog, a SYSTEM SERVICE rather than a skill an
  agent loads to do work. One daemon per unattended agent session, running outside it,
  which answers a blocking confirmation prompt nobody is present to answer: it sends
  Escape once the prompt has sat unchanged past a timeout, then injects a notice saying
  what it did. Load this file to install or reconfigure it for an agent, to change a
  prompt pattern or the timeout, or when diagnosing a `WATCHDOG` line or a session that
  went silent. The mechanism and the safety argument are `technical/watchdog.md`; this
  file is the procedure and the values to customise.
requires_install: true
---

# Stall watchdog - installation

A daemon that watches ONE unattended agent session from outside, over tmux, and
answers a confirmation prompt that has been sitting unanswered. **It always answers
no, and there is no approve path.**

**Read `technical/watchdog.md` sections 1 to 3 before installing this anywhere.**
They are the safety argument - why refusing is the only automatic answer, and why
both the signature and the unchanged-pane conditions are required. This file assumes
you have.

**Nothing here is loaded to perform a task.** It is an operator procedure: the
service runs whether or not any agent has read a word of it.

| File | What it is | Per install? |
|---|---|---|
| `SKILL.md` (this) | the install procedure and the values to customise | universal |
| `technical/watchdog.md` | mechanism, safety argument, troubleshooting | universal |
| `CONTEXT.md`, in the install context (`fleet where stall-watchdog CONTEXT.md`) | which sessions are watched here, and where their files live | **this install** |
| `config.example.json` | every key, placeholdered, with its full explanation | universal |
| `watchdog.py` | the poll loop, the decision logic, `--probe` and `doctor` | universal |
| `watchdog.test.py` | offline regression guard, hermetic | universal |
| `fixtures/` | real captured panes the suite asserts against | universal |
| `installation/check` | is it installed here, and is it current | universal |
| `installation/agent-stall-watchdog.service.example` | the unit template (Linux, systemd) | universal |
| `installation/agent-stall-watchdog.plist.example` | the LaunchDaemon template (macOS, launchd) | universal |
| `installation/render-plist.py` | renders that template for one session, its PATH from where tmux is; with `--job session`, the agent's own session job (`templates/claude-agent.plist.example`), its PATH from where tmux and `claude` are, then `/opt/homebrew/bin`, `/usr/local/bin` and the system directories | universal |
| the config `STALL_WATCHDOG_CONFIG` names | the real values, one file per watched session | **this install** |
| `installation/.install-state.json`, in the install context | what was installed, per host and per config | **this install** |

---

## 1. What must already be true

**The agent session runs inside tmux.** This is the load-bearing prerequisite and it
is easy to miss: the watchdog captures the session's terminal *from outside*, so a
session started directly in a terminal, or under a launcher that owns the TTY, cannot
be watched at all. Nothing else here matters if this is not true.

**Python 3 and tmux on the system path.** No third-party packages: `watchdog.py` is
stdlib only, and `/usr/bin/python3` is what the unit runs. On macOS the job runs the
fleet's interpreter (`FLEET_PYTHON`, else host.json's `python`, else Homebrew's
`/opt/homebrew/bin/python3`; the system `/usr/bin/python3` is older than the fleet's
floor) and finds tmux through the PATH `installation/render-plist.py` writes into the
plist: the directory of the tmux it finds, then the interpreter's, then the system
directories (step 4).

**One config and one unit per watched session.** They are not shared. Two sessions
watched by one daemon is not a configuration this supports, and two daemons sharing a
`state.dir` race to Escape the same prompt - the flock is on a file inside it.

**`TMUX_TMPDIR` must be identical in three places** - the session, `tmux.tmpdir` in
the config, and the unit's `Environment=`. A mismatch reports as `no server running`,
which reads like a missing session rather than a configuration error, and leaves the
watchdog permanently blind while `systemctl status` shows it healthy.

## 2. Write the config

The config is per agent, in that agent's config directory, at the path its unit
names - `<agents-root>/<agent>/config/stall-watchdog.json` - and **outside every
repository**: it holds one session's values, and a committed copy is a roster rather
than a config. Copy it writable, because the fleet tree is read-only and `cp` keeps
that mode:

```bash
install -m 600 "${CLAUDE_SKILL_DIR}/config.example.json" <agents-root>/<agent>/config/stall-watchdog.json
```

Replace every placeholder:

| Key | What to put in it |
|---|---|
| `tmux.tmpdir` | the `TMUX_TMPDIR` the session was created with |
| `tmux.target` | the tmux target, `<session>:<window>` |
| `stall.stall_secs` | how long a prompt must sit UNCHANGED before it is answered |
| `stall.poll_secs` | the sample interval; keep at least four samples inside the stall window |
| `stall.prompt_patterns` | leave as shipped unless the terminal UI changed; see step 5 |
| `stall.idle_patterns` | leave as shipped unless the terminal UI changed; `technical/watchdog.md` section 4 says why they matter more than the patterns |
| `stall.idle_tail_lines` | **measure it** against a live pane in step 5 - anything rendered below the status bar pushes the idle signature out of the window and silently disarms the exclusion |
| `stall.known_prompts` | a deployment decision - see step 3 |
| `action.deny_key`, `action.notice` | leave as shipped |
| `state.dir` | a durable directory this session's daemon owns, and **nothing else does** - bar the transient probe file `installation/check` writes and removes there to prove the directory is genuinely writable |
| `owner.claude_config_dir` | `null` when systemd is the launcher; systemd sets no `CLAUDE_CONFIG_DIR`, and the flock is the real single-instance guard |

**`state.dir` never comes from an environment variable**, and there is no key for
one. It is a property of the deployment, not of whoever launched the process: a
second launcher with a different value gets its own lock and runs a second watchdog
alongside the first, both racing to Escape the same prompt.

**`stall_secs` is a statement about who is present.** It assumes nobody is at the
terminal. If a human might be reading a prompt, they have `stall_secs` to answer
before it is refused for them - raise it if that stops being true.

**`STALL_WATCHDOG_CONFIG` selects the config, and there is no fallback that
resolves.** No `config.json` ships beside `watchdog.py` on purpose: a launcher that
forgot the variable then dies naming the file it could not find, instead of quietly
arming against the example, whose tmux target is a literal placeholder and whose
state directory belongs to nobody. Set the variable in exactly ONE place per session:
the unit.

## 3. Decide the taught prompts

`stall.known_prompts` are dialogs the watchdog is taught to ANSWER rather than
refuse, checked before the Escape fallback. They are for non-permission prompts that
block start-up.

**Each entry is a deployment decision and must be made deliberately.** Refusing is
safe because it is uninformed; **choosing is not** - it commits the session to one
branch. The shipped entry is the case in point: the preselected answer to the
session-resume prompt compacts, and compacting on every unattended restart silently
discards session context; the shipped keys resume the full session instead. Read the
entry's own `_comment`, decide, and record the decision in the install's `CONTEXT.md`.

**Never add an approve entry for a permission prompt.** Two checks in
`watchdog.test.py` stand behind that, and they cover different things - **taking
the first for both leaves the hole open.** `TEETH: config exposes no
approve/yes/confirm key` only inspects `action`, so it stays green against a
`known_prompts` entry that answers a permission dialog with `["Down","Down","Enter"]`
- an approve path carrying no approve key. What actually forbids that is `TEETH: a
permission prompt matches NO taught handler - it is still refused`, driven by real
captured permission prompts. Both are driven red before they are trusted.

## 4. Write the unit

Copy `installation/agent-stall-watchdog.service.example` writable
(`install -m 644 <src> <dst>`), name it for the session it watches -
`claude-agent-<agent>-stall-watchdog.service` - and fill in every placeholder the
unit's header lists:

| Directive | Value |
|---|---|
| `Wants=` / `After=` | the unit that starts the watched session |
| `User=` | the user that owns the session and its tmux socket |
| `WorkingDirectory=` | **that session's own project checkout** - the directory its agent unit starts it in |
| `ExecStart=` | `/usr/bin/python3 <fleet>/.claude/skills/stall-watchdog/watchdog.py`, where `<fleet>` is the **host fleet checkout** |
| `Environment=TMUX_TMPDIR=` | `<tmux-dir>`: identical to `tmux.tmpdir` in the config |
| `Environment=STALL_WATCHDOG_CONFIG=` | the config written in step 2 |
| `ReadWritePaths=` (state) | `state.dir` from the config |
| `ReadWritePaths=` (tmux) | `<tmux-dir>`, the tmux runtime directory |

**`ProtectSystem=strict` makes the entire hierarchy read-only**, so every path the
daemon writes needs a `ReadWritePaths` entry. The state directory is load-bearing and
was measured: without it the state write is silently blocked, which looks exactly like
a watchdog capturing nothing. The tmux socket directory is kept as cheap defence in
depth - the unit's own comment carries the measurement showing that a read-only
mount does not block the socket connect on every platform, so **re-measure before
citing it as the cause of a blind watchdog.**

**Keep `ReadWritePaths` unprefixed.** A `-` prefix would make a missing directory
tolerable at start, and the unit would come up permanently blind. Without it a
missing directory fails the unit and `Restart=always` retries until it appears, which
is the intended recovery when the watched session is down. Create `state.dir`
yourself before enabling; the tmux directory arrives with the session's own unit.

**`ExecStart` points at the host fleet checkout.** That tree moves only by `fleet
upgrade`, never because somebody pulled a branch, so every watchdog on the host runs
one released version and none changes under its session mid-work. An upgrade reaches
these root-owned units without an edit or a restart: `watchdog.py` re-executes itself
when its own file changes on disk (`technical/watchdog.md` section 9). The unit runs
with `ProtectHome=read-only`, which still lets it read the fleet tree.

**Do not set `CLAUDE_CONFIG_DIR` in this unit.** It is a supervisor, not an agent.
With `owner.claude_config_dir` null the flock is the single-instance guard.

**On macOS the unit is a LaunchDaemon, rendered by `installation/render-plist.py`**
from `installation/agent-stall-watchdog.plist.example`, as the user that owns the
session, with the directory of the session's tmux on PATH:

```bash
python3 "${CLAUDE_SKILL_DIR}/installation/render-plist.py" --agent <agent> --agents-root <agents-root> \
  --checkout <checkout> --state-dir <state dir> --tmux-dir <tmux-dir> --config <config> \
  --form system --out <launchd-prefix>.stall-watchdog.<agent>.plist
plutil -lint <launchd-prefix>.stall-watchdog.<agent>.plist
```

`<launchd-prefix>` is host.json's `launchd_prefix`, default `com.agent-fleet`.
`UserName` is the user running the renderer; `TMUX_TMPDIR` is identical to
`tmux.tmpdir`, which on macOS is `<agents-root>/run/claude-tmux-<agent>` (launchd has
no runtime directory; the session supervisor creates that one); the log goes to
`<state dir>/watchdog.log`; where an administrator installs it for a separate
agents user, `--config` names a root-owned config, as the systemd form's does;
`--form user` renders the LaunchAgent form, without `UserName`. **The job's PATH is
rendered from where tmux is**, never written by hand: watchdog.py runs a bare
`tmux`, launchd's own PATH reaches none, and a job whose PATH misses it runs,
captures nothing and looks healthy. So the renderer prints `NOT RENDERED` and writes
nothing when no tmux is on its PATH, or when tmux or the interpreter does not run
under the PATH it would write. **Where that tmux is decides whether the watchdog is
protected**: a tmux in a directory the agents user can change - its own
`~/.local/bin` on a Mac without Homebrew - is one the watched agent can replace, and
`install-agent-fleet`'s `verify-privileges.py` FAILs it, as it does a directory that
user can write anywhere before it on the job's PATH; Homebrew's, installed as the
administrator, passes. The systemd unit sets no PATH, so it runs the first tmux on
the system manager's PATH, on a distribution's layout its own root-owned
`/usr/bin/tmux`, which passes. launchd has no equivalent of `ProtectSystem`,
`ReadWritePaths` or `NoNewPrivileges`, so the plist carries none; the process runs
as the agent's user, the same boundary the session has.

## 5. Verify before installing anything

Run all three. The second and third need the watched session to be up.

```bash
python3 "${CLAUDE_SKILL_DIR}/watchdog.test.py"
#   -> ALL CHECKS PASSED. Offline and hermetic: no config, no tmux, no install.

STALL_WATCHDOG_CONFIG=<config> "${CLAUDE_SKILL_DIR}/watchdog.py" doctor
#   -> the resolved config, then "tmux reachable, N lines captured".
#      Confirm the target named is the session you meant.

STALL_WATCHDOG_CONFIG=<config> "${CLAUDE_SKILL_DIR}/watchdog.py" --probe
#   -> the live pane, the digest, and which patterns hit. Takes no action.
```

**What `--probe` must show against a healthy session**, and BOTH lines are required:

- `prompt match  False`. A hit against a working session is a pattern that is too
  loose - fix it before enabling anything, because that hit is an Escape into live
  work `stall_secs` later.
- `exclusion     ARMED`. **This is the one that gets skipped, and it is the one
  that matters.** `prompt match False` has two causes and only one of them is
  protection: the structural exclusion fired, or no prompt pattern happened to
  match. The second is unprotected - nothing then stands between a chooser the agent
  merely PRINTS and an Escape 120 seconds later - and from the outside the two are
  the same line of output.

**`stall.idle_tail_lines` is a MEASURED value, not a constant.** Anything the
terminal renders below the status bar pushes the idle signature out of the window:
an agent-list panel puts it SEVEN lines from the bottom, one outside a six-line
window, and the session then reads as `prompt match False` with the exclusion inert
(`technical/watchdog.md` section 4). Raise it until `--probe` says ARMED,
and re-run after any terminal-UI change. Widening is cheap: verify the shipped
fixtures are still detected as prompts at the new width - they are at every width up
to the whole pane - so it trades no detection for the protection.

**First check the PERMISSION MODE, or you will raise this without bound and never
reach ARMED.** `INERT` has two causes and only one of them is a window that is too
small: the idle signature may not be on the pane at all. `\u23f5\u23f5` is carried by the auto
and accept-edits status bars; a session in MANUAL or PLAN mode shows `\u23f8 manual mode
on \u00b7 ? for shortcuts \u00b7 \u2190 for agents` or `\u23f8 plan mode on (shift+tab to cycle) \u00b7 \u2190 for
agents`, which matches no shipped idle pattern at any width - measured. `--probe`
distinguishes them: it says whether the signature is on screen but outside the window,
or absent entirely. Probe the session in the mode it will actually RUN in, not the
mode it happens to start in.

**NEVER call `answer_no_and_notify` and never run the loop by hand against a
session doing real work.** The Escape lands first and interrupts whatever is running.

**A raw `tmux` command you type yourself needs `env -u TMUX`.** Inside a tmux
session, `$TMUX` wins over `$TMUX_TMPDIR`, so `TMUX_TMPDIR=<other> tmux ls` lists the
server you are sitting in - measured. `watchdog.py` drops `TMUX` itself, so the three
commands above are safe as written; `tmux ls` typed beside them is not.

## 6. Install

```bash
sudo install -m 0644 <unit file> /etc/systemd/system/<unit name>.service
sudo systemctl daemon-reload
sudo systemctl enable --now <unit name>
systemctl status <unit name>
```

On macOS, ONE sudo line installs the LaunchDaemon (root-owned, so the agent it
watches can kill the process, which launchd restarts, but cannot bootout, disable or
edit it):

```bash
sudo install -m 644 -o root -g wheel <plist file> /Library/LaunchDaemons/<label>.plist && sudo launchctl bootstrap system /Library/LaunchDaemons/<label>.plist
launchctl print system/<label>          # state = running, and its pid
tail -n 20 <state.dir>/watchdog.log
```

The same plist as a LaunchAgent (no `UserName`, in the user's
`~/Library/LaunchAgents`, bootstrapped into `gui/<uid>` without sudo) runs, but the
agent can bootout, disable or delete it, so `installation/check` reports it as exit 1,
`UNPROTECTED`, however well it captures. Use it only where no administrator is
available, and know that it is the degraded form.

Then confirm it is not merely running but **seeing**:

```bash
systemctl show <unit name> -p ActiveEnterTimestamp
ls -l <state.dir>/stall-watchdog.json
cat <state.dir>/stall-watchdog.json     # a capture_error key here is a blind watchdog, with its cause
```

**A state file whose mtime is newer than the service start, and that holds no
`capture_error`, is the proof of capture**, and the only cheap one. Every poll writes
the state; a poll whose capture failed writes it with `capture_error`, which names
the cause in the daemon's own words (`tmux could not be started ... on PATH=...`
for a job whose PATH reaches no tmux, tmux's own message for one that ran and
failed). So a healthy `systemctl status` over a stale state file, or over one
carrying `capture_error`, is exactly what a blind watchdog looks like, and
`installation/check` prints the recorded cause.

`journalctl -u <unit name> -n 20` (on macOS, the log above) should show one
`WATCHDOG-INFO watchdog up` line
and nothing else. `WATCHDOG-ERROR` lines mean it is up and failing to capture. After a
`fleet upgrade` that changed `watchdog.py`, one `changed on disk - re-executing` line
followed by a second `watchdog up` is the upgrade arriving.

## 7. Record the install

Add this host and this config to `installation/.install-state.json` in the install
context. It is keyed by host, then by the config path **exactly as the unit's
`STALL_WATCHDOG_CONFIG=` line names it** (a leading `~` expanded), because `check`
looks the record up by that string; the version comes from this file's frontmatter.
Run it as the agent, or from a checkout of the install, so `fleet where` resolves:

```bash
CONFIG=<agents-root>/<agent>/config/stall-watchdog.json   # as the unit names it
python3 - "${CLAUDE_SKILL_DIR}/SKILL.md" \
  "$(fleet where stall-watchdog installation/.install-state.json)" "$CONFIG" <<'PY'
import json, os, re, socket, sys, time, pathlib
skill, state = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
config = os.path.expanduser(sys.argv[3])
v = int(re.search(r"^version:\s*(\d+)$", skill.read_text(), re.M).group(1))
doc = json.loads(state.read_text()) if state.exists() else {}
doc.setdefault("hosts", {}).setdefault(socket.gethostname(), {})[config] = {
    "version": v, "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "by": "SKILL.md"}
state.parent.mkdir(parents=True, exist_ok=True)
state.write_text(json.dumps(doc, indent=2) + "\n")
print("recorded", config, "version", v, "on", socket.gethostname())
PY
```

It adds or replaces this host's entry for this config and leaves every other entry
alone. For an agent `ada` the file then holds:

```json
{ "hosts": { "<this host>": {
    "<agents-root>/ada/config/stall-watchdog.json": {
      "version": 1, "installed_at": "<UTC time>", "by": "SKILL.md" } } } }
```

Then run this skill's check, `"${CLAUDE_SKILL_DIR}/installation/check"` (with
`STALL_WATCHDOG_CONFIG` set, or the config path as its argument), until it exits 0.
It is a file the fleet ships, beside this one, never in the install context:
`fleet where` names install files, and for this one it would print a path where
nothing is. It reports three states:

| Exit | Meaning |
|---|---|
| `0` | installed and current - proceed |
| `1` | installed but stale, or a leg it could not measure - do not proceed |
| `2` | not installed - follow this file |

State 1 is the reason it exists: absent is loud, stale is silent.

## 8. Changing it later

- **A prompt pattern or the terminal UI changed**: capture a real prompt with
  `--probe`, tune, re-run `watchdog.test.py`. Regenerate `fixtures/` from real
  captures only - `technical/watchdog.md` section 6 says why, and **section 7 says
  how to get a real prompt on screen to capture**, which is the step people get stuck
  on: an ordinary permission prompt needs a session NOT in an auto-approving mode and
  a command shape that session has not already approved.
- **The decision logic changed**: re-run every negative control in
  `technical/watchdog.md` section 7. A green suite that cannot go red is not evidence.
- **The install procedure changed**: bump `version` in this file's frontmatter, so
  every host that has not re-run it reads as stale rather than as current.
  **"The procedure changed" means a host that re-ran it would end up with
  something DIFFERENT** - a new config key, a changed unit directive, an extra step,
  a different verification. Sharpening the prose that explains an existing step is
  not that, and bumping for it marks every correct install stale, costs a re-run per
  agent, and teaches the next reader that STALE means nothing. The test is whether an
  install performed under the old text is now WRONG, not whether the text is now
  better.
