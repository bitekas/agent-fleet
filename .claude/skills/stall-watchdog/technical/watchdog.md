# How the stall watchdog works

`SKILL.md` beside this is the installation procedure. This file is the mechanism:
what it does, why it is shaped this way, and what goes wrong when it is not.

Read sections 1 to 3 before installing it anywhere. They are the safety argument,
and they are the reason it only ever answers no.

Terminal glyphs quoted here are written as Python escapes inside backticks, so this
file stays ASCII and a quotation still pastes into a `re.search` exactly: `\u276f` is
the chooser cursor, `\u23f5` the status-bar arrow, `\u00b7` the footer separator,
`\u25cf` the activity dot. The bytes themselves are in `fixtures/`, which are
byte-exact captures.

---

## 1. The failure it exists for

An unattended session has nobody at the terminal. Some confirmation prompts cannot
be suppressed by any permission setting, and when one appears the tool call blocks
**forever**.

A blocked session is **invisible**. Its background watchers keep running and keep
accepting inbound messages, so from outside it is indistinguishable from an agent
that is deliberately ignoring you.

Such a prompt appears even in a session started with
`--dangerously-skip-permissions`: the captured `Dangerous rm operation on
possibly-empty variable path` prompt (section 5) sits on a pane whose status line
reads `\u23f5\u23f5 bypass permissions on`, and the session stays silent until someone
answers it. Section 5 has what trips that guard, measured and dated. The design does
not rest on it: the watchdog's subject is a blocking prompt nobody is present to
answer, of which the `rm` guard is one instance.

**No permission setting fixes this.** `settings.json` `permissions.allow` shapes
the baseline mode and has no effect on such a guard. Avoiding the trigger is worth
doing and cannot be relied on - it only ever addresses the last trigger, never the
next one.

## 2. It always answers no

**There is no approve path, and there must never be one.** Auto-approving would
defeat a guard that exists for a reason, unsupervised, which is the worst available
combination. `watchdog.test.py` asserts the absence of any approve key in the
config so it cannot be added quietly; that check goes red against a config
carrying an `approve_key`.

Answering **no** preserves the guard exactly - the dangerous command does not run -
while changing the failure from *fatal and silent* into *a refused tool call the
agent can see and route around*. A refusal is recoverable; a hang is not. That
trade is the whole design.

**And it says so.** The injected notice states plainly that the refusal was
mechanical and that the watchdog has no idea whether no was correct. This is not
politeness: an agent that believes a considered judgement was made on its behalf
will accept it and move on, when the entire point is that it should re-examine the
command.

**Taught prompts (`stall.known_prompts`) are the one narrower exception**, and they
are a different class: non-permission dialogs that block start-up, where the
correct answer is a deployment decision somebody has actually made. Refusing is
safe because it is uninformed; **choosing is not**, so an entry needs certainty and
a `match` specific enough that it cannot fire on a similar-looking prompt. There is
still no approve entry for a permission prompt, and there must never be one.

## 3. Two conditions, both required

```
prompt signature matches   AND   pane unchanged for stall_secs   ->   answer no
```

**Neither condition works alone, and the reasons differ.**

- **Unchanged alone is meaningless.** A session idling at its input prompt is
  unchanged for hours - that is its normal resting state, not a fault.
- **Signature alone would steal a live prompt** out from under a human who is
  reading it.

Requiring both is what keeps `Escape` away from legitimate long-running work. A
false positive fires Escape into whatever the session is really doing; a false
negative merely leaves the stall for a human. **Only the first can destroy work**,
so the patterns are kept specific and the timeout generous.

**The pane digest deliberately ignores animating content.** The footer carries a
live token counter and a spinner. Hash those and the digest changes every poll,
`since` resets every poll, the timer never expires, and the watchdog silently never
fires - a failure that looks exactly like a watchdog that is working.
`watchdog.test.py` pins this, and section 6 is why a synthetic version of that
test is not enough.

## 4. The exclusion matters more than the patterns

The pane being read also displays the agent's **own** commands and output. An agent
that prints, greps or edits text containing a chooser - this very file does - would
otherwise detect itself as prompting, and be Escaped `stall_secs` later while
perfectly healthy: a test run that prints sample dialogs matches the live pane -
measured.

The discriminator is **structural, not textual**. A modal dialog REPLACES the input
box and status bar at the foot of the pane. Idle or working, those are always
present; while a dialog is up they are always gone. So if the last
`stall.idle_tail_lines` carry the idle signature, it is not a prompt - regardless of
what is on screen further up. Text can be quoted; the structure cannot.

