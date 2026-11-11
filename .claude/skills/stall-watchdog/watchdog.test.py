#!/usr/bin/env python3
"""Offline regression guard for the stall watchdog.

Pure and offline - no tmux, no session, no keystrokes sent. Drives `decide()`,
`looks_like_prompt()` and `pane_digest()` directly, which is the whole reason the
decision logic takes `now` as an argument instead of reading the clock.

The cases that matter are the ones where a wrong answer sends Escape into real
work. Those are marked TEETH.

Run: python3 <skill dir>/watchdog.test.py   (nonzero on failure)

Hermetic: it forces the example config before importing watchdog.py, so it needs no
install, no config of its own and no tmux server, and gives the same verdict on
every machine.
"""
import importlib.util
import json as _json
import math as _math
import os
import re as _re
import sys

# ⚠️ The check NAMES carry the chooser glyph and the status-bar arrows, because the
# patterns they are about do. On a console Python has resolved to ascii - any launcher
# with LC_ALL=C and locale coercion disabled - printing a verdict then raises
# UnicodeEncodeError and the run dies with no summary, which is the "never actually
# ran" state wearing a failure's clothes. Force the stream rather than sanitise the
# names: normalising the glyphs out would take the patterns with them.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    except (AttributeError, OSError, ValueError):
        pass

_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchdog.py")
_EXAMPLE_CONFIG = os.path.join(os.path.dirname(_SCRIPT), "config.example.json")

# Resolve the module against the EXAMPLE config, unconditionally, and drop the env
# override before the import. watchdog.py reads its config at IMPORT time, so an
# ambient STALL_WATCHDOG_CONFIG would point this suite at whichever live install
# happened to run it - the suite would then pass or fail depending on whose session
# invoked it, and section 5 below would be asserting the absence of an approve key in
# a file nobody reviewed. Forcing it here is what keeps the guard offline, hermetic
# and identical on every machine, and it is why no config.json ships beside
# watchdog.py: there is no per-install file for the tests to depend on.
#
# ⚠️ The example config is therefore UNDER TEST, not merely present. Section 5's
# checks - no approve key, the {duration} placeholder, poll_secs against stall_secs -
# read whatever this variable names. A real deployment's config gets those same
# checks by exporting STALL_WATCHDOG_CONFIG and re-running... which this line
# deliberately prevents, because a suite whose verdict depends on the machine it
# ran on is not a regression guard. To audit a live config, run
# `python3 watchdog.py doctor` against it instead.
os.environ.pop("STALL_WATCHDOG_CONFIG", None)
os.environ["STALL_WATCHDOG_CONFIG"] = _EXAMPLE_CONFIG

_spec = importlib.util.spec_from_file_location("stall_watchdog", _SCRIPT)
w = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(w)

_failures = []

# The SAME file the module loaded, never a hardcoded config.json: the two must not be
# able to diverge, or the checks that read this would vouch for a file the module never
# read. Hoisted here because section 2c needs the DEPLOYED cadence and section 5 needs
# the raw text; one read, one source.
with open(w.CONFIG_FILE, encoding="utf-8") as _fh:
    _CFG_RAW = _json.load(_fh)


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))
    if not cond:
        _failures.append(name)


HOUR = 3600.0

IDLE_PANE = """\
  ⎿  Tip: Use /btw to ask a quick side question without interrupting Claude's work
─────────────────────────────────────────────────────────── <agent>-slack ──
❯
────────────────────────────────────────────────────────────────────────────────
  ⏵⏵ bypass permissions on · 3 monitors · esc to interrupt · ← for agents
"""

WORKING_PANE = """\
● Reading the deals folder…
  ⎿  Found 32 directories
✻ Thinking… (14s · 2.1k tokens · esc to interrupt)
"""

PROMPT_PANE = """\
● Bash(rm -f /tmp/skillscan/*.txt)
  Deleting files in /tmp by wildcard is too dangerous, do you want to continue?

❯ 1. Yes
  2. No, and tell Claude what to do differently (esc)
"""

# ---------------------------------------------------------------------------
# 1. Prompt signature
# ---------------------------------------------------------------------------
check("a real confirmation prompt is recognised", w.looks_like_prompt(PROMPT_PANE))

# TEETH - the two panes below are the ones that must NEVER match. A false positive
# here fires Escape into a live session.
check("TEETH: an idle session is NOT a prompt", not w.looks_like_prompt(IDLE_PANE))
check("TEETH: a working session is NOT a prompt", not w.looks_like_prompt(WORKING_PANE))
check("TEETH: prose mentioning 'yes' or 'no' is not a prompt",
      not w.looks_like_prompt("I asked whether to proceed and the answer was no.\n"
                              "1. Some numbered list item about something else\n"))

# ---------------------------------------------------------------------------
# 2. Digest ignores the volatile footer
# ---------------------------------------------------------------------------
# TEETH - the footer carries a live token count and spinner. If those reach the
# hash, the digest changes every poll, `since` resets every poll, the stall timer
# never expires and the watchdog silently never fires. That failure looks exactly
# like a watchdog that is working.
a = WORKING_PANE.replace("14s · 2.1k tokens", "15s · 2.3k tokens")
check("TEETH: spinner/token churn does not change the digest",
      w.pane_digest(WORKING_PANE) == w.pane_digest(a),
      f"{w.pane_digest(WORKING_PANE)} vs {w.pane_digest(a)}")
