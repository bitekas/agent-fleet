---
name: release
version: 1
description: >
  Cut a release of a mobile app with a cloud backend as a twelve-step
  engagement with the requester that STARTS at the RC cut: an RC branch off
  the landing branch opens the release window, and from then on the RC is
  frozen, every tester build of the candidate is made from it, fixes found in
  testing land on it and are back-merged into the landing branch, and the
  store lane builds only from it. The steps: the cut, the release branch
  merged in, the full quality gates, a changelist derived from the commit
  range, a diffchange document and a QA checklist, a backend server on the
  RC's code against the live project's data, old-client then RC-client tester
  builds against it (the RC's swept for visual bugs, and its features'
  checklists checked, by the agents before the requester gets them), two
  guided test passes (the second carrying the testing rules - every rough
  edge fixed and verified on a development build first, no new features,
  testers asked for friction after every build, unpolished features pulled -
  and the fix cycle), the fast-forward of the release branch to the validated
  RC tip with its delivery check and backmerge, and the guided store
  submission in App Store Connect and the Google Play Console. The step ORDER
  is fixed; the content is a living document. Load before cutting a release,
  before making any tester build of a release candidate, before landing a fix
  for one, when asked to ship the current state of the landing branch to the
  stores, or when any step's technicalities or store UI turn out to differ
  from what is written here.
requires_install: false
---

# Release

A release moves a frozen, tested cut of the landing branch
(`repo.landing_branch`) onto the release branch (`repo.release_branch`), which
is the branch the store lane deploys from. The twelve sections below are how
that is done, in order, and the first of them is the cut: **a release begins by
cutting the release candidate, and everything a tester sees of the candidate is
built from it.**

**What kind of project this is for.** A client-server product whose clients
are mobile apps shipped to the App Store and Google Play, whose backend deploys
from CI, and whose repository follows the branch-to-environment model
`/repo-and-environments` describes: a landing branch where finished work lands,
a release branch the store lane builds from, a live environment the store
builds talk to, and a tester-distribution service for builds that are not store
builds. Section 6 also assumes the backend can be run on one of the
install's machines against the live project's data layer; `technical/firebase-functions-emulator.md`
beside this file holds the vendor facts for one such runtime. The twelve steps
are the mechanism for any such product; every branch, file, command, host,
person and number of one install is in its `CONTEXT.md`.

The install's `CONTEXT.md` for this skill (`fleet where release CONTEXT.md`)
carries the install's values and, per step, the exact command lines to run -
its section numbers match this file's, so section 7 here lands at section 7
there. `config.json` (`fleet where release config.json`) carries the small
structured subset; `config.example.json` beside this file names every key.

---

## This file is a living document

**It is expected to be corrected every time it is used.** The steps below are
written from what the tooling does, and the tooling moves: a flag is renamed, a
lane is rewired, a store console redesigns its submission flow. When a step's
instructions do not match what you find, **the instructions are wrong** and
correcting them is part of the engagement that found the discrepancy, not a
follow-up ticket.

