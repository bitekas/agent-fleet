---
name: slack-communication
version: 3
description: >
  Slack MECHANICS for an agent fleet, the fleet's working chat transport: the
  inbound watcher (running it, arming its follower, what its lines mean, the
  follower's default filter), the Slack side of the claim that decides which
  ONE agent acts on a request several agents could pick up, and the outbound
  Web API recipes for posting, threading, formatting, reactions, DMs, file
  upload, message fetch and permalinks, plus the traps each of them carries.
  Universal: no workspace, person or repo path is named here; the
  concrete values live in the install's `CONTEXT.md` and `config.json` for this
  skill. Load before posting to Slack, acting on a Slack request, arming the
  watcher, fetching a message, or changing anything about the Slack
  integration. Mechanics only, no policy: WHO may ask for what, whose approval
  a change needs, voice and tone, and how traffic is triaged live in the owning
  agent's charter, which `CONTEXT.md` names.
requires_install: true
---

# Slack mechanics

How an agent fleet talks to Slack: the inbound watcher and the outbound API
calls. Slack is a chat transport: this skill implements the `/chat-transport`
interface, `transport.json` beside this file is its descriptor, and the claim
that settles which agent acts on a request is `/chat-transport`'s helper.

**This file is universal.** It names no workspace, channel, person, bot or repo
path. The companion files carry all of that:

| File | What it holds | Per company? |
|---|---|---|
| `SKILL.md` (this) | Slack platform mechanics, recipes, traps | universal |
| `transport.json` | the transport descriptor: id shapes, the watcher's job and config variable, the follower's default filter | universal |
| `CONTEXT.md` | workspace/bot IDs, channels, people, key path, the owning agent | **yes** |
| `config.json` | the machine-readable subset `watch.py` reads; `sched.py` (`/scheduled-tasks`) reads its `known_users` as the requester directory when an install points it here | **yes** |
| `config.example.json` | every key `config.json` must carry, with placeholder values | universal |
| `installation/` | how to install this skill, and `check` to prove it is installed and current | universal |

`CONTEXT.md` and `config.json` live in the install, never beside this file:
`fleet where slack-communication` prints that directory, and a watcher service
names its own config in `SLACK_WATCH_CONFIG`. So: **every concrete value below
is a placeholder - look it up in `CONTEXT.md`.**

**This file also contains no policy.** Whether a message should be sent, who is
allowed to ask for what, what tone to use, and how a request is triaged are the
owning agent's judgement and live in its charter, which `CONTEXT.md` names. The
claim (*Claiming a request*) is the one coordination mechanism every agent
shares: it settles WHICH agent acts on a request, never WHETHER an agent may -
that stays the charter's - and its takeover precondition is part of the
mechanism.
Typically **one agent owns the surface** - it alone arms the watcher and posts,
while other agents load this skill read-only to understand the surface, resolve
an ID, or read a recipe. `CONTEXT.md` says which agent that is.

## Setting up a workspace

What a fleet needs before any of this works:

1. **A Slack app with a bot user**, installed to the workspace.
2. **Scopes.** The watcher needs `channels:read` + `channels:history` (public),
   `groups:read` + `groups:history` (private channels), `im:read` +
   `im:history` (DMs). Posting needs `chat:write`; reactions
   `reactions:write`; uploads `files:write` (+ `files:read` to fetch).
   `users.profile:read` helps with lookups.
3. **Your personal Slack key**, on disk in a file, mode 600. `config.json`
   points at that file by path and never holds the key itself, so a config that
   leaks is embarrassing rather than exploitable. **The key is personal: it is
   held by the agent that owns this surface, never committed, never shared
   between agents, and never pasted into any file in this skill.**
4. **`channels:join` is deliberately NOT required.** Without it the bot cannot
   add itself anywhere, so **/invite by a human is the subscription
   mechanism** and /kick unsubscribes. That is a feature: channel access is
   granted by the workspace, not taken by the agent.

`CONTEXT.md` records which scopes a given install actually has, and when each was
verified. **Read the live list, not a document, when a capability is in doubt:**

```bash
curl -sS -D- -o /dev/null https://slack.com/api/auth.test \
  -H "Authorization: Bearer $TOKEN"    # read the x-oauth-scopes response header
```

## Transport

**All agent posts go through the bot** via the Slack Web API (`chat.postMessage`
etc. with `Authorization: Bearer <token>`; plain curl, no SDK).

```bash
TOKEN=$(cat <the personal Slack key file - path in CONTEXT.md>)
curl -sS -X POST https://slack.com/api/chat.postMessage \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-type: application/json; charset=utf-8' \
  --data @- <<'JSON'
{"channel":"<channel id>","text":"*Heads up* - the thing shipped."}
JSON
```

**Always read the JSON response: Slack returns HTTP 200 with
`{"ok":false,"error":"..."}` on failure, so a zero exit status proves nothing.**

**Do NOT add `username`, `icon_emoji` or `icon_url` to that call, and this is
not cosmetic advice.** Measured: any of the three makes Slack emit the message
with `subtype: "bot_message"` and **no `user` field at all** - and such a message
is undeliverable, because there is no UID to put on the emit line and nothing for
a charter to authorize. A per-message display override would therefore make this
fleet's agents invisible to each other, with nothing failing and nothing to read.
The plain call above yields `user` = the bot's own user id, `bot_id` set, no
subtype: the shape the watcher delivers.

If the fleet also has a personal Slack connector (e.g. claude.ai's), **never
post through it** - it acts as the human's own account. A connector stays
legitimate for *reading* things the bot cannot reach (channels it isn't in, user
lookups).

## The live watcher (how Slack reaches the agent)

**`watch.py`, beside this file** (its module docstring is the canonical usage
doc; **`watch.test.py`** beside it is the offline regression guard, and the
config `SLACK_WATCH_CONFIG` names holds everything workspace-specific) polls
**every public OR private channel the bot is a member of, plus every open DM**,
every `poll.poll_secs` seconds (default 5; env override
`SLACK_WATCH_POLL_SECS`) and prints one line per new
**deliverable** message - top-level and thread replies. A reply in a thread
whose parent has scrolled off the poll's 50-message page is read by a slower
**sweep** instead (every 300 s, env `SLACK_WATCH_SWEEP_SECS`) - see *Threads off
the page, and the sweep*. Deliverable is every
message except this bot's own and anything carrying a subtype.

Line formats:

- channels (public and private alike): `SLACK #<channel-name> ... Name (UID): text`
- DMs: `SLACK DM ... Name (UID): text`
- from a bot, either kind: `... Name [bot] (UID): text`

**It runs as a supervised service that restarts it, and the session arms a
FOLLOWER of its output under a persistent Monitor**; each line the follower
prints wakes the session. That is the entire inbound mechanism (one poll
interval of latency, no public endpoint). A Monitor lives a bounded time and the harness ends it, so a
watcher that is a Monitor's child is deaf from that moment until the session
re-arms it; a service is not. The follower reads the service's log from a saved
position, so a line written while no Monitor was armed arrives on the next arm.
The fleet's daemon manager renders the service from `transport.json`
(`watch.job`, `watch.config_env`) and runs the follower:
`python3 <fleet>/systemd/agent-daemons.py follow <agent> slack-watch`.
`CONTEXT.md` names the install's units and log. **That log is written only by its
service: never edit it in place (`sed -i` or any rewrite), move, truncate or delete
it; read it, or copy it** - the service opens it once, at start, so a rewrite leaves
the watcher writing to the old file while the follower reads one that never grows.

**No pipe after the follower.** Piping a line source through a filter
(`... 2>&1 | grep --line-buffered -v "<noisy line>"`) holds the NEWEST message
back until the next one arrives: the source writes the line and moves on, and
the session never sees it, so a message reads as lost and then surfaces late as
the following one lands (measured 2026-10-13, on a thread @-mention). Filtering
goes through the follower's own include/exclude options, which apply before the
line is printed and flushed. A `WATCH-INFO retired ...` line prints once per
watcher process start, never per poll.

### The follower's default filter

`watch.follow_include` in `transport.json` is the `--include` the follower
applies when it is armed with none: the one statement of which watcher lines
wake a session. Why each clause is there:

- `^SLACK ` - every delivered message.
- `^DAEMON-` - the follower's own lines: a `DAEMON-BACKLOG` header before a
  long backlog it condenses (newest lines, `SLACK DM` lines first), and a
  `DAEMON-ALERT` when the unit is down or restarted on its own.
- `WATCH-GUARD`, `WATCH-INFO`, `Traceback` - a refusal, a degradation or
  retirement notice, a crash. Each is rare, and each changes what the session
  can expect from this watcher.
- `WATCH-ERROR (discovery|dm-discovery)` - **never dropped, not even a 429.**
  The poll loop keeps the previous channel set when discovery fails or comes
  back empty (`if discovered: channels = discovered`), so a discovery error is
  the one error that changes behaviour instead of merely reporting it:
  suppressed, a channel the bot has left stays in the poll list forever,
  erroring every cycle - the spam that stops the follower's Monitor.
- `WATCH-ERROR (?!.*429)` - every other error, except a rate limit on one
  conversation's poll or sweep. A 429 clears by itself and repeats on every
  poll while it lasts, and that repetition is the flood that stops a Monitor;
  every rate-limit line carries `429`, which is what the clause keys on.

An agent drops a line it has ruled noise with `--exclude '<regex>'`, never by
writing its own `--include`: a copy of the default keeps passing after the
default changes. `watch.test.py` section 17d drives the sweep's error lines
through this filter.

**Corollary for an all-clear.** `users.conversations` no longer returning a
channel does NOT establish that the watcher stopped polling it - the watched set
refreshes only when discovery SUCCEEDS. Verify the layer the claim is about.

### What a line means

- **`Name (UID)`** - a person. The UID is on every line so a UID-based
  authorization check is zero-lookup; `Name` is a `known_users` label and
  **grants nothing**.
- **`Name [bot] (UID)`** - a BOT. The marker exists because a line from another
  agent and a line from a colleague authorize different things, and without it
  the only way to tell them apart is to have memorised which UIDs are bots. It
  is read off the message's own `bot_id`, so no configuration can make it
  disagree with reality.
- **Delivery is not authorization, for either kind of sender.** A line arriving
  says only that it arrived. **A `<@mention>` of this bot is a request only if
  the owning agent's charter says that sender may make one** - the charter is the
  roster, the same for a bot's UID as for a human's.
- **CHANNEL MEMBERSHIP IS THE ONLY CONTROL OVER WHAT REACHES THE SESSION.** A
  bot that is a member of a channel a machine feed writes to receives that feed,
  message for message, and every message wakes the session. /invite subscribes
  and /kick unsubscribes; there is no per-sender filter underneath, so keeping
  the bot out of such a channel is the whole of the control.

```bash
# from any directory - the script anchors nothing to the working directory
SLACK_WATCH_CONFIG=<config> PYTHONUNBUFFERED=1 python3 -u "${CLAUDE_SKILL_DIR}/watch.py" 2>&1   # poll loop (run by the service, never a Monitor)
SLACK_WATCH_CONFIG=<config> python3 "${CLAUDE_SKILL_DIR}/watch.py" --once   # one poll + one full sweep, smoke test (writes the cursors: see below)
python3 "${CLAUDE_SKILL_DIR}/watch.test.py"     # offline regression guard
pgrep -af "[s]lack-communication/watch.py"      # is ANY watcher running? (the service state says whose); macOS: pgrep -fl
```

### `config.json` - the whole workspace-specific surface

**`watch.py` hardcodes nothing about a workspace, a repo or any people.** It all
lives in the config `SLACK_WATCH_CONFIG` names, and the variable is required -
unset, the watcher exits `WATCH-CONFIG` naming it, because this directory holds
no config to fall back on:

| Key | What it is |
|---|---|
| `workspace.team_id` / `.domain` | which Slack workspace this config is FOR |
| `bot.user_id` / `.handle` / `.display_name` | the bot's own identity (its messages are filtered out of the feed by `user_id`) |
| `token.path` | where the personal Slack key file lives; `${VAR:-default}`, `$VAR` and a leading `~` are expanded |
| `owner.claude_config_dir` | the ONLY `CLAUDE_CONFIG_DIR` allowed to run the watcher's daemon form (`--once` does not check it) |
| `state.prefix` | prefix for the cursor files and the single-instance lock |
| `poll.*` | poll / sweep / rediscovery / baseline-window tunables (optional; env vars still win) |
| `slack.api_base` | API host (optional) |
| `known_users` | UID -> display label for the emit lines |

Required keys are **fatal when absent**, naming the missing key - a watcher that
silently defaulted an identity value would poll the wrong workspace or answer to
the wrong owner, and both fail looking like "Slack is quiet". Only `poll.*` and
`slack.*` carry defaults. JSON has no comments, so the file documents itself with
`_comment` keys, which the loader strips.

**The delivery rule, in full: every message is delivered except this bot's own
and anything carrying a subtype.** `bot_id` is not consulted, so another bot's
message arrives exactly as a human's does, and there is no key anywhere that
changes that. Every post a bot makes through `chat.postMessage` carries `bot_id`
with `user` set to that bot's own user id and no subtype, so a predicate that
dropped `bot_id` traffic would make two fleet agents **invisible to each other**,
direct `<@uid>` mentions in a shared channel included - silently, because nothing
errors and an undelivered message is indistinguishable from one never sent. Give
every bot you correspond with a `known_users` label, so its lines read as a name.

**The one consequence to hold in mind: a bot that is a member of a channel a
machine feed writes to receives that feed.** A product bot posting one message
per completed job wakes the session on every one, and channel membership is the
only thing that decides it - /invite subscribes and /kick unsubscribes.

**A TWO-NODE LOOP IS BOUNDED BY CHARTER JUDGEMENT, NOT BY CODE.** The
predicate refuses this bot's own id, so a one-node echo is unrepresentable;
nothing bounds A->B->A. Every post wakes the other agent's session, thread replies
included, with no cooldown, no depth counter and no "don't wake on a reply to my
own message" rule. What bounds it is each agent's own judgement about when NOT to
answer, which lives in its charter - so **each charter says what the other agent
may ask it for and when it stays silent**. Two agents with no such rule are a
ping-pong waiting for a topic, and at these poll rates a busy loop is also how a
watcher hits its rate limit and goes deaf.

**`workspace.team_id` is enforced, not decorative:** at startup the watcher calls
`auth.test` and refuses to poll if the token belongs to a different team. Nothing
otherwise keeps the config and the token file in step, and the mismatch is silent
- every ID in the config (bot user, known-user labels, the charter's
authorization table keyed to them) would belong to the other workspace, surfacing
as strangers posting under familiar names.

**Running a second watcher is a config edit, no code change.** Two cases:

- **Another AGENT in the SAME workspace**, the common one in a fleet. It has its
  own bot identity, its own token (hence its own rate-limit bucket), its own
  `owner.claude_config_dir` and its own `state.prefix`, and its watcher is that
  agent's own unit: `/adding-an-agent` section 4.3 step 5 writes its config, and
  its section 5 enables the unit. Nothing has to be configured for the two to
  see each other.
- **Another WORKSPACE** for the same agent: a second config beside the first,
  with that workspace's ids, its token's path and a `state.prefix` of its own.

```bash
install -m 600 <this watcher's config> <other-workspace config>   # then edit ids, token.path, state.prefix
SLACK_WATCH_CONFIG=<other-workspace config> python3 "${CLAUDE_SKILL_DIR}/watch.py"
```

Give every additional watcher its **own `state.prefix`** - that is what keeps two
watchers' cursors and single-instance locks independent so they can run side by
side. Two watchers sharing a prefix and directory contend for one lock and one
set of cursors: one exits `WATCH-GUARD`, and whichever polls first consumes the
other's messages. `watch.test.py` section 11 pins all of this, including the retarget end-to-end.

**Ownership is self-enforced by the script** - a config-dir guard admits only
`owner.claude_config_dir`, and an flock rejects a second concurrent watcher - so
an agent starting it "wrongly" is harmless (the process exits 0 with a
`WATCH-GUARD` note; a service manager does not retry that exit, so the service
stays down with the line in its log). **Both checks are the daemon form's.**
`--once` is the smoke test made to run beside the live watcher, so it checks
neither the owner nor the lock: run by anyone against the live config, it
consumes the owner's lines (see *`--once` writes the cursor files* below).
*When* the follower must be armed is a standing duty in the charter.

### Discovery

- **Channels (public + private):** the watched set is discovered at runtime via
  one `users.conversations` call with `types=public_channel,private_channel` and
  re-discovered every ~60s inside the poll loop, so **/invite is the
  subscription mechanism** (the bot has no `channels:join` scope and can't add
  itself; /kick unsubscribes) and a mid-run invite to either a public OR a
  private channel is picked up without a restart. Private channels emit
  identically to public ones - they still have a name and route through the same
  poll/first-sight/invite-race path. Private discovery needs
  `groups:read`/`groups:history`; if that scope is ever lost the combined call
  logs ONE `WATCH-INFO` line and degrades to public-only (public channels never
  lost), re-probing combined types each cycle so private channels return
  automatically. Discovery owns the watched set outright - **nothing is seeded**.
  On a discovery failure the watcher keeps polling the last known set (never
  crashes); if the very FIRST discovery of a process fails or comes back empty,
  the set is empty until the next ~60s cycle re-probes. The per-conversation
  cursors below persist on disk, so the first poll that does see a channel emits
  what arrived during the gap, back as far as the 7-day window - see THE WINDOW
  BOUND under State below. A gap shorter than the window costs delay; a longer
  one costs the top-level messages older than the window, announced by one
  `WATCH-INFO` line.
- **DMs:** a second `users.conversations` call with `types=im` (same ~60s
  cadence) discovers every open DM with the bot, so DMs are watched with no
  per-user setup - just message the bot. Requires `im:read`/`im:history`; if
  they're ever absent the probe logs ONE `WATCH-INFO` line, falls back to
  channels-only, and re-probes each cycle so DMs light up automatically once the
  scopes return (no restart).

### State and replay guards

Last-seen cursors live one file per conversation at
`<state.dir>/<state.prefix>-<channel_id>.json` - machine-local, surviving
session restarts, preventing replay. `state.dir` is where they go; absent **or
empty**, they fall back to the XDG cache directory (`$XDG_CACHE_HOME`, itself
absent-or-empty to `~/.cache`). It is expanded exactly as `token.path` is
(`${VAR:-default}`, `$VAR`, a leading `~`), so a relative value cannot be
produced by an unexpanded `${...}` - which would put every cursor and the lock
in the watcher's working directory.

**The prefix is live on-disk STATE, not a name:**
changing it orphans every cursor (each conversation re-baselines to "now",
dropping any backlog) and lets an old-prefix and a new-prefix watcher hold
different locks and both run, double-emitting. Change it only alongside a
migration that renames the existing files first. (Two *different* workspaces
should use two different prefixes - that is what keeps them independent.)

- A **channel** seen for the first time (no state file) checks a short recent
  window for the bot's own `channel_join` marker: if the bot was just invited,
  the cursor is set to the join ts and deliverable messages posted after it are
  emitted - so a message sent between the /invite and the first ~60s discovery
  poll is **not** swallowed (the invite-race guard, `initial_baseline()`).
- If no recent join is found (returning session, old membership) it baselines to
  "now" and emits nothing historical (the replay guard).
- A first-seen **DM** has no `channel_join` marker, so it baselines to "now"
  minus a short window (`DM_BASELINE_WINDOW_SECS`, 90s) - the opening message
  that made the DM discoverable isn't swallowed by discovery lag, but months-old
  DM history is never replayed.
- The baseline applied **at first sight** is stored with the cursor and is from
  then on the floor under **every** cursor in the conversation: no message with
  a ts earlier than it is ever emitted - thread replies included, even in a
  thread whose parent predates the baseline - while a reply posted after it is
  emitted whatever the age of its parent.
  A state file with no stored baseline is never migrated; it falls back to the
  channel cursor already on disk.

Because the cursors survive, watcher downtime is self-healing: messages sent
while it was down surface on the first poll after it is back, so no "I'm back"
announcement post is needed.

#### Threads off the page, and the sweep

This is the one statement of these rules; `watch.py` points here. A poll reads
the newest 50 top-level messages of a conversation, and a thread reply is found
only through its parent's `latest_reply` - so a parent with more newer posts
above it than that page holds is **off the page**, and the poll cannot see its
thread at all, however recent the reply. Two mechanisms cover what the page
does not.

**The catch-up.** In **steady state** the page reaches the channel cursor and a
poll is **one** `conversations.history` call. When it does not (after
downtime), that poll catches up in one go and delivers **at most 200 top-level
lines** (`CATCHUP_LINES`) for the conversation: the **newest** 200, because
recency is what a returning agent needs. When older ones were skipped, **one**
`WATCH-INFO <conversation>: catch-up delivered the newest 200 top-level
messages; messages and thread replies posted from <cursor> to before <oldest
delivered> were not delivered - read them on demand with ... 'Fetch a message /
thread' recipe` line says so, the range in ISO UTC, printed before the lines it
precedes; nothing is counted, so the catch-up costs one call (the newest 201 -
the extra one is what tells a skip from a backlog of exactly 200, which prints
no line). The **sweep floor rises to the oldest delivered message** (and is
never lowered), so the replies under the skipped parents are bounded by the same
cap: a reply posted before that message is not delivered, one posted after it
is. The cursor ends at the newest message, so the next poll is steady state - no
re-read and no repeat of the line. The catch-up keeps the cursor's own message
too, so a parent whose replies call failed after the cursor reached it is read
again (delivery is gated on the cursor, so nothing repeats).
- **The window.** A catch-up never reaches further back than `WINDOW_SECS`
  (7 days). A cursor older than that costs the messages between, said in the
  same `WATCH-INFO` line; when nothing at all lies inside the window, the cursor
  moves to the newest message, so the line is printed once and not every poll.

**The sweep.** Every `poll.sweep_secs` (default **300 s**; env
`SLACK_WATCH_SWEEP_SECS`) each conversation starts a sweep, at a phase of its
own so they do not start together. It pages history from the poll's edge back to
the window start and calls `conversations.replies` only for a parent whose
`latest_reply` moved past its thread's cursor. That covers every thread whose
parent was posted inside the window, tracked or not - including one whose FIRST
reply came after its parent left the page, such as the bot answering an old post
and a human answering the bot, which has no cursor to track it by. A tracked
thread whose parent is older than the window but whose newest reply read is
inside it costs one replies call per sweep, because no history read lists a
parent that old. A conversation whose page holds its whole history costs the
sweep nothing; one whose page reaches back past the window start costs no
history pages, only those old-parent replies calls.

**What sweeps cost, and the budget.** All sweeps together make at most
`poll.sweep_budget` calls per poll (default **3**; env
`SLACK_WATCH_SWEEP_BUDGET`) - history pages and replies calls alike, one budget
shared by every conversation, so sweeps in progress at once cannot stack. A
sweep the budget stops resumes on the next poll where it stopped. Slack
rate-limits per method, per workspace, per app, so the bound to hold is:

    conversations.history calls/min <= (watched conversations + sweep_budget) x 60 / poll_secs

because every poll costs each conversation one call (its page) and the sweeps at
most the budget; a catch-up adds one call, once, however long the outage. A bot
in 29 conversations at a 40 s poll makes (29 + 3) x 1.5 = **48/min**, under
Tier 3's ~50/min; a budget of 4 would be
49.5, and one more conversation at that interval needs a longer poll. The
session's own `conversations.history` and `conversations.replies` calls (the
*Fetch a message / thread* recipe below) use the same bot token and spend the
same per-method budget, so the bound must leave headroom for them. The budget
is per POLL, so the bound tightens as the poll shortens: at the script's 5 s
default, (conversations + 3) x 12 <= 50 leaves room for a single conversation.
This bound is the one statement of how to size `sweep_secs`, `sweep_budget`
and the poll interval together.

**How late an off-page reply can be:** one sweep - `sweep_secs` to start, plus
the polls the sweep needs at the shared budget. A 25-page busy feed needs at
least 9 polls (about 4.5 minutes at a 30 s poll), more while other sweeps share
the budget.

**Errors.** A sweep error is **one** `WATCH-ERROR sweep <conversation> ...`
line. It never retires the conversation (a sweep runs only after a successful
poll of the same conversation) and never costs that poll, and the state is
saved either way. After a **rate limit** (HTTP 429 or `ratelimited`) the sweep
resumes from where it stopped on the next poll; after **anything else** the next
attempt is the next due sweep, so a fault that does not clear costs one line per
`sweep_secs`, never one per poll - a non-429 line every poll is the flood that
stops the follower's Monitor. A thread Slack says is gone (`thread_not_found`,
its parent deleted) does not stop the sweep, so it cannot hide the threads
after it. In the pass over threads whose parent is older than the window it is
**dropped from tracking** with one `WATCH-INFO ... thread <ts> is gone` line,
since nothing would ever list it again; a thread whose parent history still
lists **keeps its cursor** and is reported once per process, because forgetting
it would repeat the line every sweep and, on an answer that proved transient,
re-send replies already delivered. Any other error on a thread stops the sweep
like the rest. A 429 line carries `429` like
the per-conversation one, so the follower's filter drops it alike.

