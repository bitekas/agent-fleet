# Agents

Running a fleet of AI agents: handing work to one, reading the signals it
emits, arming work that fires later, and keeping several writers out of each
other's way. How a particular tool is driven belongs to the skill that owns
it, not here.

## Files
- [Treat every subagent as single use](treat-every-subagent-as-single-use.md) - why resuming a finished agent fails exactly when it is needed, and what carries the context instead
- [Every premise in a work order is executed as fact](every-premise-in-a-work-order-is-executed-as-fact.md) - a background sentence becomes an unverifiable instruction, and a relayed finding becomes an order
- ["Agent failed" says nothing about whether the work shipped](a-failure-notice-is-about-the-agent.md) - agents die during the report; measure the landing, not the notice
- [A scheduled prompt is a claim about the past](a-scheduled-prompt-is-a-claim-about-the-past.md) - asserted values become recurring false premises, and a wrong identifier never errors
- [A same-value write still destroys authorship](a-same-value-write-destroys-authorship.md) - the write that looks idempotent overwrites who did it
