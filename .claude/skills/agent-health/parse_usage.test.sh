#!/usr/bin/env bash
# Offline regression guard for parse_usage.py. No network, no tmux, no agent.
#
# WHAT EACH CASE IS LOAD-BEARING FOR - read before deleting one
# -------------------------------------------------------------
# * PRE-GATE. Every fixture - capture AND ledger - is asserted to exist and be
#   non-empty BEFORE any verdict is checked. Without it, a renamed or deleted
#   fixture would make the parser throw or read an empty history, and a suite
#   that only looked at "did the expected verdict come back" would be reporting
#   on its own plumbing rather than on the parser.
#
# * POSITIVE EVIDENCE THE SUBJECT WAS REACHED. The healthy case asserts the
#   parser found exactly THREE limits with the expected names and percentages,
#   not merely that it said `ok`. A parser that found nothing would also be
#   capable of saying `ok` if somebody ever collapsed the inconclusive state,
#   and "it said ok" would not catch that. The count and the names do.
#
# * THE NEGATIVE CONTROL: fixtures/status-screen.txt. It is the /status tab of
#   the SAME dialog - same tab bar, same "Esc to cancel" footer, no limits. It
#   must come back `inconclusive` (exit 3). If it ever comes back `ok`, the
#   parser can no longer tell "measured and fine" from "measured nothing", and
#   every verdict it has issued since is worthless. This is the case that makes
#   the whole sweep meaningful, because "no limits on the pane" is what a failed
#   send-keys, a half-drawn pane and a renamed screen all look like.
#   ⚠️ IF THIS CASE EVER PASSES BY RETURNING `ok`, ISSUE NO VERDICT ABOUT ANY
#   AGENT UNTIL THE PARSER IS FIXED.
#
# * THE BOUNDARIES. 89/94 must be `ok` and 90/95 must be `trigger`. These are
#   the only cases that can see a threshold constant drift, and they are the
#   only reason this file beats reading the bar chart by eye.
#
# * THE WINDOW AXIS. The 90% case puts 90 on the SHORT window and leaves the
#   long ones low; the 95% case puts 95 on a LONG window and leaves the short
#   one low. Run either one alone and a parser that applied a single threshold
#   to everything would still pass. Together they pin that the two thresholds
#   are actually distinguished.
#
# THE PROJECTION HALF, AND WHAT EACH OF ITS CASES ALONE CANNOT SEE
# ----------------------------------------------------------------
# The projection rule has four independent clauses, and a suite that exercised
# it with one case would pass with any three of them deleted. Each case below
# differs from its neighbour in ONE clause:
#
# * TWO CONSECUTIVE CHECKS: `prev-ok.md` and `prev-watch.md` are the same row
#   with a different `decision` cell, driven by the same capture. `prev-ok`
#   must give `watch` (exit 0) and `prev-watch` must give `switch-projection`
#   (exit 1). ⚠️ With only one of them, a parser that switched on the FIRST
#   trip would pass the suite - and would hand an agent over on one burst of
#   work. This pair is the only thing that can see that rule disappear.
#
# * THE RESET CONDITION: `usage-short-window-80.txt` and
#   `usage-short-window-80-reset-soon.txt` differ in their `Resets` line and in
#   nothing else, against the SAME ledger. One switches, the other holds. With
#   only the first, a parser that ignored the reset entirely would pass, and
#   would burn a handover on a window that was about to empty itself.
#
# * THE HORIZON: `prev-ok-distant.md` is the same 80% capture against a reading
#   an hour back instead of half an hour, so the slope is gentler and the
#   projection lands at 120 minutes. It must be `ok`. Without it, a parser that
#   tripped on ANY positive velocity would pass every other projection case.
#
# * VELOCITY'S SIGN AND ZERO: `prev-high.md` (falling usage) must produce NO
#   projection at all, and `prev-flat-90.md` (velocity exactly 0, at the floor)
#   must still `switch-floor`. The second is the one that proves the floor does
#   not secretly depend on the projection - it is the backstop for usage that
#   arrived faster than two readings could see.
#
# * THE HANDOVER DISCONTINUITY: `prev-other-account.md` is `prev-watch.md`'s
#   row on a different account. It must read as a FIRST READING. A velocity
#   computed across a handover is arithmetic over two different counters, and
#   it is wrong in the switch-an-idle-agent direction.
#
# THE TWO CASES THAT MEASURE THE INSTRUMENT RATHER THAN THE RULE
# ---------------------------------------------------------------
# * WRITER/READER ROUND TRIP. The suite appends a reading to a ledger and then
#   runs again against that same ledger, asserting the second run FOUND the row
#   the first one wrote. ⚠️ Without this, a writer emitting a shape the reader
#   cannot parse would make every sweep a `first-reading` for ever: each run
#   green, each row recorded, no agent ever switched, and nothing anywhere
#   saying so. Both halves are ours and they are tested together for that
#   reason.
#
# * A MISSING LEDGER IS EXIT 2, NOT A FIRST READING. A mistyped `--ledger` path
#   is the same silent failure by another door. The parser refuses, and this
#   case pins the refusal.
#
# * AND AN INCONCLUSIVE CAPTURE APPENDS NOTHING. A row invented from a capture
#   that read no limits becomes the baseline the next velocity is computed
#   against, so one unread pane would poison every reading after it. The case
#   asserts the ledger is byte-identical afterwards.
set -u
here="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
p="$here/parse_usage.py"
fx="$here/fixtures"
fail=0

