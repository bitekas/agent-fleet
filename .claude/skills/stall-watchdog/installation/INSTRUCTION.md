# Installing the stall watchdog

**The procedure is `SKILL.md`, one directory up.** Follow it start to finish,
once per watched agent session: every step of it is per agent and needs that
agent's home and its running session. Only `CONTEXT.md` in the install context
is install-wide.

This file is a pointer and deliberately not a second copy. The whole of this
directory's subject IS installation - the thing is a system service, not a skill an
agent loads to do work - so `SKILL.md` is the procedure, and a parallel copy here
would be the version that goes stale while still reading as authoritative.

What lives in this directory rather than in `SKILL.md`:

| File | What it is |
|---|---|
| `check` | is it installed for one session, and is it current: exits 0, 1 or 2 |
| `agent-stall-watchdog.service.example` | the unit template, placeholdered (Linux, systemd) |
| `agent-stall-watchdog.plist.example` | the LaunchDaemon template, placeholdered (macOS, launchd) |
| `render-plist.py` | renders the LaunchDaemon (or LaunchAgent) for one session: the job's PATH from the tmux on the renderer's PATH and the fleet's interpreter, refused when tmux or the interpreter does not run under it. `--job session` renders the agent's own session job the same way, its PATH from where tmux and `claude` are (`/adding-an-agent` section 5 step 6) |
| `render-plist.test.py` | the renderer offline, both jobs on a Mac layout without Homebrew, its refusals, and that the smoke below renders through it |
| `check.test.py` | `check`'s launchd legs against a fake launchctl: OK for the LaunchDaemon, UNPROTECTED for a LaunchAgent, and the cause a blind watchdog recorded |
| `launchd-daemon.smoke.sh` | the LaunchDaemon on a real macOS launchd, with sudo, rendered by `render-plist.py`: runs as the user, captures, survives kill -9, refuses an unprivileged bootout, reads OK; a failed run prints the job's log. Not discovered by `tests/run-all.sh`: run only on a disposable or consenting Mac (it refuses without passwordless sudo) |
| `.install-state.json`, in the install context, not here (`fleet where stall-watchdog installation/.install-state.json`) | what was actually installed, per host and per config |

`check` is per SESSION, not per machine: it takes the config path as an argument or
reads `STALL_WATCHDOG_CONFIG`, and one agent's watchdog being healthy says nothing
about another's.
