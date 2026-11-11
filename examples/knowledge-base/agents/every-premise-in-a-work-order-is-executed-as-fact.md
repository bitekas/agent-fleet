> EXAMPLE lesson - shows the format and the kind of knowledge a store holds. Not part of any install's store.

---
title: Every premise in a work order is executed as fact
topic: agents
---

**A premise stated as background is the most dangerous sentence in a work
order, because nothing marks it as a claim.** An agent can check a cited
inference; it cannot check a bare assertion, so it builds on it.

- **Label a measurement as yours, with its method.** "I read one pixel and the
  fill looked flat; verify before patching" invites the check. "The fill is
  flat" forecloses it, and a wrong premise produces a second defect while
  closing the first.
- **Say where a claim came from.** An inference from a label - "the page is
  titled Settings, so this is the settings screen" - presented as a fact about
  where code lives produces a task that completes successfully while moving two
  sources further apart.
- **A finding relayed from another agent is still a claim, and passing it on
  as an instruction launders it into an order.** Relay it as "the audit
  measured X; decide whether it means Y", never as "do Y".
- **Say in the order that the agent may refuse.** A wrong relayed finding is
  stopped only by an executor who believes it is allowed to disagree.

**Cleanups are where this bites hardest**, because a wrong premise there reads
as tidiness. A layer with no visible fill may be the operand of a boolean
shape, so deleting it deletes the shape; render bounds larger than a frame may
be a shadow a test asserts on, so clipping the frame removes what the test
checks. An order that says "remove the unused layers" states as fact that
someone has established which ones are unused.
