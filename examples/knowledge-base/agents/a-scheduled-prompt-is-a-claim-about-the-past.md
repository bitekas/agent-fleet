> EXAMPLE lesson - shows the format and the kind of knowledge a store holds. Not part of any install's store.

---
title: A scheduled prompt is a claim about the past
topic: agents
---

**An instruction written to fire later was written in a world that no longer
exists by the time it fires.** Read every scheduled prompt as a claim about the
past and re-derive before acting, especially the ones that look like routine
chores.

## A prompt that asserts a value hands you a recurring false premise

**A scheduled prompt instructs a MEASUREMENT - "read the clock", "re-read the
ledger" - and never states a value.** Anything written into a timer, a work
order or a template is read later as given, by a reader with no idea it was a
guess. A job that opens with "it is about 10:00" fires with jitter and stamps
every record it writes with that error; each entry is consistent with the next,
so nothing looks wrong.

- **Fix the generator, not the output.** Correcting the bad records leaves the
  job to hand over the same premise again.
- **Never type a clock time you did not read this turn**, and prefer an event's
  own timestamp to the wall clock.

## Its POINTERS are the dangerous half, not its facts

**A stale fact gets contradicted by the world**: you check it, the answer
disagrees, the prompt corrects itself. **A wrong identifier is never
contradicted - it just succeeds.** A conversation or user id naming the wrong
person still returns success, and the message lands on someone with no
context, with nothing erroring anywhere.

- **Resolve every identifier a stored prompt hands you before writing through
  it.** It is one lookup.
- **Carry a correction into the replacement job**, naming both identifiers and
  which is which. A re-armed job inherits the errors of the one it replaces.

## A recurring job is worse than a one-shot

A stale one-shot misfires once, visibly. **A recurring one keeps acting on a
world that has moved, unattended, and its output looks normal every time.**

- **When a decision reverses, sweep the SCHEDULED surface**, not only the
  records and the messages already sent. Scheduled jobs are where the old
  instruction still has hands.
- **Write the reversal into the replacement job** rather than silently deleting
  the stale clause. A later reader who finds no caveat cannot tell "considered
  and rejected" from "nobody thought of it", and helpfully adds it back.
