# agent-revive - this install (FIXTURE)

Synthetic install context for the fleet's own tests. Every value is invented; a real
install replaces this file with its own.

## How this fleet is laid out

Agents live under `/tmp/fleet-fixture/agents/<agent>`; the session and unit templates
are `config.json`'s `fleet` block. The roster is `claude-attach` with no argument.

## Who signs in, when a human has to

An ORDER of people, 15 minutes each: Ada, then Grace, then Alan, reached in `#ops`.
The share (step 7) goes to the person the order currently has you asking; the
fallback (step 7e) delivers one account's credentials to that person only.

## The account pool and its leases

The pool, the lease file, the ledger and the handover ledger are the `accounts` block
of `config.json`. Accounts enter the pool through `pool_pick.py --register` (step 5).
Which account signs in is step 5; a pool with no candidate is case 1. Agents run as
user units; a token agent's switch is `token_switch.py` (step 5, case 15).

## The "Verify it's you" challenge

`recovery.mailbox` is the one recovery address every pool account carries
(step 6b).
