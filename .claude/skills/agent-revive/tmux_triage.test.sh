#!/usr/bin/env bash
# Offline regression guard for tmux_triage.sh: no tmux server, no network, no
# keystroke, and no file outside this skill tree written - every case feeds a fixture
# or a temp file and asserts the result. The `unreachable` cases run a tmux CLIENT,
# against a socket directory under the temp dir (UCFG, below). The daemon-liveness cases read a FAKE process table
# built under the temp dir (AGENT_REVIVE_PROC_ROOT), never the live /proc.
#
# The live-unit route IS taken - the cases that assert an unreadable unit exits 2
# have to take it to mean anything - but against a FAKE service manager:
# $FLEET_SYSTEMCTL is set below to a stand-in that knows no unit, and
# $XDG_CONFIG_HOME to an empty directory, so neither manager nor the user-unit
# directory of this host is read. The cases that need a manager to answer (a USER
# unit, a token agent) use a stand-in that answers only what they set up. What is
# still read from the host: /etc/systemd/system/claude-agent-testagent.service,
# which the fixture config's unit name keeps from existing.
#
# ⚠️ THESE CONTROLS ARE LOAD-BEARING AND MUST NOT BE REMOVED FOR TIDINESS. Each
# one exists because the property it measures is INVISIBLE while it holds:
#   - "negative control": a pane that matches NOTHING must be 'unknown'. Without it,
#     a classifier bug that returned a fixed state would pass every positive case
#     and the suite would be green while blind.
#   - "URL join beats truncation": it asserts the FULL wrapped URL is returned,
#     specifically the tail a naive single-line grep would DROP. It re-derives what a
#     truncating grep would have returned and requires the script to do strictly
#     better. That truncation is the real bug this extraction exists to fix (284 of
#     450 chars authorized as an invalid URL), so if this case ever fails, the join
#     has regressed to truncation - do not "fix" it by shortening the expectation.
#   - "status-modal is checked BEFORE healthy": the /status block is drawn OVER a
#     live session, so its pane ALSO carries the ready status bar. The control on
#     this control proves the fixture really does match the healthy signature, so
#     the ordering assertion cannot pass vacuously. Reorder the classifier and a
#     modal left open on an agent's pane reads as "healthy, nothing to do" - which
#     is exactly what the dismissal step exists to prevent.
#   - "no password reaches the output": --accounts prints usernames and must NEVER
#     print a password. That is the entire reason the command exists instead of an
#     operator running `cat` on the pool file. This assertion is what keeps the
#     property true; without it a future field-dump "for debugging" - here or in
#     the pool picker it calls - puts a password into a pane, a scrollback and a
#     transcript, and nothing goes red.
#   - "'next' is exactly the picker's pick": the table is read off agent-health's
#     pool_pick.py, run directly on the same fixture. Without it the table could
#     compute a switch target of its own that merely looks plausible, and the
#     table and the picker would disagree with nothing red.
#   - "daemon liveness": an idle pane with every configured daemon absent must read
#     `stopped`, daemons running under ANOTHER agent's config dir must not count, and
#     a reading that could not be taken must come back null and decide nothing. The
#     pane alone reads `healthy` there, so without the daemon reading a stopped agent
#     passes every hourly sweep; a mutation control proves the `stopped` branch is
#     what decides.
#   - "login-expired": a dead login behind a ready prompt prints no sign-in URL, so
#     without this branch it reads `healthy` on every sweep. The mutation control
#     disables the branch in a copy and requires exactly that `healthy` back, so the
#     branch is proven to be what decides; the regime controls (a nested bullet, a
#     `cat`, a `git diff`, a mid-sentence quote) each carry a control proving the
#     words really are on the pane - three of them behind nothing but decoration, the
#     shape the cap-style anchor admits - so they cannot pass vacuously; the
#     recovery rows (a later turn, `Login successful`) are what stop a revived agent
#     being sent through /login a second time; and the dialog rows are what keep the
#     remedy's Enter off the exit dialog, where it kills the session. Every `⎿` row
#     is built from the fixture's own prefix bytes (a NON-BREAKING space after the
#     glyph): built with ASCII spaces, the recovery row stays green while a real
#     recovery reads `login-expired`.
#   - "cross-reference guard": every `step N` and `case N` the script or SKILL.md
#     cites must exist as a heading/row in SKILL.md. Step numbers are renumbered
#     whenever a step is inserted, and a stale pointer sends an operator mid-revival
#     to the wrong instruction. Greps cannot see this: the reference is a NUMBER in
#     prose, not a symbol.
#
# ⚠️ Grep a captured VARIABLE, never `cmd 2>&1 >/dev/null | grep -q ...`: grep -q
# exits on the first match, SIGPIPEs the producer, and under `set -o pipefail` the
# pipeline then reports failure even though the string WAS found. That is a false
# red that looks exactly like a real one, and it cost a debugging round here.
#
# ⚠️ THE SIGN-IN AND THE SWITCH ARE NOT COVERED HERE AND CANNOT BE. The sign-in drives
# a LIVE Google flow in a real browser - automated by the reviving agent in SKILL.md
# step 6, by a human in step 7 - and an account switch drives a LIVE session's
# keystrokes. (The sign-in driver's own guards are different files with their own
# controls: signin_driver/redaction.test.mjs, profiles.test.mjs and share.test.mjs -
# of which only the statement of the share's input restriction is pinned here, below,
# because this file needs no browser and share.test.mjs does.)
# A green run here means the SCRIPTED READ-ONLY parts behave; it is not evidence
# that any agent can actually be revived or switched. Prove that per agent, at
# revival time.
set -uo pipefail
HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
F="$HERE/fixtures"; CFG="$F/config.fixture.json"; SKILL="$HERE/SKILL.md"
EX_POOL="$HERE/secrets/claude-account-pool.example.json"
POOL_FX="$HERE/../agent-health/fixtures/pool"
POOL_NOW=1792152000   # 2026-10-16T12:00Z, the clock agent-health's pool fixtures are written against
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
printf '#!/bin/sh\nexit 1\n' > "$TMP/no-systemctl"; chmod +x "$TMP/no-systemctl"
mkdir -p "$TMP/empty-config-home" "$TMP/home"
export FLEET_SYSTEMCTL="$TMP/no-systemctl" XDG_CONFIG_HOME="$TMP/empty-config-home"
# The systemd backend for every case but the launchd section's, which sets its own,
# so this file reads the same on macOS, where the script would otherwise pick
# launchd; and a HOME of its own, so no case reads a real ~/Library/LaunchAgents.
# The host settings keep the path the caller's HOME gave them (fleetlib's default),
# so `fleet where` resolves as it would have.
export FLEET_HOST_CONFIG="${FLEET_HOST_CONFIG:-$HOME/.config/agent-fleet/host.json}"
export FLEET_SERVICE_BACKEND=systemd HOME="$TMP/home"
unset AGENT_REVIVE_DAEMONS_STATUS
# ⚠️ THE `unreachable` CASES RUN A REAL tmux CLIENT, so its socket directory is this
# run's own. The live capture route (no --pane-file) runs `tmux capture-pane` with
# TMUX_TMPDIR taken from the config, and tmux SKIPS a TMUX_TMPDIR that does not
# exist and falls back to /tmp: it creates /tmp/tmux-<uid> (left behind on macOS as
# /private/tmp/tmux-<uid>) and asks the caller's REAL default server for the
# session, so a host with a session of that name would hand this file a live pane.
# UCFG names a directory that exists under $TMP: the client finds no server there,
# and the trap removes the tmux-<uid> it creates. Every live-route case uses UCFG,
# or a config derived from it. The name is short: macOS's $TMP is deep and caps a
# socket path (<dir>/tmux-<uid>/default) at 104 bytes.
mkdir -m 700 "$TMP/tm"
UCFG="$TMP/config.own-tmux.json"
jq --arg d "$TMP/tm" '.fleet.tmux.tmpdir = $d' "$CFG" > "$UCFG"
pass=0; fail=0
T() { bash "$HERE/tmux_triage.sh" testagent --config "$CFG" "$@"; }
state_of() { T --pane-file "$F/$1" 2>/dev/null | jq -r '.state'; }
ok() { if [ "$2" = "$3" ]; then echo "ok   - $1"; pass=$((pass+1)); else echo "FAIL - $1: expected '$3', got '$2'"; fail=$((fail+1)); fi; }
# A .claude.json carrying one email, for the offline --current-account routes.
claude_json_with() { printf '{"oauthAccount":{"emailAddress":"%s"}}\n' "$1" > "$TMP/$2"; printf '%s' "$TMP/$2"; }

ok "auth-method menu"     "$(state_of auth-method-prompt.txt)" auth-method
ok "sign-in URL waiting"  "$(state_of signin-url.txt)"         signin-url
ok "theme selector"       "$(state_of theme-prompt.txt)"       theme-prompt
ok "scroll selector"      "$(state_of scroll-prompt.txt)"      scroll-prompt
ok "healthy status bar"   "$(state_of healthy-pane.txt)"       healthy
ok "/status modal open"   "$(state_of status-modal.txt)"       status-modal
ok "usage cap at an idle prompt" "$(state_of usage-cap.txt)"    usage-cap
ok "agent-tree view, timers running" "$(state_of agent-tree.txt)" working
ok "agents panel in MANAGE mode, a subagent timer running" "$(state_of agent-manage-panel.txt)" working

# control on the control: the status-modal fixture MUST also match the healthy
# signature, or the ordering assertion above proves nothing.
ok "control: the status-modal pane DOES carry a ready status bar (so order matters)" \
   "$(grep -qiE 'bypass permissions|for shortcuts' "$F/status-modal.txt" && echo yes || echo no)" yes

# ⚠️ SAME CONTROL, SAME REASON, for usage-cap - but DERIVED rather than
# hand-copied. The cap banner is drawn above a session sitting at its ready prompt,
# so its pane ALSO matches `healthy`, and the ordering above is the only thing
# keeping it from reading as "nothing to do". A control that greps a SUBSET of the
# healthy signature by hand would keep passing if that signature were narrowed, so
# this one disables the usage-cap branch in a COPY of the real script and requires
# the fixture to fall through to `healthy`. That is the claim the ordering makes,
# measured on the classifier itself rather than restated.
sed -E 's/^elif \[ -n "\$cap_banner" \] && \[ "\$busy" = no \]; then/elif false; then/' \
    "$HERE/tmux_triage.sh" > "$TMP/no-cap-branch.sh"
ok "control: the mutation actually applied (the branch is gone from the copy)" \
   "$(grep -c 'state="usage-cap"' "$TMP/no-cap-branch.sh" | tr -d ' ')" 1
ok "control: with the usage-cap branch disabled the fixture falls through to healthy" \
   "$(bash "$TMP/no-cap-branch.sh" testagent --config "$CFG" --pane-file "$F/usage-cap.txt" 2>/dev/null | jq -r '.state')" healthy

# ⚠️ REGIME CONTROL on usage-cap, the twin of the status-modal one above: it must
# fire on the BANNER at the start of a line, not on the WORDS anywhere on the pane.
# This skill and its script quote the banner verbatim, so a substring match reports
# an agent READING this file as capped - and the remedy for usage-cap costs a human
# round trip and burns an account switch on an agent that is working fine.
printf ' > We detect the "You'"'"'ve hit your session limit" banner on the pane.\n\n bypass permissions on (shift+tab to cycle) - ? for shortcuts\n' > "$TMP/fp-cap-prose.txt"
ok "NOT a cap: prose quoting the banner mid-line" "$(T --pane-file "$TMP/fp-cap-prose.txt" 2>/dev/null | jq -r '.state')" healthy
ok "control: that pane DOES contain the banner words (so the check is not vacuous)" \
   "$(grep -q "You've hit your session limit" "$TMP/fp-cap-prose.txt" && echo yes || echo no)" yes

# the WEEKLY wording is the other half of the same banner, and it is the one that
# costs days rather than hours, so it is asserted rather than assumed.
printf ' \xe2\x9a\xa0 You'"'"'ve hit your weekly limit \xc2\xb7 resets Monday\n\n bypass permissions on (shift+tab to cycle) - ? for shortcuts\n' > "$TMP/cap-weekly.txt"
ok "a WEEKLY cap classifies as usage-cap too" "$(T --pane-file "$TMP/cap-weekly.txt" 2>/dev/null | jq -r '.state')" usage-cap

# ⚠️ ORDER AGAINST THE FIRST-RUN SELECTORS, not just against healthy. A capped pane
# still shows whatever the agent was doing when its window closed - here, a `cat` of
# the scroll fixture, whose option lines the selector signature admits because only
# decoration precedes them. Classified as a first-run selector, a capped agent gets
# an answer to a prompt that is not there and stays capped. The reverse can't
# happen: a first-run selector only appears just after a login, when there is no cap
# banner. The control is DERIVED, not hand-copied: the same pane without the banner
# line must read `scroll-prompt`, so the assertion measures the ORDER on the
# classifier itself - a pane the selector signature did not match would make the
# first row pass vacuously.
{ printf ' \xe2\x9a\xa0 You'"'"'ve hit your session limit \xc2\xb7 resets 10pm\n\n'
  sed 's/^/  /' "$F/scroll-prompt.txt"
  printf '\n bypass permissions on (shift+tab to cycle) - ? for shortcuts\n'
} > "$TMP/cap-plus-scroll-selector.txt"
grep -v "You've hit your" "$TMP/cap-plus-scroll-selector.txt" > "$TMP/scroll-selector-no-cap.txt"
ok "a capped pane whose scrollback shows the scroll selector's lines is still usage-cap" \
   "$(T --pane-file "$TMP/cap-plus-scroll-selector.txt" 2>/dev/null | jq -r '.state')" usage-cap
ok "control: the SAME pane without the banner reads scroll-prompt (so the order is what decides)" \
   "$(T --pane-file "$TMP/scroll-selector-no-cap.txt" 2>/dev/null | jq -r '.state')" scroll-prompt

# ⚠️ THE LIMIT NAME IS A SHAPE, NOT A LIST. The banner is built as "You've hit your
# <limit name> limit" and the name varies with the plan and the model, so a
# classifier enumerating the names we know today goes stale as a false NEGATIVE:
# the agent sits capped and reads `healthy`. A model-scoped name is the case that
# an enumeration of session/weekly misses.
printf ' \xe2\x9a\xa0 You'"'"'ve hit your Opus limit \xc2\xb7 resets Monday\n\n bypass permissions on (shift+tab to cycle) - ? for shortcuts\n' > "$TMP/cap-model.txt"
ok "a MODEL-scoped cap classifies as usage-cap (the name is not enumerated)" \
   "$(T --pane-file "$TMP/cap-model.txt" 2>/dev/null | jq -r '.state')" usage-cap
printf ' \xe2\x9a\xa0 You'"'"'ve hit your monthly spend limit\n\n bypass permissions on (shift+tab to cycle) - ? for shortcuts\n' > "$TMP/cap-spend.txt"
ok "a SPEND cap classifies as usage-cap too" \
   "$(T --pane-file "$TMP/cap-spend.txt" 2>/dev/null | jq -r '.state')" usage-cap

# ⚠️ A SESSION TAKING A TURN IS NOT CAPPED, whatever its transcript says. A pane
# that hit a cap, recovered and went back to work still carries the banner in its
# scrollback; classified `usage-cap`, the charter duty types /login into it and
# blocks a working session on a sign-in nobody needed. Both busy markers are pinned
# here because each is the only evidence in its own layout: the interrupt hint, and
# the agent-tree view, which REPLACES the status bar so a working session showed no
# healthy signature at all and read as `unknown`.
printf ' \xe2\x9a\xa0 You'"'"'ve hit your session limit \xc2\xb7 resets 10pm\n \xe2\x8f\xba Refactoring the normaliser (3m 12s \xc2\xb7 esc to interrupt)\n' > "$TMP/cap-then-working.txt"
ok "a capped pane that went BACK TO WORK is 'working', not 'usage-cap'" \
   "$(T --pane-file "$TMP/cap-then-working.txt" 2>/dev/null | jq -r '.state')" working
ok "control: that pane DOES carry the banner (so the busy marker is what decides)" \
   "$(grep -q "You've hit your session limit" "$TMP/cap-then-working.txt" && echo yes || echo no)" yes

# ⚠️ THE MARKERS ARE READ IN THE TAIL ONLY. This skill and both charters quote
# `esc to interrupt` and the tree rows verbatim, so an agent working ON this file
# has them in its transcript - and read anywhere on the pane, a real cap on that
# agent would be suppressed. A false NEGATIVE is the expensive direction here.
{ printf ' > The healthy branch also matches "esc to interrupt" on the pane.\n'
  printf ' > A tree row reads "12m 03s" beside a running subagent.\n'
  for i in 1 2 3 4 5 6 7; do printf ' \xe2\x8f\xba step %s of the edit\n' "$i"; done
  printf '\n \xe2\x9a\xa0 You'"'"'ve hit your session limit \xc2\xb7 resets 10pm\n\n bypass permissions on - ? for shortcuts\n'
} > "$TMP/cap-quoting-busy.txt"
ok "a cap is NOT suppressed by the busy marker appearing in the TRANSCRIPT" \
   "$(T --pane-file "$TMP/cap-quoting-busy.txt" 2>/dev/null | jq -r '.state')" usage-cap
ok "control: that pane DOES quote both busy markers, above the tail" \
   "$(grep -q 'esc to interrupt' "$TMP/cap-quoting-busy.txt" && grep -q '12m 03s' "$TMP/cap-quoting-busy.txt" && echo yes || echo no)" yes

# ── the agents panel in MANAGE mode ────────────────────────────────────────────
# ⚠️ THIS LAYOUT IS THE SECOND WAY A WORKING SESSION SHOWS NO STATUS BAR AT ALL,
# and it was measured classifying `unknown` on a live agent mid-task while an
# hourly liveness sweep was reading it. The panel REPLACES the prompt: a
# `↑/↓ to select` header, a row per agent, a `↓ N more` footer when the list is
# clipped. No status bar, no banner, no sign-in text - so every positive signature
# in the classifier misses it and the sweep reports a hard-working agent as a pane
# nobody could interpret. The cost of that is not noise: `unknown` is what sends a
# human to read a pane by hand, so the state that means "leave this agent alone"
# arrives as the state that means "someone go look".
#
# THE MUTATION CONTROL BELOW IS LOAD-BEARING AND MUST NOT BE REMOVED FOR TIDINESS.
# The positive case above proves the fixture reads `working`; it does NOT prove the
# new marker is what makes it so. A classifier that grew any other reason to call
# this pane `working` would keep that case green while the marker rotted. So this
# disables the marker's contribution to `busy` in a COPY of the real script and
# requires the fixture to fall back to exactly the reading it had before the marker
# existed - `unknown`, reproduced on the unfixed script. Two controls guard the
# mutation itself: that the condition really was disabled in the copy, and that the
# DETECTION was left intact, so a sed that merely deleted the code could not pass
# for a sed that disabled the branch.
sed -E 's/^if \[ "\$agents_panel" = yes \]; then$/if false; then/' \
    "$HERE/tmux_triage.sh" > "$TMP/no-manage-branch.sh"
ok "control: the real script has exactly one agents-panel busy condition to disable" \
   "$(grep -cE '^if \[ "\$agents_panel" = yes \]; then$' "$HERE/tmux_triage.sh" | tr -d ' ')" 1
ok "control: the mutation actually applied (no such condition left in the copy)" \
   "$(grep -cE '^if \[ "\$agents_panel" = yes \]; then$' "$TMP/no-manage-branch.sh" | tr -d ' ')" 0
ok "control: the mutation disabled the branch rather than deleting the detection" \
   "$(grep -c 'agents_panel=yes' "$TMP/no-manage-branch.sh" | tr -d ' ')" 1
ok "control: with the agents-panel marker disabled the fixture reads 'unknown' again" \
   "$(bash "$TMP/no-manage-branch.sh" testagent --config "$CFG" --pane-file "$F/agent-manage-panel.txt" 2>/dev/null | jq -r '.state')" unknown

# ⚠️ BOTH HALVES OF THE MARKER ARE REQUIRED. SKILL.md and this script now quote the
# header verbatim, so a header-only signature would classify an agent READING this
# skill as `working` - and `working` SUPPRESSES nothing loudly: it is the state that
# says leave the agent alone, so a false positive hides whatever the pane really
# shows. A running timer on an agent row is what separates the panel from prose
# about the panel.
cat > "$TMP/panel-header-only.txt" <<'PANE'
 ↑/↓ to select · Enter to view

 bypass permissions on (shift+tab to cycle) · ? for shortcuts
PANE
ok "NOT working: the panel header with no agent row carrying a timer" \
   "$(T --pane-file "$TMP/panel-header-only.txt" 2>/dev/null | jq -r '.state')" healthy
ok "control: that pane DOES carry the header at the start of a line (so the row half is what decides)" \
   "$(grep -qE '^[[:space:]]*↑/↓ to select' "$TMP/panel-header-only.txt" && echo yes || echo no)" yes

# ⚠️ THE OTHER HALF, AND IT ALSO PINS THAT THE GLYPHS ARE MATCHED AS CHARACTERS
# RATHER THAN AS BYTES. Panel rows carry `❯` and `●`, which the agent-tree marker
# does not accept - it wants a box-drawing glyph. Written as a bracket set of
# multibyte characters, that marker is a set of BYTES in the C locale (the locale a
# service unit and this test both run under) and matches the lead byte 0xE2 shared
# by ❯ ⚠ · ↓ ⏺, so this pane read `working` off the TREE marker with no tree on it.
# Measured: it made the mutation control below unfalsifiable, because a second
# marker was silently answering for the first. A false `busy` also suppresses
# `usage-cap`, so the blast radius is the capped agent nobody revives.
cat > "$TMP/panel-rows-only.txt" <<'PANE'
 ❯ ● main
   ◯ software-engineer       Grepping imports in text-utils.ts     1h 26m 55s · ↓ 269.4k tokens

 bypass permissions on (shift+tab to cycle) · ? for shortcuts
PANE
ok "NOT working: panel rows with a running timer but no panel header" \
   "$(T --pane-file "$TMP/panel-rows-only.txt" 2>/dev/null | jq -r '.state')" healthy
ok "control: that pane DOES carry a row glyph and a running timer (so the header half is what decides)" \
   "$(grep -qE '(◯|●).*[0-9]+[hms] [0-9]+[ms]' "$TMP/panel-rows-only.txt" && echo yes || echo no)" yes