check("real content change DOES change the digest",
      w.pane_digest(PROMPT_PANE) != w.pane_digest(IDLE_PANE))

# ---------------------------------------------------------------------------
# 1b. The idle-footer exclusion - the agent must not detect ITSELF
# ---------------------------------------------------------------------------
# ⚠️ The pane being read also displays the agent's own commands and output. This
# repo's own config and tests contain chooser text, so without a structural
# exclusion the watchdog matches an idle session that merely PRINTED a dialog -
# measured. The discriminator: a modal dialog replaces the input
# box and status bar; idle or working, those are always present.
IDLE_FOOT = ("\n────────\n❯ \n────────\n"
             "  ⏵⏵ bypass permissions on · 3 monitors · esc to interrupt · ← for agents · ↓ to manage")

check("option names other than Yes/No are still detected (Compact)",
      w.looks_like_prompt("Conversation is long.\n\n❯ 1. Compact now\n  2. Keep going\n"
                          "\n Esc to cancel · Tab to amend"))
check("option names other than Yes/No are still detected (Login)",
      w.looks_like_prompt("Session expired.\n\n❯ 1. Login\n  2. Cancel\n"
                          "\n Esc to cancel · Tab to amend"))
check("the cursor is found on any option, not just the first",
      w.looks_like_prompt("Pick\n\n  1. A\n❯ 2. B\n  3. C\n\n Esc to cancel · Tab to amend"))

check("TEETH: an idle agent that PRINTED a dialog is not a prompt",
      not w.looks_like_prompt("I found this prompt:\n❯ 1. Yes\n  2. No\n" + IDLE_FOOT))
check("TEETH: an idle agent grepping its own patterns is not a prompt",
      not w.looks_like_prompt("prompt_patterns: ^\\s*❯\\s*\\d+\\.\n" + IDLE_FOOT))
check("TEETH: a working session showing the status bar is not a prompt",
      not w.looks_like_prompt("● Running 1 shell command…\n" + IDLE_FOOT))
# The bare '❯' is the session's own input prompt - requiring a digit and a dot is
# the only thing separating a chooser from the resting state.
check("TEETH: the bare input prompt is not a chooser", not w.looks_like_prompt("❯ \n"))

# ---------------------------------------------------------------------------
# 1c. Is the exclusion ARMED, or merely not needed?
# ---------------------------------------------------------------------------
# ⚠️ "not a prompt" HAS TWO CAUSES AND ONLY ONE IS PROTECTION. looks_like_prompt()
# is False when the structural exclusion fires AND when no prompt pattern happened
# to match - and the second state is unprotected: a chooser the agent PRINTS would
# be read as a real one. A boolean cannot tell those apart, which is why
# idle_exclusion_hits() reports the exclusion separately and why --probe prints it.
#
# An agent-list panel rendered below the status bar puts the idle footer SEVEN
# lines from the bottom, one outside a six-line window. Such a session reads as
# "prompt match False" while the exclusion is inert.
_PANEL = "\n  ● main\n" + "".join(
    f"  ◯ worker{i}  doing something   {i}m\n" for i in range(7))

check("the exclusion is ARMED on a plain idle pane",
      w.idle_exclusion_hits("x" + IDLE_FOOT) != [])
check("TEETH: a panel rendered BELOW the footer pushes the exclusion out of the window",
      w.idle_exclusion_hits("x" + IDLE_FOOT + _PANEL, 6) == [],
      "if this passes trivially the regression it models cannot be detected")
check("TEETH: and widening the window re-arms it",
      w.idle_exclusion_hits("x" + IDLE_FOOT + _PANEL, 24) != [])
# A real dialog must NOT be excluded at any window width, or widening it would buy
# safety by making the watchdog blind - the failure that looks like working.
def _fixture(name):
    """Read a captured pane, recording its ABSENCE as a named failure.

    ⚠️ A missing fixture must red a check that SAYS a fixture is missing. Reading
    one inline raises FileNotFoundError from whichever check happens to touch it
    first, which points the reader at an unrelated section - measured while adding
    section 2c: deleting the permission captures produced a traceback from the
    width check below, about fixtures that section does not own. A traceback is at
    least loud; the failure mode it models is the quiet one, where a harness that
    can only say pass/fail reports "the suite errored" and nobody learns which
    evidence went missing. Deleting this helper reinstates that.

    ⚠️ MEMOISED, and that is not an optimisation. Without it one missing file emits
    an identical failure once per read - five times over for a fixture the width
    sweep below touches at four widths - and pushes five copies of one name into
    the failure list, so `FAILED: 14 check(s)` describes three real problems. A
    count that overstates is the same class of lie as one that understates.
    """
    if name in _FIXTURE_CACHE:
        return _FIXTURE_CACHE[name]
    path = os.path.join(os.path.dirname(_SCRIPT), "fixtures", name)
    try:
        text = open(path, encoding="utf-8").read()
    except FileNotFoundError:
        check(f"fixture {name} is present", False,
              "regenerate from a real tmux capture-pane during a live prompt, never by hand")
        text = ""
    _FIXTURE_CACHE[name] = text
    return text


