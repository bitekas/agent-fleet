---
name: chat-transport
version: 1
description: >
  The interface every chat transport skill implements - the address grammar,
  the transport descriptor (transport.json), the watcher contract and the
  outbound recipe headings - plus the transport-neutral claim that decides which
  ONE agent acts on a request several agents could pick up. Load before
  claiming a chat request, before writing or changing a transport skill or its
  transport.json, and before writing an address (a scheduler origin, a blockers
  row) that names a chat conversation. Mechanics only, no policy: whether an
  agent may take a request at all is its charter's call.
requires_install: false
---

# Chat transport

A **transport** is one chat service an agent talks through. Each transport is a
skill of its own - its watcher, its outbound recipes, its traps - and every one
of them implements the interface below, so the rest of the fleet (the daemon
manager, the scheduler, the claim) works through the interface and never
through a particular chat service.

**The registry is every `.claude/skills/*/transport.json` in the fleet tree**,
read and validated by `fleetlib.transports`. A skill that has one is a transport
skill. Its `status` is `working` or `placeholder`; only a working transport gets
a watcher unit, a scheduler origin or a place in an install's
`transports.enabled`. Which transports an install uses, and which one is its
default, are the install manifest's `transports.enabled` and
`transports.default`.

This skill holds no value of any install: it needs no config and no install
step.

## Address grammar

How a conversation is written anywhere the fleet stores or prints one - a
scheduler task's origin, a blockers row, a report:

```
address := "session"
         | <transport> ":" <kind> ":" <conversation> [ ":" <thread> ]
kind    := "channel" | "dm"
```

- A `<thread>` makes the stored kind `thread`.
- `<conversation>` and `<thread>` are validated against the transport's
  descriptor, `ids.conversation` and `ids.message`.
- **Legacy forms**, accepted wherever an address is accepted, forever:
  `slack:<id>` is `slack:channel:<id>`, and `dm:<id>` is `slack:dm:<id>`. A form
  with ONE colon is legacy; two or three colons is the grammar above. Prose that
  teaches the legacy forms stays correct.

## Transport descriptor

`<transport skill>/transport.json`, schema 1. `slack-communication/transport.json`
is the worked example; every key is required.

| Key | What it is | Who reads it |
|---|---|---|
| `schema` | `1` | the loader |
| `name` | the transport's name, unique across the fleet tree (`slack`); the skill directory holding the file is that transport's skill | everything |
| `status` | `working` or `placeholder` | the loader: `working()` excludes placeholders |
| `line_prefix` | the first word of every line its watcher prints (`SLACK`) | the follower, whose priority lines are `<line_prefix> DM ` |
| `kinds` | the conversation kinds it supports, out of `channel`, `dm`, `thread` | the scheduler |
| `ids.user` | a full-match regular expression for a user id | the scheduler's default requester pattern |
| `ids.conversation` | the same, for a conversation id | the scheduler, `claim.py` |
| `ids.message` | the same, for a message id (a thread's id is its parent message's) | the scheduler, `claim.py` |
| `watch.script` | the watcher, relative to the skill directory | the daemon manager |
| `watch.job` | the daemon job name: unit `agent-<job>@.service` (on macOS the launchd label `<launchd_prefix>.<job>.<agent>`), config `config/<job>.json`, log `state/daemons/<job>.log` under the agent's home | the daemon manager |
| `watch.config_env` | the one environment variable that names the watcher's config | the daemon manager, the watcher |
| `watch.follow_include` | the follower's default `--include` filter | the daemon manager's `follow` |

The loader contract - discovery, validation, the error for a bad descriptor -
is `fleetlib.transports`; a descriptor that does not validate stops every
reader at once, which is the point. The log `state/daemons/<job>.log` is
written only by the job's unit: never edit it in place (`sed -i` or any
rewrite), move, truncate or delete it; read it, or copy it.

**`watch.follow_include` is the one statement of what reaches a session.** The
follower applies it when it is run with no `--include`; an agent narrows it with
`--exclude '<regex>'` and never by copying the default into its own command,
because a copy keeps working after the default changes and drifts from it. Each
transport skill states the reason for every clause of its own filter.

## Watcher contract

- A transport's `watch.py` is a long-running poller configured ONLY through the
  environment variable `watch.config_env`, with `--once` for one poll.
- **Exit codes.** `0` is a guard refusal: another copy holds the lock, or the
  config's owner is not this `CLAUDE_CONFIG_DIR` - a supervisor must not restart
  it. `2` is a placeholder or a usage error. Anything else is a crash, which the
  unit restarts.