# ⚠️ THE PANEL IS THE ONE BUSY MARKER THAT MAY NOT SUPPRESS A CAP. The interrupt
# hint and the agent-tree row are drawn BY a turn in flight; the panel is a VIEW,
# and it stays on screen whether or not the session is still taking turns. Read as
# `working`, a capped agent showing an open panel is left parked for hours on a
# session cap and DAYS on a weekly one, which is the exact silence usage-cap exists
# to break. The control is DERIVED rather than hand-copied: the same pane with the
# banner line removed must read `working`, so the assertion measures the guard on
# the classifier itself instead of restating what the pane contains.
cat > "$TMP/cap-plus-panel.txt" <<'PANE'
 ⚠ You've hit your session limit · resets 10pm

 ↑/↓ to select · Enter to view

 ❯ ● main
   ◯ software-engineer       Grepping imports in text-utils.ts     1h 26m 55s · ↓ 269.4k tokens
   ↓ 3 more
PANE
grep -v "You've hit your" "$TMP/cap-plus-panel.txt" > "$TMP/panel-no-cap.txt"
ok "a cap banner under an open agents panel is still usage-cap, not working" \
   "$(T --pane-file "$TMP/cap-plus-panel.txt" 2>/dev/null | jq -r '.state')" usage-cap
ok "control: the SAME pane without the banner reads working (so the cap guard is what decides)" \
   "$(T --pane-file "$TMP/panel-no-cap.txt" 2>/dev/null | jq -r '.state')" working

# The sign-in half of that guard is asserted as a STATEMENT, not as an effect, and
# the distinction is the point. Branch order already sends a pane carrying a code
# prompt to `signin-url` before the `working` branch is ever reached, so a
# behavioural case here would pass with the guard deleted and could never see it go.
# The case below therefore pins the ORDER (worth pinning on its own: move `working`
# above `signin-url` and it reds), and the grep pins the RULE - that the two markers
# read from the wide `panel_window` (the agents panel and the live spinner) refuse
# to fire while the session is waiting for a code, whatever the classifier is
# reordered into later. The count is 2 because there are exactly those two; a third
# wide-window marker owes the same guard and moves this number in the same commit.
cat > "$TMP/panel-plus-signin.txt" <<'PANE'
 Paste code here if prompted > 

 ↑/↓ to select · Enter to view

 ❯ ● main
   ◯ software-engineer       Grepping imports in text-utils.ts     1h 26m 55s · ↓ 269.4k tokens
PANE
ok "a code prompt under an open agents panel is signin-url (branch order)" \
   "$(T --pane-file "$TMP/panel-plus-signin.txt" 2>/dev/null | jq -r '.state')" signin-url
ok "the agents-panel and spinner markers themselves refuse to fire while a code prompt is up (the rule, not its effect)" \
   "$(grep -c '\[ "\$signin_prompt" = no \]' "$HERE/tmux_triage.sh" | tr -d ' ')" 2

# ── a WORKING pane whose transcript talks about scrolling ─────────────────────
# ⚠️ MEASURED ON A LIVE AGENT, AND THE FALSE POSITIVE IS DESTRUCTIVE.
# fixtures/working-panel-scroll-prose.txt is SYNTHETIC: invented transcript text in
# the layout of the live pane that showed the defect. Its transcript reports on a
# scrolling bug ("scrolls", "mouse wheel", "wheel-scrolling"), and under its prompt
# the agents panel is listed with a subagent whose timer is running. The classifier
# matched `scroll` + `wheel|arrow|mouse` anywhere on the pane and returned
# `scroll-prompt`, whose note tells an operator to TYPE an option into the pane -
# into a live session. The fixture must keep reproducing that: with the panel marker
# disabled and the old word match restored, it reads `scroll-prompt`. Two defects
# made that possible, and each has its own row:
#   - the agents panel LISTED under the prompt was not a busy marker, and it pushes
#     the status bar (and its interrupt hint) out of the six-line tail;
#   - the scroll selector was matched by words, not by its own option lines.
ok "a working pane (agents panel under the prompt) whose transcript discusses scrolling is working" \
   "$(state_of working-panel-scroll-prose.txt)" working
ok "control: that pane DOES carry the words the old loose scroll signature matched" \
   "$(grep -qi 'scroll' "$F/working-panel-scroll-prose.txt" && grep -qiE 'wheel|arrow|mouse' "$F/working-panel-scroll-prose.txt" && echo yes || echo no)" yes
# ⚠️ MUTATION CONTROL, LOAD-BEARING: with the agents-panel marker disabled (the copy
# built above), the pane must fall to `healthy` - its ready status bar - and NOT
# to `scroll-prompt`. This is the row that pins the selector signature against this
# prose independently of branch order: were `working` ever reordered below the
# selectors, or the panel marker narrowed, the selector must still not fire.
ok "control: with the agents-panel marker disabled the pane reads healthy, never scroll-prompt" \
   "$(bash "$TMP/no-manage-branch.sh" testagent --config "$CFG" --pane-file "$F/working-panel-scroll-prose.txt" 2>/dev/null | jq -r '.state')" healthy
# ⚠️ AND THE FIXTURE MUST STILL BE THE CASE IT IS NAMED FOR. Being synthetic, it can
# drift into a pane the old defect never misread - its scroll prose softened, its
# panel redrawn - and every row above would stay green over a fixture that no longer
# exercises anything. So the defect is put back in a copy: the panel marker disabled
# (the copy above) AND the scroll selector's option-line condition replaced by the
# word match the live pane was misread by. On that copy the fixture must read
# `scroll-prompt`. Remove this row and the fixture can be rewritten into a pane that
# proves nothing, with nothing red.
LOOSE_SCROLL='elif grep -qi scroll <<<"$pane" && grep -qiE "wheel|arrow|mouse" <<<"$pane" && : \' \
  awk 'index($0, "elif adjacent_options \"$pane\" \"${opt_prefix}Send up/down arrow keys") == 1 { print ENVIRON["LOOSE_SCROLL"]; next } { print }' \
  "$TMP/no-manage-branch.sh" > "$TMP/loose-scroll.sh"
ok "control: the copy carries the old word match in place of the scroll selector's option-line condition" \
   "$(grep -c '^elif grep -qi scroll' "$TMP/loose-scroll.sh" | tr -d ' '):$(grep -c 'Send up/down arrow keys\[' "$TMP/loose-scroll.sh" | tr -d ' ')" "1:0"
ok "the fixture is still the defect's case: panel marker off and the old word match back, it reads scroll-prompt" \
   "$(bash "$TMP/loose-scroll.sh" testagent --config "$CFG" --pane-file "$F/working-panel-scroll-prose.txt" 2>/dev/null | jq -r '.state')" scroll-prompt
# The footer half of the LIST-mode panel is required: without `· ↓ to manage` at
# the end of the status bar, glyph rows with a timer are just lines - a `cat` of a
# panel capture is exactly that. Derived from the fixture, so it measures that the
# footer is what decides on the full layout rather than on a stripped-down pane.
sed 's/ · ↓ to manage[[:space:]]*$//' "$F/working-panel-scroll-prose.txt" > "$TMP/panel-list-no-footer.txt"
ok "NOT working: the listed panel's rows without the status bar's '↓ to manage' footer" \
   "$(T --pane-file "$TMP/panel-list-no-footer.txt" 2>/dev/null | jq -r '.state')" healthy
ok "control: the footer removal actually applied (so the footer half is what decides)" \
   "$(grep -c '↓ to manage' "$TMP/panel-list-no-footer.txt" | tr -d ' ')" 0

# ⚠️ THE LIVE SPINNER IS A BUSY MARKER. The reported pane (not recaptured - the
# session had moved on) carried `· Scurrying… (19s · ↓ 691 tokens)` just above the
# prompt box; this row SYNTHESIZES it into the fixture with the panel footer
# stripped, so the spinner is the only busy evidence left. The control is the same
# pane without the spinner line, and it must read `healthy` - which also proves the
# lines a FINISHED turn leaves behind (`✻ Waiting for 1 background agent to finish`
# is in this fixture) are not read as a spinner.
awk '/Update installed/ { print "· Scurrying… (19s · ↓ 691 tokens)" } { print }' \
    "$TMP/panel-list-no-footer.txt" > "$TMP/spinner-no-panel.txt"
ok "a live spinner above the prompt box is working, with no panel marker to help" \
   "$(T --pane-file "$TMP/spinner-no-panel.txt" 2>/dev/null | jq -r '.state')" working
ok "control: the spinner line was actually inserted" \
   "$(grep -c 'Scurrying… (19s' "$TMP/spinner-no-panel.txt" | tr -d ' ')" 1
ok "control: the same pane without the spinner reads healthy (so the spinner is what decides)" \
   "$(T --pane-file "$TMP/panel-list-no-footer.txt" 2>/dev/null | jq -r '.state')" healthy
ok "control: that pane DOES carry a finished-turn line the spinner match must not take" \
   "$(grep -c 'Waiting for 1 background agent to finish' "$TMP/panel-list-no-footer.txt" | tr -d ' ')" 1

# ── the first-run selectors, by their own lines ──────────────────────────────
# The positive fixture (fixtures/scroll-prompt.txt) is SYNTHESIZED: the scroll
# selector's wording is not in the Claude Code 2.1.281 binary, so no capture
# exists. Option order is not guaranteed (SKILL.md step 9), so the reversed order
# is asserted too.
{ printf ' Choose how the mouse wheel behaves in this terminal:\n\n'
  printf ' \xe2\x9d\xaf Send up/down arrow keys\n   Scroll the terminal (recommended)\n'
} > "$TMP/scroll-reversed.txt"
ok "scroll selector with its options in the other order" \
   "$(T --pane-file "$TMP/scroll-reversed.txt" 2>/dev/null | jq -r '.state')" scroll-prompt
# MUTATION CONTROL: neuter the arrow-keys option in the live pattern of a COPY; the
# fixture must then fall back to `unknown` (it carries no status bar), so the option
# lines - not some other signature - are what classify it.
sed 's#Send up/down arrow keys\[#NEVER-MATCHES-THIS-SENTINEL[#' \
    "$HERE/tmux_triage.sh" > "$TMP/no-scroll-pattern.sh"
ok "control: the mutation actually applied (the live scroll pattern is neutered in the copy)" \
   "$(grep -c 'NEVER-MATCHES-THIS-SENTINEL' "$TMP/no-scroll-pattern.sh" | tr -d ' ')" 1
ok "control: with the scroll pattern neutered the fixture reads unknown" \
   "$(bash "$TMP/no-scroll-pattern.sh" testagent --config "$CFG" --pane-file "$F/scroll-prompt.txt" 2>/dev/null | jq -r '.state')" unknown
# The pickers draw NUMBERED options, as the login-method menu does. The theme pane
# below follows the 2.1.281 binary's option order and labels; the scroll one is the
# synthesized fixture's wording with numbers added.
cat > "$TMP/theme-numbered.txt" <<'PANE'
 Let's get started.

 Choose the text style that looks best with your terminal

 ❯ 1. Auto (match terminal)
   2. Dark mode ✔
   3. Light mode
   4. Dark mode (colorblind-friendly)
   5. Light mode (colorblind-friendly)
   6. Dark mode (ANSI colors only)
   7. Light mode (ANSI colors only)

 Enter to select · Esc to cancel
PANE
ok "theme selector with numbered options (the binary's layout)" \
   "$(T --pane-file "$TMP/theme-numbered.txt" 2>/dev/null | jq -r '.state')" theme-prompt
printf ' Choose how the mouse wheel behaves in this terminal:\n\n \xe2\x9d\xaf 1. Scroll the terminal (recommended)\n   2. Send up/down arrow keys\n\n Enter to confirm\n' > "$TMP/scroll-numbered.txt"
ok "scroll selector with numbered options" \
   "$(T --pane-file "$TMP/scroll-numbered.txt" 2>/dev/null | jq -r '.state')" scroll-prompt
# ⚠️ ADJACENCY MEANS A DIFFERENT LINE. One option line on its own - a markdown
# bullet in a transcript - must not satisfy "two adjacent option lines" by standing
# in as its own neighbour.
printf '   - Dark mode (colorblind-friendly)\n\n bypass permissions on (shift+tab to cycle) - ? for shortcuts\n' > "$TMP/fp-theme-lone-option.txt"
ok "NOT a theme selector: one colour-blind option line on its own" \
   "$(T --pane-file "$TMP/fp-theme-lone-option.txt" 2>/dev/null | jq -r '.state')" healthy
printf '   - Send up/down arrow keys\n\n bypass permissions on (shift+tab to cycle) - ? for shortcuts\n' > "$TMP/fp-scroll-lone-option.txt"
ok "NOT a scroll selector: the arrow-keys option line on its own" \
   "$(T --pane-file "$TMP/fp-scroll-lone-option.txt" 2>/dev/null | jq -r '.state')" healthy
# REGIME CONTROLS: prose quoting the options mid-line, and prose about themes, are
# not selectors. Both notes tell an operator to type into the pane.
printf ' > The selector offers "Scroll the terminal (recommended)" and "Send up/down arrow keys".\n\n bypass permissions on (shift+tab to cycle) - ? for shortcuts\n' > "$TMP/fp-scroll-prose.txt"
ok "NOT a scroll selector: prose quoting both options mid-line" \
   "$(T --pane-file "$TMP/fp-scroll-prose.txt" 2>/dev/null | jq -r '.state')" healthy
printf ' > The setup guide suggests Dark mode (colorblind-friendly) for screenshots.\n\n bypass permissions on (shift+tab to cycle) - ? for shortcuts\n' > "$TMP/fp-theme-prose.txt"
ok "NOT a theme selector: prose naming the colour-blind dark theme" \
   "$(T --pane-file "$TMP/fp-theme-prose.txt" 2>/dev/null | jq -r '.state')" healthy

# ⚠️ THE LIST-MODE ROWS ARE READ ONLY BELOW THE FOOTER. The footer is on screen
# whenever any background task runs (a Monitor is enough), and `●` is also the
# bullet on every assistant message - so an idle session whose last message names a
# duration must not read `working` off its own transcript above the status bar.
cat > "$TMP/idle-footer-bullet-duration.txt" <<'PANE'
● Full e2e suite green in 12m 40s; nothing left for me.

✻ Worked for 13m 2s
─────────────────────────────────────────────────────────────── acme-corp-agent-x ─
❯ 
───────────────────────────────────────────────────────────────────────────────────
  ⏵⏵ bypass permissions on · 1 monitor · ← for agents · ↓ to manage
PANE
ok "NOT working: an idle pane whose transcript bullet names a duration, above a '↓ to manage' status bar" \
   "$(T --pane-file "$TMP/idle-footer-bullet-duration.txt" 2>/dev/null | jq -r '.state')" healthy
ok "control: that pane DOES carry a glyph line with a duration AND the footer (so row position is what decides)" \
   "$(grep -qE '^[^[:alnum:]]*(◯|◉|●|○).*[0-9]+[hms] [0-9]+[ms]' "$TMP/idle-footer-bullet-duration.txt" && grep -q '↓ to manage' "$TMP/idle-footer-bullet-duration.txt" && echo yes || echo no)" yes

# ⚠️ THE SPINNER MAY NOT SUPPRESS A CAP. It is read from the wide window, which
# reads more transcript than the tail, so it carries the panel's cap guard. The
# control is derived: the same pane without the banner must read `working`, so the
# row cannot pass because the spinner simply failed to match.
{ printf ' \xe2\x9a\xa0 You'"'"'ve hit your session limit \xc2\xb7 resets 10pm\n\n'
  printf '· Scurrying… (19s · ↓ 691 tokens)\n'
  printf ' bypass permissions on (shift+tab to cycle) - ? for shortcuts\n'
} > "$TMP/cap-plus-spinner.txt"
grep -v "You've hit your" "$TMP/cap-plus-spinner.txt" > "$TMP/spinner-no-cap.txt"
ok "a cap banner over a live-looking spinner line is still usage-cap, not working" \
   "$(T --pane-file "$TMP/cap-plus-spinner.txt" 2>/dev/null | jq -r '.state')" usage-cap
ok "control: the SAME pane without the banner reads working (so the cap guard is what decides)" \
   "$(T --pane-file "$TMP/spinner-no-cap.txt" 2>/dev/null | jq -r '.state')" working

# ── the session-rating survey ─────────────────────────────────────────────────
# ⚠️ THIS IS AN IDLE STATE, AND `unknown` IS THE EXPENSIVE READING FOR IT. `unknown`
# is what sends a person to read a pane by hand, so without this state a prompt whose
# entire meaning is "this agent is fine, press 0" arrives on the hourly sweep as
# "someone go look at this agent" - repeatedly, and for an agent with nothing wrong
# with it.
#
# The fixture is the real rendering: a cyan bullet, the message
# "...doing this session? (optional)", then a row of `<key>: <label>` cells at
# marginLeft 2, over a ready prompt. It is reconstructed from the strings in the
# Claude Code binary rather than from a capture, so the SHAPE is pinned here and the
# exact spacing is not asserted anywhere.
ok "session-rating survey over a ready prompt" "$(state_of survey-prompt.txt)" survey-prompt

# control on the control, the twin of the status-modal one: the survey is drawn OVER
# a live session, so its pane also carries the ready status bar and the ordering is
# the only thing that stops it reading `healthy`.
ok "control: the survey pane DOES carry a ready status bar (so order matters)" \
   "$(grep -qiE 'bypass permissions|for shortcuts' "$F/survey-prompt.txt" && echo yes || echo no)" yes

# ⚠️ MUTATION CONTROL, LOAD-BEARING. The positive case proves the fixture reads
# `survey-prompt`; it does NOT prove this branch is what makes it so. Disabling the
# branch in a COPY of the real script must send the fixture to the reading it gets
# without the branch. Two controls guard the mutation itself, so a sed
# that silently matched nothing could not pass for one that disabled the branch.
sed 's/How is Claude doing this session/NEVER-MATCHES-THIS-SENTINEL/g' \
    "$HERE/tmux_triage.sh" > "$TMP/no-survey-branch.sh"
ok "control: the real script matches the question in exactly one live PATTERN" \
   "$(grep -cE '^elif grep -A1 -E .*How is Claude doing this session' "$HERE/tmux_triage.sh" | tr -d ' ')" 1
ok "control: the mutation actually applied (no live pattern matches the question in the copy)" \
   "$(grep -c 'How is Claude doing this session' "$TMP/no-survey-branch.sh" | tr -d ' ')" 0
ok "control: the mutation neutered the PATTERN and left the branch standing" \
   "$(grep -c 'state=\"survey-prompt\"' "$TMP/no-survey-branch.sh" | tr -d ' ')" 1
ok "control: with the survey pattern neutered the fixture falls back to healthy" \
   "$(bash "$TMP/no-survey-branch.sh" testagent --config "$CFG" --pane-file "$F/survey-prompt.txt" 2>/dev/null | jq -r '.state')" healthy

# ⚠️ REGIME CONTROL, the twin of status-modal's and usage-cap's: it must fire on the
# PROMPT, not on the WORDS. SKILL.md, the script and this file all quote both strings
# verbatim, so a substring match classifies an agent READING them as surveyed - and
# `survey-prompt` says "this agent is fine", which SUPPRESSES whatever the pane
# really shows. Anchoring the QUESTION is what separates the two: prose puts words in
# front of it, the real pane puts only decoration there.
printf ' > The "How is Claude doing this session?" prompt offers 1: Bad 2: Fine 3: Good 0: Dismiss.\n\n bypass permissions on (shift+tab to cycle) - ? for shortcuts\n' > "$TMP/fp-survey-prose.txt"
ok "NOT a survey: prose quoting the question mid-line" \
   "$(T --pane-file "$TMP/fp-survey-prose.txt" 2>/dev/null | jq -r '.state')" healthy
ok "control: that pane DOES contain both survey strings (so the check is not vacuous)" \
   "$(grep -q 'How is Claude doing this session' "$TMP/fp-survey-prose.txt" && grep -q '0: Dismiss' "$TMP/fp-survey-prose.txt" && echo yes || echo no)" yes

# ⚠️ ANCHORING THE QUESTION ALONE WAS NOT ENOUGH, AND THESE TWO CASES ARE WHY. Both
# were measured firing on prose against the first version of this signature, and
# neither is preventable by being careful about how this tree writes its comments:
#   - A WRAPPED PANE. tmux emits a continuation at column 0, so prose about the
#     prompt that happens to wrap onto the question starts a line with an EMPTY
#     prefix. Pane width decides this, not the author.
#   - A MARKDOWN BULLET or blockquote: `-`, space and `"` are all non-alphanumeric,
#     which the decoration class admits.
# The fix is the pair of RENDERED lines, adjacent, with the question's own
# "(optional)" suffix - a shape prose does not reproduce. This matters more than an
# ordinary false positive because this state's note tells an operator to TYPE into
# the pane, and SKILL.md itself carries the question and `0: Dismiss` in order.
printf 'the sweep was reading a note about\nHow is Claude doing this session? and 0: Dismiss dismisses it\n\n bypass permissions on (shift+tab to cycle) - ? for shortcuts\n' > "$TMP/fp-survey-wrapped.txt"
ok "NOT a survey: a WRAPPED line putting the question at column 0" \
   "$(T --pane-file "$TMP/fp-survey-wrapped.txt" 2>/dev/null | jq -r '.state')" healthy
ok "control: that pane DOES start a line with the question (so the anchor alone would have fired)" \
   "$(grep -cE '^How is Claude doing this session' "$TMP/fp-survey-wrapped.txt" | tr -d ' ')" 1
printf ' - "How is Claude doing this session?" offers 1: Bad 2: Fine 3: Good 0: Dismiss\n\n bypass permissions on (shift+tab to cycle) - ? for shortcuts\n' > "$TMP/fp-survey-bullet.txt"
ok "NOT a survey: a markdown BULLET quoting the whole prompt" \
   "$(T --pane-file "$TMP/fp-survey-bullet.txt" 2>/dev/null | jq -r '.state')" healthy
ok "control: that pane's decoration IS all non-alphanumeric before the question (so the anchor alone would have fired)" \
   "$(grep -cE '^[[:space:]]*[^[:alnum:]]*[[:space:]]*How is Claude doing this session' "$TMP/fp-survey-bullet.txt" | tr -d ' ')" 1

# ⚠️ AND THE `(optional)` SUFFIX IS LOAD-BEARING, not decoration on the pattern:
# without it the wrapped case above fires. Pinned as a DERIVED case - the real
# fixture with just that suffix removed must stop classifying.
sed 's/ (optional)//' "$F/survey-prompt.txt" > "$TMP/survey-no-optional.txt"
ok "control: the suffix is what the wrapped case turns on (fixture minus '(optional)' no longer classifies)" \
   "$(T --pane-file "$TMP/survey-no-optional.txt" 2>/dev/null | jq -r '.state')" healthy

