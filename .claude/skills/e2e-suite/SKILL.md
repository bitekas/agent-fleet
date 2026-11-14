---
name: e2e-suite
version: 1
description: >
  Keep the e2e harnesses green and current, for a project whose browser-driven
  e2e harness runs through one wrapper that boots and tears down a local dev
  stack: when to run it (`e2e.runner`), how it owns the server lifecycle, the
  optional second harness that drives the NATIVE build on a simulator or
  emulator and records the run to video (`e2e.device.runner`), what each one
  can and cannot cover, the rule that new and changed screens and flows get
  their specs written or updated as part of the change, the two fan-out rules
  (a commit that deletes or moves a navigation, or reshapes a request body the
  specs assert on, retargets those specs in the SAME commit), the machine-wide
  run lock and its named "nothing ran" exit, the instrument-fault
  re-measurement, and the instrument traps that make a run's verdict
  unreliable - a stale bundle on the first run after a source edit, a filter
  that silently runs everything and reports green, and a poll loop that cannot
  see the verdict line. Load whenever touching code the harness drives, the
  bundler config, or the env/deploy scripts, and before declaring any such
  change done.
requires_install: false
---

# e2e suite: keep it green and current

**Scope.** This skill is for a project whose end-to-end harness drives a
browser against a web build of the app through ONE wrapper script, which boots
a local dev stack (an emulated backend, and a mock of every paid external
service) and tears it down again; optionally, a second harness drives the
native build on a simulator or emulator. Where this file states a fact about
the underlying test runner, it is Playwright's, the runner it was measured on.
Another runner has its own equivalents, and they are worth measuring before
they are trusted.

**Values.** Every concrete name below - the runner, its projects, its verdict
strings, its environment variables, its lock, the spec directory, the
type-check commands - is a key in this skill's `config.json` in the install
context (`fleet where e2e-suite config.json` prints its path), written as
`e2e.runner` and never as the value. The install's `CONTEXT.md` for this skill
(`fleet where e2e-suite CONTEXT.md`) is the local layer. It carries:

- the runner's invocations, its phases and what each one boots, its exit
  codes, and its verdict line verbatim;
- where the whole suite runs in CI (per push, or a scheduled gate), and how a
  branch is gated on demand;
- the runtime envelope with the hardware it was measured on, and the
  worker-count plateau;
- the grep forms for the two fan-out rules (section 2): the navigation call
  forms and the request-capture accessors;
- the serial phase's shared documents, the import chains a spec must not
  reach, the scoping probe, the fast-iteration commands, and whether the device
  harness is wired into CI;
- the measured instance behind each rule below.

Keeping the harness at `e2e.specs_dir` green **and its coverage current** is
part of the definition of done for any change it touches (`/definition-of-done`
Rule 4), not scope creep. This skill states how to run the harness and what a
change owes it, never whether a change may ship.

## 1. Two harnesses, and they cover different things

`e2e.device.runner` is a SECOND harness, present only where `e2e.device` is
configured. It drives the NATIVE build on a simulator or emulator rather than
the browser, and records the run to video.

| | `e2e.runner` (browser) | `e2e.device.runner` (device) |
|---|---|---|
| Drives | the web bundle | the native build, through a tap driver (`e2e.device.driver`) |
| Stack | **owns the lifecycle** - tears the dev stack down and rebuilds it | **non-destructive** - uses the stack and device already up, refuses if either is missing |
| Specs | under `e2e.specs_dir` | flows under `e2e.device.flows_dir`, platform-neutral |
| Artifacts | reports + the verdict line | a video of the run, per-step screenshots, driver logs |

**The browser suite remains THE coverage instrument**, and nothing in this
section moves an obligation onto the device one. The device suite exists for
what a browser run structurally cannot see: native navigation, the real gesture
surface, and what the app looks like while it runs.

- **A green device run is not coverage of a shipped binary.** A simulator or
  emulator dev build loads its JS from the dev server, so it is the dev build
  wired to a dev stack.
- **A virtual device has no real camera, and the browser suite's fake camera
  feed does not reach a native build.** The fake feed is a web-only mechanism
  (a browser flag or a web shim), so a camera-backed screen renders empty on a
  device, or shows the virtual device's own emulation (`/device-emulators`,
  `technical/camera.md`, says what each platform shows). Device flows assert on
  navigation and chrome, not on a captured frame; anything needing a frame
  stays in the browser suite.
- **A device harness that is not wired into CI is run by nobody unless a person
  runs it.** The install's `CONTEXT.md` says whether this one is.

The machine-level prerequisites, the tap driver's install, and the per-platform
input and capture matrix are `/device-emulators`'s (its section "Driving and
capturing a running device"), not this skill's.

## 2. Coverage is part of the change

- **New screen or flow** -> its own spec, in the project that owns that surface
  (`e2e.projects`), so the behaviour can never silently regress.
- **Changed flow, text or structure** -> update the affected assertions in the
  same change.
- **Reproduced production bug** -> the failing-test-first order applies
  (`/definition-of-done` Rule 4): the e2e test that reproduces it, watched FAIL
  on the unfixed code, then the fix, then the test joins the default suite.
- **Deleted or relocated navigation** -> retarget the specs that drove it, in
  the SAME commit (2.1).