**Saving.** Every poll's state is saved, **a failed poll's included**: the
cursors move message by message, so a failed poll's state records exactly what
it delivered. A **SIGTERM** saves the state the same way and then ends the
process **by the signal**, so a restart mid-poll delivers nothing twice and the
service manager restarts the watcher: an exit 0 would read as a deliberate stop,
which is what the `WATCH-GUARD` refusals use.

**The sweep floor** (`sweep_floor_ts`, one per cursor file) is written by the
first poll of a watcher that sweeps, and at first sight it is the baseline
itself. No off-page read starts below it. It is what keeps the first sweep from
delivering, in one burst and days late, the replies a watcher that does not
sweep left unread in threads whose parent had already left the page; the cost
is that a reply posted in such a thread between that watcher's last poll and
the first sweeping poll is not delivered - a gap one restart wide. A watcher
that does not sweep keeps the key without moving it, so going back to one and
then forward again leaves the floor where it was, and the first sweep after the
return delivers the off-page replies posted in between, late. Deleting
`sweep_floor_ts` from the cursor files before that return makes the next poll
set it to "now" instead.

**`--once` writes the cursor files of the config it runs under**, so with the
live watcher's config every line it prints is one that watcher will not
deliver. Smoke-test against a copy of the config whose `state.dir` holds copies
of the cursor files.