# ⚠️ AND THE TWO LINES MUST BE ADJACENT. Derived the same way: the real fixture with
# one blank line inserted between them must stop classifying, which is what stops a
# question in one part of a pane pairing with an options row somewhere else on it.
awk '/How is Claude doing this session/ {print; print ""; next} {print}' "$F/survey-prompt.txt" > "$TMP/survey-split.txt"
ok "control: the two lines must be ADJACENT (a blank line between them stops it)" \
   "$(T --pane-file "$TMP/survey-split.txt" 2>/dev/null | jq -r '.state')" healthy

# ⚠️ AND THE SURVEY MAY NOT SUPPRESS THE TWO STATES THAT COST HOURS OR DAYS. It is a
# prompt drawn over whatever the session was showing, so a capped agent or one
# waiting on a code can carry it too - and reading either as "fine, press 0" is the
# silence the sweep exists to break. Both controls are DERIVED: the same pane with
# the cap line (or the code prompt) removed must read `survey-prompt`, so the
# assertion measures the branch ORDER on the classifier rather than restating what
# the pane contains.
{ printf ' \xe2\x9a\xa0 You'"'"'ve hit your session limit \xc2\xb7 resets 10pm\n\n'
  cat "$F/survey-prompt.txt"; } > "$TMP/survey-plus-cap.txt"
grep -v "You've hit your" "$TMP/survey-plus-cap.txt" > "$TMP/survey-no-cap.txt"
ok "a cap banner under a survey prompt is still usage-cap" \
   "$(T --pane-file "$TMP/survey-plus-cap.txt" 2>/dev/null | jq -r '.state')" usage-cap
ok "control: the SAME pane without the banner reads survey-prompt (so the order is what decides)" \
   "$(T --pane-file "$TMP/survey-no-cap.txt" 2>/dev/null | jq -r '.state')" survey-prompt
{ printf ' Paste code here if prompted > \n\n'; cat "$F/survey-prompt.txt"; } > "$TMP/survey-plus-signin.txt"
grep -v 'Paste code here' "$TMP/survey-plus-signin.txt" > "$TMP/survey-no-signin.txt"
ok "a code prompt under a survey prompt is still signin-url" \
   "$(T --pane-file "$TMP/survey-plus-signin.txt" 2>/dev/null | jq -r '.state')" signin-url
ok "control: the SAME pane without the code prompt reads survey-prompt" \
   "$(T --pane-file "$TMP/survey-no-signin.txt" 2>/dev/null | jq -r '.state')" survey-prompt

# the note is the operator's whole instruction at this state, and the two halves that
# matter are that it is idle (so nothing is revived) and that 0 dismisses it.
survey_note="$(T --pane-file "$F/survey-prompt.txt" 2>/dev/null | jq -r '.note')"
ok "survey note says the state is IDLE, not a revival case" \
   "$(grep -q 'IDLE state, not a revival case' <<<"$survey_note" && echo yes || echo no)" yes
ok "survey note says 0 dismisses it" "$(grep -q 'Send 0 (Dismiss)' <<<"$survey_note" && echo yes || echo no)" yes

# ── every run emits ONE JSON object and nothing else ──────────────────────────
# ⚠️ THE PANE NEVER GOES TO STDERR RAW ON `unknown`: a merged-stream caller - which
# is what a tool call is by default - would see a screen of terminal decoration where
# it expects an object and read the SCRIPT as broken rather than the STATE as new.
# The pane is the useful half of an `unknown`, so it is carried in the object instead
# of dropped. Both halves are asserted: stderr holds no pane, and `pane` holds it.
printf ' just some log output\n nothing to see here\n' > "$TMP/unknown-pane.txt"
unk_both="$(T --pane-file "$TMP/unknown-pane.txt" 2>&1)"
ok "unknown: the MERGED stream is still parseable as one JSON object" \
   "$(jq -er '.state' <<<"$unk_both" 2>/dev/null || echo PARSE-FAILED)" unknown
ok "unknown: the captured pane comes back in the 'pane' field" \
   "$(T --pane-file "$TMP/unknown-pane.txt" 2>/dev/null | jq -r '.pane' | grep -c 'nothing to see here' | tr -d ' ')" 1
ok "pane is EMPTY for a state that is not unknown" \
   "$(T --pane-file "$F/healthy-pane.txt" 2>/dev/null | jq -r '.pane')" ""

# ── <agent> must be an agent name ─────────────────────────────────────────────
# ⚠️ The name is spliced into a sed program and joined into the agent's home path,
# so anything outside bin/fleet's agent-name pattern (`[a-z0-9][a-z0-9_-]*`) is
# refused as a usage error before it is used - a `/` breaks out of the sed
# expression, a `..` out of the agents root. Each refused name runs the pane-file
# route, the cheapest one, so the refusal must come before any of it. The control
# is a valid name using every allowed character class, which must still classify:
# without it a script that refused EVERY name would pass the refusal rows.
for bad in 'a/b' '../x' 'Ada' 'a.b' 'a b'; do
  ok "the agent name '$bad' is refused (exit 2, no JSON)" \
     "$(bash "$HERE/tmux_triage.sh" "$bad" --config "$CFG" --pane-file "$F/healthy-pane.txt" 2>/dev/null; echo "exit $?")" "exit 2"
done
ok "control: a valid name with a digit, '-' and '_' still classifies" \
   "$(bash "$HERE/tmux_triage.sh" ada-2_x --config "$CFG" --pane-file "$F/healthy-pane.txt" 2>/dev/null | jq -r '.state')" healthy
ok "the refusal names the rule" \
   "$(bash "$HERE/tmux_triage.sh" 'a/b' --config "$CFG" --pane-file "$F/healthy-pane.txt" 2>&1 >/dev/null | grep -c '^not an agent name: ' | tr -d ' ')" 1

# ⚠️ AND EVERY STATE EMITS THE SAME KEYS. `unreachable` is emitted from its own jq
# call rather than the shared one at the end, so it silently drifted: it carried
# neither `banner` nor `pane` while every other state did. A caller reading
# `.banner` off it gets jq's `null`, which is not the empty string the other states
# give and is exactly the shape a naive `if` treats as present. One key set, asserted
# across both emit paths - the live route is taken for `unreachable` because UCFG
# names a tmux socket directory of this run's own, where no server runs.
keys_of() { jq -r 'keys|join(",")'; }
UT() { bash "$HERE/tmux_triage.sh" testagent --config "$UCFG" "$@"; }
want_keys="agent,auth,banner,daemons,daemons_expected,daemons_running,followers,followers_down,followers_expected,last_turn_error,logs_replaced,note,pane,signin_url,state"
ok "the shared emit path has the full key set" "$(T --pane-file "$F/healthy-pane.txt" 2>/dev/null | keys_of)" "$want_keys"
ok "unreachable (a SEPARATE emit path) has the SAME key set" "$(UT 2>/dev/null | keys_of)" "$want_keys"
unreach="$(UT 2>/dev/null)"
ok "control: that second call really did take the unreachable path" "$(jq -r '.state' <<<"$unreach")" unreachable
ok "unreachable names the socket directory it asked, this run's own" \
   "$(jq -r '.note' <<<"$unreach" | grep -cF " in $TMP/tm " | tr -d ' ')" 1
# The live route reached tmux, and tmux used that directory rather than falling back
# to /tmp: it made its tmux-<uid> there. Without tmux on the host there is no client,
# so nothing to leak and nothing to measure.
if command -v tmux >/dev/null 2>&1; then
  ok "the tmux client the live route ran made its socket directory under \$TMP, not in /tmp" \
     "$([ -d "$TMP/tm/tmux-$(id -u)" ] && echo yes || echo no)" yes
else
  echo "n/a  - no tmux on this host: the live route ran no tmux client"
fi

# ── daemon liveness: an idle pane with nothing running behind it ──────────────
# ⚠️ AN IDLE PROMPT WITH NO DAEMONS BEHIND IT IS INDISTINGUISHABLE FROM A QUIET HOUR
# BY PANE ALONE, and a fleet agent in that state read `healthy` on every hourly sweep
# for days: its last turn ended on an API error after its watches expired, nothing
# was left to wake it, and the classifier only ever looked at the pane. The reading
# is taken from the PROCESS TABLE, which this file injects through
# AGENT_REVIVE_PROC_ROOT as a fake /proc built under $TMP - so no live process is
# needed, and every case below says exactly which processes exist.
# The config is DERIVED from the base fixture config, through UCFG (one source for
# everything but the daemon list and the tmux socket directory), and the unit file
# names the config dir so the resolution takes the --unit-file route rather than
# adding a `systemctl cat` call to this file.
DCFG="$TMP/config.daemons.json"
jq '.fleet.daemons = [{"_comment": "documentation entry, skipped"},
                      {"name":"watch","pattern":"slack-communication/watch.py"},
                      {"name":"sched","pattern":"scheduled-tasks/sched.py"}]' "$UCFG" > "$DCFG"
AGENT_DIR="/nonexistent-fixture-home/testagent/.claude"
printf '[Service]\nEnvironment=CLAUDE_CONFIG_DIR=%s\n' "$AGENT_DIR" > "$TMP/agent.service"
# mkproc ROOT PID CONFIG_DIR ARG... - one fake process: NUL-separated argv and env.
mkproc() {
  local root="$1" pid="$2" cfgdir="$3"; shift 3
  mkdir -p "$root/$pid"
  printf '%s\0' "$@" > "$root/$pid/cmdline"
  printf 'HOME=/nonexistent\0CLAUDE_CONFIG_DIR=%s\0PATH=/usr/bin\0' "$cfgdir" > "$root/$pid/environ"
}
# NONE: the agent's own session and an unrelated process - no daemon at all.
mkproc "$TMP/p-none" 100 "$AGENT_DIR" claude --dangerously-skip-permissions
mkproc "$TMP/p-none" 101 "$AGENT_DIR" /bin/bash -lc 'tail -f /dev/null'
# BOTH: the same, plus both daemons, each under its shell wrapper as on a real host.
cp -r "$TMP/p-none" "$TMP/p-both"
mkproc "$TMP/p-both" 200 "$AGENT_DIR" /bin/bash -c 'python3 .claude/skills/slack-communication/watch.py 2>&1'
mkproc "$TMP/p-both" 201 "$AGENT_DIR" python3 .claude/skills/slack-communication/watch.py
mkproc "$TMP/p-both" 202 "$AGENT_DIR" python3 /x/.claude/skills/scheduled-tasks/sched.py
# PEER: both daemons run - but under ANOTHER agent's config dir.
cp -r "$TMP/p-none" "$TMP/p-peer"
mkproc "$TMP/p-peer" 300 "/nonexistent-fixture-home/peer/.claude" python3 .claude/skills/slack-communication/watch.py
mkproc "$TMP/p-peer" 301 "/nonexistent-fixture-home/peer/.claude" python3 .claude/skills/scheduled-tasks/sched.py
# ONE: only the scheduler runs for this agent.
cp -r "$TMP/p-none" "$TMP/p-one"
mkproc "$TMP/p-one" 400 "$AGENT_DIR" python3 .claude/skills/scheduled-tasks/sched.py
# DT PROCROOT [extra args] - triage the idle-after-error fixture against PROCROOT.
DT() { local root="$1"; shift; AGENT_REVIVE_PROC_ROOT="$root" bash "$HERE/tmux_triage.sh" testagent --config "$DCFG" --unit-file "$TMP/agent.service" "$@" 2>/dev/null; }
IDLE="$F/idle-after-api-error.txt"

none_out="$(DT "$TMP/p-none" --pane-file "$IDLE")"
ok "idle pane + no daemon running -> stopped" "$(jq -r '.state' <<<"$none_out")" stopped
ok "stopped: every configured daemon reads false (the _comment entry is skipped)" \
   "$(jq -c '.daemons' <<<"$none_out")" '{"watch":false,"sched":false}'
ok "stopped: daemons_expected is the configured count" "$(jq -r '.daemons_expected' <<<"$none_out")" 2
ok "stopped: daemons_running is 0" "$(jq -r '.daemons_running' <<<"$none_out")" 0
none_note="$(jq -r '.note' <<<"$none_out")"
ok "stopped note names the missing daemons" "$(grep -q 'missing: watch, sched' <<<"$none_note" && echo yes || echo no)" yes
ok "stopped note says it is NOT a sign-in case" "$(grep -q 'NOT a sign-in case' <<<"$none_note" && echo yes || echo no)" yes
ok "stopped note sends the reader to the input box before typing" "$(grep -q 'unsent text' <<<"$none_note" && echo yes || echo no)" yes
ok "control: the stopped fixture's PANE reads healthy (so the daemon reading is what decides)" \
   "$(state_of idle-after-api-error.txt)" healthy

ok "idle pane + both daemons running -> healthy" "$(DT "$TMP/p-both" --pane-file "$IDLE" | jq -r '.state')" healthy
ok "healthy: daemons_running counts both" "$(DT "$TMP/p-both" --pane-file "$IDLE" | jq -r '.daemons_running')" 2
ok "WORKING pane + no daemon running -> working, never stopped" \
   "$(DT "$TMP/p-none" --pane-file "$F/agent-tree.txt" | jq -r '.state')" working
ok "idle pane + only ONE daemon running -> healthy (stopped needs ALL absent)" \
   "$(DT "$TMP/p-one" --pane-file "$IDLE" | jq -c '[.state, .daemons]')" '["healthy",{"watch":false,"sched":true}]'

# ⚠️ THE ENVIRONMENT IS WHAT MAKES THE READING PER-AGENT. Every agent on a fleet runs
# the same watcher script, so a command-line match alone answers "does ANY agent run
# it" - green for a stopped agent whenever one peer is up. The control proves the
# peer table really carries both patterns, so the env filter is what decides.
ok "daemons running under ANOTHER agent's config dir do not count -> stopped" \
   "$(DT "$TMP/p-peer" --pane-file "$IDLE" | jq -r '.state')" stopped
ok "control: the peer table DOES carry both patterns on command lines" \
   "$(cat "$TMP"/p-peer/*/cmdline | tr '\0' '\n' | grep -oE 'slack-communication/watch.py|scheduled-tasks/sched.py' | sort -u | wc -l | tr -d ' ')" 2

# ⚠️ THREE OUTCOMES, NEVER TWO. A reading that was not taken must not pronounce:
# reported as `false`, a broken instrument would call EVERY idle agent on the fleet
# stopped - the comfortable verdict, manufactured. Each case below is a way the
# instrument cannot see, and each must come back null, with `healthy` unchanged.
nr_out="$(DT "$TMP/no-such-proc-root" --pane-file "$IDLE")"
ok "no process table at the root -> every daemon null, no verdict" "$(jq -c '[.state, .daemons, .daemons_running]' <<<"$nr_out")" '["healthy",{"watch":null,"sched":null},null]'
mkdir -p "$TMP/p-empty"
ok "a root holding no process at all -> null (no evidence the table was read), not false" \
   "$(DT "$TMP/p-empty" --pane-file "$IDLE" | jq -c '[.state, .daemons_running]')" '["healthy",null]'
cp -r "$TMP/p-none" "$TMP/p-unread"
mkproc "$TMP/p-unread" 500 "$AGENT_DIR" python3 .claude/skills/slack-communication/watch.py
chmod 000 "$TMP/p-unread/500/environ"
if [ -r "$TMP/p-unread/500/environ" ]; then
  echo "skip - an unreadable candidate environment (running as a user that reads mode 000 files)"
else
  ok "a candidate whose environment cannot be read -> null for that daemon, no verdict" \
     "$(DT "$TMP/p-unread" --pane-file "$IDLE" | jq -c '[.state, .daemons.watch, .daemons_running]')" '["healthy",null,null]'
fi
chmod 600 "$TMP/p-unread/500/environ"

ok "no daemons configured -> no reading -> healthy" \
   "$(AGENT_REVIVE_PROC_ROOT="$TMP/p-none" T --pane-file "$IDLE" 2>/dev/null | jq -c '[.state, .daemons, .daemons_expected]')" '["healthy",{},0]'
printf '%s' '{"fleet":{"agents_home":"/nonexistent-fixture-home","tmux":{"tmpdir":"/run/claude-tmux-<agent>","target":"claude-<agent>:0"},"systemd_unit":"x","daemons":[{"name":"watch"}]}}' > "$TMP/config.bad-daemon.json"
ok "a daemon entry with no pattern is a config error (exit 2), not a daemon silently unchecked" \
   "$(bash "$HERE/tmux_triage.sh" testagent --config "$TMP/config.bad-daemon.json" --pane-file "$IDLE" >/dev/null 2>&1; echo $?)" 2
jq '.fleet.daemons = ["slack-communication/watch.py"]' "$CFG" > "$TMP/config.string-daemon.json"
ok "a bare STRING in the daemon list is a config error, not an entry the comment filter drops" \
   "$(bash "$HERE/tmux_triage.sh" testagent --config "$TMP/config.string-daemon.json" --pane-file "$IDLE" >/dev/null 2>&1; echo $?)" 2
jq '.fleet.daemons = {"name":"watch","pattern":"slack-communication/watch.py"}' "$CFG" > "$TMP/config.object-daemons.json"
ok "a daemon list that is not a LIST is a config error" \
   "$(bash "$HERE/tmux_triage.sh" testagent --config "$TMP/config.object-daemons.json" --pane-file "$IDLE" >/dev/null 2>&1; echo $?)" 2
jq '.fleet.daemons = [{"name":"watch","pattern":"a\tb"}]' "$CFG" > "$TMP/config.tab-daemon.json"
ok "a tab in a daemon pattern is a config error (the list travels as TSV)" \
   "$(bash "$HERE/tmux_triage.sh" testagent --config "$TMP/config.tab-daemon.json" --pane-file "$IDLE" >/dev/null 2>&1; echo $?)" 2
ok "control: the derived daemon config (with its _comment entry) is NOT a config error" \
   "$(DT "$TMP/p-none" --pane-file "$IDLE" >/dev/null; echo $?)" 0

# THE MUTATION CONTROL IS LOAD-BEARING: the cases above prove the fixture reads
# `stopped`; this proves the `stopped` branch is what makes it so, by disabling it in
# a COPY of the real script and requiring the same reading to fall back to `healthy`.
sed -E 's/^if \[ "\$state" = "healthy" \] && \[ "\$\(jq -n --argjson d /if false \&\& [ "$(jq -n --argjson d /' \
    "$HERE/tmux_triage.sh" > "$TMP/no-stopped-branch.sh"
