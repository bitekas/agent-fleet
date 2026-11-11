---
name: scheduled-tasks
version: 1
description: >
  Mechanics for work that must happen LATER, REPEATEDLY, or on an irregular schedule,
  and then report back into the conversation that asked for it. A task carries a Python
  predicate; a daemon evaluates every active predicate once a second and prints one line
  per due task, which wakes this session. Load before scheduling anything delayed or
  recurring, before writing or editing a predicate, before arming the scheduler's
  follower Monitor, and when a `SCHED` line arrives. NOT the harness's /schedule (cloud routines,
  CronCreate) or /loop - those start a detached run with no thread and no session
  context; this wakes THIS session and answers where it was asked. Mechanics only - who
  may schedule what, and what a due task may do unattended, live in the owning agent's
  charter.
requires_install: true
---

# Scheduled tasks

Deferred, repeated and conditional work, delivered as a wake-up line.

**This file is universal.** It names no workspace, person, channel or path. Every
concrete value lives in the config file `SCHED_CONFIG` names, and `sched.py doctor`
prints the resolved set - which beats a hand-copied table that goes stale silently.

| File | What it holds | Per deployment? |
|---|---|---|
| `SKILL.md` (this) | mechanics, the predicate contract, the traps | universal |
| `config.example.json` | every key, placeholdered; the template a real config is copied from | universal |
| the config `SCHED_CONFIG` names | db path, owner, timezone, every tunable | **yes** |
| `sched.py` | daemon + CLI + simulator, one file, stdlib plus the fleet's `fleetlib` | universal |
| `sched.test.py` | offline regression guard | universal |
| `CONTEXT.md` and `installation/.install-state.json`, in the install context (`fleet where scheduled-tasks`) | what this deployment chose, and what was installed | **yes** |

**There is deliberately no `config.json` beside this file, and its absence is the
mechanism.** How many schedulers a deployment runs is its own decision - one, or one per
agent, each with its own owner and its own database - and a committed config answers that
question for everybody, wrongly for anyone who runs more than one. So `SCHED_CONFIG`
selects the config and there is no fallback that resolves: an agent that never set it
fails loudly on a file that is not there, rather than quietly arming a daemon against the
example, whose owner matches nobody and whose database path is a literal placeholder.
The install's `CONTEXT.md` (`fleet where scheduled-tasks CONTEXT.md`) says what THIS
deployment chose and where its real configs live.

**This file contains no policy.** Whether a request should become a task, who may ask,
what a task may do at 3am with nobody watching, and how to word a confirmation are the
owning agent's judgement and live in its charter.

---

## 1. What this is, and what it is not

Use it when the request names a **time** the work must happen at, or a **repeat**:
"every", "daily", "each Monday", "in an hour", "5 times", "from now on".

Do **not** use it for:

- **"Later" / "when you get a chance"** - that is a priority, not a schedule.
- **A long job.** Minutes of work is not a timer.
- **A one-off with a deadline.** "By Friday" is a due date - do it now. A task that
  fires Friday morning is how a deadline gets missed by an hour.

And note what it is not: **it is not the harness's `/schedule` or `/loop`.** Those start
a detached run somewhere else. This one wakes the session that owns the conversation, so
the answer lands in the thread that asked.

## 2. Lifecycle

1. A human asks for something delayed or recurring.
2. You write the **instruction** (what you will do when it fires - verbatim and
   self-contained; the future you has only this line and the task row) and a **predicate**
   (when it fires).
3. `simulate` it. Read the fire times yourself before anyone else does.
4. `add` it - which dry-runs it again and refuses two classes of mistake outright, and
   refuses altogether without a `--reason` (section 3).
5. Confirm back to the requester with concrete fire times.
6. The daemon evaluates it every tick. When it comes due, one line reaches this session.
7. You do the work and report into the task's **origin**.
8. `run-result` records what happened. When the schedule ends, the row becomes `done`.

The state machine is `active <-> paused -> done | cancelled | failed | archived`.

**The daemon's job ends at the emit.** It never does the work and never knows whether
the work happened - that is what `run-result` is for. Skip it and the archive records
bells rung, not work done, and `doctor` starts reporting `lost` runs.

## 3. Data model

Two tables, and the split is load-bearing.

