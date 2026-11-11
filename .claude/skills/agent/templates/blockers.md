<!--
  BLOCKERS - the scratchpad of what this agent is waiting on.

  WHAT IT IS: one table of live blockers. What is expected, from whom, why it
  matters, where to reach them, when it was asked, and when they were last
  pinged. It answers exactly one question: who owes me what right now.

  WHAT IT IS NOT: a ledger. Nothing is archived here, nothing is struck
  through, no outcome is recorded. A row exists only while you are still
  waiting for that one thing, and is DELETED the moment you are not - whether
  it was resolved, became irrelevant, or went stale. The record of what was
  asked, decided and shipped belongs to the agent's own ledger, not here.

  A stale row is removed AND the person is told, in these words:
    "I will not ask you about <X> because it is not relevant anymore."
  Stale means the need behind the ask has lapsed or been superseded. It is the
  agent's judgement, never a timer.

  The blockers timer reads this file, so `Where` must be an address something
  other than this session can act on, in the chat-transport grammar:
  `<transport>:channel:<conversation>`, with `:<thread>` for a thread, or
  `<transport>:dm:<conversation>`.

  Rules, cadence and the timer: the `agent` skill, "Blockers".
-->

# Blockers

| Expected | From | Why | Where | Requested | Last pinged |
|---|---|---|---|---|---|
