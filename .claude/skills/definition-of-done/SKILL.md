---
name: definition-of-done
version: 1
description: >
  What done means for any change, as seven numbered rules that the rest of an
  install cites BY NUMBER: run the post-task consistency scan; drive the
  sanctioned entry points rather than an ad-hoc equivalent; land it (merged and
  pushed to the landing branch (`repo.landing_branch`) without asking, with
  every residue removed and verified - git's, the files written outside the
  worktree, and the system state the task changed - so the machine ends where
  it started, and the one carve-out for UI work the human principal is actively
  reviewing); the e2e coverage each kind of change owes and the rule that the
  whole suite is never run locally; and the mandatory UI screenshot gate, with
  the design-parity sub-gate over every screen and state on the tester's step
  sheet plus every screen the task froze or moved - run by an agent that did
  not build the feature, INCONCLUSIVE blocking until the check is fixed or
  waived by name - and the coverage that gate explicitly does NOT claim; and
  the human dev-build pass every feature gets before it merges - preceded by
  the agents' visual sweep, by the builder showing the requester, in the
  feature's chat thread, a video per platform and, where there is a design
  file, the design diff maps, and by the feature checklist passing its
  checker, run by a non-builder; driven step by step by the agent, asked for
  friction, and TIMED from the agent's own start and end posts in the thread
  (or from the dev server's session log, where it writes one), so an untimed
  or too-short pass does not merge; and the rule
  that a feature ships complete - every surface it touches (screens, server
  half, analytics, e2e coverage, push-notification copy, store listing per
  storefront) in one landing, with the SCOPE cut to a smaller feature that is
  complete on its own rather than a part landed and the rest promised. Also
  owns the feature checklist: one file per feature, made from this skill's
  template when the work starts (its design section before any code), every
  item pointing at evidence, checked by this skill's script before any build
  goes to a tester - a feature's or a release candidate's - and re-read after
  every compaction. Load before declaring ANY change complete, and when a
  feature's work starts.
requires_install: false
---

# Process: shipping changes (definition of done)

**Where it applies.** Rules 1 to 4 bind any code project. Rules 5 and 6 bind
any project with a user interface: Rule 5 every change to a screen or component,
Rule 6 every feature merge, its pass run on the development build `CONTEXT.md`
names. Rule 5's screenshots are never conditional. Exactly two facts about a
project lift a whole step, and each step says so where it applies: a project
with no user interface at all, which Rules 5 and 6 do not bind; and a project
with no design file (`figma.file_key` set to `null`), for which Rule 5's
design-parity half, the checklist's design sections (1a, 1b, 1c and 4) and the
design pack in Rule 6's presentation lift, and the checker accepts those
sections empty. One key lifts part of one step: `figma.registry_probe` set to
`null` lifts only the probe run in Rule 5's third proof, never the registry the
probe would read. Nothing else lifts anything. Rule
7's surface list is written for an app with a server half, shipped to users
through stores; for each surface the feature states what it ships there or
`none`, with the reason (Rule 7).

**What the install names.** The install's `CONTEXT.md` for this skill
(`fleet where definition-of-done CONTEXT.md`) names its landing branch and where
its worktrees live, its e2e runner's scoped invocations, its consistency-scan
prompt, its design file and pages, the human principal, the design's approvers,
and the measured instances behind the rules below. Its `config.json` (`fleet
where definition-of-done config.json`, made from `config.example.json`) carries
the values this file refers to by key. **A relative path in that `config.json`
is relative to the repository root, not to the file** - the exception to
`/claude-skill` section 2's rule for a SPECIFIC config - because each one names a
place in the project's tree: `checklist.dir` is matched against `git diff
--name-only` output, and the commands are typed from the repository root. This
file names no skill of the install's own; where a rule leans on one, it names the
ROLE, and `CONTEXT.md` names the install's skill or document that fills it:

| Role | What it is |
|---|---|
| the UI evidence gate | the screenshot procedure Rule 5 requires: the presentation viewports, and the per-state annotated pack a design-verified screen owes |
| the design verification kit | the instrument that gives a screen and state a pixel verdict against its frame, and the bar a PASS meets |
| the design-freeze procedure | how frames move from the incoming page to the current page of the design file, including its sections on editing a shared component master and on the current page as a mirror of the landing branch |
| the visual sweep | the agents' sweep over a build's screens before a tester gets it (Rule 6), the parity check it runs before a build is served, and the compact visual row it leaves on the tester's step sheet |
| the chat transport | where a feature's thread lives: the requester is shown the work there and the tester's pass is driven there (`/chat-transport`) |
| the roadmap | where a follow-up is filed as a feature of its own (Rule 7) |

**A role the install does not fill is not a skip.** `CONTEXT.md` then states how
the install meets the rule that role serves by other means. Where it cannot, the
change that rule binds is blocked, and the reason is reported to the human
principal; it is never reported as skipped. Only what "Where it applies" lists
lifts a step, or part of one.

**Seven rules, and their NUMBERS are part of the contract.** Agent charters,
other skills, prompts and design documents cite these sections by number
("Rule 3", "Rule 4(b)"), usually with no title and no quote beside it. So
**renumbering or reordering them silently repoints every inbound citation at a
different rule**: nothing goes red, and the next reader follows a citation to a
gate they were never sent to. Append a rule at the end, split one into
sub-rules under its own number, but never renumber.

| | Rule | Binds |
|---|---|---|
| **1** | Run the post-task consistency scan | every change |
| **2** | Drive the sanctioned entry points | every run, and every test |
| **3** | Land it: merged, pushed, machine back as it was | every change |
| **4** | e2e coverage, and how much of the suite to run | every change to code the suite drives |
| **5** | Show the screenshots | every change to a screen or component |
| **6** | A human tests the feature on the dev build, the agent drives, the pass is measured | every feature merge |
| **7** | A feature ships complete | every feature |

**This table is machine-read**: `check_checklist.py` takes the rule numbers
from its `| **N** |` rows, so a feature checklist owes a row per rule listed
here. Keep that row shape; a table it cannot read makes every checklist run NO
VERDICT rather than pass.

## The feature checklist: one file per feature, carrying the evidence for these rules

**Every feature keeps one checklist file, made from
`feature-checklist.template.md` beside this file when its work starts**, at
`checklist.dir/<feature-slug>.md` (the path the install's `feature_checklist`
convention names, `fleet settings conventions.feature_checklist`; nothing checks
that the two agree, so a change to one changes the other), committed on
the feature branch and landing with it. A screen task inside a feature that
already has one adds its rows there: one feature, one file. The template
documents the format. Its sections:

1. **Design, filled before any code.** (a) The design read before approval: an
   agent that did not draw the design reads every note against its frames and
   the past rulings, and lists the contradictions plus everything the design
   removes from today's app; the design's approvers (the design-file owner or
   the designer, never the agent that drew the design) rule on that list -
   `CONTEXT.md` names the people in both roles - and only then is the design
   frozen (the install's design-freeze procedure). (b) Every frozen frame,
   mapped to the plan item that builds it. (c) Every screen the feature touches
   that has no frame, flagged `NO DESIGN` with who was asked - before code, not
   at the tester's pass.
2. **Scope**: each agreed scope item, with the spec, flow or clip that proves it.
3. **Rulings after approval**: each landed on its frame and note, re-frozen
   before more code is written against it, and implemented by a named commit.
4. **Pixel verdicts** for Rule 5's parity scope.
   4b. **Bug hunt by an agent that did not build it**, before the tester sees
   the build. The hunter is a persona other than the builder, and may hand the
   hunt to a fresh subagent whose brief is ONLY section 2's scope and the
   build - no builder notes, plan or checklist, because each carries the
   builder's model of the feature, the model that produced its bugs. It hunts
   on both platforms where the feature is native, the states after a tap
   included (an open sheet or menu, the screen after save, skip or post), and
   the edge cases (empty, the longest text, errors). One run row names the
   hunter, the build (a commit the hand-off contains) and the evidence; each
   finding is `FIXED in <commit>`, `WAIVED by <name>` or `NOT A BUG: <reason>`,
   and a hunt that found nothing records one `NONE` row, because an empty table
   reads exactly like a hunt never run.
5. **These rules' gates, by number** - never their text, so this file stays the
   one source. One row is also read by its label: `6 - presented to the
   requester`, Rule 6's presentation to the requester, whose evidence is the
   chat message's permalink, matching `checklist.permalink_pattern`.
6. **The hand-off**: who ran the checker, on which commit, when.

A project with no design file (`figma.file_key` null) has nothing for sections
1a, 1b, 1c and 4 to hold: they stay in the file, with their tables, and may be
empty.

**An item is done only when it points at evidence**: a path that opens, or a
URL - a test, a pixel verdict, a clip. **Evidence has to outlive the landing**,
because a release candidate checks the same file again after the feature has
merged (`/release` section 9): a committed path, a path under the agent's own
`artifacts/` (Rule 3's carve-out), or a link to the post that carries the
result. A scratch path does not survive Rule 3's cleanup - so a verification
tool that writes to a temporary directory by default is pointed under
`artifacts/`, or its result is posted and linked.

**`check_checklist.py` beside this file checks it:**
`python3 "${CLAUDE_SKILL_DIR}/check_checklist.py" <checklist.md | directory> ... [--expect <slug>[,<slug>...]]... [--served <worktree>]`,
from inside a checkout of the feature branch. It reads `checklist.dir`,
`checklist.waivers`, `checklist.permalink_pattern` and `figma.file_key` from the
install's `config.json` (`--config <path>` overrides that, for tests). With
`figma.file_key` null it accepts empty sections 1a, 1b, 1c and 4 and prints a
`NOTE` line saying so; a config with no `figma.file_key` at all is NO VERDICT,
because an absent key must never relax a gate. Exit `0` pass; `1`
findings, each printed as `<file>:<line>: <what is wrong>`; `2` NO VERDICT - a
malformed or unreadable file, a config that does not resolve, or a run that
checked nothing. **Never read 2 as a pass**: nothing was judged, so nothing was
found. Several files in one run each get a verdict line and the run exits with
the worst (2 over 1 over 0); `--expect` names the features that must have a
checklist, so one with none is a finding, never a skip. It refuses an empty
cell, a status outside its section's closed vocabulary, `TODO`, an
`INCONCLUSIVE` or `FAIL` pixel verdict, `WAIVED by` a name not in
`checklist.waivers`, evidence that does not open, a rule number from the table
above with no row, uncommitted changes to the file, a `6 - presented to the
requester` row that is missing, `DONE` without a chat message permalink
matching `checklist.permalink_pattern` as its evidence, `N/A` while the header
names screens, or `AFTER HAND-OFF`, **a runner who is the builder**, and a
missing or unfinished bug hunt (section 4b: no hunt recorded, a hunter who is
the builder, a build or fix commit the hand-off does not contain, an empty
findings table, a finding with no disposition). With `--served <worktree>` it
also refuses a checklist with no recorded hand-off in section 6, a served HEAD
that does not contain the hand-off commit, and - with one checklist - any file
outside `checklist.dir` changed between the hand-off commit and the served
HEAD; with several checklists, a release candidate's serve, only the contains
rule applies, because the RC carries other features' commits. `--served` reads
git and nothing else: the build being served is identified by its worktree's
HEAD. On a pass it prints a `SERVED` line. Its header is the full contract.

**An agent that did not build the feature runs it**, before any build goes to
the tester (Rule 6). The runner is the identity git commits with in the
checklist's clone, compared with the header's builder. **That is evidence, not
authentication**: anyone can set an identity. What it buys is that
self-certification takes a deliberate act instead of happening by default, and
section 6 names who ran it, on which commit. An agent's subagent runs under the
identity of the agent it works for, so a builder's subagent is the builder.

**Why a file, and why a checker someone else runs.** A gate's scope held only in
a session's context narrows to whatever that session last looked at, and a
compaction drops it outright; and the builder reads the work through the very
model that produced its gaps. A file survives compaction - a session building a
feature re-reads its checklist after every one (`/agent` section 4) - and a
checker run by somebody else cannot narrow without a finding saying so.

---

## Rule 1 - Run the post-task consistency scan

**When the task's code is finished and before it is declared done, dispatch a
read-only subagent to find everything the change made stale.** The prompt is not
improvised: the canonical text lives at `process.consistency_scan_prompt`, which
is also where the project's known fan-out invariants are recorded. Fill in the
change summary it asks for - the names introduced or renamed, the surfaces
changed (collections, paths, callable signatures, route URLs, env vars), the
behaviours changed - and send it.

**Why it is a rule rather than a habit: a change lands in the file you edited,
and its consequences land in files you never opened.** The author is the one
person structurally unable to see them, because the mental model that made the
edit correct is the same model that says nothing else is involved.

The scan's real subject is **fan-out invariants**, of the form *for each X, do
Y*. Derive the X set by grepping for the structural pattern, **never from
memory**: a set recalled rather than measured is missing exactly the member that
was added since you last looked.

Three properties are what make a scan worth its cost, and each is a real failure
mode rather than a formality:

- **A grep hit is a question, not an answer.** The same substring is a defect in
  one file and correct text in the next. Every reported item must have been READ
  in context and be quoted in the report. A report that is pure grep output
  means that step was skipped: reject it and re-run rather than processing it,
  and spot-check two or three items by opening the files yourself before
  trusting the rest.
- **The ruled-out list is part of the report.** Without it there is no way to
  distinguish a scan that opened forty candidate files from one that opened
  four.
- **Every item is closed, not filed.** Fixed, deleted, or given a one-line note
  saying why it is deliberately untouched - and the list, with what was done to
  each item, goes in the final task summary. If closing it materially expands
  the task, surface that rather than silently growing scope.

## Rule 2 - Drive the sanctioned entry points, never an ad-hoc equivalent

Two faces of one rule, and both are about a seam nobody reads.

**Operating the project: one job, one entry point.** Running the dev stack
(`repo.dev_stack_command`), building and deploying (`repo.deploy_command`) and
running the suite (`e2e.runner`) each have exactly one; `/tooling-index` names
the rest and is what you check before writing any command of your own. **Never
hand-roll the equivalent invocation.** The entry point is where the environment
materialization, the port claim, the required flags and the guards live, and a
hand-rolled command omits whichever of those its author did not know about. The
result is not a failure - it is a run that differs from every other run of the
same thing, in a way nothing reports. A key set to `null` means the project has
no single entry point for that job, and `CONTEXT.md` says what stands in for it.

**When the entry point cannot do what you need, extend the entry point.** A
one-off command that works is the first half of a second, undocumented way to
run the project, and the two then drift.

**The rule is what lets defensive dead code be DELETED rather than kept.** A
fallback reachable only by an invocation this rule forbids is not a safety net;
it is an unexercised path that converts a delivery failure into a silent
wrong-target success. `CONTEXT.md` carries the measured instance.

**Testing: drive the REAL user entry points.** A spec navigates the route the
user lands on and operates the control the user taps. It does not arrange state
by reaching past the seam that state normally arrives through. **A bypass
asserts everything after the seam and nothing about the seam**, which is where
the defect usually is. Where a bypass is genuinely required - seeding a
returning-user fixture, forcing a failure a real run cannot produce - it is a
**named, sanctioned bridge**, declared as one in the spec, never an
undistinguished shortcut. The same holds for the stack underneath: `e2e.runner`
owns the stack lifecycle, so the suite boots through it and not through a
hand-started set of local service emulators.

## Rule 3 - Land it: merged, pushed, and nothing left behind

**Merging and pushing to the landing branch (`repo.landing_branch`) is the
default delivery, done WITHOUT asking, as soon as every gate is green.** Not
"ready to land pending review", not held for a live eyeball. Work parked on a
branch is undelivered: nothing ships from it, nobody else builds on it, and it
rots against a moving trunk.

**The one carve-out: UI work the human principal is actively reviewing.** There,
and only there, the finished package is presented and merged on their approval,
because the point of the review is to change the work before it lands. It also
applies when a task explicitly asks for a pre-merge approval. Outside the
carve-out the Rule 5 screenshots are **delivered, not blocking**: they are shown
in the same turn as the "done" claim, and the push does not wait on them being
looked at.

Three parts follow, and a change satisfying two of them is not done.

**1: It is pushed to the landing branch.** Merged and pushed, and you have
confirmed it arrived (`git merge-base --is-ancestor <sha> origin/<landing
branch>` after a fetch, or the landing branch's tree carrying the content). A
green exit code is not arrival: read the content back.

**2: Every local residue is cleaned up.** In order, and verify each rather than
assuming:

```bash
git worktree remove <path>          # the worktree
git worktree prune                  # its stale registry entry
git branch -d <branch>              # the local branch (-d, not -D: it must be merged)
git push origin --delete <branch>   # the remote branch
```

Then prove it: the directory is gone, `git worktree list` does not name it,
`git branch --list <branch>` is empty, `git ls-remote --heads origin <branch>` is
empty.

**Where the install's branch names carry the agent's name** (its `branch_naming`
convention; `/worktree-workflow` section 1), **that is what makes the sweep
possible**: `git branch --list '<agent>/*'` and `git ls-remote --heads origin
'<agent>/*'` list everything of yours still outstanding, local and remote, in two
commands. Run them at the end of a task rather than trusting that you remembered
every branch you cut - and keeping the namespace clear is not only tidiness: git
stores branches as nested refs, so a leftover ref at `<agent>` or
`<agent>/<type>` blocks every future branch of yours outright.

**Harvest gitignored artifacts BEFORE removing a worktree.** Reference trees,
screenshot packs, capture scripts and run artifacts are invisible to every
git-shaped check - they do not show in `status`, they do not block `worktree
remove`, and they die silently. The worktree's own `workspace.md` carries a
`harvest first` field for this (`/worktree-workflow` section 2).

**A half-cleanup is worse than none.** A removed directory with a live worktree
registry entry makes `git worktree add` refuse that path later, and a refusal
routed around is how one agent ends up operating in another's tree. Always
`prune`.

Leftovers are not untidiness, they are a live hazard: a machine that carries
dozens of worktrees at once - `CONTEXT.md` records the install's measured peak -
reaches the point where a finished workspace and an abandoned one are
indistinguishable, and the one holding the only copy of something is one reap
from losing it.

**3: The machine goes back to the state it was in.** The four commands above
clean what git can see, which is the smaller half. **The test is not "is the repo
clean" but "is this machine in the state it was in before the task started"**,
and you answer it by walking back what the task did, not by reading `git
status`:

- **Files written outside the worktree** - scratch directories, temp scripts,
  downloaded assets, generated reports, evidence packs, tarballs, capture output.
- **System state changed** - a service started or stopped, a unit installed, a
  process left running, a port or an emulator still claimed, a background job
  still polling, a config or credential written, a file moved or renamed as
  scaffolding rather than as the deliverable.

**Five carve-outs, and they are the only five**: entries in the knowledge base
(`/knowledge-base`), your own `artifacts/`, `state/` and `blockers/` directories
(`/agent` section 3), and **a gate's unread failure evidence** - a transcript or
scratch a gate kept outside the worktree because a check went non-PASS, kept
until somebody has read it. The first four are durable by design - the point of
writing them is that they outlive the task - so they are what you keep, not what
you clean. `state/` especially: it holds positions, cursors and locks that cannot
be recomputed, so "cleaning" it is not tidying but data loss, and the symptom is
silence rather than an error. `blockers/blockers.md` for the same reason and a
sharper one: a row in it is a thing SOMEBODY ELSE owes you, recorded nowhere
else, and the blocker chase (`/agent` section 6) chases exactly what is in that
file - so a task that "cleans up" the rows it added has silently cancelled its
own follow-up, and nothing anywhere reports it. The fifth is the opposite of
durable, which is why it needs naming: it exists only on the run that produced
it, and a failure that does not reproduce leaves no second copy - so deleting it
unread destroys the only record of the event, and the re-run that follows
destroys it again. It is a carve-out only while it is unread: harvest it, act on
it, then remove it by hand. A green run writes none, so a sweep over a clean tree
removes nothing, and the carve-out costs a tidy task nothing at all. `CONTEXT.md`
names the install's capturing gate and where it writes; that gate's own header
owns what a capture contains and why nothing reaps it.

**Git-shaped checks cannot see any of this, which is why it survives.** A clean
`git status`, an empty `git worktree list` and a deleted remote branch are all
perfectly consistent with a running service, a held port and a gigabyte of
scratch output. The residue that outlives a task is the residue no gate looks at.

**State you changed and did not change back is the dangerous half, not the
disk.** Files waste space; a service left in the wrong state, a port still
claimed, or a half-installed unit is a defect the NEXT task inherits and reads as
its own bug - and the failure text names the symptom, never the task that caused
it. `CONTEXT.md` carries the measured instances.

**When something must survive, name it in the final report**: what survives,
where, and why. An artifact worth keeping is worth a line saying who keeps it;
everything else dies with the task.

## Rule 4 - e2e coverage: what each kind of change owes, and how much to run

Which one you are doing decides what you write, and the order matters in the
first case.

- **A functionality bug: replicate the bug first.** Write the e2e test that
  reproduces it and watch it FAIL on the unfixed code. Then fix the bug, and make
  sure that test passes. A test written after the fix proves only that the code
  does what it currently does; a test that never failed has not been shown to
  detect anything.
- **New functionality: add e2e tests covering it, once the functionality is
  totally finished** - not per-fragment while it is still moving.
- **A change to existing functionality: update the affected tests in the same
  change.**

### Never run the entire suite

**Do not run the whole e2e suite.** You may run **individual tests** - and you
should, when your change touches the same functionality those tests cover. Scope
the run through the runner (`e2e.runner`): by spec file, by test title, or as a
dry run that lists what would run and boots nothing, as far as the runner offers
each. `CONTEXT.md` carries the install's exact invocations, and the date from
which its scoping is known to be reliable - which matters, because a filter that
silently runs the whole suite and reports green looks exactly like a correctly
scoped one (`/e2e-suite` owns that defect class).

Identify the affected tests by grepping the route, screen number, component or
callable name across the spec directory (`e2e.specs_dir`) - not by running
everything because it is easier than looking. Load `/e2e-suite` for run
mechanics and spec conventions.

**Report the shape of what you ran, never imply more.** Name the specs: "ran
`cart.spec.ts` and the new `coupon-expiry` test" - not a bare "e2e green".

### Prove the check fails for the REASON its name claims - and attack your own pushed work

A check that reds under a mutation has cleared the low bar. It can still be
measuring a different thing than its label says, and a green one can still rest
on a mechanism about to reverse. Two habits close that gap, and each catches real
defects nothing else can see.

**(a) Commission an adversarial review of your OWN just-pushed commit**: brief it
as *"could this introduce another bug"*, not *"does this look right"*. Pushing
feels terminal, which is precisely when the second pair of eyes is cheapest. The
class it catches is the one the task's own gates cannot see: a predicate that is
true for more than its name says - an "is this a plain object" test that every
class instance passes - so a timestamp slips through a merge gate, and a value
the user already gave is dropped and deleted in the same write, silently and
irrecoverably. `CONTEXT.md` carries the install's worked instance.

**(b) Prove the test tests what its NAME says: a regime control, distinct from a
negative control.** A negative control asks *"can this go red?"*. A regime
control asks *"is this exercising the case it is named for?"*. Shapes it
catches, each a check that could fail, did fail on cue, and still measured the
wrong thing:

- a fixture that exercises the first fallback while its name claims the second;
- a sweep for personal data across every analytics event that stays **green**
  when free text is added to an event, because ordinary prose carries no `@`,
  URL scheme or slash, so the sweep is not the gate anyone believes it is;
- a widened function signature whose emitted payload is byte-identical, so it
  passes **every** check on the payload's shape and keys and is caught only by a
  check on the signature itself;
- a free-text predicate blind to a string type reached through a **named**
  alias, because it recognises only builtin and numeric-union parameter
  types.

**The corollary that catches the rest: when a check or a comment rests on a
REASON rather than an observation, ask whether the reason is about to stop being
true.** A rationale that is accidentally right is the most expensive kind: it
reads as verified and rots silently. The shape: a retention argument that is
correct for deleting an account and wrong for merging one, because both rest on
the identical primitive. `CONTEXT.md` carries the install's worked instances.

**(c) An acceptance criterion must be able to produce its own evidence.** Before
a criterion enters a brief, its author states two things: the command that would
SATISFY it, and the mutation that would make it FAIL. A criterion that can never
be satisfied, or can never fail, is not a criterion - and an engineer handed one
has only two moves, both bad: manufacture the evidence, or stop. Three shapes: a
grep whose pattern cannot match by construction; a stamp condition requiring the
ABSENCE of a block another task deliberately keeps, so it can only ever answer
*not landed*; and a demand for a RED exhibiting `undefined` inside a `string[]`,
unconstructible without defeating the type that makes the check mean anything.
**And re-derive any census after the last MERGE, never after the last edit** - a
gated tree and a pushed tree are different trees, and a branch gated against a
census of N entries lands against N+1.

**And when you cannot prove something, say the smaller true thing.** A statement
that names what was measured, what it covers, and the one property you could not
establish is worth more than a confident claim of that property, and it tells the
next reader exactly where to look. `CONTEXT.md` carries the worked wording.

## Rule 5 - Always show screenshots of UI work

Any implemented or changed screen or component: capture screenshots and present
them to the human principal, via the file-sending tool, in the same turn as the
"done" claim.

**A feature is not done until the human has been shown the screenshots.** Don't
describe the change in prose and call it complete - the images go to them first.

The install's UI evidence gate sets the canonical viewports and the per-state
annotated pack a design-verified screen owes.

### Native-media components: both platforms, before landing

In a cross-platform mobile app, a change to a component that renders through a
platform-native module - Lottie, the camera preview, blur, video, haptics - is
verified on the iOS simulator AND the Android emulator before it lands, whichever
platform the reporter used. These modules have one implementation per platform;
a web render or one emulator cannot see the other platform's behaviour, and a
load gate, a callback or an intensity scale that is correct on one is routinely
wrong on the other. The evidence is a clip per platform of the changed behaviour
(`/device-emulators`), presented with the "done" claim like the screenshots
above. A change that could not be run on one platform is reported as unverified
there, never as done.

### Figma parity: every screen and state on the tester's step sheet, plus every screen the task froze or moved

Applies where the install has a design file (`figma.file_key`; `null` means it
does not, and a report says the sub-gate was skipped). Binds every feature whose
build goes to a tester, and any task that froze frames into the **current page**
(`figma.pages.current`) of the design file - the page that mirrors what is on
the landing branch; current is what is on the landing branch, period. **Its
scope is every screen and state on the tester's step sheet (Rule 6), plus every
screen the task froze or moved on the current page.** The freeze copies this
task's frames from the incoming page (`figma.pages.incoming`) at the start of
implementation and deliberately puts the current page **ahead** of the landing
branch by exactly those frames; **this gate is what closes that gap and makes
the page a true mirror again.** The install's design-freeze procedure owns the
two-phase freeze; this is its closing gate, and it is **per task**, not per page.

**Why the step sheet and not only the frozen frames: the tester walks every
state on the sheet, and a gate scoped to the frames a task froze leaves every
other one for the tester to find by hand** - a menu, a sheet, a frozen frame the
plan left out. Those are exactly the defects a pixel check catches and a person
should never have to.

It binds a task that **edited a shared component master** just as hard, even one
that froze nothing: that edit moves every frame on the current page instancing
the master, so those screens are in scope here exactly as frozen ones are (the
freeze procedure's section on editing a shared component master, whose title
`CONTEXT.md` quotes byte-exact so it stays greppable). That is the "moved" in the
scope above.

Three things are proven before the task is done, and the first of them before
the hand-off:

1. **Every screen and state in scope has a pixel verdict, recorded in the
   feature checklist's section 4**, from the install's design verification kit,
   at the bar that kit sets (`CONTEXT.md` names both). Nothing new is invented
   for this gate; it is the kit you already used, pointed at the whole scope. A
   verdict is `PASS`; `NO DESIGN` for a state with no frame, listed and never
   skipped; `AHEAD` for a state whose current-page frame another task's freeze
   has put ahead, listed and never absorbed into this gate or edited down; or
   `WAIVED by <name>`. **`INCONCLUSIVE` is not green.** An instrument that could
   not see the subject has not passed it: dynamic content swamping a diff hides a
   missing fill, which a geometry audit cannot see either, because it measures
   boxes, not fills. It blocks the hand-off until the instrument is fixed
   (masking user-supplied photos is a known fix) or the result is waived by name
   by a person in `checklist.waivers`. **The check is run by an agent that did
   not build the feature**: the builder reads the frame through the model that
   produced any defect in it.
2. **Every frame in the task's scope carrying the deletion marker
   (`figma.deletion_marker_prefix`) is gone** from the current page, **and no
   frame the task froze still wears the in-build marker
   (`figma.in_build_marker_prefix`)** once the landing is verified. Confirm both
   by *reading the page*, not by remembering that phase 2 ran. A leftover marked
   frame leaves the mirror permanently wrong, sitting next to a deletion nobody
   will later dare make; a leftover in-build mark tells every later reader that
   shipped work is still in flight.
3. **The install's design-id registry was written, and where the install has a
   registry probe (`figma.registry_probe`), the probe is green.** A freeze mints a new node id for every frame it copies and writes
   each into the one registry (`CONTEXT.md` names it), and a node id is a
   STRING - no typecheck, lint or spec can see one go dead, so without the
   registry the only symptom is a later agent getting `null` back with no way to
   tell a stale pointer from a typo. **Confirm the registry carries every frame
   this task froze by reading it**, whether or not a probe exists: a green probe
   does not prove it, because a freeze whose new ids nothing cites yet leaves the
   probe green and the registry stale. The probe reads the repository's ids back
   against the registry. **Treat any non-zero exit as not
   green, and never read a no-verdict exit as a pass because nothing was
   reported**; the probe's own header owns what each exit means. **It cannot see
   whether an id is live in the design tool** - it holds no credential - only
   whether the repository agrees with the registry; establishing the registry is
   the freeze's job, not the probe's, so a green here says nothing about the
   page. **And say what the green covers rather than "the citations are
   consistent", which reads as all of them**: a probe of this kind polices ids
   that are unregistered, ids the registry records as dead, and the positions a
   tool resolves, and a raw copy of a LIVE registered id sits in none of those,
   so swapping one live frame's id for another live frame's passes silently.
   `CONTEXT.md` states what the install's probe covers, what it does not, and the
   instrument that counts the uncovered set, because a bare number cannot be
   re-derived and therefore cannot be corrected. `figma.registry_probe` set to
   `null`: the install has no such probe, and only the probe half lapses - the
   registry is still written and read back, and the report says the probe half
   did not run rather than reading as covered. An install with a design file
   and no design-id registry states in `CONTEXT.md` how a frozen frame's new id
   is recorded and found stale instead; where it cannot, the parity gate
   blocks.

**A full-page audit of the whole current page is a SEPARATE job**, commissioned
when the human principal wants one. It is not run per task, and a task that did
not run it has skipped nothing it owed. (`CONTEXT.md` carries the page's screen
census and the date it was measured; re-derive it live.)

**State what this gate does NOT cover, every time you report it, or it will be
read as a stronger claim than it is.** It proves **the screens and states in its
scope, on the day it ran.** Specifically:

- It says **nothing** about the rest of the current page. Screens outside its
  scope are exactly as verified as they were before the task started.
- It **cannot see a silent master edit**. The shared component masters those
  frames instance are **remote**, so an edit in the library file moves frames on
  the current page with no event anyone here can observe, including a screen this
  task never opened (the freeze procedure, same section).
- It could **never** be widened into "the whole current page matches the app",
  and that is not a matter of cost. **Other tasks' freezes are in flight on that
  same page**, each one legitimately ahead of the landing branch until its own
  implementation lands, so a whole-page gate would red on work this task does not
  own and cannot close. **Pre-existing drift can also sit there**: a page can
  carry frames the app has never implemented (`CONTEXT.md` lists the measured
  instances and their dates). That drift is **reported to the human principal**,
  never absorbed into a task's gate and never "fixed" by editing the page down. A
  task owns its scope; a full-page gate would hand it everybody else's freezes and
  drift (the freeze procedure's section on the current page as a mirror of the
  landing branch, whose title `CONTEXT.md` quotes byte-exact). A step-sheet state
  whose frame another task's freeze has put ahead is the one place the two meet,
  and it is listed `AHEAD`, never verified against a frame this task does not
  own.

So report it as **"parity proven for screens X, Y, Z"**, never as a bare "Figma
parity green". A gate whose scope is left unstated gets read as total coverage,
and this gate is an instance of that failure mode, not an exception to it.

## Rule 6 - A human tests every feature on the dev build before it merges; the agent drives the pass, and the pass is measured

Binds every merge that adds a feature or changes one a user can see or feel. It
comes on top of Rules 4 and 5, never instead of them: the suite and the
screenshots see what a harness can see, and this is the pass that sees what only
a person holding the device can - a gesture that fights the thumb, a wait that
feels broken, a label that reads wrong.

**Individually, on the dev build, before the merge.** One feature per pass, on a
development build that loads the branch's code from the dev server (`CONTEXT.md`
names the commands; in a React Native app, a custom development client), by a
human tester - not on a store or tester-distribution build after the fact, where
a finding costs a rebuild per iteration.

**The agents sweep the build first.** Before the pass starts, they run the
install's visual sweep over the feature's screens. **No build goes to the tester
- first serve or re-serve - until two things hold: the parity check that sweep
defines has a verdict for every screen and state in Rule 5's parity scope (green
gates do not detect design drift, so typecheck, lint and e2e passing is not it),
and the feature checklist passes `check_checklist.py`, run by an agent that did
not build the feature, with that run recorded in the checklist's section 6 - its
bug hunt by an agent that did not build the feature (section 4b) included.
Before the tester is told the build is ready, that agent runs the checker again
with `--served <the serve worktree>`, and the hand-off message carries its
`SERVED` line: the build the tester gets is the build the pixel and e2e evidence
is for.** The sweep sets the step sheet's visual rows: the tester still looks
over each screen, in the compact row the sweep defines in place of the detailed
rows it measured, and a visual defect the tester reports anyway is a sweep
escape, recorded as the sweep says. Every behaviour row, and every row only a
physical device can answer, stays.

**The builder shows the requester first.** Before the checker runs for the
hand-off, the builder posts in the feature's chat thread, to the feature's
requester (the checklist header's Requester), a video of the feature on each
platform it runs on (for a mobile app, the iOS simulator and the Android
emulator, `/device-emulators`), and, where the install has a design file, the
design pixel-comparison pack with its diff maps (the UI evidence gate's
per-state pack, from the design verification kit). That message's permalink is the evidence in the checklist's section-5 row
`6 - presented to the requester`, and the checker refuses the hand-off until the
row is `DONE` with a permalink matching `checklist.permalink_pattern`; a feature
whose header names no screens records it `N/A`, with the reason.

**The agent drives; the tester follows.** Humans skip thorough testing when left
to it, so the agent runs the pass in the feature's thread the way `/release`
runs its guided passes (its section on how every instruction to the requester is
written): the tester's step sheet, a QA checklist of one action and one expected
result per numbered row, the expected result stated before the tester acts,
**every control and every state the feature has** exercised - the empty,
loading, error and populated states, each branch, each way it can end. It asks,
explicitly, after the scripted steps and again at the end, **whether anything
felt weird, unnatural or hard to use**, and records every instruction and every
answer in the thread. A friction answer is a finding: fixed on the branch and the
affected steps run again, or ruled out of scope in writing by the person who owns
the feature.

**The pass is timed, and the timing goes in the merge report.** The agent posts
in the thread when the driven pass starts, immediately before step 1, and when
it ends, after the last answer is recorded; the duration is the difference
between the two posts' timestamps. Where the dev server writes a session log,
that log is the measurement; where it does not, the thread posts are
(`CONTEXT.md` states which applies on the install). The merge report states the
start, the end, the duration, the floor it was held to, and the thread.

**Three outcomes, and only one of them merges:**

- **validated** - timed on the install's clock, at or above the floor, every
  step's observation matched, every friction answer closed;
- **failed** - a step did not match, or friction is open: fix, and run the
  affected steps again;
- **not validated** - the pass was not timed (where the thread is the clock:
  the start or the end post is missing), or ran shorter than the floor.
  This is not a softer pass and not a failure of the feature: it is **no
  evidence**, and the branch does not merge on it.

**The floor is stated before the pass starts**, in the thread, and quoted in the
merge report beside the measurement (`CONTEXT.md` has how it is sized). A floor
chosen after the measurement is fitted to it.

**Which clock times the pass is an install fact, and `CONTEXT.md` states it.**
There are two and only two: the dev server's session log where the install
writes one, and the thread's start and end posts where it does not. A duration
from anywhere else - the agent's recollection, a timestamp picked after the
pass, a screen recording's length - is not a measurement, and the pass it
describes is not validated.

## Rule 7 - A feature ships complete

**A feature is done when every surface it touches ships together, in one
landing: its screens, its server half, its analytics, its e2e coverage, the
push-notification copy it introduces, and the store-listing text, screenshots
and keywords it needs on each storefront the app is listed on.** When the whole
cannot ship in one landing, cut the SCOPE to a smaller feature that is complete
on its own, and ship all of that; never land a part and promise the rest. A
smaller complete feature is always better than a partially implemented big one.
**A "follow-up" is a separate feature with its own entry in the roadmap, never
the missing half of this one**: the feature that lands is judged as if no
follow-up will ever come.

**Why it is a rule: every surface has its own gate, and no gate sees the
union.** Rule 4 checks the specs, Rule 5 the screens, the probes the server
half; each goes green on its own surface while the surface nobody owns is
simply absent. A screen that works with no push telling the user it is ready,
a push that lands on a screen the store listing never mentions, a flow with no
events so nobody can say whether anyone uses it - each passes every gate it
has, and each is what a user actually meets. A partial feature is not a
smaller feature; it is a broken one, shipped. And "the rest in a follow-up" is
not a plan: the follow-up competes with everything else in the roadmap, while
the half that shipped carries its cost - holes in the analytics, a listing
describing a different app, copy nobody wrote - for as long as the follow-up
waits, which is often forever.

**The consequence: the scope is fixed against a surface list before
implementation starts, and the list travels to the merge.** For each surface
below, the feature states what it ships there or `none`, with the reason. An
entry reading *later* is not a scope, it is a partial feature: cut the feature
until no entry says it. The landing (Rule 3) carries every non-`none` entry
that lives in the repository; an entry that lives outside it - a store listing
edited in a store's console - is written out in the merge report and applied
with the release that ships the feature, never a later one. The Rule 6 pass
exercises every entry a user meets in the app, and the merge report names each
surface and what shipped on it. A surface discovered mid-build joins the list
and the landing, or the scope shrinks to exclude the behaviour that needed it;
it never becomes a ticket for afterwards.

**What "complete" means - the surfaces:**

- **Screens** - every screen, state and control the feature adds or changes,
  each behaving as it logically must (Rule 5 shows them).
- **The server half** - endpoints or callables, triggers, scheduled jobs, access
  rules, stored fields and indexes, landed with the client that needs them,
  never ahead of it and never behind.
- **Analytics** - the events that say whether the feature works and whether
  anyone uses it, added to the event vocabulary in the same landing. Events
  added afterwards measure nothing about the launch, and the launch is the one
  window that cannot be re-run.
- **e2e coverage** - Rule 4's arm for new functionality, written once the
  feature is finished and landed with it.
- **Push-notification copy** - every notification the feature sends or
  changes, title and body written, reviewed and landed with the feature. A
  feature whose natural end is telling the user something is not complete
  until it tells them.
- **Store listing, per storefront** - the description text, screenshots and
  keywords the feature needs, on EACH storefront separately: storefronts have
  different fields, limits and review steps, so one updated and the other not
  is a listing half-written. A feature that changes what the app does changes
  what the listing says.

`CONTEXT.md` names where each surface lives on the install, the storefronts,
and the roadmap a follow-up is filed in.