_FIXTURE_CACHE = {}

_ALL_PROMPT_FIXTURES = ("real-prompt-a.txt", "real-prompt-b.txt", "resume-prompt.txt",
                        "real-prompt-permission-a.txt", "real-prompt-permission-b.txt")

# ⚠️ THIS CHECK IS THE WIDTH SWEEP'S GUARD AND MUST STAY ABOVE IT. The sweep below
# asserts an ABSENCE - no idle signature at any window width - and an absence is
# satisfied for free by an empty string, so a deleted or emptied fixture makes it
# pass twenty times over while measuring nothing. Only a check that asserts the
# fixtures are PRESENT and still read as prompts can tell "swept and found clean"
# from "there was nothing to sweep". Same shape as the two guard pairs in section
# 2c: an absence assertion is never left to stand on its own here.
check("every prompt fixture is present and still reads as a prompt",
      all(w.looks_like_prompt(_fixture(f)) for f in _ALL_PROMPT_FIXTURES),
      f"not recognised: {[f for f in _ALL_PROMPT_FIXTURES if not w.looks_like_prompt(_fixture(f))]}")

check("TEETH: a real captured prompt has no idle signature at ANY window width",
      all(w.idle_exclusion_hits(_fixture(f), n) == []
          for f in _ALL_PROMPT_FIXTURES
          for n in (6, 12, 24, 10**6)))


def _glyph_only_difference(a: str, b: str) -> bool:
    """True when two captures differ ONLY by an animating glyph appearing/vanishing.

    ⚠️ THIS IS WHAT "THE FIXTURES BLINK" ACTUALLY MEANS, AND CHECKING `a != b`
    INSTEAD DOES NOT MEAN IT. Measured: regenerate one of a pair with three
    trailing spaces added to any line and the suite stays fully green - the files
    differ, the digests still match because pane_digest collapses whitespace, and
    the section-6 mechanism the pair exists to reproduce is gone with nothing
    saying so. Substituting the glyph class WITHOUT collapsing whitespace is the
    discriminator: it leaves a whitespace-only edit visible while making a genuine
    blink invisible.

    Delete this and both blinking pairs decay into "two files that happen to
    differ", which is the exact state technical/watchdog.md section 6 says a
    fixture must never be in.
    """
    sub = w._ANIM_GLYPHS.sub
    return a != b and sub(" ", a) == sub(" ", b)

# ---------------------------------------------------------------------------
# 2b. REAL CAPTURES - the synthetic fixtures above were not enough
# ---------------------------------------------------------------------------
# ⚠️ These two files are consecutive `tmux capture-pane` samples taken 10s apart
# while a genuine confirmation prompt was on screen. They exist because the
# synthetic fixtures PASSED while the watchdog was broken: the real pane shows
# "● Running 1 shell command…" and the leading ● blinks, so the same line
# alternates between "● Running…" and "  Running…". That alternation reset the
# stall timer on every poll and the watchdog could never have fired - with green
# tests and a healthy systemd status the whole time.
#
# Never replace these with hand-written panes. A fixture that does not blink
# cannot catch a bug whose entire mechanism is blinking.
_here = os.path.dirname(os.path.abspath(__file__))
REAL_A = _fixture("real-prompt-a.txt")
REAL_B = _fixture("real-prompt-b.txt")

check("real captured prompt is recognised", w.looks_like_prompt(REAL_A))
check("TEETH: two real samples 10s apart hash IDENTICALLY",
      w.pane_digest(REAL_A) == w.pane_digest(REAL_B),
      f"{w.pane_digest(REAL_A)} vs {w.pane_digest(REAL_B)}")
# ⚠️ GUARD FOR THE CHECK ABOVE, and it was missing for as long as that check
# existed: two copies of ONE file hash identically, so `cp real-prompt-a.txt
# real-prompt-b.txt` left the whole suite green with the blink deleted - measured.
# The digest check only means something while the pair genuinely blinks.
check("TEETH: the two rm-guard samples differ ONLY by an animating glyph",
      _glyph_only_difference(REAL_A, REAL_B),
      "identical files, or a difference that is not a blink, make the digest check above vacuous")
# The exact wording of the guard that started all this.
check("the real guard's wording is captured in the fixture",
      "possibly-empty variable path" in REAL_A)
# Walk the state machine on the real pair, alternating them the way the
# blink alternates. This is the end-to-end proof the timer accumulates.
st, act = {}, "wait"
for i in range(12):
    pane = REAL_A if i % 2 == 0 else REAL_B
    act, st = w.decide(st, w.pane_digest(pane), w.looks_like_prompt(pane), i * 20.0, 120.0)
    if act == "deny":
        break
check("TEETH: alternating real samples still reach a deny", act == "deny",
      f"gave up after 12 polls with action={act}")


