---
name: software-development
version: 1
description: >
  How an agent develops software, as short rules each with the reason that
  earns it: scope and isolation before the first write, the shape of a code
  change and how a changed contract fans out, root cause before a fix, what
  counts as evidence that a change works, landing and cleaning up, finishing
  and reporting, briefing and reviewing delegated work, running unattended, and
  releasing. Practice only - the install's own process, named by its
  conventions keys, outranks it. Load before starting any change to a
  codebase, before briefing or reviewing another agent's change, and before
  reporting a change as done.
requires_install: false
---

# software-development

How an agent develops software: practice, not process. The steps a change goes
through, their order and their gates belong to the install, named by its
conventions keys (`fleet settings conventions`): `workspace`, `branch_naming`,
`definition_of_done`, `feature_checklist`, `environments`, `release`. Where a
key names a skill or a document, that text outranks this file; where a key is
`null`, the practice here still holds and no step is invented to fill the gap.
Who may ask for work, and whose approval it needs, is your charter's (`/agent`
section 1).

## 1. Before you start

- **Get the owner's explicit approval before changing stored data, a schema, a
  public interface or the development process.** A revert does not undo these;
  silence or a relayed "yes" is not approval.
- **Do the task you were given; when it grows, say so before acting.** Scope is
  chosen, not drifted into.
- **Cut scope, never completeness.** A smaller change that is whole on every
  surface it touches beats a larger one landed in part: the promised follow-up
  often never comes. Inside that scope build the general mechanism, and leave
  rare edge cases to a later change.
- **Read before writing: the project's tool index, its architecture notes, the
  design of what you are changing, and the vendor's current documentation.** The
  helper probably exists, and memory or an old note states a past state.
- **Isolate before the first write: each change in its own worktree, on a fresh
  branch cut from the freshly fetched branch it will land on.** No file class is
  exempt: a shared checkout has one index, so another session's commit publishes
  your unfinished files. The `workspace` and `branch_naming` conventions say
  where and under what name.

## 2. Changing code

- **Never repeat code.** The copy that gets fixed and the copy that does not is
  how a fixed bug comes back.
- **Two copies of a number are not two copies of a claim.** Before removing a
  repeated literal, name what each occurrence asserts. A limit derived from the
  module it limits agrees with that module when it is broken, so an outside fact
  is written by hand once, with its source; and two look-alike constants may be
  correct at different values.
- **Prefer the change that makes the codebase smaller, and a maintained library
  over owning a protocol.** When two designs work, ship the one with less code
  and say so. "Extend what we already have" looks like reuse until you are
  implementing someone else's specification.
- **One tool with a mode flag, never sibling scripts, and its index row in the
  same commit.** Siblings drift silently, and an index is read as complete: a
  missing row means "no such tool".
- **Run, build, test and deploy through the project's own entry points; extend
  one when it cannot do what you need.** A hand-rolled equivalent omits the
  guards its author did not know about.
- **A changed contract fans out to everything that states it.** A required
  argument, an enumeration, a schema, a route or a config key reaches every
  caller, copy, test, document and written count, and the tool's own usage and
  error text. Find the set by searching, never from memory, change it in the
  same commit, and make a found copy read the one source: never sync two.
- **Never pick a backward-compatibility posture silently.** Installed clients
  and stored records outlive the deploy: say what each sees after the change,
  and test it.
- **Fix the pre-existing bug, error or warning you meet, and propose the
  refactoring you see.** Inside your scope, fix it; outside it, report it with
  the commit you read.
- **Comments and documents state what is true now; the commit message holds the
  history** (`/agent` section 7).

## 3. Fixing a bug

- **Confirm the cause before fixing: add logging and reproduce.** A symptom with
  a plausible mechanism is a hypothesis, whoever supplied it. Read the log the
  failure produced before reasoning, and treat a second patch for one symptom as
  the signal to revert and measure.
- **A reported bug gets a test that fails on the unfixed code, then the fix,
  then the test stays in the suite.** A test that never failed has not been
  shown to detect anything.
- **An urgent fix lands alone.** Its clean-up and documents are a second
  landing, so the fix does not wait for them.

## 4. Proving it