**"Not a prompt" has two causes and only one of them is protection.** The
exclusion fired, or no prompt pattern happened to match. A boolean cannot separate
them, so `idle_exclusion_hits()` reports the exclusion on its own and `doctor` and
`--probe` print it as `ARMED` or `INERT`. Without that line an unprotected session
and a protected one produce identical output.

**`stall.idle_tail_lines` is a measurement, not a constant.** A session that
renders an agent-list panel BELOW the status bar has its idle signature seven lines
from the bottom of the pane - one line outside the shipped six-line window (measured
2026-09-04). It reads as `prompt match False`, which is what a healthy session looks
like, while the exclusion the whole design leans on is inert. Anything rendered under
the status bar does this. Re-measure after a terminal-UI change.

Widening the window is cheap and does not trade detection for protection: every
shipped prompt fixture is still detected as a prompt at every window width up to the
entire pane, because a modal replaces the footer and the panel together. The suite
sweeps `_ALL_PROMPT_FIXTURES`, so a fixture added later is covered without anyone
editing a numeral - which is why no count is written here.

**The first prompt pattern matches the selection CURSOR** - the chooser glyph,
then a digit, then a dot - and deliberately does not match the option text. Option
names vary by dialog: Yes/No for a command confirmation, but Compact, Login and
others elsewhere. Keying on `Yes|No` silently misses every dialog that is not a
command confirmation. The cursor is the one element common to all of them.

**The cursor glyph alone is not enough**: it is also the session's own input
prompt, on screen whenever the agent is idle. Requiring a digit and a dot after it
is what separates a chooser from the resting state - get this wrong and the
watchdog Escapes an idle session every `stall_secs`, forever.

## 5. The captured prompt, and what is NOT known about its guard

The patterns **are** verified against a real captured prompt.
`fixtures/real-prompt-a.txt` and `-b.txt` are consecutive `tmux capture-pane`
samples taken 10s apart while a genuine confirmation was on screen;
`watchdog.test.py` asserts against them.

The real prompt (glyphs as escapes; the bytes are in `fixtures/real-prompt-a.txt`):

```
 Dangerous rm operation on possibly-empty variable path: $TMP/*.txt

 Do you want to proceed?
 \u276f 1. Yes
   2. No

 Esc to cancel \u00b7 Tab to amend \u00b7 ctrl+e to explain
```

**What trips that guard is a variable path inside a LOOP BODY**, and the obvious
answer - a variable in the path, alone - has been falsified. The guard is real and
unsuppressable when it fires: its text is
in the Claude Code binary (`grep -a -c 'possibly-empty variable' <versions dir>/2.1.260`
-> 4), and its own explanation reads "when the variable is unset or empty, e.g.
`rm -rf $UNSET/*` becomes `rm -rf /*`. This requires explicit approval and cannot be
auto-allowed by permission rules." But four `rm` shapes issued from the Bash tool of a
live unattended session started with `--dangerously-skip-permissions` produce **no
prompt at all** - each returns in <= 20s and watchdog state stays `fired: false`.
Measured 2026-09-04, Claude Code 2.1.260, on one Linux host:

1. `TMP=<path>; rm -f $TMP/*.txt` - **the captured prompt's own shape**
2. `SCRATCHDIR=<path>; rm -f $SCRATCHDIR/*.log`
3. `rm -f $WDSENTINEL/wd-sentinel-*.txt` - variable genuinely unset
4. `rm -rf $WDSENTINEL/wd-sentinel-dir-*` - unset, `-rf`; the guard's own documented
   shape minus the blast radius

**Do not probe the bare `rm -rf $UNSET/*` to close the gap.** Its miss case is the
filesystem root. It is never run.

What DOES fire it, reproducibly, is the same variable path inside a loop body:

```bash
for t in t1 t2 t3; do rm -rf "$D/$t"; done      # prompts, every time
```

measured 2026-09-12 over a scratchpad base path, on every attempt. The same
deletions with **every path written out literally** go through unprompted. Read against the four misses above, that isolates
the loop-plus-variable combination as the trigger rather than the variable alone.

So "write `rm` paths out literally - never `$VAR/...`, and never inside a loop over a
variable base" is MACHINE-ENFORCED for the loop form, not a convention a rule may only
gesture at. A subagent's cleanup step is written literally **in the brief**: the
agent that meets the prompt is the unattended one, and it cannot rewrite the command it
was handed. Any rule written instead as "avoid globs in /tmp" is aimed at the wrong
thing: nothing observed supports it.