**`tasks`** - the schedule. Notable columns: `predicate_src` / `predicate_sha`,
`state_json` (the predicate's carried memory), `tz`, `origin_*`, `requester_uid` and
`reason` (below), `meta_updated_by` / `meta_updated_at` (who last rewrote those two and
when), and the daemon's own backstops `max_fires`, `not_after`, `min_interval`.

**`runs`** - what actually happened, one row per fire. It is separate because:

- **The writers are disjoint and so are their moments.** The daemon inserts at fire and
  never touches the row again; you update it minutes later. In a JSON blob on `tasks`,
  a fire landing between your read and your write silently erases a run record - and
  nobody notices until someone asks "did Monday's job run?"
- **Pending runs are the crash-recovery cursor.** A wake-up line injected while the
  session was restarting is otherwise gone forever; there is no other place to re-read
  it from.

**Column ownership is the concurrency contract.** The daemon writes `state_json`,
`last_eval_at`, `last_fire_at`, `fire_count`, `error_count`, `last_error`, `rev`, and
exactly two status transitions (`active->done`, `active->failed`). You write everything
else - except `updated_at`, which is **shared**: the daemon bumps it on every state
write, fire, error and auto-archive, and several verbs bump it too. So it says the row
moved and never who moved it, which is why the provenance stamp below is a separate
pair. Do not hand-edit `state_json` while the daemon is running - `rev` will make your
write lose, silently.

**A column added to `tasks` is added by an idempotent `ALTER TABLE`, guarded on
`PRAGMA table_info`, and does NOT bump the schema version.** A version bump makes every
already-running copy of the daemon exit on sight of the database it is serving - and a
daemon is a long-lived process that a code update does not restart, so the agent whose
scheduler you were improving stops firing until somebody notices. An additive, nullable
column is invisible to the running process instead: it reads `SELECT *`, gets one extra
key, and names every column it writes. (Measured: a running daemon keeps firing across
an additive migration, uninterrupted.) Reserve the version bump for a change that genuinely breaks
the old reader - a dropped or retyped column - where refusing is the right behaviour.

### Where the answer goes - the origin

An origin is a **transport plus a kind**, given to `add --origin`:

| `--origin` | Means |
|---|---|
| `session` | answer in this session; no chat transport |
| `<transport>:<kind>:<conversation>` | `<kind>` is `channel` or `dm`, on a WORKING chat transport |
| `<transport>:<kind>:<conversation>:<thread>` | the same, inside a thread; the stored kind becomes `thread` |
| `slack:<id>`, `dm:<id>` | `slack:channel:<id>` and `slack:dm:<id>`, accepted forever |

`--thread <id>` turns a channel origin into a thread origin and leaves a dm a dm. The transport must be a working one in this fleet's
registry, and the conversation and thread ids must have that transport's shapes (its
`transport.json`); a placeholder transport is refused by name. Every refusal exits `2`
and comes before the dry run.

**Two stored formats, and the Slack-only one is never altered.** A database this
version creates stores `origin_kind` (`channel`, `dm`, `thread`, `session`) and
`origin_transport`, NULL exactly for `session`. A database with no `origin_transport`
column stores Slack origins as
`slack_channel`, `slack_dm`, `slack_thread` and refuses any other transport with
`REFUSED: this scheduler database predates transport-neutral origins and stores Slack
origins only; a <transport> origin needs a database created by this version.` `doctor`
says which format a database has.

**`origin_transport` is never added to an existing database**, and it is the one column
the additive-migration rule above does not cover: SQLite cannot rewrite a `CHECK` in
place, so a Slack-only table that gained the column would read as fresh while
admitting only `slack_*` kinds, and the next `add` would fail at the database. Its
absence is how the Slack-only format is recognised. `sched.test.py` section 16 pins it.

### Who asked, and why - `requester_uid` and `reason`

Every task carries both, and `add` refuses without a reason. They are one field's worth
of prose against the failure this system produces on its own: **a database of schedules
nobody dares cancel, because nobody remembers what any of them are for.** A schedule
outlives the conversation that created it by months. The row is all the next reader
gets, and the next reader is usually you, at 3am, being woken by it.

**The requester is a name a human recognises, never an id.** The trade is deliberate
and worth stating: the row is now readable by anyone at any distance from the request,
and the cost is that reaching that person needs a reverse lookup through the same
directory (section 10 is the one place that does it). Storing the id instead optimises for the
one path that needs an address, at the expense of every path that needs an answer to
*who wanted this*. Four kinds of value, and the fourth is the one people forget exists:

| The instruction arrived | Store |
|---|---|
| from a person over chat | that person's display name |
| typed into a terminal session by a human | the value naming that interface (`claude cli terminal`) |
| through the remote client | the value naming that interface (`claude remote client`) |
| from a standing rule in this agent's own charter or a skill | this agent's persona name |

Pass the display name, or pass the chat user id and let `add` resolve it through the
requester directory (`requester.directory_file` / `requester.directory_key`, pointed at
the chat integration's own roster so there is one roster on the machine and not a second
copy here). **An id-shaped value the directory cannot resolve is REFUSED, not stored.**
"Id-shaped" is `requester.id_pattern` when the config sets it, and otherwise the user-id
shape of every working chat transport (`ids.user` in each `transport.json`). That refusal is deliberate and is not to be softened into a warning: storing the id
satisfies every constraint, passes every test, and surfaces months later as a `by=`
field naming somebody nobody can identify - on the one row that was supposed to say
whether the task should still be running.