- **Reshaped or retired client-to-server request contract** -> retarget the
  specs asserting on that request's BODY, in the SAME commit (2.2).

### 2.1 Deleting or relocating a navigation fans out to the specs

**A commit that removes or moves a navigation call (`app.navigation_calls`)
greps the spec directory (`e2e.specs_dir`) for the route it navigated to and
retargets those specs in the SAME commit.** Grep the route through the route
table (`app.route_table`), and belt it with its literal path string, in case a
call site bypassed the table. The install's `CONTEXT.md` carries the two greps
in this stack's terms.

This is a fan-out rule, and it is one layer further from the code you are
editing than the fan-out rules that bite at build time: a navigation is an
app-side edit, and the thing it breaks is in a directory the change never
opened. Nothing in the app fails. **The suite is what fails, and it fails
LATER, for SOMEBODY ELSE.**

**The red tests are not the real cost. The downstream cost is.** Every worktree
cut while the stale specs sit on the landing branch inherits the red as a
phantom bug in **its own** work, because **the failure text names the spec and
never the commit that invalidated it**. Each of those agents pays the full
diagnostic cost of a bug that is not theirs, and the honest ones pay it twice:
once to find that the spec is stale, and once to establish that their own
change did not cause it. (The install's `CONTEXT.md` carries the measured
instance.)

**The same-commit part is the whole rule.** A follow-up commit is not a smaller
version of it: the window between the two is exactly where every phantom is
manufactured, and it is open for as long as nobody happens to run the suite.

### 2.2 Reshaping a request the app sends its own backend fans out to the specs that assert on the BODY

**A commit that renames, reshapes or retires a field in a request the client
sends to its own backend greps the spec directory (`e2e.specs_dir`) for specs
asserting on that request's body, and retargets them in the SAME commit.** Grep
the harness's request-capture accessors, NOT the field name: a spec reaches the
field as a property of a captured object, so grepping the field name finds the
app and misses every spec. The install's `CONTEXT.md` carries this harness's
accessors.

Same class as the navigation rule above, and it fails the same way - later, for
somebody else. What makes it worse is that **every cheap instrument is blind to
it**, so it survives the whole local budget and surfaces only in a full run:

- **A grep for the retired symbol does not find it.** The spec names no module,
  global or constant that the change removed. It names a property of a request
  it captured, and that property is spelled nowhere the change was looking.
- **The type-checker cannot see it.** A captured body is untyped by
  construction, so an assertion on a field the client no longer sends
  type-checks perfectly.
- **A scoped run does not reach it.** The change is server-contract-shaped and
  the spec is named for a screen, so it is not in the set a reader picks as
  "affected" - which is exactly the judgement the scoped-run trade asks for.

**The assertion worth adding while you are there is the NEGATIVE one**: pin
that the retired field is ABSENT from the body, not only that its replacement
is present. A body carrying BOTH shapes passes a present-only assertion, and a
client mid-rollout is precisely the case that sends one - so the present-only
form is green on the tree where the contract is half-migrated, which is the
tree you most need it to fail on.

### 2.3 Retargeting a spec whose MECHANISM was deleted, not just renamed

**Before you retarget an assertion, ask what made it satisfiable - and if that
mechanism is gone, the spec is REWRITTEN or RETIRED, never reshaped.** A
mechanical retarget that preserves an assertion's SHAPE after the thing that
satisfied it has been deleted produces a spec **no correct build can pass**: it
fails, and it reads as a regression. (The install's `CONTEXT.md` carries the
measured instance.)

**This is the vacuous green's mirror image, and both read as diligence.** One
check can never fail; the other can never pass. The tell is the same in both:
**an assertion whose text describes a condition nothing in the tree can now
produce.**

- **The green that hides it is the diff.** A retarget touches only the names in
  the assertion, so it reviews as a small, obviously-correct edit - which it
  is, considered as an edit, and which says nothing about whether the property
  still exists.
- **Ask it as a positive**, not as "does this still pass": *what, in the tree
  as it is now, would make this assertion true?* If the answer names something
  the commit deleted, no spelling of the assertion will help.
- **A spec left honestly RED, with the reason written where the next reader
  finds it, beats a rewritten one that passes.** A retired property should read
  as retired; a property that merely moved should be restated over its new
  mechanism, in the task that owns that mechanism.

**The sibling failure is a control asserting on a string the app never
emits.** A spec can pin a log line that exists in no application code - a
property stated in the design, asserted in the suite, and implemented nowhere -
and survive review, because nothing compares the two. **Grep the app for every
literal a spec pins as a positive control**; a control the product cannot
produce is not a weak control, it is decoration.

### 2.4 Spec conventions

- Assert on **source-casing** text: a CSS `text-transform` changes rendering,
  not the DOM text a selector reads.
- Use exact-match and first-match selectors to dodge substring collisions.
- Drive state through the harness's own seeding bridge and navigation
  patterns, copied from an existing spec - never assert on an artificially
  hacked state.

## 3. Running

The runner (`e2e.runner`) is the single entry point, invoked from the
repository root, and a run must end in the pass verdict (`e2e.verdict.pass`).
Its `--help` is the source of truth for flags; the install's `CONTEXT.md`
carries the invocations.

### 3.1 AFTER EDITING APP SOURCE, THE FIRST RUN IS NOT A VERDICT: READ THE SECOND