# A FIXED CLOCK. Every projection below is arithmetic against this instant, so
# the suite is deterministic: 2026-09-22T14:00Z.
NOW=1790085600

note() { printf '%s\n' "$*"; }
bad()  { printf 'FAIL: %s\n' "$*"; fail=1; }

# --- pre-gate: the subject and every fixture are actually there --------------
[ -x "$p" ] || { bad "parse_usage.py missing or not executable at $p"; exit 1; }
for f in usage-healthy usage-below-thresholds usage-short-window-90 \
         usage-weekly-95 usage-short-window-80 usage-short-window-68 \
         usage-short-window-80-reset-soon usage-short-window-80-reset-exact \
         usage-unclassifiable-reset usage-cut-top usage-window-dropped \
         status-screen; do
  [ -s "$fx/$f.txt" ] || { bad "fixture $f.txt missing or empty"; exit 1; }
done
for f in empty prev-ok prev-watch prev-ok-distant prev-flat-90 prev-high \
         prev-other-account prev-bad-time prev-one-minute prev-malformed \
         prev-subheading prev-unrounded; do
  [ -s "$fx/ledgers/$f.md" ] || { bad "ledger fixture $f.md missing or empty"; exit 1; }
done

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# ⚠️ THE FLOOR-ONLY CASES BELOW PASS --floor-only EXPLICITLY, and that is the
# point rather than a formality: a degraded reading must be ASKED for. Without
# the flag the parser refuses (exit 2) rather than quietly applying the floor
# alone and calling the result `ok`.
verdict_of() { python3 "$p" "$1" --floor-only 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["verdict"])'; }
exit_of()    { python3 "$p" "$1" --floor-only >/dev/null 2>&1; printf '%s' "$?"; }

expect() { # expect <fixture> <verdict> <exit>
  local f="$fx/$1.txt" want="$2" wantrc="$3"
  local got rc
  got="$(verdict_of "$f")"; rc="$(exit_of "$f")"
  if [ "$got" != "$want" ]; then bad "$1: verdict '$got', expected '$want'"; fi
  if [ "$rc" != "$wantrc" ]; then bad "$1: exit $rc, expected $wantrc"; fi
}

# --- positive evidence the parser reached the subject ------------------------
IFS=$'\t' read -r n names pcts <<<"$(python3 "$p" "$fx/usage-healthy.txt" --floor-only | python3 -c '
import json,sys
d=json.load(sys.stdin)
ls=d["limits"]
print("\t".join([str(len(ls)),
                 "|".join(l["name"] for l in ls),
                 "|".join(str(l["percent"]) for l in ls)]))
')"
[ "$n" = "3" ] || bad "healthy capture: parsed $n limits, expected 3"
[ "$names" = "Current session|Current week (all models)|Current week (Fable)" ] \
  || bad "healthy capture: names were '$names'"
[ "$pcts" = "41|10|11" ] || bad "healthy capture: percentages were '$pcts'"

# --- the negative control ----------------------------------------------------
expect status-screen inconclusive 3