**Self-originated is a real answer, not a missing one.** A task a standing rule
produced has no human requester, and leaving the field to guess makes it look like the
record was simply never filled in. Name the agent.

**The reason answers three questions, and a reason that answers fewer is not one:**
*why is this task here at all - what is worse if it is forgotten? why was it added -
what was happening when someone asked? what problem does it solve?* Write it for someone
who was not in that conversation. `add`'s refusal quotes all three, because the refusal
reaches the one reader who is already blocked and about to type something.

**"Ada asked for it" is the failure mode, not the answer** - it records that a
request happened and nothing about whether it still matters, which is the only question
anybody ever brings to this row.

**Both ride the wake-up line, reason first** (section 9), so the line that wakes you says why
before it says what.

**A task that RE-ADDS ITSELF carries both fields across, and the caller is the only
thing that can.** A `cancel` + `add` pair - the shape used by a task that re-schedules
itself for a new time, or by any change a predicate edit forces - creates a NEW row with
nothing inherited: without the fields it is refused (good), and with a hastily retyped
reason it is a row whose purpose has quietly drifted from the one it replaced. Read them
off the row you are replacing, verbatim: `show <id> --json` gives `requester_uid` and
`reason`, and they go straight into the new `add`. **Write that instruction into the
task itself**, next to the re-add step, or the future session doing the re-add has no
way to know it owed anything.

**Backfilling an existing task is `set-meta <id> --requester --reason`, never
cancel-and-add.** Cancel+add gets the fields right and silently resets everything else:
`fire_count`, `last_fire_at`, the predicate's carried `state_json` - so the next slot
re-arms from now and a daily job quietly skips a day - and the whole `runs` history.
`set-meta` touches those two fields plus its own stamp (below) and nothing else, which
is also why it leaves the instruction and the predicate byte-identical for any integrity
baseline taken over it.

### The rewrite leaves a trail, and `audit` is what reads it

`set-meta` stamps **`meta_updated_by`** and **`meta_updated_at`**, and nothing else
writes them. `--by` names the **actor**: an agent making the change on a human's
authorization stamps itself, so that a row naming a person means that person typed it.
It defaults the way `add --created-by` does, to a synthetic actor rather than to
whoever happens to be logged in.

**They are not `updated_at`, and the separate pair is the point.** `updated_at` moves
on every state change, every fire and every predicate error, and several verbs bump it
too - it records that the row moved, never who moved it. An actor name paired with it
would read *"Bea, three minutes ago"* on a row whose timestamp the daemon bumped three
minutes ago and whose reason Bea last touched in March.

**The stamp is evidence, not proof, and the guarantee runs the other way.** `--by` is
free text: nothing authenticates it, and anything with the database open can write both
stamp columns directly, so a stamp can be forged. What the stamp buys is the negative:
an **unchanged** stamp beside a changed field is a write that no verb made.

**`audit --baseline <file>` hashes `instruction + predicate_src + predicate_sha +
requester_uid + reason` per ACTIVE task** - *what* the agent does, *when* it does it, who
asked and why - and reports `CHANGED` / `NEW` / `GONE` against that file. For each difference it says
whether a `set-meta` **since the baseline** could account for it, and that is the whole
value: a backfill and a write that went around `sched.py` are the same difference until
the stamp separates them.

**It hashes the instruction and the predicate separately from the other two, because
no verb writes any of them.** A difference there can never be explained by a `set-meta`
and is never annotated with one - a row can carry a perfectly legitimate stamp from
months ago, and printing it beside this morning's rewrite exonerates the single
difference the whole mechanism exists to catch. Those three hash together and the finding
names them, because the next move after any difference in that group is `show <id>`,
which prints the instruction and the predicate in full.

**A rewritten predicate leaves every word an operator reads unchanged**, which is why
it is in there: the title, the instruction, the requester and the reason all still say
the job runs daily, and it never runs again. `simulate --id <task>` fast-forwards the
STORED predicate, so it can show you a dead one - but only if something sent you to look.
This is the only thing that reports the change unprompted.

**`predicate_sha` is audited beside `predicate_src`, and it is not a redundant copy.**
It is the key the compiled-code cache is keyed on, so it decides which code a long-lived
daemon actually runs: rewritten alone, to a sha already cached in that process, it runs
another task's predicate while `predicate_src` still reads honest.

**The audit opens the database READ-ONLY and does not migrate it.** The verb an
operator reaches for when they suspect a raw write must not take a write lock on the
subject, must not create it if it is missing, and must stay usable against a copy.

`--rebaseline` retakes the file - only once every difference has a visible verb behind
it, because rebaselining an unexplained one is how it becomes the new normal. It refuses
a file that some other tool wrote (no `sched.py audit` header), because that tool has no
field-set guard of its own and would read every task as changed afterwards.

