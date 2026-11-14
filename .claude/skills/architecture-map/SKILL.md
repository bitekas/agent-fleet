---
name: architecture-map
version: 1
description: >
  The cross-cutting architecture map a codebase keeps, and the rules that stop
  it becoming a second copy of the design it points at: what earns a slice, how
  a slice names its owning design package instead of restating it, why a count
  is never written into prose, how a slice records its traps and both halves of
  a pair that must not be generalised, where the contracts no single component
  owns are written down, and how the map is kept current when a component
  moves. The map itself is the install's CONTEXT.md for this skill, which
  loading the skill does not load. Load before changing anything that spans
  components - a request or data-processing pipeline, an API surface,
  telemetry, an auth or account-lifecycle path, or anything that stores,
  exports or purges user data - and again before writing a slice.
requires_install: false
---

# Architecture map

A codebase past a certain size keeps exactly one cross-cutting map. This file
is the mechanism: what such a map is for and the rules that keep it worth
reading. **The map itself is the install's `CONTEXT.md` for this skill**
(`fleet where architecture-map CONTEXT.md` prints its path). Loading this skill
loads this file only, so open that one too before changing anything it covers.
An adopter writes that file wholesale and never edits this one.

Every rule below protects one property: **a reader must be able to trust the
map more than the code comment they just found.** A map that has been wrong
once is thereafter read the way that comment is read, which is to say not at
all, and the effort that built it is gone.

---

## 1. What the map is, and what earns a slice

**Cross-cutting facts that span components.** A slice earns its place when no
single component file can own the fact, because the fact is true of the *seam*
between components: a pipeline's pass ordering and which pass is the sole data
source for a surface, an auth path's effect on identity elsewhere, what a
delete or a merge does across two subsystems, which third-party sinks user data
reaches and under what contract.

