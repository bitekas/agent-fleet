> EXAMPLE lesson - shows the format and the kind of knowledge a store holds. Not part of any install's store.

---
title: A group signal takes the whole group, and pgid 1 is every process the user owns
topic: machine
verify: kill(2) - a negative pid addresses the process group of that number, 0 the caller's own group, and -1 every process the caller may signal. Read it; do not probe it live
---

`kill -- -N`, `kill -TERM -- -"$pgid"` and `pkill -g N` address a process
**group**, not a process. The argument is never checked against a process the
caller owns: whatever number arrives is signalled as a group id, and three
values are catastrophic rather than merely wrong.

- **`1`** is not a group. `kill(-1, sig)` means *every process the caller may
  signal*. Where every agent session, its tmux server, the user's service
  manager and the user's login sessions all run as one user, a computed pgid of
  `1` stops all of them in the same second.
- **`0`** means *the caller's own process group*. The defensive-looking
  `pkill -g "${VAR:-0}"` is a self-destruct that fires exactly when `VAR` came
  back empty: the script kills itself mid-run and its log simply stops, which is
  indistinguishable from a hang.
- **Empty** is the one value that fails loudly - `kill -- -""` is rejected - and
  it becomes dangerous only when a `${VAR:-0}` default turns it into `0`, or
  arithmetic turns it into `1`. Do not rely on the rejection: `pkill -g ""` does
  not share it.

**Nothing logs it.** The signal needs no privilege, so no audit log, `sudo` or
service manager records who sent it; the journal shows processes stopping and
nothing about why. Every process of one user stopping at one instant is the
fingerprint of an unprivileged broad kill. The caller is found in the run logs
of whatever was executing at that moment, never in the system's own records.

## Three conditions, all of them, before any group form

**Write the guard where the pid is built, not where it is used.**

1. **The value is a positive integer that is not `1`.** Reject empty, `0`, `1`
   and anything non-numeric before the command is built:

       case "$g" in ''|0|1|*[!0-9]*) return 0 ;; esac

2. **The group belongs to a process this script created, and that process leads
   it.** Read the child's pgid (`ps -o pgid= -p <pid>`) and require
   `pgid == pid`. Only a leader this script started with `setsid` licenses the
   group form.
3. **A number in a pid file is not evidence of (2).** Pids are recycled, and a
   recycled number belonging to a process that called `setsid` passes a
   `pgid == pid` test read from the file alone. Confirm the live process is
   yours by something only yours has - its command line, its working directory -
   before the pgid test licenses the group.

When any condition fails, **narrow** to `kill "$pid"`: signal the one process,
or nothing. Broadening a signal that was just refused is how the refusal
becomes the incident.

## A control must not prove reachability by doing the damage

The tempting negative control - run the unguarded statement against a fixture
and assert the fixture died - is the defect executed on purpose, with its blast
radius decided by whatever the fixture's pid resolves to. If the fixture fails
to start and the variable lands at `1`, the control succeeds across the whole
login. Prove it instead with a sentinel the test starts in its own session and
refuses to signal unless `pgid == pid`, or with a dry-run seam that records the
pgid that WOULD have been signalled.

**The constraint belongs in the work order, not only in the review.** An agent
told to "reproduce the kill path" writes the unguarded statement, because that
is what it was asked for.