# ---------------------------------------------------------------------------
# 2c. REAL CAPTURE - an ordinary Bash PERMISSION prompt
# ---------------------------------------------------------------------------
# ⚠️ WHY A SECOND PAIR OF REAL CAPTURES, WHEN 2b ALREADY HAS ONE. The 2b pair is
# the `rm` guard (technical/watchdog.md section 5), a dialog the watchdog meets but
# was not built for. These two are the class it IS built for: an ordinary Bash
# permission confirmation, raised deliberately and reproducibly (section 7 there),
# on a throwaway session started WITHOUT --dangerously-skip-permissions.
#
# They are consecutive `tmux capture-pane` samples 10s apart during an end-to-end
# fire (measured 2026-09-04, Claude Code 2.1.260). They differ in
# exactly one line - the leading ● of "● Creating empty probe file" blinks - which
# is the section-6 mechanism reproduced independently of the 2b pair. DO NOT
# "tidy" that difference away: a fixture pair that does not blink cannot catch a
# bug whose entire mechanism is blinking, and the digest checks below would then
# pass without measuring anything.
#
# ⚠️ Delete these and the suite keeps a green permission-prompt story with nothing
# behind it: the remaining fixtures are all the unreproducible rm guard.
_PERM_A = _fixture("real-prompt-permission-a.txt")
_PERM_B = _fixture("real-prompt-permission-b.txt")

check("both permission samples are recognised as prompts",
      w.looks_like_prompt(_PERM_A) and w.looks_like_prompt(_PERM_B),
      f"a={w.looks_like_prompt(_PERM_A)} b={w.looks_like_prompt(_PERM_B)}")

# Each pattern individually, not just the OR of them: a pattern that silently
# stopped matching this dialog class would otherwise hide behind the other two.
#
# ⚠️ THIS IS DELIBERATELY *TWO* CHECKS, AND THE SECOND ONE IS WHY. A loop that
# generates one check per CONFIGURED pattern cannot see a pattern that was
# DELETED: removing it removes its check too, and the suite stays green having
# quietly stopped measuring that pattern. Measured: a control that deletes the
# selection-cursor pattern reds two unrelated checks and none of the per-pattern
# ones. So the configured set is checked for coverage, and the three
# structural elements are ALSO asserted against the fixture with regexes written
# HERE, which no config edit can delete. Collapse these two into one and the
# deleted-pattern hole reopens.
check("every configured prompt pattern hits the permission capture",
      all(_p.search(_PERM_A) for _p in w.PROMPT_PATTERNS),
      f"misses: {[_p.pattern for _p in w.PROMPT_PATTERNS if not _p.search(_PERM_A)]}")

_STRUCTURAL = {
    "selection cursor (glyph, digit, dot)": r"^\s*❯\s*\d+\.",
    "the confirmation question": r"Do you want to (proceed|continue)",
    "the dialog footer": r"Esc to cancel · Tab to amend",
}
for _what, _rx in _STRUCTURAL.items():
    check(f"the permission capture carries {_what}", bool(_re.search(_rx, _PERM_A, _re.M)),
          "the config is free to change; the CAPTURE showing this element is the fact "
          "the patterns are calibrated against")
def _covered(structural_rx: str) -> bool:
    """Does some CONFIGURED pattern match the element this structural regex names?

    ⚠️ COVERAGE, NOT STRING EQUALITY, AND THE DIFFERENCE IS THE WHOLE POINT.
    Comparing `_p.pattern == structural_rx` reds on any edit to a pattern, including
    a strictly WIDER one that still covers the element - so it would fire on the
    very change technical/watchdog.md section 12 records as a decision still to make
    (widening the cursor pattern to reach unnumbered choosers), and its failure text
    would name neither that change nor this dictionary. A tripwire on your own next
    step, with no defusing
    instruction, is worse than no tripwire. Matching against the element's own text
    keeps the check about coverage, which is what its name claims.
    """
    m = _re.search(structural_rx, _PERM_A, _re.M)
    return bool(m) and any(_p.search(m.group(0)) for _p in w.PROMPT_PATTERNS)


check("the configured patterns still cover every structural element",
      all(_covered(_rx) for _rx in _STRUCTURAL.values()),
      f"uncovered = {[k for k, v in _STRUCTURAL.items() if not _covered(v)]}; "
      f"configured = {[_p.pattern for _p in w.PROMPT_PATTERNS]}")

check("TEETH: the permission prompt's blink does not change the digest",
      w.pane_digest(_PERM_A) == w.pane_digest(_PERM_B),
      f"{w.pane_digest(_PERM_A)} vs {w.pane_digest(_PERM_B)}")

# ⚠️ GUARD FOR THE CHECK ABOVE, and byte-inequality is NOT strong enough to be it.
# The property that matters is that the pair BLINKS; two files that merely differ
# satisfy `!=` while carrying no blink at all, and pane_digest then matches them
# for the wrong reason. Measured: adding trailing whitespace to one line of B keeps
# `!=` true, keeps the digests equal, and leaves the suite fully green with the
# section-6 mechanism deleted.
check("TEETH: the two permission samples differ ONLY by an animating glyph",
      _glyph_only_difference(_PERM_A, _PERM_B),
      "identical fixtures, or a difference that is not a blink, make the digest "
      "check above vacuous")