**Three exit states, and collapsing them is the failure it guards against.** `0`
nothing moved; `1` something moved, each difference named; **`2` INCONCLUSIVE** - no
database, no baseline, or a baseline whose header does not say it covers the fields this
build hashes. An audit that never reached the tasks must not pronounce on them: the
verdict it would manufacture is the reassuring one, and a reader who sees `OK` stops
looking. That is also why the baseline carries a `fields=` header - widening the hashed
set otherwise reports every task `CHANGED`, which is byte-for-byte what tampering looks
like, on the one morning a reader most needs the two told apart.

## 4. Counts and end-dates are columns; only cadence is the predicate

"5 times" is `--max-fires 5`, not a counter inside the snippet. "Until the 30th" is
`--not-after`, not a date comparison inside the snippet.

**Put a count in the predicate and the daemon cannot close the task itself.** If the
snippet's arithmetic is off by one you get four sends or six, and the archive cannot say
which was intended. With the count in a column, a wrong snippet still stops at five.

## 5. Writing a predicate

```python
def should_fire(now, state):     # now: epoch seconds (float). state: dict from last time
    ...
    return {"fire": True, "missed": 0, "state": {...}, "done": False}
```

Accepted returns: `True` / `(True, state)` / the dict form. `missed`, `done` and `note`
are optional.

**`now` is the only clock in the namespace.** There is no `time`, no `datetime.now()`,
no `date.today()`. That is precisely what makes the simulator faithful rather than
decorative - the daemon and the dry run cannot disagree.

Available: curated builtins, `datetime` / `date` / `timedelta` / `timezone` / `UTC`,
`math`, `TZ` / `TZNAME`, `MON`...`SUN`, `BOOT_TIME` / `uptime(now)`, and the helpers
`local(ts)`, `epoch(dt)`, `at_time(dt, h, m)`, `day_start(dt)`, `is_leap(y)`,
`days_in_month(y, m)`, `nth_weekday(y, m, weekday, n)`, **`due_slots(...)`** and
`interval_slots(...)`.

**`BOOT_TIME` and `uptime(now)` are the one exception to "no clock but `now`", and it is
narrow.** `BOOT_TIME` is read once (`/proc/stat btime` on Linux, `sysctl -n
kern.boottime` on macOS) and cached for the process lifetime, so it is a **constant**,
not a second live clock - the predicate stays a pure function of `(now, state)` plus
that constant, and the simulator stays faithful. `simulate()` injects `0.0`, which
reads as infinite uptime, so a dry run shows the schedule a long-lived host would
produce rather than one suppressed by a guard. A boot time neither source answers gives
the same infinite uptime: a guard that cannot evaluate must not suppress work. That
failure is silent, so `sched.test.py` requires a real boot time on every supported
host.

**Use it for any task whose action destroys the session that reports it** - reboot,
agent restart, restarting a unit the session depends on. Such a task, if its slot is
missed, fires on the next boot and destroys the session again, and the cycle is *not
self-limiting*: the reboot kills the session before `run-result` can be written, so the
state never advances and the next boot reproduces it exactly. The uptime guard below is
what breaks the cycle.

```python
    if uptime(now) < 3600:
        return {"fire": False, "state": {"last_due": slots[-1]},
                "note": "slot consumed: host booted within the last hour"}
```

**Consume the slot, do not merely defer it.** Returning `state` unchanged leaves the slot
owed, so a suppressed 05:00 reboot fires at 10:30 instead - which is worse than either
alternative. The maintenance did happen; it just was not this task that caused it.

**Restart the daemon after editing `sched.py`, and prove it took.** The daemon imports
the module once at start; a later edit changes only what the *next* process runs. Every
verification tool here - `sched.test.py`, `simulate`, `list`, a direct `evaluate()` - runs
in a fresh process and will pass against code the daemon is not executing. A predicate
that calls a helper added after the daemon started raises `NameError` on every tick in
the running daemon, reaches `MAX_ERRORS`, and its task stops firing while every one of
those tools reports it healthy. Compare `ps -o lstart= -p <pid>` against the file's
mtime before believing a change is live.

Rules, each with the consequence that earns it:

- **Pure.** No I/O, no imports, no network. A predicate that tries to *do the work*
  runs inside the daemon with no tools, no session and a quarter-second budget - it will
  time out, and the symptom is a schedule that never fires rather than an error.
- **Terminating.** Hard-killed at `eval.timeout_secs`. A timeout is treated as "did
  not fire" and its state is not written, so a predicate that times out *every* tick is
  a task that silently never runs.
- **No `try`/`except`** - rejected at write time. A bare handler swallows the timeout
  exception and loops forever, taking the whole scheduler with it. `state.get(k, default)`
  covers the only real need.