ok "control: the real script has exactly one stopped refinement to disable" \
   "$(grep -cE '^if \[ "\$state" = "healthy" \] && \[ "\$\(jq -n --argjson d ' "$HERE/tmux_triage.sh" | tr -d ' ')" 1
ok "control: the mutation actually applied" \
   "$(grep -cE '^if false && \[ "\$\(jq -n --argjson d ' "$TMP/no-stopped-branch.sh" | tr -d ' ')" 1
ok "control: with the stopped branch disabled the same reading is healthy" \
   "$(AGENT_REVIVE_PROC_ROOT="$TMP/p-none" bash "$TMP/no-stopped-branch.sh" testagent --config "$DCFG" --unit-file "$TMP/agent.service" --pane-file "$IDLE" 2>/dev/null | jq -r '.state')" healthy

# ⚠️ A CANDIDATE THAT EXITED IS NOT RUNNING, AND MUST NOT VOID THE READING. On a live
# table a transient process quoting the pattern (a peer's grep, a sweep command) can
# exit between the scan and the environment read; its /proc entry, environ included,
# is then gone. Read as null, that would turn a stopped agent back into `healthy`
# whenever such a process happened to be alive at the scan. Modelled here as a
# candidate with a command line and no environ file - which is what an exited process
# looks like between the two reads.
cp -r "$TMP/p-none" "$TMP/p-gone"
mkproc "$TMP/p-gone" 600 "$AGENT_DIR" grep -alF -e slack-communication/watch.py
rm -f "$TMP/p-gone/600/environ"
ok "a candidate that exited before its environment was read is skipped -> stopped, not null" \
   "$(DT "$TMP/p-gone" --pane-file "$IDLE" | jq -c '[.state, .daemons.watch]')" '["stopped",false]'

# ── per-follower liveness: is EACH of this agent's daemon logs followed? ──────
# A session hears its scheduler and its chat transport only through the FOLLOWERS it
# arms, one per daemon job (`agent-daemons.py follow <agent> <job>`). An install whose
# fleet.daemons is one substring entry for the follower script cannot tell the two
# apart, and `stopped` needs every entry false: an agent with ONE follower armed read
# `healthy` while it was deaf to the other source. The expected set is derived, not
# configured: the jobs `agent-daemons.py status <agent> --json` reports as configured
# for the agent (the stand-in below answers for that call). A follower is recognised
# by its argv POSITIONS - interpreter, script ending in systemd/agent-daemons.py,
# `follow`, this agent, the job - never by a substring, because a process that merely
# QUOTES the follower command (self-compact's detached sender carries a wake line
# that names it) is no follower. FCFG is the install shape that had the bug: one
# legacy entry, `follower`, with the script's path as its pattern.
# lstatus NAME EXIT JSON - an `agent-daemons.py status` stand-in in $TMP/st-NAME that
# answers ONLY the exact call for this agent, with a canned answer and exit code.
lstatus() {
  printf '%s\n' "$3" > "$TMP/st-$1.json"
  printf '#!/bin/sh\n[ "$*" = "status testagent --json" ] || { echo "unexpected call: $*" >&2; exit 64; }\ncat "%s"\nexit %s\n' \
    "$TMP/st-$1.json" "$2" > "$TMP/st-$1"
  chmod +x "$TMP/st-$1"
}
FCFG="$TMP/config.followers.json"
jq '.fleet.daemons = [{"name":"follower","pattern":"systemd/agent-daemons.py"}]' "$UCFG" > "$FCFG"
J_CONF='"sched":{"configured":true,"active":"active","pid":901,"argv":null},"slack-watch":{"configured":true,"active":"active","pid":902,"argv":null},"relay-watch":{"configured":false,"active":"inactive","pid":0,"argv":null}'
lstatus fol 0 "{\"agent\":\"testagent\",\"backend\":\"systemd\",\"jobs\":{$J_CONF}}"
lstatus fol-garbage 3 "agent-daemons.py: the fleet is not installed on this host"
FD="/srv/fleet-fixture/agents/systemd/agent-daemons.py"
# f-both: the agent's session plus both followers, one under the Monitor's shell wrapper.
cp -r "$TMP/p-none" "$TMP/f-both"
mkproc "$TMP/f-both" 800 "$AGENT_DIR" /bin/bash -c "python3 $FD follow testagent sched 2>&1"
mkproc "$TMP/f-both" 801 "$AGENT_DIR" python3 "$FD" follow testagent sched
mkproc "$TMP/f-both" 802 "$AGENT_DIR" /usr/bin/python3 -u "$FD" follow testagent slack-watch
# f-one: the slack-watch follower killed - the scheduler's still runs.
cp -r "$TMP/p-none" "$TMP/f-one"
mkproc "$TMP/f-one" 801 "$AGENT_DIR" python3 "$FD" follow testagent sched
# f-quote: NO follower, but the detached compaction sender quotes both follower
# commands in its wake line, in this agent's environment.
cp -r "$TMP/p-none" "$TMP/f-quote"
mkproc "$TMP/f-quote" 810 "$AGENT_DIR" python3 /x/.claude/skills/self-compact/compact.py --wake-message \
  "Compaction done. Re-arm: python3 $FD follow testagent sched 2>&1 ; and python3 $FD follow testagent slack-watch 2>&1"
# f-peer: both followers run in this agent's environment, for ANOTHER agent's logs.
cp -r "$TMP/p-none" "$TMP/f-peer"
mkproc "$TMP/f-peer" 820 "$AGENT_DIR" python3 "$FD" follow peer sched
mkproc "$TMP/f-peer" 821 "$AGENT_DIR" python3 "$FD" follow peer slack-watch
FS() { local root="$1" st="$2" cfg="$3"; shift 3; AGENT_REVIVE_PROC_ROOT="$root" AGENT_REVIVE_DAEMONS_STATUS="$TMP/st-$st" \
  bash "$HERE/tmux_triage.sh" testagent --config "$cfg" --unit-file "$TMP/agent.service" "$@" 2>/dev/null; }
F3='[.state, .followers, .followers_down]'

one_out="$(FS "$TMP/f-one" fol "$FCFG" --pane-file "$IDLE")"
ok "one follower of two killed -> follower-down, never healthy (the bug: the legacy entry read it healthy)" \
   "$(jq -c "$F3" <<<"$one_out")" '["follower-down",{"sched":true,"slack-watch":false},["slack-watch"]]'
ok "control: the legacy substring entry still reads true there, so the follower reading is what decides" \
   "$(jq -c '.daemons' <<<"$one_out")" '{"follower":true}'
ok "follower-down: followers_expected is the jobs configured for the agent, in the status order" \
   "$(jq -c '.followers_expected' <<<"$one_out")" '["sched","slack-watch"]'
one_note="$(jq -r '.note' <<<"$one_out")"
ok "follower-down note names the job it does not follow and says it needs a wake" \
   "$(grep -q 'not followed: slack-watch' <<<"$one_note" && grep -q 'wake line' <<<"$one_note" && echo yes || echo no)" yes
ok "both followers running -> healthy, both true, none down" \
   "$(FS "$TMP/f-both" fol "$FCFG" --pane-file "$IDLE" | jq -c "$F3")" '["healthy",{"sched":true,"slack-watch":true},[]]'
ok "a process that QUOTES both follower commands is no follower -> both false, follower-down" \
   "$(FS "$TMP/f-quote" fol "$FCFG" --pane-file "$IDLE" | jq -c "$F3")" '["follower-down",{"sched":false,"slack-watch":false},["sched","slack-watch"]]'
ok "control: the quoting process carries the follower command as a substring, and the legacy entry matches it" \
   "$(tr '\0' '\n' < "$TMP/f-quote/810/cmdline" | grep -c "systemd/agent-daemons.py follow testagent sched" | tr -d ' '):$(FS "$TMP/f-quote" fol "$FCFG" --pane-file "$IDLE" | jq -c '.daemons.follower')" "1:true"
ok "followers of ANOTHER agent's logs in this agent's environment do not count (the agent position decides)" \
   "$(FS "$TMP/f-peer" fol "$FCFG" --pane-file "$IDLE" | jq -c '.followers')" '{"sched":false,"slack-watch":false}'
ok "followers of this agent under ANOTHER agent's config dir do not count (the environment decides)" \
   "$(cp -r "$TMP/p-none" "$TMP/f-env"; mkproc "$TMP/f-env" 830 /nonexistent-fixture-home/peer/.claude python3 "$FD" follow testagent sched
      FS "$TMP/f-env" fol "$FCFG" --pane-file "$IDLE" | jq -c '.followers.sched')" false
jq '.fleet.daemons = []' "$UCFG" > "$TMP/config.no-legacy.json"
ok "no legacy entries and every expected follower down -> stopped, naming each follower" \
   "$(FS "$TMP/p-none" fol "$TMP/config.no-legacy.json" --pane-file "$IDLE" | jq -c '[.state, (.note | test("missing: follower sched, follower slack-watch"))]')" '["stopped",true]'
ok "no legacy entries, one follower down -> follower-down" \
   "$(FS "$TMP/f-one" fol "$TMP/config.no-legacy.json" --pane-file "$IDLE" | jq -r '.state')" follower-down
ok "a WORKING pane stays working, and carries the down follower in followers_down (a flag in every state)" \
   "$(FS "$TMP/f-one" fol "$FCFG" --pane-file "$F/agent-tree.txt" | jq -c '[.state, .followers_down]')" '["working",["slack-watch"]]'
ok "no answer from agent-daemons.py status -> no expected set (null), no follower reading, no verdict from it" \
   "$(FS "$TMP/f-one" fol-garbage "$FCFG" --pane-file "$IDLE" | jq -c '[.state, .followers_expected, .followers, .followers_down]')" '["healthy",null,{},[]]'
ok "no process table -> each expected follower null, never follower-down" \
   "$(FS "$TMP/no-such-proc-root" fol "$TMP/config.no-legacy.json" --pane-file "$IDLE" | jq -c "$F3")" '["healthy",{"sched":null,"slack-watch":null},[]]'
# The follower-down branch is what makes f-one read follower-down: disabled in a copy
# of the real script, the same reading falls back to healthy.
sed -E 's/^elif \[ "\$state" = "healthy" \] && \[ "\$deaf_jobs" != "\[\]" \]/elif false/' \
    "$HERE/tmux_triage.sh" > "$TMP/no-follower-branch.sh"
ok "control: the real script has exactly one follower-down refinement to disable" \
   "$(grep -cE '^elif \[ "\$state" = "healthy" \] && \[ "\$deaf_jobs" != "\[\]" \]' "$HERE/tmux_triage.sh" | tr -d ' ')" 1
ok "control: with the follower-down branch disabled the same reading is healthy" \
   "$(AGENT_REVIVE_PROC_ROOT="$TMP/f-one" AGENT_REVIVE_DAEMONS_STATUS="$TMP/st-fol" bash "$TMP/no-follower-branch.sh" testagent --config "$FCFG" --unit-file "$TMP/agent.service" --pane-file "$IDLE" 2>/dev/null | jq -r '.state')" healthy

# ── a daemon writing to a REPLACED log: running, every follower armed, unheard ──
# A unit opens its log once; a log rewritten in place (`sed -i`) or moved leaves the
# daemon appending to the old file while the follower reads the path. status --json
# says so per job (log_replaced: the reason, false, or null when unreadable). Only a
# reason counts, and only for a job configured for this agent; it raises the
# follower-down state through deaf_jobs with every follower armed (f-both), and the
# remedy it names is a restart of the unit, not a wake. The relay job below is NOT
# configured: its replaced log must not count.
J_REPL='"sched":{"configured":true,"active":"active","pid":901,"argv":null,"log_replaced":false},"slack-watch":{"configured":true,"active":"active","pid":902,"argv":null,"log_replaced":"writes to a replaced log (/x/slack-watch.log: deleted)"},"relay-watch":{"configured":false,"active":"active","pid":903,"argv":null,"log_replaced":"writes to a replaced log (/x/relay-watch.log: deleted)"}'
lstatus repl 1 "{\"agent\":\"testagent\",\"backend\":\"systemd\",\"jobs\":{$J_REPL}}"
lstatus repl-null 0 "{\"agent\":\"testagent\",\"backend\":\"systemd\",\"jobs\":{$(sed 's/"log_replaced":"[^"]*"/"log_replaced":null/g' <<<"$J_REPL")}}"
repl_out="$(FS "$TMP/f-both" repl "$FCFG" --pane-file "$IDLE")"
ok "both followers armed, the watcher writing to a replaced log -> follower-down, the job in logs_replaced, none in followers_down" \
   "$(jq -c '[.state, .followers, .followers_down, .logs_replaced]' <<<"$repl_out")" \
   '["follower-down",{"sched":true,"slack-watch":true},[],["slack-watch"]]'
repl_note="$(jq -r '.note' <<<"$repl_out")"
ok "its note names the job and the unit restart, which no wake line makes" \
   "$(grep -q 'writes to a replaced log: slack-watch' <<<"$repl_note" && grep -q 'needs its unit restarted' <<<"$repl_note" \
      && ! grep -q 'not followed' <<<"$repl_note" && echo yes || echo no)" yes
ok "a WORKING pane keeps its state and still carries logs_replaced (a flag in every state)" \
   "$(FS "$TMP/f-both" repl "$FCFG" --pane-file "$F/agent-tree.txt" | jq -c '[.state, .logs_replaced]')" '["working",["slack-watch"]]'
ok "log_replaced null (unreadable) counts for nothing: healthy, logs_replaced empty" \
   "$(FS "$TMP/f-both" repl-null "$FCFG" --pane-file "$IDLE" | jq -c '[.state, .logs_replaced]')" '["healthy",[]]'
ok "no answer from agent-daemons.py status -> logs_replaced empty, no verdict from it" \
   "$(FS "$TMP/f-both" fol-garbage "$FCFG" --pane-file "$IDLE" | jq -c '[.state, .logs_replaced]')" '["healthy",[]]'
ok "one follower down AND a replaced log -> follower-down naming both causes" \
   "$(FS "$TMP/f-one" repl "$FCFG" --pane-file "$IDLE" | jq -c '[.state, .followers_down, .logs_replaced, (.note | test("not followed: slack-watch; writes to a replaced log: slack-watch"))]')" \
   '["follower-down",["slack-watch"],["slack-watch"],true]'
ok "control: with the follower-down branch disabled the replaced-log reading is healthy" \
   "$(AGENT_REVIVE_PROC_ROOT="$TMP/f-both" AGENT_REVIVE_DAEMONS_STATUS="$TMP/st-repl" bash "$TMP/no-follower-branch.sh" testagent --config "$FCFG" --unit-file "$TMP/agent.service" --pane-file "$IDLE" 2>/dev/null | jq -r '.state')" healthy

# ── the SHIPPED daemon lists name what actually runs ──────────────────────────
# config.example.json and the fixture install's config.json are what an installer
# copies, so their fleet.daemons must match the processes the fleet's units start.
# The table below is NOT hand-written: each process is the unit template's ExecStart
# (`@PYTHON@ -u @SCRIPT@`) filled from systemd/agent-daemons.py's own job table, so a
# moved script or a new working transport reds here. A pattern naming something that
# never runs as the daemon (`systemd/agent-daemons.py` is only the units' rotate step
# and the refresh timer) reads `false` on an agent whose scheduler is up, and an idle
# agent whose watcher is down then reads `stopped` instead of `healthy`.
FLEET_TREE="$(cd "$HERE/../../.." && pwd)"
JOBS="$(python3 "$FLEET_TREE/systemd/agent-daemons.py" jobs --json 2>/dev/null)"
ok "control: the job table was read (needs FLEET_HOST_CONFIG and FLEET_CONTEXT_ROOT, as tests/run-all.sh sets)" \
   "$(jq -r '.jobs.sched.script | endswith("/scheduled-tasks/sched.py")' <<<"$JOBS" 2>/dev/null)" true
ok "control: every daemon unit starts its script as \`@PYTHON@ -u @SCRIPT@\` (the shape the table below copies)" \
   "$(grep -hcxF 'ExecStart=@PYTHON@ -u @SCRIPT@' "$FLEET_TREE"/systemd/agent-sched@.service.in "$FLEET_TREE"/systemd/agent-watch@.service.in | tr '\n' ' ')" "1 1 "
n=700
while IFS=$'\t' read -r j_python j_script; do
  mkproc "$TMP/p-units" "$n" "$AGENT_DIR" "$j_python" -u "$j_script"; n=$((n + 1))
done < <(jq -r '.python as $p | .jobs[] | [$p, .script] | @tsv' <<<"$JOBS")
jobs_n="$(jq -r '.jobs | length' <<<"$JOBS")"
for shipped in "$HERE/config.example.json" "$FLEET_TREE/tests/fixtures/install/.claude/skills/agent-revive/config.json"; do
  label="${shipped#"$FLEET_TREE"/}"
  jq --slurpfile s "$shipped" '.fleet.daemons = $s[0].fleet.daemons' "$CFG" > "$TMP/config.shipped.json"
  out="$(AGENT_REVIVE_PROC_ROOT="$TMP/p-units" bash "$HERE/tmux_triage.sh" testagent --config "$TMP/config.shipped.json" --unit-file "$TMP/agent.service" --pane-file "$IDLE" 2>/dev/null)"
  ok "$label: one daemon entry per job in the job table" "$(jq -r '.daemons_expected' <<<"$out")" "$jobs_n"
  ok "$label: every daemon entry matches a process the units start" "$(jq -r '[.state, .daemons_running] | @tsv' <<<"$out")" "healthy	$jobs_n"
  # ...and each matches exactly ONE job's script: a pattern as loose as `.py` would
  # pass the two rows above while telling the daemons apart not at all.
  ok "$label: each pattern names exactly one job's script" \
     "$(jq -r --argjson j "$JOBS" '[.fleet.daemons[] | select(.pattern) | .pattern as $p | [$j.jobs[].script | select(contains($p))] | length] | map(tostring) | join(" ")' "$shipped")" \
     "$(printf '1 %.0s' $(seq "$jobs_n") | sed 's/ $//')"
done
# The negative half: on the same table the retired pattern finds nothing, so the
# `true` above is the pattern's doing, not a table every pattern matches.
jq '.fleet.daemons = [{"name":"scheduler","pattern":"systemd/agent-daemons.py"}]' "$CFG" > "$TMP/config.rotate-pattern.json"
ok "control: a pattern naming the rotate step, not the daemon, does NOT see the running scheduler" \
   "$(AGENT_REVIVE_PROC_ROOT="$TMP/p-units" bash "$HERE/tmux_triage.sh" testagent --config "$TMP/config.rotate-pattern.json" --unit-file "$TMP/agent.service" --pane-file "$IDLE" 2>/dev/null | jq -c '[.state, .daemons]')" '["stopped",{"scheduler":false}]'

# last_turn_error: the error the idle session's last turn ended on, joined across its
# wrap, and null where the live area shows none.
ok "last_turn_error carries the API error, wrapped lines joined" \
   "$(T --pane-file "$IDLE" 2>/dev/null | jq -r '.last_turn_error')" \
   "API Error: 529 Overloaded. This is a server-side issue, usually temporary — try again in a moment. If it persists, check https://status.claude.com."
ok "last_turn_error is null where the pane shows no API error" \
   "$(T --pane-file "$F/healthy-pane.txt" 2>/dev/null | jq -c '.last_turn_error')" null
printf ' > Triage reports the last `API Error:` line in last_turn_error.\n\n bypass permissions on (shift+tab to cycle) - ? for shortcuts\n' > "$TMP/api-error-prose.txt"
ok "last_turn_error is NOT taken from prose quoting the marker mid-line" \
   "$(T --pane-file "$TMP/api-error-prose.txt" 2>/dev/null | jq -c '.last_turn_error')" null
ok "unreachable carries the daemon reading too (it is a reading of the machine, not the pane)" \
   "$(DT "$TMP/p-none" | jq -c '[.state, .daemons, .daemons_running]')" '["unreachable",{"watch":false,"sched":false},0]'

# ⚠️ `fast limit` IS NOT A QUOTA CAP. It is the Fast-mode cooldown: it resets in
# minutes and the session keeps taking turns. Classified `usage-cap` it costs a DM
# to a human and an account switch on a healthy agent, which is why the exclusion
# is pinned rather than left to the shape.
printf ' \xe2\x9a\xa0 You'"'"'ve hit your fast limit \xc2\xb7 resets in 4m\n\n bypass permissions on (shift+tab to cycle) - ? for shortcuts\n' > "$TMP/cap-fast.txt"
ok "the Fast-mode cooldown is NOT a usage-cap" \
   "$(T --pane-file "$TMP/cap-fast.txt" 2>/dev/null | jq -r '.state')" healthy
ok "control: that pane DOES match the banner shape apart from the exclusion" \
   "$(grep -q "You've hit your fast limit" "$TMP/cap-fast.txt" && echo yes || echo no)" yes

# the builder can leave the limit name out entirely, and two SIBLING builders say
# the same thing in different words. Each is a genuine "takes no turns" state.
printf ' \xe2\x9a\xa0 You'"'"'ve hit your limit \xc2\xb7 resets 3pm \xc2\xb7 progress saved\n\n bypass permissions on - ? for shortcuts\n' > "$TMP/cap-unnamed.txt"
ok "a banner with NO limit name is still usage-cap" \
   "$(T --pane-file "$TMP/cap-unnamed.txt" 2>/dev/null | jq -r '.state')" usage-cap
printf ' You'"'"'re out of usage credits. Run /usage-credits to add more.\n\n bypass permissions on - ? for shortcuts\n' > "$TMP/cap-credits.txt"
ok "the out-of-credits wording is usage-cap" \
   "$(T --pane-file "$TMP/cap-credits.txt" 2>/dev/null | jq -r '.state')" usage-cap
printf " You've hit your team's shared budget. /model to switch models.\n\n bypass permissions on - ? for shortcuts\n" > "$TMP/cap-budget.txt"
ok "the shared-budget wording is usage-cap" \
   "$(T --pane-file "$TMP/cap-budget.txt" 2>/dev/null | jq -r '.state')" usage-cap

# ⚠️ THE `banner` FIELD IS WHY THE OPERATOR CAN OBEY THE NOTE. The note says to
# confirm the banner and to read WHICH limit it names; without the line in the
# output that instruction needs a second capture the charters do not ask for, and
# an instruction nobody can follow is one that gets skipped.
ok "the matched banner line is returned, stripped of pane decoration" \
   "$(T --pane-file "$F/usage-cap.txt" 2>/dev/null | jq -r '.banner')" "You've hit your session limit · resets 10pm"
ok "banner is EMPTY for a state that is neither usage-cap nor login-expired" \
   "$(T --pane-file "$F/healthy-pane.txt" 2>/dev/null | jq -r '.banner')" ""

# the note is the operator's whole instruction at this state, and both halves of it
# are load-bearing: a cap is handled as an expired login (a human, a fresh URL, the
# next account), and Ctrl-C must not reach a capped pane because it cancels the
# automatic continue and leaves the switch as the only way back.
cap_note="$(T --pane-file "$F/usage-cap.txt" 2>/dev/null | jq -r '.note')"
ok "usage-cap note says a cap IS an expired login" "$(grep -q 'expired login' <<<"$cap_note" && echo yes || echo no)" yes
ok "usage-cap note demands the banner be confirmed before any keystroke" \
   "$(grep -q 'CONFIRM BEFORE TYPING' <<<"$cap_note" && echo yes || echo no)" yes
ok "usage-cap note separates an account-scoped cap from a model or spend cap" \
   "$(grep -q 'model-scoped or spend cap does not follow the account' <<<"$cap_note" && echo yes || echo no)" yes
ok "usage-cap note warns about Escape as well as Ctrl-C" \
   "$(grep -q 'NEITHER Ctrl-C NOR Escape' <<<"$cap_note" && echo yes || echo no)" yes
ok "usage-cap note warns that Ctrl-C cancels the automatic continue" \
   "$(grep -q 'Ctrl-C' <<<"$cap_note" && grep -q 'automatic continue' <<<"$cap_note" && echo yes || echo no)" yes

# ⚠️ THE WAIT BRANCH IS PINNED BECAUSE THE SWITCH BRANCH IS. The assertion above
# requires the note to say `expired login`, which only the weekly / distant-reset half
# says. Leave that pinned alone and a revert that drops the wait half stays green while
# the note tells an operator to burn an account switch on a window that resets in
# minutes - the switch is irreversible for the in-flight work, the wait costs nothing.
# Both halves are the operator's instruction, so both are measured; an unpinned half
# beside a pinned one reads as the optional one.
ok "usage-cap note names the WAIT branch (an imminent session reset continues by itself)" \
   "$(grep -q 'SESSION limit whose reset is imminent' <<<"$cap_note" && grep -q 'type NOTHING' <<<"$cap_note" && echo yes || echo no)" yes
ok "usage-cap note BOUNDS the wait (poll to past the reset) instead of leaving it open-ended" \
   "$(grep -q 'poll the pane' <<<"$cap_note" && grep -q 'past the reset' <<<"$cap_note" && echo yes || echo no)" yes

# ⚠️ THE `signin-url` NOTE CARRIES A FORK THE STATE ITSELF CANNOT REPRESENT, and
# these three assertions are what keep it in the file. `signin-url` fires on the
# `Paste code here` prompt, and TWO different panes produce that prompt: an expired
# login, and a CAPPED session that was sent `/login`. They are indistinguishable on
# the pane, and the regeneration routes are opposite - Escape returns the first to
# its ready prompt and, on the second, cancels the session's automatic continue at
# the reset time, which has no undo and costs the account switch. So the note is the
# only place the operator learns that the state is ambiguous; a tidying pass that
# restores a single flat "Expired login: ... press Escape" sentence reads as a
# simplification and silently re-arms the destructive route. And a double Ctrl-C on
# this prompt quits Claude Code, so the note must never offer it as a route.
# Delete these and that edit reds nothing. They pin the PROPERTIES (both origins named, both routes named,
# the unknown-origin default), never a sentence, so the wording stays free to change.
url_note="$(T --pane-file "$F/signin-url.txt" 2>/dev/null | jq -r '.note')"
ok "signin-url note does NOT assert a single origin (it carries no 'Expired login:')" \
   "$(grep -q 'Expired login:' <<<"$url_note" && echo no || echo yes)" yes
ok "signin-url note names the capped origin and its /login route" \
   "$(grep -qi 'capped' <<<"$url_note" && grep -q '/login' <<<"$url_note" && echo yes || echo no)" yes
ok "signin-url note warns Escape/Ctrl-C cancel the automatic continue on the capped pane" \
   "$(grep -q 'NEVER Escape or Ctrl-C' <<<"$url_note" && grep -q 'automatic continue' <<<"$url_note" && echo yes || echo no)" yes
ok "signin-url note routes the expired-login prompt through Escape, then /login" \
   "$(grep -q 'ONE Escape' <<<"$url_note" && grep -q 'Login interrupted' <<<"$url_note" && echo yes || echo no)" yes
ok "signin-url note says a double Ctrl-C QUITS Claude Code (never a route)" \
   "$(grep -q 'NEVER a double Ctrl-C' <<<"$url_note" && grep -qi 'quits Claude Code' <<<"$url_note" && echo yes || echo no)" yes
ok "signin-url note does NOT prescribe the double Ctrl-C for an expired login" \
   "$(grep -qi 'takes the rapid double Ctrl-C' <<<"$url_note" && echo no || echo yes)" yes
# ⚠️ This one is pinned on 'EVERY send', not on 'regenerate'. The note said
# "Regenerate a FRESH url" BEFORE the every-send rule existed, so a `regenerat` match
# passes on the old note too - a green that corroborates nothing. Measured: reverting
# the note reds the three checks above and left a `regenerat` match green.
ok "signin-url note tells the reader EVERY send carries a newly regenerated url" \
   "$(grep -q 'EVERY send' <<<"$url_note" && grep -qi 'regenerat' <<<"$url_note" && echo yes || echo no)" yes
ok "control: the note was actually read (empty note would pass the first check vacuously)" \
   "$([ -n "$url_note" ] && [ "$url_note" != null ] && echo yes || echo no)" yes

# ⚠️ REGIME CONTROL on status-modal: it must fire on the BLOCK, not on the WORDS.
# A substring match on "login method" and "organization" classifies an agent
# DISCUSSING them as a modal - and status-modal's prescribed remedy is to send
# Escape, which INTERRUPTS a live turn. The likeliest victim is someone working on
# this very skill, whose pane carries this skill's own prose. Failing the other way
# is harmless (an unmatched modal reads as `healthy`), so the signature stays
# line-anchored, colon-terminated and
# case-sensitive. These two panes each carry BOTH words and a ready status bar.
printf ' > I updated the login method for the organization.\n\n bypass permissions on (shift+tab to cycle) - ? for shortcuts\n' > "$TMP/fp-prose.txt"
ok "NOT a modal: prose merely containing the two words" "$(T --pane-file "$TMP/fp-prose.txt" 2>/dev/null | jq -r '.state')" healthy
printf ' its block carries a `Login method:` line and an `Organization:` line, and\n the account email appears on it.\n\n bypass permissions on - ? for shortcuts\n' > "$TMP/fp-skillprose.txt"
ok "NOT a modal: an agent reading THIS skill's own prose about the block" "$(T --pane-file "$TMP/fp-skillprose.txt" 2>/dev/null | jq -r '.state')" healthy
ok "control: both false-positive panes DO contain the two words (so the check is not vacuous)" \
   "$(grep -qi 'login method' "$TMP/fp-prose.txt" && grep -qi 'organization' "$TMP/fp-prose.txt" && grep -qi 'login method' "$TMP/fp-skillprose.txt" && grep -qi 'organization' "$TMP/fp-skillprose.txt" && echo yes || echo no)" yes

# ── login-expired: a dead login behind a ready prompt ─────────────────────────
# ⚠️ MEASURED ON A LIVE AGENT, AND THE MISS IS THE WORST KIND: A DEAD AGENT READ AS
# HEALTHY. fixtures/login-expired.txt is a fleet agent's own pane: every turn ends
# on `● Login expired · Please run /login` at an otherwise ordinary ready prompt. No
# sign-in URL is printed in that state, so `signin-url` never matches, the daemons it
# runs under systemd keep running, and the pane matched only `healthy` - on three
# consecutive hourly sweeps. Its transcript lines are verbatim; the four ready-box
# lines at the bottom are reconstructed (the box's top border verbatim from the same
# capture, the prompt and status-bar shape of fixtures/idle-after-api-error.txt),
# because by the time the pane was captured somebody had already typed /login into it.
# ⚠️ EVERY PANE BELOW IS BUILT FROM BYTES CLAUDE CODE DRAWS. A result row is `  ⎿ `
# and then a NON-BREAKING SPACE; the prefix is lifted from the fixture's own line 7
# rather than typed, because a row written with two ASCII spaces is one Claude Code
# never draws - a recovery row built that way stayed green while real recoveries were
# misread. The derived panes say which binary string or capture they render.
LE="$F/login-expired.txt"
ROW="$(sed -n 7p "$LE" | grep -o '^  ⎿[^0-9]*')"
ok "control: the result-row prefix is the drawn one (⎿, a space, a non-breaking space)" \
   "$(printf '%s' "$ROW" | od -An -tx1 | tr -d ' \n')" "2020e28ebf20c2a0"
awk '/^─/ {exit} {print}' "$LE" > "$TMP/le-transcript.txt"
sed -n '/^─/,$p' "$LE" > "$TMP/le-ready-box.txt"
ok "control: the fixture splits into its transcript and a four-line ready box" \
   "$(grep -c . "$TMP/le-ready-box.txt" | tr -d ' '):$(grep -c 'Login expired · Please run /login' "$TMP/le-transcript.txt" | tr -d ' ')" "4:6"
# the transcript with its login lines removed: every control below that must NOT be
# login-expired for the right reason is the same pane built on this.
grep -vE '^● (Login expired · |Remote Control disconnected — OAuth token unavailable)' "$TMP/le-transcript.txt" > "$TMP/le-transcript-no-login.txt"
ok "an expired login at a ready prompt is login-expired" "$(state_of login-expired.txt)" login-expired
ok "login-expired returns the session's own last line in 'banner', stripped of its bullet" \
   "$(T --pane-file "$LE" 2>/dev/null | jq -r '.banner')" "Login expired · Please run /login"

# ⚠️ MUTATION CONTROL, LOAD-BEARING: the positive row proves the fixture reads
# `login-expired`; this proves the DETECTION is what makes it so, and reproduces the
# measured defect on the classifier itself - with the detection neutered in a COPY
# (it can never say yes), the same capture must read exactly what the live sweep
# read: `healthy`. Two controls guard the mutation, so a sed that matched nothing
# cannot pass for one that neutered the detection. (Disabling the BRANCH instead is
# not this control: the pane then reads the no-verdict `unknown` branch below it.)
sed -E 's/^  login_expired=yes$/  login_expired=no/' "$HERE/tmux_triage.sh" > "$TMP/no-login-expired-detection.sh"
ok "control: the real script has exactly one place the detection says yes" \
   "$(grep -cE '^  login_expired=yes$' "$HERE/tmux_triage.sh" | tr -d ' ')" 1
ok "control: the mutation actually applied (the detection never says yes in the copy)" \
   "$(grep -cE '^  login_expired=yes$' "$TMP/no-login-expired-detection.sh" | tr -d ' ')" 0
ok "control: with the detection neutered the capture reads healthy (the reading that hid it)" \
   "$(bash "$TMP/no-login-expired-detection.sh" testagent --config "$CFG" --pane-file "$LE" 2>/dev/null | jq -r '.state')" healthy
ok "control: the real script has exactly one login-expired branch, gated on the input box" \
   "$(grep -cE '^elif \[ "\$login_expired" = yes \] && \[ "\$login_box" = 1 \] && \[ "\$busy" = no \]; then$' "$HERE/tmux_triage.sh" | tr -d ' ')" 1

# The other dead-login results, rendered as the 2.1.296 binary draws them:
# `OAuth token revoked` and `Not logged in` as a RESULT ROW hanging under the line
# before (the result-row component, not a bullet), the 401 form as a bullet like
# every `API Error:` line. Derived from the capture, so only the rendering changes.
le_row_variant() {  # TEXT OUT - every Login-expired bullet becomes a result row carrying TEXT
  LE_ROW_TEXT="$1" awk -v row="$ROW" '{ l[NR] = $0 } END {
       for (i = 1; i <= NR; i++) {
         if (l[i] == "" && l[i+1] ~ /^● Login expired · Please run \/login$/) continue
         if (l[i] ~ /^● Login expired · Please run \/login$/) { print row ENVIRON["LE_ROW_TEXT"]; continue }
         print l[i] } }' "$LE" > "$2"
}
le_row_variant 'OAuth token revoked · Please run /login' "$TMP/le-revoked.txt"
le_row_variant 'Not logged in · Please run /login' "$TMP/le-not-logged-in.txt"
sed 's/^● Login expired · Please run \/login$/● Please run \/login · API Error: 401 {"type":"error","error":{"type":"authentication_error"}}/' "$LE" > "$TMP/le-auth-failed.txt"
ok "a REVOKED token, drawn as a result row, is login-expired" "$(T --pane-file "$TMP/le-revoked.txt" 2>/dev/null | jq -r '.state')" login-expired
ok "NOT LOGGED IN, drawn as a result row, is login-expired" "$(T --pane-file "$TMP/le-not-logged-in.txt" 2>/dev/null | jq -r '.state')" login-expired
ok "the 401 form ('Please run /login · API Error: 401') is login-expired" \
   "$(T --pane-file "$TMP/le-auth-failed.txt" 2>/dev/null | jq -r '.state')" login-expired
ok "the result-row form's banner carries the reason, stripped of the row prefix" \
   "$(T --pane-file "$TMP/le-revoked.txt" 2>/dev/null | jq -r '.banner')" "OAuth token revoked · Please run /login"
# ⚠️ Control on those derivations: a transform that matched nothing leaves the
# original `● Login expired` lines in place, and the rows then pass on THOSE.
ok "control: each variant carries its wording six times, the original bullet never, and the rows hang with no blank above" \
   "$(for v in revoked:'OAuth token revoked' not-logged-in:'Not logged in' auth-failed:'Please run /login · API Error: 401'; do
        f="$TMP/le-${v%%:*}.txt"; printf '%s/%s ' "$(grep -cF "${v#*:}" "$f" | tr -d ' ')" "$(grep -c '^● Login expired · ' "$f" | tr -d ' ')"; done
      grep -B1 -F "${ROW}OAuth token revoked" "$TMP/le-revoked.txt" | grep -c '^$' | tr -d ' ')" "6/0 6/0 6/0 0"
# Older builds draw the message bullet as ⏺; the match is an alternation. This row
# covers the BULLET only: those builds also drew a rounded `│ > │` input box, which
# `login_box` does not recognise, so an older pane in full reads `healthy`. The fleet
# runs 2.1.289 or later, which draws the bordered box.
sed -E 's/^● /⏺ /' "$LE" > "$TMP/le-old-bullet.txt"
ok "the same capture drawn with the older ⏺ bullet is login-expired" \
   "$(T --pane-file "$TMP/le-old-bullet.txt" 2>/dev/null | jq -r '.state')" login-expired
ok "control: the bullet substitution applied (no ● bullet left at column 0)" \
   "$(grep -c '^● ' "$TMP/le-old-bullet.txt" | tr -d ' ')" 0

# ⚠️ REMOTE CONTROL'S NOTICE DECIDES NOTHING, IN EITHER DIRECTION. It says the
# bridge's token refresh gave up - which a network outage can also do - so it is not
# evidence of a dead login, and it does not clear one: the word before it stands.
{ awk '{print} /^● Remote Control disconnected/ {exit}' "$LE"; echo; cat "$TMP/le-ready-box.txt"; } > "$TMP/le-remote-control.txt"
ok "the notice as the last line after a login-expired result: still login-expired (the result stands)" \
   "$(T --pane-file "$TMP/le-remote-control.txt" 2>/dev/null | jq -r '.state')" login-expired
ok "control: that pane's last line above the box really is the notice" \
   "$(grep -v '^$' "$TMP/le-remote-control.txt" | sed -n '/^─/q;p' | tail -1 | grep -c 'OAuth token unavailable' | tr -d ' ')" 1
{ printf '● Sweep done: all three healthy.\n\n✻ Worked for 3s · done 9:02 AM\n\n● Remote Control disconnected — OAuth token unavailable — run /login to restore Remote Control\n\n'; cat "$TMP/le-ready-box.txt"; } > "$TMP/rc-alone.txt"
ok "NOT login-expired: the notice alone, after a healthy reply" \
   "$(T --pane-file "$TMP/rc-alone.txt" 2>/dev/null | jq -r '.state')" healthy

# ⚠️ IT IS THE SESSION'S LAST WORD OR IT IS NOTHING. A login that was signed back in
# leaves the old result lines in the scrollback; read anywhere on the pane, the
# revived agent would read `login-expired` and be sent through /login again - and
# after an account switch Claude Code takes no turn of its own, so nothing else
# would clear it. `Login successful` ends the state (the row under a /login echo, and
# the login dialog's own screen); `Login interrupted` - a cancelled login - does not.
{ cat "$TMP/le-transcript.txt"; printf '❯ /login\n%sLogin successful\n\n' "$ROW"; cat "$TMP/le-ready-box.txt"; } > "$TMP/le-login-successful.txt"
ok "NOT login-expired: the same pane after a successful /login (drawn bytes)" \
   "$(T --pane-file "$TMP/le-login-successful.txt" 2>/dev/null | jq -r '.state')" healthy
{ cat "$TMP/le-transcript.txt"; printf '❯ /login\n%sLogin successful. Remote Control disconnected.\n\n' "$ROW"; cat "$TMP/le-ready-box.txt"; } > "$TMP/le-login-successful-rc.txt"
ok "NOT login-expired: the success row's Remote Control variant" \
   "$(T --pane-file "$TMP/le-login-successful-rc.txt" 2>/dev/null | jq -r '.state')" healthy
{ cat "$TMP/le-transcript.txt"; printf '❯ /login\n%sLogin interrupted\n\n' "$ROW"; cat "$TMP/le-ready-box.txt"; } > "$TMP/le-login-interrupted.txt"
ok "still login-expired: a /login that was cancelled (Login interrupted, drawn bytes)" \
   "$(T --pane-file "$TMP/le-login-interrupted.txt" 2>/dev/null | jq -r '.state')" login-expired
{ cat "$TMP/le-transcript.txt"
  printf '● Monitor event: SCHED due [tsk_x] run=1566 "agent-health sweep"\n\n● Sweep done: all three healthy. Nothing for anyone.\n\n✻ Worked for 41s · done 8:20 AM\n\n'
  cat "$TMP/le-ready-box.txt"; } > "$TMP/le-later-turn.txt"
ok "NOT login-expired: a later turn answered after the old result lines" \
   "$(T --pane-file "$TMP/le-later-turn.txt" 2>/dev/null | jq -r '.state')" healthy
# A revived session nudged straight back to work, with subagent rows listed under
# its status bar pushing the interrupt hint out of the tail: the wide-window markers
# must count again once the login is back.
awk '{ l[NR] = $0 } END { for (i = NR; i > 1; i--) if (l[i] ~ /^❯/ && l[i-1] ~ /^─/) break
                          for (j = i - 1; j <= NR; j++) print l[j] }' "$F/working-panel-scroll-prose.txt" > "$TMP/list-panel-box.txt"
