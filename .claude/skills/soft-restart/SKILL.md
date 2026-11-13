---
name: soft-restart
version: 1
description: >
  Restart your OWN Claude Code session, not the machine, so it runs the Claude
  binary that is already installed, then pick up where it stopped. A running
  session keeps executing the binary it started from, and a stale one resolves
  a model alias to an older model than the installed client offers; the fix is
  this restart, never a model override. Confirms the update from the pane's
  banner AND the running binary, stops intake, hands in-flight subagent work
  off to notes on their branches, writes a checkpoint in the agent's state
  directory, posts a heads-up and notifies the fleet's health agent when there
  is one, then types `/exit` into its own pane so the service unit relaunches
  the session. Load when you are asked to soft-restart or to take a pending
  Claude update, and when a session that has just come back finds a
  soft-restart checkpoint.
requires_install: false
---

# soft-restart

Restart this agent's session, and only it, so it runs the Claude binary that is
already installed. A running process keeps executing the file it started from:
an update installs the new version beside it and repoints the `claude` on the
PATH, which the running process never reads again. `/restart` ends the process
by rebooting the machine and every other session with it; soft-restart exits
only this session and lets the agent's service unit start it again.

**A stale binary is a model problem, not a cosmetic one.** Model aliases are
resolved by the client, so a session on an old binary resolves an alias to an
older model than the installed client offers. The fix is this restart. **Never
pin a model with an environment variable or a model override to get around a
stale binary**: the override outlives the problem, hides it from every later
check, and is wrong again at the next update.

**You start it when you are asked to**: by your owner, or by your owner passing
on a flag from the fleet's health check. Nothing in this skill starts a restart
on its own or on a schedule. Whether a request is yours to act on is your
charter's call, not this document's.

