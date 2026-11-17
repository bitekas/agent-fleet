---
name: ui-design
version: 1
description: >
  How UI design work is run between people, a design file and a codebase, as
  short rules each with the reason that earns it: the three stages a design
  passes through (drafts, approved and ready to build, implemented and merged),
  the freeze between them, screen numbers and their registry, ids for machines
  and names as links for people, building exactly what is drawn, the design
  tool's successes that are not successes, checking a screen against its design,
  showing UI work, and working with the design's owners. Practice only - the
  install's design map and tool skills outrank it. Load before drawing, moving
  or deleting a frame, before issuing a screen number, before building or
  checking a screen against a design, and before showing UI work to a person.
requires_install: true
---

# ui-design

How design work is run: practice, not process. The install's design map is its
`CONTEXT.md` for this skill (`fleet where ui-design CONTEXT.md`): the design
file, each stage page and the scratch area by id, the literal marks, the number
registry, who holds each role, and the install's own design-tool skills, which
outrank this file. Code, evidence, landing and delegating in general are
`/software-development`; who may ask for design work is your charter's.

Three roles recur: the **design approver** rules on what the product looks
like, the **design-file owner** on the file itself (deletions, numbering), and
the **code-change authorizer** on building it.

## 1. The three stages

- **A design passes through three stages, each on its own page, with the stage
  number at the start of the page name: 1 drafts, 2 approved and ready to build,
  3 implemented and merged.** Each page is a statement about a different thing,
  and the number makes the page list read in the order work flows.
- **Drafts are work in progress: nothing is built from them, and they carry no
  screen number.** An agent draws only there, as new frames over the screen as
  it is now, and touches only its own. On the design approver's word a draft is
  moved, not redrawn, to the approved page.
- **The approved page belongs to the design owners and may change at any time.**
  That freedom is why nothing is built from it either.
- **The implemented page mirrors the landing branch and is the only page
  anything is built from.** New design is never authored there. A difference
  between it and the landing branch is a finding, not the model.
- **"The design was fixed" and "the app is wrong" are claims about a page: ask
  which.** A fix on the approved page reaches no build until it is frozen
  across, and an app that matches the implemented page is not a bug.

## 2. The freeze

- **The one movement from approved to implemented is the freeze, and it is the
  first act of the implementing agent, once every blocker is resolved.** Later,
  the design can change under the build; earlier, it freezes open questions.
  The blockers include the design read: someone who did not draw it has listed
  its contradictions and what it removes from the app, and the approver ruled.
- **Phase one: mark the frames the new design supersedes or drops, copy the new
  frames in wearing the in-build mark, report the mapping, and stop.** A mark a
  person must notice lives in the frame name and on the canvas, and is kept out
  of exports: the agent reads the interface, the person reads the board.
- **Sever the copy from its source, and record its new ids with the ids they
  replace.** A copied component instance stays bound to its master on the
  approved page, so edits there still move the "frozen" frame; and a copy mints
  new ids, so until then the repository points at the superseded frame.
- **Phase two has two gates: marked frames are deleted on the design-file
  owner's confirmation, and code is written on the code-change authorizer's.**
  Back the page up first, and pick what to delete by a property this task
  introduced: a mark alone matches every pending task's frames.
- **The in-build mark is a status, not part of the name, and it comes off when
  the work is verified on the landing branch.** Until then the page is ahead of
  the branch by exactly that task's frames. A ruling made meanwhile lands on
  its frame and note, and the set is frozen again before more code is written.
- **The reverse direction is bookkeeping.** Editing the implemented page to
  match what already shipped needs no design approval and no freeze: it is part
  of the task that shipped the code, and it is reported.

## 3. Screen numbers

- **One registry issues every screen number, before the number appears in the
  design file or in code.** A frame carrying an unissued number is repaired by
  back-filling the registry, never by renaming the frame.
- **A number is used once.** A deletion, a rename and a deprecation each spend
  it for good, and its row stays, marked retired with its old purpose. A reused
  number is two screens under one name, and nothing detects it.
- **Only screens get numbers; a state or variant takes a suffix.** A suffix
  spends nothing and is reversible. A reserved, unbuilt screen keeps its number.
- **Numbers agree across the code, the registry and the design file, and when
  they disagree the order is: code, registry, implemented page, approved page.**
  A lower rank is the drift: never change the code side to match the design.
- **Numbers for an approved design need no further approval: take the next
  unused ones. Realigning a disagreement is the design-file owner's.** First
  check both sources describe the same screen: a stale citation is no conflict.

## 4. Identifying things

- **Resolve a page, section or frame by id, never by name.** Names move between
  nodes, and a lookup by name returns the wrong board with no error. Read the
  id-to-name map afresh at the start of each engagement.
- **To a person, write the name as a link, never an id.** An id appears nowhere
  in the design tool's interface, so a person cannot find it; the link is what
  puts them in front of the node. When a name is ambiguous, add context words.
- **A screen number is not a frame.** One number can name several frames (full
  page, viewport, empty state): list every candidate, skip superseded ones, and
  when two live ones remain, ask. A wrong reference passes every later check.
- **A recorded id can be wrong: resolve it again by name and geometry.** Before
  reporting a frame deleted, resolve its id: a living id was only renamed.

