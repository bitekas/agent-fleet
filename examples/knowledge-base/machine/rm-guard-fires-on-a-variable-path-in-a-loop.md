> EXAMPLE lesson - shows the format and the kind of knowledge a store holds. Not part of any install's store.

---
title: Claude Code's rm confirmation guard fires on a variable path inside a loop
topic: machine
verify: from the Bash tool of a session nobody is attending, run `for t in a b; do rm -rf "$D/$t"; done` with D a scratch path - it prompts; the same deletions written out literally do not
---

Claude Code carries a confirmation guard on an `rm` whose path is built from a
variable, announced as `Dangerous rm operation on possibly-empty variable path`
and explicitly not allowable by any permission rule. In an unattended session
the tool call then blocks forever, and a blocked session looks exactly like one
that is ignoring you: its watchers keep running and keep accepting messages.

**The shape that fires it is a variable path inside a loop body:**

```bash
for t in t1 t2 t3; do rm -rf "$D/$t"; done     # prompts, every time
```

**The same deletions with the paths written out literally go through
unprompted**, and a variable path outside a loop does not fire it either. It is
the loop-plus-variable combination that is load-bearing.

- **Write `rm` paths out literally**: `rm -f /tmp/scan/*.txt`, or
  `rm -rf /tmp/scan` when the whole directory is yours. Never `$VAR/...`, and
  never inside a loop over a variable base.
- **A subagent's cleanup step is written literally in its brief.** The agent
  that meets the prompt is the unattended one, and it cannot rewrite the command
  it was handed.
- **Reach for the whole-directory form because the directory is yours, never
  because the narrower command was refused.** Broadening a command that just
  failed is a separate hazard: a broad delete takes what the glob matches, not
  what you meant.

## A second prompt: rm inside shell text the guard cannot parse

A different confirmation fires when a Bash call contains `rm` anywhere inside
script text the guard cannot check statically:

- a nested `bash -c '...'` whose body mentions `rm`, or one in the same call as
  an ordinary top-level `rm`;
- a process substitution such as `source <(sed ...)` in the same call as `rm`;
- a heredoc that WRITES A FILE whose content merely contains `rm` text, such as
  a brief carrying literal cleanup lines. The `rm` never runs, but the guard
  sees it and cannot prove that.

The consequence is the same: an unattended session blocks.

- **A file whose content contains command text is written with the Write tool,
  never through a Bash heredoc or `echo`.**
- **An `rm` goes in a Bash call of its own, with a literal path and nothing else
  in the call**, so no other part of a compound command can make it
  uncheckable.

A stall watchdog that answers such a prompt with "no" is a net under a blocked
session, not a licence to write the command that blocks it.