# ⚠️ THIS DIALOG OFFERS THREE WAYS TO SAY YES, one of which switches the whole
# session to auto mode permanently. The watchdog answers it by sending Escape,
# never by index, and it must never acquire a taught handler: a `known_prompts`
# entry matching this pane would be an approve path for a permission prompt, which
# section 2 of technical/watchdog.md forbids outright. The fixture is the guard -
# it carries that "Yes, and switch to auto mode" line verbatim, so an entry written
# to match it reds this check.
check("the capture really does offer an approve-and-widen option",
      "switch to auto mode" in _PERM_A,
      "without this line the check below cannot detect the entry it exists to forbid")
check("TEETH: a permission prompt matches NO taught handler - it is still refused",
      w.match_known_prompt(_PERM_A) is None and w.match_known_prompt(_PERM_B) is None,
      "a taught answer for a permission prompt is an approve path; there must never be one")

# The state machine over the real blink, at the cadence THIS CONFIG declares - not
# the 20s walk of section 2b, and ⚠️ not a literal. Writing 30 and 120 here made the
# check pass unchanged at poll_secs 60 / stall_secs 600 while its own name still
# said "after 120s" - measured. A cadence check that cannot see the cadence change
# is the check reporting on itself. Section 5's four-samples ratio does not catch it
# either: 600/60 is 10.
_POLL = float(_CFG_RAW["stall"]["poll_secs"])
_STALL = float(_CFG_RAW["stall"]["stall_secs"])
_EXPECTED_POLL = _math.ceil(_STALL / _POLL)

_st, _act, _fired_on = {}, "wait", None
for _i in range(2 * _EXPECTED_POLL + 4):
    _pane = _PERM_A if _i % 2 == 0 else _PERM_B
    _act, _st = w.decide(_st, w.pane_digest(_pane), w.looks_like_prompt(_pane),
                         _i * _POLL, _STALL)
    if _act == "deny":
        _fired_on = _i
        break
check(f"TEETH: alternating permission samples reach a deny at {_POLL:.0f}s polling",
      _act == "deny", f"gave up with action={_act}")
check(f"the deny lands at t={_STALL:.0f}s - the first poll not short of stall_secs",
      _fired_on == _EXPECTED_POLL,
      f"fired at t={None if _fired_on is None else _fired_on * _POLL:.0f}s "
      f"(poll index {_fired_on}), expected index {_EXPECTED_POLL} "
      f"from stall {_STALL:.0f}s / poll {_POLL:.0f}s")

# ---------------------------------------------------------------------------
# 2d. KNOWN GAP - a start-up dialog the patterns do NOT reach
# ---------------------------------------------------------------------------
# ⚠️ THIS SECTION PINS A GAP, NOT A DESIRED BEHAVIOUR, AND THAT DISTINCTION IS THE
# ONLY REASON IT IS SAFE TO HAVE HERE. `fixtures/real-prompt-trust.txt` is a real
# capture of Claude Code's trust-this-folder dialog: a genuinely blocking, modal,
# unattended-fatal prompt that NONE of the three prompt patterns match, because its
# options carry no number and its footer reads "Enter to confirm · Esc to cancel"
# rather than "Esc to cancel · Tab to amend". An unattended session started in a
# folder it has not trusted therefore blocks forever with the watchdog watching it.
# The Claude-in-Chrome start-up dialog has the same shape.
#
# ⚠️ WHEN THIS CHECK GOES RED, THE FIX IS TO RETIRE THE GAP, NOT TO RESTORE THE MISS.
# Red here means someone widened a prompt pattern to reach unnumbered choosers - the
# change technical/watchdog.md section 12 records as a decision still to make. The
# correct response is to delete this section AND the corresponding gap entry in
# technical/watchdog.md section 12 in the SAME commit. It
# is deliberately arranged so that closing the gap cannot be done quietly: a
# documented gap with no test rots into folklore, and a test with no documented gap
# reads as a design decision nobody would dare reverse.
#
# The two checks below the pin are what stop it being vacuous: without them any
# degraded or truncated file passes "is not detected" for free.
_TRUST = _fixture("real-prompt-trust.txt")

check("the trust-dialog capture really is a blocking chooser",
      "Quick safety check" in _TRUST and "Enter to confirm" in _TRUST,
      "without this the pin below passes on any file that is not a prompt")
check("the trust dialog has no NUMBERED option - that is why the cursor pattern misses",
      _re.search(r"^\s*❯\s*\S", _TRUST, _re.M) is not None
      and _re.search(r"^\s*❯\s*\d+\.", _TRUST, _re.M) is None,
      "it must carry a cursor but no digit-and-dot, or it is not the case being pinned")
check("KNOWN GAP: the trust-folder start-up dialog is NOT detected as a prompt",
      not w.looks_like_prompt(_TRUST),
      "RED HERE IS PROGRESS: a pattern now reaches unnumbered choosers. Retire this "
      "section and the matching gap entry in technical/watchdog.md section 12 "
      "together, in one commit.")

# ---------------------------------------------------------------------------
# 3. decide() - the state machine
# ---------------------------------------------------------------------------
d = w.pane_digest(PROMPT_PANE)