**Each slice names the design package that owns it**, a directory under
`design.packages_dir` (this skill's `config.json` in the install context):
read the package before changing that slice. The map is **the index and the
invariants, never the design.** A fact that one file already owns and a reader
can derive from it does not earn a slice; a pointer to that file might.

## 2. The map points at the authority. It never becomes a second copy.

A second copy is the copy that goes stale, and the two copies are
indistinguishable to whoever finds one of them first. So:

- **Never write down a count the code can be counted from.** Write the
  *derivation* instead: which file, which literal, what to count. Concurrent
  branches add members independently, so a figure written into prose is stale
  on merge - and it is stale in the direction that reads as authoritative. The
  phrasing the map uses throughout is *"read the list there rather than
  trusting a count written here."* The same applies to any set a tool already
  enumerates: derive it from the mapping, never by transcription.
- **When a design package is only PARTLY superseded, say which part.** A blanket
  "superseded" banner discards every decision in it that still stands, and
  nobody re-derives those; they are simply re-invented worse. Name the half
  that moved (a surface, a transport) and state that the rest is untouched.
- **When a package carries a post-freeze errata register, send the reader to
  the register FIRST**, before the body. Some errata change *meaning*, not
  wording, so a reader who takes the body first has already formed the wrong
  model by the time they reach the correction.
- **A pointer beats a paraphrase.** Where the authority is an array in a build
  script, a test, or a package's own section, name it and stop.

## 3. When the map contradicts the rest of the tree, it says so

Prose describing a mechanism that has been deleted or reversed **is read as
ground truth and never re-derived** - no typecheck, no test and no lint reaches
it. So the map does not quietly hold the better answer:

- A slice that knows it is contradicted elsewhere **says so explicitly and
  claims authority for that slice**, in the entry itself, where the reader
  already is.
- It names what is **GONE rather than renamed**. "Renamed" sends a reader
  looking for the new name of a thing that no longer exists, and they will find
  something with a similar name and use it.
- Where several comments still assert the retired rule, say that too, so the
  next reader who finds one recognises it instead of trusting it.

## 4. Every slice carries its reasoning, and both halves of a pair

A reader told *what* to avoid works around that one instance. A reader told
*why* recognises the next member of the class. So a slice states what the trap
costs when it fires, and in particular:

- **Both halves of a deliberate asymmetry live in the same slice.** Two
  subsystems that share a transport but take **opposite** failure dispositions;
  a spend control that fails open above a safety gate that fails closed; the
  same primitive that is correct on one path and destroys data on another. Whoever
  reads only one half generalises it into "how this layer behaves", and that
  generalisation is how the other half gets removed as an inconsistency. Say
  *why* they differ - usually a ruling about who is waiting, or what is
  recoverable - not merely that they do.
- **Say when the blast radius was ZERO.** "This cutover changed no stored byte,
  no access rule and no endpoint" is the one thing a later reader cannot
  re-derive, and without it a superseded package reads as wholly dead.
- **Where an ordering is enforced as a TYPE rather than a comment, say so.** A
  constraint a compiler holds cannot be reordered away; a constraint a comment
  holds already has been. Recording which one you have tells the next editor how
  much freedom they actually have.
- **Where a rule lives in exactly one place, name that place and say it is the
  only one.** That sentence is what stops a second implementation being added
  next to it.

## 5. The contracts no single component owns

These are the map's highest-value slices, because there is nowhere else they
can live:

- **The data-egress and purge contract.** For each third-party sink, state
  whether it is inside the contract, and what it holds. A sink that receives no
  account identifier is exempt *only while that remains true* - so record the
  precondition, and state that adding an identifier requires extending the purge
  contract **first**.
- **Precondition-first for capabilities that do not exist yet.** Where a slice
  is analytics-grade and spoofable, or a datum is decorative today, say what
  attaching real value to it would require *before* anyone attaches it. The
  story is cheap to write while nothing depends on it and impossible to
  retrofit after.
- **Record an accepted gap so it is not re-raised.** A known, ruled-on hole -
  "neither sink is purged, both gaps are accepted" - must be written down as
  *accepted*, with the reason, or every competent reader rediscovers it, argues
  it, and some of them fix it, undoing a decision they never saw.
- **A client half and a server half of the same contract belong in one slice.**
  Where a server-side purge leaves live client state behind, the omission is a
  shipped privacy bug rather than a cosmetic one, and the two halves are only
  visible together.

## 6. What the gates cannot see

A slice names the properties **no automated gate covers**, and says which
instrument would have to see them. Coverage that exists on one platform and not
another, a path a suite is structurally blind to because the subsystem is
disabled there, a behaviour that only a real device exercises: without the
note, a green suite is read as coverage and the untested half is "cleaned up"
by someone who checked that nothing went red.

## 7. Identifiers are retired, never reused

An identifier that several artifacts share - a screen or route number, an
event name - is **shared vocabulary** across the design files, the route table,
the source filenames, test configs and analytics tokens. A reused identifier
silently means two things at once, and nothing can detect it. So: retire it
permanently, keep the retirement note at the identifier's own home (the route
table, not only the map), and record the retirement in the map so the absence
reads as deliberate rather than as an omission.

Its counterpart: **a surface that MOVED rather than died keeps its vocabulary.**
An analytics field naming the surface that owns a control stays valid across the
move, and "tidying it up" silently breaks a continuous series. Where a token's
*anchor* moved while its name did not, say so: the counts step at the cutover
with no change in behaviour, and a dashboard reader will otherwise read the step
as growth.

## 8. Keeping the map current

- **A change that makes a slice wrong edits that slice in the same commit.**
  There is no gate that can catch a stale slice; the same-commit habit is the
  entire mechanism.
- **A component that moves takes its slice with it**, and the slice records
  where it moved from only when that history changes what a reader should do.
- **State what is true now.** The map is not a changelog: a superseded
  alternative left in the text keeps two options alive where there is one. The
  exception is a *measured* fact, which carries the date it was measured,
  because that is a re-check trigger rather than a story.
- **The map is prose, so it is the artifact class nothing else can see.** No
  test, spec, typecheck, lint or visual gate reads it. Whatever discipline it
  gets, it gets from the person editing the code beside it.
