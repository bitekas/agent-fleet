---
name: self-compact
version: 1
description: >
  Compact your own context window: the preflight that has to be true before you
  discard context, and the detached sender that types `/compact` into your own
  session after your turn has ended, because a turn cannot type into the prompt
  that is running it, and then types a wake line that starts the first turn after
  the compaction, because the compaction itself starts none. Load when a task is finished and you are about to compact,
  when a compaction has to be scheduled around work still in flight, and before
  changing anything about how the sender reaches the session.
requires_install: false
---

# self-compact

## 1. Why this needs a detached process at all

An agent cannot type `/compact` into its own prompt from inside a turn. The turn is the
thing that is running, and the prompt only accepts a command once it is idle. Whatever
sends that command therefore has to be alive **after** the turn ends, and ending a turn
signals the turn's children, so it cannot be one of them either.

`compact.py` spawns that sender: a process double-forked into its own session and
process group, with its stdio closed and SIGHUP ignored, which waits a few seconds for
the turn to finish and then types the message into the agent's own tmux pane and presses
Enter. The same process then waits a further `--wake-delay` and types a second line, the
wake line, with its own Enter. The parent prints the sender's pid and exits immediately,
so the agent's turn is free to end, which is exactly what the sender is waiting for.

**The wake line is what makes "the first turn after the compaction" real.** A
compaction's output is a local command record, not a user turn: when it finishes, the
session sits idle at its prompt and no turn runs. Nothing else wakes it: after the
compaction the session's watchers and monitors are stopped (section 5), so no inbound line
arrives to start a turn. Without the wake line the session stays idle, with its watchers
down, until something outside it types into the pane. The wake
line is ordinary text, so it is submitted as a user message and starts an ordinary turn,
and that turn is where the post-compaction duties run.

**It escapes the process tree and deliberately not the cgroup.** Where an agent session
runs as a service that kills by control group, a service restart takes down everything
the session spawned no matter what the sender does about its parentage. That is correct
here: the pane the sender types into belongs to the same session, so a sender that
outlived the service would be typing into a pane that no longer exists, or into whatever
took it over. Surviving the TURN is the requirement. Surviving the SERVICE is not one,
and chasing it would be a bug.

**Nothing is passed to it and nothing needs to be.** The caller's own environment is the
credential: `$TMUX` names the socket the session is already connected to, and the pane it
is running in answers "which session am I". `$TMUX_TMPDIR` covers a caller outside tmux.
There is no key, token or session name to hand over.

**Precondition: the agent's Claude Code session runs inside a tmux session started by
its service unit.** That is the fleet's session contract, and it is what makes the
above true: the unit starts tmux (exporting `TMUX_TMPDIR` when it uses a non-default
socket directory) and runs Claude Code in it, so every shell the agent opens is inside
that tmux session and `$TMUX` is already set. A session started directly in a terminal
has no pane to type into, and the script refuses rather than guessing.

## 2. The preflight, which is the part no script can do

Compaction discards context. Everything below is the agent's own judgement before it
runs the script, and none of it is checkable from outside the session:

- **No subagent is in flight.** A result that arrives after compaction lands in a context
  that no longer holds the reason it was commissioned.
- **No background command is still running.** A build, a suite, a capture: wait for it
  and read its result first. Compacting is not a way to stop waiting.
- **No Monitor is armed on work that has not arrived**, and nothing scheduled is about to
  fire into this session with state only the current context can interpret.
- **Nothing is owed to a person.** A report, an answer, a blocker ping: send it first. A
  compaction is invisible to them, so an unsent answer just never arrives.
- **Everything worth keeping is written down.** Whatever the next turn will need has to
  be in a file before the context holding it is summarised: the knowledge base for
  project facts, the agent's own memory for facts about itself, its state directory for
  positions and ledgers, its blockers file for what it is waiting on.

**Only the session that OWNS the pane runs this, and that rule is the whole
protection: there is no guard behind it.** A subagent inherits its parent's `$TMUX`, so
what it resolves is the parent's pane; compacting from a subagent discards the context of
a session that is mid-turn waiting for that very subagent to return.