**Where a correction lands.** This file is shared by every install and is
read-only on the host, so a correction goes to the layer that is wrong. A
command, a flag, a file, a value or any other detail of this install is
corrected in the install's `CONTEXT.md`, in the section with the same number. A
correction to the mechanism itself - this file, a file under `technical/`, or a
vendor console sequence in section 12 - belongs in the fleet repository: make or
propose it there in the same engagement, the way `/agent` section 8 says, and
until it has landed write the correction as a note at the top of the install's
`CONTEXT.md` section with the same number, which outranks this file, so the next
reader meets it. **That note is deleted in the same change that takes up the
fleet version carrying the fix** (the install's next fleet upgrade past it),
because a note left behind outranks the corrected text and is the two-copies
drift the rule below exists to prevent. If the fleet change is refused, the note
either becomes this install's value, written as such, or is removed.

**Two halves, and only one of them may change:**

- **The ORDER and the TWELVE STEPS are fixed.** They are the procedure as it is
  specified, and only the specifier (`CONTEXT.md`, *Who decides*) re-specifies
  them. Do not merge two steps, reorder them, skip one, or insert a
  thirteenth. A step that turns out to be unrunnable is reported as a blocker at
  the point it is reached - it is not routed around, and the steps after it do
  not start.
- **The CONTENT of a step may and should change**: the technicalities (a
  command, a flag, a file, a gate) and the user interfaces (section 12 above
  all). Correct it where the rule above says, in the same engagement, and say in
  your report which sections you changed.

**Correct in place; do not annotate.** Write what is true now. A step that says
"this used to be `--bundle`" makes the next reader weigh two options where there
is one. `git log` is the history.

---

## What lives elsewhere, and is not restated here

- **The branch-to-environment map, what each environment is for, where a build
  lands, how a build gets its configuration, the version file and what advances
  it, the backmerge, the store lanes, the push rules:** `/repo-and-environments`.
  That skill is canonical, it is cited below by section number, and a second
  copy of any of it here is the bug.
- **The store release note** (`/repo-and-environments` section 4.5). Where the
  install ships a fixed note, nothing is composed per release and no step below
  previews one; the console steps that touch a note are section 12a step 5 and
  section 12b step 5.
- **Worktrees, branch cutting, landing and the evidence rules for claiming
  something landed:** `/worktree-workflow`.
- **What done means, the consistency scan, the gate discipline:**
  `/definition-of-done`.
- **The e2e harness, its scoping, its verdict line and its traps:**
  `/e2e-suite`.
- **The UI evidence gate, when a step produces UI evidence, and the visual
  sweep section 9 runs before the requester is handed the RC's builds:** the
  install's UI evidence skill, which `CONTEXT.md` section 0 names. Where the
  install has none, section 9 reports the sweep NOT COVERED and the detailed
  visual rows stay in the walk.
- **The design source, where the install keeps one** - a design file with a
  page that mirrors what is on the landing branch: the install's design-source
  skill, which `CONTEXT.md` section 0 names, owns its mechanics; sections 1, 10
  and 11 say what a release does to it, and an install with no design source
  skips those paragraphs and says so.
- **Which tool owns which job**, before you write any command of your own:
  `/tooling-index`.
- **Running a build on a simulator or emulator**, where a step needs one:
  `/device-emulators`.
- **Setting a cloud secret an agent cannot type a password for:** the install's
  cloud-secret procedure, which `CONTEXT.md` section 0 names.
- **Everything version-specific a release needs that the twelve steps and CI
  do NOT enforce:** the install's release plan, a file at the repository root
  that `CONTEXT.md` section 0 names, which any task adds to the moment it finds
  such a step; its header says what belongs. Section 1 opens the version's
  entry; section 11 confirms it before the merge into the release branch and
  removes it once every step in it is done.

## The standing tension, and who resolves it

The release branch takes **no new features, interfaces or schema changes**
(`/repo-and-environments` section 3.1). A release is a merge from the landing
branch, which carries whatever landed there. **The two are in conflict by
construction**, every time, and the conflict is not an agent's to resolve: the
person `CONTEXT.md` names authorizes the merge in section 11, on the evidence
sections 4 and 5 produce. Steps 1 to 10 are what turn that authorization from a
guess into a decision. **Do not cut a release that moves a contract on your own
reading.**

---

## The release window: what the RC cut opens, and the four rules inside it

Section 1's cut opens the release window and section 11's merge closes it.
Inside it, four rules hold, and every step below is written against them:

1. **The freeze is on the RC only.** The landing branch keeps taking work
   throughout. What lands there after the cut is **not** in this release; it
   rides the next one.
2. **Nothing flows from the landing branch into the RC after the cut** - except
   a cherry-pick the person `CONTEXT.md` names has explicitly approved, one
   commit at a time, recorded in section 5's documents. The one other merge INTO
   the RC is section 2's, from the release branch.
3. **Every tester build of the candidate is built from the RC** - never from the
   landing branch, a fix branch or a feature branch - and none is made before
   the cut. Section 7's builds are the one tester build in the window that is
   not the candidate: their subject is the previous release, by construction.
4. **A fix found in testing lands on the RC**, on a branch cut from the RC tip,
   and every push to the RC is back-merged into the landing branch by the
   backmerge job (RC -> landing, never the reverse; `/repo-and-environments`
   section 5.2). Where the install has a live-copy environment, the same job, on
   the same push and once the landing branch holds the RC, moves the live-copy
   environment's branch to it and redeploys it: while the window is open the
   live-copy branch follows the RC, its ordinary promotion refuses without an
   explicit flag, and the job refuses loudly when the live-copy branch carries
   anything else. Section 10 carries the cycle.

**The store lane enforces the end of it**: the deploy script's store target
refuses to build from any branch that is not an RC, except the release branch
in CI once section 11 has fast-forwarded it to the RC, so the store build is the
RC commit the testers passed, and a store build of anything else is not a matter
of discipline but a refusal. `CONTEXT.md` section 11 has this install's exact
rule and its CI allowance; where an install's store lane does not enforce it,
section 11's checks are the only guard, and the report says so.

---

## How every instruction to the requester is written

Steps 5, 8, 10 and 12 put instructions in front of a person. All four obey the
same six rules, and they are stated once here rather than four times below.

1. **The instruction is a QA checklist: one numbered row per action, written
   `<n> <action> -> <expected result>`.** A row holds exactly ONE action that
   can fail on its own and the ONE observable result that proves it worked.
   Navigation that cannot fail in an interesting way ("launch the app, go to the
   settings tab") prefixes the row's action; anything that can fail by itself -
   a sign-in, a save, a sheet opening, a value persisting - is its own row. A
   row that bundles several such actions under one expectation cannot say where
   a failure happened, which is the one thing the requester's report exists to
   say. **Every label is literal.** A control, a heading, a message or a field
   is quoted exactly as the build renders it, in quotes, read from the app's
   string catalog at the build's commit (`CONTEXT.md`, *Where the literal UI
   strings are read*) - never paraphrased, shortened or described:
   `"Saved items"`, not "Saved"; the sheet's `"Add to list"`, not "Add". A
   control with no text is named by what it shows and where it sits ("the gear
   icon on the home screen"). A label the requester cannot find on screen is a
   row they cannot run.
2. **Rows are numbered per step (`2.1`, `2.2`) and the requester reports by row
   number.** A row added later takes the next number in its step, so nothing
   already reported is renumbered. When an observed result opens or closes rows,
   say how many remain and why.
3. **Every row states its EXPECTED RESULT before the requester performs it**, in
   the same message: what appears, what it says, what it does not do. A row that
   only says what to do makes the requester the judge of a criterion they were
   never given.
4. **One platform per message.** That platform's rows go as one checklist;
   never iOS and Android in one message, and the second platform's checklist
   goes after the first platform's rows are reported.
5. **The first mismatch stops the run.** A mismatch between expected and
   observed is a **stop**, not a note to carry forward: report it against its
   row, and do not continue past that row until it is ruled on.
6. **The sequence opens by delivering the build to the tester account.** The
   release builds are installed and tested signed in to one shared tester
   account (`CONTEXT.md`, *The tester account*). When the requester starts a
   sequence, and before its step 1, send the install link of every build the
   sequence uses - the tester-distribution service's release link per platform,
   which the upload prints - to the address that section gives for delivering
   builds to that account, with the build's version, the commit it was built
   from, and the on-screen check that proves it is the installed one. Step 1
   then names the same build. A sequence that names no build gets run on whatever happens
   to be installed, and its results describe that.

---

# 1. Open the release window: cut the release candidate branch off the landing branch

**What it does.** Opens the release window (above) and creates the branch the
whole release is built, tested and fixed on, so that nothing in steps 2 to 10 is
written into a shared checkout, nothing on the release branch moves until
section 11, and no tester build of the candidate exists that was not built from
it. **This is the first act of a release, before any tester build of the
candidate.**

**How.** A fresh git worktree on a new RC branch (`repo.rc_branch_prefix`
followed by the cut's date, `YYYY-MM-DD` - the name shape the install's store
lane accepts, `CONTEXT.md` section 11) cut from the **freshly fetched** tip of the landing branch, **pushed to
origin at once** (a CI tester build is a workflow dispatch on it, and a fix
branch is cut from it), in your own workspaces directory, with a real
independent install of **every dependency root** (`/worktree-workflow` owns the
line and the roots it covers; `CONTEXT.md` section 1 has this install's
commands). Never a shared checkout, never a hardlinked install - a shared
install's staleness produces false gate verdicts in an isolated tree, which is
exactly what section 3 is about to read.

**That first push is the window's first RC landing.** Where the install has a
live-copy environment, the backmerge job moves its branch to the RC and
redeploys it (`/repo-and-environments` section 5.2), so the live-copy
environment runs the candidate from the cut on. Check its run as section 10's
move 3 says, and say so when you announce the cut. **A CI token may be refused a
push that changes a workflow file** - GitHub's default job token is - so when
the landing branch changed a workflow file since the live-copy branch was last
moved, the job cannot make that move: its run is red, by design and not as a
defect to chase, and the move is made by hand with your own credentials before
you announce the cut (`CONTEXT.md` section 1 has the job's message and the
commands).

**The RC branch keeps its `repo.rc_branch_prefix` name and takes no per-author
prefix**, whatever the install's branch naming (`/worktree-workflow`) asks of
other branches, and that naming rule must exempt it. A release branch is a
**lane artifact**, worked on by whoever is holding the release and outliving
whichever agent cut it, so a name that claims one author owns it would be false
the first time somebody else picks the release up. The same exemption covers
the landing and release branches themselves. **Commits an author makes on the
RC still follow the install's commit-subject rule**; only the branch name is
exempt. Because git stores branches as nested refs, the prefix's first segment
is reserved too: a branch, or an agent-named ref, equal to that bare segment
would block every RC branch under it (`CONTEXT.md`, *The branches and the
lane*, names this install's reservation).

**Read the landing branch's tip before you cut, and record what you see.** A tip
that is CI's version-bump commit carries a `[skip ci]` marker in its subject,
and that marker is evaluated against the **head commit of a push** (GitHub
Actions reads it there), not against its author or its branch - so when that
commit becomes the head of section 11's push to the release branch, **the
release fires nothing at all**: no run, no build, no backmerge, and nothing red
to notice the absence of (`/repo-and-environments` section 4.3). It is not a
reason to stop; it is a reason section 11 takes the dispatch route instead of
trusting the push. Recording it now is what makes section 11 cheap.

**Record three coordinates and carry them through every later report:** the
landing branch's SHA you cut from, the release branch's current SHA, and the
value of the version file (`release.version_file`) on each. Every claim in this
engagement is made about those SHAs.

**Ask what is still in flight BEFORE you cut, and announce the cut after.**
From the cut until section 11 the RC is frozen while other agents keep landing
on the landing branch, and what lands after the cut does not reach this release
except as an approved cherry-pick. So ask first whether anything
committed-but-unpushed or about to land must be in this release - section 4
explains why the repository cannot answer that - and wait for it or record that
it rides the next one. Then announce the cut with the RC's name and SHA and the
window's four rules, so every agent knows that a tester build of the candidate
is made from the RC and a fix for it lands there.

**Snapshot the design at the cut, where the install keeps a design source.**
Copy the design file's current page - the one that mirrors what is on the
landing branch - into a new page named from the install's release-snapshot
template, which carries the RC's `x.y` from the version file and the cut's date
(`CONTEXT.md` section 1 names the template, and the design-source skill owns the
copy). **The snapshot is a record only once it is cut loose from everything
that can change it**: every component it uses is detached from its master,
wherever in the design file that master lives, because an edit to a master the
snapshot is still bound to changes the snapshot silently. Then the snapshot is
made to show what this release ships, and nothing else:

- **Work that is not in this release comes out.** A frame the design source
  marks as still being built is not in this release, and is deleted from the
  snapshot. **The mark is only as current as the landings that should have
  taken it off**, and a landed task that skipped its un-marking leaves shipped
  frames wearing it. So before the snapshot drops a marked frame, check whether
  its work is in the RC: the install's design-to-code record for the frame, and
  the commit that wrote it, lie in the release range. A frame that passes is
  owed its un-marking on the current page, done first and then carried into the
  snapshot; a frame with no record and no citing commit cannot be verified from
  the repository, keeps its mark, and goes to whoever marked it.
- **The shipped version of a screen stays until its successor lands.** A frame
  the design source marks for deletion is, until its successor lands, the
  shipped version, so the snapshot keeps it. Where such a frame has already been
  deleted from the current page and this release ships its screen, the shipped
  frame survives only on the design source's last backup taken before that
  delete; that backup is the shipped reference for the screen, and the snapshot
  says so in a note that names the screen and links the backup.
- **The snapshot is not a backup.** A backup guards the current page against a
  frame's deprecation or deletion; the snapshot records what this release ships.
  Making the snapshot writes nothing to the current page, so it takes no backup;
  any write during the window that deprecates or deletes a frame there takes
  the backup as the design-source skill says, and an edit to a live frame takes
  none.

`CONTEXT.md` section 1 names this install's marks, its design-to-code record
and its backups.

**The previous release's snapshot moves to the design archive now**, where the
design file keeps only the current release's snapshot: move it, and delete it
from the design file only after the move is proven (the design-source skill
owns the move and that rule; `CONTEXT.md` section 11 has the command). Until
both are done, your report carries it as an open checklist line,
`[ ] move <previous snapshot> to the design archive, then delete it from the design file`.

**Open this version's entry in the release plan.** The repo-root live log
(`CONTEXT.md` section 0 names it; its header says what belongs) carries every
version-specific step these twelve steps and CI do NOT enforce. Add this
version's entry at the TOP, or take over the one a task already opened, with
every step known at the cut, each with a `[ ]`/`[x]` status and an owner. A
step found later is added by whichever task finds it. Section 11 confirms them
before the merge into the release branch.

**Done when:** the RC branch is cut from the recorded landing-branch SHA and
pushed, the worktree exists at a known path with the install complete in all
roots, the three coordinates are written down, the in-flight question has an
answer from a person, the cut is announced, the release snapshot exists without
work that is not in the release (or the install keeps no design source, and the
report says so), this version's release-plan entry is opened at the top with
its manual steps, and the previous snapshot's move to the design archive is
done or reported as owed.

---

# 2. Merge the release branch into the RC branch

**What it does.** Carries forward every fix that was committed straight onto the
release branch, and surfaces every conflict between the two lines **here**,
inside a worktree where a broken merge harms nobody.

**Direction is the whole point: release branch -> RC branch.** Never the
reverse, and never resolved on either shared branch. The reverse direction is
section 11 and happens only after section 10 passes. This is the one merge into
the RC the window's second rule allows besides a fix landing; it carries the
live line's own fixes, never the landing branch's work.

The backmerge (`/repo-and-environments` section 5) normally keeps the landing
branch caught up, so this merge is often empty or near-empty. **An empty merge
is a result, not a skipped step:** say so, because a non-empty one means the
landing branch was behind and the RC now carries commits the gates in section 3
have never been run against together.

**The version file conflicts by design and is the ONE file resolved
mechanically.** Two branches each minted a successor to it from a common base.
Where it is the **only** conflicted path, resolve it with the version tool's
reconcile mode - **field-wise maximum**, each of the version fields taken
independently - which is the same single implementation CI uses, so no second
copy of the version rules is created (`/repo-and-environments` section 4.3;
`CONTEXT.md` section 2 has the commands). Where anything **else** conflicts, or
the version file conflicts **alongside** something else, a human resolves it:
"what did the author mean" is not computable, and taking one side's major with
the other's minor produces a version nobody chose.

**Done when:** the merge is committed on the RC branch, no conflict markers
remain, the version file holds the field-wise maximum, and you have reported how
many commits the merge carried (zero is an answer).

---

# 3. Run the full quality gates on the RC

**What it does.** Establishes that the merged tree is green **as a whole**,
before anybody is asked to test it. This is the one measurement that covers the
combination; every gate run before now covered a piece.

**The gate set is the install's scheduled quality workflow's**, and that
workflow is the definition of "full gates" - not a list assembled here, which
would drift from it silently. `CONTEXT.md` section 3 carries the gate table with
each command as the workflow runs it, and the two routes:

- **Dispatch the quality workflow on the RC ref.** Preferred. It runs the same
  gate set on the runner, with the same install, and costs no local machine.
  **Where the workflow records its own outcome as a tracked file on the ref it
  ran on, the dispatch pushes a commit onto the RC branch WHENEVER THAT FILE'S
  STATE MUST CHANGE**, which on an RC's first green run is always: the RC tip
  then moves after sections 1 and 3 wrote it down, and section 11's merge
  carries that file onto the release branch. Re-record the RC SHA here, and
  **quote the SHA the gates actually ran against** rather than the new tip.
  Where the branch already carries the right state the dispatch commits nothing
  and the tip holds - read the outcome, do not assume either way. Section 11
  states the rule that governs where that file may land; `CONTEXT.md` section 3
  has what the dispatch writes, as the states it can land in.
- **Run the gates locally**, in an isolated worktree of the RC commit with a
  real install of every dependency root (`/worktree-workflow`), so the reading
  is about that commit and nothing else - not your uncommitted edits, not a
  stale install, and not a tree somebody else is mid-edit in.

**On the full e2e suite: prefer the dispatch route, and do not read a local
full run as newly permitted.** The standing rule is that the whole suite is
CI's job and the local budget for it is zero (`/definition-of-done` Rule 4,
`/e2e-suite`) - which the dispatch route satisfies exactly, because the workflow
runs it on the runner. The local route is not a new exception invented here: it
is the same integration-gate carve-out `/e2e-suite` already grants for
orchestrated work, run **once**, at the very end, over the merged whole, and a
release is that. It stays scoped to the RC commit and to one run. **If you find
yourself running it a second time locally, the thing to fix is whatever made the
first run untrustworthy** - a suite that disagrees with itself across runs on
identical code is a defect in the gate, not noise to re-run past.

**A gate that could not RUN is not a gate that passed, and the exit codes say
so.** Several gates can have a third state distinct from pass and fail -
precondition unmet, gate fault, no verdict - and every one of them means *this
gate has not pronounced*. Report it as its own state. **Never map it onto a
pass because nothing was reported**: an instrument that could not measure and
an instrument that measured clean produce the same silence, and only the exit
code separates them. `CONTEXT.md` section 3's gate table names each gate's third
state.

**It runs again on every RC tip that moves by more than a version bump** - after
each fix landing in section 10's cycle and each approved cherry-pick - before a
tester build is made from that tip, because section 11 lands only a tip the
gates measured.

**Done when:** every gate in the table has a green verdict at the RC SHA, each
reported with its own exit code, and no gate is in a third state. **A red or
unpronounced gate stops the release here.** It is fixed on the RC branch, the
way section 10's fix cycle lands a fix (which sends you back through section 3,
not around it), or the release is abandoned; it is not baselined, not
allowlisted, and not dropped from the table.

---

# 4. Derive the changelist: features, functionality branches, edge cases

**What it does.** Turns the commit range into the thing everything downstream is
built from. Section 5's two documents, section 8's old-client test set and
section 10's full pass all read from this and from nothing else, so an omission
here is invisible for the rest of the engagement.

**The range is `git log <release branch>..<RC branch>`** - exactly what this
release carries and nothing else (`CONTEXT.md` section 4 has the invocation).
It is routinely hundreds of commits; that is the normal case, not a signal that
something is wrong.

**Group into FEATURES, never into commits.** A commit is an accounting unit; a
feature is a capability a user or a caller can exercise. One feature usually
spans many commits, and one commit sometimes touches several features.

**For each feature, derive three things, and derive them from the code:**

- **Its functionality branches** - every path through it. The happy path, each
  alternative the user can choose, each state the system can be in when they
  arrive (signed out / anonymous / signed in; first run / returning; empty /
  populated), and each way it can end.
- **Its edge cases** - the boundaries and the failures. Empty and absent state,
  the maximum and the minimum, permission denied, network absent, a retry after
  a failure, a value written by an older version of the code, concurrent use.
- **Its screens** - every screen it adds or changes. They are the visual
  sweep's subject (section 9).

**Then, for each branch and edge case, name what already proves it
automatically** - the e2e spec, the unit or integration test, or the
security-rules test that drives it at the RC SHA, read from the test's code
rather than its title - or write `none`. This is the automated coverage section
5b sizes the device pass against: a check named here takes a row off the
tester's pass, so naming one that does not actually drive the branch leaves
that branch tested by nobody.

**Two sources, and they answer different questions.** The **diff** is the
authority on what actually shipped. The **design package** under
`release.design_packages_dir`, where the feature has one, is the authority on
what the branches were intended to be - it is where the edge cases were
enumerated by someone who had the whole picture. Read both. **Where they
disagree, report the disagreement; do not pick a side.** A design package is a
historical record of a decision at its date and is not maintained against the
code, so a divergence is a finding about this release, not an error in the
document. Where the install keeps no design packages (`release.design_packages_dir`
is empty), derive everything from the diff and say so.

**Read the diffs, not the subjects.** A commit whose message says one thing and
whose diff does another is counted by its diff. A conventional-commit prefix is
a claim, not a classification.

**A BRANCH TIP IS NOT THE SYSTEM'S PRESENT, and the cut was made from a tip.**
Committed-but-unpushed work in another agent's worktree was structurally
invisible to the cut: the log is *correct about those commits* and *wrong about
the system*, and nothing on disk can correct it, because the disk is not lying.
That is why section 1 asks the people before cutting. What the frozen RC buys
here:

- **Work landing on the landing branch during the engagement does NOT change
  this range.** It is not in the RC and does not reach section 11.
- **The range moves only by what the window allows onto the RC**: section 10's
  fix commits and approved cherry-picks. Each one is assigned to a feature here
  and written into section 5's documents in the same sitting.
- **Work that missed the cut is not in this release**, however much the
  requester believes it is. Say so when you deliver section 5, naming what
  section 1's in-flight answer said would ride the next one.

Section 11 re-derives the range and checks it against exactly that.

**"No user-visible effect" is a claim that must be measured, not asserted.** A
commit is only in that bucket once you have shown it, in one of three ways:
every file it touches is outside what a build can reach; or BOTH sides of its
diff in reachable files are comments only; or every changed line sits behind a
switch that is off in every store and tester build, which you name (a bundler
rule that empties the module, a development-only gate). **"It's only docs" is
not a measurement**, and a one-line guard can be the entire fix for a defect
that silently stops a whole product surface working.

- **Both sides, not the added side.** A commit that only DELETES code has an
  empty added side and is anything but inert.
- **A line-prefix filter is not enough on its own.** On a JavaScript or
  TypeScript codebase, the continuation lines of a JSX block comment carry no
  comment marker, and a `//` inside a template string is not a comment. Pair the
  filter with a parser-based comparison of the file before and after with
  comments removed (the TypeScript printer with `removeComments` does it), and
  require the two instruments to agree. Prove both against a known
  code-changing commit before trusting a "comments only".
- **A merge is measured by what the merge itself wrote.** Its combined diff's
  `++`/`--` lines are the lines neither parent had; when those are absent or
  comments only in reachable files, the merge carries no content of its own. A
  combined diff cannot see a conflict resolved by taking one side whole, so a
  merge whose combined diff is empty is re-merged from its parents and compared
  when it matters.

**Done when:** every commit in the range is assigned to exactly one feature or
to the measured no-user-visible-effect bucket, the count of unassigned commits
is **zero**, and every feature has its branches and edge cases written out, each
with its automated coverage named or `none`, and its screens listed. Say the two
counts - commits in range, features derived - in the report.

---

# 5. Present the diffchange, then the QA checklist

**What it does.** Puts section 4's derivation in front of the requester in two
artifacts, in that order, because the second is only readable once the first is
agreed.

Both are delivered as artifacts, not as a chat summary: they are read more than
once, by sections 8 and 10 and by whoever authorizes section 11. `CONTEXT.md`
section 5 says where they are written.

## 5a. The diffchange document

What changed, as features, in the requester's language rather than the
repository's.

```markdown
# Release <version file value on the RC> - what changed

Range: <release branch SHA>..<RC SHA> - <N> commits, <F> features.
Gates: all green at <RC SHA> (section 3).

## <Feature name - what a user would call it>

**What it is.** One or two sentences. What can somebody now do, or what
now behaves differently, that did not before.

**How it behaves.**
- <functionality branch> -> <what happens>
- <functionality branch> -> <what happens>

**Edge cases.**
- <edge case> -> <expected handling>

**Contract changes.** <A stored-document field, a backend call's signature, a
response schema, a route - or "none". This line is what section 11's
authorization turns on, so it is never omitted and never left implicit.>

**Platforms.** <iOS / Android / both / backend only / a web surface only>

## ... one section per feature ...

## Changes with no user-visible effect

<count> commits, measured rather than assumed (section 4). <One line on what
they were: tooling, docs, agent prose, tests.>

## Fixed on the RC during testing

<One line per fix landed by section 10's cycle: the checklist row that found
it, the fix commit, the RC SHA it landed at. "None" until the first one.>

## Pulled from this release

<One line per feature pulled because it was not polished (section 10, rule 4):
the feature, the revert commit on the RC, what it still lacks.>

## Deferred to the next release

<One line per request ruled a feature (section 10, rule 2), as written in the
release thread.>

## Cherry-picked from the landing branch

<One line per approved cherry-pick: the commit, who approved it. "None" is the
normal state.>
```

## 5b. The QA checklist

Derived from the same section 4 material, and **sized to the release's
device-pass budget**: `CONTEXT.md` section 5 names the rule that sets it, and it
is read before a row is written. Three things follow from it, and the checklist
carries all three:

- **Every branch and edge case section 4 derived is decided keep or drop, with
  its reason written beside it in the rule's terms.** A drop for automated
  coverage names the check section 4 recorded; a detailed visual row dropped for
  the visual sweep (section 9) names the captures that covered it. The drops are
  listed under the kept rows, so the cut can be audited rather than trusted.
  **Every screen section 4 lists is covered by one of the compact visual rows
  the install's visual sweep defines** (its skill is named in `CONTEXT.md`
  section 0), because the requester still looks over every changed screen on
  both phones.