## 5. Reading a design and building it

- **The frame is the specification, and drawing it is the approval.** Build what
  is drawn; a difference between app and frame is a defect, not a question.
- **Follow the drawn design, never an improved alternative.** Add only what
  makes it buildable. Where a note and a drawing disagree, the note and the
  latest drawing stand.
- **Close the design input before building on it.** Contradicting frames, a
  missing state, an effect that cannot be reproduced: ask before that element is
  built, and silence is not permission. Measure first: most contradictions are
  measurements nobody took, and most "missing" controls are hidden layers.
- **Every new control gets real behaviour, and every removed one an answer for
  what it used to do.** Never ship a dead control.
- **Every value and asset comes from the design source.** Never invent, redraw
  or placeholder an icon: export it, or ask for a selection link. Reuse an asset
  only after comparing geometry and fills: the same name is not the same asset.
  A person confirms an asset is complete before it is exported, because an
  unfinished one looks exactly like a finished one.
- **One divergence is sanctioned: the design contradicts its own system.**
  Report it at once, build the error as drawn and pass the checks on it, then
  fix it and ship the fix with a marker, in the code and beside the check,
  stating the expected difference. "I would have done it differently" is not an
  error, and a shared component drawn differently on two screens goes to the
  approver, never into a per-screen override.
- **Unrequested drift resolves toward the design; a requested code change wins,
  and the design is updated.** When a new design reverses shipped behaviour that
  was itself requested, that is the code-change authorizer's decision.

## 6. Working in the design tool

- **Delegate design-tool jobs, each with a call budget.** One page read can fill
  a context window, and the tool's seat is shared and capped. Batch the edits.
- **Read-only by default; write or delete only on an explicit instruction.** The
  instruction is the authorization: carry it out, then report every node
  touched, as name links. Destructive operations are never inferred.
- **Tooling writes go to the scratch area only, and you sweep for strays
  afterwards:** a copy or an upload can land on the page built from.
- **A call that returned cleanly proves nothing.** Read the node back (the write
  landed) and render the frame (it landed where you meant), in the same script.
- **Every enumeration is a floor.** A listing can come back short with no
  marker: walk the children and count twice before reporting a node absent.
- **An export can succeed and be wrong.** Check its pixel size against the scale
  asked for, that it is not empty, that transparency survived, and that no
  neighbouring layer was composited in.

## 7. Checking and showing

- **Compare on two axes: placement at the design width, and scaling away from
  it.** At the design width a fixed literal and a scaled value are the same
  number, so a check at one viewport cannot see a scaling mistake.
- **Name the properties a check covers and those it does not, and suppress
  nothing.** A wrong value in an unmeasured property gives the same clean result
  (`/software-development` section 4). An expected difference gets a label; an
  element on one side only, or one that cannot be measured, is a finding.
- **Never edit the reference to close a red, and never read green tests as
  parity.** The extracted values and images are what "correct" means; tests read
  behaviour, not pixels; and an unclear or missing frame is a stop.
- **UI work is shown, not described: screenshots in the message that says
  done, at a fixed, named set of viewports, each captioned.** A closed set lets
  packs taken months apart be compared. Confirm the change is in the shot:
  settled, loaded, not cut off.
- **Before a tester sees a build, someone who did not build it sweeps every
  changed screen:** both platforms, the smallest and largest viewport, the base
  language, the longest text, the longest unbreakable word, a non-Latin script.
  The tester's look should have nothing to report.

## 8. Working with people

- **Scope decides the approver, not who proposed it.** A new screen, theme,
  brand or regrouping goes to the design approver; a design changed to match
  shipped code needs nobody. Default to doing it.
- **A design question is options, each with what it changes for users, its
  cost, its risk and what undoing it costs, every fact checked, and no pick**
  (`/talking-to-humans`). The person decides on what you tell them.
- **A deletion ask carries a rendered preview of every frame on it,** and of
  its replacement, beside the name link. The owner decides from the picture.
- **Feedback runs in rounds.** Wait for the reviewer's "done", duplicate the
  last pass and edit the copy so passes can be compared, apply every comment in
  scope, and answer every question comment in one message.
- **Answer a critique item by item, the current version beside the proposal,
  and report one finding per message: screen, element, render, proposed fix.**
  When an item reads as already done, suspect the wrong copy first.

## Install

**Asks for:** the design file (its key or link); the three stage pages by id
(1 drafts, 2 approved and ready to build, 3 implemented and merged) and the
scratch area by id; the two literal marks, the in-build mark and the mark for a
frame a new design supersedes or drops; where the screen-number registry
lives, in one of three forms: a document in the install repository (its
repository-relative path), a page or frame in the design file (its id), or
another system (its link); who holds the design approver, design-file owner
and code-change authorizer roles; and, optionally, the install's own
design-tool skills.

**Writes:** `CONTEXT.md` in the install context
(`fleet where ui-design CONTEXT.md`): the design map, as the table
`installation/INSTRUCTION.md` gives.

**Steps:** `installation/INSTRUCTION.md`; no step is per agent.
`installation/check` reports not configured until every value is there.
Where the install also takes definition-of-done, five of the values are copied
from its `config.json`, never asked twice, and changed together; the check
compares them.
