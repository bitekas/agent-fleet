<!--
FEATURE CHECKLIST TEMPLATE. Copy this file to `checklist.dir/<feature-slug>.md`
when the feature's work starts, commit it on the feature branch, and fill
section 1 before any code. The definition of done's SKILL.md, "The feature
checklist", says who fills what and who runs the checker; `check_checklist.py`'s
header is the checker's contract. These comments may stay or go: the checker ignores
everything inside an HTML comment.

THE FORMAT, which the checker parses:
- Every section below is found by the number at the start of its heading
  (`## 2.`, `### 1b.`) and the Header by its name. Reword a title freely; keep
  the number, keep one table per section, and keep each table's columns, in
  order, as written here. A missing section, a renamed column or a row with the
  wrong number of cells is NO VERDICT (exit 2), never a pass. Section 4b holds
  two tables, the run and its findings; a checklist with no section 4b is a
  finding (exit 1), because what is missing is the hunt, not the format.
- Every cell of every row is owed. An empty cell is a finding.
- Status values are a closed list per section, written exactly. `TODO` is
  accepted anywhere and always blocks. A qualified status ("PASS (header
  only)") is not that status: what was not covered goes in a row of its own.
- Evidence is a path or a URL. A path is repo-relative (`e2e/x.spec.ts`, in
  backticks), absolute, or `~/`-relative, and must open on the machine the
  checker runs on; a Markdown link's relative target resolves from this file's
  directory, as Markdown renders it. A URL is taken as it stands. Evidence has
  to outlive the landing, because a release candidate re-checks this file
  after the feature has merged: a committed path, a path under your own
  `artifacts/` directory, or a link to the post that carries the result. A
  path under `/tmp` does not survive Rule 3's cleanup, so a verification tool
  that writes there by default is pointed under `artifacts/`.
- Gates are named by rule number only. The rule text lives in the definition
  of done and nowhere else.
- A project with no design file (`figma.file_key` null in the install's
  config) keeps sections 1a, 1b, 1c and 4 with their tables and may leave them
  empty; the checker accepts that and prints a NOTE saying so. Every row that
  is there is still checked. The presentation row in section 5 then carries
  the videos only.
-->

# Feature checklist - <feature name>

## Header

| Field | Value |
|---|---|
| Feature | <what a user would call it> |
| Slug | <feature-slug, the same as this file's name> |
| Builder | <the agent building it> |
| Requester | <who asked for it, and tests it> |
| Screens | <the screen numbers it touches, or none> |
| Started | <YYYY-MM-DD> |

## 1. Design - filled before any code

### 1a. The design read, before approval

<!--
An agent that did not draw the design reads every note against its frames and
the past rulings, and lists the contradictions plus everything the design
removes from today's app. The design's approvers (the design-file owner or
the designer, never the agent that drew the design) rule on that list - the
install's CONTEXT.md for the definition of done names the people in both
roles - and only then is the design frozen. Status: DONE or TODO.
-->

| Item | Status | Evidence |
|---|---|---|
| Contradictions and removals list | TODO | |
| Rulings on that list by the design's approvers | TODO | |

### 1b. Every frozen frame, mapped to the plan item that builds it

<!--
One row per frame the freeze copied in. Frame: the frame's NAME as a link to
the design file. Plan item: the item that builds it. Evidence: the plan.
Status: DONE or TODO. A frozen frame with no plan item is the gap this section
exists to show before code, rather than at the tester's pass.
-->

| Frame | Plan item | Status | Evidence |
|---|---|---|---|
| [<frame name>](<design-file link>) | | TODO | |

### 1c. Every screen the feature touches that has no frame

<!--
One row per touched screen or state with no design frame. Asked: who was
asked for a frame. Evidence: the question and its answer. Status: NO DESIGN.
Each one is flagged here before code, and listed again in section 4.
-->

| Screen | Asked | Status | Evidence |
|---|---|---|---|
| <screen and state> | | TODO | |

## 2. Scope

<!--
One row per agreed scope item. Evidence: the spec or flow that drives it, or a
clip of it working. Status: DONE or TODO.
-->

| Scope item | Status | Evidence |
|---|---|---|
| <scope item> | TODO | |

## 3. Rulings after approval

<!--
One row per ruling that arrives after the design was approved. Ruling: a link
to it. Frame and note: a link to the frame and the note it updated. Commit:
the commit that implements it. Status: RE-FROZEN once the updated set is
frozen again, before more code is written against it; TODO until then.
Evidence: the re-freeze. No rows when no ruling arrived after approval.
-->