- **Every kept row carries its estimated minutes on the phone**, and the header
  totals them per phone and for both phones together, section 8's rows and
  section 10's; the combined total is what is held against the budget. Whenever
  a fix or a merge moves the RC (section 10's fix cycle, section 11's re-merge),
  an entry under *Not on the phone* that it reaches is decided again, and the
  total is re-taken.
- **A pass that would take the release past the budget is put to the requester
  before it starts** - the per-phone totals and what makes up the excess - and
  runs as they decide, never on your own reading.

**Written so that a kept row can be read aloud as an instruction** - sections 8
and 10 do exactly that, and a checklist that has to be re-authored at that point
was not finished here. **It is YOUR script for those passes, not a worksheet
handed to the requester to work through alone**: you read each row to them one
at a time and record what they report back (sections 8 and 10).

```markdown
# Release <version> - QA checklist

Budget: <the rule's budget>. Both phones <n> min = iOS <n> (section 8 <n>, section 10 <n>) + Android <n> (section 8 <n>, section 10 <n>).

| # | Feature | What to do | Expected result | Platform | Touched | Kept because | Min | Observed iOS | Observed Android |
|---|---|---|---|---|---|---|---|---|---|
| 1 | <feature> | <the exact taps, in order> | <the exact observable> | both | yes | <the rule's ground> | 3 | | |
| 2 | ... | ... | ... | ... | ... | ... | ... | | |

## Not on the phone

| Branch or edge case | Feature | Dropped because |
|---|---|---|
| <from section 4> | <feature> | <the rule's ground; automated coverage names the check> |
```

