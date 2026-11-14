<!--
TEST FIXTURE for check_checklist.test.py: a checklist that PASSES. Every
negative control in the test is one mutation of this file. The test copies it
into a throwaway git repository as docs/checklists/example-feature.md, creates
the repo-relative evidence it names, and replaces COMMIT_SHA with a real commit
(an ancestor of the hand-off commit) and ABS_EVIDENCE with an absolute path it
created. People: Ada builds, Tess tests, Hugo hunts, and Olive, Tess and Dana
are on the fixture install's waiver allow-list. Every link is an obviously fake
placeholder: chat links match the fixture install's permalink_pattern, design
links point at design.example.com.
-->

# Feature checklist - Example feature

## Header

| Field | Value |
|---|---|
| Feature | Sort the cart by price |
| Slug | example-feature |
| Builder | Ada |
| Requester | Tess |
| Screens | 12, 14 |
| Started | 2026-10-20 |

## 1. Design - filled before any code

### 1a. The design read, before approval

| Item | Status | Evidence |
|---|---|---|
| Contradictions and removals list | DONE | https://chat.example.com/feature-thread/m/1000000000000001 |
| Rulings on that list by the design's approvers | DONE | [the rulings](https://chat.example.com/feature-thread/m/1000000000000002) |

### 1b. Every frozen frame, mapped to the plan item that builds it

| Frame | Plan item | Status | Evidence |
|---|---|---|---|
| [12 - cart](https://design.example.com/file/example?node=12) | T1 | DONE | `docs/plan.md` |
| [14 - item](https://design.example.com/file/example?node=14) | T2 | DONE | [plan](../plan.md) |

### 1c. Every screen the feature touches that has no frame

| Screen | Asked | Status | Evidence |
|---|---|---|---|
| 12 - sort sheet, empty state | Dana | NO DESIGN | https://chat.example.com/feature-thread/m/1000000000000003 |

## 2. Scope

| Scope item | Status | Evidence |
|---|---|---|
| Sort the cart by price | DONE | `e2e/cart-sort.spec.ts:12` |
| The sort survives a relaunch | DONE | the clip in https://chat.example.com/feature-thread/m/1000000000000004 |

## 3. Rulings after approval

| Date | Who | Ruling | Frame and note | Commit | Status | Evidence |
|---|---|---|---|---|---|---|
| 2026-10-22 | Dana | [ruling](https://chat.example.com/feature-thread/m/1000000000000005) | [12 - cart](https://design.example.com/file/example?node=12) | `COMMIT_SHA` | RE-FROZEN | https://chat.example.com/feature-thread/m/1000000000000006 |

## 4. Pixel verdicts - every screen and state on the tester's step sheet

| Screen and state | Frame | Verdict | Evidence |
|---|---|---|---|
| 12 - cart, default | [12 - cart](https://design.example.com/file/example?node=12) | PASS | `ABS_EVIDENCE` |
| 12 - sort sheet, empty state | none | NO DESIGN | https://chat.example.com/feature-thread/m/1000000000000003 |
| 14 - item, header | [14 - item](https://design.example.com/file/example?node=14) | AHEAD | https://chat.example.com/feature-thread/m/1000000000000007 |
| 14 - item, photo | [14 - item](https://design.example.com/file/example?node=14) | WAIVED by Olive | https://chat.example.com/feature-thread/m/1000000000000008 |

## 4b. Bug hunt by an agent that did not build it

| Hunter | Build (commit) | Scope given | Run at (UTC) | Evidence |
|---|---|---|---|---|
| Hugo | `COMMIT_SHA` | section 2 | 2026-10-24T09:00Z | https://chat.example.com/feature-thread/m/1000000000000012 |

| # | Finding | Disposition | Evidence |
|---|---|---|---|
| 1 | The sort sheet clips its longest label | FIXED in COMMIT_SHA | https://chat.example.com/feature-thread/m/1000000000000013 |
| 2 | An empty cart shows no sort hint | NOT A BUG: the design draws no hint for the empty state (1c) | https://chat.example.com/feature-thread/m/1000000000000014 |
| 3 | The sort lags on a 400-item cart | WAIVED by Dana | https://chat.example.com/feature-thread/m/1000000000000015 |

## 5. Definition-of-done gates

| Rule | Status | Evidence |
|---|---|---|
| 1 | DONE | https://chat.example.com/feature-thread/m/1000000000000009 |
| 2 | DONE | `e2e/cart-sort.spec.ts` |
| 3 | AFTER HAND-OFF | the merge report |
| 4 | DONE | `e2e/cart-sort.spec.ts` |
| 5 | DONE | https://chat.example.com/feature-thread/m/1000000000000010 |
| 6 - visual sweep | DONE | https://chat.example.com/feature-thread/m/1000000000000011 |
| 6 - presented to the requester | DONE | https://chat.example.com/feature-thread/m/1000000000000016?thread=1000000000000011 |
| 6 - the tester's pass | AFTER HAND-OFF | the feature's thread |
| 7 | DONE | `docs/plan.md` |

## 6. Hand-off

| Checker run by | Commit | At (UTC) |
|---|---|---|
| | | |