# --- boundaries, on both window axes ----------------------------------------
# ⚠️ `floor-only`/4 where a projected run would say `ok`/0 - the whole point of
# the separate verdict. `trigger`/1 is unchanged: the floor is the floor with or
# without a ledger.
expect usage-healthy            floor-only 4
expect usage-below-thresholds   floor-only 4   # 89 short, 94 long -> under both
expect usage-short-window-90    trigger 1   # 90 on the SHORT window only
expect usage-weekly-95          trigger 1   # 95 on a LONG window only

# --- the window classification itself ---------------------------------------
windows="$(python3 "$p" "$fx/usage-healthy.txt" --floor-only | python3 -c '
import json,sys; print("|".join(l["window"] for l in json.load(sys.stdin)["limits"]))')"
[ "$windows" = "short|long|long" ] || bad "window classification was '$windows'"

# --- an empty capture is inconclusive, never ok ------------------------------
empty_verdict="$(printf '' | python3 "$p" --floor-only | python3 -c 'import json,sys; print(json.load(sys.stdin)["verdict"])')"
[ "$empty_verdict" = "inconclusive" ] || bad "empty capture returned '$empty_verdict'"

# --- a degraded reading has to be ASKED FOR, and is never `ok` --------------
# ⚠️ A forgotten `--ledger` would otherwise give a floor-only reading reported
# as `ok`/exit 0 - byte-identical, to a caller reading $?, to a fully projected
# clean sweep. That is the same "green for ever while measuring nothing"
# outcome the missing-ledger refusal exists to prevent, through the front door.
python3 "$p" "$fx/usage-healthy.txt" >/dev/null 2>&1
[ "$?" = "2" ] || bad "a run with no --ledger and no --floor-only did not exit 2"

fo_verdict="$(python3 "$p" "$fx/usage-healthy.txt" --floor-only | python3 -c '
import json,sys; print(json.load(sys.stdin)["verdict"])')"
python3 "$p" "$fx/usage-healthy.txt" --floor-only >/dev/null 2>&1
fo_rc="$?"
[ "$fo_verdict" = "floor-only" ] || bad "--floor-only verdict was '$fo_verdict', expected floor-only"
[ "$fo_rc" = "4" ]               || bad "--floor-only exited $fo_rc, expected 4 (never 0 - that is `ok`'s code)"

decisions="$(python3 "$p" "$fx/usage-healthy.txt" --floor-only | python3 -c '
import json,sys; print("|".join(l["decision"] for l in json.load(sys.stdin)["limits"]))')"
[ "$decisions" = "floor-only|floor-only|floor-only" ] \
  || bad "floor-only decisions were '$decisions', expected all floor-only"

# --- the normaliser, driven directly ----------------------------------------
# ⚠️ ONE function normalises a window name, and the WRITER and the READER both
# go through it. They did not: `_cell` mapped "" to "-" on the way in while the
# lookup asked for "", so that window was a `first-reading` on every sweep for
# ever at exit 0. Pinned here because no end-to-end case can reach the empty
# branch any more (an unnamed limit is now inconclusive before it gets there).
norm="$(python3 -c '
import importlib.util,sys
spec=importlib.util.spec_from_file_location("pu", sys.argv[1])
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(m._cell("a|b"), m._cell(""), m._cell(" x "), m._cell("a\nb"))' "$p")"
[ "$norm" = "a/b - x a b" ] || bad "_cell normalisation was '$norm', expected 'a/b - x a b'"

# =============================== the projection ==============================

# run <ledger-fixture> <capture> -> prints "<verdict> <decision-of-limit-0> <exit>"
run() {
  local led="$tmp/$1-$RANDOM.md" out rc
  cp "$fx/ledgers/$1.md" "$led"
  out="$(python3 "$p" "$fx/$2.txt" --agent alpha --account acct-a \
        --ledger "$led" --now "$NOW" 2>/dev/null)"; rc=$?
  printf '%s %s\n' "$(printf '%s' "$out" | python3 -c '
import json,sys
d=json.load(sys.stdin)
print(d["verdict"], d["limits"][0]["decision"])')" "$rc"
}

proj() { # proj <ledger> <capture> <verdict> <decision> <exit>
  local got want="$3 $4 $5"
  got="$(run "$1" "$2")"
  [ "$got" = "$want" ] || bad "$1 + $2: got '$got', expected '$want'"
}