**The two Observed columns ship empty and are filled in during sections 8 and
10.** They are columns rather than a separate log because the checklist is the
artifact that gets handed back as evidence, and a result recorded anywhere but
beside its expectation is a result nobody can check. **Two columns, not one:** a
row can pass on one platform and fail on the other, and a single column makes
that unrepresentable - which is how a platform-specific failure gets recorded as
a pass.

**The `Touched` column is load-bearing.** Section 10 runs every kept row.
Section 8 runs **only** the rows marked `yes` - the ones that reach a server or
contract change - because section 8's question is narrower (see below). Marking
it now, while section 4's derivation is fresh, is what makes section 8 a short
pass instead of a second full one.

The column takes two values, because section 8 drives the PREVIOUS release's app
and that app cannot show a change made only in the new one:

- `yes` - the row reaches a server or contract change (backend code, security
  rules, the shape of stored data) AND its expected result holds on the previous
  app. A row whose previous-app behaviour differs gets its own previous-app row
  stating that behaviour, marked `yes`.
- `client` - only the new app's code changed on the row's path, or the row is
  about UI the previous app does not have. Section 10 runs it; section 8 does
  not.

A branch nothing in the range reaches is not a row at all: it is unchanged, and
it goes under *Not on the phone* with that reason.

**Done when:** both documents are delivered to the requester and both name the
SHAs they were derived from, and the checklist states its per-phone minutes
against the budget, with any excess already put to the requester. **They stay
live for the rest of the window**: each fix section 10 lands and each approved
cherry-pick is written into both, with the RC SHA it moved the branch to, and so
is each detailed visual row the sweep (section 9) takes off, before the builds
that carry it are handed out.

---

# 6. Stand up a backend server on the new code against the live project's data

**What it does.** Gives sections 7 and 9 a backend that runs the release
candidate's backend code while reading and writing the live project's database,
sign-ins and stored files - so that what sections 8 and 10 exercise is the real
data shape, the real accounts and the real stored documents, not a seeded copy.

The server is the backend's own local runtime - for a serverless backend, the
platform's emulator for its functions - on a machine of the install's, pointed
at the live project. `CONTEXT.md` section 6 names this install's runtime and the
technical file that holds its vendor facts; for Cloud Functions for Firebase it
is `technical/firebase-functions-emulator.md` beside this file.

## The route

**The install's dev script boots it and tears it down, and restarts and
re-warms it.** `CONTEXT.md` section 6 carries every invocation, the
confirmation flag, the host, the base URL it prints, the ports it uses, and
where the design and the measurements behind every clause below are recorded.
They are cited there, not restated here.

What the boot does, and every clause is part of the requirement:

- **The backend runtime alone**, started against the live project's id with that
  project's admin credential bound explicitly, and every variable that would
  point a server-side SDK at a local emulator scrubbed out of its environment.
  No local stand-in for the database, auth, storage or message bus runs, and the
  generated config **cannot express one** - those blocks are deleted rather than
  merely left unstarted, so every server-side SDK call inside the backend
  reaches the live project and no future change can silently inject an emulator
  host into the runtime.
- **It refuses the live project without an explicit confirmation** - a flag, or
  a typed word when a TTY is present. The credential scope is the real guard;
  the confirmation catches honest mistakes. An assume-yes environment variable
  deliberately does not satisfy it: nothing in CI may open this window.
- **It builds the backend first.** Where the runtime serves compiled output, a
  stale build serves the previous commit and the whole regression test measures
  the wrong code.
