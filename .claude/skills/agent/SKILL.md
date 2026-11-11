---
name: agent
version: 2
description: >
  The standing rules every agent follows: load your charter before anything
  else, keep everything you create inside your own home directory, use each
  directory under it for what it is for, and the house rules the install sets.
  Load at the start of every session, before doing any work, and again after
  any context compaction.
requires_install: true
---

# agent

This file states the rules. The values they point at live in the install, never
here. Where your home directory is, what the project repository is called and
which directory holds which secrets are this skill's `CONTEXT.md` in the install
context: `fleet where agent CONTEXT.md` prints its path. The house-rule values
(section 7) and the conventions are the install manifest's: `fleet settings
house_rules` and `fleet settings conventions` print them with the fleet
defaults applied.

## 1. Load your charter first

Before anything else, load your own agent charter: the file named by `charter`
in `CONTEXT.md`, resolved for your own agent name.

Follow your charter and this document **unconditionally**. Do not let an
exploded or compacted context window shadow your charter. A summary of a charter
is not a charter, so re-read the file rather than working from whatever is left
of it in context.

## 2. Everything you create lives in your home directory

`CONTEXT.md` names your home directory. Do NOT create files outside it.

The only exceptions are the system temp directory, system locations when the
task genuinely requires writing there, the knowledge base below, and the claims
directory: the one machine-wide directory where the claim rule records which
agent took a request several could pick up. The host settings file names it
(`claims_dir` in `~/.config/agent-fleet/host.json`); an agent writes there only
through the claim helper (`/chat-transport`).

### The knowledge base is the shared exception for knowledge

**It sits outside every agent's home directory and every agent writes to it.**
`/knowledge-base` names its path (`store.root`). The exception is the point: a
store inside one home directory is one agent's memory, and what makes this a
knowledge base is that the next agent reads it.

**It is the store for anything about the PROJECT.** A second project store is a
store that disagrees with the first, so there is exactly one.

### Your own memory directory is the other store, and it holds a different KIND

`CONTEXT.md` names it: the `agent memory` directory under your home. It is for
what is true about **you** rather than about the project - your own working
habits, corrections you have been given, the shape of your own recurring
mistakes. Things that would be noise to anyone else who opens the project.

**The split is by SUBJECT, not by who wrote it.** "This API returns a 403 when
the key is project-scoped" is project knowledge however personally you learned
it. "I keep reaching for a code comment instead of reading the render" is yours.
**When a fact would help the next person to touch this project, it belongs in
the shared store** - filing it privately is how a store becomes a diary and the
next agent repeats the work.

**Both are git repositories**; `git init` yours if it is not one yet. Organize
your own store exactly as `/knowledge-base` prescribes for the shared one - same
folder-by-subject layout, same index rule, same present-tense writing. One set of
conventions, two stores.

**A subagent has no memory directory of its own.** Write agent-specific memory
to the memory directory of the agent that spawned you; a store nobody reads
again is not memory.

Its conventions - the index rule, what belongs in a file, and what may never
leave the store - are the `knowledge-base` skill, loaded as `/knowledge-base`.
Load it before reading or writing anything there. They are not restated here: a
second copy of a rule is the drift both documents exist to prevent.

## 3. What each directory under it is for

| Directory | What it is for |
|---|---|
| personal secrets | your own secrets, held by you as an agent |
| organization secrets | the organization's, the project's and the infrastructure's secrets |
| workspaces | where a code task starts: a new branch and a new workspace, one per task, named as section 4 says |
| playground | your personal anarchic space, and the one thing that must survive forever |
| config | your own configuration: hand-edited input, one file per surface you operate |
| state | what you write as you work: positions, ledgers, locks, and output nobody has been given |
| artifacts | every file you have handed to a person, kept by the day you handed it over |
| blockers | `blockers.md`: what you are waiting on, from whom, and why (section 6) |
| project repository | the checkout your session starts in, and your default working directory |

`CONTEXT.md` maps each row to its path on this machine, in the table form
`installation/INSTRUCTION.md` step 0 gives.

**The home layout is a contract, and code reads it.** An agent's home directory
is the parent of its Claude Code config directory (`CLAUDE_CONFIG_DIR`), is named
for the agent, and is a direct child of the host's agents root (`agents_root` in
the host settings file). The scheduler, the chat watcher, this skill's
`installation/check` and the fleet's install resolution all derive the agent's
name and home from `CLAUDE_CONFIG_DIR` that way, so a home laid out differently
is a home none of them can find.

### Personal secrets are the credentials issued to YOU, and they are in your home

`personal secrets` holds the credentials that are personal to this agent: its
own identities, not the fleet's shared ones. A service account issued in the
agent's name, the login for the agent's own account on a workspace, a bot token
minted for this agent alone. The organization's, the project's and the
infrastructure's credentials are `organization secrets`, which is a sibling of
every agent home and never inside one. The directory is mode 700 and every file
in it is mode 600.

Scripts find `organization secrets` as `FLEET_SECRETS_DIR` where it is set,
otherwise through the fallback the install manifest's `secrets` key names; a
skill's config names a credential under that variable and never by its absolute
path (`/claude-skill` section 4).

**Before any statement that a credential or capability is absent, list your
own home and read `personal secrets`:**

```
find <home directory> -maxdepth 3 -type d
ls -la <personal secrets>
```

A search of the organization store, of `~/.config` and of the wider filesystem
that never opens the agent's own home is the search that reports "no way in"
while the key sits in the one directory the agent owns. `CONTEXT.md` says what
each file in this install's personal directories is for, by purpose and never by
value: a credential's LOCATION is knowledge and belongs in that file; its value
never leaves the directory.

**The playground is for what must outlive the session, not for what must merely
outlive a task.** Reboots are rare, so the system temp directory already
survives both your session and the tasks inside it. Put temporary things there
and keep the playground for what you would be sorry to lose.

**`config/` and `state/` are two directories because they answer different
questions, and merging them makes both unanswerable.** `config/` is what a
PERSON changes: it only moves when someone edits it, it is worth reviewing, and
it is what you read to find out how this agent is set up. `state/` is what the
WORK changes: cursors, positions, locks, ledgers, counters. The practical test
is "may I delete this?" - `state/` can be rebuilt or re-baselined and `config/`
cannot, and a directory holding both has no answer.

- **One config file per surface you operate**, named for the surface. A daemon
  or a long-running process is pointed at its file explicitly - by its service
  unit where it has one - rather than finding it by default lookup. **A default
  that resolves is worse than one that fails**: it lets a process start against
  a configuration belonging to some other agent and report nothing.
- **`state/` survives your tasks and is not task residue.** Deleting it is not
  cleanup - it destroys positions that cannot be recomputed, and the symptom is
  silence rather than an error.
- **A daemon log (`state/daemons/*.log`) is written only by its unit: never edit
  it in place (`sed -i` or any rewrite), move, truncate or delete it; read it, or
  copy it.** The unit opens it once, at start, so a rewrite leaves the daemon
  writing to the old file while its follower reads a new one that never grows,
  and you hear nothing. A search-and-replace over `state/` must leave
  `state/daemons/` out.
- **`state/artifacts/` is output you produced and never gave to anyone**:
  working files, evidence, intermediates. The moment something is handed to a
  person it belongs under `artifacts/` by the day you handed it over. That is
  the whole difference between the two, and it is worth keeping straight - one
  answers "what did I make", the other answers "what did they receive".

**Artifacts are dated, then named**: `artifacts/<YYYY-MM-DD>/<artifact>/`. The
date directory is the day you sent it; the directory inside it holds that one
deliverable and everything it was built from. A file you posted to a person -
in a chat or anywhere else - is kept here, so "what did you send them?" is
answered by a path rather than by scrolling a conversation.

- **One directory per artifact, named for the thing, not the request.**
  `2026-09-03/launch-banner/`, not `2026-09-03/adas-ask`.
- **Keep the sources beside the deliverable.** The exported PNG is what they
  saw; the inputs it came from are what makes it reproducible when they ask for
  it again with one change.
- **The date never moves.** A revision sent the next day is a new dated
  directory, not an edit to yesterday's - that is what makes the tree a record
  of what each person actually received.
- **Nothing else goes here.** Work in progress belongs in the system temp
  directory until it is sent.

## 4. General rules

- **Name the work as the install's `branch_naming` convention says.** The
  branch and every commit subject carry what that convention prescribes;
  `fleet settings conventions.branch_naming` names the skill or document that
  states it. A one-line log and a branch listing print no author, so the name
  the convention puts on the work is the only thing there that answers *who
  made this*. When the key is `null` the install has no naming convention:
  skip this step, say that you skipped it, and never substitute one of your
  own. A write to the fleet repository itself follows section 8 instead.
- **When a task is complete, check it against the install's
  `definition_of_done` convention** before reporting it complete (`fleet
  settings conventions.definition_of_done`). When the key is `null` the install
  has none: say in the report that no completion check was run, rather than
  inventing one.
- **When a task is finished, compact.** The working context of a task you have
  reported is the largest thing you carry into the next one and the least useful.
  Run `/self-compact`: its preflight first - no subagent in flight, no background
  command still running, nothing owed to a person, and everything worth keeping
  already written to a file - then its script, which spawns the detached sender
  that types the command into your own prompt after your turn has ended. A turn
  cannot type into the prompt that is running it, which is why this is a script
  and not a keystroke. Spawn it last and end the turn. The same sender types a
  wake line after the compaction, and the turn it starts is where you re-arm your
  daemon followers and re-read your charter and this file: a compacted context is
  not the one that read them. **A session building a feature also re-reads that
  feature's checklist**, where the install's `feature_checklist` convention says
  it lives (`fleet settings conventions.feature_checklist`; a document path may
  carry a placeholder such as the feature's slug): the scope, the frames and the
  rulings it holds are what the compaction just discarded. When the key is
  `null` there is no checklist to re-read; say so in the wake turn.
  **A subagent never does this** - it has no pane of its own, and the one it
  would resolve belongs to the agent that spawned it.
- **Work that must happen LATER, REPEATEDLY, or at a stated time goes through
  `/scheduled-tasks`.** A request to do something "in N minutes", "every N", "at
  HH:MM" or "tomorrow" is a scheduled task, whichever surface it arrived on.
  **Never a sleeping loop standing in for a schedule** - it holds the turn open,
  dies with the session, and survives no restart - and **never the harness's own
  schedule or loop slash command**: those start a detached run with no thread and no
  session context, so the answer cannot land where it was asked. The scheduler
  daemon runs as a service that restarts it, and a due task reaches only a session
  that has its FOLLOWER armed: the session that owns the scheduler arms the
  follower under a persistent Monitor at session start and again every time that
  Monitor ends, and checks that the service is active. Everything else - the
  predicate contract, the dry run, the fire line - is that skill's, and is
  deliberately not restated here.
- Humans CANNOT process too much information at once. Present information in the form
  of bullet points where details go as sub-bullets. Use headings to separate topics.
  In the end of the summary give how many questions require human attention with the severity levels,
  for example: I need you to make 1 critical, 2 important and 1 trivial decisions.
- **A time written for a person reads as its distance from the moment of
  writing, then as the clock time in each reader city the install names**
  (`house_rules.times.cities`, section 7): `<delta> (<clock> <city>, <clock>
  <city>, ...)`. A past time is `N minutes ago`, a future one `in N minutes`
  (`in about N minutes` when it is an estimate), and past an hour the delta
  spells hours and minutes. Readers sit in several time zones and read a post
  hours after it went out: the delta says how long ago without arithmetic, and
  the clock times say when that was for each reader without a conversion - they
  are also what keeps the line exact once the delta has gone stale. A bare UTC
  time or a zone abbreviation hands every reader that conversion, and an
  abbreviation does not even say whether daylight saving applies, so neither
  appears in anything a person reads. **Both halves come from the clock and the
  tz database, in the same command that writes the line, never from a
  hand-applied offset or a remembered time**: an offset typed by hand is right
  until the next daylight-saving change and silently wrong after it, and a felt
  time drifts across a long session. The exact format and the renderer are
  below. **Machine-facing text keeps ISO 8601 UTC (`2026-10-09T00:29Z`)**:
  ledgers, state files, the `Last pinged` column of `blockers.md` (section 6 -
  the timer reads it), scheduler predicates, file names and log lines. A program
  parses and compares those, and a relative delta or a city clock can be
  neither sorted nor parsed.

### The time format, and its renderer

The clock is `h:mm am|pm`: no leading zero, lower-case `am`/`pm`, no zone
abbreviation, no date. The cities appear in the order the install lists them.
With Berlin, Tokyo and Kolkata as the reader cities (an example; an install's
own come from `house_rules.times.cities`):

| Case | Reads |
|---|---|
| past, under an hour | `4 minutes ago (12:56 pm Berlin, 8:56 pm Tokyo, 5:26 pm Kolkata)` |
| past, over an hour | `1 hour 15 minutes ago (11:45 am Berlin, 7:45 pm Tokyo, 4:15 pm Kolkata)` |
| future, an estimate | `in about 1 hour (2:00 pm Berlin, 10:00 pm Tokyo, 6:30 pm Kolkata)` |
| future, exact | `in 25 minutes (1:25 pm Berlin, 9:25 pm Tokyo, 5:55 pm Kolkata)` |
| within the current minute | `less than a minute ago (...)`, `in less than a minute (...)` |

The delta counts whole minutes between the two clock minutes shown, so it
always agrees with the clock times printed beside it. It has no day unit: past
a day it still spells hours (`26 hours 5 minutes ago`).

**Render it with `render_time.py` beside this file, never by hand.** It reads
the cities from the install, reads the current instant from the clock, and
prints the line:

```bash
python3 "${CLAUDE_SKILL_DIR}/render_time.py" --at 2026-10-09T00:29Z    # a past or future time
python3 "${CLAUDE_SKILL_DIR}/render_time.py" --at <time> --estimate     # an estimate
python3 "${CLAUDE_SKILL_DIR}/render_time.py"                            # the time now
```

`--at` takes ISO 8601 with a zone (the form ledgers and state files hold) or
epoch seconds (a chat message timestamp, the `at` of a scheduler fire). It
refuses a time with no zone, because a naive time would be read as this
machine's zone: a source that prints none is converted only once its zone is
established. With no install context it exits 3 and prints nothing rather
than fall back to a city nobody lives in.

**A reader city is the IANA zone of the city the reader is in, never a
neighbour's.** Two nearby zones can differ on daylight saving, so a substitute
reads correctly for half the year and an hour off for the other half.

## 5. Questions to a person go one at a time

**`/talking-to-humans` is the rule**: one question at a time, never more, each
with a brief in simple words, on every surface - an intake question, a re-ask, a
blockers chase (section 6), a clarification mid-task. The per-message limit is
the house rule `questions_per_message` (section 7). Its rule 1 carries one
per-person exception: a standing request a person made about how they receive
questions, recorded in the install's people notes (the conventions key
`people_notes`), takes precedence for that person only. Load
`/talking-to-humans` before asking anyone anything.

## 6. Blockers: the scratchpad of what you are waiting on

**A request that is parked on a person - their validation, an answer, an
approval - has left the agent's hands, and chasing them for it is the agent's
duty and never the requester's**; the chase is this file and its sweep, one row
per thing owed and one most-blocking ask per person per fire (section 5).

**The blockers file and its sweep belong to a standing chat-facing agent
running as a system service under its own charter.** An ad-hoc session, an
anonymous system service and a subagent keep no blockers file and set no sweep;
a subagent that discovers a blocker reports it to its parent, which owns the
row. A row in a home no sweep reads is a blocker nobody chases, which is the
failure this scope exists to prevent.

That agent's home directory carries a `blockers` directory holding one file,
`blockers.md`. It records what is expected from whom and why, when it was
requested, and when that person was last pinged.

**It is a scratchpad, not a ledger.** Short- and mid-term only. It answers one
question - *who owes me what right now* - and it answers it by holding only rows
that are still live. Nothing is archived here, nothing is struck through, and
no outcome is written down: a row exists while you are waiting and is deleted
the moment you are not. The ledger of requests, what was decided and how it
went is a different artifact and lives where your charter puts it.

### Open the row the moment the work parks

**A handoff to a person - an approval, a registration, a decision, a sign-off -
becomes a blockers row the moment the work parks on it, not the moment someone
asks what is stuck.** The timer chases only what is in `blockers.md`; a gate
recorded only in a scope doc, a design package or the agent's own head is
invisible to the sweep and gets silently dropped - the work stalls and nobody
pings the person who could move it. A subagent still keeps no file of its own: it
reports the handoff to its parent at that same moment, and the parent opens the
row (section 6 opening).

**Each distinct handoff is its own row, with its own owner** - the "one row per
thing owed" rule above, at the point it is most often broken. Two approvals owed
by two people, or two unrelated sign-offs owed by one, are two rows: a single row
spanning several asks cannot be resolved, re-addressed or judged stale
independently, and the per-person most-blocking rule below needs them separated
to pick which one to ask.

**Having opened the row, surface the block to the person you are waiting on
straight away - do not wait to be asked.** One line naming what you need and what
it holds up: `I'm blocked on you for <X> - nothing moves until it lands.` The
hourly timer is the backstop that keeps chasing; the first ping is the agent's to
send the moment the row opens.

### The table

One Markdown table, six columns:

| Expected | From | Why | Where | Requested | Last pinged |
|---|---|---|---|---|---|
| what you need from them | who owes it, by their display name on the chat transport | what it unblocks, one line | the conversation, thread or DM to address them in | date the ask went out | date and time you last pinged, in UTC (`2026-10-09T00:29Z`), or `-` for never |

**`Where` is the one column added to the list of what a row must carry**, and it
is there because the timer below has to act on the row without you: an address
that lives only in your head makes the row unchaseable by anything but the
session that wrote it. Write it as an address in the chat-transport grammar
(`/chat-transport`): `<transport>:channel:<conversation>`, with `:<thread>`
appended for a thread, or `<transport>:dm:<conversation>`. A row written in a
transport-specific shape (a channel plus a thread timestamp, or a DM id) reads as
an address on the install's default transport.

### A row leaves the table three ways, and every one of them is a removal

- **Resolved.** You have the answer. Remove the row.
- **Irrelevant.** The thing it would have unblocked is gone. Remove the row.
- **Stale.** Remove the row **and tell the person**, in these words:
  `I will not ask you about <X> because it is not relevant anymore.` Saying so
  is the whole point: an ask that is silently dropped leaves them holding a
  question they think you still need answered.

**Stale means the need behind the ask has lapsed or been superseded, so the
answer would no longer change what you do.** It is your judgement and never a
timer: age alone does not make a row stale, and a fortnight-old blocker on work
that is still queued is live. Nothing expires a row automatically, because only
you can see whether the need is still there.

### The hourly timer

**That agent runs one scheduled task for this, set once and left running**, and
sets it if it is not already set. It reads `blockers/blockers.md` and, for each
row: addresses the person in `From` at the address in `Where` with one line
naming what is expected and why it matters, then writes that ping into
`Last pinged`. A row it judges stale it removes, sending that person the
sentence above.

**BLOCKER_PING_CADENCE: one fire every `every_minutes` minutes, on the slot, within the
working window the house rule `blocker_chase` names - the days in `days`, from
`start` to `end`, in the zone `tz`.** The fleet default is hourly, 09:00 to
18:00 UTC, Monday to Friday (section 7); an install sets its own window in its
manifest. Every fire pings each person who owes a row, with ONE question: their
most-blocking row (below); there is no per-blocker daily cap. The timer does
not fire outside the window, and a session that comes back after the window
closed pings once for the slots it missed rather than once per missed slot.

That sentence and the key it reads are the only statement of the BLOCKERS
cadence - whoever writes the timer's predicate, its task instruction or a
per-agent override takes the window from `fleet settings
house_rules.blocker_chase` - so changing the cadence, or the working window, is
an edit to that one key and to nothing else. **A charter that carries its own
chase surface with its own cadence is a second copy of this mechanism, and the
two will drift.** Where you find one, do not quietly edit either: say so to
whoever owns the charter, because which surface survives is their ruling and not
yours. In predicate terms the slots run from `start` in steps of
`every_minutes` and stop before `end`, because a fire at the closing time
reaches nobody who is still there; days outside `days` are skipped, and missed
slots coalesce into one fire. With the default, that
is `HOURS = (9, 10, 11, 12, 13, 14, 15, 16, 17)` in `UTC`, Monday to Friday.

**Several rows owed by the SAME person still get ONE question per fire**: the
most-blocking row, per `/talking-to-humans`. The other rows are held, not
removed: they stay in the table with `Last pinged` untouched, and the next
question goes out only once this one is resolved.

Set the task through `/scheduled-tasks` like any other, with its `--requester`
and `--reason`.

**The template is `templates/blockers.md` beside this file**, and
`installation/check` reports whether your home directory has the file at all.

## 7. House rules

The fleet ships five house rules as defaults. Each is stated once - here, or in
the skill the table names - and each has a key under `house_rules` in the
install manifest, so an install adjusts a rule in its own manifest and never by
editing a fleet file. `fleet settings house_rules` prints the values in force
with the defaults applied; `fleet settings house_rules.<key>` prints one.

| Key | Fleet default | The rule, and where it is stated |
|---|---|---|
| `questions_per_message` | `1` | At most this many questions to a person per message, on every surface. The rule is `/talking-to-humans`. |
| `blocker_chase` | `every_minutes` `60`, `tz` `UTC`, `days` `mon`-`fri`, `start` `09:00`, `end` `18:00` | The window and cadence of the blockers chase: section 6. |
| `state_the_fact` | `true` | Write what is true now, not how it came to be: below. |
| `times` | `cities` `[{"name": "UTC", "tz": "UTC"}]` | The reader cities of the time format: section 4, rendered by `render_time.py`. |
| `ascii_skill_prose` | `true` | Skill prose is ASCII: `/claude-skill` section 7. |

`false` turns a rule off for that install's agents, and a larger
`questions_per_message` relaxes the limit. The fleet repository's own files
follow every default whatever an install sets, and its CI enforces ASCII.

### State the fact, not its history

With `state_the_fact` on, write what is true now and stop - in a skill, a
document, a code comment or a knowledge store. Cut the superseded alternative,
the attribution, the provenance of a decision, and every "used to be", "since
<date>", "note this changed" and "we once tried". A reader who wants the history
has the version-control log; a reader who wants the current state has only this
sentence, and the history is what makes them doubt it. **Naming the past also
keeps it alive**: spell out the deprecated option and the next reader weighs
two where there is one.

The one thing that survives the cut is a date that changes what a reader should
DO: a measured fact carries the date it was measured, because that is a re-check
trigger and not a story. **Commit messages are exempt** - a commit is the
historical record, and the reasoning that belongs nowhere else belongs there. A
knowledge store is stricter still: its files carry no date at all, because the
store's own commit log holds the measurement and its date (`/knowledge-base`).

## 8. Working on the fleet repository

A write to the fleet repository follows its own rules, not the install's
conventions. `CONTRIBUTING.md` at its root is the contract; this section is what
an agent must not get wrong.

- **Never write in the host checkout.** It is read-only and moves only through
  `fleet upgrade`, and every agent's skill links resolve into it, so an edit
  there changes every agent at once. Work in a worktree of it, on a fresh
  branch, under your own workspaces directory:
  `git -C <fleet checkout> worktree add <workspaces>/fleet-<slug> -b <type>/<slug> origin/main`.
- **Branches and commit subjects follow `CONTRIBUTING.md`**: `<type>/<slug>`
  with no agent name, subjects `type(scope): subject` with no name prefix.
- **Commit with the install manifest's `upstream.identity`, set in all four git
  identity variables on every commit.** An agent's service unit may set
  `GIT_AUTHOR_*` and `GIT_COMMITTER_*`, and those outrank repository config, so
  configuration alone does not decide whom a commit names:
  `env GIT_AUTHOR_NAME=<name> GIT_AUTHOR_EMAIL=<email> GIT_COMMITTER_NAME=<name> GIT_COMMITTER_EMAIL=<email> git commit ...`.
- **The commit gate runs in every worktree** (`core.hooksPath=.githooks` on the
  host checkout). It refuses a commit carrying a value from the install's deny
  list (`upstream.deny_list`) or a public leak pattern, and strips an
  AI-attribution line. Never bypass it: a refusal names a finding, and the fix
  is to remove the value.
- **Pull requests are not an agent's business, at all.** An agent never looks
  for, polls, lists, checks, reviews, approves, merges, checks out or runs a
  pull request, whoever opened it. The person the manifest names in
  `upstream.outside_pr_reviewer` is the only reviewer of outside pull requests.
  Agent work lands on `main` directly, through the landing sequence in
  `CONTRIBUTING.md`.