| Date | Who | Ruling | Frame and note | Commit | Status | Evidence |
|---|---|---|---|---|---|---|

## 4. Pixel verdicts - every screen and state on the tester's step sheet

<!--
One row per screen and state on the step sheet, plus every screen the task
froze or moved. Frame: the frame's name as a link, or `none`. The check is run
by an agent that did not build the feature. Verdict, exactly one of:
  PASS              at the verification kit's bar; Evidence: the verdict.
  NO DESIGN         no frame exists; it is also a row in 1c.
  AHEAD             its frame on the current page is ahead because ANOTHER
                    task's freeze is in flight; Evidence: that freeze. Listed,
                    never absorbed into this feature and never edited down.
  WAIVED by <name>  a person on the waiver allow-list waived it; Evidence: the
                    waiver.
INCONCLUSIVE, FAIL and TODO block the hand-off. INCONCLUSIVE means the check
could not see the screen: fix the check, or have it waived by name.
-->

| Screen and state | Frame | Verdict | Evidence |
|---|---|---|---|
| <screen - state> | [<frame name>](<design-file link>) | TODO | |

## 4b. Bug hunt by an agent that did not build it

<!--
Before the tester sees the build, an agent that did not build the feature
hunts it for bugs. The hunter is a persona other than the builder. It may hand
the hunt to a fresh subagent, whose brief is ONLY the agreed scope (section 2)
and the build: no builder notes, no plan, not this checklist, because each of
those carries the builder's model of the feature, and that model is the one
that produced its bugs. It hunts on both platforms where the feature is
native, including the states after a tap - an open sheet or menu, the screen
you land on after save, skip or post - and the edge cases: empty, the longest
text, errors.

The run table holds exactly one row: who hunted, the build (a commit, equal to
or an ancestor of the hand-off commit in section 6), `section 2` as the scope
given, when (ISO 8601 UTC), and the evidence (clips, screenshots, notes).

The findings table holds one row per finding. Disposition, exactly one of:
  FIXED in <commit>     the commit is an ancestor of the hand-off commit
  WAIVED by <name>      a person on the waiver allow-list
  NOT A BUG: <reason>   the reason is owed
A hunt that found nothing has exactly ONE row: Finding `NONE`, Disposition
`-`, Evidence its notes. An empty table is a finding: a hunt that was never
run looks exactly like one that found nothing.
-->

| Hunter | Build (commit) | Scope given | Run at (UTC) | Evidence |
|---|---|---|---|---|
| <an agent that did not build it> | <commit> | section 2 | <YYYY-MM-DDTHH:MMZ> | |

| # | Finding | Disposition | Evidence |
|---|---|---|---|
| 1 | <what it found, or NONE> | TODO | |

## 5. Definition-of-done gates

<!--
One row per rule of the definition of done, by number; a rule may take more
than one row (`6 - visual sweep`). The checker reads the rule numbers from the
definition of done's rule table, so a rule appended there is a finding here
until it has a row. Status: DONE (Evidence: a path or URL), N/A (Evidence: the
reason), or AFTER HAND-OFF for what follows the tester's pass by construction
(Evidence: where it will be recorded).

The row `6 - presented to the requester` is read by its label, so keep it
written exactly so. It is DONE once the builder has shown the Header's
Requester, in the feature's chat thread, a video of the feature per platform
and the design pixel-comparison pack with its diff maps; Evidence: that
message's permalink, which must match the install's
`checklist.permalink_pattern`. N/A, with the reason, only when Screens is
`none`. Never AFTER HAND-OFF: it comes before the hand-off.
-->

| Rule | Status | Evidence |
|---|---|---|
| 1 | TODO | |
| 2 | TODO | |
| 3 | AFTER HAND-OFF | the merge report |
| 4 | TODO | |
| 5 | TODO | |
| 6 - visual sweep | TODO | |
| 6 - presented to the requester | TODO | |
| 6 - the tester's pass | AFTER HAND-OFF | the feature's thread |
| 7 | TODO | |

## 6. Hand-off

<!--
Filled from the line the checker prints on a PASS, run by an agent that did
not build the feature: who ran it, on which commit, when (ISO 8601 UTC).
-->

| Checker run by | Commit | At (UTC) |
|---|---|---|
| | | |