act, st = w.decide({}, d, True, 1000.0, HOUR)
check("first sight of a prompt waits (starts the clock)", act == "wait" and st["since"] == 1000.0)

act, st = w.decide(st, d, True, 1000.0 + HOUR - 1, HOUR)
check("one second short of the timeout still waits", act == "wait")

act, st = w.decide(st, d, True, 1000.0 + HOUR + 1, HOUR)
check("past the timeout it denies", act == "deny")
check("denying sets the fired latch", st["fired"] is True)

# TEETH - without the latch the watchdog escapes the same prompt every 30s forever.
act2, st2 = w.decide(st, d, True, 1000.0 + HOUR + 500, HOUR)
check("TEETH: it does not fire twice on one stall", act2 == "wait")

# A changed pane rearms it.
act3, st3 = w.decide(st2, "different-digest", True, 1000.0 + HOUR + 600, HOUR)
check("a changed pane rearms the latch", act3 == "wait" and st3["fired"] is False)

# TEETH - the single most dangerous case: a session sitting idle for days. Unchanged
# forever, but never a prompt, so it must never be touched.
idle = w.pane_digest(IDLE_PANE)
act, st = w.decide({}, idle, False, 0.0, HOUR)
for t in (HOUR, HOUR * 10, HOUR * 100):
    act, st = w.decide(st, idle, False, t, HOUR)
check("TEETH: an idle session is never denied, however long it idles", act == "wait",
      f"action={act}")

# TEETH - long-running work whose pane genuinely does not change must also be safe,
# because it is not a prompt.
work = w.pane_digest(WORKING_PANE)
act, st = w.decide({}, work, False, 0.0, HOUR)
act, st = w.decide(st, work, False, HOUR * 3, HOUR)
check("TEETH: a long unchanged non-prompt is never denied", act == "wait")

# ---------------------------------------------------------------------------
# 4. The notice says the refusal was mechanical
# ---------------------------------------------------------------------------
# Not cosmetic: an agent that reads this as a considered decision will accept it
# and move on, when the entire point is that it should re-examine the command.
notice = w.NOTICE.lower()
check("the notice states a stall occurred", "stall" in notice)
check("the notice states the answer was NO", "no" in notice)
check("the notice admits it was unthinking",
      "without thinking" in notice or "no idea" in notice)
check("the notice says the command did not run",
      "refused" in notice and "not executed" in notice)
check("the notice tells the agent to inform whoever was waiting", "waiting" in notice)

# ---------------------------------------------------------------------------
# 5. There is no approve path anywhere in the config
# ---------------------------------------------------------------------------
# TEETH - an auto-approve option would defeat the guard unsupervised. Its absence
# is a design property, so it gets a test rather than a comment.
raw = _CFG_RAW
action_keys = [k for k in raw.get("action", {}) if not k.startswith("_")]
check("TEETH: config exposes no approve/yes/confirm key",
      not any(k.lower() in ("approve_key", "yes_key", "confirm_key", "accept_key")
              for k in action_keys),
      f"action keys = {action_keys}")
check("the deny key is Escape", raw["action"]["deny_key"] == "Escape")

# ⚠️ The notice must NOT hardcode a duration. It did once, and a later tuning of
# stall_secs turned the one sentence whose job is "how long you were gone" into a
# lie - sending the agent looking for an hour-long gap that never happened.
check("TEETH: the notice carries a {duration} placeholder, not a fixed number",
      "{duration}" in raw["action"]["notice"])
check("TEETH: the notice states no hardcoded time",
      not any(t in raw["action"]["notice"] for t in ("60 minutes", "an hour", "120 seconds")),
      raw["action"]["notice"][:80])

# poll_secs must stay well below stall_secs or the window is sampled too few times
# for an "unchanged since" comparison to mean anything.
check("poll_secs leaves at least 4 samples inside the stall window",
      raw["stall"]["stall_secs"] / raw["stall"]["poll_secs"] >= 4,
      f"{raw['stall']['stall_secs']}/{raw['stall']['poll_secs']} = "
      f"{raw['stall']['stall_secs']/raw['stall']['poll_secs']:.0f} samples")

check("format_notice renders minutes for a 2-minute stall",
      "2 minutes" in w.format_notice("gone for {duration}.", 120.0),
      w.format_notice("gone for {duration}.", 120.0))
check("format_notice renders seconds for a short stall",
      "45 seconds" in w.format_notice("gone for {duration}.", 45.0))
check("format_notice renders hours for a long stall",
      "hours" in w.format_notice("gone for {duration}.", 7200.0),
      w.format_notice("gone for {duration}.", 7200.0))


# ---------------------------------------------------------------------------
# Taught prompts. The Claude Code session-resume prompt blocks a start-up with no
# Monitors armed; the shipped entry answers "continue, not compact". ⚠️ Refusing
# is safe because it is uninformed; CHOOSING is not - so these tests exist to
# prove the match cannot fire on the wrong prompt.
# ---------------------------------------------------------------------------

_resume = _fixture("resume-prompt.txt")

check("the resume prompt is detected as a prompt at all",
      w.looks_like_prompt(_resume))

