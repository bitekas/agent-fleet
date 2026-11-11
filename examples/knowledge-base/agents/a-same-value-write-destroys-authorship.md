> EXAMPLE lesson - shows the format and the kind of knowledge a store holds. Not part of any install's store.

---
title: A same-value write still destroys authorship
topic: agents
---

**Before writing a state pointer, read whether it is already in the desired
state.** "Same value, therefore harmless" is false wherever the write also
records *who* made it.

A pointer carrying `setBy`, `updatedBy`, `lastModifiedBy`, a pinned message or
a status field records authorship alongside the value. Writing it again with an
identical value changes nothing observable and **overwrites the record of a
person doing it**, so the audit trail says an agent did what a person did - the
exact confusion the provenance field exists to prevent, produced by the
operation that looks like a no-op.

- **Read, then write, on any pointer that carries authorship.** Where the value
  already matches the goal, do not write: report that it is already done, and
  by whom. That report is more useful than the write.
- **The dangerous case is the one that looks idempotent.** A write that changes
  no behaviour reads as free, so nobody guards it. Ask what else the write
  stamps.
- **Put the precondition in the work order.** A subagent cannot infer a
  precondition nobody stated, and "a person did it while you were working" is an
  ordinary race wherever a person can reach the same control. Name the outcome
  in the brief: *"if it is already done, stop and tell me who did it."*
- **Stamp the actor that performed the write.** An agent writing on a person's
  authorization records an automation identity, never the person's.
- **Tell the person whose action was erased**, plainly and at once.