- **Dedicated ports, outside every port a local development stack uses, for the
  runtime and for every auxiliary service it starts by default: each auxiliary
  service is switched off where it can be (an emulator's web UI, say, whose
  committed port is a development stack's) and given a fixed port of its own
  where it cannot** - so this mode steals no port from a colleague's running
  stack.
- **The runtime binds loopback only; a private-network HTTPS front is what
  makes it reachable.** A store-identity iOS build carries no cleartext-HTTP
  exception (App Transport Security refuses plain HTTP), so the tester's client
  can only reach it over HTTPS; the front terminates TLS with the host's own
  certificate and proxies to loopback. The boot prints the base URL to point
  section 7's and section 9's builds at, and says so separately when the front
  did not come up and when it came up but the host name could not be read -
  those two have opposite exposure and must never be reported together. Only the
  backend-code traffic rides that front: the tester's client still reaches the
  live auth, database and storage directly over the public internet, so a device
  off the private network half-works rather than failing (section 10, *The
  server window, and the tester's route to it*).
- **Every line it prints carries a distinct prefix, and the banner names the
  project and states in words that this writes real data.** A vendor CLI's own
  warning that calls will affect the live services may name no project at all,
  in which case it is identical whichever project you booted against.

**Teardown is a security control, not housekeeping** (see the two subsections
below). It verifies rather than assumes: it reports what is true after the
kills - the process, its pid file, the generated config, the CLI's config
directory, any debug log the CLI writes (which can record the secret store's
responses, payloads included), the log streamer, the HTTPS front - and exits
non-zero if the window may still be open. Two of its checks - a process census
for another checkout's server of this kind, and a census of listeners on this
mode's ports - are deliberately machine-wide and report-only rather than scoped
to the worktree that runs it, because a worktree-scoped verification run from the
wrong directory finds nothing of its own and would report "window closed" over
somebody else's live server. The ports are the only evidence that does not
depend on being in the right directory.

## What such a server SERVES, and what it does not

**Section 6 needs a runtime that, pointed at the live project's data layer,
dispatches no background event and fires no schedule.** Such a runtime serves
the request-driven surface - callable functions and HTTP routes - and nothing
else. The Cloud Functions for Firebase emulator meets this as it stands: it
dispatches background events only from local emulators running beside it, and
with none running it subscribes to nothing (`technical/firebase-functions-emulator.md`
section 1). **A runtime that consumes live event sources from a local process -
a queue or storage trigger reading the live resource, a timer firing locally -
does not meet it as it starts**: its triggers would run the RC's code against
live events, in a race with the deployment. On such a runtime the triggers are
disabled before it boots, and its technical file says how and how that was
verified. `CONTEXT.md` section 6 names this install's runtime and its technical
file.

So, with a runtime that meets the requirement:

- **Database triggers, storage triggers and scheduled jobs keep running on the
  LIVE deployment**, against the same live data, from the **previously
  deployed** code. The RC's changes to any of them are therefore **not**
  exercised by section 8 or 10, and every trigger side-effect a tester observes
  is the old code's. Say so when reporting the pass: it is the largest gap in
  what sections 8 and 10 cover, and it is invisible from the device.
- **No scheduled job fires in it**: the deployed schedule keeps firing the
  deployed code, and the RC's scheduled code runs nowhere.
- **A hook the platform runs on sign-in stays live too**, unless the runtime's
  technical file says otherwise: a real sign-in runs the deployed one.

**The startup log is not evidence of what is armed.** A runtime can report a
background function as initialized whether or not anything can ever dispatch to
it, and a reader using its startup output to decide what this server covers
will over-count. Take the census from what can dispatch, on every release's
boot, because it counts what the BOOTED source exports and not what the live
project has deployed; `CONTEXT.md` section 6 records the latest one.

## The request channels may not verify the caller

**Measure per channel whether the runtime verifies the caller's credential; do
not reason about it.** A route whose own code verifies the caller's token
against the project the runtime was started with still verifies under the
runtime. A channel whose verification lives inside a vendor SDK's wrapper may be
decoded rather than verified there - on Cloud Functions for Firebase the
callables are, unconditionally, and App Check with them
(`technical/firebase-functions-emulator.md` section 2).

**So while this server runs, any device that can reach it can invoke every
unverified channel against the live project's data as any user it chooses**,
with no credential, using nothing but a hand-written token, wherever the
backend's identity check reads the user id on the request.

**State this to whoever authorizes the release, before the server is booted**,
and state what does and does not bound it. `CONTEXT.md` section 6 names the
network boundary this install ruled on. **The window is the mitigation: nothing
else is** - which is why the teardown is a security control, why it verifies
instead of assuming, and why the boot arms its signal handler one line after the
spawn, so a Ctrl-C during the slow part of the boot closes the window instead of
orphaning a credentialed server.

## The secrets, and the one log line that means one failed

**Where the runtime fetches a secret lazily, per invoked function, never at
boot**, a boot log with no secret line in it is the normal, healthy case and
says nothing either way. The boot therefore WARMS: it reads the runtime's own
list of functions and sends one unauthenticated request to every request-driven
function that declares a secret - a callable whose wrapper rejects an empty body
before any user code runs, and a plain request route only if its handler has
been read to reject a missing credential before touching data - then greps its
own child's log. One line per function, with its status.

**The warm is also the defence against a credential that cannot refresh.**
Where the runtime's CLI holds one access token minted when it starts and cannot
refresh it under a service-account key, the first NEW function worker that
fetches a secret after the token expires takes the whole server down. A warmed
function keeps its worker and its secrets until something the runtime watches
changes - a file under the backend's source directory - which drops every idle
worker; an unwarmed function, a second concurrent call to a warmed one, or any
call after such a reload is a new worker. So the boot prints a deadline, and the
server is restarted before it for as long as anyone is testing against it.
`CONTEXT.md` section 6 carries the versions, the deadline and the commands; the
runtime's technical file carries the mechanism.

**A failed fetch may not fail the request.** Where an unresolvable secret reads
as an empty string rather than throwing, the function runs, answers normally,
and the **only** signal is the runtime's own error block in the log. The boot
check greps for that block's exact text (the runtime's technical file has it),
proved able to match under a negative control - a wrong credential produces it.
A request would otherwise be served by a third-party API client holding an
empty key.
A log streamer keeps watching for that text for the life of the server, because
a function invoked an hour later fetches its secrets then.

**That check issues three outcomes and never collapses them to two.** It says OK
only when every warmed function answered as expected and no error block
appeared; it says INCONCLUSIVE - and claims nothing - when the function listing
could not be read or was empty, when no function answered as expected (the
secret path was never exercised), or when a local secrets file is present, which
satisfies the parameters from disk and disconnects the check from the credential
it claims to measure. And it names the secrets it actually proved - the union of
what the functions that answered declare - so an unqualified "secrets OK" never
claims more than was run. A function the warm did not reach is named as NOT
covered, and that is not an OK: it is the function whose first real call after
the deadline crashes the server.

**Done when:** the server is running the RC's backend code against the live
project's data; the boot's secret check said OK (an INCONCLUSIVE verdict is
resolved before a tester is pointed at it, never read as a pass); the base URL
is recorded and is what sections 7 and 9 will build against; and both the
trigger/scheduler gap and the caller-verification gap have been stated to the
requester. **Section 7 cannot start without section 6's answer**, because
section 7's whole subject is "pointed at the new backend".

**And the step is not closed until the server is:** at the end of the
engagement the teardown runs, reports every check green and exits zero. A
non-zero exit means the window may still be open, and it is chased down before
the engagement closes.

---

# 7. Build the previous release's clients against the new backend, and distribute them

**What it does.** Reproduces the **delayed-rollout window** - the state the
product is in after every backend deploy and before a store review clears, in
which every user in the world is running yesterday's client against today's
server. It is the state that is always live, and the one a matched-pair test is
structurally blind to.

**The one tester build in the window that is not built from the RC.** Its
subject is the previous release, so it is built from the previous release's
source by construction; everything else a tester installs in the window is the
RC (section 9).

**What "the previous release" is here:** the commit each store's served build
was made from - **resolved per platform**, because a release run can upload one
platform and skip the other, so the two stores can serve builds of two
different commits. Read what each store serves from the store itself, then the
commit from the run that uploaded it. Where the install keeps no release tags,
that commit is on the release branch, identified by the version file's build
number matching the build the store is actually serving; and the release
branch's tip is usually CI's bump commit, which holds the NEXT number and was
never uploaded anywhere (`/repo-and-environments` section 4.3). `CONTEXT.md`
section 7 carries the commands to resolve it - deliberately the commands and
not the numbers, because a build number written into a document is wrong the
next time anything ships and still reads as authoritative.

## The requirement

**A bundled build of the previous release's source, wearing the live
environment's identity in every respect except where its backend calls go.**
Concretely, and every clause is load-bearing:

- **The live app identifiers (package name and bundle id), the live cloud
  project's client configuration, and live sign-in.** The tester signs in as
  themselves, against the real accounts.
- **Auth, the database and storage stay LIVE.** The client reads and writes the
  real data, which is the whole point of section 6 - a copy would answer a
  different question.
- **Every backend-code call goes to section 6's server, on every channel the
  client has, not one**: the calls made through the vendor SDK (callables) and
  any raw HTTP routes alike. One override value drives all of them (`CONTEXT.md`
  section 7 names the key and how it does it). **A redirect that moves one
  channel and not another is worse than no redirect** - see the split-brain
  warning below.
- **Delivered through the install's tester-distribution service**, to the
  requester's registered devices, like any other tester build - to the live
  environment's tester group, against the live environment's
  tester-distribution app ids (`CONTEXT.md` section 7 names the service, the
  group and the ids).

## The invocation

Both platforms, from the previous release's source; `CONTEXT.md` section 7
resolves which commit that is and carries the invocation. What it must do:

- **It sets the override for this one build only**, in the environment file the
  deploy script materializes, never in a tracked environment file and never from
  the caller's shell (a materialized file whose loader assigns its values
  overwrites a pre-exported one). The override moves every backend-code channel;
  auth, the database and storage keep talking to the live project. `CONTEXT.md`
  section 7 has the flag combination the deploy script accepts it under and the
  URL validator, which is strict on purpose: every URL shape it refuses would
  fail silently on the device rather than erroring.
- **It builds an ad-hoc, live-identity artifact for the tester-distribution
  service, never a store artifact.** The deploy script's guard matrix accepts
  the live environment with the tester-distribution target only under ad-hoc
  signing, and the store lane still requires release signing, so a non-store
  build still cannot reach a store.
- **The dependency-health gate judges an old source against the dependency
  table of the framework version it was built with**, not against the vendor's
  table as it stands today. Where the gate fetches its expected versions from a
  live vendor endpoint, a commit that passed it on the day it shipped reds once
  the vendor publishes patch releases, with the shipped dependency set
  unchanged, and the gate's own recovery (bumping) would build a client nobody
  runs. `CONTEXT.md` section 7 has the switch that points the gate at the table
  installed with the old source, and the measurement behind it. Section 9's RC
  build keeps the online gate exactly as written: the RC is current, so a red
  there is a finding about the candidate.

**The one standing control: the build-provenance gate stays exactly as it was,
on purpose.** The override is a **separate** key from the live backend URL the
provenance gate derives the live identity from (`/repo-and-environments`
section 7), so the live URL stays in the bundle untouched and the gate keeps
asserting what it always did. This is not a residual blocker; it is the control
the lane runs **with** rather than around, and nothing about it may be edited to
make this procedure run - not the marker set, not the tracked environment file.
Where the two key names share a substring, the overlap is a live hazard: a
pattern reaching for "the backend URL line" hits the marker, not the override
(`CONTEXT.md` section 7 names both keys).

**The old client exercises what the store app can reach.** This lane's clients
are the store apps, so what a tester drives here is the surface those apps call.
A surface they do not carry - an admin web app, say - is not tested through this
server even where the server serves it; `CONTEXT.md` section 7 says where the
install validates it and what residual the server's wider surface leaves.

**The split-brain shape is why the override moves EVERY channel, not one.**
Where a client resolves some backend routes from a public environment key and
the rest through a vendor SDK from the project id, a redirect that moved only
the key would send part of the product's flows to the new server while the rest
kept talking to the **live** backend - a configuration that has never existed
and never will, whose green pass would be evidence about nothing. The single
override value driving every channel is what forecloses that shape.

**iOS ad-hoc distribution has a lead time the requester will not expect.** An
ad-hoc profile embeds an explicit device list, so a device whose identifier was
not registered **before** the build cannot install it - and the failure happens
at install time on the phone, not in the release run, which stayed green because
the upload genuinely succeeded. Register the requester's device first, or the
first thing section 8 produces is a build nobody can open
(`/repo-and-environments` section 4.4).

**The build IS the provenance check on the override bundle.** The
tester-distribution build runs the build-provenance gate on the finished
artifact (`/repo-and-environments` section 7). Nothing else asserts that a BUILT
override bundle passes the gate - a check on source cannot, and a full-bundle
census needs a real build - so the tester build here is that assertion: a green
build IS the evidence that the override left the live markers intact. A red gate
here stops section 7; it is not bypassed.

**Done when:** both platforms' previous-release builds are installed by the
requester from a distribution link, each passed the provenance gate at build
time, and each is confirmed to be talking to section 6's server. **Section 8
cannot start without section 7's builds.**

---

# 8. Walk the requester through the old-client tests, step by step, per platform

**What it does.** Establishes that the installed client survives the new
backend. This is the pass that catches an interface or schema change that is
perfectly self-consistent in the new code and unreadable to the app already on a
phone - the exact failure the release branch's no-contract-changes rule exists
to prevent (`/repo-and-environments` section 3.1).

**You lead this pass and the requester follows.** You issue one instruction at a
time and wait for the requester's observed result before sending the next; their
job is to do exactly what you say and report what they saw, not to work down a
checklist on their own. Section 5b's checklist is **your** script for this, not a
worksheet handed to them. A mismatch between expected and observed stops the
pass: you investigate it before sending the next step, rather than leaving the
requester to decide whether it matters. This guided pass is how the requester's
validation of the release is conducted, and section 10's testing-phase rules
bind it: every finding is reported and fixed, no feature enters, and you ask
after each build and at the end of the pass whether anything felt weird,
unnatural or hard to use.

**Its subject is narrower than section 10's, and that is deliberate.** Run
**only** the checklist rows section 5b marked `yes`. The old client's behaviour
on features this release did not change on the server is already known; what is
unknown is how it reacts to the changed contracts. Running the whole checklist
here doubles section 10 and buries the rows that matter.

**Both directions of compatibility are in scope, and the second is the one
that gets forgotten:**

- a document written by the **old** backend still reads correctly under the
  **new** one, and
- a document the **new** backend writes is still readable by the **old**
  client.

A change that is only forward-compatible passes a single-direction test and
breaks every phone in the field.