# runx: the raw exit code alone, for the cases with no limits to read
runx() {
  local led="$tmp/$1-x$RANDOM.md"
  cp "$fx/ledgers/$1.md" "$led"
  python3 "$p" "$fx/$2.txt" --agent alpha --account acct-a \
    --ledger "$led" --now "$NOW" >/dev/null 2>&1
  printf '%s' "$?"
}

# a first reading is RECORDED, not acted on
proj empty               usage-healthy              ok      first-reading      0
# the SECOND of the two consecutive checks is what switches; the first watches
proj prev-ok             usage-short-window-80      ok      watch              0
proj prev-watch          usage-short-window-80      trigger switch-projection  1
# ...and the reset condition, same ledger, one changed Resets line
proj prev-watch          usage-short-window-80-reset-soon ok hold-reset-first  0
# a projection beyond the 60-minute horizon is not a trip at all
proj prev-ok-distant     usage-short-window-80      ok      ok                 0
# the floor fires at velocity exactly zero - it does not depend on the slope
proj prev-flat-90        usage-short-window-90      trigger switch-floor       1
# falling usage projects nothing
proj prev-high           usage-healthy              ok      ok                 0
# a reading on a different account is a first reading, never a velocity
proj prev-other-account  usage-short-window-80      ok      first-reading      0

# ⚠️ A READING THAT PRODUCES NO PROJECTION DOES NOT CLEAR A STANDING TRIP.
# These agents work a turn and then wait, so their velocity alternates between
# a burst and zero. With a zero reading resetting the consecutive counter a
# bursty agent tripped the horizon three times, was never switched, and met the
# floor at 100% with the cap already landed. The pair below is the only thing
# that can see that behaviour change: same capture, same zero velocity, one
# previous decision apart.
proj prev-watch          usage-short-window-68      ok      watch              0
proj prev-ok             usage-short-window-68      ok      ok                 0

# ⚠️ THE RESET COMPARISON IS INCLUSIVE, and this fixture is the only thing that
# says so: its reset lands EXACTLY on the projected depletion (14:50). With `<`
# instead of `<=` it switches; the window empties itself at the very moment it
# would have run out, so holding is right and the boundary is a decision.
proj prev-watch          usage-short-window-80-reset-exact ok hold-reset-first 0

# ⚠️ THE UNCLASSIFIABLE-RESET FAIL-SAFE, which the docstring and SKILL.md both
# state and nothing measured. The capture sits at 92 with a `Resets` line that
# parses as neither a time nor a date: under the SHORT threshold (90) that is a
# trigger, under the LONG one (95) it is `ok`. Flip the fail-safe to the looser
# threshold and this is the case that reds.
proj prev-ok             usage-unclassifiable-reset trigger switch-floor       1

# ⚠️ A SLOPE NEEDS AN INTERVAL. The previous row is ONE MINUTE back, which is
# an ordinary gap (a session-start sweep followed by the scheduled one). Taken
# as a rate, one percentage point over a minute is 60 %/h and projects
# depletion inside the horizon on an agent that moved 1%. No slope is computed.
proj prev-one-minute     usage-short-window-80      ok      first-reading      0

# a corrupt `time` cell is a first reading, NOT a traceback. An uncaught
# strptime here exits 1, which is the published contract for "hand this agent
# over".
proj prev-bad-time       usage-short-window-80      ok      first-reading      0

# ⚠️ ANY heading closes an agent's section. `prev-subheading.md` is
# `prev-watch.md` with its row parked under an operator's `### notes`: read as
# alpha's, it would switch the agent on somebody's annotation.
proj prev-subheading     usage-short-window-80      ok      first-reading      0

# ---- the instrument reaching only PART of its subject: inconclusive, not ok --
# ⚠️ Both of these came back `ok` before, and both are ordinary `capture-pane`
# output rather than adversarial input.
#  * a capture cut at the top (a dialog taller than the pane) leaves the first
#    limit with no NAME line, and a nameless limit cannot be matched against its
#    own previous reading - so it was a `first-reading` for ever at exit 0;
#  * one wrapped `NN% used` line drops a whole window from the sweep, and the
#    window that vanished was the one sitting on a `watch`.
# ⚠️ AGAINST `empty.md`, NOT AGAINST A LEDGER WITH ROWS, AND THAT IS THE WHOLE
# CASE. With a previous sweep recorded, the missing-window guard below ALSO
# reports this capture inconclusive - so the assertion passed with the unnamed
# guard deleted, measuring the broader guarantee instead of the rule it names.
# An empty ledger has no previous sweep, so nothing but the unnamed guard can
# produce this verdict.
[ "$(runx empty      usage-cut-top)"        = "3" ] \
  || bad "a capture with an unnamed limit did not come back inconclusive"