- **stdout**: exactly one line per deliverable message, starting
  `<line_prefix> `. The line carries the conversation's label, `[<id label>
  <message id>]`, `reply in thread <thread id>` when it is a reply, and the
  sender as `Name (id)` or the bare id, with ` [bot]` when the sender is a bot;
  at most 500 characters of text. Nothing else ever goes to stdout: a follower
  delivers every stdout line as a message.
- **stderr**: diagnostics, prefixed `WATCH-GUARD`, `WATCH-INFO` or
  `WATCH-ERROR`.

Slack's watcher is the reference implementation, and its line format is the
contract as it stands.

## Outbound recipes

Outbound is performed by the agent, from recipes in its transport skill. No
fleet machinery posts by itself, and there is no shared posting command. Every
transport skill documents its recipes under these exact headings, so an agent
finds the same operation by the same name in any transport:

- *Post*
- *Reply in thread*
- *React*
- *Direct message*
- *Upload a file*
- *Fetch a message*
- *Permalink*

## Placeholder transports

A placeholder has the interface and none of the service: its `SKILL.md` carries
every heading above, each saying it is not implemented in this version; its
`transport.json` says `"status": "placeholder"`; its `watch.py` is a symlink to
`placeholder_watch.py` here, which honours the watcher CLI, prints
`WATCH-GUARD <transport> transport is a placeholder: not implemented` to stderr
and exits 2. No unit is rendered for it, the scheduler accepts no origin on it,
and an install cannot enable it.

Turning a placeholder into a transport is: write the recipes under the headings,
replace the symlink with a watcher that keeps the watcher contract, set
`status` to `working`, give the watcher a test, and enable the transport in the
install manifest.

## Claiming a request

**Every agent in a shared conversation receives the same message, so a request
more than one of them could pick up is answered twice unless one claims it
first.** Before ANY visible act on such a request - a reply, a reaction, or
starting the work - claim it. Whether an agent may take the request at all stays
its charter's call; the claim only settles which of the agents that may, does.

**The key is the conversation ID and the id of the message that carries the
request.** Each transport skill says where its watcher line carries them (for
Slack: `/slack-communication`, *Claiming a request*). For a thread reply it is
the reply's own id, never the thread's - one thread carries many requests.

```bash
python3 "${CLAUDE_SKILL_DIR}/claim.py" take <conversation id> <message id> --agent <your name>
```

`--transport <name>` names the transport; without it, the install's
`transports.default` is used.

| Exit | Line | Do |
|---|---|---|
| `0` | `CLAIMED` - you won; `ALREADY-YOURS` - you had already won (after a restart, say) | the transport's acknowledgement (its *React* recipe), then post your ETA in the thread |
| `1` | `CLAIMED-BY <owner> at <time>` on stdout | stay out: no reaction, no reply. Follow-ups in that thread belong to the owner |
| `2` | invalid input (a conversation NAME instead of its ID is the usual one, or an id of another transport) | a fault, not a win and not a loss: do not act as the owner; fix the call |
| `3` | environment fault - the claims directory is missing or unusable, the fleet's settings or transport registry cannot be read, or the script crashed | a fault, not a win and not a loss: do not act as the owner; report it |

**Exit 1 with no `CLAIMED-BY` or `UNCLAIMED` line is a FAULT, not a loss** -
handle it like `3`. Exit 1 is also Python's own status when the script could not
run at all (a SyntaxError in a half-merged checkout, a failed import), and that
1 arrives with a traceback and nothing on stdout. Read as lost, it keeps the
agent out of every request, silently; the result line is what makes a 1 an
answer.

`show <conversation id> <message id>` names the owner without claiming (exit 1:
`UNCLAIMED`).

**Reactions never decide ownership.** A reaction carries no order that can be
read back, so "who reacted first" settles nothing. The acknowledgement is for the
humans in the thread; the claim file is the record.

**Takeover, only when the owner is down**: when `/agent-revive`'s triage of the
owning agent shows a session that cannot act (a state that skill treats as
needing a revival or a wake). Never on silence alone: `healthy` and `working` are
still on it, `unknown` decides nothing, and `follower-down` counts only when its
`followers_down` or `logs_replaced` names the conversation's transport watcher, the
source the owner no longer hears. Say so in the thread first, then:

```bash
python3 "${CLAUDE_SKILL_DIR}/claim.py" takeover <conversation id> <message id> --agent <your name> --from <owner>
```

It succeeds only while `<owner>` still holds the claim, so two agents taking over
at once cannot both win; the file records `took_over_from`. Exit 1 names who
holds it now, or says `UNCLAIMED` (take it instead). The script cannot check
that the owner is down; that is the taker's to establish.

**Release when the owner hands the request away**, so another agent may take
it: `release <conversation id> <message id> --agent <your name>` (owner only;
exit 1 names the owner otherwise).

**Pruning is automatic.** `take` prunes claims older than 14 days at most once a
day: the directory grows exactly when agents claim, so the claim path is the one
place a prune is guaranteed to run, where a timer would be a unit to install and
a manual chore would never run. `prune [--older-than DAYS]` does it by hand.

**The claims directory is ONE directory for the whole host**: `claims_dir` in the
host settings file `fleet install` writes (`~/.config/agent-fleet/host.json`),
never a per-agent or per-skill config, because two sources are two claim spaces
in which two agents both win the same request. `fleet install` creates it,
mode 700, and `claim.py` never does - a missing directory is exit 3 naming the
`fleet install` that creates it - and `/slack-communication`'s
`installation/check` verifies it. `--dir` is for
tests only.

**Claim names.** A Slack claim is `<conversation>-<message>`, with no transport
prefix, so every version of the script names the same Slack claim file; every
other transport's claim is
`<transport>--<conversation>-<message>`. The script's header is its full
contract; `claim.test.py` is its guard, race harness and negative controls
included.

## Related

- **Claim:** `claim.py` (its header is the contract), `claim.test.py`.
- **Descriptors and placeholders:** `transports.test.py` (every descriptor loads
  through `fleetlib.transports`; each placeholder's watcher refuses as above),
  `placeholder_watch.py`.
- **The working transport:** `/slack-communication`.
- **Origins on a transport:** `/scheduled-tasks`.