**Format:** the six standing rules above - a QA checklist, one action and one
expected result per numbered row, one platform per message, complete iOS before
starting Android or the reverse, never interleaved.

```
<platform> - <feature> - build <version> (<release link>)

<n.1> <one action> -> <its exact observable: what appears, what it says, what it does not do>
<n.2> <one action> -> <its exact observable>
...

Reply by row number; the first mismatch stops the run.
```

**A mismatch here is a stop and usually a release blocker, not a bug to file.**
An old client failing against the new backend means the delayed-rollout window
is broken, and that window opens the moment section 11's backend deploy
completes - hours or days before any new build can reach anyone. Report it
against the feature and the contract it came from in section 5a, and do not
continue. **A fix for it lands on the RC through section 10's fix cycle** - the
same cycle, entered from here: the old client is not rebuilt (its source is the
previous release), section 6's server is restarted on the new RC tip, and the
`yes` rows are run again.

**Done when:** every `yes` row has an observed result from the requester on
both platforms, every result matches its expectation, and the observed results
are recorded against the checklist rather than only in the conversation.

---

# 9. Build the release candidate's clients against the same server, and distribute them

**What it does.** Produces the matched pair - new client, new server - which is
the state the world reaches only after the build has shipped and users have
updated.

**The agents' visual sweep runs first, before these builds are made** (the
install's UI evidence skill, `CONTEXT.md` section 0), because this is the step
that hands the candidate to the requester: over every screen section 4 lists,
on simulator and emulator builds of this RC SHA. Its findings go through section
10's fix cycle and are swept again before the builds are made. The detailed
visual rows it measured then move under section 5b's *Not on the phone*, naming
the sweep, every screen stays covered by a compact visual row (section 5b), and
the minutes are re-taken. A capture it could not drive is NOT COVERED, section
3's third state, never a pass, and the detailed rows it would have measured stay
in the walk. A visual defect the requester reports in section 10 anyway is a
sweep escape: fixed through the fix cycle, and recorded as the UI evidence skill
says. Section 7's builds are the shipped client and change no screen, so section
8 owes no sweep.

**The features' checklists are checked before these builds go to the requester
too** (`/definition-of-done` Rule 6, its feature checklist): every feature
section 4 derived has its checklist pass the checker at this RC SHA, in one run
that names the features with `--expect` and passes `--served <the RC worktree>`
(`CONTEXT.md` section 9 has the command), run by an agent that did not build
those features. Over several checklists `--served` applies one rule: the RC
worktree's HEAD contains every feature's hand-off commit, so the build the
requester installs carries every feature as it was handed off. **A feature in
the changelist with no checklist is a finding, not a skip**; a finding goes
through section 10's fix cycle like any other. The changelist names features as
a user would, and each checklist's header names the same feature, which is how a
feature is matched to its file.

**Same lane and same distribution route as section 7**, built from the RC branch
tip instead of from the previous release's commit - the identical invocation
(`CONTEXT.md` section 9), pointed at section 6's server, run in the RC worktree.
**Every tester build of the candidate comes from the RC**: this one wherever
`CONTEXT.md` section 9 says it is built - on the install's own machines when the
release workflow does not carry the backend override - and any CI-built tester
build by a workflow dispatch **on the RC ref** (`CONTEXT.md` section 9), never
on the landing branch or a fix branch. A build made from anything else is not a
build of this candidate, and a pass on it is not evidence about it. Everything
in section 7 applies here unchanged and is not restated: the override moves
every channel, the provenance gate runs on this bundle too, and the client
exercises what the store app can reach.

**One thing is different and worth stating**: an ad-hoc tester build and a store
build are **different signing identities and different artifacts**, so a pass
here is evidence about the RC's code, not about the artifact section 11 uploads.
The provenance gate is what covers that seam on the store artifact
(`/repo-and-environments` section 7), and it runs in section 11.

**Done when** the step leaves seven things proven, each recorded in the
release's ledger:

1. **Each artifact's build number equals the RC's version file at the recorded
   RC SHA**, read off the artifact itself - **check that, do not assume it.**
2. **The provenance gate reported OK on both artifacts.**
3. **Where the version file has not moved since the previous tester build of
   the candidate, the discriminators are recorded.** The two builds then carry
   the same build number, so 1 cannot tell them apart, and `CONTEXT.md` section
   9's three stand in for it: the distribution release id, proof in each shipped
   bundle that the fix is in it, and the observable the rebuilt client shows and
   the superseded one does not.
4. **Any live-project credential copied for the upload is gone afterwards** -
   confirmed by looking, not inferred from the script meant to delete it.
5. **The step started no backend server.** Booting one is section 6's move,
   timed to when a tester is on it, because an open server is the window section
   6 exists to keep short.
6. **The visual sweep is clean or NOT COVERED on every capture at this SHA**,
   before the builds were made.
7. **The checker exited 0 over every changelist feature's checklist at this
   SHA, with `--served` on the RC worktree**, run by an agent that built none
   of them, before the builds went out; its `SERVED` line is in the ledger.

Then the requester installs both from the distribution link, and the installed
build is confirmed before section 10 runs - by its build number, or on a rebuild
by the observable in 3. A tester installing yesterday's build and reporting on
it is indistinguishable from a passing test. Section 10's fix cycle comes back
here after every fix that reaches the client.

---

# 10. Walk the requester through the full QA checklist on the RC's clients, and run the fix cycle on the RC until it passes

**What it does.** Runs section 5b's checklist on the matched pair, and turns
every mismatch into a fix on the RC, a back-merge, a re-gated and rebuilt RC,
and a re-run - until every kept row has passed on builds of one RC SHA. **This
step carries the release's tester/fix cycle**, including the fixes section 8
finds. It is the pass that authorizes section 11.

**You lead this pass and the requester follows**, exactly as in section 8: one
instruction at a time, sent only after the previous step's observed result is
in; the requester does what you say and reports what they saw, and does not work
down the checklist alone. Section 5b's checklist is **your** script, not a
worksheet handed to them. A mismatch stops the pass for you to investigate
before continuing - it is not the requester's to wave past - and this full pass
is how the requester's validation of the release is conducted before it
authorizes section 11.

**Every kept row of section 5b, `client` as well as `yes`.** Section 3's gates
cover what the suite drives, and this covers what in this release it does not -
the native surface, the real gesture layer, the camera, the store and sign-in
flows, and everything a browser-driven harness is structurally blind to
(`/e2e-suite`).

**Format:** identical to section 8 - the six standing rules: a QA checklist, one
action and one expected result per numbered row, one platform per message, the
first mismatch stops the run.

**Give the expected result from the checklist, verbatim.** Paraphrasing it at
this point is how a row silently becomes a different test: the checklist row is
what section 4 derived and what section 5 delivered, and the requester's answer
is recorded against that row.

**Report progress as `N of M` and never as a percentage or a fraction of
features.** The requester is tracking one number, and it is the one they are
being asked to act on.

## The testing phase's rules

They bind every pass in the window - section 8's and this one - and every tester
build.

1. **Every finding is reported and fixed, however small.** Every minor error,
   hiccup or rough edge a tester meets is reported in the release thread
   (`CONTEXT.md` section 8), then fixed and **verified on a development build**
   of the fix branch - a dev client loading from the bundler's dev server, where
   a fix iterates in seconds (`CONTEXT.md` section 10 has the commands) -
   **before the next RC tester build is made**. The RC build is where a fix is
   confirmed, never where it is developed. **Except a defect the live app
   already has**: it is reported like any other, and the device-pass rule
   `CONTEXT.md` section 5 cites decides whether this release fixes it.
2. **The RC takes fixes to existing features, never features.** The purpose of a
   release is to finish what is already there. A request that is a feature is
   deferred to the next release **in writing, in the release thread**, and
   enters the RC by no route - not as a fix branch, not as a cherry-pick.
3. **Ask; do not wait for reports.** After every tester build is installed, and
   at the end of every pass, ask the testers explicitly whether anything felt
   weird, unnatural or hard to use. Record each answer against the checklist; an
   answer that names anything is a finding under rule 1.
4. **A feature ships only when it is 100% polished.** One that is not - a rough
   edge the cycle cannot close inside this window - is **pulled from the RC**
   rather than shipped: its revert is a fix, landed through the fix cycle below,
   and section 5a lists it under *Pulled from this release*. The feature leaves
   the release, never the trunk: the pull is recorded on the landing branch
   BEFORE the RC push that carries it, as section 11 says, so the backmerge
   carries the revert without applying it there.

## The server window, and the tester's route to it

Both bind section 8's pass as well as this one.

- **A step whose result depends on a backend-code call - anything that reaches
  the request-driven surface section 6 serves, such as a save, a submit or an
  upload's processing - measures nothing unless section 6's server is up at the
  moment the tester performs it.** Send one only while the server is up. A
  re-check sent or performed while it is down is void and is run again once it
  is back, so the message that tells the tester the server is going down also
  tells them that such an action retried before it is back counts for nothing.
- **A tester build's backend-code calls reach section 6's server over the
  private network only; its uploads and reads go to the live project over the
  public internet.** A device whose private-network client is down therefore
  half-works: the upload lands, no call arrives, and the screen spins until the
  call times out. Before every device session the tester confirms the device is
  connected (`CONTEXT.md` section 10 names what to look at), and that signature
  is checked against the server host's network log for the device before anyone
  blames the code or rebuilds.

## The fix cycle

A mismatch stops the pass (above). Once it is diagnosed as a defect in the
candidate, the fix goes through these six moves, in order, and the pass resumes
only after the last one:

1. **Fix it on the RC.** A bug branch (`/worktree-workflow` names it) cut from
   the **RC tip**, carrying the failing test first and the fix second
   (`/definition-of-done` Rule 4), iterated and verified on the development
   build (rule 1 above) before it lands. The live branch's no-contract-changes
   rule binds it (`/repo-and-environments` section 3.1): a fix that moves a
   contract is escalated, not landed.