[ "$(runx prev-watch usage-window-dropped)" = "3" ] \
  || bad "a capture missing a window the previous sweep recorded did not come back inconclusive"
# ...and the SECOND of those is the LEDGER comparison, not something about the
# capture: with no ledger to compare against, the same capture is readable.
python3 "$p" "$fx/usage-window-dropped.txt" --floor-only >/dev/null 2>&1
[ "$?" = "4" ] \
  || bad "the dropped-window capture is not readable at all - the inconclusive above is about the capture, not about the missing window"

# a malformed ledger row is an INSTRUMENT FAULT (exit 2), never a silent skip.
# Skipping it makes an OLDER row the baseline and downgrades a handover to a
# wait, with nothing red anywhere.
[ "$(runx prev-malformed usage-short-window-80)" = "2" ] \
  || bad "a malformed ledger row did not exit 2 - it was skipped, and an older row became the baseline"

# ---- the dated-reset path, which nothing read ------------------------------
# ⚠️ Every projection fixture's long windows are first readings, so their
# `resets_at` was never looked at: the whole `Sep 23, 8pm` branch, its month
# table and its year rollover could return None, or the wrong year, with the
# suite green. The short-window cases cannot see it - they all use a time-only
# reset.
resets_at="$(python3 "$p" "$fx/usage-healthy.txt" --agent alpha --account acct-a \
  --ledger <(cat "$fx/ledgers/empty.md") --now "$NOW" 2>/dev/null | python3 -c '
import json,sys; print("|".join(str(l["resets_at"]) for l in json.load(sys.stdin)["limits"]))')"
[ "$resets_at" = "2026-09-23T01:20Z|2026-09-23T20:00Z|2026-09-23T20:00Z" ] \
  || bad "resolved reset times were '$resets_at' (time-only, dated, dated)"

