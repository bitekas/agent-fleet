> EXAMPLE lesson - shows the format and the kind of knowledge a store holds. Not part of any install's store.

---
title: Treat every subagent as single use
topic: agents
---

**A finished subagent's context is not reliably available for resuming.** A
message sent to it can fail with a "no transcript found" error minutes after it
completed, inside the same session. A send resumes an agent only while its
transcript exists, and often it does not.

**Resume failures land at the worst moment by construction.** You only want to
resume when a person has just reacted - a revert request seconds after an edit,
a revision list minutes after a delivery - so the refusal always arrives with
someone waiting.

- **Never plan a multi-round task around resuming one agent.** Every round
  starts cold.
- **The artifact carries the context, not the agent.** Land the work where it
  lives, with a header recording the non-obvious decisions, so the next round
  reads the file instead of an agent's memory. Work left in a scratch directory
  dies with the transcript.
- **Write follow-up orders self-contained**: restate the constraints, the traps
  and the rules that must not regress, even when the agent "already knows". If
  the resume succeeds the restatement is cheap; if it fails the order still
  works. Restate context; cite mechanics by pointing at the skill that owns them.
- **Durable learnings belong in a store that outlives any transcript**, not in
  the agent.

The other half is the report: once the transcript is gone, the subagent's final
report is the only surviving record, so it names what changed, where, and what
was deliberately left alone.