**THE WINDOW BOUND, and it is the limit on every "nothing is lost" claim on
this page.** A reply is not read when its thread's parent is **older than the
window, off the page, and no reply in that thread was read inside the window**
- including a thread the bot itself revives by answering a post that old. A
top-level message is not read when the watcher's outage **outlasted the
window**, and a message or thread reply older than the newest 200 top-level
messages a catch-up delivers is not delivered either - both announced by that
catch-up's one `WATCH-INFO` line, with the range and the fetch recipe that reads
them on demand.
Everything else is delivered: on the page within one poll, off it within one
sweep. Inside a thread nothing is
dropped: `conversations.replies` pages forward from the thread cursor, and on a
full page the cursor stops at the newest reply read, so the rest arrive on the
following reads, one page each.

A thread's cursor is the newest reply the poll READ - with the parent's
`latest_reply` as a lower bound unless the page reported `has_more` and moved
the cursor - and never
`latest_reply` alone: the replies call runs after the history call, so it can
hold newer replies of the same burst, and a cursor written from `latest_reply`
sits behind them and delivers them twice. `watch.test.py` section 10x. A read that
finds nothing new leaves the cursor where it was, so a cursor always names a
real reply and a quiet thread leaves the window when its replies do.

The channel cursor moves with **every** top-level message a poll processes, not
once at the end of the poll: a call that fails later in the same poll leaves
the messages already delivered behind the cursor, so they are not delivered
again. `watch.test.py` section 10y-ix; the sweep and the window, sections 10y and 17.