- **Verify with the checks that can see the change, and nothing more.** A
  server-only fix runs its typecheck, lint and the test that pins it; the full
  ladder (end-to-end, devices, a person's pass) is for what a user can see or
  feel.
- **Show the check failing without the change, for the reason its name claims.**
  A check that cannot go red measures nothing; one that goes red for another
  reason guards a different thing.
- **A check has three outcomes: pass, fail and no verdict.** A run that judged
  nothing is neither. Write a gate as an if/else that exits non-zero: a success
  line chained with `&&` prints nothing on failure, and a pipe replaces the exit
  code.
- **Green on a run that skipped the job is not evidence the job passes.** A path
  filter is a machine for not exercising lanes.
- **A guard that checks a string's shape cannot see its content go stale.**
  Where you can, make the real tool the oracle and replay the recorded
  invocations through it.
- **Two checks with a shared blind region are one check.** Their agreement says
  nothing about what neither can see.
- **When a check disagrees with the artifact, suspect the check first.** Settle
  it with a positive control: the same instrument on a case known to be bad.
- **An all-clear needs stronger evidence than a finding.** A wrong all-clear
  tells everyone to stop looking. An absence is a claim about what was searched:
  name the scope and the revision, and prove the search could have found it.
- **When the evidence points one way and the choice is reversible, decide.** How
  hard an action is to undo sets the bar for proof, not how important it feels.

## 5. Landing

- **Finished work is landed work.** Merge the landing branch into yours, resolve
  conflicts there, pass the check the `definition_of_done` convention names,
  then push. Work parked on a branch ships nothing and rots against a moving
  trunk.
- **Commit your own paths only (`git commit -- <paths>`), and never rewrite
  history someone may have built on.** A bare commit publishes whatever else is
  staged; under a live committer merge, do not rebase.
- **Have a reader who did not write the change search for everything it made
  stale.** The author's model of the change is the one that says nothing else is
  involved. Each hit is read in context, then fixed, deleted or noted as kept.
- **Write, read back, then announce.** A push can print success and carry
  nothing: fetch, then read the change on the remote branch.
- **Clean up as part of the task:** the branch locally and on the remote, the
  worktree, temporary files, and the system state you changed (a service, a
  port, a background job). The test is whether the machine is as it was before
  the task; version control sees less than half of that.

## 6. Finishing and reporting

- **Finish before you stop.** Never end a turn while a command you launched is
  still running: it ends with the turn and the work stalls in silence. Past
  about twice its expected time a command is presumed runaway; read its log,
  then stop it.
- **Stop mid-task only at a concrete blocker, naming what you need and from
  whom** (`/agent` section 6, `/talking-to-humans`).
- **Report what you measured, on which commit and in which tree, and what you
  could not establish.** Name the tests you ran, never "tests pass"; state only
  numbers you produced; say the smaller true thing in place of the larger
  unproven one.
- **A correction reaches every copy of the wrong version, and the retraction
  stays visible.** A fix in prose loses to a stale table row, and a quietly
  deleted claim is re-opened by the next reader.
- **A lesson worth keeping goes to the knowledge store** (`/knowledge-base`).

## 7. Delegating

- **A brief carries the goal and what done looks like, what is ruled out, the
  files to read, the fence (paths owned, branch, what not to touch), the fan-out
  search to run, the clean-up as literal commands, and the shape of the
  report.** The brief is all the worker knows, and a fenced worker has no
  licence to look further.
- **Write observations into a brief, never diagnoses, and acceptance criteria
  that can produce their own evidence.** The worker builds on a wrong premise;
  for each criterion name the command that satisfies it and the change that
  would fail it.
- **Run independent pieces in parallel, and own the merge.** Independent means
  disjoint files, no ordering, no shared mutable resource. Two correct changes
  can merge cleanly into a wrong whole: check the combined tree.
- **Review comes from someone who did not build it, asked to falsify.** Ask
  "could this introduce another bug", and withhold your own reading: a reviewer
  who can infer the answer you want returns it.
- **A worker's report is testimony: verify it before you repeat it, then land
  and clean up what the worker produced.** A claim relayed three times is one
  source, and a branch tip is read at merge time, not from an earlier poll.

## 8. Running unattended

- **A confirmation prompt nobody can answer stops the session for good.** Spell
  out the paths of a destructive command, never build them from a variable or
  loop over one, and write a worker's clean-up that way in its brief: the worker
  cannot rewrite the command it was handed.
- **List what a delete will match before running it, and never widen a command
  that was refused or fell short.** The broader second attempt drops the guards
  of the first. A refusal is information: find out whose state you met.
- **Never print a secret.** Check that a credential and its keys exist without
  showing values, and say so in any brief that goes near one; a slip goes to the
  credential's owner.

## 9. Releasing

The `release` and `environments` conventions own the procedure. These hold
under any of them.

- **Cut the release candidate once and freeze it.** Tester builds come from it,
  a fix found in testing lands on it and is merged back, no new feature enters:
  what ships is the commit that was tested.
- **The live line takes critical fixes only: no new feature, interface or schema
  change.** When the only fix you can see changes a contract, escalate.
- **Write down what a release needs the moment you learn it, with its status and
  owner.** A step that lives in one head is the step the release ships without.
