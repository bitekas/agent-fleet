<!--
TEST FIXTURE for check_checklist.test.py: a hand-off whose pixel check covered
only the frames the task froze, written as the checklist it would have been.
So:
  - the summary slide was frozen and left out of the plan (1b);
  - the item screen's three-dot menu, the share sheet and that slide were on
    the tester's step sheet with no verdict at all (4);
  - the home header was checked for its banner only (4);
  - the own-listing manage sheet came back INCONCLUSIVE, user photos swamping
    the diff, and was accepted as non-blocking (4). Its white panel was
    missing: a geometry audit passes that, because it measures boxes, not
    fills.
And no agent that had not built it hunted it for bugs before the tester saw
it, so both of 4b's tables are empty. Section 5 carries no `6 - presented to
the requester` row, so no presentation of the videos and the diff maps to the
requester is recorded (5).
Every other section is filled and passes, so the checker's output is exactly
the pixel-check findings, the missing hunt and the missing presentation. The
test asserts that output. People are the test's: Ada builds, Tess tests.
Every link is an obviously fake placeholder.
-->

# Feature checklist - Listing management

## Header

| Field | Value |
|---|---|
| Feature | Listing management |
| Slug | handoff-replay |
| Builder | Ada |
| Requester | Tess |
| Screens | home, item, summary |
| Started | 2026-10-20 |

## 1. Design - filled before any code

### 1a. The design read, before approval

| Item | Status | Evidence |
|---|---|---|
| Contradictions and removals list | DONE | https://chat.example.com/feature-thread/m/2000000000000001 |
| Rulings on that list by the design's approvers | DONE | https://chat.example.com/feature-thread/m/2000000000000002 |

### 1b. Every frozen frame, mapped to the plan item that builds it

| Frame | Plan item | Status | Evidence |
|---|---|---|---|
| [Home - banner](https://design.example.com/file/example?node=21) | T1 | DONE | https://chat.example.com/feature-thread/m/2000000000000003 |
| [Item - own listing, manage sheet](https://design.example.com/file/example?node=22) | T4 | DONE | https://chat.example.com/feature-thread/m/2000000000000003 |
| [Summary slide](https://design.example.com/file/example?node=23) |  | DONE | https://chat.example.com/feature-thread/m/2000000000000003 |

### 1c. Every screen the feature touches that has no frame

| Screen | Asked | Status | Evidence |
|---|---|---|---|

## 2. Scope

| Scope item | Status | Evidence |
|---|---|---|
| Banner on the home screen | DONE | https://chat.example.com/feature-thread/m/2000000000000004 |
| Manage your own listing | DONE | https://chat.example.com/feature-thread/m/2000000000000005 |

## 3. Rulings after approval

| Date | Who | Ruling | Frame and note | Commit | Status | Evidence |
|---|---|---|---|---|---|---|

## 4. Pixel verdicts - every screen and state on the tester's step sheet

| Screen and state | Frame | Verdict | Evidence |
|---|---|---|---|
| Home - banner | [Home - banner](https://design.example.com/file/example?node=21) | PASS | https://chat.example.com/feature-thread/m/2000000000000006 |
| Home - header | [Home - header](https://design.example.com/file/example?node=24) | PASS (banner only) | https://chat.example.com/feature-thread/m/2000000000000006 |
| Item - own listing, manage sheet | [Item - own listing, manage sheet](https://design.example.com/file/example?node=22) | INCONCLUSIVE (user photos swamp the diff; accepted as non-blocking) | https://chat.example.com/feature-thread/m/2000000000000007 |
| Item - three-dot menu | [Item - three-dot menu](https://design.example.com/file/example?node=25) |  |  |
| Item - share sheet | [Item - share sheet](https://design.example.com/file/example?node=26) |  |  |
| Summary slide | [Summary slide](https://design.example.com/file/example?node=23) |  |  |

## 4b. Bug hunt by an agent that did not build it

| Hunter | Build (commit) | Scope given | Run at (UTC) | Evidence |
|---|---|---|---|---|

| # | Finding | Disposition | Evidence |
|---|---|---|---|

## 5. Definition-of-done gates

| Rule | Status | Evidence |
|---|---|---|
| 1 | DONE | https://chat.example.com/feature-thread/m/2000000000000008 |
| 2 | DONE | https://chat.example.com/feature-thread/m/2000000000000009 |
| 3 | AFTER HAND-OFF | the merge report |
| 4 | DONE | https://chat.example.com/feature-thread/m/2000000000000010 |
| 5 | DONE | https://chat.example.com/feature-thread/m/2000000000000011 |
| 6 - visual sweep | DONE | https://chat.example.com/feature-thread/m/2000000000000012 |
| 6 - the tester's pass | AFTER HAND-OFF | the feature's thread |
| 7 | DONE | https://chat.example.com/feature-thread/m/2000000000000013 |

## 6. Hand-off

| Checker run by | Commit | At (UTC) |
|---|---|---|
| | | |
