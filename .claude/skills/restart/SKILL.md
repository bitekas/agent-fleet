---
name: restart
version: 1
description: >
  Gracefully wind down all in-flight work, persist state to disk, and reboot the
  machine. Rebooting restarts the agent's service unit (`service.unit`), so the
  next session starts fresh - picking up new MCP servers, PATH/profile changes,
  and config edits that only apply on agent restart.
requires_install: false
---

# Restart the agent machine

Do the wind-down properly before pulling the trigger; an abrupt reboot mid-write
is how work gets lost. Whether a reboot is authorized at all, and by whom, is the
invoking agent's charter, not this document.

A Claude binary update already installed under a running session needs no
reboot: `/soft-restart` restarts that one session and leaves every other alone.

Every concrete name below - the service unit, the two commands, the teardown, the
handoff file - is a key in this skill's `config.json` in the install context
(`fleet where restart config.json` prints its path), written as `` `service.unit` ``
and never as the value. The file serves every agent of the install, so
`service.unit` and `service.reattach_command` hold the token `<agent>`: put your
own agent name in its place before using either.

Work through these steps **in order**:

## 1. Stop in-flight work

- Stop every background task you started this session (Bash background jobs,
  Monitors, workflows): use TaskStop / let them be killed, but check
  `TaskList`-style state first so you know what was running.
- Gracefully stop project dev servers: run the scoped teardown
  (`stack.teardown_command`), which kills this worktree's servers via their PID
  files and removes the runtime artifacts they wrote. **An empty
  `stack.teardown_command` means the install runs no dev stack: skip this
  bullet.**
- Kill anything it missed: `pkill -f` on each pattern in
  `stack.stray_process_patterns` (ignore "no process" failures; an empty list
  means skip). These are DELIBERATELY machine-wide - they kill **every other
  worktree's stack and any other session's in-flight run**, which is acceptable
  ONLY because an immediate reboot follows. If the reboot is called off, **say
  so**: those sessions' stacks are gone and their owners have no way to tell that
  from a crash of their own. Never copy this pattern into anything that is not
  about to reboot - the scoped teardown (`stack.teardown_command`), run once per
  worktree, is what a non-rebooting caller wants.

## 2. Persist state to disk

- File edits made via tools are already on disk - but double-check `git status`
  in each repository you worked in and report what is uncommitted in your
  wind-down summary. Do NOT auto-commit; uncommitted work survives a reboot fine,
  the user just needs to know it's there.
- Write a handoff note to `handoff.file` so the next session can resume: what was
  in progress, what is uncommitted, next steps, any gotchas. Keep it under ~30
  lines. A relative `handoff.file` resolves against the session's working
  directory - the directory the service unit starts the session in - so the next
  session finds it at the same path. If that directory is a repository, the file
  must be gitignored there.
- Run `sync` to flush filesystem buffers.

## 3. Tell the user, then reboot

- Post a short summary in chat: what was stopped, what's uncommitted, where the
  handoff note is, and a reminder that they re-attach after boot with
  `service.reattach_command` (the service unit `service.unit` relaunches the
  agent automatically at boot).
- Then run `service.reboot_command`. This restarts the machine.

On macOS the agent's session has two forms. With an administrator it is a
LaunchDaemon in launchd's system domain, which launchd loads at boot with nobody
logged in. With no administrator it is a LaunchAgent in the agents user's gui
domain, which exists only once that user is logged in. In both forms the agent's
daemons are LaunchAgents in that gui domain, so a Mac host comes back with its
agents only with automatic login on for the agents user.

## After the reboot (for the NEXT session reading this)

If you find the handoff note (`handoff.file`) at session start, read it, act on it
(or surface it to the user), then delete it - it is one-shot state, not
documentation.