- **State is the only memory, and it must round-trip JSON.** Return a `set` and it
  comes back a `list` next tick, changing what the predicate does on day two. The
  evaluator rejects it on day one instead.
- **Never compare time for equality.** `local(now).hour == 9` depends on landing
  exactly inside the right hour and, worse, fires *zero* times after any outage that
  spans it. Use the slot-key idiom.

### The slot-key idiom - the pattern, not a style note

Derive a **key** for the slot the work belongs to, fire only if that slot's start has
**passed** and you have not already fired for it, then record it. `due_slots()` does the
derivation for you.

That buys four properties at once: fires once per slot regardless of tick rate; fires on
the first tick *after* a boundary rather than needing to hit it; a machine that was down
through the boundary fires **once** on return rather than zero or eight times; and no
drift, because the key comes from the wall clock and never from arithmetic on the last
fire.

**Coalescing is a property of your predicate, not of the daemon.** The daemon never
replays a missed tick - it evaluates once per tick against the current time. Written
with a slot key, a three-day outage produces one fire reporting `missed=3`. Written as
an equality test, it produces **nothing**, and nothing tells you.

### The template

Edit `HOURS` and `skip_day`; leave the rest alone.

```python
HOURS = (9,)                  # local wall-clock hours this task is due at
ARM_LOOKBACK = 8 * 86400      # how far back to look when arming

def skip_day(d):              # d is a date; True skips the whole day
    return False

def should_fire(now, state):
    last = state.get("last_due", 0)
    if not last:
        # ARM. Record the most recent slot that has ALREADY passed, and do not fire.
        # Without this, installing a daily 09:00 job at 14:00 fires immediately, which
        # reads to a human as a bug.
        prev = due_slots(now - ARM_LOOKBACK, now, HOURS, TZ, skip=skip_day)
        return {"fire": False, "state": {"last_due": prev[-1] if prev else now}}
    slots = due_slots(last, now, HOURS, TZ, skip=skip_day)
    if not slots:
        return {"fire": False, "state": state}
    # COALESCE (the default): N due times passed while we were down, so fire ONCE and
    # report N-1 missed.
    return {"fire": True, "missed": len(slots) - 1, "state": {"last_due": slots[-1]}}
```

**Do not write the arming branch as `due_slots(last or now, now, ...)`.** That is an
empty window on the first evaluation, so `last_due` is never recorded and the task never
fires - for ever, silently. The simulator (section 7) shows it as a run with zero fires.

## 6. Three worked examples

**(a) "send hello in this group 5 times with 1 minute interval"** - interval cadence in
the predicate, the count in `--max-fires 5`:

```python
INTERVAL = 60
TOTAL = 5

def should_fire(now, state):
    sent = state.get("sent", 0)
    nxt = state.get("next", now)
    if now < nxt:
        return {"fire": False, "state": state}
    # Re-anchor on `now` and do NOT count missed boundaries as sends: the request asked
    # for FIVE hellos. Downtime may delay them; it must not eat them.
    missed = int((now - nxt) // INTERVAL)
    sent += 1
    return {"fire": True, "missed": missed,
            "state": {"sent": sent, "next": now + INTERVAL},
            "done": sent >= TOTAL, "note": f"hello {sent}/{TOTAL}"}
```

**(b) "research competitors once per day daily and send summary to me over email"** -
the template with `HOURS = (9,)` and no skip rule.

**The schedule is legal; the described action may not be.** Standing rules bind a
task at 3am exactly as they bind a live request at 3pm. Where sending email requires a
human, the *instruction* is written as "compose the summary as a draft and post the
draft link to the origin" - and written that way in the task row, not just intended.
**A task description that says "send" is a rule violation stored on disk waiting for a
night when nobody is awake.** The charter is the authority here.

**(c) "validate this link every day 2 times except leap years and every second monday"**

**Do not encode this as written.** It has at least three honest readings: is "every
second Monday" the 2nd Monday of each month or a fortnightly cadence? Is "except leap
years" the whole year or 29 February? Ask, then encode. An ambiguous schedule that is
guessed at runs wrong for a month before anyone notices, because a scheduler firing on
the wrong days looks exactly like one that is working.

For the settled reading *"09:00 and 21:00; skip the whole year if it is a leap year;
also skip the second Monday of each month"*:

```python
HOURS = (9, 21)
ARM_LOOKBACK = 40 * 86400

def skip_day(d):
    if is_leap(d.year):
        return True
    if d.weekday() == MON and 8 <= d.day <= 14:   # the SECOND Monday
        return True
    return False
```

`8 <= d.day <= 14` is the second Monday. `d.day <= 7` is the **first** - an easy
transposition that no test catches unless you look at real dates, which is what
`simulate` is for.