2. **Land it on the RC**, and on the RC only - merged into the RC branch and
   pushed, with the release snapshot brought up to date by the same landing
   (below). Never on the landing branch first and cherry-picked across: that is
   the landing->RC flow the window forbids, and it would leave the RC carrying a
   commit its own history cannot explain.
3. **The backmerge job back-merges the RC into the landing branch** on move 2's
   push - RC -> landing, the one direction the window allows - so the fix is not
   lost from the trunk and the landing branch never re-breaks what the release
   fixed; then, where the install has a live-copy environment, on the same push
   it moves that environment's branch to the RC and redeploys it
   (`/repo-and-environments` section 5.2). **Check its run** (`CONTEXT.md`
   section 10): both branches contain the RC tip and the redeploy's run exists.
   A version-file conflict is computed, as in section 2; any other conflict reds
   the run, which names the paths and prints the resolution, and resolving it is
   a human's - and the live-copy branch waits for it, because it only ever moves
   to what the landing branch holds. A landing that changes a workflow file can
   be refused to the job's token (section 1): the run then says so, with the
   commands, and you run them with your own credentials.
4. **Re-run section 3's gates on the new RC tip**, and update section 5's
   documents with the fix (row, commit, SHA).
5. **Rebuild what the fix reaches, from the new tip.** A backend change restarts
   section 6's server on it (where the runtime serves compiled output, a server
   left running serves the old code); a client change rebuilds section 9 and the
   installed build number is checked again. An old-client (section 8) row the
   fix can reach is run again on section 7's unchanged builds.
6. **Resume the pass**, once the sweep has run again on every screen the fix
   reaches and the checklist run has passed again at the new tip (section 9,
   item 7): the failed row first, then every row the fix can reach on both
   platforms - reach measured as section 4 measures it, from the fix's diff -
   and every dropped entry it reaches that section 5b's decision now keeps. A
   row the fix cannot reach keeps its earlier observed result, **recorded
   against the RC SHA it was observed at**.

**Every landing on the RC keeps section 1's release snapshot current**, where
the install keeps one - a fix's, a pull's and an approved cherry-pick's alike.
When a landing takes the still-being-built mark off frames on the design
source's current page, the same landing copies those frames into the snapshot:
each copy replaces the frame it supersedes, or is added in its screen's place,
and is cut loose from its masters by section 1's rule (the design-source skill
owns the mechanics). **The snapshot never records unshipped UI**, which makes
two exceptions:

- **A frame that also draws rows or states for features NOT yet on the RC is
  held back** - a settings screen drawing switches for two features still
  unlanded, say - and is copied by the landing that brings the last of those
  features onto the RC.
- **A feature that drops out of the release stops holding a frame back** -
  pulled under rule 4 of the testing phase's rules, or left for the next
  release: its rows are removed from the snapshot copy instead, and the frame
  is copied without them.

**The pass is complete when every kept row's latest observation is a match and
every row the fixes can reach was observed on builds of the final RC SHA.** That
SHA is the one section 11 lands; write it at the top of the completed checklist.

**Done when:** every kept row has an observed result on both platforms, every
result matches its expectation, the final RC SHA is recorded, every fix the
cycle landed is back-merged into the landing branch, every capture of the sweep
is clean or NOT COVERED, recorded against the RC SHA it was taken at, the
checklist run (section 9) passed at the final RC SHA, every sweep escape
(section 9) is recorded, every frame an RC landing took the still-being-built
mark off is in the release snapshot or held back with the features it waits for
named (where the install keeps a snapshot), and the completed checklist - with
the observed column filled in - is delivered back to the requester as the
evidence section 11's authorization rests on.

---

# 11. Merge the validated RC into the release branch and confirm the builds are delivered

**What it does.** Moves the release branch to the validated RC tip, which is
what queues the store builds and closes the release window. **The store build is
that commit and no other** where the store lane enforces it: the deploy script's
store target refuses every branch but an RC, and accepts the release branch only
in CI, where this step's fast-forward has made its tip the RC's (`CONTEXT.md`
section 11 has this install's rule). Where the lane does not enforce it, the
checks below are the only guard, and the report says so.

**It is authorized by a person, not by a green gate.** Section 5a's
contract-changes lines and section 10's completed checklist are the evidence;
the decision is the `CONTEXT.md`-named person's, per the standing tension above.
**Get it before you push, not after.**

**Every release-plan step due before this merge is applied BEFORE it.** The
entry for the version being promoted carries the version-specific steps these
twelve steps and CI do NOT enforce (section 1, and the preamble). A step still
`[ ]` is a step the merge ships without. Each of them is done and marked, or
taken to the person authorizing the merge; the merge does not proceed over an
un-applied step. A step the entry marks to run after the push - a store-listing
edit, say - is confirmed as owned, not as done.

**Merge direction: RC branch -> release branch.** Resolve nothing on the release
branch - if the release branch has moved since section 2, merge it into the RC
again first and resolve there, which moves the RC and sends it back through
section 3 and the rows that merge can reach.

**The gate-outcome file reaches the release branch only by a FAST-FORWARD of the
gated SHA**, where section 3's dispatch commits one. That file is the quality
workflow's own assertion that every gate was green **on one tree**. Carrying
that assertion onto the release branch is honest only when the release branch
fast-forwards to exactly the SHA the gates ran against, because then the tree
that lands is the tree that was measured. **Where that fast-forward is not available - the RC
moved after section 3, or the release branch moved - the gates run again, on
the final tree, before the merge:** not the RC's tree as gated, not the release
branch's, but the merged result about to be pushed. Re-running is the cheap half
of this rule. The expensive half is what it prevents: a green assertion sitting
on the release branch about a tree nothing ever measured is a claim no later
reader can falsify, and it is indistinguishable from a real one.

**A pulled feature is recorded on the landing branch, not reverted there.** Its
revert (section 10, rule 4) is an RC commit like any other, and the backmerge
carries every RC commit into the landing branch, where it would delete a feature
that is only leaving THIS release. So the pull is recorded on the landing branch
first: merge the pull branch's tip into the landing branch with
`git merge -s ours`, which marks the revert as merged while keeping the landing
branch's content, and push that BEFORE the RC push that carries the revert
(`CONTEXT.md` section 10 has the commands). The backmerge then finds the revert
already merged and applies nothing of it. Done after the RC push, it is too
late: the revert has already reached the landing branch. **`-s ours` marks the
revert's whole ancestry merged, applying none of it**, so it is made only once
the landing branch already holds everything the revert sits on - every earlier
RC landing back-merged. Otherwise an RC fix underneath it is marked merged into
the landing branch without its content, and is lost there silently.

**Re-derive section 4's commit range first, and account for every commit in
it.** It must be section 4's range plus exactly what the window allows onto the
RC: section 10's fix commits and the approved cherry-picks section 5 lists, with
the version-bump and gate-outcome commits CI writes. **A commit outside those is
a landing->RC flow nobody approved**: stop, and take it to the person
authorizing the merge - it goes back out of the RC, or it is approved and the
passes it can reach run again. **Do not silently ship a range nobody was
shown.**

**Only CI's own commits may sit above section 10's final RC SHA.** Two kinds are
allowed past it: the version-bump commit a CI tester build dispatched on the RC
writes, and the gate-outcome commit a green section 3 dispatch on the final tree
writes, which `CONTEXT.md` section 11 describes as the intended state. So
`git diff <final RC SHA>..<RC tip> --name-only` names the version file, the
gate-outcome file, both, or nothing. Anything else is code no tester ran, and it
goes back through sections 3 and 10.

**Say what the push will fire BEFORE you fire it.** The release workflow's path
filters are wider than they look: one push can queue a backend deploy, a web
deploy and both native builds at once (`/repo-and-environments` section 3.2).
`CONTEXT.md` section 11 says how to read what this particular push will trigger.

**Then verify delivery, and every one of these is a separate check:**

1. **The push arrived, by CONTENT.** A green exit code is not arrival: prove the
   commit is an ancestor of the remote release branch and that the branch's tree
   carries the change (`/worktree-workflow`).
2. **A workflow run exists FOR THE PUSHED SHA.** This is a different check from
   "the run went green", and it is the only one that catches the `[skip ci]`
   no-op section 1 told you to watch for: a version-bump tip suppresses the
   entire release, silently, with the branch advancing and nothing red. **The
   RC's own tip is a version-bump commit whenever a CI tester build was
   dispatched on it last**, so read the subject of the commit you are pushing,
   not only the one section 1 recorded. **Never read a successful push as a
   fired release.** Recovery is a dispatch of the release workflow on the
   release branch that force-runs every job regardless of the path filter
   (`CONTEXT.md` section 11).
3. **The deploy jobs RAN rather than skipped.** A run that completes green with
   every deploy job skipped is a release that deployed nothing. Read the
   change-detection step's log line, which names the two refs it compared
   (`/repo-and-environments` section 5.1). A run that skips every DEPLOY job is
   not by itself this defect - a docs-only push skips them correctly - so read
   the refs before diagnosing. **And the converse: a failed run is not
   necessarily a failed release.** A release workflow can carry a job that is
   not a deploy and that nothing depends on; a red run whose deploy jobs are all
   green is that job, and its own log says what it found. Read the per-job
   results, never the aggregate conclusion, and do not read that red as "the
   release is broken" (`CONTEXT.md` section 11 names any such job and what its
   red means).
4. **Both native builds reached their lane.** The store lane's upload is what
   the version bump gates on, so a bump that did not happen is evidence an
   upload did not (`/repo-and-environments` section 4.3).
5. **Two post-upload failure states need a human, one per platform**, and they
   share a shape: the failure happens **after** the upload, so the build number
   is burned on the store while no receipt is written and no bump happens.
   **Check the store console for the build's state before retrying anything**,
   and if it uploaded, advance the version file by hand in the same sitting. **A
   rejected upload is recovered by a NEW push, never by re-running a BUILD
   job** - that re-run reads the same version file and is refused identically.
   **The BUMP job is the opposite case**: re-running it is safe and is the valid
   recovery, because it adopts its own bump commit rather than minting a second
   number - so read GitHub's "Re-run failed jobs" (only what went red) and
   "Re-run all jobs" (which restarts the builds too) as two different actions
   here (`/repo-and-environments` section 4.3).
