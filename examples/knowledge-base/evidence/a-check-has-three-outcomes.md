> EXAMPLE lesson - shows the format and the kind of knowledge a store holds. Not part of any install's store.

---
title: A check has three outcomes, and inconclusive is neither of the other two
topic: evidence
---

**PASS / FAIL / NO VERDICT.** A check that cannot reach its subject must report
that it does not know, because the verdict it would otherwise manufacture is
always the comfortable one. Pass-or-fail is the wrong shape for any check that
can die before it reaches its subject: not a git repository, a commit missing
from a shallow clone, a comparison ref that does not exist, a dependency the
standard install does not cover.

The meaning drifts in both directions, and both drifts are silent.

## Inconclusive read as pass

A run that never executed is not a smaller green. "Skipped because a filter
excluded me" and "my instrument is broken" are structurally different messages,
both correctly inconclusive, and neither is a pass. The tempting repair - make
the inconclusive exit quieter because it fires on a healthy tree - silently
disarms every instrument-fault signal in the suite while looking like a small
ergonomic fix. Make the reasons distinguishable in the output instead.

A sample coarser than the event is inconclusive too. A loop that takes a
screenshot every two seconds cannot see a one-second toast; two identical
samples say nothing about whether the toast appeared.

## Inconclusive read as fail

A runner that maps "could not run" onto FAIL reports *"your change broke this"*
when the truth is *"your change was never tested"*. A script whose unhandled
exception exits 1 collides with the exit code reserved for a real violation.

**When a check reports a failure, separate "the subject is wrong" from "the
instrument never ran" before acting.**

## Require positive evidence that the subject was reached

A check that runs a probe against deliberately broken copies of its subject has
the same three outcomes - the mutant behaved as predicted, it misbehaved, or the
probe never ran - and comparing exit codes alone collapses the third into the
second: a probe that dies at load time with exit 1 "matches" every mutant
predicted to exit 1.

1. **The probe prints one pronouncement line on every exit path** - `PASS`,
   `FAILED` or `NO VERDICT` at the start of a line - and a run that printed none
   is NO VERDICT, whatever killed it. A list of known crash messages goes stale
   the day the probe finds a new way to die; an absent pronouncement does not.
2. **The harness tests its own pronouncement matcher before scoring anything**:
   it must accept a real sample of each banner and reject a real crash text. A
   matcher that drifted to match nothing, or to match the crash, is caught
   there, and that self-test failing is itself NO VERDICT.
