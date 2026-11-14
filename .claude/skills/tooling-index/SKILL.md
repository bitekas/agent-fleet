---
name: tooling-index
version: 1
description: >
  The index of every reusable tool a repository owns, and the rules that keep
  it true: one row per tool saying what it is for and where its real
  documentation lives, the same-commit rule for adding, renaming or deleting a
  tool, why an index that is only sometimes updated is worse than no index,
  why changing a tool's interface counts as renaming it and how far that fans
  out, and why one tool with a mode flag beats adjacent sibling scripts. Also
  owns the rule that a framework-managed package is added only through the
  framework's own installer. The index itself is the install's CONTEXT.md for
  this skill, which loading the skill does not load. ALWAYS load before
  building any helper script - the tool probably already exists - before
  adding, renaming or deleting a reusable tool, and when you need to know
  which tool owns a job.
requires_install: false
---

# Tooling index

One line per reusable tool: **the map, not the manual.** This file is the
mechanism. **The index itself is the install's `CONTEXT.md` for this skill**
(`fleet where tooling-index CONTEXT.md` prints its path). Loading this skill
loads this file only, so open that one too: the rules below without the rows
answer nothing. An adopter writes that file wholesale and never edits this one.

The commands and the scratch location named below are keys in this skill's
`config.json` in the install context (`fleet where tooling-index config.json`),
written here as `packages.add_command` and never as the value.

---

## 1. Read the index before you build a helper

The index exists for one reason: **the tool probably already exists.** A second
copy of a helper is a bug rather than a shortcut - the copy that gets fixed and
the copy that does not is how a fixed bug comes back, and neither copy's author
is present when it does.

So the index is a *load-before* artifact, not a reference. Reading it after
writing the helper recovers nothing.

## 2. What a row is

**A name, one line of purpose, and a pointer to where the full documentation
lives** - the tool's own header, a README beside it, or the skill that owns it.
The row is deliberately too short to reconstruct the tool from, because the
documentation must have exactly one copy and that copy belongs next to the
code.

- **The source header is usually the ONLY copy of a tool's contract.** Deleting
  a comment there takes its knowledge with it and the index cannot restore it.
  Say so in the row where it is true.
- **A row names the OWNER when the tool belongs to another skill or package.**
  The index spans ownership boundaries: the reader's question is *"does this
  exist"*, not *"whose is it"*, and a tool omitted because someone else owns it
  is a tool that gets rewritten.
- **A row may carry the caveat a caller cannot discover from the interface** -
  a third exit state that is not a pass, a self-test that must be run first, a
  mode that must stay serialised, a value that must never be pinned. Anything a
  caller would otherwise learn by being wrong.

## 3. The same-commit rule

**Adding, renaming or deleting a *reusable* tool updates the index in the same
commit.** Not the next commit, not the cleanup pass.

One-off scripts are exempt, and they belong outside the repository -
`tooling.scratch_dir`, or an ignored directory - so that "is it in the index?"
and "is it reusable?" never become two questions with different answers.

## 4. Why a sometimes-updated index is worse than no index

**An index is read as COMPLETE.** That is its entire value and its only failure
mode, and the two cannot be separated.

If a reader knew the index were partial they would keep looking, and the index
would merely be slow. Because it presents as complete, **a missing row is read
as "no such tool exists"** - and the reader then writes the second copy the
index exists to prevent, in good faith, having done the check they were told to
do. A stale row is the same failure with the reader's time spent first.

Nothing can detect this. No typecheck, test or lint reads the index, so the
same-commit rule above is not tidiness: it is the whole mechanism, and it is
enforced only by whoever is editing the tool.

## 5. Changing a tool's INTERFACE counts as renaming it

A newly required argument, a retired flag or a changed default is a rename, and
the fan-out **reaches further than this index**. It reaches every caller:
automation steps, package scripts, whatever another tool prints as a suggested
command, docs, skill prose - and, last and worst, **the tool's own usage text
and the remediation it prints when it REJECTS you.** That message reaches the
one reader who is already blocked and copy-pasting, at the moment they have the
least ability to notice it is wrong.

**What it costs when it fires:** a build script's newly required flag that
reaches none of its automation's call sites and none of its own rejection
messages breaks every build that goes through them, on every branch, and the
reader it stops is handed a remediation that names the form which no longer
works.

Two corollaries, both of which look like reassurance and are not:

- **Green automation on a run that SKIPPED the job is not evidence the job
  passes.** A path filter is a machine for not exercising lanes, so a streak of
  changes that miss the lane hides the breakage and the next change that hits it
  pays for the whole streak. A breakage one run would have shown in minutes
  stays hidden for as long as the streak lasts.
- **A guard that checks a string's SHAPE cannot see its CONTENT go stale.** A
  guard asserting that each rejection message *names a corrected invocation*
  stays green while the invocation it names stops working, because it never
  runs that invocation. Where you can, **make the tool itself the oracle**:
  replay every recorded call site through the real tool, so a flag made
  required tomorrow reds every stale caller with no edit to the guard. Where you
  cannot, say in the row that the sweep is by hand.

## 6. One tool with a mode flag, not adjacent sibling scripts

Two scripts that share an auth layer, a comparator, a resolution rule or a
target-selection step will drift, and the drift is silent because both keep
working. **One tool, two modes** - and one copy of the shared part.

- Its counterpart: when two tools genuinely need the same core, **extract it and
  require it; never re-inline it "to keep the script self-contained."** One
  definition is the point: tuning a discriminator must not be able to leave a
  twin behind, and a copy re-inlined into a caller is the twin.
- **A mode name that reads as one thing while meaning another is retired, not
  aliased.** An abbreviation that reads as the live environment, on an alias
  that means nothing of the kind, is how a seed intended for one target reaches
  another; a compatibility alias keeps the misreading alive forever.

## 7. Framework-managed packages are added only by the framework's installer

Where the repository is built on a framework that ships its own compatible
package set (`packages.ecosystem`), a package belonging to it is added or
bumped **ONLY** through the framework's own installer
(`packages.add_command`). A plain package-manager install of one is always
unsafe in such a repository, whatever its packages declare. Where
`packages.ecosystem` is `null`, the repository has no such framework and this
section does not apply.

**The mechanism, not just the instruction**, because the mechanism is what makes
it invisible: the package manager can check only the peer range each package
declares on the framework, and **only the framework's own compatibility table
can see a mismatch**; the installer is the tool that consults it. Where those
packages declare that range as a wildcard, the package manager has **no
constraint to check** - no warning, no peer conflict, no lockfile complaint,
ever - and the ecosystem's normal safety net is structurally disabled by
design. Where they declare a real range, it checks only that range, which is
usually wider than the table. **The rule holds either way; the declaration
decides only how silent the failure is.** Read one of the framework's own
package manifests to know which case you are in, record in the install's
`CONTEXT.md` which package you read and at which framework version, and read it
again when the framework is upgraded.

**What it costs when it fires:** nothing warns, or only the declared range
does, while the dependency set drifts behind the framework's table, so the
first symptom can be a built artifact that fails at launch - on a framework
with native modules, a missing native symbol - after it has shipped. Recovery
and alignment are `packages.fix_command`, then `packages.doctor_command` until
it exits clean. Where `packages.doctor_command` is `null` the framework ships no
doctor, and the installer is the only instrument that sees a mismatch.

**A gate that enforces this reads the EXIT CODE, never the number of checks the
doctor reports.** The tally moves with the framework version, so a pinned count
reds on an upgrade that changed nothing - and the fix a blocked reader reaches
for is to relax the gate, which is the one outcome the gate exists to prevent.