ok "control: the LIST-mode box was cut from the fixture (border, prompt, border, status bar, rows)" \
   "$(head -2 "$TMP/list-panel-box.txt" | tail -1 | grep -c '^❯' | tr -d ' '):$(grep -c '↓ to manage$' "$TMP/list-panel-box.txt" | tr -d ' ')" "1:1"
{ cat "$TMP/le-transcript.txt"; printf '❯ /login\n%sLogin successful\n\n❯ You were revived - keep going.\n\n' "$ROW"
  printf '✢ Pondering… (14s · ↓ 312 tokens)\n\n'; cat "$TMP/list-panel-box.txt"; } > "$TMP/le-revived-working.txt"
ok "a revived, re-prompted session working again, hint pushed out by listed subagents, is working (pins the echo and the guards; the success rule is pinned above)" \
   "$(T --pane-file "$TMP/le-revived-working.txt" 2>/dev/null | jq -r '.state')" working
# ⚠️ A PROMPT ECHO STARTS A TURN, and whatever that turn says next is the word - so a
# turn in flight after the old results is not read as the dead login it may have left.
{ cat "$TMP/le-transcript.txt"; printf '❯ keep going\n\n✢ Pondering… (14s · ↓ 312 tokens)\n\n'; cat "$TMP/list-panel-box.txt"; } > "$TMP/le-prompt-in-flight.txt"
ok "a prompt echo after the old results, turn in flight: working, not login-expired" \
   "$(T --pane-file "$TMP/le-prompt-in-flight.txt" 2>/dev/null | jq -r '.state')" working

# ⚠️ A SLASH COMMAND'S ROWS ARE ITS OUTPUT ONLY UNTIL THE NEXT COLUMN-0 LINE. After
# it, a `›` message starts a turn like a prompt echo does, and that turn's result row
# is the session speaking again.
{ printf '● Sweep done.\n\n✻ Worked for 3s · done 9:02 AM\n\n❯ /usage\n%sUsage dialog dismissed\n\n' "$ROW"
  printf '› Message from @architect (ctrl+o to expand)\n%sOAuth token revoked · Please run /login\n\n✻ Worked for 0s · done 9:05 AM\n\n' "$ROW"
  cat "$TMP/le-ready-box.txt"; } > "$TMP/le-after-slash-command.txt"
ok "a revoked-token row after a slash command's output and a › message is login-expired" \
   "$(T --pane-file "$TMP/le-after-slash-command.txt" 2>/dev/null | jq -r '.state')" login-expired

# ⚠️ PRECEDENCE AGAINST signin-url: a code prompt wins. It is what the same pane
# shows once /login has been run - the old result lines are still above it, and the
# remedy for this state (run /login) would be a step BACKWARDS from a session that
# is already waiting for its code. Shaped exactly as the live capture was.
{ cat "$TMP/le-transcript.txt"; printf '❯ /login\n'; cat "$F/signin-url.txt"; } > "$TMP/le-then-code-prompt.txt"
ok "a code prompt under the old login-expired lines is signin-url" \
   "$(T --pane-file "$TMP/le-then-code-prompt.txt" 2>/dev/null | jq -r '.state')" signin-url
ok "control: that pane's last top-level message IS the login-expired line (so the order is what decides)" \
   "$(grep -E '^(●|⏺) ' "$TMP/le-then-code-prompt.txt" | tail -1 | sed -E 's/^(●|⏺) //')" "Login expired · Please run /login"

# ⚠️ NO INPUT BOX, NO VERDICT. The remedy types /login and Enter. The exit dialog
# (strings from the 2.1.296 binary, layout approximated) is preselected on "Exit and
# stop tasks", so that Enter KILLS the session; the login dialog's success screen
# takes Enter to continue. A dead transcript under either is not login-expired.
{ cat "$TMP/le-transcript.txt"; printf '────────────────────────────────────────\n  Background work is running\n  The following will stop when you exit:\n    · 1 monitor\n\n  ❯ 1. Exit and stop tasks\n    2. Move to background and exit\n    3. Stay\n'; } > "$TMP/le-exit-dialog.txt"
ok "NOT login-expired: a dead transcript under the EXIT dialog (its Enter kills the session)" \
   "$(T --pane-file "$TMP/le-exit-dialog.txt" 2>/dev/null | jq -r '.state')" unknown
{ cat "$TMP/le-transcript.txt"; printf '❯ /login\n────────────────────────────────────────\n  Login\n\n  Browser didn'"'"'t open? Use the url below to sign in (c to copy)\n\n'
  grep '^ *https://\|^[A-Za-z0-9%=&_.-]*$' "$F/signin-url.txt" | grep -v '^$'; } > "$TMP/le-login-dialog-url.txt"
ok "NOT login-expired: a dead transcript under the login dialog, before its code prompt draws" \
   "$(T --pane-file "$TMP/le-login-dialog-url.txt" 2>/dev/null | jq -r '.state')" unknown
ok "control: both dialog panes keep the dead transcript's result lines and draw no code prompt (so the box is what decides)" \
   "$(grep -c '^● Login expired · ' "$TMP/le-exit-dialog.txt" | tr -d ' '):$(grep -c '^● Login expired · ' "$TMP/le-login-dialog-url.txt" | tr -d ' '):$(grep -ciE 'Paste code here|paste the code|authorization code' "$TMP/le-login-dialog-url.txt" | tr -d ' ')" "6:6:0"
# The login dialog's success screen is a RECOVERY, not a no-box case: its own
# `Login successful` line clears the dead result before the box is ever asked about.
{ cat "$TMP/le-transcript.txt"; printf '❯ /login\n────────────────────────────────────────\n  Logged in as x@example.com\n  Login successful. Press Enter to continue…\n'; } > "$TMP/le-login-dialog-ok.txt"
ok "NOT login-expired: the login dialog's own success screen (its Login successful line clears it)" \
   "$(T --pane-file "$TMP/le-login-dialog-ok.txt" 2>/dev/null | jq -r '.state')" unknown
# ⚠️ A BOX ON SCREEN IS NOT A BOX WITH THE FOCUS. Dialogs drawn UNDER the box (plan
# approval, mode switch - layout approximated) leave it on screen, and the remedy's
# Enter would answer them. A numbered selector under the box refuses the state, and
# the pane reads the no-verdict `unknown` rather than falling through to `healthy`.
{ cat "$LE"; printf '\n  Switch to auto mode?\n  ❯ 1. Yes\n    2. No\n'; } > "$TMP/le-dialog-under-box.txt"
ok "a dialog drawn UNDER the box of a dead session: unknown, never login-expired or healthy" \
   "$(T --pane-file "$TMP/le-dialog-under-box.txt" 2>/dev/null | jq -r '.state')" unknown
ok "control: the no-verdict note forbids /login and Enter until the dialog is understood" \
   "$(T --pane-file "$TMP/le-dialog-under-box.txt" 2>/dev/null | jq -r '.note' | grep -c 'Do NOT type /login or Enter' | tr -d ' ')" 1
grep -v '❯ 1\. Yes' "$TMP/le-dialog-under-box.txt" > "$TMP/le-no-selector-under-box.txt"
ok "control: the SAME pane without the selector line reads login-expired (so the selector is what decides)" \
   "$(T --pane-file "$TMP/le-no-selector-under-box.txt" 2>/dev/null | jq -r '.state')" login-expired

# ⚠️ PRECEDENCE AGAINST usage-cap: login-expired wins. A cap banner is matched
# anywhere on the pane and lingers in the scrollback; the login line is the
# session's LAST word. And usage-cap's wait branch is wrong on a dead login - a
# session with no valid token never continues by itself at any reset - so reading
# this pane as a cap parks a dead agent behind a wait. Derived control: the same pane
# without its login lines must read usage-cap.
{ printf ' \xe2\x9a\xa0 You'"'"'ve hit your session limit \xc2\xb7 resets 10pm\n\n'; cat "$LE"; } > "$TMP/cap-then-login-expired.txt"
grep -vE '^● (Login expired · |Remote Control disconnected — OAuth token unavailable)' "$TMP/cap-then-login-expired.txt" > "$TMP/cap-no-login-lines.txt"
ok "a cap banner above a login-expired last message is login-expired" \
   "$(T --pane-file "$TMP/cap-then-login-expired.txt" 2>/dev/null | jq -r '.state')" login-expired
ok "control: the SAME pane without its login lines reads usage-cap" \
   "$(T --pane-file "$TMP/cap-no-login-lines.txt" 2>/dev/null | jq -r '.state')" usage-cap