**The fixtures stay.** They are real captures of a prompt that appears, and the
patterns are what this watchdog tests - the pattern layer does not depend on knowing
why the prompt is raised.

**To re-verify after a UI change, run `--probe` while a prompt is on screen.** It
prints the pane and reports which patterns hit and which miss, taking no action.
**Every firing also logs the pane it matched** (`WATCHDOG-PANE |`, last 25 lines)
*before* acting, so a wrong pattern leaves evidence rather than a mystery.

## 6. What a synthetic fixture cannot catch

**A digest that hashes animating content never fires**, and nothing else looks
wrong: tests green, `systemctl status` healthy, config sensible.

While a prompt is up the session displays `\u25cf Running 1 shell command\u2026` and
**the leading glyph blinks** - the same line alternates between `\u25cf Running\u2026`
and `  Running\u2026` about every other second. A digest that strips only the footer
changes on every poll over that line, `since` resets on every poll, and the stall
timer never accumulates past one interval. A synthetic fixture does not blink, so a
test built on one passes against exactly that broken digest.

`pane_digest()` normalises animating glyphs and collapses whitespace before
hashing. The lasting guard is not that normalisation but the **fixtures**: real
captures that do blink, plus a test that walks the state machine alternating
between them and requires it to reach a deny. There are **two independent blinking
pairs** - the `rm` guard's, walked at a 20 s cadence, and the permission prompt's
(section 7), walked at whatever cadence the config declares - so a normalisation bug
has to survive two separate reproductions of the mechanism instead of one.

**A pair that merely DIFFERS is not a pair that blinks, and the difference is not
academic.** Add trailing whitespace to one line of a sample and the files differ, the
digests still match (whitespace is collapsed), and the mechanism is gone with the
suite fully green - measured. Each pair therefore carries a check that the two samples
are identical after the animating glyphs are substituted out and different before it.
Byte-inequality alone cannot see this.

**Regenerate the fixtures from real `tmux capture-pane` output, never by hand.**
A fixture that cannot reproduce the mechanism cannot test it. Hand-written panes are
how a watchdog ends up green and blind, and blind is worse than absent - an absent
watchdog leaves people watching, a blind one stops them.

**The fixtures are byte-exact captures and are exempt from the ASCII house rule.**
Their box-drawing, spinner and cursor glyphs are what the matcher matches; normalise
them and the tests stop measuring anything. The same protection covers the glyph
class in `watchdog.py` and the patterns in the config.

## 7. Testing it, and how to raise a real prompt on demand

Each half is verified separately, and the fixtures remain the real regression guard.
But an ordinary **permission** prompt IS reproducible, which the `rm` guard of section
5 is not, and that is the class this watchdog actually targets. Three conditions, all
required:

1. **A session not in an auto-approving permission mode.** Claude Code defaults to
   auto mode (measured 2026-09-04, 2.1.260), which assesses tool calls itself and runs the lower-risk ones with no
   dialog - so merely omitting `--dangerously-skip-permissions` is not enough. Cycle to
   the manual mode with shift+tab and read the status bar back before relying on it.
2. **A command shape not already approved in that session** (the caching rule below).
3. **A throwaway session**, on its own tmux server, its own config and its own
   `state.dir`, never one a live watchdog is watching - because the fire sends Escape
   into whatever is running.

An end-to-end run demonstrates the MECHANISM; it is still a poor regression test,
because it needs a live session and two minutes per fire. The suite is what runs
unattended.

**The decision half** is `watchdog.test.py`, offline and hermetic: no tmux, no
session, no keystrokes. It forces `STALL_WATCHDOG_CONFIG` at `config.example.json`
before importing the module, so its verdict does not depend on which machine or
which agent ran it - and so section 5 of the suite is auditing a file that ships and
is reviewed, rather than an unreviewed local one.

**A green suite is not evidence unless it can go red for the reason its names
claim.** The controls below establish that, and re-running them is how you
re-establish it after any change to the decision logic:

| Break this | The check that must fail |
|---|---|
| empty `stall.idle_patterns` | `TEETH: an idle agent that PRINTED a dialog is not a prompt` |
| add an `approve_key` to `action` | `TEETH: config exposes no approve/yes/confirm key` |
| `pane_digest()` hashes the raw pane | the blink checks in BOTH real-capture sections, incl. each `alternating ... reach a deny` |
| remove `fixtures/` | `every prompt fixture is present and still reads as a prompt`, plus one `fixture <name> is present` per file |
| replace one sample of a pair with a copy of the other | `TEETH: the two ... samples differ ONLY by an animating glyph` (that pair's) |
| make one sample differ by WHITESPACE instead of a glyph | the same check - byte-inequality passes it, blinking is what it measures |
| delete a `stall.prompt_patterns` entry | `the configured patterns still cover every structural element` |
| widen a `stall.prompt_patterns` entry so it reaches unnumbered choosers | ONLY `KNOWN GAP: the trust-folder start-up dialog is NOT detected as a prompt` - which is the designed signal to retire that gap, not a regression |
| add a `known_prompts` entry matching a permission dialog | `TEETH: a permission prompt matches NO taught handler - it is still refused` |
| change `stall.stall_secs` / `poll_secs` | nothing, by design - the cadence checks derive from the config. An off-by-one in `decide()` reds `the deny lands at t=...s` instead |
| render a panel below the footer, window unchanged | `TEETH: a panel rendered BELOW the footer pushes the exclusion out of the window` |
| `maybe_reexec()` never re-executes | `TEETH: a changed mtime re-executes this interpreter on the same argv`, and the real-loop check after it |
| `maybe_reexec()` compares the file's mtime with the clock instead of its recorded value | `TEETH: a file dated in the future does not re-execute, cycle after cycle` |

**The rows above name checks, never counts.** A numeral in this table has no gate
and rots on the next edit.

**The action half** (`answer_no_and_notify`) can only be verified by calling it
directly:

```python
m.answer_no_and_notify("TEST: typed by the watchdog, not a human")
```

`Escape` lands first and **interrupts whatever is running**, then the text is
typed and submitted, arriving as an ordinary message. A false positive does not
merely add noise, it cancels work in progress - which is the whole reason for the
idle-footer exclusion in section 4. **Never run this against a session doing real
work**, and never run the daemon in loop mode by hand against a live session for the
same reason.

**A command approved once will not prompt again in the same session.** Approving
the confirmation caches the decision for that command shape, so the obvious way to
re-test - run the same `rm` again - silently succeeds and proves nothing. Vary the
command, or test the two halves separately.

## 8. `$TMUX` beats `TMUX_TMPDIR`

When `tmux` runs **inside** a tmux session it inherits `$TMUX`, which carries the
socket path of the server it is running under, and **that wins over
`TMUX_TMPDIR`**. Measured: `TMUX_TMPDIR=<one agent's dir> tmux ls`, typed from
another agent's session, lists the OTHER agent's server while looking entirely
correct.

- **`watchdog.py` is immune**: `_tmux()` drops `TMUX` from the child environment.
  That line is load-bearing, and its rationale is in the function's docstring.
- **The daemon is not exposed** - systemd sets no `TMUX` - but every hand-run is,
  which is why the script drops it rather than leaving the warning to prose.
- **A raw `tmux` command you type yourself is still exposed.** Prefix it with
  `env -u TMUX`.

## 9. Where it runs, and why not a Monitor

**Prefer the system service: the systemd unit, or on macOS the LaunchDaemon that
runs as the agent's user.** A user-domain LaunchAgent is a service the watched agent
can switch off, and `installation/check` reports it UNPROTECTED. The agent's own unit
has `Restart=always` (launchd: KeepAlive), which covers
the agent process *dying*. It does not cover the agent *hanging* - a process blocked
on a prompt is alive and healthy by every measure systemd has. A watchdog armed as a
Monitor inside the session it watches shares that session's fate, which is backwards
for a supervisor.

**`ReadWritePaths` deliberately carries no `-` prefix**, so a missing tmux
runtime directory fails the unit at start rather than starting it blind. That is the
recovery path, not a defect: the agent unit owns that directory
(`RuntimeDirectory=`), so while the agent is stopped the watchdog restart-loops
every `RestartSec` and comes up correctly the moment the agent returns. With `-` it
would start into a read-only namespace and be permanently blind while
`systemctl status` showed it healthy.

**The unit runs `watchdog.py` from the host fleet checkout, and its working directory
is the watched agent's own checkout.** The fleet checkout moves only by `fleet
upgrade`, never because somebody pulled a branch, so several units sharing it share
one released version rather than one branch state. The units are root-owned, so an
upgrade must reach them without an edit or a `sudo systemctl restart`: **the loop
re-executes itself** (`os.execv` of the same interpreter and argv; an exec that fails,
because the interpreter's path is gone after a Homebrew upgrade, exits 75 and the
service manager starts it again from the unit's interpreter) when the mtime of
its own file differs from the mtime it recorded at start, checked once per poll. It
compares with that recorded value and never with the clock, so a file dated in the
future - clock skew, a restored backup - cannot make it re-execute every cycle and
reset the stall timer each time. The stall cursor is on disk and the lock is
re-taken by the fresh process, so a re-exec loses nothing. `watchdog.test.py` section
6 pins both directions, including a real loop re-executing once on a touched file.

## 10. What it does NOT cover

**Only stalls that put a confirmation prompt on screen.** A session that stops
responding without a prompt is invisible to it - the pane simply looks idle, which is
a normal resting state. That failure exists and looks identical from outside, so **do
not treat an armed watchdog as proof a session is alive.** Coverage for it has to come
from something the session actively does, not from what its terminal looks like.

**And not every dialog on screen is one the patterns reach: an UNNUMBERED chooser
is invisible too.** The cursor pattern requires a digit and a dot after the glyph,
and the footer pattern requires `Tab to amend`. Claude Code's start-up dialogs have
neither - the trust-this-folder dialog and the Chrome-extension dialog list bare
option text under `Enter to confirm \u00b7 Esc to cancel` - so an unattended session
started in a folder it has not trusted blocks forever with the watchdog watching it,
reporting `prompt match False` the whole time. `fixtures/real-prompt-trust.txt` is a
real capture and the suite PINS the miss, so closing the gap cannot be done silently.

**Closing it is a decision, not a patch.** Widening the cursor pattern to accept a
bare glyph plus any non-space would reach these dialogs and would also enlarge the
false-positive surface, into which this watchdog sends Escape. Whoever widens it
retires the pinned gap and its section 12 entry in the same commit.

## 11. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `tmux UNREACHABLE` in `doctor` | `tmux.tmpdir` disagrees with the session's `TMUX_TMPDIR`. They must match exactly or tmux reports "no server running". Also check the session is up at all. |
| `tmux could not be started ... on PATH=...` (`WATCHDOG-ERROR`, the state's `capture_error`, `installation/check`) | The job's PATH reaches no tmux. watchdog.py runs a bare `tmux`, and a service manager's PATH is not the shell's: launchd's reaches none on a Mac. On macOS re-render the job with `installation/render-plist.py`, which writes the directory of the tmux it finds into the job's PATH and refuses when it finds none; under systemd the unit has systemd's default PATH, which reaches `/usr/bin/tmux`, the session unit's. |
| `doctor` reports the wrong session | You are inside another tmux session and something bypassed `_tmux()`. See section 8; prefix raw `tmux` with `env -u TMUX`. |
| Works by hand, blind under systemd | `ProtectSystem=strict` makes the whole hierarchy read-only, so check every path the daemon writes has a `ReadWritePaths` entry. **The tmux socket dir is not the usual cause**: a read-only mount does not block a connect to a unix socket - measured 2026-09-04 on systemd 259 / Linux 7.0.0, `/run` is read-only under this hardening and `capture-pane` through it succeeds. Its entry is cheap defence in depth; re-measure on the platform before naming it as the explanation for a blind watchdog. The STATE dir entry, by contrast, is load-bearing and was measured: without it the state write is blocked. |
| macOS job not running, `launchctl print system/<label>` shows a last exit code | Read `<state.dir>/watchdog.log`. A job whose log directory does not exist does not start: create `state.dir` (0700, owned by the agent's user) first. |
| Unit fails at start, status 226/NAMESPACE | A `ReadWritePaths` directory does not exist. The state dir must be created before the unit starts; the tmux dir appears when the agent unit starts. See section 9. |
| Is it actually seeing the pane? | Compare the saved digest against `pane_digest("")`. Equal usually means it is capturing nothing - but a genuinely BLANK pane hashes to the same value, observed against a throwaway session running a silent loop, so this is a hint and not a verdict. Every poll writes the state, and a failed capture writes it with `capture_error`, so a state file whose mtime is newer than the service start and that holds no `capture_error` is itself proof the capture worked. |
| Never fires during a real stall | Pattern miss. Run `--probe` against the live prompt and tune. Check the digest is not churning on the footer. |
| Fires during normal work | A pattern is too loose. Narrow it, then read the `WATCHDOG-PANE` log to see what it matched. |
| Fires repeatedly on one prompt | The `fired` latch is not persisting - check `state.dir` is writable. |
| `WATCHDOG-GUARD` and exit 0 | Wrong `CLAUDE_CONFIG_DIR` for `owner.claude_config_dir`, or another instance holds the lock. Expected and harmless. |
| `WATCHDOG-CONFIG missing config file` | `STALL_WATCHDOG_CONFIG` is unset or points at nothing. There is deliberately no fallback config beside `watchdog.py`; see `SKILL.md`. |
| Two watchdogs running | Different `state.dir` between launchers, so the flock is on different files. That location comes from config, never from the environment. |
| `WATCHDOG-INFO ... changed on disk - re-executing` | `watchdog.py` changed under the running loop - a `fleet upgrade` - and the loop replaced itself with the new code (section 9). Once per change is expected; on every poll means something rewrites the file each cycle. |

## 12. Three gaps, measured end to end

Measured 2026-09-04 on Claude Code 2.1.260, by driving a throwaway session (its own
tmux server, config and `state.dir`) to an ordinary Bash permission prompt, which
the watchdog refuses. The three gaps below are open.

**"Started without `--dangerously-skip-permissions`" does not mean "prompts".** Auto
mode is the default permission mode: a fresh session comes up `\u23f5\u23f5 auto mode
on` and approves lower-risk tool calls itself; it runs `ls -la` with no dialog at all.
**Raising a permission prompt takes two things**: shift+tab to **manual mode**
(`\u23f8 manual mode on`), AND a command shape not already approved in that session -
an approved shape is cached, so re-issuing the identical command silently succeeds and
proves nothing. Section 7 builds on both.

**In manual mode and in plan mode the structural exclusion is INERT on an IDLE
session.** Their status bars read `\u23f8 manual mode on \u00b7 ? for shortcuts \u00b7
\u2190 for agents` and `\u23f8 plan mode on (shift+tab to cycle) \u00b7 \u2190 for agents`,
and none of the shipped `stall.idle_patterns` matches either - the `\u23f5\u23f5`
glyph is what auto and accept-edits modes carry, and it is what the exclusion leans
on. `--probe` against such a session reports `prompt match False` with `exclusion
INERT`, which is the unprotected state section 4 is about: only the prompt patterns
then stand between a chooser the agent merely PRINTS and an Escape `stall_secs` later.
**Say IDLE and not "healthy"**: a manual-mode session that is WORKING shows `esc to
interrupt` in the same footer, which does match, so the exclusion arms and disarms
with the session's activity - the worst version of a protection to reason about. A
session that runs with bypass permissions shows `\u23f5\u23f5` and is unaffected; a
session that ever cycles its mode is, and nothing announces it.

**The two start-up dialogs are invisible to the watchdog, and they are exactly the
blocking-prompt-nobody-can-answer case.** The trust-this-folder dialog (`Quick safety
check: Is this a project you created or one you trust?`) and the Claude-in-Chrome
dialog both number nothing and both close with `Enter to confirm \u00b7 Esc to
cancel`, so every shipped prompt pattern misses: the cursor pattern needs a digit and
a dot after the glyph, and the footer pattern needs `Tab to amend`. An unattended
session started in a folder it has not trusted therefore blocks forever with the
watchdog watching it.

**The trust dialog does not always block - given an Enter it EXITS, and that is the
worse half.** Its preselected option is `No, exit`, so anything that sends a bare Enter
into that pane terminates the session rather than answering it. Measured 2026-09-04:
an agent unit whose `ExecStartPost` sends an unconditional Enter to deliver a boot
message kills Claude Code on the first start in a folder that config directory has
not trusted; the tmux server dies with it, the send-keys reports `no server
running`, `ExecStartPost` exits 1, and `Restart=always` loops the unit about once a
minute - a start-up failure with no dialog anywhere in the journal. **A start-up
handshake must therefore wait for a READY STATUS BAR before it sends anything**,
which is the same structural discriminator this watchdog leans on: a modal dialog
replaces the status bar, so `bypass permissions on` in a capture cannot coexist with
a dialog. A handshake that sleeps a fixed interval and then sends is the shape that
fails.

The capture is `fixtures/real-prompt-trust.txt`, and section 2d of `watchdog.test.py`
**pins the miss**, so this entry cannot quietly become false. **When that check goes
red the gap has been CLOSED, and the fix is to delete the pin and this entry together,
in one commit** - never to restore the miss. Widening the cursor pattern to unnumbered
choosers enlarges the surface this watchdog sends Escape into, so it is a decision, not
a patch (section 10).