### Retiring a conversation Slack says is gone

A per-conversation poll failure is caught so one bad conversation cannot kill the
whole watch. A **permanent** failure therefore repeats every poll - and at the
default 5 s poll that is ~720 lines an hour, every one of them a wake-up through the
follower, until Monitor's rate limiter stops the follower's Monitor outright and **the watcher is alive,
silent and looks healthy**.

So when a poll fails with `channel_not_found` (`GONE_CONVERSATION_ERRORS` in
`watch.py`), the watcher **retires** that conversation for the rest of the
process: **one** `WATCH-INFO retired ... (<id>): Slack says <reason>` line, then no
further polls or lines for it. (The case it covers: a DM that stays in
`users.conversations` discovery while `conversations.history` on it answers
`channel_not_found` for a bot token.)

- **Every other exception keeps its per-poll `WATCH-ERROR`**, deliberately: for a
  fault that can end - `ratelimited`, a timeout, `missing_scope` - repetition is
  the signal that it has not ended, and retiring one would drop a live
  conversation behind a single line nobody was watching for.
- **A cut or reset READ is re-issued before it can become a `WATCH-ERROR`.**
  `api()` issues a call up to `_READ_ATTEMPTS` (3) times on
  `http.client.IncompleteRead`, `ConnectionResetError` or a read timeout, with a
  short backoff, then re-raises the last one unchanged so the per-conversation
  guard still fires for a persistent fault. A large `conversations.history` body
  can be cut mid-body by the peer closing the connection at the client's ~64 KiB
  TCP receive window - a link event, not a Slack one, which is why the cut lands
  at the same offset across unrelated body sizes and why the next request
  returns the whole body. A Slack-level `ok:false` is an ANSWER, not a failed
  read, and is never re-issued. `watch.test.py` section 16.