**Do not add an environment-variable guard for this without reading the variable in
BOTH a root turn and a subagent turn.** The obvious marker is measured and does not
work: `CLAUDE_CODE_CHILD_SESSION` is set to `1` in a subagent's shell and set to `1` in
the pane-owning session's own shell as well, so it marks a Bash tool call rather than a
subagent, and a guard keyed on it refuses the one caller the script exists to serve. The
Claude process's `/proc/<pid>/environ` holds its EXEC-TIME environment and never the
per-tool-call variables the harness injects, so reading it from a subagent infers a fact
about the parent instead of measuring it there. The two session-id variables are not a substitute either: they hold different
namespaces (a local uuid and the hosted session id) and therefore differ in a root turn
too. A guard whose discriminator has not been read on both sides is worse than none,
because it is trusted.

## 3. Running it

```
"${CLAUDE_SKILL_DIR}/compact.py"               # /compact in 3 s, then the wake line 120 s later
"${CLAUDE_SKILL_DIR}/compact.py" --no-wake     # /compact only, nothing wakes the session
"${CLAUDE_SKILL_DIR}/compact.py" --dry-run     # print the resolved target and both sends, spawn nothing
"${CLAUDE_SKILL_DIR}/compact.py" --wake-message "<the install's wake text>"
```

**The install's own wake text, when it has one, is in this skill's `CONTEXT.md` in the
install context** (`fleet where self-compact CONTEXT.md` prints its path), and is passed
with `--wake-message`. Without it the generic default below is typed.

The sender makes two sends, in order, from one process:

1. `--delay` seconds after the spawn, the message, then Enter.
2. `--wake-delay` seconds after that, the wake line, then Enter.

Each send is two `send-keys` calls, the literal text (`-l --`) and a separate Enter (section 4).
The second wait is measured from the first send, so it is the time the compaction has to
finish before the wake line arrives.