# the year rollover, which only a date already past this year can see
rollover="$(python3 -c '
import importlib.util,sys
from datetime import datetime,timezone
spec=importlib.util.spec_from_file_location("pu", sys.argv[1])
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
now=datetime(2026,9,22,14,0,tzinfo=timezone.utc).timestamp()
def f(x):
    r=m.resolve_reset(x, now)
    return "None" if r is None else datetime.fromtimestamp(r,tz=timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
print(f("Jan 2, 8pm (UTC)"), f("Sep 23, 8pm (UTC)"), f("Sep 23, 8pm"), f("Sep 23, 8pm (PST)"))' "$p")"
[ "$rollover" = "2027-01-02T20:00Z 2026-09-23T20:00Z None None" ] \
  || bad "reset resolution was '$rollover' - expected a January date to roll into 2027, a bare (no-zone) reset to be UNRESOLVED rather than assumed UTC, and a named non-UTC zone to be unresolved"

# the numbers themselves, not only the labels: 68% -> 80% in 30 min is 24 %/h,
# and 20 points left at 24 %/h is 50 minutes.
IFS=' ' read -r v mins dep <<<"$(cp "$fx/ledgers/prev-ok.md" "$tmp/num.md"; \
  python3 "$p" "$fx/usage-short-window-80.txt" --agent alpha --account acct-a \
  --ledger "$tmp/num.md" --now "$NOW" | python3 -c '
import json,sys
l=json.load(sys.stdin)["limits"][0]
print(l["velocity_pct_per_hour"], l["minutes_to_depletion"], l["projected_depletion"])')"
[ "$v" = "24.0" ]    || bad "velocity was '$v', expected 24.0"
[ "$mins" = "50.0" ] || bad "minutes to depletion was '$mins', expected 50.0"
[ "$dep" = "2026-09-22T14:50Z" ] || bad "projected depletion was '$dep'"

# ⚠️ A NON-ROUND VELOCITY, because 24.0 is 24.0 rounded or not. 68% -> 80% over
# 35 minutes is 20.571... %/h, and the ledger prints one decimal place: the
# projection is computed from the PRINTED number so that a reader can
# recompute the row. Delete the rounding and this is the only case that sees it.
IFS=' ' read -r rv rdep <<<"$(cp "$fx/ledgers/prev-unrounded.md" "$tmp/round.md"; \
  python3 "$p" "$fx/usage-short-window-80.txt" --agent alpha --account acct-a \
  --ledger "$tmp/round.md" --now "$NOW" | python3 -c '
import json,sys
l=json.load(sys.stdin)["limits"][0]
print(l["velocity_pct_per_hour"], l["projected_depletion"])')"
[ "$rv" = "20.6" ] || bad "velocity was '$rv', expected 20.6 (one decimal place, so the row can be recomputed)"
[ "$rdep" = "2026-09-22T14:58Z" ] || bad "projected depletion from the rounded velocity was '$rdep', expected 2026-09-22T14:58Z"

# EVERY limit's decision, not only the first. Every projection case above
# reads `limits[0]`, so a regression confined to the long windows would show up
# only if it flipped the top-level verdict.
alldec="$(cp "$fx/ledgers/prev-ok.md" "$tmp/all.md"; \
  python3 "$p" "$fx/usage-short-window-80.txt" --agent alpha --account acct-a \
  --ledger "$tmp/all.md" --now "$NOW" | python3 -c '
import json,sys; print("|".join(l["decision"] for l in json.load(sys.stdin)["limits"]))')"
[ "$alldec" = "watch|first-reading|first-reading" ] \
  || bad "the full decision vector was '$alldec', expected 'watch|first-reading|first-reading'"

# the floor case with zero velocity really did compute a zero, rather than
# failing to compute one: a null would pass the decision check above too.
zv="$(cp "$fx/ledgers/prev-flat-90.md" "$tmp/zv.md"; \
  python3 "$p" "$fx/usage-short-window-90.txt" --agent alpha --account acct-a \
  --ledger "$tmp/zv.md" --now "$NOW" | python3 -c '
import json,sys; print(json.load(sys.stdin)["limits"][0]["velocity_pct_per_hour"])')"
[ "$zv" = "0.0" ] || bad "flat-90 velocity was '$zv', expected 0.0"

# =============================== the instrument ==============================

# WRITER/READER ROUND TRIP. Append a reading, then read it back as the previous
# row 30 minutes later. Without this, a writer the reader cannot parse makes
# every sweep a first reading for ever, silently.
rt="$tmp/roundtrip.md"
cp "$fx/ledgers/prev-ok.md" "$rt"
appended="$(python3 "$p" "$fx/usage-short-window-80.txt" --agent alpha \
  --account acct-a --ledger "$rt" --now "$NOW" --append | python3 -c '
import json,sys; print(json.load(sys.stdin)["ledger"]["rows_appended"])')"
[ "$appended" = "3" ] || bad "round trip: appended '$appended' rows, expected 3"

IFS=' ' read -r seen prevpct prevdec <<<"$(python3 "$p" \
  "$fx/usage-short-window-90.txt" --agent alpha --account acct-a \
  --ledger "$rt" --now "$((NOW + 1800))" | python3 -c '
import json,sys
l=json.load(sys.stdin)["limits"][0]
pv=l["previous"]
print(bool(pv), pv and pv["percent"], pv and pv["decision"])')"
[ "$seen" = "True" ] || bad "round trip: the appended row was NOT read back - the writer and the reader disagree"
[ "$prevpct" = "80" ]   || bad "round trip: previous percent read back as '$prevpct', expected 80"
[ "$prevdec" = "watch" ] || bad "round trip: previous decision read back as '$prevdec', expected watch"

# A MISSING LEDGER IS AN INSTRUMENT FAULT (exit 2), NOT AN AGENT WITH NO HISTORY.
python3 "$p" "$fx/usage-healthy.txt" --agent alpha --ledger "$tmp/no-such-ledger.md" \
  --now "$NOW" >/dev/null 2>&1
[ "$?" = "2" ] || bad "a missing ledger did not exit 2 - a mistyped path reads as 'first reading' for ever"

# --ledger with no --agent cannot know whose rows to read, and refuses.
python3 "$p" "$fx/usage-healthy.txt" --ledger "$fx/ledgers/empty.md" >/dev/null 2>&1
[ "$?" = "2" ] || bad "--ledger without --agent did not exit 2"

# ...and with no --account it would match nothing, so it refuses too. ⚠️ This
# defaulted to "-" and was accepted: forgetting it gave `first-reading` on every
# window for ever at exit 0, the same failure as a mistyped ledger path.
python3 "$p" "$fx/usage-healthy.txt" --agent alpha --ledger "$fx/ledgers/empty.md" >/dev/null 2>&1
[ "$?" = "2" ] || bad "--ledger without --account did not exit 2"

# ⚠️ AN UNEXPECTED EXCEPTION IS EXIT 2, NEVER EXIT 1. Exit 1 is the published
# contract for HAND THIS AGENT OVER, and an uncaught traceback exits 1. A
# --ledger naming a DIRECTORY passes the exists() check and then throws.
python3 "$p" "$fx/usage-healthy.txt" --agent alpha --account acct-a \
  --ledger "$tmp" --now "$NOW" >/dev/null 2>&1
[ "$?" = "2" ] || bad "a --ledger naming a directory did not exit 2 - a crash was reported as a trigger"
python3 "$p" --init --ledger "$tmp/no-such-dir/led.md" >/dev/null 2>&1
[ "$?" = "2" ] || bad "--init into a missing directory did not exit 2"

# THE SANCTIONED ENTRY POINT. Every other case here runs `python3 <path>`;
# SKILL.md documents the bare form, so a broken shebang would leave this suite
# green and the documented command dead.
"$p" "$fx/usage-healthy.txt" --floor-only >/dev/null 2>&1
[ "$?" = "4" ] || bad "the bare ./parse_usage.py invocation did not run - check the shebang"

# AN INCONCLUSIVE CAPTURE APPENDS NOTHING.
inc="$tmp/inconclusive.md"
cp "$fx/ledgers/prev-ok.md" "$inc"
before="$(cksum < "$inc")"
python3 "$p" "$fx/status-screen.txt" --agent alpha --account acct-a \
  --ledger "$inc" --now "$NOW" --append >/dev/null 2>&1
rc=$?
after="$(cksum < "$inc")"
[ "$rc" = "3" ]             || bad "inconclusive + --append exited $rc, expected 3"
[ "$before" = "$after" ]    || bad "an inconclusive capture WROTE to the ledger - it would poison the next velocity"
# ...and the guard itself, not only its effect. An append of an inconclusive
# capture's (empty) limit list changes no bytes either, so the cksum above
# passes whether or not the guard exists. `rows_appended` is null when no
# append was ATTEMPTED and an integer when one was: that is the only place the
# guard is visible from outside, and without this line it could be deleted with
# the whole suite still green.
att="$(cp "$fx/ledgers/prev-ok.md" "$tmp/inc2.md"; python3 "$p" "$fx/status-screen.txt" \
  --agent alpha --account acct-a --ledger "$tmp/inc2.md" --now "$NOW" --append 2>/dev/null \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["ledger"]["rows_appended"])')"
[ "$att" = "None" ] || bad "inconclusive + --append ATTEMPTED an append (rows_appended=$att); the guard is gone"

# ======================= the prose the parser is driven from ==================
#
# SKILL.md's sweep is a NUMBERED procedure and its steps get reordered - this
# very commit moved the account read from step 5 to step 3. A `step N` pointer
# is prose, so no symbol grep can see it go stale, and a stale one sends an
# operator mid-sweep to the wrong instruction. `agent-revive` carries the same
# guard over its own skill for the same reason; this is agent-health's.
#
# ⚠️ A POINTER QUALIFIED BY ANOTHER SKILL'S NAME BELONGS TO THAT SKILL, AND
# CHECKING IT HERE WOULD BE ACCIDENTALLY RIGHT. This file says "`/agent-revive`
# step 5" and "`/agent-revive` step 11"; agent-health happens to have a step 5
# and a step 11 too, so a guard that did not separate them would go green
# while validating nothing about either skill. They are split out and checked
# against agent-revive's OWN step list when that skill is present - and the
# split is asserted to have actually removed something, because an exclusion
# that matches nothing is an exclusion that is not running.
# CONTEXT.md is the INSTALL's file, so it is read from the install context `fleet
# where` resolves (the fixture install in the fleet's CI); the skill directory holds
# COMMON files only. $FLEET_BIN overrides this fleet tree's own bin/fleet.
SK="$here/SKILL.md"
CX="$("${FLEET_BIN:-$here/../../../bin/fleet}" where agent-health CONTEXT.md 2>/dev/null)" || CX=""
[ -s "$SK" ] || bad "SKILL.md missing at $SK"
[ -s "$CX" ] || bad "CONTEXT.md missing at '${CX}' (fleet where agent-health CONTEXT.md - the install context must resolve)"

have_steps="$(grep -oE '^### [0-9]+\.' "$SK" | grep -oE '[0-9]+' | sort -un)"
# ⚠️ NEWLINES ARE FLATTENED BEFORE ANYTHING IS MATCHED, AND THAT IS NOT TIDYING.
# These are hard-wrapped prose files, so a pointer lands across a line break as
# often as not - a charter carries a live "`/agent-revive` step" / "5" split,
# found by a reviewer after a line-oriented grep of that same file
# reported no pointers at all. A guard that reads line by line therefore reports
# CLEAN on exactly the pointers that are hardest to notice by eye, which is the
# worst direction for it to be wrong in. The control below measures the
# flattening itself, on a synthetic wrapped pointer, rather than relying on the
# prose happening to contain one - prose re-wraps, and a control that depends on
# where a line breaks today is a control that silently stops controlling.
all_refs="$(cat "$SK" "$CX" | tr '\n' ' ')"
# pointers that name another skill: `/<skill>` immediately before "step N"
foreign="$(printf '%s' "$all_refs" | grep -oE '`/[a-z-]+`[^.]{0,4}[Ss]tep [0-9]+' | grep -oE '[0-9]+$' | sort -un)"
own="$(printf '%s' "$all_refs" | sed -E 's@`/[a-z-]+`([^.]{0,4})[Ss]tep [0-9]+@@g' \
        | grep -oE '[Ss]tep [0-9]+' | grep -oE '[0-9]+' | sort -un)"

bad_own=""
for n in $own; do grep -qx "$n" <<<"$have_steps" || bad_own="$bad_own $n"; done
[ -z "$bad_own" ] || bad "SKILL.md/CONTEXT.md point at step(s)$bad_own, which SKILL.md does not have"

# control on the FLATTENING, read off the guard's OWN corpus rather than off a
# synthetic string. ⚠️ The first version of this control piped a two-line literal
# through `tr` and checked the result - which measures that `tr` works, not that
# this guard uses it, and would stay green with the flattening deleted. If
# $all_refs still carries a newline, the references are being matched line by
# line and every wrapped pointer is invisible.
lines_in_refs="$(printf '%s' "$all_refs" | grep -c '^')"
[ "$lines_in_refs" -le 1 ] \
  || bad "step guard: the reference text still has $lines_in_refs lines - it is not flattened, so a pointer wrapped across a line break is invisible"

# control: the guard found something to check, rather than passing on an empty set
[ "$(wc -w <<<"$own")" -ge 4 ] \
  || bad "step guard: only $(wc -w <<<"$own") own-step references found - it is passing by finding nothing"
# control: the foreign-pointer split actually fired
[ "$(wc -w <<<"$foreign")" -ge 1 ] \
  || bad "step guard: the cross-skill exclusion matched nothing, so it is not separating anything"

# the foreign pointers, against the skill that owns them
revive="$here/../agent-revive/SKILL.md"
if [ -s "$revive" ]; then
  revive_steps="$(grep -oE '^### [0-9]+\.' "$revive" | grep -oE '[0-9]+' | sort -un)"
  [ "$(wc -w <<<"$revive_steps")" -ge 4 ] \
    || bad "step guard: could not read agent-revive's step list - it issues no verdict on the cross-skill pointers"
  bad_foreign=""
  for n in $foreign; do grep -qx "$n" <<<"$revive_steps" || bad_foreign="$bad_foreign $n"; done
  [ -z "$bad_foreign" ] || bad "a \`/agent-revive\` step pointer names step(s)$bad_foreign, which that skill does not have"
else
  note "note: agent-revive is not installed beside this skill, so its step pointers were not checked"
fi

if [ "$fail" = 0 ]; then note "parse_usage.test.sh: PASS"; else note "parse_usage.test.sh: FAILED"; fi
exit "$fail"