_k = w.match_known_prompt(_resume)
check("the resume prompt matches its taught handler",
      _k is not None and _k["name"] == "claude-code-resume-return",
      str(_k and _k["name"]))

# ⚠️ THREE OUTCOMES, NOT TWO, AND THE THIRD IS THE ONE THAT LIES. With no handler
# matched, `_k["keys"]` raises and the run dies HERE - past the checks it already
# printed, before the FAILED summary, so the suite exits with a traceback and no
# verdict, where its callers expect two exit states: 0 pass, 1 with every failing
# check named on stdout. A check that could not run must SAY it could not run; it
# must never inherit the surrounding pass.
if _k is None:
    for _name in ("TEETH: it answers CONTINUE, not compact - Down then Enter",
                  "TEETH: its notice says 'as-is' and does NOT claim it compacted",
                  "TEETH: the notice tells the session to re-arm Monitors"):
        check(_name, False, "NOT RUN - no taught handler matched, so there was nothing to check")
else:
    check("TEETH: it answers CONTINUE, not compact - Down then Enter",
          _k["keys"] == ["Down", "Enter"], str(_k["keys"]))

    check("TEETH: its notice says 'as-is' and does NOT claim it compacted",
          "as-is" in _k["notice"] and "compact" in _k["notice"].lower()
          and "NOT compact" in _k["notice"], _k["notice"][:70])

    check("TEETH: the notice tells the session to re-arm Monitors",
          "re-arm" in _k["notice"].lower(), _k["notice"][-60:])

# Named for the guard they actually capture. Section 2c owns the fixtures that are
# permission prompts; calling these two that as well made the suite read as though
# the class was already covered, which is the gap section 2c exists to close.
#
# ⚠️ Both are ABSENCE assertions and both pass on an empty string, so a deleted
# fixture would leave them green. Their guard is "every prompt fixture is present
# and still reads as a prompt" in section 1c, which covers all five fixtures - not
# a local one. Named here because 200 lines away is too far to be found by anyone
# reading only this.
for name, fx in [("rm-guard prompt A", _fixture("real-prompt-a.txt")),
                 ("rm-guard prompt B", _fixture("real-prompt-b.txt"))]:
    check(f"TEETH: {name} does NOT match a taught handler - still refused",
          w.match_known_prompt(fx) is None)

check("TEETH: a pane merely MENTIONING the resume text still matches only on the real string",
      w.match_known_prompt("we discussed resuming the full session yesterday") is None)

check("comment-only entries in known_prompts are ignored",
      all(not n["name"].startswith("_") for n in w.KNOWN_PROMPTS))

# ---------------------------------------------------------------------------
# 6. The loop re-executes itself when watchdog.py changes - and only then
# ---------------------------------------------------------------------------
# The unit runs this file from the host fleet checkout and is root-owned, so the
# re-exec is the only way a `fleet upgrade` reaches a running watchdog. Two failure
# directions, both silent: no re-exec, and the watchdog runs the old code until the
# next reboot; a re-exec every cycle, and the stall timer never survives long enough
# to fire, while systemd shows the service healthy.
import shutil as _shutil
import subprocess as _subprocess
import tempfile as _tempfile
import time as _time

# A SHORT, RESOLVED base: the end-to-end case below puts a tmux socket under it, and a
# unix socket path holds at most 103 bytes on macOS, whose TMPDIR alone is about 50.
# Resolved because tmux reports its socket directory by realpath, and macOS's /tmp is
# /private/tmp.
_rx_tmp = os.path.realpath(_tempfile.mkdtemp(prefix="wdr.", dir="/tmp"))
_rx_file = os.path.join(_rx_tmp, "watchdog.py")
with open(_rx_file, "w") as _fh:
    _fh.write("# stand-in for watchdog.py\n")
_calls = []


def _fake_execv(path, args):
    _calls.append((path, list(args)))


_rec = w.self_mtime(_rx_file)
check("an unchanged file does not re-execute",
      w.maybe_reexec(_rec, _rx_file, execv=_fake_execv) is False and _calls == [], repr(_calls))
_st = os.stat(_rx_file)
os.utime(_rx_file, ns=(_st.st_atime_ns, _st.st_mtime_ns + 5_000_000_000))
w.maybe_reexec(_rec, _rx_file, execv=_fake_execv)
check("TEETH: a changed mtime re-executes this interpreter on the same argv",
      _calls == [(sys.executable, [sys.executable, *sys.argv])], repr(_calls))


def _gone_execv(path, args):
    raise FileNotFoundError(2, "No such file or directory", path)


try:
    w.maybe_reexec(_rec, _rx_file, execv=_gone_execv)
    _rx_exit = "returned"
except SystemExit as _e:
    _rx_exit = _e.code
check("TEETH: a re-exec whose interpreter is gone exits 75 (the service manager restarts it), "
      "never returns into the loop and never dies on a traceback", _rx_exit == 75, repr(_rx_exit))

# A file dated in the FUTURE when the process starts. Recorded at start, it is equal
# to itself on every later cycle, so nothing happens.
_calls.clear()
_future_ns = int((_time.time() + 10 * 365 * 86400) * 1e9)
os.utime(_rx_file, ns=(_future_ns, _future_ns))
_rec_future, _start_ns = w.self_mtime(_rx_file), _time.time_ns()
for _ in range(5):
    w.maybe_reexec(_rec_future, _rx_file, execv=_fake_execv)