- **The test for membership is "would DISCOVERY already fix this?", not "does
  this error look permanent?"** - which is why `not_in_channel` (kicked) and
  `is_archived` are **not** in the set even though both read as gone. Discovery
  lists only conversations the bot belongs to and passes `exclude_archived=true`,
  so either condition drops the conversation from the watched set at the next
  ~60s rediscovery by itself. Retiring them would buy ~12 suppressed lines and
  risk the opposite, far worse failure: a freshly /invited channel whose
  membership reaches discovery before the read path agrees answers
  `not_in_channel` on poll #1, and retiring it would kill a **live** channel for
  the rest of the process - permanently, because a member never leaves discovery
  to be un-retired. The argument, and the two checks that pin it, are in
  `watch.py` at `GONE_CONVERSATION_ERRORS` and `watch.test.py` sections 15b-ii and 15e-ii.
- A retirement **survives rediscovery** while the conversation is still
  discovered. If it leaves discovery and later returns, it gets one fresh probe.
- Retirement is **process-scoped**: restarting the watcher re-probes everything,
  so nothing has to be un-stuck by hand.
- The cost, and it is the reason the retiring set is deliberately one code
  wide: a retired conversation is watched by **nothing** until the watcher
  restarts, that one line is the only notice it ever gets, and its cursor stops
  advancing - so if it is ever un-retired, it resumes under THE WINDOW BOUND
  like any other gap.