6. **The backmerge carried the version back to the landing branch.** It runs
   **twice** per release, and the second, dispatched run is the load-bearing one
   (`/repo-and-environments` section 5): it is the only way the landing branch
   ever learns the build number this release consumed. Confirm the landing
   branch's version file actually moved - without it, the landing branch's next
   native build reuses a burned number and is refused (`/repo-and-environments`
   sections 4.3 and 5).

**The release is IN FLIGHT for as long as the native builds take, and the
version-bump commit lands only at the end of that window.** Do not push another
native-affecting commit to the release branch while it is open: such a push
builds from a tree that predates the bump, uploads a number the first run
already consumed, and both stores refuse it (`/repo-and-environments` section
4.3). Wait for the bump commit, or dispatch. **This is also why steps 1 to 10
happen before the push and not alongside it** - there is no safe way to fix
something on the release branch while a release from it is running.

**The window closes here.** Announce it: the RC is released, a fix for this
release from now on is a live-line fix (`/repo-and-environments` section 3.1),
and a tester build of the next candidate waits for the next cut.

**Remove the promoted version's entry from the release plan** once every step
in it is `[x]`. A step still pending after the push keeps the entry, with its
owner, and whoever marks that step done removes the entry. Entries for later
versions stay. An entry left behind reads as steps still owed.

**Finalize the release snapshot** section 1 made and section 10 kept current,
where the install keeps one: rename it with the released version's `x.y` and the
release date; delete from it the frames of every feature section 5a lists under
*Pulled from this release*, and that feature's rows from a frame it shares with
what ships; and settle every frame section 10 still holds back - a feature not
on the validated RC is not in this release, so its rows come out of the copy and
the frame is copied without them (section 10's exceptions). It is the design
file's current release page until the next release's section 1 makes a newer
one, which moves it to the design archive (`CONTEXT.md` section 11 has the
move's commands; the design-source skill owns the rule that the delete follows
only a proven move).

**Done when:** all six checks are affirmative, each stated separately, with the
release-branch SHA, the run id, the build numbers uploaded per platform, and the
landing branch's post-backmerge version file value; every release-plan step due
before the merge was applied before it and the promoted version's entry is
removed, or kept only for post-push steps that have owners; and the release
snapshot, where the install keeps one, carries the final name, no pulled
feature's frame or row, and no frame still held back. **Report what the push
triggered, not what you expected it to trigger.**

---

# 12. Guide the requester through submitting to review and publishing

**What it does.** Takes the build from "uploaded" to "in review" to "released"
on both stores. Everything before this runs on the install's own tooling; this
happens in two vendor consoles it does not control.

**Where the install keeps a record of the client builds in use, it follows the
stores.** On the day this release reaches users on a store, which comes after
this step's done-condition, its build joins the record and every build whose
measured use has fallen below the install's cut-off leaves it, in one landing on
the landing branch with each value read from git at that build's commit. The
agent that ran the step arms a check for that day (`/scheduled-tasks`) instead
of waiting to be asked. `CONTEXT.md` section 12 names the file, the measurement
and the cut-off.

**Where the install bounds a minimum supported app build, a second record
follows the stores at a STRICTER moment: the store's live build.** When the
build is LIVE on a store - every user of that store can install it, not merely
some - the requester sets that store's live build in the control the install
has for it, in their own session; the agent arms a check for that moment too,
because it can come days after the build joins the record above. **The two
records are different and are never set from each other**: the in-use record
holds a build SOME users run, the live build is the newest one EVERY user of
that store can install, and a live build recorded early is a ceiling that lets
the minimum strand the users who cannot install it yet. Forgetting the live
build only stops the minimum being raised past the old value; it never blocks a
user. `CONTEXT.md` section 12 names the control and what LIVE reads as in each
console.

## What is already automated, and where the manual part begins

The store lane does the upload and sets the release note on both platforms, on
Play in the default language only (12b step 5 is the rest): the iOS lane uploads
to TestFlight, and the Android lane uploads to the environment's configured Play
track and verifies the stored artifact digest afterwards. `CONTEXT.md` section 12 says what this
install's lane automates and how it is configured today.

**Where the iOS lane does not wait for App Store Connect to finish processing,
the build is normally still `Processing` when you arrive at this step, and the
wait for `Processed` is yours to perform.** fastlane's pilot returns as soon as
the build row appears when its `skip_waiting_for_build_processing` option is
set; `CONTEXT.md` section 12 says whether this install's lane sets it. Two
consequences to carry into
12a: the build may not be listed as selectable for minutes after a green
release run, and a processing REJECTION surfaces only here - the release run
went green, the build number is already burned, and the version file has
already advanced (`/repo-and-environments` section 4.3). Where the lane does
attach an external tester group, it also submits for Beta App Review; where it
does not, the build reaches internal testers only. `CONTEXT.md` section 12 says
which is currently the case, and that is the fact that decides how much of the
manual sequence below is needed.

**So the manual part starts at: a processed build exists in App Store Connect,
and an uploaded artifact exists on the configured Play track.** Nothing below
uploads anything.

**These two sequences are the most perishable content in this file.** Both
consoles are redesigned without notice. Present them as written, and the
**instant** the requester reports that a screen, a button or a label differs
from what you gave them, **ask them what they see, and correct this section in
this engagement** (the living-document rule says where a correction lands) -
before continuing the sequence, so the correction is made while the evidence is
in front of you. That is not optional tidying; it is what the living-document
rule is for, and this section is where it is cashed.

## What these two sequences have and have not been proven against

They are written from the consoles as they stand and have **not** been driven
end to end from this file. So the honest claim is: *this is the sequence to
present, and its first use is also its first validation.* That is not a reason
to withhold it - a requester with a numbered sequence that is 90% right gets
further than one with none - but it **is** the reason the correct-in-place rule
above is stated so hard, and the reason you ask "does your screen match this?"
at each step rather than only when something breaks.

**Present each console as its own numbered sequence with its own `M`**, and say
both totals up front so the requester knows the shape of what they are agreeing
to: App Store Connect below is 10 steps, Play Console is 9. Re-derive both after
any correction - a step you split makes `M` move, and the standing rules require
you to say so.

## 12a. App Store Connect

Presented as a numbered checklist per the standing rules: one console action and
its expected result per row.

1. Sign in to App Store Connect and open the app record.
2. **TestFlight** tab. Confirm the build this release uploaded is listed, then
   **wait until its status reads processed rather than still processing** -
   where the lane does not wait for processing (above), **expect to find it
   still processing and expect to wait here**, and where the build is not listed
   at all yet, that is earliness rather than a failure. Match it by **build
   number** against section 11's report, not by "the newest one". **A processing
   failure appears at this step and nowhere earlier** - the release run is
   already green and the build number already burned - so if the status
   resolves to anything other than processed, STOP: that is a release blocker,
   not a console hiccup, and the recovery is a new push, never a re-run
   (`/repo-and-environments` section 4.3).
   **Then read the build's What-to-Test text and confirm it is not empty.**
   This is a SECOND check, not a restatement of the first, and it is here
   because the upload tool can report the note set when it wrote nothing:
   fastlane's pilot reads the build's localization list at the moment the build
   row appears, and an empty list means it writes no note, raises nothing, and
   prints success anyway. No static gate in a repository can see that - it is a
   race - so this human read is the only thing standing between it and a release
   with a blank note. An empty note is repaired by hand in the console; it is not
   a reason to re-upload.
3. Where an external test is wanted and the build was not auto-attached: attach
   it to the external group and supply the Beta App Review information the form
   asks for. Where no group is attached by configuration, skip this and say you
   skipped it.
4. **Distribution** (App Store) tab. Create the new version, or open the version
   already in a `Prepare for Submission` state.
5. Set the version's **What's New** text.
6. **Build** section: select the build from step 2.
7. Answer the export-compliance and content-rights questions the form presents.
8. Confirm the release option - automatic on approval, manual, or phased.
9. **Add for Review**, then **Submit for Review**.
10. Confirm the version's state reads as waiting for review.

## 12b. Google Play Console

**Start on the track the artifact was actually uploaded to, not on Production.**
The upload goes to the track the install's lane is configured with, and where
that is a pre-launch track the first action is to open **that** track and
**promote** its release, not to create a new Production one - creating a new one
there asks for an upload that already exists somewhere else. `CONTEXT.md`
section 12 says which track is configured today.

1. Sign in to the Play Console and open the app.
2. **Release ->** the track named in `CONTEXT.md` section 12, to find the
   uploaded release; then **Production** (or whichever track this release is
   being promoted to).
3. **Promote release** from the track the upload landed on, or **Create new
   release** where the target track is where it already is.
4. **App bundles**: the artifact is already uploaded, so select it from the
   library rather than uploading anything. Match it by **version code** against
   section 11's report.
5. Set the release name and the release notes. **The release-notes box carries
   one block per language of the main store listing** (`<en-US>...</en-US>`,
   `<de-DE>...</de-DE>`, ...), including listing languages the app itself is not
   translated into. Where the lane fills the default language's block alone (the
   note `/repo-and-environments` section 4.5 describes), every other block holds
   Play's placeholder line, `Enter or paste your release notes for <lang> here`.
   **Delete every block except the default language's** - Play then shows the
   default-language note in those languages - or replace a block's placeholder
   with a real note in that language. **Never submit with a placeholder line
   left in**: whatever a block holds is published to users in that language.
   Measured 2026-10-15.
6. **Next**, and resolve any errors or warnings the review panel raises.
7. **Save**, then **Send for review** (or **Start rollout to Production** where
   the release is already approved).
8. Set the rollout percentage where a staged rollout is wanted.
9. Confirm the release's status reads as in review or rolling out.

**Done when:** both stores report the release as submitted for review or rolling
out, the requester has confirmed each console's final state in their own words,
**section 6's backend server has been torn down and its teardown reported every
check green** (it is the only mitigation there is, and nothing before this point
ends it), and **any step whose UI differed from the text above has been
corrected in this engagement, where the living-document rule says.** Say in the
report which steps you corrected, or that none differed.