Every concrete name below is a key in this skill's `config.json` in the install
context (`fleet where soft-restart config.json` prints its path), written as
`` `service.unit` `` and never as the value. The file serves every agent of the
install, so `service.unit` holds the token `<agent>`: put your own agent name in
its place. The install's `CONTEXT.md` for this skill (`fleet where soft-restart
CONTEXT.md`) is the local layer: section *What CONTEXT.md carries* below.

**Your state directory** is the `state` row of `/agent` section 3, which the
install's `agent` CONTEXT.md maps to a path. It is the one place this skill
writes what the returning session reads; step 4 says why it is never your
working directory and never the session scratchpad.

Work through the steps in order. `/exit` is typed in step 6 and nowhere else.

## 0. Confirm an update is pending

```bash
python3 "${CLAUDE_SKILL_DIR}/pending_update.py"
```

It takes two readings, independently, and needs both:

- **The banner** on your own pane: `Update installed`, U+00B7, `Restart to
  update`, right-aligned on the line directly above the input box's top rule.
  It reads that line only. The same words anywhere else on the screen are
  conversation text - a quoted capture, this skill under discussion - and say
  nothing about the binary.
- **The binary**: the version your session's claude process is executing, read
  from its executable (`/proc/<pid>/exe` on Linux, where a file the updater has
  since removed reads `<path> (deleted)`; lsof's text entry where there is no
  `/proc`), against the version `claude --version` reports for the installed
  client, which is the one the service starts next.

| Exit | Last line | Meaning | Do |
|---|---|---|---|
| `0` | `PENDING: ...` | banner shown, running binary older than the installed one | continue to step 1 |
| `1` | `NONE: ...` | no banner, running binary is the installed one | stop, and tell the requester there is no update to take: a restart now costs the return time and adopts nothing |
| `3` | `NO VERDICT: ...` | the readings disagree, or one could not be taken; the line says which | stop, post the line in the request thread, and go on only on the requester's explicit go-ahead |
| `2` | `refusing: ...` | not inside a tmux pane, so there is no own pane to read | the session contract is broken (`/self-compact` section 1, its precondition); report it |

**Why both, and why a disagreement stops you.** The banner is what the client
says about itself; the executable is what the process actually runs. A restart
is worth its cost only when the two agree that something newer is installed. A
banner over a binary that is already the installed one means the restart adopts
nothing; a stale binary with no banner means the client and the process disagree
about what is installed, which is a question for a person, not a reason for an
exit nobody is watching.

Exit 1 with no `NONE` line is Python failing to run the file, not an answer: read
the line, not the code. The same check run after the return reads `NONE` with
the new version, and that is step 7's proof that the restart took.

## 1. Stop new intake

- **Take no new request** from here until you are back. One that arrives is
  deferred the way your charter defers any request, so it is in your record of
  open requests when you return.
- **Leave the daemons running.** The scheduler and the chat watcher are separate
  always-on units that keep running through the restart, and their lines wait in
  their logs for the returning session. Their followers - the Monitors that
  carry those lines into your turns - are stopped in step 6 and re-armed in step
  7. Stopping a daemon loses that buffering, which is what makes the restart
  lose nothing.
- **A claim you hold survives the restart**: the claim helper answers
  `ALREADY-YOURS` to the returning session (`/chat-transport`, *Claiming a
  request*). Do not release a claim on work you are about to resume.

## 2. Hand off in-flight work

**Assume everything this session started ends with it.** Subagents run inside
the session, and on systemd the service's stop kills its whole control group:
every subagent, background command, Monitor and server the session launched ends
at the `/exit`. Whatever survives it elsewhere runs unsupervised, against a
session that no longer exists.

**One mode: the handoff.** Send each in-flight subagent this instruction (a
message to a running subagent is delivered at its next tool round):

> Soft-restart: stop at the next safe point. Commit your work in progress on
> your own branch, following the install's commit conventions, and write the
> handoff note (`handoff.note`) at your worktree's root: what is done, what
> remains, and the exact next step - a command or an edit, not a direction. Do
> not commit the note. Report the branch, the commit and the note's path, then
> stop.

- A subagent with no worktree (a search, a review) gives its note as its final
  report, and you copy the note into the checkpoint.
- **Wait for every report before step 3.** A subagent still running at the
  `/exit` is killed mid-write, and its next step then exists nowhere.
- **Draining instead is allowed when everything in flight is minutes from
  done**: wait for each one to finish, read its result, and there is nothing to
  hand off. Waiting on work that is not minutes from done keeps the requester
  waiting for an update with no deadline; hand that work off.
- **Background commands and Monitors**: wait for one whose result is minutes
  away and read it; otherwise record its exact command, and the directory it ran
  in, for the checkpoint. A Monitor armed on a result that has not arrived dies
  with the context that would have read it.

## 3. Stop what dies with the service, and record how to start it

List every process this session launched that the service's stop will end - a
dev server, an emulator, a watch loop - each with **the exact command that
started it, byte for byte, and the directory it ran in**, so the relaunch is a
paste and not a reconstruction.

**A process a client has been pointed at comes back on the SAME address.** A dev
server whose host and port are baked into installed builds, a callback URL
registered somewhere else: relaunched on another port, it breaks every client
holding the old one, and nothing reports it. Record the address it serves, as its
clients were given it. Before running the teardown, check whether the teardown
removes what pins that address - a ports or slot file, a PID or lock file, a
claim the next start reads - and if it does, record what the relaunch needs to
take the same address again, or skip the teardown for that process and let the
service's stop end it. A pin that holds only while its process is alive is gone
either way, so for that one the record is the only route back. The install's
`CONTEXT.md` says which applies to its stack.

Then stop each one cleanly: run the scoped teardown (`stack.teardown_command`)
in each worktree whose servers this session started. It stops that worktree's
servers by their PID files and removes their runtime artifacts. A process ended
by the service's kill gets a signal instead, and whether it then cleans up after
itself is up to it. An empty `stack.teardown_command` means the install runs no
dev stack: skip the teardown, and still record each process.

**Never a machine-wide `pkill`.** That is `/restart`'s move, licensed only by an
imminent reboot; here it takes down every other session's stack for a restart
that concerns only you.

## 4. Write the checkpoint

Write `checkpoint.file`, a path relative to your state directory, in under ~40
lines:

- **Why**: a soft-restart from Claude `<running>` to `<installed>` (step 0's
  line), started at `<time>`, back by `<time>` (step 5).
- **The request**: the address of the thread it came from (`/chat-transport`,
  *Address grammar*), where step 7 posts "back".
- **The health agent notice**: the address of the message step 5 posts, so step
  7 answers it; `none` when step 5 skipped it.
- **Processes to relaunch** (step 3), in the order to start them, each with its
  exact command, its directory, and the address its clients were given, with
  whatever the relaunch needs to take that address again.
- **Handed-off subagents** (step 2): each one's id or name, its brief in one
  line, its branch, its commit, and its note's path - or the note itself, for one
  with no worktree.
- **Commands to run again** (step 2), each with its directory.
- **Uncommitted state** in each worktree you touched yourself (`git status
  --short`). Your own work is not auto-committed; it survives on disk, and the
  next session only needs to know it is there.
- **Open requests**: a pointer to your record of them, not a copy.

**The checkpoint goes in your state directory, never in your working
directory.** A session's working directory can be a shared checkout that must
never be written to: a file there shows in every other session's `git status`,
and the next bare commit anyone makes there publishes it.

**Nothing the return depends on goes in the session scratchpad**: not the
checkpoint, not a script a standing watch runs, not evidence a note points at.
A subagent's cleanup can and does delete the whole scratchpad. Move such a file
under your state directory (`state/artifacts/` for evidence, `/agent` section 3)
and point at it there.

**Point at the checkpoint from where a fresh session looks.** The service
relaunches with `--continue`, which restores this conversation, so the normal
return reads this step in its own transcript. When the service starts a fresh
session instead, nothing in it knows a restart happened: add an entry to the
record of open requests your charter reads at session start, naming the
checkpoint's path. The install's `CONTEXT.md` names that record.

Then run `sync`.

## 5. Tell the requester, and notify the health agent

**The heads-up**: one message in the request thread, saying you are
soft-restarting to take Claude `<installed>` and will post there when you are
back, by now plus `return.expected_minutes`, in the time format of `/agent`
section 4:

```bash
python3 "${CLAUDE_SKILL_DIR}/../agent/render_time.py" --at "$(( $(date +%s) + <return.expected_minutes> * 60 ))" --estimate
```

**The health agent notice**, when the fleet has one. `health_agent.address` is
where it takes messages, in the address grammar (`/chat-transport`, *Address
grammar*). An absent `health_agent`, or an empty `health_agent.address`, means
the fleet has none: skip the notice, and the heads-up is the whole of this step.
Skip it too when you are the health agent (`health_agent.name` is you). Otherwise
post ONE message there, through your own transport's posting recipe, carrying:

- which agent and which service unit (`service.unit`), and that this is a
  soft-restart: an intentional `/exit`, not a crash;
- why: the version being adopted, from and to;
- the expected return time, the same one the heads-up gave;
- what "came back" looks like: the unit active, the session at its ready
  prompt, its followers re-armed - and that you will answer this message when you
  are back.

**It is a notification: do not wait for an acknowledgement, and do not abort when
none comes.** What the health agent does with it is up to that agent's owner, and
this skill depends on none of it. A post that fails (your bot is not in that
channel, say) goes in the checkpoint and in the "back" message; it does not stop
the restart.

Add each posted message's address to the checkpoint.

## 6. The `/exit`

Reuse the detached sender `/self-compact` owns; this skill keeps no copy of it.
First the dry run, which spawns nothing and prints the pane it would type into -
it must be your own session:

```bash
python3 "${CLAUDE_SKILL_DIR}/../self-compact/compact.py" --message /exit --no-wake --dry-run
```

Then stop every Monitor and background command the session still has running,
your followers included, with the harness's task-stop tool (TaskStop), as the
last thing before the real send: a session with background work running can
meet the `/exit` with an exit dialog instead of exiting (*Failure modes*).
Nothing is lost by it: the daemons behind the followers keep running and buffer
their lines, and step 7 re-arms the followers.

Then, as the LAST tool call of the turn, the real one:

```bash
python3 "${CLAUDE_SKILL_DIR}/../self-compact/compact.py" --message /exit --no-wake
```

- The sender outlives the turn and types `/exit` and Enter into your pane a few
  seconds after the turn ends (`/self-compact` section 1 says why a turn cannot
  type into its own prompt). A turn that runs on past the spawn defeats the
  delay, so end it with one line naming the checkpoint's path and this skill's
  step 7: that line is what the resumed transcript shows next.
- `--no-wake`: there is no turn to wake. The session is replaced by the one the
  service starts, and the service's start handshake types the boot message into
  that one.
- **Only the session that owns the pane runs this** (`/self-compact` section 2).
  A subagent resolves its parent's pane, and an `/exit` from there ends a session
  that is waiting on that very subagent.

What follows is the service unit's own contract, which this skill relies on and
does not change. On systemd the clean exit ends the tmux session,
`Restart=always` starts the unit again after `RestartSec`, the pre-sleep runs,
`claude --update` and then `claude ... --continue` start the session on the
installed binary with this conversation restored, and the start handshake types
the boot message. On macOS the session supervisor exits 1 when the session ends,
and launchd relaunches every exit but 0. **Do not restart the unit yourself
instead**: in the system form the agents user cannot, and in the user form the
restart kills the turn that issued it, mid-command.

The unit's command ends `claude ... --continue || claude ...`. The process the
`/exit` ends returning 0 ends the shell, and the unit restarts; should it return
non-zero, the shell starts the fresh half in the same pane instead, on the
installed binary but with no conversation and no boot message. Step 4's pointer
is what that session finds.

## 7. On return

The session reading this after the restart does these in order, each once:

1. **Re-arm your followers**, as the boot message says, before anything else:
   an unarmed follower is silent and reads as a quiet day.
2. **Read the checkpoint** (`checkpoint.file` in your state directory). It holds
   every list the next steps work through.
3. **Relaunch the listed processes**, in the checkpoint's order, each with its
   recorded command in its recorded directory, and confirm each one is up on its
   recorded address. This is the first work resumed, before any subagent and
   before "back": a requester told "back" tries the server next. A process that
   cannot get its recorded address back is named in the "back" message with the
   address it is on now, never left for a client to discover.
4. **Confirm the restart took**: step 0's check reads `NONE`, and its running
   version is the one the checkpoint was adopting, or newer (`claude --update`
   takes the latest at relaunch). `PENDING` means the old process is still
   running: the `/exit` did not take (*Failure modes*).
5. **Resume each handed-off subagent**: where the harness can continue a stopped
   subagent with its context, continue it by its id with a message naming its
   note; otherwise, or when that fails, spawn a fresh one whose brief is the
   note. Run the recorded commands again.
6. **Post "back"** in the request thread, with the version now running; and when
   step 5 notified a health agent, answer that notice the same way, so it can
   stand down.
7. **Delete the checkpoint**, its session-start pointer, and each handoff note
   once its work has resumed: they are one-shot state, not documentation. Delete
   each by its literal path, written out in the command, never through a
   variable: a variable path in a loop is the shape the harness's delete guard
   stops on, and in a session nobody is watching that prompt blocks it until
   someone answers.

## Failure modes

- **Step 0 reads `NONE` or `NO VERDICT`**: no restart. Report the line.
- **The `/exit` did not take** - the session is still there at its next turn and
  step 0 still reads `PENDING`. Text already in the input box is prepended to the
  typed `/exit` (`/self-compact` section 4), and a dialog on screen takes the
  keys. Re-arm your followers first, since step 6 stopped them; then read the
  pane, clear the cause, and send again. Do not post "back".
- **The exit dialog takes the `/exit`.** Claude Code asks before it exits a
  session with background work running: the pane reads `Background work is
  running`, lists what will stop (`1 monitor`), and offers `1. Exit and stop
  tasks`, `2. Move to background and exit` and `3. Stay`, with the cursor on the
  first. That is measured on the double-Ctrl-C exit path (Claude Code 2.1.266,
  `/agent-revive` step 3 and its *Traps*); whether a typed `/exit` raises the same
  dialog has not been measured, and step 6 stops every Monitor and background
  command first so that it has nothing to ask about. Nothing answers the dialog on
  its own, and a stall watchdog's automatic "no" can choose Stay: the restart then
  silently does not happen while the requester waits for "back". The remedy is to
  read the pane and choose `1. Exit and stop tasks`, never `2. Move to background
  and exit`, which by its own label keeps the tasks running after the session that
  owned them is gone.
- **The unit does not relaunch, or the new session stalls at a first-run or
  sign-in prompt**: the session cannot report this itself. The return time in the
  heads-up is what tells the requester something is wrong, and the health agent
  notice, where there is one, is what lets that agent step in. `/agent-revive` is
  the procedure for a stalled session.
- **A fresh session starts instead of the resumed one**: step 4's session-start
  pointer leads it to the checkpoint.
- **A newer version lands during the handoff**: harmless. `claude --update` takes
  the latest at relaunch, and step 7 reports what is running.
- **A subagent cannot commit** (a hook refuses the work-in-progress commit): its
  note says so and names the uncommitted files, which survive on disk in its
  worktree.

## Difference from `/restart`

| | `/restart` | `/soft-restart` |
|---|---|---|
| Scope | the whole machine | this agent's session |
| Other sessions | restarted with it | untouched |
| For | what needs a boot: new MCP servers, PATH and profile, config | a Claude binary already installed under a running session |
| Ended by | `service.reboot_command` | `/exit` typed into its own pane by the self-compact sender |
| Dev stack | the scoped teardown, then machine-wide `pkill` patterns | the scoped teardown only, each process's command recorded and relaunched |
| In-flight subagents | stopped | handed off to notes on their branches, or drained when minutes from done |
| Who is told | the user, in chat | the request thread, and the health agent when there is one, before and after |
| Comes back by | the boot starting every unit | the service relaunching on the clean exit |

## What CONTEXT.md carries

The install's `CONTEXT.md` for this skill says, for the agents and people of that
install:

- who may ask an agent to soft-restart, or where the install says so;
- the health agent, when the fleet has one: who it is, how it is reached (what
  `health_agent.address` names, in words), and any precondition of reaching it,
  such as the restarting agent's bot being a member of its channel;
- the record of open requests each agent's charter reads at session start, which
  step 4's pointer goes into;
- the service shape behind `return.expected_minutes` - the pre-sleep and the
  start timeout - so a reader can derive the number again.

## Measured

- **2026-11-13**, Linux, Claude Code's native install, a session running 2.1.286
  with 2.1.323 installed: the session's claude process is the one child of its
  pane's shell; its `/proc/<pid>/exe` reads `<versions dir>/2.1.286 (deleted)`
  while `claude --version` answers 2.1.323; the pane shows the banner,
  right-aligned, on the line directly above the input box's top rule.

## Its test

```bash
python3 "${CLAUDE_SKILL_DIR}/pending_update.test.py"
```

Offline, with no tmux server, no `ps`, no `/proc` and no claude binary touched:
the banner read on its line and not elsewhere, the session process, both version
readings and their failures, every verdict, the CLI's lines and codes, and that
step 0's table above names each line the script prints. Its header names the two
controls that hold it up; read that before editing it.

## What is NOT here

Whether a request to soft-restart is yours to act on, and who may make one, are
your charter's and the install's `CONTEXT.md`'s. This file is the mechanism and
the order.