check("TEETH: a file dated in the future does not re-execute, cycle after cycle",
      _calls == [], repr(_calls))
# CONTROL for the check above: it only discriminates if the tempting rule - "newer than
# when I started" - WOULD have fired on this same file. If this ever reads False the
# fixture stopped being future-dated and the check above passes for free.
check("CONTROL: a clock-based rule would re-execute on that same file every cycle",
      all(w.self_mtime(_rx_file) > _start_ns for _ in range(5)),
      f"mtime {w.self_mtime(_rx_file)} vs start {_start_ns}")

os.remove(_rx_file)
check("a file briefly absent (mid-checkout) is not a change",
      w.maybe_reexec(_rec_future, _rx_file, execv=_fake_execv) is False and _calls == [],
      repr(_calls))

# End to end, with a real process: a copy of watchdog.py on a throwaway config runs its
# loop against a tmux socket directory where no server exists (every capture fails and
# is logged; no key can be sent), its file is touched, and the SAME pid must come back
# up with a second "watchdog up" line - and then stay put.
_e2e = os.path.join(_rx_tmp, "e2e")
os.makedirs(os.path.join(_e2e, "state"))
# ⚠️ THE SOCKET DIRECTORY MUST EXIST. tmux treats TMUX_TMPDIR as the first of several
# candidate directories and moves on to /tmp when it cannot create `tmux-<uid>` inside
# it: with the directory missing, a capture reached the machine's default server and
# answered "can't find session" (measured 2026-11-06, tmux 3.6). Created, it holds no
# server, so every capture fails with an "error connecting to <that directory>/..." line
# and nothing else is reached. A host without tmux fails every capture earlier, which is
# just as safe.
os.makedirs(os.path.join(_e2e, "no-tmux-server"))
_copy = os.path.join(_e2e, "watchdog.py")
_shutil.copy2(_SCRIPT, _copy)
_e2e_cfg = _json.loads(_json.dumps(_CFG_RAW))
_e2e_cfg["tmux"] = {"tmpdir": os.path.join(_e2e, "no-tmux-server"), "target": "nobody:0"}
_e2e_cfg["stall"]["poll_secs"] = 0.2
_e2e_cfg["state"]["dir"] = os.path.join(_e2e, "state")
_e2e_cfg["owner"]["claude_config_dir"] = None
with open(os.path.join(_e2e, "config.json"), "w", encoding="utf-8") as _fh:
    _json.dump(_e2e_cfg, _fh)
_log_path = os.path.join(_e2e, "stderr.log")
_env = {k: v for k, v in os.environ.items() if k != "TMUX"}
_env["STALL_WATCHDOG_CONFIG"] = os.path.join(_e2e, "config.json")


def _log_text():
    with open(_log_path, encoding="utf-8", errors="replace") as _fh:
        return _fh.read()


def _wait_for(pred, secs=10.0):
    _deadline = _time.monotonic() + secs
    while _time.monotonic() < _deadline:
        if pred():
            return True
        _time.sleep(0.05)
    return pred()


with open(_log_path, "w") as _log:
    _proc = _subprocess.Popen([sys.executable, _copy], env=_env, stdout=_subprocess.DEVNULL,
                              stderr=_log, cwd=_e2e)
try:
    _up_once = _wait_for(lambda: _log_text().count("WATCHDOG-INFO watchdog up") >= 1)
    _st = os.stat(_copy)
    os.utime(_copy, ns=(_st.st_atime_ns, _st.st_mtime_ns + 5_000_000_000))
    _up_twice = _wait_for(lambda: _log_text().count("WATCHDOG-INFO watchdog up") >= 2)
    _time.sleep(1.0)        # five more cycles: the fresh process must not re-execute again
    _text = _log_text()
    check("a real loop comes up, re-executes once when its file changes, and comes back up",
          _up_once and _up_twice and _text.count("changed on disk - re-executing") == 1
          and _proc.poll() is None,
          f"up_once={_up_once} up_twice={_up_twice} rc={_proc.poll()} log={_text[-400:]!r}")
    check("the re-executed loop is the same process (exec, not a respawn)",
          _proc.poll() is None and _text.count("WATCHDOG-INFO watchdog up") == 2,
          _text[-300:])
    _sock_dir = os.path.join(_e2e, "no-tmux-server")
    _capture_errors = [ln for ln in _text.splitlines() if ln.startswith("WATCHDOG-ERROR")]
    check("the throwaway loop reached no tmux server at all",
          _capture_errors and all(_sock_dir in ln or "No such file or directory: 'tmux'" in ln
                                  for ln in _capture_errors),
          _text[-300:])
finally:
    _proc.kill()
    _proc.wait()
    _shutil.rmtree(_rx_tmp, ignore_errors=True)

print()
if _failures:
    print(f"FAILED: {len(_failures)} check(s): {', '.join(_failures)}")
    sys.exit(1)
print("ALL CHECKS PASSED")