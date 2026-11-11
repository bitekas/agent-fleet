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
| `check.test.py` | `check`'s launchd legs against a fake launchctl: OK for the LaunchDaemon, UNPROTECTED for a LaunchAgent |
| `launchd-daemon.smoke.sh` | the LaunchDaemon on a real macOS launchd, with sudo: runs as the user, captures, survives kill -9, refuses an unprivileged bootout, reads OK. Not discovered by `tests/run-all.sh`: run only on a disposable or consenting Mac (it refuses without passwordless sudo) |
| `.install-state.json`, in the install context, not here (`fleet where stall-watchdog installation/.install-state.json`) | what was actually installed, per host and per config |

`check` is per SESSION, not per machine: it takes the config path as an argument or
reads `STALL_WATCHDOG_CONFIG`, and one agent's watchdog being healthy says nothing
about another's.
