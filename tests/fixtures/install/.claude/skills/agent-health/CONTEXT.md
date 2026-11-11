# agent-health - this install (FIXTURE)

Synthetic install context for the fleet's own tests. Every value is invented; a real
install replaces this file with its own. `parse_usage.test.sh` reads it for its step
and case pointers, so keep at least one `step N` of this skill and one
`/agent-revive` step pointer in it.

## Who owns this surface

`healer`, the fleet's health agent, runs the sweep and every handover.

## The roster

`claude-attach` with no argument prints the agents with a live tmux socket and exits
2. `healer` excludes itself (step 1).

## The sweep cadence

Every 30 minutes, Monday to Sunday. The analysis under "Thresholds" is worked at this
cadence.

## The usage ledger

`/tmp/fleet-fixture/agents/healer/state/agents.md`, created once with
`parse_usage.py --init`, written by `parse_usage.py --append` (step 4 captures, step 5
reads the verdict).

## The handover ledger

`/tmp/fleet-fixture/agents/healer/state/reports/handover.md`, written by
`pool_pick.py --take` and `--record` (step 9, step 11).

## Where handover packages go

`/tmp/fleet-fixture/agents/<agent>/state/handover/<YYYY-MM-DD>-<HHMM>-handover.md`,
named in step 6's message; the switch itself is `/agent-revive` step 5 and step 6.