Options: `--message` (default `/compact`), `--delay` seconds (default 3),
`--wake-message` (default `Compaction done. First: re-arm the monitors your charter
names. Then re-read your charter and the agent rules, pick up what you were holding, and
stand by.` - `compact.test.py` compares this quotation with the script's default),
`--wake-delay` seconds (default 120), `--no-wake`, `--socket`, `--tmpdir`, `--target`,
`--dry-run`.
Exit 0 means the sender is spawned: it prints the sender's pid and, unless `--no-wake`,
a second line saying when the wake line will be typed. Exit 2 is a
refusal with one line saying why, and it refuses rather than guesses whenever the target
is ambiguous, unreachable, not the caller's own session, the message or the wake line is
empty or carries a newline, or either delay is negative. With `--no-wake` the wake
options are not read. An empty `--wake-message` is a refusal rather than a quiet
`--no-wake`: an unset variable expanding to nothing would otherwise drop the one turn
that re-arms the session, with nothing printed.

**Then end the turn.** The delay is the margin for that, so a turn that runs on for
another minute after the spawn defeats it. Spawn the sender as the last thing the turn
does.

**After the compaction, the first-turn duties run on the turn the wake line starts.**
The compaction ends the session's Monitors - the daemon followers among them; the daemon
services themselves keep running and their lines wait in the logs - so that turn is what
re-arms them, and the wake line says so first. A compacted context is not the context
that read the charter, so on that turn the charter and the standing agent rules are read
again from their files rather than from what survived the summary. With `--no-wake`
there is no such turn until something else types into the pane, so use it only when
something else will.

## 4. Traps

- **`--` before the message is load-bearing.** Measured on tmux 3.6: without it,
  `send-keys -l "-bar"` dies with `unknown flag -b` and types nothing, while the caller
  still sees a spawned pid and reads it as delivery. `-l` is equally load-bearing in the
  other direction: it makes the text literal, so `/compact` goes in as eight characters
  rather than as a key sequence.
- **Enter is a second, separate `send-keys` call.** Under `-l` every argument is
  literal, so an `Enter` in the same call types the word.
- **A slash command typed this way runs; it is not left sitting in the completion
  menu.** The revival skill measures the same two-call pattern opening the login menu
  from `/login` on this Claude Code line.
- **A socket path is a unix socket path, capped near 108 bytes.** A `--socket` under a
  deep scratch directory fails with `File name too long`, which reads as a missing server
  rather than as a path problem.
- **A wake line that arrives before the compaction finishes has not been measured.** The
  120 s default is sized so that it does not; a session with a context large enough to
  take longer is given a larger `--wake-delay`.
- **Text already sitting in the input box is prepended to the message.** The sender
  types; it does not clear the line first, deliberately, because clearing it would throw
  away whatever a person or another tool had half-written there. The result of the
  collision is visible and harmless - the concatenated line is submitted and is not a
  command - so the recovery is to look at the pane and send again.
- **This skill must never be named after the command it types.** A project skill
  whose name equals a built-in slash command SHADOWS the built-in: typing `/compact` at
  the prompt then loads the skill's own `SKILL.md` as a skill invocation instead of
  running the context compaction, so the sender delivers, the command executes, and
  nothing is compacted. Every visible sign is of success, which is why the name is the
  fix rather than a note. That is what `self-compact` is for, and renaming it to the
  command's own name breaks it silently.
- **Never test with a real `/compact`.** Use `--message ping` against a throwaway tmux
  server (`tmux -S <short path> new-session -d -s probe 'cat > <file>'`), where the file
  shows both the text and the Enter that followed it. Testing against a live session
  costs that session its context, which is the one failure this skill cannot undo.

## 5. Measured

- **2026-10-03**, tmux 3.6: `compact.py --message ping --delay 1 --wake-delay 3` against a
  throwaway server (`tmux -S /tmp/cfu-s new-session -d -s probe 'cat > <file>'`) leaves
  the file holding `ping` and the default wake line, each ending in the newline its own
  Enter submits, 4 s after the spawn.
- **2026-10-01**, Claude Code 2.1.286: `/compact` typed by the sender compacts the
  session and starts no turn; without a wake line the session stays idle, its monitors
  stopped, until something types into the pane.
- **2026-09-13**, Claude Code 2.1.266 on tmux 3.6, the whole loop end to end: `compact.py`
  with its defaults, run from the pane-owning root session, resolves its own pane from
  `$TMUX`; after the turn ends the sender types `/compact` into the idle prompt, Claude
  Code runs the BUILT-IN compaction, and the session comes back with a compaction summary
  and re-reads its charter and the `agent` skill from their files. That summary in the next
  turn is what distinguishes the built-in running from a skill of the same name being
  loaded.
- **2026-09-12**, Claude Code on tmux 3.6: `compact.py --message ping --delay 3`
  resolving its own pane from `$TMUX` delivers `ping` to the session's input box and the
  Enter submits it; the session picks the message up and processes it. This is the whole
  delivery path except that the message is `ping` rather than `/compact`.
- **2026-09-12**: a sender spawned with a 20 s delay is reparented to pid 1 in its own
  session and process group, survives the exit of the shell that launched it, and
  delivers afterwards.
- **2026-09-12, from the pane-owning session**: with a project skill named `compact`
  installed, the delivered `/compact` resolves to that skill and loads its `SKILL.md`
  into the turn; nothing is compacted. A skill's name shadows a built-in slash command
  of the same name, so this skill is `self-compact` and the message it types is
  `/compact`.
- **2026-09-12, read on both sides**: `CLAUDE_CODE_CHILD_SESSION=1` in a subagent turn
  and `CLAUDE_CODE_CHILD_SESSION=1` in the root turn that owns the pane. That is why no
  environment marker gates anything here, and the test carries a regression pin that
  reds by name if one is added.

## 6. Its test

```
python3 "${CLAUDE_SKILL_DIR}/compact.test.py"
```

Offline, no tmux server needed: target resolution from `$TMUX`, from `$TMUX_TMPDIR` and
from the overrides, every refusal (the wake line's included), the exact argv and step
list the sender will run (both sends, their order and their waits, with and without
`--no-wake`), the dry run, and the double fork exercised against a python one-liner
rather than tmux, timing the wait before the wake step. The file's header names the
two controls that hold it up and what each one costs if it is removed. Read that before
editing it.

## 7. What is NOT here

**Whether and when to compact is policy and lives with the agent's operating rules**, not
in this file. This skill is the mechanism and the preflight.
