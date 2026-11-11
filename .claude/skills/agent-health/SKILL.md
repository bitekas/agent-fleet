---
name: agent-health
version: 1
description: >
  Proactive usage monitoring for a fleet of long-running agents: sweep every
  live agent's session, read its /usage screen, and move that agent onto the
  pool account with the most usable headroom BEFORE the cap lands rather than
  after - on an absolute floor,
  and before that on a projection of when each window will deplete at the rate
  it is currently filling.
  A cap that arrives unannounced kills the agent's subagents on
  HTTP 429 and strands whatever they were holding; a planned handover stops the
  tree cleanly, writes a handover package, switches the account and resumes from
  the package. A login agent is read off its /usage screen and switched
  in-session; a token agent (claude setup-token), whose /usage shows no plan rows,
  is read off the rate-limit snapshot its status line writes and switched by
  installing the next account's token and restarting it through its unit. Owns the
  pool's picker, its lease file, its usage ledger and its handover ledger.
  Universal: no host, person, path, agent name or credential is
  named here, the concrete values live in the install's CONTEXT.md. Load
  before running a usage sweep, before deciding whether an agent needs a
  handover, and before typing anything into another agent's pane.
requires_install: false
---

# agent-health - move an agent before the cap, not after

A long-running agent hits a usage cap without warning. When it does, every
subagent it has in flight fails on HTTP 429, the work they were holding is lost,
and the agent itself sits at a capped prompt for hours (a session window) or
days (a weekly one). Reviving it afterwards is `/agent-revive`'s job and it
works, but it is a recovery: the tree is already dead by then.

**This skill is the version that happens BEFORE.** It watches the usage
percentage of every live agent, and at a threshold - while the agent is still
fully functional - it stops the tree in an orderly way, takes a handover
package, switches the account, and puts the agent back to work on the package.
Nothing is lost because nothing was interrupted.

**This file is the MECHANISM and names nothing install-specific.** No host, no
person, no absolute path, no agent name, no credential. Where a concrete value
is needed it names the config key or points at `CONTEXT.md`, which lives in the
skill's install context, `<install root>/.claude/skills/agent-health/`
(`fleet where agent-health` prints it). Every other file below is in this
directory, and prose runs a script here as `"${CLAUDE_SKILL_DIR}/<script>"`.