## 7. The dry-run simulator

```bash
"${CLAUDE_SKILL_DIR}/sched.py" simulate --predicate-file p.py --days 14 --step 300
"${CLAUDE_SKILL_DIR}/sched.py" simulate --id <task> --days 6 --outage '2026-08-06T08:00..2026-08-09T10:00'
"${CLAUDE_SKILL_DIR}/sched.py" simulate --predicate-file p.py --start 2028-02-20T00:00 --days 30   # leap year
```

It fast-forwards a fake clock through the **same code path the daemon runs**, prints
local fire times, and takes `--outage` to prove coalescing. `--json` gives you the fire
list a confirmation is rendered from.

| Warning | Why it matters |
|---|---|
| `never fires in this horizon` | **The failure with no symptom.** A dead schedule is indistinguishable from a quiet one. This is the only place it is ever visible. |
| `N fires/day` | Every fire is a wake-up line in the session. |
| `never returns done` | Runs forever unless `--max-fires` or `--not-after` is set. |
| `due times folded into fewer fires` | Coalescing happened - confirm that is what was wanted. |
| `ERROR: ...` | It would have failed live, at 3am, instead of here. |

**Always simulate across a DST boundary for a wall-clock schedule, and across a leap
boundary for anything mentioning years.** A `last + 86400` style predicate drifts by an
hour twice a year, and the symptom is a report arriving early - which reads as flakiness,
so nobody files it.

## 8. Running the daemon, and arming its follower

```bash
"${CLAUDE_SKILL_DIR}/sched.py"            # tick loop - run by a SERVICE MANAGER, never a Monitor
"${CLAUDE_SKILL_DIR}/sched.py" --once     # single tick, smoke test (skips the lock)
"${CLAUDE_SKILL_DIR}/sched.py" doctor     # resolved config, DB health, armed state, origin format
pgrep -af "[s]ched.py"                  # is ANY daemon running? (not: is MINE); macOS: pgrep -fl
```

**The tick loop runs as a supervised service that restarts it, and the session arms a
FOLLOWER of its output under a persistent Monitor.** A Monitor lives a bounded time and
the harness ends it; a daemon that is a Monitor's child is down from that moment until
the session re-arms it, firing nothing and saying nothing, and the gap is longest
exactly when the session is busy, compacting or restarting. A service does not stop
with the Monitor. Its output goes to a log, and the follower prints every line of it
the session has not seen yet, from a saved position, so a due line written while no
Monitor was armed arrives on the next arm instead of being lost. The install's
`CONTEXT.md` names the service, the log and the follower command; on a fleet host the
service unit and the follower both come from the fleet's daemon manager
(`systemd/agent-daemons.py` in the fleet tree). **The log is written only by its
service: never edit it in place (`sed -i` or any rewrite), move, truncate or delete
it; read it, or copy it** - the service opens it once, at start, so a rewrite leaves
the daemon writing to the old file while the follower reads one that never grows.

