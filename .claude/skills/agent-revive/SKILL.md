---
name: agent-revive
version: 3
description: >
  Revive a stuck or expired fleet agent whose Claude Code session has stopped
  making progress, most commonly because its login expired and the session is
  sitting with a sign-in URL and a "Paste code here" prompt nobody is present to
  answer. The generic parts - connecting over tmux, triaging the pane, extracting
  a fresh sign-in URL, pasting the code and the bootstrap prompt back - are the
  same for every agent and are scripted. The sign-in itself is done by the reviving
  agent, driving a real browser interactively through a socket driver and reacting to
  each screen it finds rather than replaying a script. When a CAPTCHA stops it, the
  human step is tap-to-solve: the agent shares that same browser as a public,
  one-time-password, mouse-and-left-click-only page and one person solves the puzzle
  on it; a human signing in in their own browser is the fallback, for when the share
  cannot run. Google's
  "Verify it's you" challenge is an EXPECTED screen on either route, not a block:
  its code goes to the account's recovery email, one mailbox the reviving agent
  reads by API and answers itself. Also owns the
  ACCOUNT CHOICE at the sign-in: the Claude login's accounts are one pool that
  belongs to no agent, a lease file says which agent holds which account (one
  account live in one session at a time), the next account is the pool picker's
  deterministic pick from the usage ledger, and switching is done in-session so the
  running work survives. Knows each agent's AUTH MODE, from its unit: a login
  agent signs in through the browser; a TOKEN agent (claude setup-token) never
  does - its switch installs the next account's token and restarts it through its
  unit, and a dead token is reported to the operator, never revived; an api-key
  agent is in no pool. Owns the ONE way an account enters the pool
  (pool_pick.py --register). Per-install values (how sessions are named, where the
  account pool and its leases live, who the designated human is -
  one person, or an ORDER of people with a timeout between them)
  are in the install's config.json and CONTEXT.md. Load this when an agent has
  gone silent, when a session is reported stuck on a login prompt, when an agent
  must be moved onto a different account, or when bringing a rebooted agent back to
  a working session.
requires_install: true
---

# agent-revive - bring a stuck or expired agent back to life

A fleet agent runs as an unattended Claude Code session inside a tmux window. When
its login expires, the session prints a sign-in URL and waits on `Paste code here`
for a human who is not there: it looks hung, its watchers keep running, and it
makes no progress. This skill is the reproducible procedure to revive it, plus the
scripts for the mechanical parts. The same procedure moves an agent onto a different
account, because the sign-in is where the choice of credentials is made (step 5).

**This file is the MECHANISM and names nothing install-specific.** No host, no
person, no email, no absolute path, no agent name, no credential. Where a concrete
value is needed it refers to the config key - the session target
(`fleet.tmux.target`), the account pool (`accounts.pool_file`) and its leases
(`accounts.lease_file`), the service unit (`fleet.systemd_unit`) - never to
the value. The companion files carry the specifics. The two marked **this install**
live in the skill's install context, `<install root>/.claude/skills/agent-revive/`
(`fleet where agent-revive` prints it); every other file is in this directory, and
prose runs a script here as `"${CLAUDE_SKILL_DIR}/<script>"`:

| File | What it holds | Per install? |
|---|---|---|
| `SKILL.md` (this) | the revival procedure, the prompts, the traps | universal |
| `CONTEXT.md` | how this fleet names sessions, where the pool and its leases live, who the human is | **this install** |
| `config.json` | the machine-readable values the scripts read | **this install** |
| `config.example.json` | every key, placeholdered, with its explanation | universal |
| `secrets/claude-account-pool.example.json` | the shape of the account pool, with fake contents | universal |
| `tmux_triage.sh` | capture a session's pane, classify it, read whether its daemons run and each of their logs is followed, extract a wrapped URL, read the bootstrap prompt, report where everything of an agent is and how it signs in (`--facts`), report which account the session is on and list the pool with each account's role | universal |
| `token_switch.py` | move a TOKEN agent onto another pool account: install that account's token as the agent's auth file and restart the agent's session through its own unit (step 5, "Switching a token agent") | universal |
| `../agent-health/pool_pick.py` | the pool picker `--accounts` reads its `next` from, the one writer of the lease file (`--take`) and of the handover ledger, and the one way an account enters the pool (`--register`) - owned by `/agent-health`, which owns the usage ledger it predicts from; the scripts reach it through the fleet root | universal |
| `../google-spreadsheet/gsheets.py` | the delegated-token minter `read_recovery_code.py` imports (step 6b) - owned by `/google-spreadsheet`; reached through the fleet root | universal |
| `signin_driver/` | the browser the reviving agent drives for the automated sign-in: driver, client, README, `profile.mjs` (the stored-profile rules), `share.mjs` (the tap-to-solve share's rules and its one teardown), its offline redaction test, `profiles.test.mjs` and `share.test.mjs` | universal |
| `tmux_triage.test.sh`, `fixtures/` | the offline regression guard, and `fixtures/fake-tailscale.mjs`, the stand-in `tailscale` the driver's tests run so nothing they do is public | universal |
| `token_switch.test.py` | the token agent's guard: the user-manager unit read, the auth facts, the switch against a fake service manager, and the dead-token pane (`fixtures/token-invalid.txt`, a measured capture) | universal |

**This file contains no policy.** WHO may revive an agent, and WHO the designated
human for the sign-in is, are the reviving agent's charter and `CONTEXT.md`, not
this skill. The skill states HOW. **"The designated human" may be an ORDER of
people with a timeout rather than one person** - `CONTEXT.md` says which, and a
reader that assumes one fixed addressee asks the wrong person first.

**This is a security-sensitive procedure.** It handles a pool account's Google
password and the OAuth code that becomes the agent's session.

- On the **automated route (step 6)** neither secret is handled by anything that
  keeps a copy: the driver reads the chosen account's password out of the pool file
  inside its own process and types it into the field, and it writes the code to a
  mode-0600 file and reports its LENGTH. Nothing reaches a command line, a shell
  history, a tool result or a transcript.
- A **stored profile** ("Stored profiles" below) keeps one pool account's
  signed-in browser session on disk ON PURPOSE, so a revival types no password. It
  is a credential: it lives only in `accounts.profiles_dir`, mode 0700, and the
  driver refuses that directory inside a git work tree or an agents home.
- **Tap-to-solve (step 7)** hands a person no credential at all: a public link to a
  view of the driver's own browser, and a one-time password for that view, which
  dies with the share. The person can move the pointer and left-click, nothing else,
  and the window has no address bar.
- On the **fallback (step 7e)** the credentials of the ONE chosen account are
  delivered to a human so they can sign in in a real browser. That is the one path
  that carries them, by design. Deliver them only to the human `CONTEXT.md`'s order
  currently has you asking, only over the channel the charter names, and never log
  them.
- `tmux_triage.sh --accounts` never opens the pool file; the picker reads it
  in-process for **usernames** and neither prints a password - they exist so nobody
  `cat`s that file onto a pane.
- A **token file** (a pool account's long-lived token, and a token agent's auth
  file, which is a copy of one) is mode 0600 and is read by `pool_pick.py` alone:
  `--register` writes it from standard input, `--take --install-token` copies it
  file to file in-process, and `--read-auth-file` reads its comment header and
  never the line carrying the token. Nothing prints one, and nothing else opens
  one.

**Glyphs.** This file is ASCII. A character Claude Code draws on the pane is written
as its code point in braces: `{U+276F}` is the prompt and selection cursor (a heavy
`>`), `{U+25CF}` the message bullet (a filled circle), `{U+23BF}` the result-row hook
(drawn with a no-break space, U+00A0, after it), `{U+203A}` the queued-message mark,
`{U+00B7}` the middle-dot separator in status lines, `{U+2191}` and `{U+2193}` the up
and down arrows, `{U+2022}` a mask dot and `{U+2026}` an ellipsis. `tmux_triage.sh`
matches the glyphs themselves, byte for byte.

---

## The one mistake that costs real money - read this first, twice

> ## NEVER SELECT THE API / CONSOLE OPTION AT THE AUTH-METHOD MENU
>
> Regenerating a fresh sign-in URL (step 3) brings up Claude Code's login-method
> menu. **ALWAYS take the subscription account** - option 1, *"Claude account with
> subscription"*, where the cursor `{U+276F}` already sits, selected by a bare Enter.
> **NEVER move to option 2**, *"Anthropic Console account - API usage billing"*.
>
> **Why this is the one irreversible-cost mistake in the whole procedure.** Option
> 2 authenticates the session against a metered API key that **bills per token,
> against our budget, on every single turn the agent takes**, for as long as that
> agent keeps running. Option 1 does not: it runs against a flat-rate plan. A
> revived agent works either way, so nothing on screen ever warns you that you
> picked the meter - the bill is the only symptom, and it arrives later.
>
> The cursor defaults to option 1, so the safe action is to send **Enter and
> nothing else** - do NOT arrow down. If you have arrowed, arrow back up and
> confirm `{U+276F}` is on option 1 before Enter. This is the one step in this skill where
> a stray keypress costs money.

The same warning is repeated at step 3 where it applies. It is repeated on purpose.

---

## The reproducible path (the spine of this skill)

This is the sequence, measured working on a real expired agent. `<agent>` is the
agent's fleet name; the scripts resolve its session, Claude config dir and unit from
that name through the config templates. Run the read-only parts through
`tmux_triage.sh`; the keystroke and sign-in parts are the tmux commands shown.

**Links AND sign-in phases EXPIRE - act fast.** The displayed URL is usually
already stale, and even a freshly generated one, and the half-completed sign-in
behind it, time out. If any step stalls on an expired link, regenerate a fresh URL
(step 3) and restart from there. Do not nurse a stale link.

### 1. Connect to the agent's session

The agent's tmux server lives on a socket dir and the session is a target; both
come from the agent's facts, and `<tmux_tmpdir>` and `<tmux_target>` in every
command below are those two values:

```
"${CLAUDE_SKILL_DIR}/tmux_triage.sh" <agent> --facts         # where everything of this agent is (JSON)
"${CLAUDE_SKILL_DIR}/tmux_triage.sh" <agent>                 # capture the LIVE pane and classify it
```

`--facts` reads the agent's service unit - from the USER manager first
(`systemctl --user cat`, the fleet's agent unit template is a user unit), then
the system manager - and prints the manager that runs it (`unit_scope`), its
config dir, its socket dir (the unit's own `TMUX_TMPDIR`, with `%t` expanded for
that manager: `/run/user/<uid>` for the user's, `/run` for the system's; the
config template `fleet.tmux.tmpdir` when no unit answers), `tmux_target`, and its
AUTH MODE (step 2). On macOS the unit is the agent's launchd job, read from its
plist (`~/Library/LaunchAgents/<label>.plist`, then `/Library/LaunchDaemons/`), with
`fleet.systemd_unit` holding the label (`<launchd_prefix>.session.<agent>`): its
EnvironmentVariables are the unit's environment, the session supervisor's
`--env-file` its credential file and `--boot` its boot message; `unit_manager` says
which service manager answered.

**`$TMUX` beats `$TMUX_TMPDIR`.** A `tmux` run from inside another session reads
THAT session's server. Every tmux call here drops `$TMUX` (`env -u TMUX ...`);
`tmux_triage.sh` does it for you. A bare `tmux` you type by hand must be prefixed
`env -u TMUX`.

### 2. Triage: is this an expired login?

**First, how does this agent sign in?** `--facts` (step 1) prints `auth`, read
from the agent unit's `FLEET_AGENT_AUTH` line - the line the fleet's agent unit
template records it in, beside the `EnvironmentFile=` that carries the
credential (`/adding-an-agent` writes both); every triage object carries the same
`auth`:

| `auth` | The session | What this skill does for it |
|---|---|---|
| `login` (or no such line) | an interactive sign-in kept in its config dir | everything below: the browser sign-in, the in-session switch |
| `token` | `CLAUDE_CODE_OAUTH_TOKEN`, a long-lived token from `claude setup-token`, read from the unit's EnvironmentFile (the auth file) | **no browser sign-in, ever.** A switch installs the next account's token and restarts the session through its unit (step 5, "Switching a token agent"); a dead token is `token-invalid`, reported (case 15) |
| `api-key` | `ANTHROPIC_API_KEY` from the auth file, billed per token | nothing: it holds no pool account and has no plan windows; a dead key is `token-invalid`, reported (case 15) |
| `mismatch`, `unknown` | the auth file is missing, the value is none of the three, or the unit could not be read | **nothing until a person fixes it** - `auth_problem` says what. An unreadable unit is never read as `login`: that default walks a token agent into /login |

**/login in a token or api-key session does not switch it and does not revive
it.** Claude Code keeps the token its environment gave it over any stored
sign-in - measured from the 2.1.317 binary: *"OAuth 401: keeping the
user-supplied CLAUDE_CODE_OAUTH_TOKEN instead of adopting the stored credential.
Mint a fresh token with `claude setup-token` and restart with it"*. A browser
sign-in typed into such a session leaves it on its old token while everything
around it records a switch.

`tmux_triage.sh <agent>` reports `signin-url` when the pane shows an OAuth sign-in
URL (a `https://.../oauth/authorize?...` link) followed by `Paste code here`. That
is the expired login, and it is the case this skill exists for. An expired login
also sits at an ordinary READY prompt with no URL on the pane at all: that is
`login-expired`, below. (Other states:
`healthy` - nothing to do; `stopped` - idle with none of its daemons running, see
below; `follower-down` - idle and not hearing every daemon the fleet runs for
it (a follower down, or a daemon writing to a replaced log), see below; `login-expired` - the session's last message is a dead-login line at a ready
prompt, see below; `token-invalid` - the same last word on a token or api-key
agent: its credential expired or was revoked, case 15, reported and never typed
at; `auth-method` - the login menu is already up, go to step 3's Enter;
`theme-prompt` / `scroll-prompt` - a first-run prompt, answer per step 9;
`status-modal` - a /status block is open and must be dismissed with Escape (step
5); `usage-cap` - a usage-limit banner with no sign of a running turn, so the quota
window looks exhausted (step 5, case 14); `working` - the session is taking a turn
right now, which is stronger evidence than `healthy` and needs nothing;
`survey-prompt` - a session-rating prompt is drawn over the input, which is an IDLE
state and not a revival case: send `0` to dismiss it and re-triage; `unreachable` -
there is no tmux session at all, so the agent is DOWN rather than merely logged out,
and the service unit is where to look; `unknown` - read the pane yourself, and the
capture comes back in the output's `pane` field rather than on stderr.)

**`stopped` IS AN IDLE SESSION WITH NOTHING RUNNING BEHIND IT, AND THE PANE ALONE
CANNOT SHOW IT.** A fleet agent is woken by daemons it keeps running - an
inbound-message watcher, a scheduler - and `fleet.daemons` lists them. The triage
reads the process table, not the pane: for each daemon, does a process whose command
line carries its pattern run with THIS agent's `CLAUDE_CONFIG_DIR` in its
environment. The output carries that reading in every state - `daemons` (per daemon
`true`, `false`, or `null` when the reading could not be taken), `daemons_expected`,
`daemons_running` - plus `last_turn_error`, the last `API Error:` line the pane's
live area shows. A ready prompt with EVERY configured daemon and every expected
follower (below) absent reads `stopped` instead of `healthy`: nobody's message and
no scheduled task can reach that session, so it stays idle until a person happens
to look.

- **It is NOT a sign-in case.** No /login, no Ctrl-C, no account switch: the login
  is fine and the session is simply not polling anything.
- **Read the pane before typing anything.** A person may have typed into the input
  box and never sent it; typed keys append to that text and Enter submits both.
- **The remedy is a wake line** typed into the pane, by whoever `CONTEXT.md`
  authorises - the session takes a turn and re-arms its daemons' followers. `last_turn_error`,
  when set, says what the last turn ended on.
- **A `working` pane is never `stopped`** (a session mid-turn may not have re-armed
  yet), **one running daemon keeps it out of `stopped`** (an agent may run only some
  of the fleet's daemons), **a `null` reading decides nothing**, and **no daemons
  configured and no follower expected means no reading** - the state is then
  `healthy`.

**`follower-down` IS AN AGENT DEAF TO ONE SOURCE, AND IT IS NEVER `healthy`.** The
session hears each daemon only through the follower it arms for that job
(`agent-daemons.py follow <agent> <job>`: the scheduler's, and each working
transport's watcher). The triage derives the jobs it must follow from the fleet
itself - the jobs `agent-daemons.py status <agent> --json` reports as configured
for the agent, in `followers_expected` - and reads each follower from the process
table by its argv positions, never by a substring, with this agent's
`CLAUDE_CONFIG_DIR`: `followers` (per job `true`, `false` or `null`) and
`followers_down` (the jobs read false, in every state, a `working` one included). A
ready prompt with an expected follower down while something else can still wake it
reads `follower-down`; every daemon and follower down reads `stopped`. The remedy is
the same wake line, asking the session to re-arm the follower of each job in
`followers_down`, with the same rules: read the pane first, not a sign-in case. On
macOS no process's environment is readable, so no follower is read: `followers` is
empty, and only a replaced log (below) makes the state `follower-down` there.

**A daemon writing to a replaced log is the same deafness with every follower
armed.** A unit opens its log once, at start; a log rewritten in place (`sed -i`,
any write-a-copy-and-rename) or moved leaves the daemon appending to the old file
while its follower reads the path, which never grows. `agent-daemons.py status
<agent> --json` reads each job's stdout and stderr (`log_replaced`; on macOS
through `lsof`), and the triage lists the configured jobs it names in
`logs_replaced`, in every state on both systems. A ready prompt with one reads
`follower-down`, and its remedy is NOT a wake line: the job's unit needs a restart,
which the fleet's refresh job makes on its next run (every 5 minutes on systemd,
`StartInterval` 300 on launchd). Report the reading; one that outlasts that run
means the refresh job is not running, and `fleet status` names it.

**`login-expired` IS A DEAD LOGIN BEHIND A READY PROMPT, AND IT PRINTS NO SIGN-IN
URL.** Once the session's token can no longer be refreshed, every turn it takes ends
on a result of the shape `<reason> {U+00B7} Please run /login`, and the prompt is ready
again. `Login expired` (and the 401 form `Please run /login {U+00B7} API Error: ...`) is
drawn as a top-level message, `{U+25CF}` at column 0; `OAuth token revoked` and `Not logged
in` are drawn as a `{U+23BF}` result row under the line before. Its daemons keep running
and keep waking it, and every wake fails at once, so the daemon reading cannot see
this state and the pane alone matches `healthy`. The triage reads it only when that
result is the session's LAST word and the input box is on the pane:

- **A quoted copy is not a word.** A nested bullet in a message, a `cat` or a `git
  diff` shown as tool output, a quote mid-sentence, a message whose first paragraph
  is only the line with prose after it, and a `{U+23BF}` row quoted in an agent's own
  message all read as what they are. A `{U+23BF}` row counts only with the non-breaking
  space Claude Code draws after the glyph, and only under an input line - a Monitor
  event, a tool call, a prompt echo, a `{U+203A}` message.
- **Anything later clears it**: a later turn's message, a prompt echo (a turn began),
  or `Login successful` - under a /login, or on the login dialog's own screen.
  `Login interrupted` is a cancelled login and does not. Remote Control's `OAuth
  token unavailable` notice decides nothing either way: a network outage can raise it
  too.
- **No input box with the focus, no state.** The remedy types /login and Enter,
  and on the exit dialog that Enter selects "Exit and stop tasks"; a dialog drawn
  under a box that stays on screen (plan approval, mode switch) would take it too. A
  dead result with a dialog or a panel holding the keys reads `unknown` - no
  verdict, a person reads the pane - and its note says not to type until the dialog
  is understood.

`banner` carries the result line.

**On a token or api-key agent the same last word is `token-invalid`, not
`login-expired`.** Measured 2026-11-06 on 2.1.317: a session started with a
refused `CLAUDE_CODE_OAUTH_TOKEN` ends every turn on `Please run /login {U+00B7}
API Error: 401 OAuth access token is invalid.` - exactly the dead-login shape
(`fixtures/token-invalid.txt` is that capture). Its remedy is case 15, never the
/login below.

- **The remedy is the /login route at the ready prompt** (step 3): /login +
  Enter, then a bare Enter on option 1. Never a Ctrl-C. Read the input line first:
  typed keys append to unsent text.
- **Sign the SAME account back in** (step 5's default): an expired login is not an
  account problem. A usage-limit banner on the same pane makes it case 14 instead.
- **The automated sign-in first** (step 6); a human only where it stops - to tap a
  CAPTCHA on a shared view of it (step 7), or, as the fallback, to sign in themselves
  (step 7e).
- **Precedence.** `signin-url` and `status-modal` win: a code prompt means /login
  has already run, and a modal is dismissed and re-triaged. It beats `usage-cap`,
  whose wait branch never ends on a dead login. `working` wins only on the markers a
  turn draws - the interrupt hint, an agent-tree row with a running timer - and never
  on the agents panel or the spinner. It is never refined into `stopped`: a wake line
  into a logged-out session fails like every other turn.

**Every triage run emits ONE JSON object and nothing else**, `unknown` included.
A caller that merges stdout and stderr - which a tool call does by default - can
therefore always parse the result, instead of reading a screen of pane decoration as
the script having failed.

`working` is read off the live status area, which is not always the bottom of the
pane. The agents panel has two layouts and both count: in MANAGE mode it replaces
the status bar (a `{U+2191}/{U+2193} to select` header over agent rows carrying running timers),
so a pane showing only that panel has no status bar, no banner and no prompt on it;
LISTED under the prompt, the same rows sit below a status bar that ends in `{U+2193} to
manage`, and push that status bar, interrupt hint included, out of the tail the
script reads. The live spinner above the prompt box (a verb, then a parenthesised
elapsed time and token count) counts too. Without these a working agent reads as a
pane nobody can interpret - or worse, as whatever first-run selector its own
transcript happens to resemble.

**`theme-prompt` and `scroll-prompt` both tell you to TYPE into the pane, so they
are matched by the selector's own option lines, never by words.** A word match
reads `scroll-prompt` off a working agent whose transcript merely discusses a
scrolling bug. The
scroll selector's wording is not in the Claude Code 2.1.281 binary (measured
2026-09-24), so its signature comes from a synthesized fixture; a selector that
renders differently falls through to `healthy` or `unknown`, and nothing is typed.

**THE BANNER DECIDES BETWEEN WAITING AND SWITCHING, AND IT IS READ BEFORE ANY
KEYSTROKE.** A **session**-window cap whose reset time is imminent - within ~15
minutes - continues by ITSELF on the same account: the status line reads `Usage limit
reached {U+00B7} continuing shortly {U+00B7} esc to cancel`, and the session resumes when the window
resets. The right action there is to type NOTHING and poll the pane with a bounded
until-loop to ~3 minutes past the reset time. Everything else takes the switch, which
is the expired-login procedure: a human, a fresh sign-in URL, and the NEXT account
from step 5. That covers a **weekly** cap, a **session** cap whose reset is hours
away, and a `signin-url` pane.

The banner reads `You've hit your <limit name> limit` and names a reset time. The
limit name says what the cap follows: a **session** or **weekly** window follows the
ACCOUNT, which is why the switch fixes it; a **model-scoped** or **spend** cap does
not, and goes to the human as it stands. The reset time says whether waiting is
bounded. `tmux_triage.sh` reports all of them as the single state `usage-cap`, so the
state is never the discriminator - the `banner` line it returns is, and reading it is
what separates a wait from a switch. It matches the limit name as a word run rather
than as a list, because a list of the names we know today goes stale as a false
negative the day a new plan or model ships - and a false negative here is an agent
sitting capped and reporting `healthy`. **`fast limit` is excluded**: that is the
Fast-mode cooldown, it resets in minutes, and the session keeps working through it.

**`usage-cap` IS A TRIGGER TO LOOK, NOT A LICENCE TO TYPE.** The classifier sees
a banner on a pane; it cannot see whether the session is SAYING it or merely
SHOWING it. Every ordinary way of quoting the banner starts a line with punctuation
- a bullet, a blockquote, a diff hunk, a `cat`, a message one agent is composing
about another - and a window that has already reset leaves the banner in the
scrollback. The script refuses the state while the session is demonstrably taking a
turn, which removes the worst of it, but a finished turn whose transcript shows the
banner still reads `usage-cap`. **So confirm the `banner` line is the session's own
live state before sending it a keystroke.** Typing /login into a healthy session
blocks it on a sign-in nobody needed, which turns a working agent into the exact
thing this procedure exists to fix. Waiting is correct only where the banner earns
it: a session window minutes from its reset recovers on its own, while a session cap
hours out parks the agent and a weekly cap parks it for DAYS, holding its in-flight
work and answering nobody the whole time - and the account switch takes minutes.

### 3. Get a FRESH sign-in URL

**Do not reuse the URL already on the pane - it is usually stale or already
consumed.**

**And do not regenerate while a link you have already posted is still live for
someone** - a new link kills the code they are about to send back (see Traps).
Regenerate at the moment you send, never ahead of it.

Force the session to print a new one. Which keystroke opens the menu depends on the
session's state:

- **Session at its ready prompt (a live session being switched to another
  account, or a `login-expired` pane):** type the /login command. Measured 2026-09-12 on Claude Code 2.1.266
  with two Monitors running: /login + Enter opens the login-method menu within
  ~8 s.

  **Literal text is always sent as `-l -- "<text>"`.** Without the `--`, text
  that begins with `-` or `/` is parsed as tmux's own options instead of being
  typed, which fails as a tmux usage error rather than as anything about the
  session. Every literal send in this skill carries it.

  ```
  env -u TMUX TMUX_TMPDIR=<tmux_tmpdir> tmux send-keys -t <tmux_target> -l -- "/login"
  env -u TMUX TMUX_TMPDIR=<tmux_tmpdir> tmux send-keys -t <tmux_target> Enter
  "${CLAUDE_SKILL_DIR}/tmux_triage.sh" <agent>          # confirm state is 'auth-method' before the next line
  # select option 1 (cursor defaults to {U+276F} there) with a BARE Enter:
  env -u TMUX TMUX_TMPDIR=<tmux_tmpdir> tmux send-keys -t <tmux_target> Enter
  ```

  **Do NOT send a rapid double Ctrl-C to a session at its prompt.** On 2.1.266
  with background Monitors it opens the EXIT dialog - *"Background work is running
  ... 1. Exit and stop tasks / 2. Move to background and exit / 3. Stay"* - with the
  cursor on **1. Exit and stop tasks**, so the bare Enter the next line prescribes
  would kill the session and its watchers. `tmux_triage.sh` reports that dialog as
  `unknown`; if you see it, arrow Down twice to **3. Stay** and Enter, re-triage to
  `healthy`, then use /login.

- **Session at its ready prompt but USAGE-CAPPED (`usage-cap`):** the same /login
  route, and **only** that route. Measured 2026-09-14 on Claude Code 2.1.266 against
  a capped idle prompt: `send-keys -l -- "/login"` then `send-keys Enter` (two
  separate calls) brings up the auth-method menu in ~6 s, and a bare Enter on
  option 1 prints the fresh URL in ~5 s.

  ```
  env -u TMUX TMUX_TMPDIR=<tmux_tmpdir> tmux send-keys -t <tmux_target> -l -- "/login"
  env -u TMUX TMUX_TMPDIR=<tmux_tmpdir> tmux send-keys -t <tmux_target> Enter
  "${CLAUDE_SKILL_DIR}/tmux_triage.sh" <agent>          # 'auth-method' before the next line
  env -u TMUX TMUX_TMPDIR=<tmux_tmpdir> tmux send-keys -t <tmux_target> Enter
  ```

  **A rapid double Ctrl-C does NOT open the login menu on a capped prompt** - it
  opens a usage dialog. A double Ctrl-C is a route to the login menu on no pane.

  **AND SENDING Ctrl-C TO A CAPPED SESSION CANCELS ITS AUTOMATIC CONTINUE**
  (`Automatic continue cancelled - /rate-limit-options to re-arm`). The automatic
  continue is the session's own recovery at the reset time, so a stray Ctrl-C
  removes the fallback while leaving the cap in place: after it, the account switch
  is the only way back.

  **Escape is no safer.** A capped session's own status line reads *"Continuing
  automatically when your limit resets {U+00B7} esc to cancel"*, so Escape cancels the
  continue exactly as Ctrl-C does. Whether Escape on the usage dialog merely closes
  the dialog or also reaches that cancel has not been measured - which is the reason
  not to open the dialog in the first place. **Send /login to a capped pane, and
  neither Ctrl-C nor Escape.** The same caution applies to a /status block found
  open on a capped pane: dismissing it is the documented remedy, and on that pane it
  may cost the automatic continue.

- **Session blocked on `Paste code here` after an EXPIRED login (not capped):** the
  paste prompt accepts no commands, so /login typed there is ignored. Leave the
  prompt with ONE Escape, then take the ready-prompt route. Measured 2026-10-22 on a
  live, non-capped paste prompt: Escape prints `Login interrupted` and returns the
  session to its ready prompt, where /login + Enter opens the auth-method menu.

  ```
  env -u TMUX TMUX_TMPDIR=<tmux_tmpdir> tmux send-keys -t <tmux_target> Escape
  "${CLAUDE_SKILL_DIR}/tmux_triage.sh" <agent>          # the ready prompt, with 'Login interrupted' above it
  env -u TMUX TMUX_TMPDIR=<tmux_tmpdir> tmux send-keys -t <tmux_target> -l -- "/login"
  env -u TMUX TMUX_TMPDIR=<tmux_tmpdir> tmux send-keys -t <tmux_target> Enter
  "${CLAUDE_SKILL_DIR}/tmux_triage.sh" <agent>          # 'auth-method' before the next line
  env -u TMUX TMUX_TMPDIR=<tmux_tmpdir> tmux send-keys -t <tmux_target> Enter
  ```

  **NEVER send a double Ctrl-C to a paste-code prompt: it QUITS Claude Code.**
  Measured 2026-10-22: a rapid double Ctrl-C on an expired-login `Paste code here`
  prompt exits the client and the service restarts the unit, dropping the session
  context. It is not a route to the login menu on any pane.

  **A `Paste code here` prompt reached FROM A CAPPED PROMPT via /login takes no
  Escape.** On that pane Escape (like Ctrl-C) can cancel the session's automatic
  continue at the reset time, which is the one loss that has no undo. **Regenerating
  on such a pane is the capped route again** - /login + Enter (menu in ~6 s), then
  a bare Enter on option 1 (fresh URL in ~5 s). Measured 2026-09-14 on Claude Code
  2.1.266.

  **The two panes are indistinguishable at the prompt, so the question is not what
  the pane shows but HOW IT GOT THERE**: a paste-code prompt you produced by sending
  /login to a capped session is capped-origin, however ordinary it now looks, and
  `tmux_triage.sh` reports both as `signin-url`. When the origin is unknown, read the
  pane for a usage-limit banner above the prompt, and when it is still unknown take the
  /login route FIRST: it is safe on both panes, and an expired-login paste prompt
  simply ignores it (no `auth-method` within ~10 s), which is the signal that the pane
  is not capped and the Escape above is safe. The reverse order has no such recovery -
  the cancelled automatic continue does not come back.

> **NEVER arrow down to option 2 (*"Anthropic Console account - API usage
> billing"*): it bills per token against our budget on every turn, forever. Send
> Enter on option 1 only.** See the banner above.

After Enter, the session prints a fresh sign-in URL and blocks on `Paste code
here`.

### 4. Extract the fresh URL (joining wrapped lines)

**tmux wraps the URL across several pane lines, and a naive `grep -oE
'https://[^ ]*'` TRUNCATES it** at the end of the first pane line - 284 of a
450-character URL, measured - and a truncated OAuth URL silently fails to authorize. `tmux_triage.sh <agent>` prints the
FULL url under `signin_url` by joining the continuation lines: from the `https://`
line, it concatenates each following line that is non-empty, contains no space, and
is not the `Paste code here` line, stopping at the first blank / spaced / `Paste`
line. Use the script's `signin_url`; do not re-grep the pane by hand.

### 5. Decide WHICH account signs in

The sign-in has a choice in it. Make that choice here, before anything is handed to a
human - once the human has the wrong credentials the mistake costs a whole round trip
and a fresh URL.

**The Claude login's accounts are ONE POOL, and they belong to no agent.** The login
governs the token quota and nothing else (see "What a switch actually changes" below),
so any agent may be signed in with any pool account. The pool is one file
(`accounts.pool_file`), a JSON list of `{ username, password, token_file, home_agent }`:
an entry carries a password (what a `login` agent's browser sign-in types), a token
file (what a `token` agent runs with), or both; `home_agent` records which agent an
account was issued for and decides nothing. Which agent holds which account right
now is the **lease file** (`accounts.lease_file`), `{ "<username>": { "agent",
"since" } }`.

#### Adding an account to the pool - the one way

```
python3 "${CLAUDE_SKILL_DIR}/../agent-health/pool_pick.py" --register <username> --token-stdin [--home-agent <agent>]
python3 "${CLAUDE_SKILL_DIR}/../agent-health/pool_pick.py" --register <username> --password-stdin
```

The credential is read from standard input - without echo when stdin is a
terminal, so a person pastes it at the prompt - and never from an argument, so it
reaches no command line, history or transcript. A token is what `claude
setup-token` printed for that account (it must start `sk-ant-oat`, so an API key or
a stray line is refused); it is written to `<accounts.tokens_dir>/<username>.env`
(default `claude-account-tokens` beside the pool file), mode 0600 in a 0700
directory, as

```
# fleet-auth: token
# fleet-account: <username>
CLAUDE_CODE_OAUTH_TOKEN=<the token>
```

- an environment file systemd reads as it stands, whose header names the account.
A second `--register` of the same username adds the other credential and keeps the
first. The first registration creates the pool (0600), the lease file (`{}`) and
the usage ledger; the JSON it prints names every file it created and never a
credential. `claude setup-token` runs where a browser is (one approval of the
account's sign-in); the token prints once, is saved nowhere, and is valid for one
year (vendor docs; the 2.1.317 binary's default is 31536000 seconds).

**A token agent's own auth file is installed from the pool**, never written by
hand: `pool_pick.py --take <username> --agent <agent> --install-token <the
agent's auth file>` copies that account's token file over it and takes the lease
in one locked write, so the header names the account the session runs as and
`--current-account` can read it. A hand-written auth file names no account, and
the agent is then case 3b until a `--take --install-token` replaces it.

**ONE ACCOUNT IS LIVE IN ONE SESSION AT A TIME** - while the pool has at least as many
accounts as there are agents. Usage follows the account, so two agents on one account
drain it at twice the rate and neither one's usage readings mean anything. A leased
account is never offered, and the lease moves only with `pool_pick.py --take` (below),
which releases and re-takes in one locked write.

**With FEWER accounts than agents** (one account and two agents; two and four) agents
may share an account, and only as an explicit **shared lease**: one lease naming every
holder, `{"agents": [..], "since"}`. It is joined only by `--take <account> --agent
<agent> --share`, which is refused - changing nothing - while the pool has as many
accounts as agents. The pick offers a share only when no free account qualifies
(`"share": true`, and `--accounts` marks that row `next-shared-with-<holders>`).
Readings of a shared account are taken once per sweep and attributed to the account
(`/agent-health` step 1); a handover moves the whole group (`/agent-health` step 9).
**A share is never silent**: `pool_pick.py --shares` prints `N agents share account
X` for each one, and `fleet status` repeats it - as ok while sharing is allowed, as
drift once the pool has an account for every agent. `--release --agent <agent>` takes
an agent leaving the fleet out of every lease it holds.

Read the pool, the leases and the pick without opening the pool file:

```
"${CLAUDE_SKILL_DIR}/tmux_triage.sh" <agent> --current-account   # the account this session last signed in as
"${CLAUDE_SKILL_DIR}/tmux_triage.sh" <agent> --accounts          # every pool account: username, role, why
```

`--accounts` prints one row per pool account - `username`, a role, and the picker's
note on it - where the role is `current` (this session's account), `leased-by-<agent>`
(`leased-by-<a>,<b>` for a shared lease), `next` (the account to switch to),
`next-shared-with-<holders>` (a share pick) or `free`. It exits 0 only when a `next` row exists
and nothing disagrees; every other outcome marks no row `next`, exits 1 and says why on
stderr. It passes the agent's auth mode to the picker, so a token agent's `next` has a
token file and a login agent's a password; an api-key, mismatch or unknown agent gets
no table (case 15).

`--current-account` reads a login agent's account from its config dir and a token
agent's from its auth file's `# fleet-account:` header: a session on an environment
token records no sign-in in `.claude.json`, and its /status shows `Auth token:
CLAUDE_CODE_OAUTH_TOKEN` with no `Email:` line (measured 2026-11-06, 2.1.317).

**Never `cat` the pool file to answer this.** It holds EVERY pool account's
password. `--accounts` prints usernames and never a password; `cat` puts them all onto
a pane, into a scrollback, and into a transcript that outlives the revival. That is
the whole reason the command exists.

**The default is to sign the SAME account back in.** An expired login is not an
account problem, and re-signing the account that expired is the entire fix. Switch
only when (a) the operator or the charter instructs it, or (b) the failure is
**account-scoped** - a usage limit, a suspension, a terms block - i.e. it follows the
account rather than the session.

**The switch target is the account `--accounts` marks `next`, which is the pool
picker's answer** - agent-health's `pool_pick.py`, a deterministic
function of the pool, the leases, the usage ledger (`accounts.ledger_file`), the
exclude list (`accounts.exclude`) and the clock, so two operators pick the same
account. In order:

1. **Predict** each account's weekly usage from the ledger's latest weekly reading of
   that account - in whichever agent's section it was recorded, because usage follows
   the account. A recorded weekly reset that has passed predicts 0%; otherwise the
   reading stands. An account with no ledger row at all is idle: 0%, reset unknown.
2. **Exclude** the current account, every leased account, every account on the exclude
   list, and every account predicted at 80%+ weekly.
3. **Prefer the soonest NEXT weekly reset** among those left with at least 30%
   headroom. Headroom that expires at a reset is lost if it is not spent, so it is
   spent first and the long runways stay in reserve. A passed reset rolls forward in
   7-day steps; an unknown one sorts last.
4. **Ties go to the account idle longest.** With nothing at 30% headroom the least-used
   of the rest is picked, and the reason says so.

`pool_pick.py`'s header owns the rule, and `pool_pick.test.py` pins every clause of it.
A predicted 0% is a guess about an account nobody has read: it is right whenever
the account really was idle, and the first /usage reading after the switch replaces
it with a measurement.

**With a pool there is always a candidate unless the pool is exhausted** - every
account current, leased, excluded or at 80%+ weekly. That is case 1, and it is an
escalation, not a wait.

**Taking the lease is part of the switch.** Once the agent is signed in on the new
account - not before, because a sign-in that fails leaves the agent where it was:

```
python3 "${CLAUDE_SKILL_DIR}/../agent-health/pool_pick.py" --take <the new account> --agent <agent> --why "<what made this a switch or a revival>"
```

It releases every lease `<agent>` holds and leases the new account to it in one locked
read-modify-write that replaces the file atomically, so the file never shows the agent
on two accounts or on none. It refuses (exit 1) an account leased to another agent or
in no pool entry. Re-signing the same account leaves its lease alone. Under the same
lock it appends one row to the handover ledger (`accounts.handover_ledger_file`) -
When, Agent, Old account, New account, Why, Outcome - so every lease change has its
row by construction; `--record --agent <agent> --why ... --outcome ...` adds a row
that moves no lease (how the handover ended). The actor of every row is the agent
that ran the command.

#### Reading the current account when /status cannot run

This is the normal case, not the exception: a session blocked on `Paste code here`
accepts no commands, so /status is exactly the thing you cannot do at the moment
you need the answer. `--current-account` needs no session at all. It reads
`.oauthAccount.emailAddress` from `.claude.json` in the agent's Claude config dir -
resolved from the service unit's `CLAUDE_CONFIG_DIR`, falling back to the fleet's
own layout (`fleet.agents_home`) - which records the **last successful login**, i.e.
precisely the account that has now expired. That file holds no secret: the OAuth
token lives in a separate file this skill never opens.

When the session *is* alive, /status answers it too. **Take the account from the
block's `Email:` line, which states it outright.** The `Organization:` line is
derived and only sometimes contains the email - on a Workspace account it commonly
renders the organisation's NAME instead - so reading the account off it works until
the day it quietly does not.

**Dismiss the /status block with Escape the moment you have read it, then
re-triage.** A modal left open on an agent's pane makes the next person read a
working session as a stuck one.
`tmux_triage.sh` reports `status-modal` rather than `healthy` for exactly this
reason - so a block you forgot to close is caught rather than mistaken for a ready
prompt.

#### A login agent's switch is IN-SESSION ONLY - the session and its in-flight work must survive

Do the switch inside the running session: /login to the auth-method menu (step 3;
a session already blocked on a non-capped `Paste code here` is first left with one
Escape), then sign
in with the chosen account. **Restarting the agent's service is FORBIDDEN
as a way to switch a login agent's account.** It does re-run `ExecStartPost` for you,
but it drops the resumed session context and kills the subagents the agent has in
flight - the work you are trying to keep alive is the reason you are switching at
all. For a login agent's *switch*, in-session revival and a restart are not
alternatives; only one of them is allowed.

#### Switching a token agent - its unit's restart, after the handover

A token agent cannot switch in-session: its session reads `CLAUDE_CODE_OAUTH_TOKEN`
once, at start, and keeps it over any sign-in (step 2), and a running process's
environment cannot be changed from outside. The new token reaches the session only
through a new process - the unit's restart, which re-reads its EnvironmentFile= and
resumes the conversation (`--continue` in the agent unit template). Its in-flight
work is protected the way a login agent's is: by the handover BEFORE the switch
(`/agent-health` steps 6 to 8), so the restart runs only once the package is written.

```
python3 "${CLAUDE_SKILL_DIR}/token_switch.py" <agent> --to <the account --accounts marks next> --package <the handover package> --why "<the limit and its reset>"
python3 "${CLAUDE_SKILL_DIR}/token_switch.py" <agent> --to <account> --no-package --why "<why>"   # a session that holds no work: its token is already dead
```

It refuses - changing nothing - unless `--facts` says `token` and names the service
manager that runs the unit, and unless the package exists. Then `pool_pick.py --take
--install-token` copies the account's token over the agent's auth file (0600,
atomic, token before lease) and moves the lease with its ledger row, and only then
does it restart THAT agent's unit on THAT manager, `restart --no-block` - it does not
wait for the start, which takes minutes (the template's 60-second pre-sleep and its
readiness wait). Exit 0 is a queued restart, never a confirmed one: step 11 of
`/agent-health` confirms the agent came back working. Exit 2 after the take says what
already moved - a system-manager unit can need privileges the reviving agent lacks,
and the JSON then names the one command a person runs. On macOS the restart is the
job's bootout and bootstrap (fleetlib.services), which stops the session supervisor
with SIGTERM so it kills the old session; never `launchctl kickstart -k`, after which
a supervisor that could not clean up is replaced by one that adopts the session still
running on the old token.

#### What a switch actually changes

Switching the Claude login changes the **token quota and nothing else**. Every other
credential the fleet uses is a file - the shared secrets store, and each agent's own
tokens under its home - and none of them is derived from or bound to the Google
account Claude is signed in with. That is what makes the pool possible: an agent
signed in with an account issued for another agent is still itself everywhere else.

#### The cases, and what each one does

| | Situation | What the procedure does |
|---|---|---|
| **Case 1** | **The pool is exhausted** - `--accounts` marks no `next` and says so | Every account is current, leased, excluded or predicted at 80%+ weekly. STOP and escalate with the soonest reset the picker's notes show, written for the person in the form `/agent` section 4 owns. Never borrow a leased account: that is two sessions on one account. |
| **Case 2** | **The leases disagree with the session** - the current account is leased to ANOTHER agent, carries no lease, or this agent also holds a lease on some other account | **STOP. Do not switch and do not edit the lease file by hand.** Either the lease file is out of date or two sessions share an account, and both are a human's call. Report which account is live and what the lease file says. `--accounts` prints the disagreement and marks no `next`. |
| **Case 3** | **/status cannot be run** (the session is blocked) | Use `--current-account`, which needs no session. See above. |
| **Case 3b** | ...and there is no recorded login either (`.claude.json` has no `oauthAccount`, or the config dir is not the one the session uses) | `--current-account` exits non-zero and says which path it tried, and `--accounts` marks no `next`. **Do not guess.** Ask the human `CONTEXT.md`'s order currently has you asking which account they last signed this agent in with; failing that, sign in with `pool_pick.py`'s answer run without `--current`, and note in the handover that the previous account was unknown. |
| **Case 4** | /status (or `--current-account`) reports an account that is **in no pool entry** | **STOP. Do not guess and do not switch.** Either the pool is out of date or the session is signed in as an account nobody put there, and both are a human's call - escalate. Report which account is live. Which agents are in this state is machine state: discover it with `--accounts`, never from a written list. |
| **Case 5** | **Which account to switch to** | The one `--accounts` marks `next`, i.e. `pool_pick.py`'s pick. Deterministic, so two operators choose the same account; never a different one because it "looks better". |
| **Case 6** | **Every account tried in this revival came back exhausted** | An account is exhausted when the sign-in *succeeds* and the first turn then fails with a usage/limit error naming that account - an auth failure is a different thing. Track which accounts you have signed in during **this** revival and pass each to the picker as `--exclude <username>`, because its ledger reading may still predict room it does not have. When the picker then names none, that is case 1. |
| **Case 7** | The /status block is still on the pane | Escape, then re-triage until the state is `healthy`. Never leave it open. |
| **Case 8** | **No pool file at all** | No account can be signed in by this procedure. STOP and escalate. |
| **Case 9** | The pool file is **malformed** (not a JSON list; an entry missing its `username`; an entry with neither a usable password - one that is missing, empty or whitespace-only is not - nor a `token_file`) | `--accounts` exits non-zero naming the defect by entry index, never by quoting the file. STOP - a guess about which account a malformed pool meant is a guess about which account signs in, and a blank password is one the sign-in driver refuses to type. |
| **Case 10** | **Duplicate usernames** in the pool | Which entry's password signs in is ambiguous. STOP and have the pool fixed. |
| **Case 11** | An account's **sign-in is known broken** (Google rejects it, an open escalation on it) | Put it on `accounts.exclude` in `config.json`, with the reason, so no pick names it; for this revival alone, `--exclude <username>`. The reason is printed beside the account in `--accounts`. |
| **Case 12** | /status and `--current-account` **disagree** | The live pane wins; `.claude.json` is only the last write. A disagreement means the file is stale or the config dir is not the session's - resolve it before switching. |
| **Case 13** | A **brand-new** account has never accepted the Consumer Terms | Expect the step 10 API 400 on its first use. That is the account being new, not the switch failing. |
| **Case 14** | A **usage-limit banner** with no running turn (`usage-cap`) | **Confirm the `banner` line is the session's own live state, not one it is displaying**, then read which limit it names AND when it resets - `tmux_triage.sh` reports every cap as `usage-cap`, so the banner is the only discriminator, and it is read before any keystroke. A **session** limit whose reset is imminent (within ~15 min) continues by itself on the same account: type NOTHING and poll the pane with a bounded until-loop to ~3 min past the reset. A **weekly** cap, or a **session** cap whose reset is hours away, follows the account and IS an expired login: same human, same fresh URL, and the account `--accounts` marks `next`. A **model-scoped** or **spend** cap does not follow the account - report it to the human as it stands rather than burning a switch on it. Use /login to reach the menu (step 3's capped route); a double Ctrl-C opens a usage dialog instead, and ANY Ctrl-C or Escape to a capped session cancels its automatic continue, after which the switch is the only way back - which is also why an imminent reset is waited out rather than typed at. If no pool account is left, that is case 1: stop and escalate with the reset time. |
| **Case 15** | The agent is **not a login agent** (`--facts` `auth` is `token`, `api-key`, `mismatch` or `unknown`) | **No browser sign-in, at any step.** A `token` agent switches with `token_switch.py` (above). A `token-invalid` pane means its token expired (one year after `claude setup-token`) or was revoked: REPORT it to the operator over the charter's channel - the agent, the account its auth file names (`--current-account`), and that a person runs `claude setup-token` for that account where a browser is, registers it (`pool_pick.py --register <account> --token-stdin`), and `token_switch.py <agent> --to <account> --no-package` installs it and restarts the session. An `api-key` agent is in no pool: a dead key goes to the operator as it stands. `mismatch` and `unknown` are a STOP with `auth_problem` as the report. Never "revive" any of them with /login. |

Carry the chosen account - and only that one - into the next step.

### 6. Sign in with the automated browser - YOU drive it, interactively

This is the PRIMARY route. It completes the whole sign-in with no human in the loop:
the driver launches a browser, and **you** take it through the flow one command at a
time, reading each page before you act on it.

> **The rule this step exists to state:** *the agent should drive the process
> interactively, and react to new unknowns, not a script.* You inspect the page's
> text and its interactive elements, decide the next action from what is actually
> there, perform it, and inspect again. Everything below that looks like a sequence
> is what to **expect and verify**, never a list of commands to replay.

**A SCRIPT OF THIS SIGN-IN FAILS ON ITS OWN MODEL OF THE FLOW RATHER THAN ON ANY
BLOCK.** Google moves the form into a popup, so an email typed and a Next clicked
**on the opener window** land on nothing, and the run stalls looking exactly like a
wall. A screen the script's model never reaches, such as Anthropic's **Authorize**
button, has no step written for it, so the run stops dead there. Neither is a block
by Google or by Claude. **A script encodes one morning's screens**; labels, element
ids and page order move, and when they move the script does not report a changed
screen, it reports a failure. An agent that looks at the page it is on survives all
of it. That is why the driver has `inspect`, `click` and `fill` and deliberately has
no `sign-in`.

#### 6a. Launch the driver - on the account's stored profile when it has one

```
node "${CLAUDE_SKILL_DIR}/signin_driver/signin.mjs" <agent> start --profile <the username chosen in step 5> --app-window
node "${CLAUDE_SKILL_DIR}/signin_driver/signin.mjs" <agent> start     # that account has no stored profile
```

**On a stored profile, start `--app-window` every time.** It makes the first window
an app window - no tabs, no address bar, no menu - and records the display, which is
what step 7's share needs and refuses to run without. A CAPTCHA at Authorize is only
discovered after the click, and a driver started without it has to be quit and
started again to share, which loses the Authorize page the person was meant to clear.

**When the account chosen in step 5 has a stored profile** ("Stored profiles"
below; `profiles-check --profile <username>` reads `absent` when it has none), start
on it. That browser is one Google and claude.ai already know, so no password is
typed: `goto` the fresh sign-in URL and the opener should land straight on
**Authorize** (6c, item 6), with its *"Logged in as &lt;account&gt;"* line. Read that
line - it must name the account chosen in step 5 - then Authorize, and continue at
6d.

**If it lands on a login page instead, the stored profile has expired.** Do not
sign in inside it: `quit`, then `start` again WITHOUT `--profile` and take the
password route below - or go to step 7e. Refreshing the profile is enrollment, which
happens off the critical path ("Stored profiles"), never inside a revival whose code
dies within the minute.

**`start --profile` exits 2 with `profile in use` when another driver holds that
profile** - a `profiles-check`, an enrollment, another revival. It is refused before
a browser is launched, because a launch on a held profile opens a stray window in
the browser holding it. Wait for that driver to quit, or take the throwaway route.

`start` prints the socket, the run dir and the log path, or fails saying the driver
never created its socket - **read that as a launch failure, never as earliness**, and
the log it names is the evidence. A driver that refused (exit 2) is reported at once,
with its own reason. It needs `node`, and on a host with no X session
`xvfb-run`, which it uses automatically (the browser must be **headful**: headless is
rejected by Google at the identifier step). If either is missing, that is the
environment lacking the route - go to step 7e.

Then, for the rest of this step:

```
S="${CLAUDE_SKILL_DIR}/signin_driver/signin.mjs"
node $S <agent> inspect --page 0       # text + every visible interactive element
node $S <agent> pages                  # which windows are open, and their urls
node $S <agent> click --role button --name "<the text you just read>" --page 1
node $S <agent> fill --label "<the label you just read>" --value "<account>" --page 1
node $S <agent> fill --label Password --secret "<the username chosen in step 5>" --page 1
node $S <agent> shot --name <slug>     # a PNG per open page, when you want one
```

**NEVER `shot` THE CALLBACK PAGE, AND NEVER OPEN A SHOT YOU TOOK NEAR IT.** A PNG
is the one channel the redaction cannot reach: the code is rendered there as ordinary
visible text, so a screenshot puts it on disk in pixels, and the natural next move -
opening the file to look at it - puts it in a transcript. The driver writes shots
mode 0600 and deletes them with the run dir on `quit`; that bounds the exposure, it
does not remove it. Use `inspect` to read a page and `savecode` to take the code.

**`--secret` takes the USERNAME, not a password.** The driver reads that
account's password out of the pool file (`accounts.pool_file`) inside its own process
and types it into the field. `--pool-file <path>` on `start` points it at another
file instead - an agent's own credential file, one `{ username, password }` object,
is read as a one-entry pool. Never put a password on a command line: a command line reaches a shell
history, a tool result and a transcript that all outlive the revival.

#### 6b. The loop

**`inspect`, decide, act, `inspect` again.** After anything that could open or close a
window, run `pages` first - it tells you which page index to act on, and an action
on the wrong one lands on a page that has left the flow.

**When `inspect` shows none of the elements you expected, take a `shot` before
concluding anything.** A CAPTCHA drawn over the page is invisible to `inspect` (6c),
so an empty or unchanged element list says nothing about what is on the screen; the
shot does. The one page never shot is the callback page, which carries the code.

**Unfamiliar screen? Read it and act on what it says.** A challenge, a new consent
page, a renamed button, a "choose an account" list, a recovery-details interstitial -
none of these is a reason to stop. The page states what it wants; `inspect` gives you
its text and its buttons; do the thing it asks and carry on. **Never skip a screen you
did not expect, and never hard-code around it.** Stop ONLY on an explicit block - a
refusal, a lockout, a verification that needs a device or a phone you do not have, a
CAPTCHA (6c) - and then record the block's exact text. A CAPTCHA on a stored profile
started `--app-window` is step 7 (tap-to-solve); every other block is step 7e.

**One challenge is EXPECTED, and it is neither a block nor a screen to guess at:
"Verify it's you".** Google interposes it after the password on some sign-ins. The
page carries that heading, a MASKED recovery address (`d{U+2022 x5}@{U+2026}`), a control reading
**Send code** or **Get a verification code** (sometimes behind a "Try another way"
list, where the email option is the one to pick), and after it a code field. It is
asking for a code sent to the account's **recovery email** - and every agent
account's recovery email is the one mailbox `recovery.mailbox` names, which the
reviving agent reads by API as that user through the delegated minter, the
google-spreadsheet skill's `gsheets.py` (`CONTEXT.md` names the mailbox). So:

1. `click` the send-code control (on the popup, as ever - re-read `pages`).
2. Read the code from the recovery mailbox - it arrives within seconds:

   ```
   code="$(python3 "${CLAUDE_SKILL_DIR}/read_recovery_code.py" --minutes 5)" || echo "no code: $?"
   ```

   It prints the code and nothing else on stdout, or exits non-zero with the reason on
   stderr (1 no fresh code from Google, 2 config, 3 mint refused, 4 Gmail API). A 1 a
   few seconds after the click is usually earliness - run it again; a 1 that persists
   past a minute means the code went somewhere else, and THAT is the block to record.
3. `fill` the code field with it, **Next**, and carry on with the loop.

The code is a plain 6-digit number and expires within minutes, so read it right after
the click and fill it right after reading it. Never `shot` this screen for the code:
`inspect` shows the masked address, and the helper is how the code is read.

#### 6c. What to expect (a worked example)

Measured on a Workspace account with no 2FA. Treat it as the shape to recognise and
confirm, not as commands to replay.

1. `goto` the FRESH sign-in URL from step 4. The claude.ai login page offers
   **"Continue with Google"**.
2. Click it. **Google opens a POPUP** (`accounts.google.com/v3/signin/identifier`,
   `display=popup`) - `pages` now shows two pages, and everything until the popup
   closes happens on **page 1**.
3. Fill the email **in the popup**, and press its **Next** - ON THE POPUP.
4. The popup moves to the password step. `fill --label Password --secret <username>`,
   then **Next**, again on the popup.

   Here Google may interpose **"Verify it's you"** with a masked recovery address and
   a send-code control. Handle it as 6b says - click send, read the code out of the
   recovery mailbox with `read_recovery_code.py`, fill it, **Next** - and the flow
   resumes at 5. When it does not appear, nothing is skipped.
5. Google shows **"You're signing back in to Claude"**. **Continue**, on the popup.
6. The popup closes and the Google-Identity-Services hand-back fires. `pages` drops
   back to one page, and the **opener** is now on `claude.ai/oauth/authorize`:
   *"Claude Code would like to connect..."*, with **Authorize** / **Decline** and a
   *"Logged in as &lt;account&gt;"* line. **Read that line** - it is the last chance to
   catch the wrong principal before the token is issued.
7. **Authorize.** The browser lands on `platform.claude.com/oauth/code/callback`
   showing *"Paste this into Claude Code: &lt;code&gt;"* - two segments joined by `#`.

**AN AUTOMATED BROWSER CAN BE SHOWN A CAPTCHA ON THE claude.ai LOGIN PAGE AND AT
AUTHORIZE, AND ONLY A `shot` SEES IT.** Two forms are measured:

- **On the login page (item 1 above)**, a picture-grid challenge - headings such as
  *"Click all incorrectly parked cars"* or *"Click all empty parking slots"* - drawn
  before "Continue with Google" can be used. Measured 2026-10-22.
- **Over the Authorize card (item 7 above)**, a drag-the-puzzle-piece challenge -
  heading *"Drag the matching puzzle piece to finish the picture"*, two draggable
  pieces on the left, a picture on the right, a language selector, a menu, a
  refresh, an accessibility icon and a **Skip** button - with the *"Logged in as
  &lt;account&gt; / Switch account"* line still visible below it.

**`inspect` does not reveal either**: the element list and the page text do not
change (at Authorize the buttons still list as Authorize / Decline). What you get
instead is a page with nothing to act on, or a click that does not advance - `pages`
keeps reporting the same url and, at Authorize, `savecode` returns `saved: false`.
**The only instrument that shows it is a `shot` of page 0**, and a shot is safe on
both pages because no code exists yet - the never-shot rule is about the callback
page, which this run has not reached. **A CAPTCHA is a hard stop for the AGENT**: do
not solve it and do not click Skip repeatedly. Record its heading verbatim and hand
it to a person: on a stored profile started `--app-window`, leave the driver exactly
where it is and go to step 7 - tap-to-solve, on this same browser; otherwise `quit`
the driver and go to step 7e with a FRESH link.

#### 6d. Take the code and paste it WITHIN THE MINUTE

```
node $S <agent> savecode
```

It writes the whole code to a mode-0600 file and prints the **path and length, never
the code**. Paste it into the agent's pane immediately:

```
code_file="<the file savecode printed>"
env -u TMUX TMUX_TMPDIR=<tmux_tmpdir> tmux send-keys -t <tmux_target> -l -- "$(cat "$code_file")"
env -u TMUX TMUX_TMPDIR=<tmux_tmpdir> tmux send-keys -t <tmux_target> Enter
```

**THE CODE EXPIRES IN ABOUT A MINUTE, AND AN EXPIRED ONE FAILS AS SOMETHING ELSE.**
Measured: a code pasted 49 minutes after it is produced returns `OAuth error:
Request failed with status code 400`; one pasted 17 seconds after it is produced
logs in. **A 400 after a paste is almost always a stale code, not a bad
one** - and the tempting reading is that the account, the URL or the whole route is
broken, which sends the next hour in the wrong direction. **Never park a code**: do
not save it for later, do not put it in a message, do not finish reading the page
first. `savecode` succeeding is the signal to paste, now.

**`savecode` PRINTS ITS JSON AFTER THE DRIVER'S LOG LINES, so a caller that pipes
the WHOLE output into a JSON parser gets nothing - and then never pastes.** Measured:
the stdout carries driver log text first and the `{"saved": true, "path": ...}` object
last, so `savecode | jq -r .path` fails on the first line and the code sits on disk
until it expires. **The file is always `<run-dir>/code.txt`** - the run dir is what
`start` printed as `run_dir` - so when the parse fails, paste from that path directly
rather than re-running `savecode` to get a cleaner print:

```
code_file="<run_dir from start>/code.txt"
```

The minute still runs while you sort this out; the path is fixed so that nothing
has to be parsed to find it.

#### 6e. Then quit the driver

```
node $S <agent> quit
```

**This is not tidiness.** A throwaway profile holds live Google and claude.ai
sessions for the pool account it signed in - a credential in everything but name, and
so do any screenshots you took. `quit` deletes the whole run dir, the throwaway
profile inside it, and so does an ordinary crash or a Ctrl-C; **a SIGKILL or a reboot
cannot be covered by anything**, so after one, remove the run dir by hand. A STORED
profile is outside the run dir and `quit` keeps it - that is what it is for - and
`quit` is also what writes its session to disk, so end every stored-profile run with
it rather than a kill. The driver's own log lives OUTSIDE the run dir (it has to
survive a launch failure, which is the one thing it is for) and `quit` does not
remove it.

Then continue with step 8 (the code is already pasted, so read that step for what
comes back), and steps 9-12 as written.

### 7. The human step: tap-to-solve

**When a CAPTCHA stops step 6, a person solves the puzzle on the agent's own browser,
and signs nothing in.** The driver is already on the account's stored profile, at
Authorize, with the right *"Logged in as"* line; what it cannot do is the puzzle (6c).
So it shares that one window: a public link, a one-time password, and a view in which
the person can move the pointer and LEFT-click - a left-drag included, which is what
the puzzle takes - and nothing else. They never see the account's password, the
window has no address bar, and the share tears itself down.

**Use it whenever the driver runs on a stored profile started `--app-window` (6a).**
Step 7e, the person signing in in their own browser, is the fallback for when the
share cannot run - and only then.

The order, every time:

```
S="${CLAUDE_SKILL_DIR}/signin_driver/signin.mjs"
node $S <agent> start --profile <the username chosen in step 5> --app-window   # 1 (6a)
node $S <agent> goto "<the FRESH sign-in URL from step 4>"                     # 2
node $S <agent> inspect                                                         # read "Logged in as" (6c, item 6)
node $S <agent> click --role button --name Authorize                            # 3
node $S <agent> savecode                     # saved: true - no CAPTCHA; paste NOW (6d), and no person is needed
node $S <agent> shot --name authorize        # saved: false - look before asking anyone (6c: inspect cannot see it)
node $S <agent> share                        # 4 - only when no code appeared
#   post the URL and the one-time password in ONE message (7b); on their "done":
node $S <agent> savecode                     # 5 - then paste within the minute (6d)
node $S <agent> unshare
```

#### 7a. What `share` does, and what it refuses

It starts `x11vnc` on the driver's own virtual display (127.0.0.1 only, a fresh
8-character password in a mode-0600 file), `websockify` serving noVNC in front of
it (127.0.0.1 only), and a Tailscale Funnel on the configured funnel port (`share.*` in
`config.json`), and prints ONE JSON object:

```
{ "ok": true, "shared": true, "url": "https://<this host's Tailscale name>:<funnel port>/vnc.html?...",
  "password_file": "<run dir>/vnc.pass", "expires_at": "<ISO time>", "minutes": 10, "input": "..." }
```

- **It never prints the password** - only the FILE. The password is read by the
  process that posts it (7b) and by nothing else.
- **The input is restricted on the server**, by `x11vnc`'s own flags
  (`signin_driver/share.mjs` names each one and what it closes): pointer motion and
  the left button reach the browser; a right, middle, wheel or side click, every key,
  the clipboard in either direction, and a remote-control request to widen any of it
  do not. `share.test.mjs` proves it against a control server that delivers all of
  them. **One viewer at a time**: a second connection replaces the first, so the
  person's reconnect works and nobody watches beside them.
- **The window has no address bar**: `--app-window` makes it an app window, and a
  Google sign-in popup opened from it has none either. **A link with
  `target=_blank` opens a normal tabbed window**, and its menu answers a left click -
  no URL can be typed into it, but its menus, settings and new-tab page are a
  click away. `share` refuses while any second window is open; while a share is live,
  a second window in `pages` is a reason to `unshare` at once.
- **It expires on its own**: a detached timer tears the whole share down at
  `--minutes` (default `share.minutes`). That timer is the safety net; `unshare` the
  moment the code is pasted is the plan.
- **It refuses** (exit 2) a driver not started `--app-window` - quit it and start
  again with it - a display other than the Xvfb the driver's own `xvfb-run` started,
  because a share shows the WHOLE display, and a driver with more than one window
  open; and (exit 1) while another share is live or being set up on this host, or its
  ports are taken. Two shares started at once on one host: exactly one wins, and the
  other takes nothing of the winner's with it. A failure half-way is torn down before
  it exits, and says what failed.
- **Nothing is shared unless `share` is run.** No other command, and no start flag,
  makes anything public.

#### 7b. The ask: ONE message, with the password read inside the posting process

`CONTEXT.md` names WHO to ask and in what order; send to the person it currently has
you asking, over the channel the charter names, ONE message carrying the share's URL
and its one-time password, and these instructions: *open the link, enter the
password, solve the puzzle by dragging or tapping (only the mouse, or a finger,
works), and reply "done".*

**The password goes from its file into the message inside the posting process,
and nowhere else.** Never `cat` it, never put it on a command line, never echo it
into a variable you print. Post through the install's chat transport (`/chat-transport`
names it and its *Post* recipe). A post API may ECHO the message text in its response
- Slack's `chat.postMessage` does - so printing the response prints the password:
print only the fields you need. For the Slack transport:

```
jq -n --arg ch "<channel id>" --arg url "<url from share>" --rawfile pw "<password_file from share>" \
  '{channel: $ch, text: ("<@person> tap-to-solve for <agent>: " + $url + "  password: " + ($pw | rtrimstr("\n")) + "  - solve the puzzle, then reply done")}' \
| curl -sS -X POST https://slack.com/api/chat.postMessage -H "Authorization: Bearer $TOKEN" \
    -H 'Content-type: application/json; charset=utf-8' --data @- | jq '{ok, ts, error}'
```

(`$TOKEN` and the channel are the posting bot's, per `/slack-communication` and the
charter.)

#### 7c. Take the code, paste it, take the share down

The code exists the moment the puzzle is solved, and its minute (6d) starts then -
not when the person's "done" reaches you. **So run `savecode` while you wait as well**,
every few seconds; the first `saved: true` is the signal, whichever comes first. If
the page is still Authorize after the puzzle, with the button enabled, `click` it.
Paste exactly as 6d says, then `unshare`, then `quit` and continue as 6e says.

`unshare` turns the funnel port off FIRST and confirms it from Tailscale's own
status, then kills the share's processes, deletes the password file, and prints what
it did. It is safe to repeat. `quit`, and every exit the driver can observe (a crash,
a signal), tear the share down too.

**A teardown that cannot finish keeps the share's record - and says so.** `unshare`
exits 1 with `clean: false` and the reason (a funnel that would not turn off, a
process that would not die); the record stays in the run dir and the expiry timer
stays armed, because they are the only things that still know the share exists. A
`quit` in that state removes everything in the run dir but the record and its log,
and the next `start` on that run dir refuses until `unshare` has cleared it. Read
what it reports, fix that, and `unshare` again - and if the funnel itself will not
turn off, `<share.tailscale> funnel --https=<funnel port> off` by hand, then check
`funnel status`.

**After a SIGKILL nothing in the driver runs**, and the share outlives it until its
timer. `unshare`, or the next `start` on that run dir, tears it down - so never
remove a run dir by hand before one of them has run: the share's only record is in
it.

#### 7d. When it lapses, and when the order moves on

A share that expires unanswered is gone, password and all. Asking again - the same
person, or the next one in `CONTEXT.md`'s order - is a NEW `share`, with a new
password; never re-send the old one. The sign-in link inside the driver can be stale
by then too: regenerate it (step 3), `goto` it, Authorize, and share again - never
while a person may still be mid-puzzle on the old one, because a new link kills every
code from the old (Traps).

The `--port` DevTools route ("Stored profiles") is for ENROLLMENT, not for this step,
and is offered only to the designated owner `CONTEXT.md` names, on request: it reaches
the browser through an ssh login to this host. Everyone else, at enrollment too, gets
this share.

#### 7e. FALLBACK: sign in via a REAL browser

**Use this only when tap-to-solve cannot run, or step 6 has stopped at a block no
puzzle explains**, i.e. one of:

- the chosen account has no stored profile, or its stored profile has expired (6a),
  so there is no signed-in browser to share;
- `share` refuses or fails - `x11vnc`, `websockify` or noVNC missing, the Funnel not
  allowed or not reachable (`installation/check` names the leg) - which you record
  verbatim;
- the host has no `node` or no `xvfb-run` (and no `DISPLAY`), so there is no browser
  to drive;
- the driver reports an explicit block - a refusal, a lockout, a 2-step verification
  that needs a device or a phone, "This browser or app may not be secure" - which you
  record verbatim, because it is the only evidence that distinguishes a real block
  from a screen nobody read. **"Verify it's you" with a masked EMAIL address is
  not on this list**: that code goes to the recovery mailbox the reviving agent reads
  itself (6b); falling back on it hands a human a challenge the agent could have
  answered;
- there is no usable pool account (SKILL.md step 5, cases 1, 8, 9 and 10), in which
  case a human cannot sign it in either and the answer is an escalation, not this
  step.

**A screen you did not expect is NOT a block.** Falling back on one costs a human
a round trip and teaches the next reviver that the automated route "doesn't work",
which is how a working route dies. Read the screen, act on what it says, and fall
back only on the list above.

A human then does it in a real browser. **`CONTEXT.md` names WHO to ask, and in what
order when it names more than one** - read it before sending anything, and follow its
hand-off rules verbatim rather than from memory. Send the person it currently has you
asking - **and only that person, over the channel the charter names** - a message
carrying:

- the FRESH sign-in URL from step 4,
- the username and password of **the account chosen in step 5** - one entry, never
  the whole file - read from the pool file (`accounts.pool_file`) for this message
  and nowhere else, never with a `cat` onto a pane, and
- these instructions: *start a new Chrome window in INCOGNITO MODE; open the link;
  choose "Continue with Google"; sign in with the username and password above;
  click Continue / accept the consent; the Claude callback page then shows a CODE;
  send back the WHOLE code.*

**The credentials are the chosen POOL account's, never the operator's or the
human's own.** Any pool account is a valid Claude login for any agent; an account
from outside the pool is not, and neither is a second account the person happens to
hold.

**Incognito matters:** a clean profile avoids a human's own Google session
hijacking the flow, and leaves nothing behind afterwards.

**The human can hit the same "Verify it's you" challenge, and the code still goes
to the recovery mailbox - which the human cannot see and the reviving agent can.**
Tell them in the same message: *if Google asks you to verify with a code sent to a
masked email address, choose that option, press send, and tell me - I will send you
the code.* When they do, read it with `read_recovery_code.py` (6b) and DM it to them
at once; it expires within minutes. The human types it, and the flow continues to the
Claude callback page as above. This is the one part of the human route the reviving
agent still performs.

**The code is the WHOLE string, including a trailing `#...` part.** It has two
segments joined by `#` (the authorization code and a verifier); dropping the `#...`
tail makes the paste fail. Take the entire string the human sends back.

### 8. Paste the code back

Paste the whole code LITERALLY (it contains `#` and other characters a shell or tmux
would otherwise interpret), then Enter:

```
env -u TMUX TMUX_TMPDIR=<tmux_tmpdir> tmux send-keys -t <tmux_target> -l -- "<the whole code with #...>"
env -u TMUX TMUX_TMPDIR=<tmux_tmpdir> tmux send-keys -t <tmux_target> Enter
```

### 9. Clear the post-login prompts

`Login successful` appears, then a run of prompts. Send `Enter` through the security
notes. On a FRESH login you then get, in order:

- **Theme prompt** - choose the **dark, colour-blind-friendly** theme (worded like
  *"Dark mode (colorblind-friendly)"*).
- **Scroll-behaviour prompt** - choose the mode where the **mouse wheel scrolls the
  terminal**, NOT the mode that makes the wheel send up/down arrow keys.
- **Session-resume prompt** - choose **"Resume from summary"**.

Navigate all of these by the option TEXT, not by position; ordering is not
guaranteed across Claude Code versions. And do not send a bare Enter into a pane you
have not just read: a first-run trust-folder dialog preselects *"No, exit"*, and a
stray Enter terminates the session rather than answering it. Read, then send.

### 10. If the first turn throws an API 400 about the Consumer Terms

A freshly-authenticated account can fail its first API call with
`API 400 ... "accept the updated Consumer Terms and Privacy Policy in claude.ai
with <email>"`. The fix is accepting the updated Terms on claude.ai, signed in as the
AGENT'S account, in the browser the sign-in happened in: on steps 6 and 7 that is the
driver on the account's stored profile - `goto` claude.ai, `inspect`, accept - and on
step 7e it is the human, in the SAME incognito session. The agent then runs. This is
per account and usually once.

### 11. Nudge the agent back to work

**After a sign-in the agent is authenticated but IDLE, and a ready `{U+276F}` prompt is
not the same thing as an agent that is working.** Reviving inside the existing
session does NOT re-run the service unit's `ExecStartPost`, which is what normally
gives the agent its first turn. So give it one by hand.

**Which nudge depends on whether the session kept its context, and getting this
backwards is destructive - so decide it explicitly rather than by habit:**

| The session | Send | Why |
|---|---|---|
| **Lost its context** - a fresh revival, a restart, a resumed-from-summary session that has no in-flight work | the agent's **bootstrap prompt** | It has to start its day: arm its monitors, pick up standing duties. That is what the prompt says. |
| **Survived** - an account switch (step 5), where the point is that the session and its in-flight work live through it | exactly `keep going` | It already HAS its context and half-finished work. A bootstrap prompt tells it to start over, which throws that work away - the precise thing the in-session switch exists to protect. |
| **Restarted for a token switch** (`token_switch.py`) | nothing until the unit's own boot message has run, then `/agent-health` step 10's resume message | The restart re-ran `ExecStartPost`, which types the boot message itself once the session is ready, and `--continue` resumed the conversation; its subagents and monitors are gone, which is what the handover package is for. A second bootstrap prompt would duplicate the boot message. |

For the bootstrap case:

- Read the agent's service unit (`fleet.systemd_unit` resolved for `<agent>`) and
  take the bootstrap prompt string its `ExecStartPost` sends via `tmux send-keys` -
  the long quoted argument, not the bare `Enter` that follows it. `tmux_triage.sh
  <agent> --bootstrap-prompt` prints exactly that string, read from the live unit,
  so the per-agent wording is never hardcoded here.
- Paste it literally, then Enter:

```
prompt="$("${CLAUDE_SKILL_DIR}/tmux_triage.sh" <agent> --bootstrap-prompt)"
env -u TMUX TMUX_TMPDIR=<tmux_tmpdir> tmux send-keys -t <tmux_target> -l -- "$prompt"
env -u TMUX TMUX_TMPDIR=<tmux_tmpdir> tmux send-keys -t <tmux_target> Enter
```

For the surviving-session case, the same two calls with the literal string
`keep going` in place of `$prompt`.

**Then confirm it is actually PROCESSING, not merely ready.** Re-capture the pane a
few seconds later: a working agent shows a running turn (a spinner, a tool line, an
`esc to interrupt` hint), not a bare prompt. If it is still sitting idle, send
`keep going` - that is the whole remedy, and it is safe to repeat.

**This step is only for reviving WITHIN an existing session.** A full restart of
the agent's unit re-runs `ExecStartPost` itself and injects the bootstrap prompt for
you - but it drops the resumed session context, which is why in-session revival
exists at all, and why a restart is **forbidden** as a way to switch a login agent's
account (step 5). A token agent is the one exception, because its token reaches it no
other way (step 5, "Switching a token agent").

### 12. Verify and disconnect

Confirm the agent is back at its ready `{U+276F}` input prompt and responding
(`tmux_triage.sh <agent>` reports `healthy`). Then detach - `Ctrl-b d` if attached;
do not kill the session. The agent keeps running.

---

## Stored profiles: enrolling and refreshing one

A **stored profile** is one pool account's signed-in Chromium profile, kept at
`<accounts.profiles_dir>/<username>` (`CONTEXT.md` names the directory for this
install). With one, step 6 opens a browser Google and claude.ai already know: no
password is typed and Authorize is the only click left. Without one, step 6 runs on a
throwaway profile and signs in with the password.

**A stored profile is a CREDENTIAL.** It holds live Google and claude.ai sessions
for its account, and its cookies are encrypted with Chromium's fixed built-in key
rather than a keyring, so anyone who can read the directory can sign in as that
account. The driver keeps the profiles dir and each profile mode 0700, re-set on
every start, and refuses an `accounts.profiles_dir` that resolves into a git work
tree or under an agents home. Never copy a profile, never read its files, and never
keep one anywhere else. A profile is named after a pool account; when an account
leaves the pool, its profile directory is deleted with it.

**Its state, read-only** (`$S` is the client, as in 6a):

```
node $S profiles-check [--profile <username>]
```

One JSON object: per profile, `claude` and `google`, each `in`, `out` or `unknown`,
read from where `https://claude.ai/` and `https://myaccount.google.com/` land - or a
`status` of `busy` (another driver holds it), `absent` or `error`. It types nothing
and clicks nothing, and an absent profile is reported, never created. **`unknown`
is not `in`** - an interstitial or a landing nobody has mapped - and even `in` is a
reading, not a sign-in: the test of a profile is step 6a landing on Authorize.

**Enrolling one** - the first time, or as a refresh once `profiles-check` reads `out`
or step 6a found the profile expired. **Off the critical path, always**: never
while an agent waits on a code, because enrollment takes a person's minutes and a
code dies in one. The agent signs in; a person clears only what the agent cannot (a
CAPTCHA, a device prompt). **The person reaches the browser through the step 7 share,
whoever they are.** The `--port` DevTools route is an ssh login to this host, so it is
offered only to the designated owner `CONTEXT.md` names, and only when they ask for it.

1. `node $S <agent> start --profile <username> --app-window` - `--app-window`, because
   `share` refuses without it (7a).
2. `node $S <agent> goto https://claude.ai/login?reauth=1`. **`reauth=1`, not the
   bare login page**: a profile whose claude.ai session still opens the app redirects
   /login straight to it, while the OAuth sign-in a revival needs can demand a fresh
   login from the same profile. `reauth=1` forces that fresh login, and the fresh login
   is what renews the profile.
3. Sign in exactly as step 6 does - `inspect`, Continue with Google, the popup (the
   account chooser, or the email and `fill --secret <username>` for the password), the
   recovery-mailbox code for "Verify it's you" (6b). **If Chromium offers to save the
   password, decline it**: a saved password sits in the profile under the same fixed
   key as the cookies, and outlives every session in it.
4. **At a CAPTCHA, `share` and ask** exactly as 7a-7b do: one message with the link and
   the one-time password, to the person, and `unshare` the moment the page moves on. A
   share that lapses is a new `share` with a new password (7d). The password is typed
   from the pool, so the person never needs it.
5. When claude.ai shows its signed-in app, `unshare` if a share is still up, then
   `quit`. The profile is kept, and the clean close is what writes its session to disk.
6. `node $S profiles-check --profile <username>`: `in` at both sites, or `unknown` -
   then start on it again and `inspect` what claude.ai shows.

**The designated owner's DevTools route**, on request: `start --profile <username>
--port <N>` (`N` a free port from 1024) instead of step 1. The reply carries
`port_answers` and `person_steps`: the ssh tunnel `ssh -L N:127.0.0.1:N
<login>@<this host's Tailscale name>` - read from `tailscale status`, because a laptop
resolves this host by that name - then in desktop Chrome `chrome://inspect`, Configure
`localhost:N`, inspect the page target and, once it opens, the Google popup's target
too. While the driver runs, every local process can reach that port; quit as soon as
the profile is signed in. A driver started with `--port` and not `--app-window`
cannot be shared: switching that person to the share is a `quit` and a new step 1.

A refresh is the same steps on the existing profile: `start --profile` opens it as it
stands, and signing in again inside it renews its sessions.

## The GIS hand-back, and what the browser configuration has to be

An automated browser completes the Google half of this sign-in and the hand-back that
follows it, and step 6 is the route that does it. What the configuration has to be is
narrow, and the two things that do not work are worth knowing so nobody widens it by
accident. **The hand-back is not where automation stops.** Where the automated route
can end instead is at Anthropic's own CAPTCHA - a picture grid on the claude.ai
login page, or a puzzle over the Authorize card (step 6c) - an explicit block, and
step 7 from there.

**What is measured to work** (one configuration, driven interactively, producing a
pasted code and a signed-in agent):

- **stealth + headful + a virtual display.** `playwright-extra` with
  `puppeteer-extra-plugin-stealth`, Chromium launched `headless: false` under
  `xvfb-run -a` on a host with no X session, a fresh persistent profile.
- **The popup-to-opener hand-back fires.** Google Identity Services completes the
  sign-in in a popup and hands the result back to the opener; in this configuration
  the opener does advance, to `claude.ai/oauth/authorize`, carrying a *"Logged in as
  &lt;account&gt;"* line and the Authorize / Decline buttons. Authorize then either yields
  the code on `platform.claude.com/oauth/code/callback` or is covered by a puzzle
  CAPTCHA (step 6c), which is where the automated route ends - as it does at a
  picture CAPTCHA on the login page, before Google is reached.
- **No 2-step prompt, no "This browser or app may not be secure", no ban**, on a
  Workspace account with no 2FA.

**Headless is shut.** Google rejects a headless browser at the identifier step
(*"This browser or app may not be secure"*). Headful is not a preference here: it is
the requirement, and a virtual display is what satisfies it on a server.

**A SCRIPT THAT IS WRONG ABOUT THE FLOW LOOKS LIKE A WALL.** Clicking Next on the
opener while the form is in the popup, or stopping at Anthropic's Authorize because
the script's model of the flow never reaches that screen, presents identically to a
real block - a page that does not advance, no code - so the conclusion "the
automated browser cannot do this" is always available and usually wrong. **A page
that will not advance is a hypothesis about the page, not a verdict about the
route:** `inspect` it before concluding anything.

**These measurements cover the one configuration above, the one step 6 uses.** A
headed run without stealth, a headless run, or the stealth plugin under different
settings is a configuration this section does not cover, and a reading from one is
not evidence about the route.

---

## Measured

- An agent idle after an API 529, with no daemons running, reads `healthy`: the
  pane alone cannot distinguish it from a quiet hour (measured 2026-10-03).
- An agent whose login has expired - every turn ending on
  `Login expired {U+00B7} Please run /login` at a ready prompt, both daemons running - reads
  `healthy`, and no sign-in URL is printed in that state (measured 2026-10-22).

---

## Traps

- **A SCRIPT'S MODEL OF THE FLOW IS WHAT BREAKS - DRIVE IT INSTEAD** (step 6).
  A script of this sign-in fails by being wrong about the screens, not by being
  blocked, and a wrong model presents exactly like a block: a page that will not advance and no code. `inspect` the page before
  concluding anything about the route, and act on what the page says rather than on
  what the sequence expected. The corollary is that **a screen you did not expect is
  not a reason to fall back** - it is a screen to read.
- **claude.ai CAN SHOW A CAPTCHA ON THE LOGIN PAGE (a picture grid: "Click all
  incorrectly parked cars") AND OVER AUTHORIZE (a puzzle), AND `inspect` IS BLIND TO
  BOTH** (step 6c). The symptom is a page with nothing to act on or a click that does
  not advance, while the element list and the page text do not change. **When
  `inspect` shows no expected element, take a `shot` before concluding anything**; it
  is the only instrument that shows the challenge, and it is safe on both pages
  because no code exists yet (the callback page is still never shot). A CAPTCHA is a
  hard stop for the AGENT - do not solve it, do not click Skip repeatedly; record the
  heading verbatim and hand it to a person: on a stored profile started
  `--app-window`, keep the driver where it is and share it (step 7); otherwise quit it
  and go to step 7e with a FRESH link.
- **A SHARE IS PUBLIC UNTIL IT IS TAKEN DOWN** (step 7). `unshare` the moment the
  code is pasted; the expiry timer is the net, not the plan. After a SIGKILL of the
  driver the share outlives it, and its only record is in the run dir - so `unshare`
  (or `start` again on that run dir) before anything removes that dir by hand.
- **`chat.postMessage` ECHOES THE MESSAGE TEXT IN ITS RESPONSE** (step 7b). The
  tap-to-solve ask carries the one-time password, so printing the response prints the
  password into a tool result and a transcript. Print `{ok, ts, error}` and nothing
  else, and read the password from its file inside the posting process.
- **ON TAP-TO-SOLVE THE CODE'S MINUTE STARTS AT THE PUZZLE, NOT AT THE PERSON'S
  "DONE"** (step 7c). Waiting for the message before `savecode` spends the minute on
  their typing and your watcher's poll; run `savecode` while you wait.
- **"VERIFY IT'S YOU" IS AN EXPECTED SCREEN, NOT A BLOCK** (step 6b, step 7e).
  Google sends its code to the account's RECOVERY EMAIL, which is the one mailbox
  the reviving agent reads by API through the delegated minter
  (`read_recovery_code.py`; `recovery.mailbox` in `config.json`, and the
  google-spreadsheet skill's minter). Click send, read, fill, continue - and on the human route, read it
  and send it to the human. Only a challenge that names a PHONE or a DEVICE is a
  block.
- **`savecode` PRINTS ITS JSON AFTER DRIVER LOG LINES** (step 6d). Piping the whole
  output into a JSON parser yields nothing and the code is never pasted. The file is
  always `<run-dir>/code.txt`; paste from that path when the parse fails - the code
  still expires within the minute.
- **THE CODE EXPIRES WITHIN ABOUT A MINUTE, AND A STALE ONE FAILS AS
  `OAuth error: Request failed with status code 400`** (step 6d). Measured: pasted
  49 minutes after it is written -> 400; pasted 17 seconds after -> logged in. The
  400 is easily read as a bad account, a bad URL or a broken route, which sends the
  next hour the wrong way. **Never park a code**: the moment `savecode` succeeds, the
  paste is the next thing you do.
- **A CAPPED SESSION MOVED INTO A LOGIN FLOW LOSES ITS OWN AUTOMATIC CONTINUE.**
  Once /login has been sent, the session's recovery at the reset time no longer
  fires: measured, a capped agent left at a Paste-code prompt past its reset time
  does not continue. **After a revive is started, only a code finishes it.** So do not
  start one half-heartedly on a cap you were planning to let expire: the fallback you
  were relying on is gone the moment you type.
- **The "How is Claude doing this session?" survey prompt is a harmless IDLE
  state.** `1: Bad 2: Fine 3: Good 0: Dismiss`, drawn over the input. It is not a
  revival case: send `0` to dismiss it and re-triage. `tmux_triage.sh` classifies it
  as `survey-prompt`, so it never reads `unknown`, the state that sends a human to
  look at an agent that is perfectly fine.
- **The displayed URL is usually stale.** Always regenerate a fresh one (step 3)
  rather than trusting what is already on the pane, and every send to a human carries
  a newly regenerated one - a hand-off to the next person and a re-send to the same
  person alike.
- **REGENERATING INVALIDATES EVERY CODE FROM THE PREVIOUS URL, so WHEN you
  regenerate is as load-bearing as THAT you do.** Each /login mints a new PKCE
  verifier, so a new link kills every code from the one before it: the person acting on
  the older link pastes a code that fails `OAuth error: Request failed with status code
  400`, and the pane then needs Escape, /login and yet another link - costing that
  person a round trip for a mistake that was not theirs. **A link once
  posted to a person is LEFT ALONE until that person answers or their window lapses.**
  A re-send replaces it only after telling them the old one is dead, and never while a
  code from them may already be in flight. This is the same rule as the bullet above,
  with its sequencing: one live link at a time, regenerated at the moment it is sent
  and not before.
- **A wrapped URL is truncated by a naive grep.** Use `tmux_triage.sh`'s joined
  `signin_url` (step 4); a truncated OAuth URL fails silently.
- **/login + Enter from a ready prompt is the ONE route to the login menu.** A
  double Ctrl-C is a route on no pane: at the ready prompt it opens the EXIT dialog
  with "Exit and stop tasks" preselected, and on a `Paste code here` prompt it QUITS
  Claude Code (measured 2026-10-22). A non-capped paste-code prompt is left with one
  Escape (`Login interrupted`, back at the ready prompt) before /login; a CAPPED or
  capped-origin one gets /login directly and never Escape (step 3). Confirm the
  `auth-method` state before sending Enter.
- **Send Enter on option 1 only** - option 2 is the metered API path. Never arrow
  down.
- **Paste the WHOLE code including the `#...` tail**, literally (`send-keys -l -- "<text>"`; the `--` keeps text starting with `-` or `/` from being read as tmux options).
- **$TMUX beats $TMUX_TMPDIR** - drop `$TMUX` on every hand-run tmux call.
- **A bare Enter can KILL a session** (the trust-folder dialog's default is *"No,
  exit"*). Triage before sending keys.
- **After in-session revival the agent is idle until you nudge it** (step 11), and
  **a ready prompt is not a working agent** - confirm it is processing turns, and send
  `keep going` if it is not.
- **Bootstrap prompt for a session that LOST its context; `keep going` for one that
  survived** (step 11). A bootstrap prompt sent to a surviving session tells it to
  start its day over and throws its in-flight work away.
- **Restarting the agent's unit is forbidden as a way to SWITCH a login agent's
  account** (step 5): it drops the session context and kills in-flight subagents,
  which is exactly what the switch was protecting. A token agent switches ONLY by
  that restart, through `token_switch.py`, after its handover package is written.
- **NEVER /login A TOKEN OR API-KEY AGENT** (step 2, case 15). Its session keeps the
  token its environment gave it over any sign-in, so the browser route changes
  nothing while everything around it records a switch or a revival. A dead token is
  `token-invalid`, and it is REPORTED: a person mints a new one with `claude
  setup-token`. Read `auth` (`--facts`) before the first keystroke; an unreadable
  unit is `unknown`, never `login`.
- **The agent's unit can be on either service manager.** The fleet's template is a
  user unit (`systemctl --user`); its system form runs under the system manager. On
  macOS it is a launchd job in the user's gui domain (or the system domain).
  `--facts` reads the user manager first and names the one that answered
  (`unit_scope`); a restart goes to that manager and no other.
- **A protected Mac agent is token-only.** With an administrator a macOS agent's
  session is a LaunchDaemon (`unit_manager` launchd, `unit_scope` system), which has
  no window server and no login Keychain, so it signs in only with a token or an
  API key: its switch is `token_switch.py` (step 5, a token agent), a dead token is
  reported (case 15), and neither /login nor the sign-in driver (steps 3 and 6) is
  ever offered for it. `--facts` reports such a unit set to `login` as auth
  `unknown`, exit 1, naming why. The no-admin form, a LaunchAgent in the agents
  user's own GUI session, signs in like a Linux agent, and is UNPROTECTED.
- **Never `cat` the pool file** - it holds every account's password. Use
  `--accounts`, which prints usernames and never passwords (step 5). The same for a
  token file and an agent's auth file: `pool_pick.py` is the only thing that opens
  them, and an account enters the pool only through `--register`, which reads its
  credential from standard input.
- **/status cannot run on a blocked session**; `--current-account` reads the
  account with no session at all (step 5). And **dismiss the /status block with
  Escape** once read - a modal left open reads as a stuck agent.
- **A current account that is in no pool entry is a STOP and an escalation, not a
  guess** (step 5, case 4), and so is **a lease file that disagrees with the
  session** (case 2) - never corrected by hand.
- **A usage cap is READ before it is acted on** (step 5, case 14).
  `tmux_triage.sh` reports every cap as `usage-cap`, so the banner text and its reset
  time are the discriminator. A **session** limit resetting within ~15 min continues
  by itself: type nothing and poll the pane to ~3 min past the reset. A **weekly**
  cap, or a session cap whose reset is hours away, is an expired login - a human, a
  fresh URL and the account `--accounts` marks `next`. Only a session or weekly cap follows
  the account at all.
- **Send neither Ctrl-C nor Escape to a CAPPED session.** A double Ctrl-C there
  opens a usage dialog rather than the login menu, and Ctrl-C cancels the session's
  automatic continue at the reset time; the capped status line reads `esc to cancel`,
  so Escape does the same. Either way the fallback is gone and the account switch is
  the only way back. Use /login (step 3).
- **`usage-cap` is a trigger to LOOK.** The banner may be text the session is
  displaying rather than its own state. Confirm it before typing (step 2).
- **One account is live in one session at a time** (step 5). A leased account is
  never a switch target, and the lease moves only through `pool_pick.py --take`,
  taken once the new sign-in has succeeded - two agents on one account drain it at
  twice the rate and make both agents' usage readings meaningless. The one
  exception is a SHARED lease, and only with fewer accounts than agents: joined
  with `--share`, named in the lease, read once per sweep, handed over as a group,
  and reported by `--shares` and `fleet status` (step 5).
- **The switch target is the pool picker's pick, not a judgement call** (step 5,
  case 5). It is deterministic so two operators choose the same account; a pool is
  never "out of accounts" until the picker says it is exhausted (case 1).
- **Credentials go to the person `CONTEXT.md`'s order currently has you asking, and
  to nobody else**, over the charter's channel, one entry and not the whole file, and
  are never logged - and only on the fallback (step 7e): tap-to-solve carries none. Where that order hands off to the next person, the hand-off carries
  a FRESH URL and the SAME account (step 4, step 5).
