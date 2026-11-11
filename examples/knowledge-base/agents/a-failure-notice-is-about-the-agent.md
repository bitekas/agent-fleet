> EXAMPLE lesson - shows the format and the kind of knowledge a store holds. Not part of any install's store.

---
title: '"Agent failed" says nothing about whether the work shipped'
topic: agents
---

A task-failure notification is a statement about the **agent**, not about the
**work**, and it can arrive long after the run with nothing in it marking it as
historical.

**Death after completion is common.** A long-running agent often dies during
its *report*, which is the cheapest phase to lose and the one that produces the
failure notice. The heavier the task, the likelier "failed" means "finished,
then fell over". Acting on such a notice re-runs completed work, which for a
change that was already applied is the destructive direction.

- **Read the timestamps before the status.** The first and last entries of the
  agent's transcript bound when it ran. A notice with no date is not evidence of
  recency.
- **Measure the landing, not the agent.** Search the landing branch for the
  change's identifying symbol, then look for leftover branches and worktrees;
  the change present and neither leftover is the sign the work was closed out.
- **Check whether the people were already told.** The relay is usually the part
  that was lost, so read the message history rather than trusting recall.
- **Verify the safety properties of what shipped, not the whole change.**
  Spot-check what would hurt a user; do not re-review settled work.
- **Do not reopen a documented deviation.** Shipped, commented and safe in
  behaviour outranks matching the order word for word.

A failure notice says nothing about whether the agent is still **running**
either. Liveness is read from the artifacts the agent writes - its transcript
growing, its output files changing - and an ambiguous reading defaults to
alive, because the answer to an agent read as dead is to kill it.