# ⚠️ PRECEDENCE AGAINST working: a turn in flight wins, read off the markers a turn
# DRAWS - the interrupt hint in the tail. Derived control: the same pane without the
# hint reads login-expired.
sed 's/(shift+tab to cycle)$/(shift+tab to cycle) · esc to interrupt/' "$LE" > "$TMP/le-interrupt-hint.txt"
ok "the login-expired pane with an interrupt hint in its status bar is working" \
   "$(T --pane-file "$TMP/le-interrupt-hint.txt" 2>/dev/null | jq -r '.state')" working
ok "control: the hint was actually inserted" "$(grep -c 'esc to interrupt' "$TMP/le-interrupt-hint.txt" | tr -d ' ')" 1
# ⚠️ ...BUT THE WIDE-WINDOW MARKERS MAY NOT SUPPRESS IT, for the reason they may not
# suppress a cap or a code prompt: the agents panel is a VIEW that stays up whether
# or not turns are being taken, and the spinner is read from a window wide enough to
# take a quoted line. A dead agent read as `working` is the agent nobody revives.
# Each has a derived control: the same layout under the login-free transcript reads
# `working`, so the guard - not a non-matching marker - is what decides.
{ cat "$TMP/le-transcript.txt"; cat "$TMP/list-panel-box.txt"; } > "$TMP/le-plus-list-panel.txt"
{ cat "$TMP/le-transcript-no-login.txt"; cat "$TMP/list-panel-box.txt"; } > "$TMP/list-panel-no-login-lines.txt"
ok "subagents LISTED under a login-expired session's status bar: login-expired, not working" \
   "$(T --pane-file "$TMP/le-plus-list-panel.txt" 2>/dev/null | jq -r '.state')" login-expired
ok "control: the SAME listed panel under the login-free transcript reads working" \
   "$(T --pane-file "$TMP/list-panel-no-login-lines.txt" 2>/dev/null | jq -r '.state')" working
{ cat "$TMP/le-transcript.txt"; printf '· Scurrying… (19s · ↓ 691 tokens)\n'; cat "$TMP/le-ready-box.txt"; } > "$TMP/le-plus-spinner.txt"
{ cat "$TMP/le-transcript-no-login.txt"; printf '· Scurrying… (19s · ↓ 691 tokens)\n'; cat "$TMP/le-ready-box.txt"; } > "$TMP/spinner-no-login-lines.txt"
ok "a spinner line under a login-expired last message is login-expired, not working" \
   "$(T --pane-file "$TMP/le-plus-spinner.txt" 2>/dev/null | jq -r '.state')" login-expired
ok "control: the SAME spinner under the login-free transcript reads working" \
   "$(T --pane-file "$TMP/spinner-no-login-lines.txt" 2>/dev/null | jq -r '.state')" working
# The MANAGE-mode panel REPLACES the input box, so it is the no-box case above: the
# guard keeps the dead agent from reading `working`, and the missing box keeps the
# remedy's Enter off a panel - the pane reads `unknown`, a person's look.
{ cat "$TMP/le-transcript.txt"; cat "$F/agent-manage-panel.txt"; } > "$TMP/le-plus-manage-panel.txt"
{ cat "$TMP/le-transcript-no-login.txt"; cat "$F/agent-manage-panel.txt"; } > "$TMP/manage-panel-no-login-lines.txt"
ok "a MANAGE panel open over a login-expired transcript is unknown: neither working nor a typed remedy" \
   "$(T --pane-file "$TMP/le-plus-manage-panel.txt" 2>/dev/null | jq -r '.state')" unknown
ok "control: the SAME manage panel under the login-free transcript reads working" \
   "$(T --pane-file "$TMP/manage-panel-no-login-lines.txt" 2>/dev/null | jq -r '.state')" working
# The rule as a STATEMENT, for the reason the code-prompt twin above is one: branch
# order alone would keep most of these rows green with a guard deleted. Exactly the
# two wide-window markers carry it - counted on their own condition lines, not on any
# line that happens to mention it; a third owes the same guard and moves this number
# in the same commit.
ok "the agents-panel and spinner markers refuse to fire on a login-expired pane (the rule, not its effect)" \
   "$(grep -cE '^if \[ -z "\$cap_banner" \] && \[ "\$signin_prompt" = no \] && \[ "\$login_expired" = no \]' "$HERE/tmux_triage.sh" | tr -d ' ')" 2

# ⚠️ PRECEDENCE AGAINST stopped: `stopped` refines `healthy` only, so a dead login
# with no daemon running reads login-expired - a wake line into a logged-out session
# ends on one more `Login expired`. The daemon reading still travels in the object.
le_none="$(DT "$TMP/p-none" --pane-file "$LE")"
ok "login-expired with no daemon running stays login-expired, never stopped" \
   "$(jq -c '[.state, .daemons_running]' <<<"$le_none")" '["login-expired",0]'
ok "login-expired with both daemons running is still login-expired (daemons cannot see a dead login)" \
   "$(DT "$TMP/p-both" --pane-file "$LE" | jq -c '[.state, .daemons_running]')" '["login-expired",2]'

# ⚠️ REGIME CONTROLS: the text QUOTED is not the session SAYING it. Every pane below
# carries the login line, and none of them is a dead login: a markdown bullet in an
# agent's own message, a `cat` of this very fixture rendered as tool output, a
# `git diff` hunk, prose quoting it mid-line, and a message whose first paragraph is
# nothing but the line (inline-code backticks are not drawn, so it sits at column 0).
# The first three carry the line behind nothing but decoration - which the cap-style
# anchor admits, as the control on each proves.
anchored() { grep -cE '^[[:space:]]*[^[:alnum:]]*[[:space:]]*(Login expired · Please run /login|OAuth token unavailable)' "$1" | awk '$1>0{print "yes"} $1==0{print "no"}'; }
{ printf "● healer's pane ends every turn with:\n  - Login expired · Please run /login\n  and it read healthy on three sweeps.\n\n"; cat "$TMP/le-ready-box.txt"; } > "$TMP/fp-le-bullet.txt"
ok "NOT login-expired: a markdown bullet in an agent's own message" \
   "$(T --pane-file "$TMP/fp-le-bullet.txt" 2>/dev/null | jq -r '.state')" healthy
ok "control: that pane carries the line behind decoration only (so an anchor alone would have fired)" "$(anchored "$TMP/fp-le-bullet.txt")" yes
{ printf '● Bash(cat .claude/skills/agent-revive/fixtures/login-expired.txt)\n'
  awk -v row="$ROW" 'NR==1 {print row $0; next} {print "     " $0}' "$LE"
  printf '\n✻ Worked for 2s · done 9:14 AM\n\n'; cat "$TMP/le-ready-box.txt"; } > "$TMP/fp-le-cat.txt"
ok "NOT login-expired: a cat of the fixture, rendered as tool output" \
   "$(T --pane-file "$TMP/fp-le-cat.txt" 2>/dev/null | jq -r '.state')" healthy
ok "control: that pane carries the line behind decoration only" "$(anchored "$TMP/fp-le-cat.txt")" yes
{ printf '● Bash(git diff -- .claude/skills/agent-revive/fixtures/login-expired.txt)\n%s@@ -44,3 +44,5 @@\n' "$ROW"
  printf '     +● Login expired · Please run /login\n     +\n      ✻ Churned for 0s · done 7:22 AM\n\n'; cat "$TMP/le-ready-box.txt"; } > "$TMP/fp-le-diff.txt"
ok "NOT login-expired: a git diff hunk adding the line, rendered as tool output" \
   "$(T --pane-file "$TMP/fp-le-diff.txt" 2>/dev/null | jq -r '.state')" healthy
ok "control: that pane carries the line behind decoration only" "$(anchored "$TMP/fp-le-diff.txt")" yes
{ printf '● Its last result line reads "Login expired · Please run /login" on every turn.\n\n'; cat "$TMP/le-ready-box.txt"; } > "$TMP/fp-le-prose.txt"
ok "NOT login-expired: a top-level message quoting the line mid-sentence" \
   "$(T --pane-file "$TMP/fp-le-prose.txt" 2>/dev/null | jq -r '.state')" healthy
ok "control: that pane DOES carry the words" "$(grep -c 'Login expired · Please run /login' "$TMP/fp-le-prose.txt" | tr -d ' ')" 1
{ printf '● Login expired · Please run /login\n\n  That is what ada ends every turn on, so its sweep reads healthy.\n\n✻ Worked for 3s · done 9:20 AM\n\n'; cat "$TMP/le-ready-box.txt"; } > "$TMP/fp-le-first-paragraph.txt"
ok "NOT login-expired: a message whose first paragraph is only the line, with prose after it" \
   "$(T --pane-file "$TMP/fp-le-first-paragraph.txt" 2>/dev/null | jq -r '.state')" healthy
grep -v 'That is what ada' "$TMP/fp-le-first-paragraph.txt" > "$TMP/le-first-paragraph-alone.txt"
ok "control: the SAME pane without the second paragraph reads login-expired (so the paragraph is what decides)" \
   "$(T --pane-file "$TMP/le-first-paragraph-alone.txt" 2>/dev/null | jq -r '.state')" login-expired
# ⚠️ A RESULT ROW QUOTED IN AN AGENT'S MESSAGE sits two columns in, exactly where a
# real one does - and the fleet's agents quote panes as their job. Typed with ASCII
# spaces it lacks the drawn NBSP; copied from a capture it has it, and then the line
# it hangs under is what decides: a row under an agent's own prose is a quote. The
# control hangs the SAME drawn row under a Monitor event, which is how a real wake
# fails, and requires login-expired.
{ printf '● Sweep: ada is dead. Its pane ends on:\n\n  ⎿ OAuth token revoked · Please run /login\n\n✻ Worked for 4s · done 9:30 AM\n\n'; cat "$TMP/le-ready-box.txt"; } > "$TMP/fp-le-quoted-row.txt"
ok "NOT login-expired: a result row quoted (typed) in an agent's own message" \
   "$(T --pane-file "$TMP/fp-le-quoted-row.txt" 2>/dev/null | jq -r '.state')" healthy
{ printf '● Sweep: ada is dead. Its pane ends on:\n\n%sOAuth token revoked · Please run /login\n\n✻ Worked for 4s · done 9:30 AM\n\n' "$ROW"; cat "$TMP/le-ready-box.txt"; } > "$TMP/fp-le-quoted-drawn-row.txt"
ok "NOT login-expired: a result row with the drawn bytes, quoted in an agent's own message" \
   "$(T --pane-file "$TMP/fp-le-quoted-drawn-row.txt" 2>/dev/null | jq -r '.state')" healthy
sed 's/^● Sweep: ada is dead. Its pane ends on:$/● Monitor event: SLACK #general reply in thread 1 [ts 2] U0 [bot]: ping/' "$TMP/fp-le-quoted-drawn-row.txt" > "$TMP/le-row-under-monitor.txt"
ok "control: the SAME drawn row under a Monitor event reads login-expired (so the owner line is what decides)" \
   "$(T --pane-file "$TMP/le-row-under-monitor.txt" 2>/dev/null | jq -r '.state')" login-expired

# The drawn NBSP is what decides where the owner cannot: a person pasting a pane
# excerpt into a prompt puts a TYPED row under a prompt echo, an input line.
{ printf '❯ healer shows this on ada:\n  ⎿ OAuth token revoked · Please run /login\n\n'; cat "$TMP/le-ready-box.txt"; } > "$TMP/fp-le-pasted-row.txt"
ok "NOT login-expired: a typed result row pasted into a prompt (no drawn NBSP)" \
   "$(T --pane-file "$TMP/fp-le-pasted-row.txt" 2>/dev/null | jq -r '.state')" healthy

# ...and the other side of that rule: an error that WRAPS continues on the very next
# line, indented two, with no blank line - and stays a result.
{ cat "$TMP/le-transcript.txt"
  printf '● Please run /login · API Error: 401 {"type":"error","error":{"type":"authentication_error","message":"OAuth\n  token has expired"}}\n\n✻ Worked for 0s · done 9:40 AM\n\n'
  cat "$TMP/le-ready-box.txt"; } > "$TMP/le-wrapped-401.txt"
ok "a WRAPPED 401 result (continuation directly under it) is still login-expired" \
   "$(T --pane-file "$TMP/le-wrapped-401.txt" 2>/dev/null | jq -r '.state')" login-expired

# the note is the operator's whole instruction at this state; its properties are
# pinned, never its sentences.
le_note="$(T --pane-file "$LE" 2>/dev/null | jq -r '.note')"
ok "control: the login-expired note was actually read" "$([ -n "$le_note" ] && [ "$le_note" != null ] && echo yes || echo no)" yes
ok "login-expired note says the login EXPIRED" "$(grep -qi 'login .*expired\|expired login' <<<"$le_note" && echo yes || echo no)" yes
ok "login-expired note names the /login route at the ready prompt (step 3)" \
   "$(grep -q '/login' <<<"$le_note" && grep -q 'step 3' <<<"$le_note" && grep -qi 'ready prompt' <<<"$le_note" && echo yes || echo no)" yes
ok "login-expired note warns off the double Ctrl-C" "$(grep -q 'never a Ctrl-C' <<<"$le_note" && grep -qi 'quits Claude Code' <<<"$le_note" && echo yes || echo no)" yes
ok "login-expired note makes the SAME account the default (step 5)" \
   "$(grep -q 'SAME account' <<<"$le_note" && grep -q 'step 5' <<<"$le_note" && echo yes || echo no)" yes
ok "login-expired note puts the automated sign-in first (step 6)" \
   "$(grep -qi 'automated' <<<"$le_note" && grep -q 'step 6' <<<"$le_note" && echo yes || echo no)" yes
ok "login-expired note sends the reader to the input line before typing" \
   "$(grep -q 'unsent text' <<<"$le_note" && echo yes || echo no)" yes

# negative control
printf ' just some log output\n nothing to see here\n' > "$TMP/nothing.txt"
ok "negative control (unknown)" "$(T --pane-file "$TMP/nothing.txt" 2>/dev/null | jq -r '.state')" unknown