**The standing duty is therefore two checks and one arm, at session start and on every
Monitor expiry:** the service is active (the service manager's own state, never "is
there a child process"), and the follower is armed. Re-arming the follower is safe to do
unconditionally: a second one on the same log refuses with one line.

The daemon's guards are an owner check against `owner.claude_config_dir` and
an flock, **both exiting 0**. Under a service manager that exit is the one exit that must
not be retried - a retry changes nothing - so the service stays down with the
`SCHED-GUARD` line in its log, and the follower reports the service as not active.

**The DB path comes from the config this process resolved, and the lock lives beside
the DB** - so two daemons sharing one config cannot both run. `SCHED_DB` overrides the
path for a one-off, a throwaway database for a smoke test; it is not how a deployment is
configured.

**A launcher that exports `SCHED_CONFIG` or `SCHED_DB` inconsistently forks the
state.** Two daemons, two databases, every task firing twice - and nothing anywhere
reports it, because each daemon is behaving correctly against the database it was told
about. Where a deployment runs more than one scheduler, each one's `SCHED_CONFIG` is set
in exactly ONE place, and `sched.py doctor` is what proves which database a session is
actually talking to. Do not infer it from which agent you are.

**`pgrep` answers a different question than the one you are asking.** It says a
daemon is running, not that *yours* is: where a deployment runs one scheduler per agent
it returns a line per daemon and none of them is labelled. The per-agent evidence is the
lock on the file beside that agent's database, and `doctor` is what tests it - it prints
`armed` against the config it actually resolved. Use `pgrep` to see that something is
alive and `doctor` to see whether it is yours.

**The bracket narrows the lie; it does not remove it.** `pgrep -af "sched.py"`
matches the shell running it, so the pattern is written `[s]ched.py` - but that protects
`pgrep`'s own argument list ONLY. If the literal `sched.py` appears anywhere else on the
wrapping command line - an echo, a heredoc, a log path, a script that edits this file -
the bracketed form matches that shell too. Measured: both forms return the editing
shell on a machine where no daemon is running.

**So the checker must not be able to match itself, and `pgrep` structurally can.** The
lock cannot: the lock file stays on disk after the daemon dies and only the lock on it
is released, so `doctor` tests the lock, never the file's presence, and a leftover file
or its contents never block a start. `doctor` names a `lock holder` only while the lock
is held (the pid in a leftover file is a daemon that is gone), and `installation/check`
makes the same non-blocking flock attempt. Ask `doctor`, not `ps`.

**Not arming the follower is invisible.** A running scheduler whose follower nobody
armed looks exactly like a day with nothing due: the lines pile up in the log and never
wake the session. Nothing will ever tell you, and no error is ever raised. Check; do not
assume.

**A daemon restart replays pending runs.** At every start the daemon re-emits each
`pending` run older than `emit.replay_grace_secs` with `replay=1`, up to three times per
run, then marks it `lost`. A supervised daemon starts more often than a Monitor-run one
(a crash, a code change, a scheduled refresh), so an unacknowledged fire can reach the
session again as `replay=1` beside its original line from the log. A replay never fires
the task again or creates a run - `sched.test.py` section 15 pins that across a restart loop -
and `run-result` is what stops it.

## 9. The fire line

```
SCHED due [tsk_20260804T2011Z_a3f19c] run=417 "Weekly digest" origin=CEXAMPLE01(#ops) via=slack thread=1784577731.070209 by="Ada" missed=0 - why: the ops channel has no other weekly signal and the Monday standup runs off it - build the digest and post it in the origin thread
```

| Field | Why it is inline |
|---|---|
| `SCHED due` | two-token sentinel; `SCHED alert` shares the greppable prefix |
| `[tsk_...]` | the handle for every CLI verb |
| `run=417` | closes the loop with `run-result 417` and no lookup |
| `origin=` | where the answer goes - id, with a label in parentheses if there is one |
| `via=` | the chat transport the answer goes out on - load that transport's skill to reply. Absent for a `session` origin |
| `thread=` | present only when the task was born in a thread, **always paired with its origin** |
| `by=` | who asked, by name (section 3). **Quoted**, because it holds human text and the prefix is a space-separated field list - `claude cli terminal` is in the vocabulary, so a space in this value is certain rather than hypothetical |
| `missed=` | how many due times were folded in - say so when you report |
| `- why: reason` | why the task exists - **before** the instruction, and that order is load-bearing |
| `- instruction` | the payload, always last |

**Never take a thread id from one place and a channel from another.** The line pairs
them for exactly this reason: some chat APIs silently post to the wrong place rather
than rejecting a mismatch.

Nothing structural is ever truncated; an over-long payload degrades into `... (full
text: sched.py show <id>)` rather than into a lie.

**The reason precedes the instruction because the line budget cuts from the END.**
With the instruction first, every task whose instruction is long enough to truncate
loses its reason entirely - silently, on exactly the wake-up where you are least able to
go and ask why the task exists. Reason first means a long instruction is what gets cut,
and its truncation already carries a pointer to its own full text. `emit.reason_chars`
caps the reason so it cannot starve the instruction in return.

**`SCHED alert`** is the one other stdout line: a rate-limited escalation for a DB the
daemon can no longer use. It means nothing will fire until a human intervenes.

## 10. When a fired task fails

Report the failure into the task's origin, record it with
`run-result <id> --status failed --outcome '...'`, and **leave the schedule running**.
Nothing retries by itself.

A failure report is still a report - the same content rules apply to it as to the
work. A message quoting a filename or a row can disclose as much as the document.

If the origin is unreachable (thread parent deleted, bot removed from the channel), fall
back in order: the origin channel top-level -> a direct message to the requester -> say it
in session. Never drop the report because its address went stale.

**`by=` is a NAME, not an address.** Resolve it back through the requester directory
(section 3) - the same map, read in reverse - and where it does not resolve to a person at all,
which is the correct answer for an interface value or a self-originated task, skip
straight to saying it in session rather than inventing a recipient.

## 11. CLI

| Verb | What it does |
|---|---|
| `add` | create a task; dry-runs the predicate and **refuses** a dead or runaway one, and refuses outright without `--reason` |
| `list [--status live\|all\|...] [--json]` | what is scheduled |
| `show <id> [--runs N]` | full task, its predicate and its run history |
| `set-meta <id> [--requester] [--reason] [--by]` | change who asked and why, in place - the ONLY way to backfill them (section 3). Stamps `meta_updated_by`/`meta_updated_at`; `--by` names the ACTOR |
| `audit --baseline <file> [--rebaseline] [--force]` | hash instruction+predicate (src and sha)+requester+reason per active task against a baseline; CHANGED/NEW/GONE, saying whether a `set-meta` since the baseline could account for each. Read-only. 0 clean / 1 drift / **2 INCONCLUSIVE** (section 3) |
| `pause` / `resume [--rearm] [--reset-errors]` | stop and restart evaluation |
| `cancel <id> [--reason]` | terminal; the schedule is over. Its `--reason` is why you are CANCELLING; the task's own `reason` (section 3) is why it existed, and `cancel` never touches it |
| `run-result <run_id> --status ok\|failed\|skipped [--outcome]` | close the loop |
| `archive` / `purge --yes` | retention; `purge` is the only destructive verb |
| `simulate` | the dry run (section 7) |
| `doctor` | resolved config, integrity, counts, armed state, lost runs |

**`add` refuses two things without `--force`**: a predicate that never fires in the
horizon, and one that fires more than `add.fires_per_day_warn` times a day. These are
the two mistakes an authored snippet actually makes - one silent for weeks, one that
floods the session immediately.

**A third refusal, and `--force` does NOT override it: a missing `--reason`.** The
other two are mistakes about a schedule and show up within weeks; this one is a mistake
about *purpose* and shows up in a year, as a task nobody can justify and nobody will
cancel. There is no hurry that makes it worth skipping - the refusal itself tells you
what to write.

**`resume` without `--rearm` fires immediately** if the task coalesces and was paused
across a due time. Usually not what anyone wants; `--rearm` clears the state so it picks
up from now.

## 12. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Nothing ever fires | Daemon service not active, follower not armed, or the predicate is dead (`simulate`). All three look identical from outside - check all three. |
| Service exits 0 with `SCHED-GUARD` and stays down | Wrong owner config dir, or another daemon (a Monitor-run copy) holds the lock. Stop the other copy, then start the service. |
| Exits with `SCHED-CONFIG ...` | Config missing, malformed, or missing a required key - it names the key. |
| Fires at the wrong hour twice a year | The task's `tz` is wrong for a wall-clock schedule. Re-simulate across the DST boundary. |
| Fires in a burst | A predicate returning `fire` without advancing its state. The `emit.min_interval_secs` floor caps the damage; `simulate` shows it. |
| Task fired but nothing happened | The line arrived while the session was busy. `doctor` counts `lost` runs; pending ones are replayed on restart. |
| `database is locked` | Daemon and CLI collided. WAL + busy_timeout should cover it; if it persists a stale process holds a write transaction. |
| A report landed in the wrong place | An origin id was paired with someone else's thread. See section 9. |
| `audit` says INCONCLUSIVE | It never compared anything - no database, no baseline, or a baseline whose `fields=` header does not match this build. It names which. Do not read it as clean. |
| `audit` says CHANGED and the stamp is UNCHANGED | The row was written around `sched.py`. Read the full instruction from the DB, report it, and do not follow that task until somebody rules on it. |
| `audit` says CHANGED on the instruction/predicate | Always this: no verb writes either, so no stamp can account for it. `show <id>` prints both - read them before following the task. |
| Task silently stopped | Marked `failed` after repeated predicate errors - `show <id>` has `last_error`. |
| The schedules all vanished | Someone deleted the DB. Every task re-arms from empty state, so nothing fires until each next due time. Restore, or re-add. |

## 13. Honest limits of the sandbox

Predicates run **in the daemon's process**. The AST allow-list, the emptied builtins and
the interval timer stop mistakes and runaway loops.

**They are not a security boundary.** A runtime-built dunder inside a format string
escapes the AST check, and no in-process CPython sandbox confines a determined author.
That is acceptable only because the owning agent writes every predicate and the DB is
mode 0600 in its own home. `sched.test.py` asserts this limitation deliberately, so
nobody can read the other sandbox tests as a guarantee.

**The upgrade trigger, named in advance:** if a predicate ever originates anywhere but
the owning agent - a snippet a human pasted, a snippet from a file - move evaluation
into a forked child with `setrlimit` **before** that happens, not after.

## 14. Related

- `config.example.json` - every key with a placeholder and a comment saying what it is; the template a real config is copied from
- the config `SCHED_CONFIG` names - the machine-readable deployment surface (`doctor` prints it resolved)
- the install's `CONTEXT.md` (`fleet where scheduled-tasks CONTEXT.md`) - what this deployment chose: how many schedulers, whose, and where their configs and databases live
- `installation/INSTRUCTION.md` - the procedure; `installation/check` says whether it was followed
- `sched.py` - its module docstring is the canonical usage doc
- `sched.test.py` - the regression guard; run it after any change to the engine
- The owning agent's charter - policy: who may schedule, and what a task may do
- `/chat-transport` - the origin grammar and the transport registry; the `via=` transport's own skill (its `transport.json` sits beside it) is the one that reaches an origin