| File | What it holds | Per install? |
|---|---|---|
| `SKILL.md` (this) | the sweep, the thresholds, the messages, the traps | universal |
| `CONTEXT.md` | the roster command, the sweep cadence, the socket/target templates, where handover packages go, which agent owns this | **this install** |
| `parse_usage.py` | turns a captured /usage screen into numbers, a velocity, a projection and a verdict, and appends the reading to the usage ledger | universal |
| `parse_usage.test.sh`, `fixtures/` | the offline regression guard, including its negative control and the one pair that can see the two-consecutive-checks rule disappear | universal |
| `pool_pick.py` | picks the pool account a handover switches to, from the pool, the leases, this skill's usage ledger and the agent's auth mode; is the one writer of the lease file and the handover ledger (`--take`, which also installs a token agent's token, and `--record`); and is the one way an account enters the pool (`--register`). `/agent-revive` step 5 owns the rule, the script's header the detail | universal |
| `usage_statusline.py` | a token agent's status-line command: keeps the session's `rate_limits` in `<config dir>/fleet-usage.json`, which `parse_usage.py --rate-limits` reads (step 4) | universal |
| `pool_pick.test.py`, `fixtures/pool/` | its offline guard: every clause of the pick, its negative control (a missing ledger or lease file is exit 2, never a pick), a mutation control per rule, and the no-password-in-any-output scan | universal |
| `pool_mechanism.test.py` | the pool as a mechanism: register, a projected cap handed over to the other account end to end, the lease race (one winner, with its lock-free negative control), the ledger round trip, the status-line writer | universal |
| `shared_lease.test.py` | shared leases: refused while accounts >= agents, one lease naming every holder, one reading per account per sweep, the whole group handed over | universal |

**This skill has NO `config.json` of its own, deliberately.** Everything machine
readable it needs already exists: an agent's tmux socket dir and target, its
config dir and its auth mode are `agent-revive`'s `tmux_triage.sh <agent>
--facts` (read off the agent's unit, with `agent-revive`'s `config.json`
templates as the fallback), and
the roster command is in `CONTEXT.md`, and the ledger path is the owning
agent's own (`CONTEXT.md` again). The account pool's paths, the lease file,
the ledger path the picker reads, the handover ledger (`handover_ledger_file`),
the token directory (`tokens_dir`) and the exclude list are `agent-revive`'s
`config.json` `accounts` block, which `pool_pick.py` reads by default. The
thresholds and the depletion horizon are in `parse_usage.py`, and the pick's
two lines (80% excluded, 30% headroom) in `pool_pick.py`, as named constants
with the tests that pin them. A second config file holding a
second copy of the tmux templates is a file that drifts from the first, and it
drifts silently in the direction of a sweep that reads the wrong server.

**This file contains no policy.** WHICH agents are swept, how often, and who is
told about a handover live in the owning agent's charter, which `CONTEXT.md`
names.

**Glyphs.** This file is ASCII. A character Claude Code draws on the pane is written
as its code point in braces: `{U+276F}` is the prompt and selection cursor,
`{U+2500}` the box-drawing rule, `{U+25EF}` an idle agent's ring, `{U+2193}` the down
arrow, `{U+00B7}` the middle dot, `{U+2588}` and `{U+258C}` the full and left-half
blocks of a usage bar (`x20` repeats one twenty times), `{U+2026}` an ellipsis.
`parse_usage.py` and the recipes below match the glyphs themselves.

---

## Thresholds

Two rules. The floor reads one capture; the projection reads two.

### The floor - fires on sight, needs no history

- **A SHORT window at 90% or more triggers a handover.** A short window is the
  rolling one that resets several times a day - the one an operator calls "the
  daily limit". On the measured build it is labelled `Current session`.
- **Any OTHER limit at 95% or more triggers a handover.** In practice the weekly
  windows.

It is the backstop, not the main instrument: it catches usage that arrived
faster than two readings could see it, and it is deliberately independent of
everything below. A floor trigger at a velocity of exactly zero is still a
trigger.

### The projection - the early warning

- **Velocity** is the change in `% used` since that window's previous reading,
  per hour.
- **Projected depletion** is `now + (100 - %) / velocity`.
- **SWITCH when the projection lands within 60 minutes on TWO CONSECUTIVE
  checks AND the window's reset falls after that moment.**
- **A window whose reset precedes the projected depletion is left alone.** It
  empties itself; a handover taken to dodge a cap that was never going to land
  costs the stop-and-resume and buys nothing.
- **A first reading is recorded, not acted on**, and so is a velocity of zero
  or below. No previous row means no slope; a flat or falling one projects no
  depletion at all.
- **A reading that produces NO projection does not CLEAR a standing trip.**
  These agents work a turn and then wait - on a subagent, a monitor, a person -
  so their velocity alternates between a burst and zero. If a zero reading
  reset the consecutive counter, a bursty agent would trip the horizon again and
  again, never be switched, and meet the floor at 100% with the cap already
  landed - measured on a simulated one. Absence of progress is not evidence of safety.

**Two checks, because one pair of readings is a slope through two points.** A
single burst of work draws a slope that says an hour, and switching on it hands
over an agent that was about to go quiet.

**Velocity is computed per window, against that same window's own previous
row on the SAME account.** Two windows fill at different rates, so a velocity
across them is a number that looks right and means nothing; and a reading on a
new account compared against one on the old is arithmetic across a
discontinuity, wrong in the hand-an-idle-agent-over direction. `parse_usage.py`
matches on both and records a first reading when either differs.

**The previous row comes from the usage ledger and from nowhere else, and a
missing ledger file is an instrument fault, not an agent with no history.** A
mistyped `--ledger` path makes every window a `first-reading` for ever: every
sweep recorded, none ever acted on, the fleet reported healthy while nothing is
being measured. `parse_usage.py` exits 2 rather than pronouncing. The ledger is
created once with `--init`. **The same refusal covers `--account`** - the
previous row is matched on the window AND the account, so an omitted account
matches nothing and is the identical failure - and **a ledger is required
outright** unless `--floor-only` is asked for explicitly, because forgetting the
flag otherwise buys a floor-only reading reported as `ok` at exit 0.

### What this rule does NOT buy at the sweep cadence - measured 2026-09-22

The sweep cadence *c* is the interval between sweeps, a value `CONTEXT.md`
names. The numbers below are worked at a 30-minute cadence (`c = 0.5 h`); put
the install's own *c* into the same formulas. They are stated plainly because
they do not compose, and a reader who assumes they do will trust the projection
to do work the floor is actually doing:

- **Below a cut-off velocity the projection CANNOT fire before the short-window
  floor.** With cadence *c* and horizon *h*, the second consecutive in-horizon
  check lands at `p >= 100 - v*(h/60 - c)`; at `c = 0.5 h`, `h = 60 min` that is
  `p >= 100 - v/2`, which the 90% floor pre-empts for every `v <= 20 %/h`. For
  a long window (floor 95) the cut-off is 10 %/h. In that range the projection
  is strictly dominated by the floor it is meant to improve on.
- **Where it does fire, it fires with `h - c` of runway** (30 minutes at
  `c = 0.5 h`), and step 7 alone budgets up to 30 minutes for the sentinel,
  before step 8's five and the sign-in. For the projection to buy anything the
  horizon has to exceed **cadence + handover duration**, i.e. ~120 minutes at a
  30-minute cadence, not 60.
- **The floor's own claim is cadence-bound too.** A 90% floor catches a short
  window before 100% only while `v <= (100 - 90) / c` (20 %/h at `c = 0.5 h`);
  at 36 %/h and that cadence a window moves 18 points between sweeps, so
  88 -> 100 with no reading in between.

None of that is an argument for removing the projection - it is what the rule
does, and the carry-forward above is what makes it fire at all on a bursty
agent. It is the input to a decision about the three numbers, which belongs to
whoever owns the cadence.

**A `working` agent is read like any other.** /usage and /status are
dialogs of the Claude Code client, drawn over the pane and dismissed with
Escape; nothing about them enters the model's context or the running turn. The
agent mid-turn is the one burning usage, so it is the reading the sweep most
needs. The only skip is typed, unsubmitted input (step 2), and a skipped agent
is re-checked 5 minutes later, not at the next cadence.

**The window is classified off the `Resets` line, never off the limit's
NAME.** A reset that is a bare time of day is a short window; one carrying a
date is a long window. Names move between Claude Code versions and between
plans, and there is no limit literally labelled "daily" on the measured build -
a rule keyed on the word `daily` would match nothing and report every agent
healthy for ever. The reset shape is what actually encodes how long the window
is. `parse_usage.py` applies exactly this rule; an unclassifiable reset is
treated as SHORT, i.e. the stricter threshold, so the failure mode is handing
over slightly early rather than missing a cap. The same line is also resolved
to an absolute time for the reset-versus-depletion comparison, and a reset that
cannot be resolved counts as LATER than any projection - fail-safe in the same
direction.

---

## Measured: what the /usage screen actually looks like

**Measured 2026-09-16 on Claude Code 2.1.273, a subscription plan, model Fable.** Read
this before writing anything that parses the screen: the layout below is the
subject, not a guess at it.

/usage and /status are two TABS OF THE SAME dialog. It opens with a tab bar,
carries a `Esc to cancel` footer, and Escape dismisses it (the pane then logs
`Settings dialog dismissed`). The usage tab:

```
  Settings  Status   Config   Usage   Stats

  Session

  Total cost:            $0.0000
  Total duration (API):  0s
  Total duration (wall): 1m 8s
  Total code changes:    0 lines added, 0 lines removed
  Usage:                 0 input, 0 output, 0 cache read, 0 cache write

  Current session
  {U+2588 x20}{U+258C}                              41% used
  Resets 1:20am (UTC)

  Current week (all models)
  {U+2588 x5}                                              10% used
  Resets Sep 23, 8pm (UTC)
  +50% weekly limits promo ended {U+00B7} now +25% permanently {U+00B7} clau.de/cc-25-weekly

  Current week (Fable)
  {U+2588 x5}{U+258C}                                             11% used
  Resets Sep 23, 8pm (UTC)

  Usage credits
  Usage credits are off {U+00B7} /usage-credits to turn them on

  Esc to cancel
```

What that means for a parser:

- **A limit is a three-line group**: a NAME line, a bar line whose right-hand
  end reads `NN% used`, and a `Resets ...` line. There is one group per limit
  and the count is not fixed.
- **The `Session` block at the top is NOT a limit.** It is cost and duration
  stats and carries no `% used`. It is skipped by having no percentage on it,
  which is why the percentage is the anchor rather than the block order.
- **`Usage credits` is not a limit either.** It prints on/off, no percentage.
- **The limit names on this build are `Current session`, `Current week (all
  models)` and `Current week (<model>)`.** There is no limit called "daily" and
  none called "5-hour". Do not key anything on these strings.
- **Windows:** `Resets 1:20am (UTC)` is a time of day only, so `Current session`
  is the SHORT window; `Resets Sep 23, 8pm (UTC)` carries a date, so both weekly
  entries are LONG windows.

The /status tab, measured in the same session, is where the signed-in account
is read (step 3). It states it outright on an `Email:` line; the `Organization:`
line beside it renders the organisation's NAME on a Workspace account and is not
the account.

```
  Version:                 2.1.273
  Session kind:            interactive
  Login method:            Claude <plan> account
  Organization:            <account>'s Organization
  Email:                   <account>
  Model:                   claude-fable-5-1[1m] (claude-fable-5-1)
```

---

## The sweep

### 1. Get the roster, and skip yourself

`CONTEXT.md` names the command that lists the agents with a live session. It is
run rather than read out of a file: a roster written down goes stale as an agent
nobody sweeps.

**Drop your own name from the list.** An agent that sends /usage into its own
pane is typing into the session that is running the turn.

**Then read each agent's facts** - `"${CLAUDE_SKILL_DIR}/../agent-revive/tmux_triage.sh"
<agent> --facts`, one JSON object, no keystroke. `<tmux_tmpdir>` and
`<tmux_target>` in every recipe below are its `tmux_tmpdir` and `tmux_target`, and
its `auth` decides the route:

| `auth` | Usage is read from | The switch (step 9) |
|---|---|---|
| `login` | the /usage dialog on its pane (steps 2-4) | in-session, `/agent-revive` |
| `token` | its rate-limit snapshot (step 4, "A token agent"), no keystroke | `token_switch.py`, a restart through its unit |
| `api-key` | nowhere: it is billed per token and has no plan windows | none - skip it, and say so in the ledger line |
| `mismatch`, `unknown` | nowhere until a person fixes it | none - report `auth_problem`, issue no verdict |

**And read the pool's shares once per sweep.** With fewer accounts than agents,
agents may hold one account together as a SHARED lease (`/agent-revive` step 5),
and a shared account is read ONCE, its readings attributed to the account rather
than to any agent:

```
python3 "${CLAUDE_SKILL_DIR}/pool_pick.py" --shares --json --roster <the roster, comma-separated>
```

`by_agent` names, for every agent a lease names, whether this sweep reads it
(`read`) and under which ledger section (`section`). An agent with `read: false` is
skipped - its account is read by `covered_by`, the first holder in the roster. A
reader's reading goes to `shared:<account>`: step 5's `--agent` is that section,
not the agent's name, so the baseline survives whichever holder reads it next. A
token group's reading passes `--rate-limits` once per holder's config dir, and the
snapshot written last is the one read: every holder's turns move the account, and
each snapshot is only as fresh as its own agent's last answer.

### 2. Read the pane BEFORE you type into it, every time

One `tmux_triage.sh <agent>` call per agent (`/agent-revive` owns the script and
what each state means). Then:

| State | What the sweep does |
|---|---|
| `healthy` | proceed to step 3 |
| `working` | proceed to step 3 exactly as for `healthy`: the usage dialog is client-local and does not touch the turn. Before step 4's Escape, confirm the capture shows the dialog (`Esc to cancel`) - an Escape into a working pane with no dialog open INTERRUPTS its turn. |
| `signin-url`, `usage-cap` | **the cap already landed.** This is no longer a health sweep, it is a revival: go straight to `/agent-revive`. Do not send /usage. Send a capped pane neither Ctrl-C nor Escape. |
| `login-expired` | **the login already expired**: every turn fails at once behind a ready prompt, and no sign-in URL is on the pane. A revival, not a health sweep: go straight to `/agent-revive` (its step 3 /login route at the ready prompt). Do not send /usage. |
| `token-invalid` | **a token or api-key agent's credential expired or was revoked**: the same dead last word, on an agent /login cannot fix. REPORT it (`/agent-revive` step 5, case 15) and type nothing into the pane. |
| `survey-prompt` | idle and fine. Send `0`, re-triage, then proceed. The same survey drawn over a `working` pane (a background subagent keeps it up) is dismissed the same way: send `0` once when the input line is empty, confirm it is gone, then proceed. Left up, it blocks every read for as long as the subagent runs. |
| `stopped` | idle with none of its daemons running, so nothing will wake it. Proceed to step 3 exactly as for `healthy`, and report the reading: the wake line is `/agent-revive`'s, never this sweep's. |
| `follower-down` | idle and deaf to the daemons named in `followers_down` (its scheduler, or its chat transport) or in `logs_replaced` (a daemon writing to a replaced log), while something else can still wake it. A job in `followers_down` needs a wake exactly as `stopped` does; a job in `logs_replaced` needs its unit restarted, which the refresh job does on its next run, not a wake. Either way: proceed to step 3 as for `healthy`, and report the reading with the jobs named; the wake line is `/agent-revive`'s, never this sweep's. |
| `status-modal` | a dialog is already open. Escape, re-triage, then proceed. |
| `unreachable`, `unknown`, or any state this table does not list | read the pane by hand and report it. Issue no verdict. |

**In every state, a non-empty `followers_down` goes into the report** with the
jobs it names: a `working` agent keeps its state, and the dead follower is still a
wake owed once the turn ends. **So does a non-empty `logs_replaced`**: that job's
daemon writes to a replaced log and nobody hears it until its unit restarts.

**AND READ THE INPUT LINE ITSELF, NOT JUST THE TRIAGE STATE - WITH ITS
ATTRIBUTES.** A pane at a ready prompt can have TEXT sitting in its input,
typed and not submitted. `send-keys -l` appends to it, so /usage becomes
`<whatever was there>/usage` and Enter submits that to the agent as a prompt.
**A non-empty input line means skip this agent NOW and schedule a one-off
re-check of it 5 minutes later** (`/scheduled-tasks`, one fire, requester the
owning agent) - do not clear it, it is not yours. The case this exists for is a
person attached over a second tmux client, half-way through typing a prompt:
that lasts minutes, and waiting a whole cadence leaves the agent unread for it.
**An attached client is not itself a reason to skip**: a pane with a client
attached and an EMPTY input line is read exactly like a detached one. The input
line decides, never `#{session_attached}`.

**But an EMPTY input box is not blank: Claude Code draws a placeholder in
it** - a contextual suggestion such as `keep going`, `Continue from where you
left off.`, `what's in flight now?` or `stand by for Slack traffic` - and a
plain `capture-pane -p` renders it byte-for-byte like typed text. The one
thing that separates them is the SGR attribute: the placeholder is DIM (`ESC[2m`
... `ESC[0m`), typed text is not. So the input line is read with
`capture-pane -p -e` and the dim spans are discarded before deciding it is
non-empty:

```
RULE="$(printf '\342\224\200')"   # U+2500, the box rule of the prompt box's top border
CUR="$(printf '\342\235\257')"    # U+276F, the prompt cursor
env -u TMUX TMUX_TMPDIR=<tmux_tmpdir> tmux capture-pane -p -e -t <tmux_target> \
  | awk -v rule="$RULE$RULE$RULE$RULE$RULE" -v cur="$CUR" 'index(prev, rule) && index($0, cur) {print; exit} {prev=$0}' \
  | sed "s/.*$CUR//; s/\x1b\[2m[^\x1b]*\x1b\[0m//g; s/\x1b\[[0-9;]*m//g"
# anything left that is not whitespace is typed text -> skip this agent, re-check in 5 min
```

The glyphs are built with `printf` octal escapes so the recipe is plain ASCII and
does not depend on the shell's locale; the bytes are the ones Claude Code draws.

**The input line is the `{U+276F}` directly under the box's top border (a run of `{U+2500}`),
never "the last `{U+276F}` on screen".** The agents panel below the status bar marks
its selected row with the same `{U+276F}` glyph, so `grep '{U+276F}' | tail -1` on a pane
with subagents returns `{U+276F} {U+25EF} software-engineer {U+2026}` and the gate reads a
subagent's status as typed input - the same false skip a placeholder read as text
gives, through a different `{U+276F}` (measured 2026-09-22).

On Claude Code 2.1.27x (measured 2026-09-22) a colorless capture reads every idle
agent's `ESC[2m` placeholder as unsubmitted text, so the sweep skips every idle agent
and takes no usage reading anywhere. A sweep that reads the placeholder as input is
blind on exactly the idle agents it can read, for ever, and reports them as skipped
rather than as unread.

### 3. Note the account the agent is signed in as

**Before the capture, not after.** The account is an input to the reading: it
is written into the ledger row, and it is half of what identifies the previous
row a velocity is computed against. Read it after the fact and the row is
stamped with an account that was only assumed.

`tmux_triage.sh <agent> --current-account` answers it with **no keystrokes at
all**, and is the route to prefer - it needs no dialog opened on somebody
else's pane. For a token agent it is the ONLY route: it reads the account off
the agent's auth file (`/agent-revive` step 5), and that session's /status has
no `Email:` line. Failing that on a login agent, the three calls of step 4 with
/status in place of /usage, then Escape; take the account from the **`Email:`**
line. `/agent-revive` step 5 owns why the `Organization:` line is not it.

### 4. Open the usage screen and capture it

Three calls, in this order. The literal send and the Enter are separate calls,
and the literal send carries `--` so text beginning with `/` is typed rather
than parsed as a tmux option.

```
env -u TMUX TMUX_TMPDIR=<tmux_tmpdir> tmux send-keys -t <tmux_target> -l -- "/usage"
env -u TMUX TMUX_TMPDIR=<tmux_tmpdir> tmux send-keys -t <tmux_target> Enter
# wait ~4 s for the dialog to draw
env -u TMUX TMUX_TMPDIR=<tmux_tmpdir> tmux capture-pane -p -t <tmux_target>
env -u TMUX TMUX_TMPDIR=<tmux_tmpdir> tmux send-keys -t <tmux_target> Escape
```

**Escape closes it. Ctrl-C does not**, and on a capped pane Ctrl-C cancels the
session's own automatic continue at the reset time, which has no undo. Always
Escape, and always close what you opened: a dialog left on an agent's pane makes
the next reader see a stuck agent.

**On a `working` pane, confirm the dialog drew before sending Escape.** The
capture must show `Esc to cancel` (or the `Settings  Status  Config  Usage` tab
bar). A working pane's own status line reads `esc to interrupt`, so an Escape
sent with no dialog open interrupts the agent's turn. If the dialog is not on
the capture, send nothing and re-capture a few seconds later.

**Before the send, check the window is tall enough for the dialog, and
resize it if it is not.** `capture-pane` returns only what is on screen, and the
dialog is ~65 rows on the measured build (a per-model `Session` block, three
limits, then a page of usage insights). A detached tmux window nobody has
attached to is **80x24**, which is what every window is after a service restart,
and on it the capture is cut: the top of the dialog with the last window missing
under a `{U+2193}` marker, or the bottom of it with no limit on it at all. Both are
`inconclusive`, and both look like a sweep. A resize is not a keystroke - it
touches no input line and submits nothing - so it is the fix, taken before the
three calls above:

```
env -u TMUX TMUX_TMPDIR=<tmux_tmpdir> tmux display -p -t <tmux_target> '#{window_height}'
# height under 70, attached or not: resize for the reading
env -u TMUX TMUX_TMPDIR=<tmux_tmpdir> tmux resize-window -t <tmux_target> -x 120 -y 70
# ... send, capture, Escape (the three calls above) ...
# IMMEDIATELY afterwards, resized or not: put the window back on client-following sizing
env -u TMUX TMUX_TMPDIR=<tmux_tmpdir> tmux set-option -w -t <tmux_target> window-size latest
```

**`resize-window` pins the window's `window-size` option to `manual`, and
that outlives the capture.** A person attached at that moment sees the window
clipped at the bottom and padded with `{U+00B7}` filler wherever their terminal is
smaller than the pinned size, and a person who attaches LATER gets the same
clipped window, because a manual size no longer follows the client. So
`window-size latest` is set on the window immediately after the reading, whether
the sweep resized it or not, and a window is never left on `manual`. With that
done straight after the capture, a window a client is attached to is resized for
the reading too: the attached person sees the 120x70 window for the seconds the
reading takes, and then the window follows their terminal again.

Measured 2026-09-23: a window a fleet restart leaves at 80x24 returns a capture
cut in both shapes, and the resize makes the next capture complete; a person
attaching to a window left on `manual` sees it clipped and dot-filled, and
re-attaching does not fix it until `window-size` is `latest` again.

#### A token agent: its rate-limit snapshot, and no keystroke

**A token agent's /usage dialog shows no limit at all**, so steps 2 and 4 cannot
read it. The dialog fetches its plan rows only for a sign-in carrying the
`user:profile` scope, and a token from `claude setup-token` carries `user:inference`
alone (the Claude Code 2.1.317 binary: *"env-var and setup-token sessions default to
user:inference only"*). Measured 2026-11-06 on a session started with an
environment token: the dialog drew the Session block and nothing else - which
`parse_usage.py` reads, correctly, as `inconclusive`, on every sweep, for ever.

**The same session's status line does carry its usage.** Claude Code hands the
status-line command `rate_limits.five_hour` and `rate_limits.seven_day`
(`used_percentage`, `resets_at`), taken from the response headers of the session's
own model requests, with no scope check (the same binary; not yet seen on a live
setup-token session - the first sweep of a token agent is that measurement).
`usage_statusline.py` is that command: it keeps the last reading of each window in
`<config dir>/fleet-usage.json`. A token agent's Claude settings,
`<config dir>/settings.json`, carry:

```
{ "statusLine": { "type": "command", "command": "<fleet>/.claude/skills/agent-health/usage_statusline.py" } }
```

(`<fleet>` is the fleet checkout; the agent's own status line, when it has one, is
replaced - this one prints `5h NN% | 7d NN%`.) Then the reading is:

```
"${CLAUDE_SKILL_DIR}/parse_usage.py" --rate-limits <config_dir from --facts> \
    --agent <agent> --account <the account from step 3> \
    --ledger <the usage ledger, CONTEXT.md> --append
```

It yields the same two limits a capture does - `Current session` (short) and
`Current week (all models)` (long), resets in the screen's own shape - so step 5
reads both routes alike. No dialog is opened, nothing is typed, and the input line
does not matter. **A missing snapshot is `inconclusive`, never `ok`**: the status
line is not configured, or the session has had no answer from the API since it
started. A window whose reset has passed reads 0% (the agent has taken no turn since,
or the snapshot would be newer; one account is live in one session, so nothing else
spent it).

### 5. Read the verdict, and refuse to guess

```
"${CLAUDE_SKILL_DIR}/parse_usage.py" <the captured file> \
    --agent <agent> --account <the account from step 3> \
    --ledger <the usage ledger, CONTEXT.md> --append
# exit 0 = ok, 1 = trigger, 3 = inconclusive,
#      4 = floor-only, 2 = instrument fault
```

**`--agent`, `--account` and `--ledger` are required together** and the script
refuses without any one of them, each for the same reason: a missing one
silently turns every window into a `first-reading`, for ever, at exit 0.

`--append` writes this reading into the ledger as it goes, which is what makes
the NEXT sweep able to compute a velocity at all. Each limit comes back with
its `velocity_pct_per_hour`, its `projected_depletion` and a `decision` - one
of `first-reading`, `ok`, `watch`, `hold-reset-first`, `switch-projection`,
`switch-floor`. `verdict` is `trigger` when any decision is a `switch`.

**`watch` is not `ok` and it is not a trigger either.** It is the first of
the two consecutive checks: record it, do nothing, and let the next cycle
decide. A later reading that produces no projection carries it forward rather
than clearing it. **`floor-only` is its own verdict and its own exit code
(4)**, never `ok`/0: it means the floor was applied and the projection was not.

**`inconclusive` covers three things, not one**, and two of them arrive
looking like an ordinary sweep: no limit parsed at all; a limit with NO NAME
above it (the capture is cut at the top, which is what `capture-pane` returns
when the dialog is taller than the pane); and **a window the previous sweep
recorded and this capture does not** - one wrapped `NN% used` line drops a
window, and the one that vanishes may be the one sitting on a `watch`. A limit
Claude Code genuinely retires lands here too and stays inconclusive until a
person looks: only a person can tell a product change from a half-drawn pane.

**`inconclusive` is not `ok`.** It means no limit was found on the capture,
which is what a send-keys that never landed, a half-drawn pane, a wrong pane and
a renamed screen all look like - and the comfortable reading of every one of
them is "nothing is wrong". Re-capture once; if it is still inconclusive, read
the pane by hand and report it. **Issue no verdict about that agent** and never
coerce the state to a boolean. The parser's header and
`fixtures/status-screen.txt` carry the whole argument.

On `trigger`, note WHICH limit triggered it, on which rule, and its reset time
- all of it goes in the report - and continue to step 6. **The handover
instruction goes out on this same sweep**: a decision recorded now and acted on
next cycle is taken a whole cadence late, which is most of the margin the
projection just bought.

**Exit 2 pronounces on nothing.** The ledger path is wrong, or `--agent` is
missing, or the capture could not be read. Fix the instrument and re-run; do
not fall back to running without the ledger and reporting what comes back, which
is a floor-only reading wearing a full one's clothes.

### 6. Tell the agent to stop and hand over - VERBATIM

**Send this as ONE line.** A newline inside a `send-keys -l` submits the
message where the newline is, so a multi-line instruction reaches the agent as
several truncated prompts, the first of which says "stop everything" with no
instruction after it.

Substitute the handover path (`CONTEXT.md` says where these go) for `<path>`:

> STOP EVERYTHING NOW - account handover. Your session is about to be signed into a different account, so: (1) stop every monitor you have armed - your daemon followers included, but NOT the daemon services (agent-sched@ and agent-slack-watch@ keep running and their lines queue in the logs for after the hold; never stop or disable them) - and every piece of work in flight, including your whole subagent tree - tell each running subagent to stop where it is and report back, and start nothing new; (2) wait for a confirmation from EVERY subagent that it has stopped; (3) write a handover package to <path> covering the full current state - what you were doing and why, every subagent and exactly what it was doing and how far it got, what is committed and pushed versus what exists only in a worktree, every branch and worktree you own, every monitor and scheduled task that will need re-arming (the two followers always do), and anything you owe a person; (4) print exactly one line, HANDOVER-READY <path>, and nothing after it, ONLY once every subagent has confirmed it is stopped and the package is written; (5) you are ON HOLD from this moment until the switch is done and the hold is explicitly released - take NO new task from any surface meanwhile, not a Slack message, not a scheduled fire, not a person in session: acknowledge it in one line if a person is waiting, note it under 'owed' in the package, and start nothing. Do nothing else until you are told to continue.

### 7. Wait for the sentinel

The agent signals readiness with one line in its pane:

```
HANDOVER-READY <path>
```

Poll the pane capture for it. **Bound the wait: 30 minutes.** Stopping a
subagent tree cleanly takes minutes, not seconds, and a tree with a long
running command in it takes longer.

**The hold is part of the instruction, and it outlives the sentinel.** Between
`HANDOVER-READY` and step 10 the agent is idle at a ready prompt, its followers
stopped while its watcher and scheduler services keep running, so a Slack message
or a due task lands in a log and waits there. A follower re-armed early, or any
other surface - a person in session - would otherwise start a fresh tree on the
account that is about to be switched out from under it. Clause (5) is what keeps the gap empty; step 10's first words
are what end it. An agent that took something up in between has broken the
hold - note it in the ledger row's `Outcome`.

**If the sentinel never comes, do NOT switch the account anyway.** Switching
mid-turn is the thing this whole procedure exists to avoid: it is the cap,
arriving on purpose. Instead capture the pane, report the agent and what it is
still holding to whoever the charter says, and leave it running. An agent that
reaches its cap having been asked to stop is no worse off than one that reaches
it having been asked nothing, and an agent whose tree you killed by hand is.

**The sentinel is the agent's own claim, not a measurement.** It says the
subagents confirmed. It is still the only signal available, so take it - but
say so in the report rather than reporting the tree as verified stopped.

### 8. Wait five more minutes

A subagent that has said it stopped can still have a tool call in flight, and a
write that lands after the switch lands into a session that is no longer there.
Five minutes after the sentinel, not five minutes after the instruction.

### 9. Switch the account through `/agent-revive`

Load `/agent-revive` and follow it. Do not restate it or work from memory. The
parts that decide this case:

- **The target is the pool pick**: the account `tmux_triage.sh <agent>
  --accounts` marks `next`, which is `pool_pick.py`'s answer (in this skill,
  `/agent-revive` step 5 owns the rule). Its prediction for each account is
  read off the usage ledger these sweeps write - the latest weekly reading of
  that account, a passed reset predicting 0% - so every reading step 5 appends
  is also an input to the next handover's choice. An `--accounts` that exits
  1 names no target and says why: the leases disagree with the session (an
  escalation, never a hand edit) or the pool is exhausted.
- **On the switch, release and re-take the lease in one write**, once the new
  sign-in has succeeded:
  `python3 "${CLAUDE_SKILL_DIR}/pool_pick.py" --take <new account> --agent <agent> --why "<the limit, its rule and its reset>"`.
  It releases the lease on the old account and leases the new one under one
  lock, atomically, so the lease file never shows the agent on two accounts or
  on none, and writes the handover ledger's row in the same act. Its JSON names
  what it released and what it took.
- **A login agent's route is /login, typed at the ready prompt.** Never a Ctrl-C
  and never an Escape into a capped session. And the agent here is NOT capped
  yet, which is the entire advantage of doing this early.
- **Option 1 at the auth-method menu, selected by a bare Enter.** Option 2 is
  the metered API path and bills per token for as long as the agent runs.
- **A protected Mac agent is token-only** (its session a LaunchDaemon:
  `/agent-revive`'s `--facts` names `unit_scope` system under launchd). It has no
  window server and no login Keychain, so its switch is the token route below and
  never /login; a unit of one set to `login` is auth `unknown` and is reported, not
  switched.
- **Restarting a login agent's unit (systemctl, or launchctl on macOS) is
  forbidden as a way to switch an account.** It drops the session context and kills the subagent tree, which is
  what the handover was protecting.
- **A token agent's route is its unit's restart, and only that**:
  `python3 "${CLAUDE_SKILL_DIR}/../agent-revive/token_switch.py" <agent> --to <next> --package <path> --why "<the limit, its rule and its reset>"`.
  It installs the account's token, takes the lease with its ledger row, and
  restarts that agent's unit (`/agent-revive` step 5, "Switching a token agent").
  /login in such a session changes nothing (`/agent-revive` step 2). The package
  is why the restart is safe: the tree is already stopped and written down.
- **A shared account's trigger hands over the WHOLE GROUP.** The pick for any
  holder carries `group_plan`, `{holder: {to, share}}`: one free account per
  holder while they last, the rest sharing the last one, and with none free,
  every holder onto the best account another agent holds. Every holder gets
  steps 6 to 8 and its own switch to its `to`, taken with
  `--take <to> --agent <holder> --share` where `share` is true. A group left
  half-moved is two accounts draining for one group's work.
- **With a pool there is always a target unless the pool is exhausted** -
  every account current, leased, excluded or predicted at 80%+ weekly. Then
  there is nothing to switch to: report it with the soonest reset the picker's
  notes show (`/agent-revive` step 5, case 1).

### 10. Put the agent back to work - VERBATIM

One line again, same `<path>`:

> Account handover complete and the hold is released - you are signed on a different account and your session and its work are intact. Re-arm every monitor and scheduled task you stopped, your two daemon followers first (they deliver what queued in the logs during the hold), read your handover package at <path>, continue from where it says you left off, and then take up whatever arrived while you were on hold, in the order it arrived.

**This is the "session survived" nudge, not a bootstrap prompt.** The point
of the in-session switch is that the context lives through it;
`/agent-revive` step 11's bootstrap prompt would tell the agent to start its day
over and throw the handover away.

**A token agent was restarted, so it gets this line instead**, once its unit's
boot message has run (the pane shows the session working on it, or back at a ready
prompt):

> Account handover complete and the hold is released - your session was restarted on a different account's token, and your conversation was resumed but every subagent and monitor it had is gone. Re-arm your two daemon followers and every monitor and scheduled task the package lists, read your handover package at <path>, restart from it whatever was in flight, continue from where it says you left off, and then take up whatever arrived while you were on hold, in the order it arrived.

### 11. Confirm it is actually working

`tmux_triage.sh <agent>` should report `working`, not merely `healthy`. A ready
prompt is not a working agent. If it is idle, send `keep going`, which is safe
to repeat. A token agent's restart takes minutes (its unit's pre-sleep and
readiness wait): re-triage every 30 seconds for up to 6 minutes before reading
anything into an `unreachable`.

The handover ledger already holds the lease change - `--take` wrote the row, with
the agent, the old and the new account, the `--why` and what it released and took
- so a lease change can never lack one. Record how it ended with one more row:

```
python3 "${CLAUDE_SKILL_DIR}/pool_pick.py" --record --agent <agent> --account <new account> \
    --why "handover outcome" --outcome "<working or not; package read or not; anything taken up during the hold>"
```

---

## Traps

- **`$TMUX` beats `$TMUX_TMPDIR`.** A `tmux` call made from inside another
  session reads THAT session's server, so every call here is prefixed
  `env -u TMUX`. Without it a sweep reads its own pane and reports on itself.
- **Never send keys into a pane you have not just read** - and read the INPUT
  LINE, not only the triage state. Text already sitting unsubmitted in the input
  is appended to, not replaced, so /usage becomes `<their text>/usage` and
  Enter submits it as a prompt. Skip that agent and re-check it in 5 minutes;
  do not clear their line. A `working` state is NOT a reason to skip: the
  dialog is client-local and never reaches the model.
- **Dim text in the input box is the placeholder, not input.** An empty
  Claude Code input draws a suggestion (`keep going`, `Continue from where you
  left off.`) that a colorless capture cannot tell from typed text. Read the
  line with `capture-pane -e` and drop the `ESC[2m` spans first (step 2);
  otherwise the sweep skips every idle agent and calls it caution.
- **An 80x24 window cuts the dialog, and a cut capture is `inconclusive`
  in both of its shapes.** Every detached window is 80x24 after a restart. Read
  `#{window_height}` and `resize-window` before the send (step 4), attached
  client or not; a resize sends no key. **Set `window-size latest` back
  immediately after the reading, every time, and never leave a window on
  `manual`**: a resize pins the size as manual, which clips and dot-fills the
  terminal of anyone attached now or later until it is set back.
- **Escape closes the dialog; Ctrl-C does not.** On a capped pane Ctrl-C (and
  Escape at the capped prompt itself) cancels the session's automatic continue
  at the reset time, and that has no undo. A pane that is already `usage-cap` is
  a revival, not a sweep: hand it to `/agent-revive` untouched.
- **A bare Enter can kill a session.** A first-run trust-folder dialog
  preselects *"No, exit"* - measured, it is the default. Triage before sending
  Enter into anything you did not open yourself.
- **Option 1 only at the auth-method menu.** Option 2 bills per token against
  the budget on every turn, for as long as the agent runs, and nothing on screen
  ever says so.
- **`inconclusive` is not `ok`.** A capture with no limits on it is the
  instrument failing to reach the subject, and it wears the costume of a healthy
  agent. Re-capture, then report; issue no verdict. It also appends NOTHING:
  a row invented from a capture that read no limits becomes the baseline the
  next velocity is computed against.
- **A MISSING LEDGER IS EXIT 2, AND EXIT 2 IS NOT A VERDICT.** A mistyped
  `--ledger` path would otherwise read as an agent with no history - every
  window `first-reading`, every sweep recorded, nothing ever acted on, forever.
  A missing `--account` is the identical failure, so it is refused the same way.
  Fix the instrument; do not re-run without the ledger and report the result as
  a sweep.
- **EXIT 2 IS ALSO EVERY UNEXPECTED EXCEPTION, AND THAT MATTERS BECAUSE EXIT
  1 MEANS HAND THIS AGENT OVER.** A crash - a `--ledger` naming a directory,
  an `--init` into a missing directory, one bad byte in the ledger - exits 2,
  never 1, so an instrument that has fallen over never issues the loudest verdict
  the script has.
- **A LEDGER ROW THE PARSER CANNOT READ IS EXIT 2, NOT A SKIPPED ROW.**
  Skipping it makes an OLDER row the velocity baseline, which downgrades a
  `switch` to a `watch` with nothing red anywhere. Nothing but `parse_usage.py`
  writes that file, so an unreadable row means somebody edited it by hand.
- **TWO READINGS LESS THAN FIVE MINUTES APART GET NO SLOPE.** The ledger
  stamps to the minute while the clock does not, so a thirty-second gap turns
  one percentage point into 120 %/h - enough to project depletion inside the
  horizon on an idle agent, twice, and switch it. A session-start sweep
  followed by the scheduled one is exactly that gap.
- **`watch` is one check, not a decision.** The switch needs the projection
  to land inside the horizon on two consecutive checks. Acting on the first one
  hands over an agent whose slope came from a single burst of work.
- **A window that resets before it would deplete is left alone.** The cap
  never lands; the handover costs the stop-and-resume and buys nothing.
- **Velocity is per window AND per account.** Across two windows it is a
  plausible-looking number that means nothing; across a handover it is
  arithmetic over two different counters. `parse_usage.py` records a first
  reading rather than computing either, which is why the `--account` argument
  is not optional in practice.
- **One line per message.** A newline in a `send-keys -l` submits the prompt
  at the newline, and the handover instruction is exactly the message you cannot
  afford to have truncated.
- **Do not switch an account on a missing sentinel.** The switch without a
  clean stop IS the cap, delivered deliberately. Report and leave it running.
- **There is no limit called "daily".** Classify the window by the shape of
  its `Resets` line, not by its name.
- **A TOKEN AGENT'S /usage IS EMPTY BY DESIGN, NOT A CUT CAPTURE.** Re-capturing
  it is `inconclusive` for ever. Read its snapshot (`--rate-limits`, step 4); a
  missing snapshot is a status line nobody configured, reported as such.
- **A TOKEN AGENT IS NEVER SENT /login.** Not to switch it, not to revive it:
  its session keeps its environment's token over any sign-in. It switches by
  `token_switch.py` after the handover, and a dead token is reported
  (`/agent-revive` case 15).
- **Read `auth` before the first keystroke** (`--facts`, step 1). An unreadable
  unit is `unknown`, and unknown is no verdict and no switch.
- **A SHARED ACCOUNT IS READ ONCE, UNDER ITS OWN SECTION.** Read every holder and
  the account's usage lands twice per sweep; read it under the reader's own name
  and the next sweep, read by another holder, finds no baseline. `--shares --json`
  says who reads and where (step 1).