**The dev server can serve a STALE BUNDLE to some parallel workers on the first
run after a source edit, so one run reports a mix of the old code and the new
one, with no error, no warning, and a perfectly ordinary-looking pass/fail
line.** Measured on more than one spec (the install's `CONTEXT.md` carries the
instances): disabling a fix and running immediately reported fewer failures
than the truth; re-running with *nothing else changed* gave the true count.
Only one worker had picked up the changed bundle; the others were served the
previous one.

**So: after any app-source edit, run the affected specs TWICE and believe the
SECOND.** It costs one extra scoped run (seconds against a warm stack), and it
is the cheapest instrument correction in this file.

**The dangerous direction is the reassuring one, which is why this is a rule
and not a tip.** A stale bundle most often produces a *green* against code that
does not have the change. That reads as "these assertions have no teeth" and
invites deleting or weakening them. So the failure mode of skipping the second
run is not a wrong verdict you notice, it is a good test you remove.

This applies to **every** measurement taken across a source edit, in both
directions:
- proving a new spec FAILS on unfixed code (the bug-fix order's first step),
- proving it PASSES after the fix,
- any negative control that reverts a fix to watch a named spec go red.

A single run is only a verdict when **no app source changed since the previous
run against that same stack**.

### 3.2 Running a scoped subset (iteration - and, for a contained change, the gate)

The runner scopes three ways: by spec file (which infers the suite), by test
title, and as a **plan-only** dry run that prints what would run and boots
nothing. Unrecognized arguments are forwarded to the underlying test runner, so
its own selectors work. A filter must resolve to one suite. (A runner with no
plan-only mode needs one before any filter it takes can be trusted.)

**A filter that silently ran everything and reported green is
indistinguishable from a correctly scoped one** (section 10). So confirm a
filter with the plan-only mode, which costs no boot, rather than inferring from
the run's duration that it scoped.

**Reuse mode** skips the cold boot and the teardown, running against whatever
stack is already up: seconds instead of a full boot, which is the only way
single-test iteration is worth doing. Its two costs, both real:
- The stack must already be a **mock-service e2e stack** (one left up by an
  earlier run). A plain dev-stack boot talks to the REAL paid services: a run
  against it makes live calls at real cost.
- Suites share one database, and the global setup seeds only what the install's
  `CONTEXT.md` lists; it never resets data between tests. Specs self-seed but
  clean up only defensively, so a spec asserting a **fresh** state can fail on a
  stack an earlier run dirtied. **A red under reuse is not a red until a cold
  run reproduces it.**

### 3.3 GREEN SCOPED AND RED IN THE FULL RUN IS AN ASSERTION DEFECT, NOT A FLAKY GATE

A spec that passes run on its own and fails in the full parallel run is almost
never a gate needing another attempt. It is a spec **asserting one ARM of a
race**, and the two runs differ in precisely the way that decides which arm
wins.

The mechanism: wherever a product path can legitimately end more than one way -
two orderings of concurrent server work, a delete racing a read, a timeout that
may or may not have elapsed - one arm dominates on an idle machine and the
other appears under load. Scoped, the spec meets its favourite arm and passes,
and passes again, which is exactly what makes the wrong conclusion so easy to
reach.

**THE TEMPTATION AT THAT MOMENT IS TO CALL THE GATE FLAKY AND RE-RUN**, and it
is wrong in the expensive direction. Re-running to green ships a spec that
passes only on a quiet box; it then fails for whoever next runs the suite under
load, and reads to THEM as a bug in their own change - the same downstream cost
as a stale spec, with the same property that the failure names the spec and
never the commit that made it fragile. **Repeated scoped greens are not
evidence the spec is sound. They are evidence the box was quiet.**

**Two tells separate this from an ordinary flake**, and both are cheap to
check: the spec is green scoped *repeatedly* rather than once, and the failing
assertion is about **HOW the outcome was reached** rather than about the
outcome itself. The second is the real tell - an assertion on a mechanism is
precisely where arms differ, while an assertion on the user-visible result
usually does not.

**The fix is never to pick the arm you happened to see.** Ask what is true in
EVERY arm and assert that:

- the invariant the user actually cares about - the outcome, not the route to
  it;
- paired with controls that do not depend on which arm won, because an
  invariant-only test drifts toward vacuity. A control proving the scenario was
  genuinely entered is what keeps the teeth.

**And where the arms produce genuinely different user experiences and only one
of them is acceptable, the spec has just found a PRODUCT defect.** Report it.
Encoding the acceptable arm as the expectation hides the other one behind a
green, which is how a race becomes permanent.

Note this is usually discovered from a run you did not launch - the scheduled
gate, or a full run a work order asked for explicitly. The local budget below
is unchanged; the point is how to read such a red when it arrives, not a
licence to go looking for one.

### 3.4 NEVER RUN THE FULL SUITE LOCALLY

**The local budget is ZERO full-suite runs, not one.**

**Locally you run exactly two things: the specs your change affects, and the
specs you just wrote.** Identify the first set by grepping the route,
component, screen name or callable name across `e2e.specs_dir`. Do not default
to a full run because it is easier than looking.

**The whole suite is CI's job.** You do not duplicate it, you do not "just
check", and you do not re-run it because the tree moved.

**Where the whole suite runs is the install's CI design, and the trade you
accept depends on it.** The install's `CONTEXT.md` says which it is;
`/repo-and-environments` section 3.2 says what a push triggers. When the whole
suite runs in a SCHEDULED gate rather than per push, the cost model is a day
wide, not a build wide: a regression is caught within the schedule's period,
on the default branch only, and a feature branch is gated by nothing at all
until it lands, unless the quality workflow is dispatched on its ref. **The
local budget is still zero**; what changes is how wide the trade is that you
accept when you follow it.

**Why zero.** A fleet of agents in parallel worktrees, each running the whole
suite a few times "just to check", multiplies into many hours of compute a day
re-proving the same tree (the install's `CONTEXT.md` carries the measured
day). It is also self-harming: a suite with wall-clock instruments is
load-intermittent under concurrent stacks, and native release builds compete
for the same memory. **The runs manufacture the flakes that then justify more
runs.**

**What still happens locally, and is not the suite:**
- **The affected specs, and any spec you added.** Green there is your gate.
- **Negative controls.** Proving a test can fail (revert the fix, watch that
  named spec go red, restore, watch it go green) stays mandatory and is scoped
  by construction. It finds real defects, among them a suite whose teeth had
  never once executed.

**Report the shape of what you ran, never imply more.** Name the specs and say
which were affected and which are new; the full suite is CI's. A reader must be
able to tell scoped coverage from full coverage without asking.

**The trade, stated rather than glossed:** a regression outside the specs you
picked is found by CI after the push instead of by you before it. That is
accepted, but **it makes picking the affected set an actual obligation**, not a
formality. If you cannot name why a spec is unaffected, it is affected.

**A change that cannot reach runtime gets no e2e at all**: a workflow file, a
comment-only diff, a memory or skill edit, a design doc. Say why it was
skipped, and **prove the claim where it is load-bearing**: stripping
comment-prefixed lines from the added side of your diff and getting an empty
set is a measurement; "it's only comments" is not.

**"Trivial" and "small" are not the same word.** A **one-line** guard can be
the entire fix for a defect that silently disabled a whole feature, and a
**single clause** in one predicate can decide a user-visible outcome (the
install's `CONTEXT.md` carries the instances). Both are tiny; neither is
trivial. **Ask what the change can reach first, and let size decide only once
the answer is "nothing".**

**How much to run - `/definition-of-done` Rule 4 decides, and the answer is not
always "everything":**
- Change confined to code that existing specs cover -> update those specs and
  run **only** them; green there is the gate. Identify the covering specs by
  grepping the route, component or callable name across `e2e.specs_dir`.
- New product functionality -> a new spec ships with it.
- Orchestrated multi-agent work -> one **full** cold run ending in the pass
  verdict, run **once at the very end**, after every subagent's work is finished
  and handed over. Not per-subagent, not mid-flight: each piece is already
  proven by its own specs, and this run is the integration gate over the merged
  whole.

The reuse caveat still applies wherever it is used: a red under reuse is not a
red until a cold run reproduces it, and a scoped run used as the gate should be
a cold one.

### 3.5 Runtime / ETA (declare this envelope when you dispatch a run)

The install's `CONTEXT.md` carries the measured wall-clock figures, the
hardware they were taken on, and the resulting runaway thresholds. **Declare
the applicable envelope in any work order that runs the suite.** A run that
passes **~2x its ETA** is presumed runaway -> kill it and investigate (a wedged
emulator, a spec awaiting input that never comes, a machine-load stall) rather
than waiting it out. Re-run once the cause is understood; do not
retry-until-green blind. A run legitimately slowed by heavy machine load is
still killed and re-run on an idle machine, not waited through.

**TWO EXCEPTIONS, AND BOTH ARE A RUN BEHAVING PERFECTLY. Read the log before you
kill anything.**

- **A run WAITING ON THE MACHINE-WIDE LOCK** (section 7.1). The ETA measures a
  run that is running; a queued one has not started, and its wait is separately
  bounded by the interlock's own timeout. A run printing the interlock's
  waiting heartbeat is queued and must be left alone, and the ETA clock starts
  at the "acquired" line, not at the invocation. Killing a queued run to
  "unstick" it is the one action that turns an interlock doing its job back
  into the contention it exists to prevent.
- **A run RE-MEASURING AN INSTRUMENT FAULT** (section 4). After the tests have
  finished, it re-runs the faulted spec files before the verdict line prints,
  and it announces that with its own line. A run that has printed it is
  measuring, not wedged.

Historical minute figures age badly: they were taken at a worker count and on
hardware that have both moved. Re-measure rather than trusting the number, and
treat an old figure as an upper bound for smaller hardware.

### 3.6 If you POLL for the run to finish, your poll loop is a check too, and both of its halves fail silently

Waiting out a multi-minute run means writing a wait loop, and that loop is an
instrument whose failures are invisible: it reports a healthy suite as dead, or
a finished one as still running, and neither prints an error.

- **THE VERDICT LINE MAY NOT BE ANCHORABLE.** A runner that prints its verdict
  (`e2e.verdict.pass` / `e2e.verdict.fail`) behind a decoration - leading
  box-drawing characters, a timestamp, a colour code; the install's
  `CONTEXT.md` shows the line verbatim - defeats a line-anchored
  `grep -qE '^...'`, which then **can never match the line it exists to
  detect**: the loop only ever exits because the process died, and a clean
  green run reads as "gone, no verdict". Match unanchored. **Prove the parse
  fires on real text before you trust it**: run it against a previous run's log
  under the artifacts root (`e2e.artifacts.root`). A negative control proves a
  check is not blindly true; only a POSITIVE control proves it can ever fire,
  and the positive half is the one people skip.
- **`pgrep -f <runner>` INSIDE A `bash -c` MATCHES ITS OWN SHELL**: the
  wrapper's command line contains the pattern verbatim, so
  `if ! pgrep ...; then done; fi` can never be true and every cycle reports
  "still running" forever. **The `[r]unner` bracket trick does NOT fix this**:
  it protects `pgrep`'s own argv and nothing about the wrapping shell, whose
  command line still holds the literal text (in an echo, a log path, a status
  message). The fix that holds is to **exclude by PID and match on `comm`, not
  the full command line**: the poller's `comm` is `bash`, which cannot match a
  search for the runner. Better still: **do not process-match at all.** Poll
  the log's mtime plus the unanchored verdict line, which is what you actually
  want to know.
- **`grep` on a live run log can return a confident FALSE NEGATIVE**, because
  `file(1)` classifies the partially-written log as `data` and grep then
  refuses to match it. Pass `-a` (treat binary as text) on every grep against a
  run log.
- **A wrapper's exit code is not the suite's verdict.** A backgrounded call
  that itself backgrounds the suite reports the *wrapper's* exit: a `tail` that
  finished early has been reported as "completed (exit code 0)" while the suite
  still had minutes to run, and runs that wrote the FAILED verdict have been
  reported as exit 0. Read the verdict out of the log; never infer it from a
  tool result.

## 4. An INSTRUMENT FAULT is re-measured, never reported as a red

Some measurements are corrupted by machine load in a direction that produces a
**red**: a per-painted-frame sampler thinned by a contended box OVERSTATES the
stall it is timing, so the number it produces is a claim about the machine
wearing the costume of a claim about the app. A spec that can detect that about
its own apparatus declares an **instrument fault**
(`e2e.instrument_fault.marker`) in its failure message, and the runner acts on
it.

**The policy, entire.** When every failed test in a run carries the marker, the
runner re-runs exactly the spec **files** those tests live in, once, at one
worker (`e2e.instrument_fault.remeasure_workers`), and **that re-measurement
is the verdict**. It never widens past the faulted files: a test that did not
run elsewhere stays not-run, and the gate's zero-skips bar keeps the run red.
One non-fault failure anywhere and nothing is re-run. A second fault is a red
meaning the box is too loaded to measure on, and the runner says what to check.
Every decision prints one line, so a reader of a CI log can see which branch
was taken without opening a report.

**How to declare one.** The marker has exactly one home
(`e2e.instrument_fault.declaration_module`), and a spec builds its message
through that module's helper - never by retyping the string. The runner's
classifier (`e2e.instrument_fault.classifier`) matches the marker in the JSON
report, so the string is a **contract across two languages with no compiler
between them**: a reworded literal blinds the policy silently, and every fault
reds as an ordinary failure again with nothing to announce that the policy
stopped applying. One check pins the two sides together
(`e2e.instrument_fault.teeth`); it is not redundant, it is the only thing that
can see them diverge.

**It is much narrower than `NO VERDICT`, and conflating the two is the one way
to break this.** `NO VERDICT` is written all over a spec directory and means "a
precondition of this measurement did not hold" - a selector that stopped
resolving, a control that did not fire, a guard marker gone stale. **Those are
real defect signals, and most of them fail identically on an idle box.** An
instrument fault is the strict subset that is **load-caused and therefore
re-measurable**. The test before reaching for the marker: *would this assertion
fail on an idle machine with the app unchanged?* If yes - or if you cannot
answer - it is not an instrument fault.

**This is not retries, and the difference is the whole point.** The policy
assumes the test runner's retries are set to zero and that the CI verdict gate
reds a flaky result, because a retried green hides a real red. Global retries
would buy **every** failure a second chance, including a genuine intermittent
product bug. This buys one only to a measurement the instrument itself
disowned *before* the verdict was read - a claim a spec author had to write
down on purpose.

**The two tempting alternatives are both the instrument going blind.** Widening
the tolerance the fault is declared against removes the detection permanently;
lowering the bar for what counts as a fault is retries by the back door.
**Never widen a truth value to make a fault stop happening.** The fault is the
instrument working.

**The premise - that the degradation is EXOGENOUS - is not proven, and the
place it can fail is the place it matters.** A sampler that runs on the page's
own main thread is starved by a long task in the app exactly as it is by a
contended box, so a real main-thread regression presents as an instrument fault
and a marginal one is re-measured green. The honest claim is the narrow one:
**this recovers a contention red, and it cannot prove the contention was
external.** The declaring module states it, and the runner's repeat-fault
message names the app as the second candidate, so nobody closes a repeat fault
as machine load without considering it. Do not restate the policy as
"load-caused reds are handled".

**The re-measurement must reach the report the CI gate reads, not just the
console.** The gate reads each phase's JSON report - executed count, failed,
skipped, flaky - so a policy that only flipped the runner's exit code leaves CI
reddening a run whose own log says it passed, and one that simply overwrote the
phase report with the re-run's leaves CI reddening it for having executed a
handful of tests out of hundreds. Both look like a working policy right up
until the gate runs, and neither is visible in the runner's verdict line. The
runner therefore merges the re-measured statuses back into the phase report and
keeps the pre-merge copy beside it as evidence.

**And the merge must check WHAT IT WROTE, not merely that it wrote.** A zero
exit from the test runner is not the same statement as "the phase report now
satisfies CI": the test runner exits zero on a test that passed on RETRY and on
a run with SKIPS, both of which the CI gate reds. So the merge refuses -
writing nothing - unless the merged report meets the gate's exact per-phase
bar, and the runner then restores the original and stands on the failure. A
console saying PASSED over a report CI reds is worse than either answer alone,
because whoever reads the console stops looking.

## 5. Concurrency: one phase is parallel, the other is not

The parallel phase (`e2e.projects.parallel`) runs fully parallel across a
configurable worker count (`e2e.workers_env_var`); the serial phase
(`e2e.projects.serial`) is serial and stays that way while its specs carry an
intra-file ordering dependency or mutate singleton documents other specs read
(the install's `CONTEXT.md` names them). That second reason is why a spec about
a parallel-phase surface can still belong in the serial phase: a spec that
moves a global pointer, even briefly to an id that does not exist, would trip
any parallel spec that reads it.

What makes a spec safe to overlap, in the order you should reach for it when
writing a new one:
1. **A fresh browser context per test.** Where the app gives every new visitor
   its own anonymous identity, that is a private data subtree. Most specs need
   nothing more.
2. **A fresh signed-in account per test**, from the harness's own account
   fixture. Never sign a parallel spec in as a shared fixed account. A per-test
   account also means you never need a "wipe leftovers for a clean slate"
   preamble: a new account IS a clean slate.
3. **The exclusive tag (`e2e.exclusive_tag.tag`) in the test title**: last
   resort, for a test that reads or writes ACROSS other tests' data. It routes
   to a serial project (`e2e.projects.exclusive`) the runner starts as its OWN
   invocation once the parallel one has exited, so it runs alone. **Slow or
   stateful is NOT enough to qualify: only whole-database reach is.**

**Each phase runs, and answers, for itself.** A test runner's project
dependency does two things, and only the first is wanted: it ORDERS the
dependent after its dependency, and it SKIPS the dependent wholesale the moment
a dependency test fails. Inside one invocation, one timing flake in the
parallel phase hides every exclusive test, and the run's only verdict is the
red that caused it - a skipped test reads as nothing at all. So the phases are
sequential invocations (ordering kept, skip dropped), each writes its own
report and its own traces, and the runner prints one row per phase before its
verdict line: tests, passed, failed, **did not run**. A phase is passed only
when every test it collected executed and none failed; a failed run's verdict
line names each phase's verdict, so "did not run" is on the line a reader
actually reads. **A skipped test is never a pass.**

Tuning is a **plateau, not a point**: a range of worker counts lands within a
couple of percent of each other on wall-clock, and the default
(`e2e.workers_env_var.default`) is picked on the safe side of it rather than at
the nominal fastest. A contention marker on the shared backend rises
monotonically with worker count, so workers past the plateau load it harder for
no wall-clock gain, and CPU is not the constraint. **Past the plateau, one
machine has one run's worth of capacity**: shards in separate worktrees on the
same machine queue on the machine-wide lock (section 7.1) rather than overlap,
so they cost the sum of their runs. Take the wall-clock, run fewer specs, or
run on another machine. The install's `CONTEXT.md` carries the measured
plateau.

Triage: an explicit per-invocation worker flag beats the environment default,
so reproduce a suspected parallelism flake serially at one worker. Per
`/definition-of-done` Rule 4, a failure caused BY parallel execution is a
harness bug to fix, not a reason to serialize the suite or retry until green.

## 6. Run artifacts: one shared location, readable by every agent

Every run writes its server logs AND the test runner's output to a single
machine-wide directory outside any checkout (`e2e.artifacts.root`, overridable
through `e2e.artifacts.root_env_var`), with a stable `latest-<worktree>`
pointer, and the path is echoed at the end of every run. Three reasons it is
not in the repository, each a failure the in-repository location produces:

- **Cross-agent readable.** Fleet sessions work in separate worktrees, so a
  repository-relative path is private by construction: one agent cannot open
  another's failing run. This is the shared spot: to analyse someone else's
  run, read their directory directly.
- **It survives its own re-run.** The test runner WIPES its own output
  directory at the start of every run, including when it aborts in global setup
  before a single test runs. These artifacts exist to diagnose *intermittent*
  failures, and the first response to one is to re-run and see if it
  reproduces, so a location inside the test runner's output directory destroys
  exactly the evidence just captured.
- **The stack teardown deletes the server logs outright**, and teardown runs on
  every non-reuse run, so without a copy taken first a failing run's backend
  log is gone by the time anyone looks. That log is what separates a function's
  own error path from the runtime dying underneath it; a probe reporting only an
  HTTP status cannot tell those apart.

Collection is unconditional, not failure-only: a green run's logs are what you
diff the next red one against.

**The root is OVERRIDABLE and the runner PRUNES under it, so it is validated
before it is used - and on a harder rule than any other knob.** Keeping only
the last N runs per worktree means the runner runs `rm -rf` under a path an
operator supplied, which makes a malformed value destructive rather than merely
odd: an artifact root containing whitespace, fed through an unquoted shell
expansion, splits into fragments, and every fragment after the first is
RELATIVE - so the deletion lands under the runner's own working directory, i.e.
the checkout. Require an absolute path with no whitespace, that is neither the
filesystem root nor anywhere AT OR INSIDE the checkout, refuse anything else as
a usage error BEFORE the run boots, and treat empty as unset. Make the checkout
test a PREFIX test, not an equality test - `<repo>/artifacts` is perfectly
absolute and sits in exactly the place the artifacts are designed never to
live - and refuse an UNNORMALISED spelling (a repeated slash, a `.` or `..`
component) so that prefix test is exact without resolving anything, which
matters because the root need not exist yet. Do both layers: validate the
value, and reconstruct the deletion target as `<validated root>/<single
basename>` rather than reusing whatever the directory listing emitted. One
layer over an `rm -rf` is one malformed value away from deleting the checkout.

## 7. The runner owns the server lifecycle

Do not boot the stack by hand for a normal run: the runner delegates the whole
lifecycle to the dev stack script, brings it down for a cold boot, and runs
each phase against the **mock services** (deterministic, zero API cost) with
its seeding done for it. **It takes over and tears down THIS worktree's stack
only**, so it never touches a neighbour's. What protects that neighbour must be
the dev script's per-PROCESS ownership check (a process belongs to the worktree
it runs in), **not** port separation: the reset runs before a port slot is
claimed, so a dev script that tears down by PORT kills whichever stack holds
the default ports, on every run. Every port is derived from the worktree's slot
artifact (`e2e.ports.slot_artifact`), never from a literal. The install's
`CONTEXT.md` carries the phases, the flags and the port map.

### 7.1 ONE RUN PER MACHINE: NOT COLLIDING IS NOT THE SAME AS NOT CONTENDING

**Parallel runs across worktrees are NOT supported. They QUEUE.** Separate
worktrees get disjoint ports, emulators and dev servers, and share one box's
CPU, RAM and disk - and a suite that contains any wall-clock instrument (how
promptly a screen paints, how long an animation stalls) then measures *the
machine* rather than the app. The starved run reds a spec that has nothing
wrong with it, and **the failure text names the spec and never the
neighbour**, so the cost lands on whoever reads it next. The install's
`CONTEXT.md` carries the measurement.

So the runner takes a **machine-wide lock** (`e2e.lock.library`) for the whole
run, on a fixed path outside every checkout (`e2e.lock.lock_file` in the
directory `e2e.lock.dir_env_var` names, defaulting to `e2e.lock.dir_default`:
the same machine-global state root the port slots use, so there is one place
per box saying what this repository is doing). Four properties are the whole
design, and each is a failure mode somebody would otherwise re-discover:

- **A waiting run names WHO holds the box** - pid, start time, worktree, worker
  count, invocation - from a sidecar the holder maintains (one per holder in
  `e2e.lock.holders_dir`), and prints a heartbeat while it waits
  (`e2e.lock.heartbeat_env_var`, default `e2e.lock.heartbeat_default_s`).
  Silence for twenty minutes is indistinguishable from a hang.
- **The wait is BOUNDED** (`e2e.lock.timeout_env_var`, default
  `e2e.lock.timeout_default_s`) and gives up with its OWN exit code
  (`e2e.lock.timeout_exit_code`), distinct from the suite-failed code and from
  the runner's REFUSED code (also "nothing ran", but for a reason inside the
  checkout rather than on the box). **That exit is a NAMED "nothing ran", never
  a verdict about the code** - no spec executed, so the run says nothing either
  way. A caller that reads it as "the suite failed" re-creates the defect this
  closes, one layer up.
- **The lock is a kernel advisory lock (flock(2)), not a claim file.** It is
  released when the holder dies by ANY means, SIGKILL included, so there is no
  stale-lock class and no liveness protocol to get wrong. Any sidecar is
  *information* and must never gate acquisition. **The corollary bites**: a
  child process inherits the lock's file descriptor and HOLDS the lock for as
  long as it lives, so every call site that spawns a surviving daemon must
  close that descriptor. The dev stack backgrounds its emulators and server,
  and a reuse-mode run deliberately leaves them up - miss the close, and one
  run owns the box until somebody tears that stack down by hand. (macOS ships
  no `flock` command; a runner meant for both systems takes the lock through a
  language runtime's binding, such as Python's `fcntl.flock`.)
- **There is no escape hatch that simply disables it.** Such a flag gets
  reached for exactly when the box is busiest, which is the moment it must not
  be. The one sanctioned way to run beside somebody (`e2e.lock.share_flag`)
  takes the lock SHARED, requires a filter, and caps the worker count
  (`e2e.lock.share_workers_env_var`, default `e2e.lock.share_workers_default`) -
  and is for FUNCTIONAL iteration only, never a wall-clock or geometry
  measurement, which is precisely what a contended box corrupts.

Plan-only and help take no lock: they boot nothing, and a preview that queued
behind a full run is a preview nobody uses.

**The lock is only as strong as the OLDEST checkout on the box.** A worktree
cut before the lock landed runs lockless and starves a lock-holding run, with
nothing to say so. Same shape as the port-sweeping dev script above, and the
same remedy: pull, or grep the runner for the lock library
(`e2e.lock.library`) - no match means that checkout is lockless.

**A queued run is NOT a runaway run**, and the ~2x-ETA rule (section 3.5) must
not kill one. The ETA clock starts when the run ACQUIRES the lock; before that
it prints the interlock's waiting heartbeat and is behaving correctly.

## 8. DO NOT `import` AN APP CONSTANT INTO A SPEC TO ASSERT ON IT: IT FAILS AT COLLECTION, AND A FILE THAT DOES NOT RUN LOOKS LIKE A SUITE WITH NOTHING TO SAY

Asserting a screen's copy against a pasted string literal is a real hazard: the
literal drifts by one character, the test silently exercises a *different*
branch, and it stays green. The obvious fix is "import the constant instead of
pasting it", and **that instruction is not implementable here.**

Importing the constant pulls its module's whole transitive chain into the test
runner, including native-module shims the test runner cannot type-strip. The
spec fails **at collection**, reporting no tests found, so **the whole file
stops running rather than going red**, and a file that does not run is
indistinguishable from a suite whose assertions all passed. (The install's
`CONTEXT.md` names the measured import chain.)

**Not every such import fails, and the ones that SUCCEED are the second half of
this hazard rather than an exemption from it.** Where the chain reaches an
ordinary package instead of a native shim, it resolves - but from **that
module's own install root**, which may not be the spec directory's. The spec
then passes in a fully installed worktree and takes down the **entire listing**
in one that is short a root, so the damage lands on unrelated checks and reads
as a defect in whatever was being measured. Treat a spec's reach across install
roots as a cost to declare, not a thing that either works or fails loudly; the
install's `CONTEXT.md` names the live chains and the gate that diagnoses them.

**What to do instead:** read the declaration out of the source file as TEXT and
compare, with an **extraction guard that asserts the declaration was FOUND
before comparing**. A rename then fires its own named failure, instead of an
empty regex quietly matching nothing and passing.

The general rule this is an instance of: **a spec that reaches into app code
for a value must reach for the TEXT, not the MODULE**, and any extraction step
needs its own positive control, because "found nothing" and "found and matched"
must never produce the same verdict.

## 9. Companion type-checks

Run the project's type-checks (`checks.commands`) with every e2e pass; they are
part of the definition of done.

## 10. Scoping a filtered run: the defect class, because the wrong behaviour is a pass

A filtered run that quietly executes the **whole** suite and reports green is
the failure this section exists for. Its symptom is a pass, so nothing but a
probe whose first check is a positive control can detect it; the install's
`CONTEXT.md` names that probe and carries the measured before and after.

Three things generalise beyond any one harness:

- **A dependency between test projects is not free.** Playwright runs a
  dependency project **IN FULL, ignoring your filter** (measured 2026-08-19), so
  a filter that happens to match a test in the dependent project silently widens
  to everything - and it SKIPS the dependent wholesale when a dependency test
  fails (section 5). Reproducing the ordering one level up (run the projects as
  sequential invocations, dependencies disabled) keeps the isolation guarantee
  **only while the dependency is a mutual-exclusion device and not a real data
  prerequisite**. Write that condition down where the code is, because the day
  someone gives it a genuine prerequisite, this stops being true silently.
- **The cheap check agrees with you in exactly the case you must not trust
  it.** A dry `--list` without the no-dependency flag reports the full count
  precisely when the dependency is pulled in, and the scoped count in every case
  where nothing was wrong. So it disagrees with the real run only in the one
  case that matters. Pass the no-dependency flag when you list, or read the
  run's own "Running N tests" count.
- **A filter matching nothing must be a loud error, never a silent full-suite
  fallback.** Check that before trusting any filter you have not run before.
  **In Playwright it IS loud, and loud is not the same as legible: a zero-match
  filter prints `No tests found` and exits 1 - the SAME exit code as a real
  red.** So the exit code alone cannot tell *your change broke a test* from
  *your filter matched no test*, and the second reads as the first, which sends
  the reader debugging code that is fine. **And `-g` is a REGEX, not a
  substring**, so a title carrying `(`, `[`, `+`, `?` or `.` matches something
  other than what was typed. **Read the run's own test COUNT before you read
  its exit code**, every time. This is also why the runner infers the suite
  from a spec path: without that, a filter runs against every project and the
  one it does not match fails the whole run on a bare `No tests found`.

### 10.1 The folklore, which was worse than the bug

A careful, correct measurement taken on one unusual input and written up as a
universal claim ("this runner cannot scope a run") becomes folklore that
outlives the fix, and folklore with a remedy attached is worse than the bug it
describes. Two lessons, both cheap to repeat:
- **A claim generalised from one instance inherits that instance's
  authority.** State the boundary you measured, not the headline it suggests.
- **A remedy stated beside a measurement inherits the measurement's
  authority.** An untested workaround in a skill file is more dangerous than no
  workaround at all.

### 10.2 Fast iteration below reuse mode

For tighter loops than reuse mode, hand-boot the mock-service stack and call
the test runner directly from the spec directory (the install's `CONTEXT.md`
has the two commands). That path never passes the exclusive project, so none of
the scoping defect class above applies to it.