- A Slack `{"ok": false}` answer raises `SlackApiError`, which carries the error
  code as `.code` - so a `WATCH-ERROR` line from an API failure reads
  `... SlackApiError: <method>: <code>`. `SlackApiError` subclasses
  `RuntimeError`, so code that catches `RuntimeError` catches it, and an
  operator filter keyed on `WATCH-ERROR` or on a conversation id matches the
  line.

### Known gaps

- Replies inside a thread whose **parent was deleted** are unreachable (Slack's
  history API can't list orphaned threads).
- A reply in a thread whose parent is **older than the 7-day window and off the
  poll's page**, with no reply in that thread read inside the window, is not
  read - THE WINDOW BOUND above. Answering a post that old does not bring its
  thread back into view.
- A catch-up delivers at most the **newest 200** top-level messages of a
  conversation; older messages and the replies under them are announced - ISO
  UTC range, no count - in one `WATCH-INFO` line and read on demand with the
  fetch recipe.
- A reply in a thread whose parent is off the poll's page arrives within one
  **sweep** (300 s to start, plus the polls the sweep needs at the shared
  per-poll budget), not one poll.
- The bot never sees channels of **other workspaces/orgs** it isn't installed
  in.
- DMs are invisible if the `im:*` scopes are ever dropped.
- A conversation Slack reports **gone** (`channel_not_found`) is
  retired and then watched by nothing until the watcher restarts - one line of
  notice, and no further sign. See *Retiring a conversation Slack says is gone*.
- A bot **kicked and then re-invited** keeps its cursor file, so first sight -
  and with it the baseline - never runs again: what was posted while it was out
  is emitted on the first poll after the re-invite, back to the window start;
  what lies before the window is not read, and one `WATCH-INFO` line says so.
- **A watcher line carries only TEXT.** A message that surfaces with empty text
  usually carries a FILE (audio clip, image) - see the file recipe below.
- The watcher surfaces **every** deliverable message, tagged or not; @-mentions
  of the bot are not a filter it applies.
- **There is no per-sender filter**, so a channel carrying a machine feed
  delivers every one of its messages. Leaving the channel is the remedy; the
  predicate is not.

## Claiming a request

**Every agent in a shared channel receives the same message, so a request more
than one of them could pick up is answered twice unless one claims it first.**
Before ANY visible act on such a request - a reply, a reaction, or starting the
work - claim it. The claim is `/chat-transport`'s transport-neutral helper, and
that skill's *Claiming a request* is the whole rule: what each answer means,
takeover, release, pruning and the one claims directory. What is Slack's is the
key and the acknowledgement.

**The key is the conversation ID and the `ts` of the message that carries the
request.** The watcher line carries the channel's NAME, so the ID comes from
`CONTEXT.md`'s channel table. The `ts` is the line's `[ts ...]`: for a thread
reply that is the reply's own `ts`, never the `reply in thread <ts>` root - one
thread carries many requests.

```bash
python3 "${CLAUDE_SKILL_DIR}/../chat-transport/claim.py" take <channel id> <ts> --agent <your name>
```

Without `--transport` the install's default transport is used; `--transport
slack` names Slack whatever the default. Exit `0` (`CLAIMED`, `ALREADY-YOURS`)
makes you the owner: react `eyes` (*React*), then post your ETA in the thread.
Exit `1` with a `CLAIMED-BY` line means another agent owns it: no reaction, no
reply. Anything else - a `2`, a `3`, or a `1` with no result line - is a fault,
never a win and never a loss.

## Posting

### Post

`chat.postMessage` as in *Transport* above, with `channel` set to the
conversation ID; a top-level post omits `thread_ts`. Read the JSON response
every time - an HTTP 200 carries `{"ok":false}` failures.

### Reply in thread

- Reply in a thread with `"thread_ts": "<parent ts>"`.
- Add `"reply_broadcast": true` to make a thread reply ALSO appear in the main
  channel (used when the audience is wider than the thread).
- A top-level post omits `thread_ts` entirely.

**Message-targeting trap:** before
ANY `chat.postMessage` carrying a `thread_ts`, verify the channel id is the one
that thread actually lives in. **Slack does NOT reject a foreign or nonexistent
`thread_ts` - it silently posts the message top-level in whatever channel you
named.** Never fire a message at a thread ts copied from a watcher line without
also copying its channel; and never post through a compound shell command whose
first half hasn't validated the target.

### Formatting

- Slack mrkdwn, not Markdown: `*bold*`, `_italic_`, `` `code` ``, triple-backtick
  blocks, `<https://url|label>` for links.
- **Tag a person with `<@UID>`** - a bare name notifies nobody.
- Emoji by `:shortcode:`.
- Newlines are literal `\n` inside the JSON payload.

### Editing and deleting

The bot can **edit** its own messages (`chat.update`, same `channel` + `ts`) and
**delete** them (`chat.delete`). Editing does not notify anyone, which is what
makes a pinned, continuously-updated status board viable. **`text` is capped at
4,000 characters on `chat.update` and `chat.postMessage` alike** - past it the
call returns `msg_too_long` and nothing changes, so a growing board is trimmed
before the edit, not after the refusal. Deleting a thread
parent orphans its thread - the replies survive but lose context and become
invisible to the watcher (see Known gaps).

**Verifying a cleanup: enumerate the PARENT'S REPLIES, never the channel
history.** `conversations.history` returns only top-level messages, so **thread
replies are invisible to it - including orphaned ones**. A cleanup that deletes
a parent and re-enumerates history therefore reads as "channel empty, all
deletions verified" while the replies are still there, unreachable and
undeleted. Check each parent with `conversations.replies` **before** deleting
it, and confirm afterwards that the call returns `thread_not_found`.

**And never trust a reply `ts` you recorded at post time - read it back.**
A reply `ts` recorded at post time can differ from the one Slack holds (in the
sub-second digits), so `chat.delete` returns `message_not_found` for every reply
while the *parent* deletes fine and history comes back empty: a cleanup that
reports **zero delete failures** and has deleted no reply. Both halves of that
verification are true and neither measures the thing that matters. Parse each `chat.delete` response individually (`{"ok":false,
"error":"message_not_found"}` arrives with HTTP 200 like everything else here),
and treat a `message_not_found` as a finding to investigate, not as "already
gone".

### React

`reactions.add` / `reactions.remove` with `{channel, timestamp, name}` - `name`
is the emoji shortcode without colons (`eyes`, `white_check_mark`, `+1`).
Requires `reactions:write`. **`+1` through a form-encoded body arrives as a
space** (`curl -d name=+1` sends `name= 1` and Slack answers `invalid_name`):
send it as `%2B1`, use a JSON body, or use the alias `thumbsup`.

### Direct message

A DM to a user goes through the same `chat.postMessage` with the **user's ID as
the channel** (`{"channel":"U...", ...}`) - Slack resolves/opens the IM conversation
itself. `conversations.open` with `users:<UID>` is available if you need the IM
channel id explicitly.

### DMs to an Assistant-enabled app - reply INSIDE the open assistant thread

**If the app has Slack's Assistant / AI-app feature enabled, its DMs are not
ordinary IMs.** A DM conversation is organised into **assistant threads** - you
will see `New Assistant Thread` messages from the human in
`conversations.history`. That changes where a reply has to go, and the three
options do NOT behave the same:

| what you send | what the human sees |
|---|---|
| `thread_ts` = **the open assistant thread's ts** | **correct - lands in the chat** |
| no `thread_ts` (top-level) | wrong - does not land in the conversation properly |
| a NEW thread on your own message | wrong - renders as collapsed **"history"**, easy to miss |

**So: take the `thread_ts` from the incoming DM and reply into it.** The watcher
line that surfaced the message carries it. Do not start your own thread, and do
not post top-level.

**Measured with a human on the other end**, both wrong options included.

**Getting the IM channel id:** `chat.postMessage` accepts a **user ID** as
`channel` and resolves it, but `conversations.history` does **not** - it needs the
real `D...` id, or it returns `channel_not_found`. Get it from
`conversations.open` with `{"users":"<UID>"}`.

**Not yet tested:** an agent-INITIATED DM where the human has no assistant thread
open. Prefer replying into the most recent one; if none exists, posting top-level
is the only option available and its behaviour is unverified - say so rather than
assuming it landed.

### Upload a file

Screenshots, packs, any artifact.

**A bot with `files:write` CAN upload files.** This is the delivery path for
screenshot packs and any visual a human needs to react to - there is no need to
route images through an agent session or paste filesystem paths a Slack user
cannot open.

`files.upload` is deprecated. Use the **three-step external flow**:

1. `files.getUploadURLExternal` - **form-encoded**, `{filename, length}` where
   `length` is the byte size. Returns `{upload_url, file_id}`.
2. `POST` the raw bytes to `upload_url` (`Content-Type: application/octet-stream`).
   No auth header on this one - the URL carries its own credential.
3. `files.completeUploadExternal` - **form-encoded**, with `files` as a
   **JSON-encoded string** of `[{id, title}]`, plus `channel_id` and optional
   `initial_comment`. Add `thread_ts` to land it in a thread.

Steps 1 and 3 are form-encoded, like `conversations.replies` - a JSON body gets
the same misleading "missing required field" error. **Several files completed in
ONE step-3 call post as a single message**, which is what you want for a
before/after pack: one notification, one comment, all images together.

The `initial_comment` is a normal mrkdwn message, so `<@UID>` tagging and all
formatting work in it. Prefer putting the explanation there rather than in a
separate post - a bare image drop makes the reader guess what they are looking at.

## Reading

### Fetch a message

**Fetch a message / thread:** `conversations.history`
(`{channel, latest, oldest, inclusive, limit}`) for top-level,
`conversations.replies` (`{channel, ts}`) for a thread. Use these to recover
the full content behind a watcher line - attachments, files, blocks, and
reactions exist only in the API payload, never in the watcher line.

### Permalink

`chat.getPermalink` with `{channel, message_ts}` returns a stable URL - use it
whenever a message needs to be referenced from another channel, a DM, or a repo
doc.

### Users

`users.info` / `users.list` resolve a UID to a profile (email included when the
install has the scope). If the fleet also has a personal Slack connector, its
user-search is the fallback for lookups the bot can't do - `CONTEXT.md` names
it.

### Voice messages and other file attachments

An empty-text watcher line usually means a FILE:

1. Fetch the message via `conversations.history` and read its `files[]`.
2. Slack's own `transcription` field is often `{"status": "none"}` - do not rely
   on it.
3. Download the file with the personal Slack key
   (`curl -H "Authorization: Bearer $TOKEN" <url_private_download>`).
4. Transcribe or interpret it with whatever model access the project has -
   **`CONTEXT.md` names the model and how its key is resolved**, because that is
   project infrastructure, not a Slack mechanic. Model IDs go stale and
   retired models return auth-shaped failures: **if the call 404s, probe the
   model before debugging the key.**

## Probed limitations (don't re-discover these)

- `users.profile.set` on the bot -> `not_allowed_token_type`. **A bot cannot edit
  its own Slack profile**, which is why a live status board has to be a pinned,
  edited message instead.
- `views.publish` (App Home tab) -> `not_enabled` unless the tab is turned on in
  the app config. If it is enabled, a status board can be mirrored there.
- **The bot cannot rename itself** - the display name is a Slack admin action.
  Renaming does not change the underlying handle, and mentions travel on the wire
  as `<@UID>` either way, so nothing keyed on the UID is affected.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Nothing arrives from Slack | The watcher service is not active, or its follower is not armed - check the service state and re-arm the follower (`CONTEXT.md`). Cursors survive, so downtime messages arrive on the first poll, and the follower delivers what the log holds. |
| Service exits 0 with `WATCH-GUARD` and stays down | Wrong `CLAUDE_CONFIG_DIR` for this config's `owner`, or a second watcher (a Monitor-run copy) already holds the flock. Stop the other copy, then start the service. |
| Exits with `WATCH-CONFIG ...` | `SLACK_WATCH_CONFIG` is unset, or the config it names is missing, malformed, missing a required key (it names the key), names a `token.path` that cannot be read (it names the path), or declares a workspace the token doesn't belong to. The unit restarts it, so a fixed config or a token written later is picked up on the next start. The follower's default filter does not pass this line: under the unit the session sees the restarts as `DAEMON-ALERT`, and the line is in the unit's log (`CONTEXT.md` names it). |
| A `WATCH-INFO retired ...` line | That conversation answered `channel_not_found` and is no longer polled by this process - see *Retiring a conversation Slack says is gone*. Expected for a dead DM. If it names a conversation you still expect traffic from, that is the one failure direction this design accepts: restart the watcher (retirement is process-scoped) and report it, because `channel_not_found` is not observed to arrive transiently. |
| A `WATCH-INFO` line about `missing_scope` | A scope (`groups:*` or `im:*`) is absent from the current install; the watcher degrades and re-probes each cycle. Fix = reinstall the app with the scope. |
| A new channel isn't being watched | The bot must be /invited (no `channels:join` scope). Wait one ~60s rediscovery cycle after the invite. |
| A reply landed top-level instead of in its thread | Channel/`thread_ts` mismatch - see the message-targeting trap above. |
| `{"ok":false,"error":"..."}` on an HTTP 200 | Always parse the body; common ones: `channel_not_found` (wrong/guessed ID), `not_in_channel` (bot not invited), `missing_scope`. |
| A thread has gone invisible | Its parent was deleted - orphaned threads can't be listed. Recover via a saved permalink if one exists. |
| A cleanup reported "all deleted", channel still has content | `conversations.history` cannot see thread replies. Verify with `conversations.replies` per parent (expect `thread_not_found`), and parse every `chat.delete` body - see Editing and deleting. |

## Related

- **This workspace's values** (IDs, channels, people, key path, owning agent):
  `CONTEXT.md` in the install (`fleet where slack-communication`)
- **Watcher:** `watch.py`, `watch.test.py` beside this file; its config is the
  file `SLACK_WATCH_CONFIG` names
- **Descriptor:** `transport.json` beside this file (`/chat-transport`)
- **Claim:** `/chat-transport`, *Claiming a request*
- **Policy, identity, authorization, triage:** the owning agent's charter, named
  in `CONTEXT.md`