# --- URL join beats truncation ---
url="$(T --pane-file "$F/signin-url.txt" 2>/dev/null | jq -r '.signin_url')"
# what a naive single-line grep would have returned (the first https:// line's fragment):
naive="$(grep -oE 'https://[^ ]*' "$F/signin-url.txt" | head -1)"
ok "join: starts at https://claude.com" "$([[ "$url" == https://claude.com/cai/oauth/authorize* ]] && echo yes || echo no)" yes
ok "join: includes the redirect_uri (past the first wrap)" "$(grep -q 'redirect_uri=' <<<"$url" && echo yes || echo no)" yes
ok "join: includes the trailing state (the last chunk)" "$(grep -q 'state=abcdef0123456789deadbeefcafe' <<<"$url" && echo yes || echo no)" yes
ok "join is strictly longer than the truncating grep" "$([ "${#url}" -gt "${#naive}" ] && echo yes || echo no)" yes
# and prove the naive grep really WOULD have truncated (control on the control):
ok "control: naive grep DOES truncate here" "$(grep -q 'state=abcdef' <<<"$naive" && echo no || echo yes)" yes

# --- bootstrap-prompt extraction from a service unit ---
bp="$(T --bootstrap-prompt --unit-file "$F/agent-unit.service" 2>/dev/null)"
ok "bootstrap: extracts the prompt string" "$([[ "$bp" == You\ are\ the\ example\ agent* ]] && echo yes || echo no)" yes
ok "bootstrap: does NOT return the bare Enter" "$([ "$bp" != "Enter" ] && echo yes || echo no)" yes
ok "bootstrap: is the whole quoted prompt (ends at the closing quote)" "$([[ "$bp" == *"stand by." ]] && echo yes || echo no)" yes

# ⚠️ A unit that cannot be read must EXIT 2 from --bootstrap-prompt, not fall through.
# unit_text is read through a command substitution, so an `exit` inside it would kill
# only the subshell and the script would carry on with an empty string - failing later
# under the WRONG message ("no ExecStartPost line") and the WRONG code (1). These two
# assert the code, and the third asserts the message the operator actually needs.
ok "bootstrap: a missing --unit-file exits 2" "$(T --bootstrap-prompt --unit-file /no/such/unit.service >/dev/null 2>&1; echo $?)" 2
ok "bootstrap: an unreadable live unit exits 2" "$(T --bootstrap-prompt >/dev/null 2>&1; echo $?)" 2
unit_err="$(T --bootstrap-prompt 2>&1 >/dev/null)"
ok "bootstrap: says the UNIT could not be read, not 'no ExecStartPost line'" \
   "$(grep -q 'cannot read service unit' <<<"$unit_err" && ! grep -q 'no ExecStartPost' <<<"$unit_err" && echo yes || echo no)" yes

# --- --facts: how the agent signs in, from the unit's FLEET_AGENT_AUTH --------------
# token and api-key agents are never signed in through the browser: /agent-revive and
# /agent-health branch on this answer, so an unreadable unit is `unknown` and exit 1,
# never the `login` that would send a token agent through /login. The user-manager
# read, the switch and the dead-token pane are token_switch.test.py's.
printf 'CLAUDE_CODE_OAUTH_TOKEN=not-a-real-token\n' > "$TMP/auth.env"
auth_unit() { printf '[Service]\nEnvironment=CLAUDE_CONFIG_DIR=/nonexistent/.claude\nEnvironmentFile=%s\n%s' "$TMP/auth.env" "$1" > "$TMP/auth.service"; T --facts --unit-file "$TMP/auth.service" 2>/dev/null | jq -r '.auth'; }
ok "auth: a unit without FLEET_AGENT_AUTH is login (every unit written before the line)" "$(auth_unit '')" login
ok "auth: Environment=FLEET_AGENT_AUTH=token is token" "$(auth_unit $'Environment=FLEET_AGENT_AUTH=token\n')" token
ok "auth: api-key is api-key" "$(auth_unit $'Environment=FLEET_AGENT_AUTH=api-key\n')" api-key
ok "auth: the LAST assignment wins, as systemd reads a drop-in" \
   "$(auth_unit $'Environment=FLEET_AGENT_AUTH=token\n[Service]\nEnvironment="FLEET_AGENT_AUTH=login"\n')" login
ok "auth: an assignment among others on one Environment= line is read" \
   "$(auth_unit $'Environment=A=1 FLEET_AGENT_AUTH=api-key B=2\n')" api-key
ok "auth: a value outside login/token/api-key is unknown, exit 1" \
   "$(auth_unit $'Environment=FLEET_AGENT_AUTH=tokn\n'):$(T --facts --unit-file "$TMP/auth.service" >/dev/null 2>&1; echo $?)" "unknown:1"
ok "auth: a token unit whose credential file does not exist is a mismatch" \
   "$(printf '[Service]\nEnvironment=FLEET_AGENT_AUTH=token\nEnvironmentFile=/no/such/claude-auth.env\n' > "$TMP/auth.service"; T --facts --unit-file "$TMP/auth.service" 2>/dev/null | jq -r '.auth')" mismatch
ok "auth: an unreadable unit is unknown and exit 1 - never a default of login" \
   "$(T --facts --unit-file /no/such/unit.service 2>/dev/null | jq -r '.auth'):$(T --facts --unit-file /no/such/unit.service >/dev/null 2>&1; echo $?)" "unknown:1"

# --- current-account: which account did this session last sign in as? -----------
cj="$(claude_json_with "agent.example@example.com" have-account.json)"
ok "current-account: prints the email and nothing else" "$(T --current-account --claude-json "$cj" 2>/dev/null)" "agent.example@example.com"
ok "current-account: exits 0 when it can answer" "$(T --current-account --claude-json "$cj" >/dev/null 2>&1; echo $?)" 0

printf '{"someOtherKey":1}\n' > "$TMP/no-oauth.json"
ok "current-account: no oauthAccount -> exit 1, not a guess" "$(T --current-account --claude-json "$TMP/no-oauth.json" >/dev/null 2>&1; echo $?)" 1
ok "current-account: no oauthAccount -> stdout is EMPTY (never a fabricated answer)" \
   "$(T --current-account --claude-json "$TMP/no-oauth.json" 2>/dev/null | wc -c | tr -d ' ')" 0
ok "current-account: missing file -> exit 1" "$(T --current-account --claude-json /no/such/.claude.json >/dev/null 2>&1; echo $?)" 1

# config-dir resolution order: the unit's CLAUDE_CONFIG_DIR beats the fleet
# convention. Asserted through the failure message, which names the path it tried -
# with a negative control proving the two routes really do resolve differently.
err_unit="$(T --current-account --unit-file "$F/agent-unit.service" 2>&1 >/dev/null)"
err_conv="$(T --current-account 2>&1 >/dev/null)"
ok "resolve: the unit's CLAUDE_CONFIG_DIR wins" "$(grep -q '/nonexistent-example-home/.claude/.claude.json' <<<"$err_unit" && echo yes || echo no)" yes
ok "control: without the unit it falls back to agents_home (a DIFFERENT path)" \
   "$(grep -q '/nonexistent-example-home/' <<<"$err_conv" && echo no || echo yes)" yes

# --- CLAUDE_CONFIG_DIR: systemd's LAST assignment wins, not the first ------------
# `systemctl cat` prints the unit then every drop-in, and a drop-in is the normal way
# an Environment= is changed. `head -1` returns the assignment systemd DISCARDED -
# and the worst part is that the stale dir usually still EXISTS, so the lookup
# succeeds and prints ANOTHER account's email with exit 0. Also covered: several
# assignments on one Environment= line, and a quoted value, both of which are
# systemd-legal and both of which silently fell through to the convention path.
cat > "$TMP/dropin.service" <<'UNIT'
# /etc/systemd/system/claude-agent-testagent.service
[Service]
Environment=CLAUDE_CONFIG_DIR=/first-LOSES/.claude

# /etc/systemd/system/claude-agent-testagent.service.d/override.conf
[Service]
Environment=CLAUDE_CONFIG_DIR=/second-WINS/.claude
UNIT
err_dropin="$(T --current-account --unit-file "$TMP/dropin.service" 2>&1 >/dev/null)"
ok "config dir: the LAST assignment wins (a drop-in overrides the unit)" \
   "$(grep -q '/second-WINS/.claude/.claude.json' <<<"$err_dropin" && echo yes || echo no)" yes
ok "control: the LOSING assignment is not the one used" \
   "$(grep -q '/first-LOSES/' <<<"$err_dropin" && echo no || echo yes)" yes

cat > "$TMP/multi.service" <<'UNIT'
[Service]
Environment=FOO=bar CLAUDE_CONFIG_DIR=/multi/.claude
UNIT
err_multi="$(T --current-account --unit-file "$TMP/multi.service" 2>&1 >/dev/null)"
ok "config dir: found when it is not the first assignment on the line" \
   "$(grep -q '/multi/.claude/.claude.json' <<<"$err_multi" && echo yes || echo no)" yes
cat > "$TMP/quoted.service" <<'UNIT'
[Service]
Environment="CLAUDE_CONFIG_DIR=/quoted/.claude"
UNIT
err_quoted="$(T --current-account --unit-file "$TMP/quoted.service" 2>&1 >/dev/null)"
ok "config dir: found when the assignment is quoted" \
   "$(grep -q '/quoted/.claude/.claude.json' <<<"$err_quoted" && echo yes || echo no)" yes

# ⚠️ The convention fallback must end in the CONFIG DIR and then the file inside it.
# Dropping the `.claude` segment names a path that never exists, so the fallback
# degrades into "no recorded login" - turning a knowable answer into a guess, and
# only on the hosts the fallback exists for (no systemd, an unreadable unit), where
# nobody is watching.
ok "config dir: the convention fallback keeps the .claude segment" \
   "$(grep -q '/testagent/.claude/.claude.json' <<<"$err_conv" && echo yes || echo no)" yes

# --- accounts: the pool table, rendered from the REAL picker ---------------------
# Every case runs the real `--accounts` against agent-health's pool fixtures through
# the real pool_pick.py (fixtures/config.fixture.json's accounts block), with the
# clock pinned, as agent `alpha` - the fixture lease file has alpha on g and beta on
# f. pool_pick.test.py owns WHICH account the pick is and why; this section owns
# that the table renders the picker's answer faithfully, and that every state with
# no switch target shows none.
TA() { bash "$HERE/tmux_triage.sh" "$1" --config "$CFG" --accounts --now "$POOL_NOW" "${@:2}"; }
cj_g="$(claude_json_with "g@example.com" g-account.json)"
pool_users="$(jq -r '.[].username' "$POOL_FX/pool.json")"
ok "control: the pool fixture is present and names nine accounts (so the row checks below are not vacuous)" \
   "$(grep -c . <<<"$pool_users" | tr -d ' ')" 9

acc_out="$(TA alpha --claude-json "$cj_g" 2>/dev/null)"
acc_err="$(TA alpha --claude-json "$cj_g" 2>&1 >/dev/null)"
ok "accounts: a clean pick exits 0" "$(TA alpha --claude-json "$cj_g" >/dev/null 2>&1; echo $?)" 0
ok "accounts: one row per pool account, in pool order" "$(cut -f1 <<<"$acc_out")" "$pool_users"
ok "accounts: every row has three tab-separated columns" \
   "$(awk -F'\t' 'NF != 3' <<<"$acc_out" | wc -l | tr -d ' ')" 0
ok "accounts: the session's account is 'current'" "$(awk -F'\t' '$2=="current"{print $1}' <<<"$acc_out")" "g@example.com"
ok "accounts: another agent's lease reads 'leased-by-<agent>'" \
   "$(awk -F'\t' '$2 ~ /^leased-by-/{print $1"="$2}' <<<"$acc_out")" "f@example.com=leased-by-beta"
ok "accounts: exactly one row is 'next'" "$(awk -F'\t' '$2=="next"' <<<"$acc_out" | wc -l | tr -d ' ')" 1
# ⚠️ The table must render the PICKER'S answer, never a pick of its own. Read the
# picker directly and compare, so a table that drifted into computing `next` itself
# (a file-order rotation, say) reds here even while its answer looks plausible.
direct_pick="$(python3 "$HERE/../agent-health/pool_pick.py" --config "$CFG" --now "$POOL_NOW" \
               --agent alpha --current g@example.com 2>/dev/null | jq -r '.pick')"
ok "control: the picker itself names a pick on this fixture" "$([ -n "$direct_pick" ] && [ "$direct_pick" != null ] && echo yes || echo no)" yes
ok "accounts: 'next' is exactly the picker's pick" "$(awk -F'\t' '$2=="next"{print $1}' <<<"$acc_out")" "$direct_pick"
ok "accounts: every other row is 'free', with the picker's reason beside it" \
   "$(awk -F'\t' '$2=="free" && $3==""' <<<"$acc_out" | wc -l | tr -d ' ')" 0
ok "accounts: the excluded account says why" \
   "$(awk -F'\t' '$1=="a@example.com"{print $3}' <<<"$acc_out")" "excluded: Google rejects its sign-in"
ok "accounts: stderr carries the pick's reason" "$(grep -q '^pick: j@example.com' <<<"$acc_err" && echo yes || echo no)" yes

# The example twin is a pool the picker accepts: its first entry carries a
# `_comment` key, and an install copying it must not be refused for that.
printf '{"pool.example.one@example.com":{"agent":"alpha","since":"2026-10-16T06:00Z"}}\n' > "$TMP/ex-leases.json"
cj_ex="$(claude_json_with "pool.example.one@example.com" ex-account.json)"
ex_out="$(TA alpha --claude-json "$cj_ex" --pool-file "$EX_POOL" --lease-file "$TMP/ex-leases.json" 2>/dev/null)"
ok "accounts (example twin): two rows, current then next" \
   "$(cut -f1,2 <<<"$ex_out" | tr '\t\n' ': ')" "pool.example.one@example.com:current pool.example.two@example.com:next "

# --- accounts: every state with no switch target marks NO row 'next' -------------
# ⚠️ THE TABLE AND THE VERDICT MUST AGREE. With the table printed before the guards
# ran, stdout named a `next` while stderr said none could exist - and stdout is the
# documented interface, so a reader takes the half they already believed.
no_next() { awk -F'\t' '$2=="next"' <<<"$1" | wc -l | tr -d ' '; }
unk_out="$(TA alpha --claude-json "$TMP/no-oauth.json" 2>/dev/null)"
unk_err="$(TA alpha --claude-json "$TMP/no-oauth.json" 2>&1 >/dev/null)"
ok "unknown current account -> exit 1" "$(TA alpha --claude-json "$TMP/no-oauth.json" >/dev/null 2>&1; echo $?)" 1
ok "unknown current account -> no row is 'next', stderr names case 3b" \
   "$(no_next "$unk_out"):$(grep -q 'case 3b' <<<"$unk_err" && echo yes || echo no)" "0:yes"

two_out="$(TA beta --claude-json "$cj_g" 2>/dev/null)"
two_err="$(TA beta --claude-json "$cj_g" 2>&1 >/dev/null)"
ok "current account leased to ANOTHER agent (two sessions, one account) -> exit 1" \
   "$(TA beta --claude-json "$cj_g" >/dev/null 2>&1; echo $?)" 1
ok "...no row is 'next', and stderr says two sessions on one account" \
   "$(no_next "$two_out"):$(grep -q 'two sessions on one account' <<<"$two_err" && echo yes || echo no)" "0:yes"

mismatch_cj="$(claude_json_with "someone.else@example.com" mismatch.json)"
mm_out="$(TA alpha --claude-json "$mismatch_cj" 2>/dev/null)"
mm_err="$(TA alpha --claude-json "$mismatch_cj" 2>&1 >/dev/null)"
ok "current account in NO pool entry -> exit 1" "$(TA alpha --claude-json "$mismatch_cj" >/dev/null 2>&1; echo $?)" 1
ok "...no row is 'next', and stderr names case 4" \
   "$(no_next "$mm_out"):$(grep -q 'case 4' <<<"$mm_err" && echo yes || echo no)" "0:yes"

# Exhausted: every healthy account leased to somebody else.
jq '. + {"c@example.com":{"agent":"x"},"d@example.com":{"agent":"x"},"e@example.com":{"agent":"x"},"h@example.com":{"agent":"x"},"j@example.com":{"agent":"x"}}' \
  "$POOL_FX/leases.json" > "$TMP/all-leased.json"
ex_all_out="$(TA alpha --claude-json "$cj_g" --lease-file "$TMP/all-leased.json" 2>/dev/null)"
ex_all_err="$(TA alpha --claude-json "$cj_g" --lease-file "$TMP/all-leased.json" 2>&1 >/dev/null)"
ok "pool exhausted -> exit 1" "$(TA alpha --claude-json "$cj_g" --lease-file "$TMP/all-leased.json" >/dev/null 2>&1; echo $?)" 1
ok "...no row is 'next', and stderr says the pool is exhausted" \
   "$(no_next "$ex_all_out"):$(grep -q 'pool exhausted' <<<"$ex_all_err" && echo yes || echo no)" "0:yes"

# --- accounts: a SHARED lease is named, and a share pick is marked as one -----------
# Two accounts, three agents: bob and carl share y, ada holds x. bob's group has no
# free account to move to, so the pick is a share of x - and the table must mark x
# as next-shared-with-ada, not hide it behind its leased-by role.
printf '[{"username":"x@example.com","password":"fixture-not-real"},{"username":"y@example.com","password":"fixture-not-real"}]\n' > "$TMP/share-pool.json"
printf '{"x@example.com":{"agent":"ada","since":"2026-10-16T00:00Z"},"y@example.com":{"agents":["bob","carl"],"since":"2026-10-16T00:00Z"}}\n' > "$TMP/share-leases.json"
cp "$POOL_FX/ledger.md" "$TMP/share-ledger.md"
cj_y="$(claude_json_with "y@example.com" y-account.json)"
share_out="$(TA bob --claude-json "$cj_y" --pool-file "$TMP/share-pool.json" --lease-file "$TMP/share-leases.json" --ledger "$TMP/share-ledger.md" 2>/dev/null)"
ok "accounts (shared): bob is on y, and x is next as a share with ada" \
   "$(awk -F'\t' '{printf "%s:%s ", $1, $2}' <<<"$share_out")" "x@example.com:next-shared-with-ada y@example.com:current "
ok "accounts (shared): a share pick still exits 0" \
   "$(TA bob --claude-json "$cj_y" --pool-file "$TMP/share-pool.json" --lease-file "$TMP/share-leases.json" --ledger "$TMP/share-ledger.md" >/dev/null 2>&1; echo $?)" 0

# --- accounts: an input the picker cannot read STOPS, with no table --------------
nofile_err="$(TA alpha --claude-json "$cj_g" --pool-file /no/such/pool.json 2>&1 >/dev/null)"
ok "no pool file -> exit 1" "$(TA alpha --claude-json "$cj_g" --pool-file /no/such/pool.json >/dev/null 2>&1; echo $?)" 1
ok "no pool file -> says escalation, names case 8" \
   "$(grep -qi 'escalation' <<<"$nofile_err" && grep -q 'case 8' <<<"$nofile_err" && echo yes || echo no)" yes
printf '[{"username":"a@example.com","password":"truncated-pool-canary"},\n' > "$TMP/truncated.json"
ok "a truncated pool file -> exit 1" "$(TA alpha --claude-json "$cj_g" --pool-file "$TMP/truncated.json" >/dev/null 2>&1; echo $?)" 1
ok "a truncated pool file -> stdout carries NO table rows" \
   "$(TA alpha --claude-json "$cj_g" --pool-file "$TMP/truncated.json" 2>/dev/null | grep -c . | tr -d ' ')" 0
# A blank password is MALFORMED (case 9): the sign-in driver refuses to type it, so a
# table that lists the entry as fine reads as fine until a sign-in fails. The control
# is the same pool with a real (fake) password, which must render a table and name no
# case 9 - without it, the refusal could be any other fault of this hand-made pool.
printf '[{"username":"g@example.com","password":"fake-blank-ctl-pw"},{"username":"h@example.com","password":"  "}]\n' > "$TMP/blank-pw.json"
printf '[{"username":"g@example.com","password":"fake-blank-ctl-pw"},{"username":"h@example.com","password":"fake-h-pw"}]\n' > "$TMP/blank-pw-ctl.json"
blank_err="$(TA alpha --claude-json "$cj_g" --pool-file "$TMP/blank-pw.json" 2>&1 >/dev/null)"
ctl_out="$(TA alpha --claude-json "$cj_g" --pool-file "$TMP/blank-pw-ctl.json" 2>&1)"
ok "control: the same pool with a password renders rows and names no case 9" \
   "$(grep -q '^h@example.com' <<<"$ctl_out" && ! grep -q 'case 9' <<<"$ctl_out" && echo yes || echo no)" yes
ok "a whitespace-only password -> exit 1" "$(TA alpha --claude-json "$cj_g" --pool-file "$TMP/blank-pw.json" >/dev/null 2>&1; echo $?)" 1
ok "a whitespace-only password -> STOP, case 9, names the entry by index" \
   "$(grep -q 'STOP' <<<"$blank_err" && grep -q 'case 9' <<<"$blank_err" && grep -q 'pool entry 1' <<<"$blank_err" && echo yes || echo no)" yes
ok "a whitespace-only password -> stdout carries NO table rows" \
   "$(TA alpha --claude-json "$cj_g" --pool-file "$TMP/blank-pw.json" 2>/dev/null | grep -c . | tr -d ' ')" 0
ok "...and no password from that pool reaches either stream" \
   "$(grep -q 'fake-blank-ctl-pw\|fake-h-pw' <<<"$blank_err$ctl_out" && echo yes || echo no)" no
ok "no lease file -> exit 1 (never read as 'nothing leased')" \
   "$(TA alpha --claude-json "$cj_g" --lease-file /no/such/leases.json >/dev/null 2>&1; echo $?)" 1

# --- the picker is the SIBLING skill's script, reached through the fleet root ----
# No config key names it: tmux_triage.sh resolves its own path with every symlink
# followed and takes <fleet root>/.claude/skills/agent-health/pool_pick.py. An agent
# reaches the skill through a personal link, and the UNRESOLVED path is that link's
# directory, whose parent holds only the links the install chose - so a script that
# derived the fleet root without following the link finds no picker, or a stale one.
# The REAL script runs here through a link whose directory has no agent-health.
mkdir -p "$TMP/linkcfg/skills"; ln -s "$HERE" "$TMP/linkcfg/skills/agent-revive"
ok "control: the link directory has no agent-health beside it (so only the fleet root can supply the picker)" \
   "$([ -e "$TMP/linkcfg/skills/agent-health" ] && echo yes || echo no)" no
ok "accounts through a skill link: the picker is found through the fleet root, and 'next' is the picker's pick" \
   "$(bash "$TMP/linkcfg/skills/agent-revive/tmux_triage.sh" alpha --config "$CFG" --accounts --now "$POOL_NOW" --claude-json "$cj_g" 2>/dev/null | awk -F'\t' '$2=="next"{print $1}')" "$direct_pick"
# MUTATION CONTROL, so the case above cannot pass for a reason other than the link
# being followed: the same layout - a fleet tree with agent-health beside agent-revive,
# reached through a link - with `readlink -f` removed from a COPY must find no picker.
mkdir -p "$TMP/mfleet/.claude/skills/agent-revive" "$TMP/mlink/skills"
ln -s "$(readlink -f "$HERE/../agent-health")" "$TMP/mfleet/.claude/skills/agent-health"
sed 's/\$(readlink -f "\${BASH_SOURCE\[0\]}")/${BASH_SOURCE[0]}/' "$HERE/tmux_triage.sh" > "$TMP/mfleet/.claude/skills/agent-revive/tmux_triage.sh"
ln -s "$TMP/mfleet/.claude/skills/agent-revive" "$TMP/mlink/skills/agent-revive"
ok "control: the mutation applied (the real script follows its own link once, the copy never)" \
   "$(grep -c 'readlink -f "${BASH_SOURCE\[0\]}"' "$HERE/tmux_triage.sh" | tr -d ' '):$(grep -c 'readlink -f "${BASH_SOURCE\[0\]}"' "$TMP/mfleet/.claude/skills/agent-revive/tmux_triage.sh" | tr -d ' ')" "1:0"
ok "control: with the link NOT followed, the same call finds no picker (exit 2)" \
   "$(bash "$TMP/mlink/skills/agent-revive/tmux_triage.sh" alpha --config "$CFG" --accounts --now "$POOL_NOW" --claude-json "$cj_g" >/dev/null 2>&1; echo $?)" 2
ok "control: the unmutated script in that layout finds it (so the layout itself is sound)" \
   "$(cp "$HERE/tmux_triage.sh" "$TMP/mfleet/.claude/skills/agent-revive/tmux_triage.sh"; bash "$TMP/mlink/skills/agent-revive/tmux_triage.sh" alpha --config "$CFG" --accounts --now "$POOL_NOW" --claude-json "$cj_g" >/dev/null 2>&1; echo $?)" 0
mkdir -p "$TMP/bare-fleet/.claude/skills/agent-revive"; cp "$HERE/tmux_triage.sh" "$TMP/bare-fleet/.claude/skills/agent-revive/"
ok "a fleet tree without the agent-health skill -> exit 2 (a usage fault, not a verdict)" \
   "$(bash "$TMP/bare-fleet/.claude/skills/agent-revive/tmux_triage.sh" alpha --config "$CFG" --accounts --claude-json "$cj_g" >/dev/null 2>&1; echo $?)" 2

# --- the config default is `fleet where`, never a file beside the script ---------
# With neither --config nor $AGENT_REVIVE_CONFIG the install's config.json is what
# `fleet where agent-revive config.json` prints: the skill directory holds COMMON
# files only. $FLEET_BIN selects a fake that logs its arguments and answers with the
# fixture config, so the cases prove the call, that its answer is used, and that a
# failed resolution is a usage fault rather than a fall-through to some default.
printf '#!/usr/bin/env bash\nprintf "%%s\\n" "$*" >> "%s"\n[ "$*" = "where agent-revive config.json" ] && { printf "%%s\\n" "%s"; exit 0; }\nexit 3\n' \
  "$TMP/fake-fleet.log" "$CFG" > "$TMP/fake-fleet"
printf '#!/usr/bin/env bash\nprintf "%%s\\n" "%s"\n' "$TMP/no-such-dir/config.json" > "$TMP/fake-fleet-stale"
chmod +x "$TMP/fake-fleet" "$TMP/fake-fleet-stale"
NOCFG() { env -u AGENT_REVIVE_CONFIG FLEET_BIN="$1" bash "$HERE/tmux_triage.sh" testagent --pane-file "$F/healthy-pane.txt" "${@:2}"; }
ok "no --config and no AGENT_REVIVE_CONFIG: the config is fleet where's answer" \
   "$(NOCFG "$TMP/fake-fleet" 2>/dev/null | jq -r '.state')" healthy
ok "...and the fleet command was asked exactly that, once" "$(cat "$TMP/fake-fleet.log")" "where agent-revive config.json"
: > "$TMP/fake-fleet.log"
ok "--config wins: the fleet command is not consulted" \
   "$(NOCFG "$TMP/fake-fleet" --config "$CFG" 2>/dev/null | jq -r '.state'):$(grep -c . "$TMP/fake-fleet.log" | tr -d ' ')" "healthy:0"
ok "an answer naming no file -> exit 2 (the answer is used, not ignored)" \
   "$(NOCFG "$TMP/fake-fleet-stale" >/dev/null 2>&1; echo $?)" 2
nofleet_err="$(NOCFG "$TMP/no-such-fleet" 2>&1 >/dev/null)"
ok "a fleet command that fails -> exit 2, naming --config and AGENT_REVIVE_CONFIG as the remedy" \
   "$(NOCFG "$TMP/no-such-fleet" >/dev/null 2>&1; echo $?):$(grep -q 'pass --config or set AGENT_REVIVE_CONFIG' <<<"$nofleet_err" && echo yes || echo no)" "2:yes"

# --- SECURITY: no password from a pool file ever reaches the output --------------
# Checks BOTH streams, every state above, and the literal password strings of the
# fixture pool, the example twin and the truncated sentinel. A control proves those
# strings really are in the files, so this cannot pass by testing nothing.
# ⚠️ The truncated file is in the loop on purpose: the one path that could leak file
# BYTES is a JSON error echoed on the way out, and feeding only well-formed files
# exercises everything except the leak.
pw_re="$(jq -r '[.[].password | select(. != "")] | join("|")' "$POOL_FX/pool.json")|example-not-a-real-password|truncated-pool-canary"
ok "control: the pool fixture and the example twin really do contain the password strings" \
   "$(grep -q 'fixture-pw-j-not-real' "$POOL_FX/pool.json" && grep -q 'example-not-a-real-password-either' "$EX_POOL" && echo yes || echo no)" yes
leak=no; reached=0
for args in "--claude-json $cj_g" "--claude-json $cj_ex --pool-file $EX_POOL --lease-file $TMP/ex-leases.json" \
            "--claude-json $TMP/no-oauth.json" "--claude-json $mismatch_cj" \
            "--claude-json $cj_g --pool-file $TMP/truncated.json" "--claude-json $cj_g --lease-file $TMP/all-leased.json"; do
  # shellcheck disable=SC2086 - the args are space-free temp paths, split on purpose
  out="$(TA alpha $args 2>&1)"
  grep -qE "$pw_re" <<<"$out" && leak=yes
  grep -q '^pick: ' <<<"$out" && reached=$((reached + 1))
done
# ⚠️ POSITIVE EVIDENCE THE PICKER WAS REACHED. An absence of passwords is also what a
# run that died before reading the pool prints, so the scan counts only if the picker
# actually answered on every run that should reach it (all but the truncated pool).
ok "control: the picker answered on every well-formed run the scan read" "$reached" 5
ok "no password reaches stdout or stderr" "$leak" no

# --- --help prints the WHOLE header, not a truncated line range -----------------
# The header is the script's only documentation, and a pinned range truncates it
# invisibly as the header grows. Asserted against the header's FIRST and LAST lines.
helpout="$(T --help 2>/dev/null)"
first_hdr="$(sed -n '2p' "$HERE/tmux_triage.sh")"
last_hdr="$(awk 'NR>1 && /^#/ {l=$0; next} NR>1 {exit} END{print l}' "$HERE/tmux_triage.sh")"
ok "--help starts at the first header line" "$(grep -Fqx "$first_hdr" <<<"$helpout" && echo yes || echo no)" yes
ok "--help reaches the LAST header line (not truncated)" "$(grep -Fqx "$last_hdr" <<<"$helpout" && echo yes || echo no)" yes
ok "--help stops at the header (no code leaks in)" "$(grep -q 'set -uo pipefail' <<<"$helpout" && echo no || echo yes)" yes

# --- contract: a missing config is rejected, not defaulted ---
if T --pane-file "$F/healthy-pane.txt" --config /no/such/config.json >/dev/null 2>&1; then
  ok "missing config rejected" fail ok
else
  ok "missing config rejected" ok ok
fi

# --- cross-reference guard: SKILL.md step and case pointers resolve -------------
# Renumbering is what breaks these, and prose pointers are invisible to a symbol
# grep. A stale pointer sends an operator mid-revival to the wrong instruction.
have_steps="$(grep -oE '^### [0-9]+\.' "$SKILL" | grep -oE '[0-9]+' | sort -un)"
# ⚠️ THE GUARD READS EVERY FILE THAT CARRIES A `step N` POINTER - the sign-in driver
# and the install docs as well as the skill and the script - because a renumbering
# strands a pointer in a file nobody re-reads just as silently as one here. The
# glob is deliberate - a new file under
# signin_driver/ or installation/ is covered the day it lands, with no edit here -
# and the existence filter keeps a partial checkout from turning this into a grep
# error rather than a verdict.
# ⚠️ agent-health's pool_pick.py CARRIES STEP AND CASE POINTERS TOO, and so do the
# INSTALL's files: this skill's CONTEXT.md and the agent skill's CONTEXT.md, in the
# install context `fleet where` resolves (the fixture install in the fleet's CI).
# They are checked when present. The install's charters cite step numbers as well;
# they are install files this tree cannot see, so fixtures/charters/ stands in for
# them here, with a pointer wrapped across a line break as a real charter carries one.
# (The `--accounts` cases above are the one part of this file that does need
# agent-health beside it: the pool picker is a dependency of the skill, reached
# through the fleet root, so a tree without it cannot answer --accounts at all.)
CTX="$("${FLEET_BIN:-$HERE/../../../bin/fleet}" where agent-revive 2>/dev/null)" || CTX=""
ok "control: the install context resolves (fleet where agent-revive), so its CONTEXT.md is in the reference set" \
   "$([ -n "$CTX" ] && [ -f "$CTX/CONTEXT.md" ] && echo yes || echo no)" yes
REFSRC=("$SKILL" "$HERE/tmux_triage.sh")
for f in "$HERE"/signin_driver/*.mjs "$HERE"/signin_driver/*.md "$HERE"/installation/INSTRUCTION.md "$HERE"/installation/requirements.txt "$HERE"/installation/check "$HERE"/config.example.json "$HERE"/secrets/*.json "$HERE"/../agent-health/pool_pick.py "$HERE"/fixtures/charters/*.md ${CTX:+"$CTX/CONTEXT.md" "$CTX/../agent/CONTEXT.md"}; do
  [ -f "$f" ] && REFSRC+=("$f")
done
# ⚠️ NEWLINES ARE FLATTENED BEFORE MATCHING, AND WITHOUT IT THIS GUARD IS BLIND
# TO THE POINTERS HARDEST TO SPOT BY EYE. These are hard-wrapped prose files, so
# a pointer lands across a line break as often as not: a charter carries a live
# "`/agent-revive` step" / "5" split, and a line-oriented grep of
# that file reports it as carrying NO pointers at all. Adding a file to REFSRC
# while reading it line by line is worse than leaving it out - it manufactures
# the confidence that the file is covered. The definitions above stay line-
# anchored (`^### N.` is a heading and must be); only the REFERENCES are joined.
REFTEXT="$(cat "${REFSRC[@]}" | tr '\n' ' ')"
ref_steps="$(printf '%s' "$REFTEXT" | grep -oE '[Ss]tep [0-9]+' | grep -oE '[0-9]+' | sort -un)"
bad_steps=""
for n in $ref_steps; do grep -qx "$n" <<<"$have_steps" || bad_steps="$bad_steps $n"; done
ok "every 'step N' reference names a real SKILL.md step${bad_steps:+ (dangling:$bad_steps)}" "${bad_steps:-none}" none
have_cases="$(grep -ohoE '\*\*Case [0-9]+[a-z]?\*\*' "$SKILL" | grep -oE '[0-9]+[a-z]?' | sort -u)"
ref_cases="$(printf '%s' "$REFTEXT" | grep -oE '[Cc]ase [0-9]+[a-z]?' | grep -oE '[0-9]+[a-z]?' | sort -u)"
bad_cases=""
for n in $ref_cases; do grep -qx "$n" <<<"$have_cases" || bad_cases="$bad_cases $n"; done
ok "every 'case N' reference names a real SKILL.md case${bad_cases:+ (dangling:$bad_cases)}" "${bad_cases:-none}" none
# control on the guard: it must actually FIND references, or it passes by finding none.
ok "control: the guard found step references to check" "$([ "$(wc -w <<<"$ref_steps")" -ge 4 ] && echo yes || echo no)" yes
ok "control: the guard found case references to check" "$([ "$(wc -w <<<"$ref_cases")" -ge 4 ] && echo yes || echo no)" yes
# control on the FLATTENING, asserted against the guard's OWN reference text and
# not against a synthetic string. ⚠️ The first version of this control piped a
# two-line literal through `tr` and checked the result - which tests that `tr`
# works, not that this guard uses it, and stayed green with the flattening
# deleted. Read REFTEXT itself: if it still carries a newline, the references
# are being matched line by line and every wrapped pointer is invisible.
ok "control: the reference text is flattened (no newline survives in REFTEXT)" \
   "$(printf '%s' "$REFTEXT" | grep -c '^' | awk '$1<=1{print "yes"} $1>1{print "no"}')" yes
# control on the CHARTERS actually being in REFSRC: the wrapped pointer in the
# fixture charter is the one a line-oriented guard could not see, so its absence
# from the reference set means the charter is listed and unread.
ok "control: the fixture charter is in the reference set" \
   "$(printf '%s' "$REFTEXT" | grep -c 'the fleet.s health agent' | awk '$1>0{print "yes"} $1==0{print "no"}')" yes
ok "control: the fixture charter carries a step pointer split across a line break" \
   "$(grep -c '`/agent-revive` step$' "$HERE"/fixtures/charters/*.md | awk -F: '{n+=$NF} END{print (n>0?"yes":"no")}')" yes

# ── portable userland: no GNU-only grep ────────────────────────────────────────
# macOS's grep is BSD grep, which has no -P. This stand-in refuses -P the way it
# does and hands everything else to the real grep, so the bootstrap prompt is shown
# to be read without it on any system. The control proves the stand-in refuses,
# calling it by its path: the stand-in is what it measures.
mkdir -p "$TMP/bsd-grep"
printf '#!/bin/sh\nfor a in "$@"; do case "$a" in --) break ;; --*) ;; -*P*) echo "grep: invalid option -- P" >&2; exit 2 ;; esac; done\nexec %s "$@"\n' \
  "$(command -v grep)" > "$TMP/bsd-grep/grep"
chmod +x "$TMP/bsd-grep/grep"
ok "control: the BSD-grep stand-in refuses -P and passes -E through" \
   "$("$TMP/bsd-grep/grep" -oP 'x' <<<x >/dev/null 2>&1; echo $?):$(PATH="$TMP/bsd-grep:$PATH" grep -cE 'x' <<<x)" "2:1"
ok "bootstrap: the prompt is read with a grep that has no -P (BSD)" \
   "$(PATH="$TMP/bsd-grep:$PATH" T --bootstrap-prompt --unit-file "$F/agent-unit.service" 2>/dev/null)" \
   "$(T --bootstrap-prompt --unit-file "$F/agent-unit.service" 2>/dev/null)"

# ── macOS: the agent's unit is its launchd job's plist ─────────────────────────
# FLEET_SERVICE_BACKEND=launchd selects the plist reading, as it selects
# fleetlib.services' backend; HOME holds the user's ~/Library/LaunchAgents; the job
# is fixtures/agent-session.plist, in templates/claude-agent.plist.example's shape,
# whose boot message carries a double quote and XML escapes. Every other case in
# this file runs under FLEET_SERVICE_BACKEND=systemd, set at the top, so the file
# reads the same on both systems.
# The CONTROL: the same home and config under the systemd backend find no unit, so a
# fact read here is the plist's and not a fallback's.
LH="$TMP/launchd-home"
LCFG="$TMP/config.launchd.json"
LPLIST="$LH/Library/LaunchAgents/com.agent-fleet-test.session.testagent.plist"
jq '.fleet.systemd_unit = "com.agent-fleet-test.session.<agent>"
    | .fleet.tmux.tmpdir = "/tmp/fleet-fixture/agents/run/claude-tmux-<agent>"' "$CFG" > "$LCFG"
mkdir -p "$LH/Library/LaunchAgents" "$TMP/empty-home"
printf '# fleet-account: x@example.com\nCLAUDE_CODE_OAUTH_TOKEN=fixture-not-a-token\n' > "$TMP/l-auth.env"
sed "s#@AUTH_FILE@#$TMP/l-auth.env#" "$F/agent-session.plist" > "$LPLIST"
LT() { HOME="$LH" FLEET_SERVICE_BACKEND=launchd bash "$HERE/tmux_triage.sh" testagent --config "$LCFG" "$@"; }
LBOOT='You are Testagent, just restarted: arm "both" followers & check <status>.'

lfacts="$(LT --facts 2>/dev/null)"
ok "launchd: --facts reads the job's plist from ~/Library/LaunchAgents (scope user)" \
   "$(jq -r '.unit + " " + .unit_scope' <<<"$lfacts")" "com.agent-fleet-test.session.testagent user"
ok "launchd: the config dir is the plist's CLAUDE_CONFIG_DIR" \
   "$(jq -r '.config_dir' <<<"$lfacts")" "/nonexistent-fixture-home/testagent/.claude-from-plist"
ok "launchd: the tmux dir is the plist's TMUX_TMPDIR" \
   "$(jq -r '.tmux_tmpdir' <<<"$lfacts")" "/tmp/fleet-fixture/agents/run/claude-tmux-testagent"
ok "launchd: auth is the plist's FLEET_AGENT_AUTH, its file the supervisor's --env-file, its account the header" \
   "$(jq -r '[.auth, .auth_file, .auth_account] | join(" ")' <<<"$lfacts")" "token $TMP/l-auth.env x@example.com"
ok "launchd: --bootstrap-prompt is the supervisor's --boot argument, quote and escapes decoded" \
   "$(LT --bootstrap-prompt 2>/dev/null)" "$LBOOT"
ok "launchd: --unit-file takes a plist too, on any backend" \
   "$(T --bootstrap-prompt --unit-file "$LPLIST" 2>/dev/null)" "$LBOOT"
ok "control: under the systemd backend the same home and config find no unit" \
   "$(HOME="$LH" FLEET_SERVICE_BACKEND=systemd bash "$HERE/tmux_triage.sh" testagent --config "$LCFG" --facts 2>/dev/null | jq -r '[.unit_scope, .auth] | map(tostring) | join(" ")')" "null unknown"
lerr="$(HOME="$TMP/empty-home" FLEET_SERVICE_BACKEND=launchd bash "$HERE/tmux_triage.sh" testagent --config "$LCFG" --bootstrap-prompt 2>&1 >/dev/null)"; lrc=$?
ok "launchd: no plist -> --bootstrap-prompt exits 2 naming both plist paths" \
   "$lrc:$(grep -c "no readable plist at $TMP/empty-home/Library/LaunchAgents/com.agent-fleet-test.session.testagent.plist or /Library/LaunchDaemons/com.agent-fleet-test.session.testagent.plist" <<<"$lerr" | tr -d ' ')" "2:1"
ok "launchd: no plist -> auth unknown, never login" \
   "$(HOME="$TMP/empty-home" FLEET_SERVICE_BACKEND=launchd bash "$HERE/tmux_triage.sh" testagent --config "$LCFG" --facts 2>/dev/null | jq -r '.auth')" unknown

# ── macOS: a protected agent (its session a LaunchDaemon) is token-only ─────────
# With an administrator a macOS agent's session is a LaunchDaemon, which has no
# window server and no login Keychain, so it signs in only with a token or an API
# key. FLEET_LAUNCHD_SYSTEM_DIR is fleetlib's seam for /Library/LaunchDaemons. The
# CONTROL is the same login job as a LaunchAgent (the no-admin GUI form): a login
# agent there, so `unknown` below is the LaunchDaemon deciding, not the word login.
# setauth SRC DST MODE - the fixture plist with FLEET_AGENT_AUTH set to MODE.
setauth() {
  python3 -c 'import plistlib, sys; d = plistlib.load(open(sys.argv[1], "rb")); d["EnvironmentVariables"]["FLEET_AGENT_AUTH"] = sys.argv[3]; plistlib.dump(d, open(sys.argv[2], "wb"))' "$1" "$2" "$3"
}
LSYS="$TMP/launchd-system"; LUSR="$TMP/launchd-login-home/Library/LaunchAgents"
mkdir -p "$LSYS" "$LUSR"
setauth "$LPLIST" "$LSYS/com.agent-fleet-test.session.testagent.plist" token
LDT() { HOME="$TMP/empty-home" FLEET_SERVICE_BACKEND=launchd FLEET_LAUNCHD_SYSTEM_DIR="$LSYS" bash "$HERE/tmux_triage.sh" testagent --config "$LCFG" "$@"; }
ok "launchd: a LaunchDaemon session is read from the system directory (scope system), a token agent" \
   "$(LDT --facts 2>/dev/null | jq -r '[.unit_scope, .auth] | join(" ")')" "system token"
setauth "$LPLIST" "$LSYS/com.agent-fleet-test.session.testagent.plist" login
ld_facts="$(LDT --facts 2>/dev/null)"; ld_rc=$?
ok "launchd: a LaunchDaemon session set to login is auth unknown, exit 1, its problem naming the LaunchDaemon" \
   "$ld_rc:$(jq -r '.auth + " " + ((.auth_problem // "") | test("LaunchDaemon.*token or an API key") | tostring)' <<<"$ld_facts")" "1:unknown true"
setauth "$LPLIST" "$LUSR/com.agent-fleet-test.session.testagent.plist" login
ok "control: the same login job as a LaunchAgent (the no-admin form) is a login agent" \
   "$(HOME="$TMP/launchd-login-home" FLEET_SERVICE_BACKEND=launchd FLEET_LAUNCHD_SYSTEM_DIR="$TMP/no-such-dir" bash "$HERE/tmux_triage.sh" testagent --config "$LCFG" --facts 2>/dev/null | jq -r '[.unit_scope, .auth] | join(" ")')" "user login"

# ── macOS: daemon liveness from agent-daemons.py status, not /proc ─────────────
# macOS has no /proc and does not show another process's environment, so under the
# launchd backend (with no injected proc root) the reading is this agent's own daemon
# jobs as `agent-daemons.py status <agent> --json` reports them, with each running
# process's argv. AGENT_REVIVE_DAEMONS_STATUS is a stand-in that answers ONLY the
# exact call for this agent and prints a canned answer with a canned exit code.
LDCFG="$TMP/config.launchd-daemons.json"
jq '.fleet.daemons = [{"name":"watch","pattern":"slack-communication/watch.py"},
                      {"name":"sched","pattern":"scheduled-tasks/sched.py"}]' "$LCFG" > "$LDCFG"
# lstatus (defined in the per-follower section) writes each stand-in.
J_SCHED='"sched":{"unit":"com.agent-fleet-test.sched.testagent","active":"active","pid":5001,"argv":["/opt/homebrew/bin/python3","-u","/x/.claude/skills/scheduled-tasks/sched.py"]}'
J_WATCH='"slack-watch":{"unit":"com.agent-fleet-test.slack-watch.testagent","active":"active","pid":5002,"argv":["/opt/homebrew/bin/python3","-u","/x/.claude/skills/slack-communication/watch.py"]}'
J_SCHED_DOWN='"sched":{"unit":"com.agent-fleet-test.sched.testagent","active":"inactive","pid":0,"argv":null}'
J_WATCH_DOWN='"slack-watch":{"unit":"com.agent-fleet-test.slack-watch.testagent","active":"failed","pid":0,"argv":null}'
J_SCHED_UNREAD='"sched":{"unit":"com.agent-fleet-test.sched.testagent","active":"active","pid":5001,"argv":null}'
lstatus both 0 "{\"agent\":\"testagent\",\"backend\":\"launchd\",\"jobs\":{$J_SCHED,$J_WATCH}}"
lstatus none 1 "{\"agent\":\"testagent\",\"backend\":\"launchd\",\"jobs\":{$J_SCHED_DOWN,$J_WATCH_DOWN}}"
lstatus unread 0 "{\"agent\":\"testagent\",\"backend\":\"launchd\",\"jobs\":{$J_SCHED_UNREAD,$J_WATCH}}"
lstatus garbage 3 "agent-daemons.py: the fleet is not installed on this host"
LD() { local st="$1"; shift; HOME="$LH" FLEET_SERVICE_BACKEND=launchd AGENT_REVIVE_DAEMONS_STATUS="$TMP/st-$st" \
  bash "$HERE/tmux_triage.sh" testagent --config "$LDCFG" --pane-file "$IDLE" "$@" 2>/dev/null; }
ok "launchd daemons: both jobs active with the patterns in their argv -> healthy, 2 running" \
   "$(LD both | jq -c '[.state, .daemons, .daemons_running]')" '["healthy",{"watch":true,"sched":true},2]'
ok "launchd daemons: both jobs down -> stopped; agent-daemons.py's exit 1 does not void its JSON" \
   "$(LD none | jq -c '[.state, .daemons, .daemons_running]')" '["stopped",{"watch":false,"sched":false},0]'
ok "launchd daemons: an active job whose argv cannot be read -> null for the unmatched daemon, no verdict" \
   "$(LD unread | jq -c '[.state, .daemons, .daemons_running]')" '["healthy",{"watch":true,"sched":null},null]'
ok "launchd daemons: no JSON from agent-daemons.py -> every daemon null, never stopped" \
   "$(LD garbage | jq -c '[.state, .daemons, .daemons_running]')" '["healthy",{"watch":null,"sched":null},null]'
ok "control: an injected proc root wins over the launchd route (the procfs cases above run on macOS too)" \
   "$(AGENT_REVIVE_PROC_ROOT="$TMP/p-none" LD both | jq -c '.daemons')" '{"watch":false,"sched":false}'
# The launchd route reads no follower: with both jobs configured and down, the agent
# is still `stopped` (a null per follower would have blocked it), and followers is
# empty while followers_expected names the jobs.
lstatus none-conf 1 "{\"agent\":\"testagent\",\"backend\":\"launchd\",\"jobs\":{$(sed 's/"active":/"configured":true,"active":/' <<<"$J_SCHED_DOWN"),$(sed 's/"active":/"configured":true,"active":/' <<<"$J_WATCH_DOWN")}}"
ok "launchd: configured jobs down -> stopped, no follower read, the expected set still named" \
   "$(LD none-conf | jq -c '[.state, .followers, .followers_expected, .followers_down]')" '["stopped",{},["sched","slack-watch"],[]]'
# A replaced log IS read on the launchd route (agent-daemons.py answers through lsof
# there), so a Mac agent whose watcher writes to one reads follower-down.
lstatus repl-ld 1 "{\"agent\":\"testagent\",\"backend\":\"launchd\",\"jobs\":{$(sed 's/"active":/"configured":true,"active":/' <<<"$J_SCHED"),$(sed 's/"active":/"configured":true,"log_replaced":"writes to a replaced log (\/x\/slack-watch.log: deleted)","active":/' <<<"$J_WATCH")}}"
ok "launchd: both jobs active, the watcher writing to a replaced log -> follower-down, the job in logs_replaced" \
   "$(LD repl-ld | jq -c '[.state, .daemons_running, .followers, .logs_replaced]')" '["follower-down",2,{},["slack-watch"]]'

# The same route fed by the REAL `agent-daemons.py status --json`, not a stand-in, so
# a change to that command's JSON reds here rather than silently reading every
# daemon as null. The fleet's fake launchctl holds one loaded job, the scheduler,
# whose pid is a real process this file starts with the scheduler's path in its argv
# (read through fleetlib.services: procfs, or the kernel's on macOS); the watcher
# has no job at all.
RD="$TMP/real-daemons"
mkdir -p "$RD/agents/testagent"
python3 -c 'import time; time.sleep(120)' "$RD/x/.claude/skills/scheduled-tasks/sched.py" &
rd_sleeper=$!
python3 -c 'import plistlib, sys; plistlib.dump({"Label": sys.argv[2], "ProgramArguments": ["python3", "-u", "sched.py"], "RunAtLoad": True, "KeepAlive": {"SuccessfulExit": False}}, open(sys.argv[1], "wb"))' \
  "$RD/sched.plist" "com.agent-fleet.sched.testagent"
printf '{"next_pid": %s}\n' "$rd_sleeper" > "$RD/launchd.json"
RENV=(env FLEET_SERVICE_BACKEND=launchd FLEET_LAUNCHCTL="$HERE/../../../tests/fixtures/launchd/fake-launchctl"
      FAKE_LAUNCHD_STATE="$RD/launchd.json" FAKE_LAUNCHD_CALLS="$RD/calls" AGENT_DAEMONS_ROOT="$RD/agents" HOME="$LH")
"${RENV[@]}" "$HERE/../../../tests/fixtures/launchd/fake-launchctl" bootstrap "gui/$(id -u)" "$RD/sched.plist"
rd_status="$("${RENV[@]}" python3 "$HERE/../../../systemd/agent-daemons.py" status testagent --json 2>/dev/null)"
ok "control: the real agent-daemons.py reports the loaded scheduler running on the sleeper's pid" \
   "$(jq -r '.jobs.sched.active + " " + (.jobs.sched.pid | tostring)' <<<"$rd_status" 2>/dev/null)" "active $rd_sleeper"
ok "launchd daemons from the REAL agent-daemons.py: the running scheduler's argv carries its pattern, the absent watcher reads false" \
   "$("${RENV[@]}" bash "$HERE/tmux_triage.sh" testagent --config "$LDCFG" --pane-file "$IDLE" 2>/dev/null | jq -c '[.state, .daemons]')" \
   '["healthy",{"watch":false,"sched":true}]'
kill "$rd_sleeper"
wait "$rd_sleeper" 2>/dev/null

# ── the tap-to-solve share's input restriction: its STATEMENT, pinned unattended ──
# signin_driver/share.test.mjs proves what these x11vnc flags DO - on a throwaway
# Xvfb, against an unrestricted control - but it needs X, x11vnc and a browser, and a
# machine without them gets NO VERDICT from it. This pins what the flags ARE, so an
# edit that widens what a person on a public share can do reds here on any machine. If it
# reds on purpose: re-run share.test.mjs and get its half A green FIRST, then re-pin.
SHARE_MJS="$HERE/signin_driver/share.mjs"
ok "share.mjs restricts x11vnc input to the pointer and the left button, no clipboard, no remote control" \
   "$(grep -cxF "export const INPUT_FLAGS = ['-input', 'MB', '-buttonmap', '1-1=1', '-nosel', '-safer'];" "$SHARE_MJS")" 1
ok "...and every x11vnc it starts carries those flags, bound to loopback, one viewer at a time, reading no rc file" \
   "$(tr '\n' ' ' < "$SHARE_MJS" | grep -cE "'-localhost',.*'-nevershared',.*'-norc', \.\.\.INPUT_FLAGS\]")" 1
ok "control: share.mjs is where the pin looks (so a zero above is not a missing file)" \
   "$([ -r "$SHARE_MJS" ] && grep -c 'export function x11vncArgs' "$SHARE_MJS")" 1

echo ""; echo "passed $pass, failed $fail"
[ "$fail" -eq 0 ]
