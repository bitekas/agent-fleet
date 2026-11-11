#!/usr/bin/env bash
# ai-attribution.test.sh - teeth for tools/commit-hygiene/ai-attribution.sh,
# its pattern file, and the commit-msg and pre-push hooks that call it.
#
# Run: bash tools/commit-hygiene/ai-attribution.test.sh   (tests/run-all.sh runs it)
#
# A hook is a gate only on the clones where it is enabled, and nothing
# announces a clone where it is not. So this file proves two things and claims
# no third: the strip and check LOGIC (sections 1-9), and that a real
# `git commit` / `git push` through .githooks runs it (sections 10-11). Whether
# the hook ran on the machine that authored a pushed commit is CI's job: the
# commit-hygiene job runs check-range over every pushed range.
#
# Sections 1-5 carry the verdicts of the AI-attribution hook test this
# repository's strip was taken from, case for case. Every test message is
# built at runtime with printf, so no line of this file starts with an
# attribution phrase.
#
# THE REGIME CONTROL (section 6b): each pattern line alone must strip the case
# it is named for, and with that line deleted the case must survive. Without
# it, a case could pass because another line happens to catch it, and the line
# it is named for could be deleted with nothing red.
set -u
REPO_ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../.." && pwd)"
SCRIPT="$REPO_ROOT/tools/commit-hygiene/ai-attribution.sh"
ERE="$REPO_ROOT/tools/commit-hygiene/ai-attribution.ere"

checks=0; fails=0
ok()  { checks=$((checks + 1)); echo "ok  : $1"; }
bad() { checks=$((checks + 1)); fails=$((fails + 1)); echo "FAIL: $1"; }

[ -f "$SCRIPT" ] || { echo "FAIL: $SCRIPT not found"; exit 1; }
bash -n "$SCRIPT" || { echo "FAIL: $SCRIPT is not valid bash"; exit 1; }
ok "script parses"

# A scrubbed git environment: nothing inherited from a hook or an agent unit.
for v in $(env | sed -n 's/^\(GIT_[A-Za-z0-9_]*\)=.*/\1/p'); do unset "$v"; done
WORK="$(mktemp -d)" || { echo "FAIL: mktemp"; exit 1; }
trap 'rm -rf -- "${WORK:?}"' EXIT INT TERM HUP
export GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL="$WORK/gitconfig" HOME="$WORK/home"
mkdir -p "$HOME"
printf '[user]\n\tname = Fixture Tester\n\temail = tester@example.com\n[init]\n\tdefaultBranch = main\n' > "$GIT_CONFIG_GLOBAL"

strip() { bash "$SCRIPT" strip "$1"; }
CO='Co-Authored-By'   # assembled into messages at runtime only

# -- 1. AI trailers are stripped ------------------------------------------------
M="$WORK/m1"; printf 'feat: x\n\nBody.\n\n%s: Claude Opus 5 <noreply@anthropic.com>\nClaude-Session: http://x\n' "$CO" > "$M"
strip "$M" >/dev/null 2>&1
if grep -qiE 'claude|anthropic' "$M"; then bad "AI trailers survived the strip"; else ok "AI trailers stripped (co-author trailer, Claude-Session trailer)"; fi

# -- 1b. NEGATIVE CONTROL: the strip is targeted, not blanket --------------------
# Without it, section 1 is satisfied by a strip that deletes every trailer, or
# empties the file: "no claude in the output" is true of both.
M="$WORK/m1b"; printf 'feat: x\n\n%s: A Human <h@example.com>\n' "$CO" > "$M"
strip "$M" >/dev/null 2>&1
if grep -q 'A Human' "$M"; then ok "a human co-author trailer is preserved"; else bad "the strip removed a human co-author"; fi

# -- 1c. a "Generated with Claude Code" line is stripped; prose about it is not --
M="$WORK/m1c"; printf 'feat: x\n\nBody.\n\n\xf0\x9f\xa4\x96 Generated with [Claude Code](https://claude.com/claude-code)\nGenerated with Claude Code\n' > "$M"
strip "$M" >/dev/null 2>&1
if grep -qi 'generated with' "$M"; then bad "a Generated-with-Claude-Code line survived"; else ok "Generated-with-Claude-Code lines stripped (emoji+link form, bare form)"; fi
M="$WORK/m1d"; printf 'fix: x\n\nThe Claude Code skill loader now reads the context root.\nWe strip the Generated with Claude Code footer in the hook.\n' > "$M"
strip "$M" >/dev/null 2>&1
if grep -q 'skill loader' "$M" && grep -q 'We strip the Generated' "$M"; then ok "prose mentioning Claude Code, or the footer phrase mid-sentence, is preserved"
else bad "the strip removed a prose line"; fi

# -- 2. body preserved; the blank line the strip orphaned is collapsed ------------
M="$WORK/m2"; printf 'feat: x\n\nBody line.\n\nClaude-Session: http://x\n' > "$M"
strip "$M" >/dev/null 2>&1
if [ "$(cat "$M")" = "$(printf 'feat: x\n\nBody line.')" ]; then ok "body preserved, trailing blank run collapsed"
else bad "unexpected message after strip: $(tr '\n' '/' < "$M")"; fi

# -- 2b. THE SUBJECT LINE: which shapes survive, and the documented constraint ---
# The patterns are anchored to the LINE start, not the line's position, so
# they reach line 1. Both directions are asserted because only the pair pins
# the boundary: an ordinary subject survives, and a `Claude-<word>:` subject
# (any case) is eaten - the constraint ai-attribution.sh documents.
for subj in 'fix(ci): stop the nightly gate reading a stale sampler' 'docs(repo): x' 'Claudette: chore(x): z'; do
  M="$WORK/m2b"; printf '%s\n\nBody.\n' "$subj" > "$M"
  strip "$M" >/dev/null 2>&1
  if [ "$(head -1 "$M")" = "$subj" ]; then ok "subject survives: ${subj%%:*}:"; else bad "the strip ate the subject ${subj%%:*}:"; fi
done
for subj in 'Claude-Ops: fix(ci): y' 'claude-ops: fix(ci): y'; do
  M="$WORK/m2c"; printf '%s\n\nBody.\n' "$subj" > "$M"
  strip "$M" >/dev/null 2>&1
  if [ "$(head -1 "$M")" != "$subj" ]; then ok "a ${subj%%:*}: subject is eaten (documented constraint)"
  else bad "a ${subj%%:*}: subject survived - the documented constraint in ai-attribution.sh is now wrong"; fi
done

# -- 3. strip is silent and exits 0 on a clean message ---------------------------
M="$WORK/m3"; printf 'feat: touch a file\n\nBody.\n' > "$M"
out="$(strip "$M" 2>&1)"; rc=$?
[ -z "$out" ] && [ "$rc" -eq 0 ] && [ "$(cat "$M")" = "$(printf 'feat: touch a file\n\nBody.')" ] \
  && ok "silent, exit 0 and unchanged on a clean message" || bad "clean message: rc=$rc out='$out'"

# -- 4. a merge-shaped message is stripped like any other -----------------------
M="$WORK/m4"; printf "Merge branch 'x'\n\nClaude-Session: http://x\n" > "$M"
out="$(strip "$M" 2>&1)"; rc=$?
if [ -z "$out" ] && [ "$rc" -eq 0 ] && ! grep -qi claude "$M"; then ok "a merge message is stripped, silently"
else bad "merge message mishandled (rc=$rc out='$out')"; fi

# -- 5. a missing TMPDIR does not break the strip ------------------------------
M="$WORK/m5"; printf 'feat: x\n\nClaude-Session: http://x\n' > "$M"
out="$(TMPDIR="$WORK/no-such-tmpdir" bash "$SCRIPT" strip "$M" 2>&1)"; rc=$?
if [ "$rc" -eq 0 ] && [ -z "$out" ] && ! grep -qi claude "$M"; then ok "with TMPDIR missing, the strip still runs, silently, exit 0"
else bad "with TMPDIR missing: rc=$rc out='$out'"; fi
leftover="$(find "$WORK" -maxdepth 1 -name 'm5.*' | head -1)"
[ -z "$leftover" ] && ok "its temp file is removed" || bad "temp file left behind: $leftover"

# -- 6. the fourth line: the variants -------------------------------------------
M="$WORK/m6"; printf 'feat: x\n\nBody.\nMade with Claude\n\xf0\x9f\xa4\x96 Written by [Claude]\nCreated using Claude\nClaude Code 2.1.320 changed the footer\n' > "$M"
strip "$M" >/dev/null 2>&1
if grep -qE '^(Made with|.*Written by|Created using)' "$M"; then bad "a fourth-line variant survived: $(tr '\n' '/' < "$M")"
else ok "Made with / Written by [...] / Created using Claude lines stripped"; fi
if grep -q 'Claude Code 2.1.320 changed the footer' "$M"; then ok "a line about Claude Code that is not an attribution is kept"
else bad "the strip removed 'Claude Code 2.1.320 changed the footer'"; fi

# -- 6b. REGIME CONTROL: each pattern line catches its case on its own -----------
# (a) A file holding ONLY line N strips case N: the line works by itself.
# (b) A file holding every line BUT N lets case N survive, for N = 1, 2, 4, 5
#     and 6: no other line covers for it, so deleting it would be seen. Lines 5
#     and 6 are lines 1 and 2 behind an indent or a `>` quote; lines 1 and 2
#     need column 0 and lines 5 and 6 need a prefix, so neither pair covers the
#     other.
#     Line 4 is a superset of line 3 (every line line 3 matches, line 4 matches
#     too), so for N = 3 the case is still stripped, and that is asserted: line
#     3 stays because it is the inherited expression's text, unchanged, and the
#     day line 4 stops covering it this check says so.
# case_for_line N prints the message line pattern line N is named for.
case_for_line() {
  case "$1" in
    1) printf '%s: Claude <noreply@anthropic.com>' "$CO" ;;
    2) printf 'Claude-Session: http://x' ;;
    3) printf '\xf0\x9f\xa4\x96 Generated with Claude Code' ;;
    4) printf 'Made with Claude' ;;
    5) printf '    %s: Claude <noreply@anthropic.com>' "$CO" ;;
    6) printf '> Claude-Session: http://x' ;;
  esac
}
nlines="$(wc -l < "$ERE")"
[ "$nlines" -eq 6 ] && ok "the pattern file has its six lines" || bad "the pattern file has $nlines lines, the regime control below covers 6"
# strip_with <pattern-file-content> <line>: prints 1 if <line> survives a strip, else 0
strip_with() {
  local D; D="$(mktemp -d "$WORK/regime.XXXXXX")"
  cp "$SCRIPT" "$D/ai-attribution.sh"
  printf '%s\n' "$1" > "$D/ai-attribution.ere"
  printf 'feat: x\n\nBody.\n%s\n' "$2" > "$D/msg"
  bash "$D/ai-attribution.sh" strip "$D/msg" >/dev/null 2>&1
  grep -cF -- "$2" "$D/msg"
}
for n in 1 2 3 4 5 6; do
  line="$(case_for_line "$n")"
  only="$(sed -n "${n}p" "$ERE")"
  others="$(sed "${n}d" "$ERE")"
  [ "$(strip_with "$only" "$line")" -eq 0 ] && ok "pattern line $n alone strips its case" \
    || bad "pattern line $n alone does not strip its case"
  survived="$(strip_with "$others" "$line")"
  if [ "$n" -eq 3 ]; then
    [ "$survived" -eq 0 ] && ok "pattern line 4 still covers line 3's case (line 4 is a superset of line 3)" \
      || bad "line 3's case survives without line 3: line 4 no longer covers it - update section 6b"
  else
    [ "$survived" -eq 1 ] && ok "without pattern line $n its case survives (no other line covers it)" \
      || bad "without pattern line $n its case is still stripped - the check cannot see line $n deleted"
  fi
done

# -- 6c. bytes that are not text: a NUL line, an invalid-UTF-8 prefix -------------
# Without grep -a, a NUL makes grep print "binary file matches" instead of the
# kept lines; without LC_ALL=C, an invalid UTF-8 byte before "Generated" is not
# a non-alphanumeric CHARACTER in a UTF-8 locale and the footer survives.
M="$WORK/m6c"; printf 'feat: x\n\nkeep\0this\n\xffGenerated with Claude Code\nlast line\n' > "$M"
LANG=C.UTF-8 strip "$M" >/dev/null 2>&1
if [ "$(head -1 "$M")" = "feat: x" ] && grep -aq 'last line' "$M" && grep -aq 'keep' "$M" && ! grep -aq 'Generated with' "$M"; then
  ok "a message with a NUL and an invalid-UTF-8 footer prefix is stripped line by line"
else bad "NUL / invalid UTF-8 message mishandled: $(tr '\0\n' '@/' < "$M")"; fi

# -- 6d. indented and quoted trailers: stripped, checked, and nothing else ------
# `git merge --squash` writes each squashed commit's message indented by four
# spaces, and a body quoting `git log` or a mail thread puts `> ` before it.
# Decoys: a human co-author behind the same indent, and an indented prose line
# that starts with a Claude- word but is no trailer, must both survive.
M="$WORK/m6d"
printf 'feat: x\n\nBody.\n    %s: Claude <noreply@anthropic.com>\n> %s: Claude <noreply@anthropic.com>\n\t%s: Claude Opus 5 <noreply@anthropic.com>\n    Claude-Session: http://x\n> Claude-Session: http://x\n    %s: A Human <h@example.com>\n    Claude-Code is named in this indented line\n' "$CO" "$CO" 'Signed-off-by' "$CO" > "$M"
out="$(bash "$SCRIPT" check "$M" 2>&1)"; rc=$?
hits="$(printf '%s\n' "$out" | grep -c '^ai-attribution: ')"
[ "$rc" -eq 1 ] && [ "$hits" -eq 5 ] && ok "check names the five indented or quoted attribution lines" \
  || bad "check on indented/quoted trailers: rc=$rc hits=$hits out='$out'"
strip "$M" >/dev/null 2>&1
if grep -qiE '(co-authored-by|signed-off-by): claude|claude-session' "$M"; then bad "an indented or quoted trailer survived the strip: $(tr '\n' '/' < "$M")"
else ok "indented and quoted co-author, sign-off and Claude-* trailers are stripped"; fi
if grep -q 'A Human' "$M" && grep -q 'Claude-Code is named' "$M"; then ok "an indented human co-author and an indented prose line are kept"
else bad "the strip removed a decoy: $(tr '\n' '/' < "$M")"; fi

# -- 7. check: names the line; clean after strip -------------------------------
M="$WORK/m7"; printf 'feat: x\n\nBody.\n\n%s: Claude <noreply@anthropic.com>\n' "$CO" > "$M"
out="$(bash "$SCRIPT" check "$M" 2>&1)"; rc=$?
if [ "$rc" -eq 1 ] && printf '%s' "$out" | grep -q "$M:5: $CO: Claude"; then ok "check exits 1 naming line 5"
else bad "check on an unstripped message: rc=$rc out='$out'"; fi
strip "$M" >/dev/null 2>&1
out="$(bash "$SCRIPT" check "$M" 2>&1)"; rc=$?
[ "$rc" -eq 0 ] && [ -z "$out" ] && ok "check exits 0, silent, on the stripped message" || bad "check after strip: rc=$rc out='$out'"

# -- 8. check-range over a two-commit fixture repository -----------------------
R="$WORK/repo"; mkdir -p "$R"; cd "$R" || exit 1
git init -q .
git commit -q --allow-empty -m 'chore(x): clean one'
good1="$(git rev-parse HEAD)"
printf 'feat(x): carries a trailer\n\nBody.\n\n%s: Claude <noreply@anthropic.com>\n' "$CO" > "$WORK/msg8"
git commit -q --allow-empty -F "$WORK/msg8"
badc="$(git rev-parse HEAD)"
git commit -q --allow-empty -m 'chore(x): clean two'
out="$(bash "$SCRIPT" check-range "$(git rev-parse HEAD)" 2>&1)"; rc=$?
if [ "$rc" -eq 1 ] && printf '%s' "$out" | grep -q "^ai-attribution: ${badc:0:12}:5: " \
   && printf '%s' "$out" | grep -q '3 commit(s) checked, 1 with an attribution line'; then
  ok "check-range over the whole history finds exactly the one bad commit"
else bad "check-range whole history: rc=$rc out='$out'"; fi
out="$(bash "$SCRIPT" check-range "0000000000000000000000000000000000000000..HEAD" 2>&1)"; rc=$?
[ "$rc" -eq 1 ] && ok "an all-zero base means the whole history" || bad "all-zero base: rc=$rc out='$out'"
out="$(bash "$SCRIPT" check-range "$badc..HEAD" 2>&1)"; rc=$?
[ "$rc" -eq 0 ] && printf '%s' "$out" | grep -q '1 commit(s) checked, 0 with' && ok "a range past the bad commit is clean" \
  || bad "range past the bad commit: rc=$rc out='$out'"
out="$(bash "$SCRIPT" check-range "$good1..$badc" 2>&1)"; rc=$?
[ "$rc" -eq 1 ] && ok "a range ending at the bad commit is red" || bad "range ending at the bad commit: rc=$rc"
out="$(bash "$SCRIPT" check-range "..HEAD" 2>&1)"; rc=$?
[ "$rc" -eq 2 ] && ok "..<b> is refused (git would read it as HEAD..<b>)" || bad "..HEAD: rc=$rc out='$out'"
out="$(bash "$SCRIPT" check-range "no-such-ref..HEAD" 2>&1)"; rc=$?
[ "$rc" -eq 3 ] && ok "an unresolvable range is a fault (3), not a verdict" || bad "bad range: rc=$rc out='$out'"
cd "$WORK" || exit 1

# -- 9. the pattern file is validated before use ---------------------------------
guard_case() { # <label> <pattern-file-content-printf-format>
  local label="$1" fmt="$2" D="$WORK/guard-$1"
  mkdir -p "$D"; cp "$SCRIPT" "$D/ai-attribution.sh"
  if [ "$fmt" != MISSING ]; then printf "$fmt" > "$D/ai-attribution.ere"; fi
  local M="$WORK/g-$label"; printf 'feat: x\n\nBody line.\n' > "$M"
  local before; before="$(cat "$M")"
  out="$(bash "$D/ai-attribution.sh" strip "$M" 2>&1)"; rc=$?
  if [ "$rc" -eq 3 ] && [ "$(cat "$M")" = "$before" ]; then ok "pattern file $label: strip refuses (3) and leaves the message untouched"
  else bad "pattern file $label: rc=$rc, message now '$(tr '\n' '/' < "$M")'"; fi
  out="$(bash "$D/ai-attribution.sh" check "$M" 2>&1)"; rc=$?
  [ "$rc" -eq 3 ] && ok "pattern file $label: check refuses (3)" || bad "pattern file $label: check rc=$rc"
}
guard_case blank-line '^Claude-[A-Za-z-]+:\n\n^x\n'
guard_case empty ''
guard_case crlf '^Claude-[A-Za-z-]+:\r\n'
guard_case missing MISSING
guard_case bad-regex '^(unclosed\n'

# -- 10. a real commit through .githooks/commit-msg -----------------------------
# The fixture gets the hooks and both tools; gitleaks is a stub answering the
# pinned version, and no host config exists, so the leak gate runs its public
# half and prints its skip line. That is the leak gate's own business
# (tools/leak-gate/leak_gate.test.py); here it only has to let a clean message
# through.
H="$WORK/hooked"; mkdir -p "$H"; cd "$H" || exit 1
git init -q .
cp -R "$REPO_ROOT/.githooks" .githooks
mkdir -p tools/commit-hygiene tools/leak-gate
cp "$REPO_ROOT"/tools/commit-hygiene/ai-attribution.{sh,ere} tools/commit-hygiene/
cp "$REPO_ROOT"/tools/leak-gate/{leak_gate.py,patterns.txt,allow.txt,gitleaks.version,gitleaks.toml} tools/leak-gate/
# the leak gate imports fleetlib from the repository it sits in, as in any clone
mkdir -p lib/fleetlib && cp "$REPO_ROOT"/lib/fleetlib/*.py lib/fleetlib/
pinned="$(cut -d' ' -f1 tools/leak-gate/gitleaks.version)"
printf '#!/usr/bin/env bash\nif [ "${1:-}" = version ]; then echo %s; exit 0; fi\nwhile [ $# -gt 0 ]; do if [ "$1" = --report-path ]; then shift; printf "[]" > "$1"; fi; shift; done\nexit 0\n' "${pinned#v}" > "$WORK/fake-gitleaks"
chmod +x "$WORK/fake-gitleaks"
export FLEET_GITLEAKS="$WORK/fake-gitleaks" FLEET_HOST_CONFIG="$WORK/no-host.json"
unset FLEET_LEAK_DENY_FILE FLEET_CONTEXT_ROOT
git add -A >/dev/null && git commit -q --no-verify -m 'chore: base'
git config core.hooksPath .githooks
echo one > a.txt; git add a.txt
printf 'feat(x): add a\n\nBody.\n\n%s: Claude Opus 5 <noreply@anthropic.com>\nClaude-Session: http://x\n' "$CO" > "$WORK/msg10"
out="$(git commit -q -F "$WORK/msg10" 2>&1)"; rc=$?
msg="$(git log -1 --format=%B)"
if [ "$rc" -eq 0 ] && [ "$(git log -1 --format=%s)" = "feat(x): add a" ] && ! printf '%s' "$msg" | grep -qiE 'claude|anthropic'; then
  ok "a real commit through the hook is recorded without its attribution lines"
else bad "real commit: rc=$rc out='$out' message='$(printf '%s' "$msg" | tr '\n' '/')'"; fi
git checkout -q -b side; echo two > b.txt; git add b.txt; git commit -q -m 'feat(x): side' >/dev/null 2>&1
git checkout -q main
out="$(git merge -q --no-ff side -m "Merge branch 'side'" -m 'Claude-Session: http://x' 2>&1)"; rc=$?
if [ "$rc" -eq 0 ] && ! git log -1 --format=%B | grep -qi claude; then ok "a merge commit's message is stripped by the hook too"
else bad "merge through the hook: rc=$rc out='$out' message='$(git log -1 --format=%B | tr '\n' '/')'"; fi

# -- 11. pre-push refuses a --no-verify commit carrying a trailer ----------------
git init -q --bare "$WORK/remote.git"
git remote add origin "$WORK/remote.git"
out="$(git push -q origin main 2>&1)"; rc=$?
[ "$rc" -eq 0 ] && ok "a clean first push of main passes pre-push" || bad "clean first push: rc=$rc out='$out'"
echo three > c.txt; git add c.txt
printf 'feat(x): sneak\n\n%s: Claude <noreply@anthropic.com>\n' "$CO" > "$WORK/msg11"
git commit -q --no-verify -F "$WORK/msg11"
out="$(git push origin main 2>&1)"; rc=$?
if [ "$rc" -ne 0 ] && printf '%s' "$out" | grep -q 'with an attribution line'; then ok "pre-push refuses a --no-verify commit with an attribution trailer"
else bad "pre-push on a --no-verify trailer commit: rc=$rc out='$out'"; fi

# -- 12. a real `git merge --squash` of commits that carry trailers ---------------
# The commits are made without the hook (as in a clone without it). The squash
# writes their trailers INDENTED into the message; the hook must strip them
# (12a), and when the squash itself is committed without the hook, check-range
# - CI's commit-hygiene job - must refuse it (12b).
git checkout -q -b squash-src main
for k in 1 2; do
  echo "$k" > "sq$k.txt"; git add "sq$k.txt"
  git commit -q --no-verify -m "feat(x): squashed $k" -m "$CO: Claude <noreply@anthropic.com>"
done
git checkout -q -b squash-hooked main
git merge -q --squash squash-src >/dev/null 2>&1
# regime control: the squash message really carries the trailers, and indented,
# or 12a would pass on a message that never held one
n="$(grep -c "^    $CO: Claude" "$(git rev-parse --git-dir)/SQUASH_MSG")"
[ "$n" -eq 2 ] && ok "the squash message carries the two trailers, indented" || bad "SQUASH_MSG holds $n indented trailers, expected 2"
out="$(git commit -q --no-edit 2>&1)"; rc=$?
if [ "$rc" -eq 0 ] && ! git log -1 --format=%B | grep -qi "$CO: claude"; then ok "a squash commit through the hook is recorded without the indented trailers"
else bad "squash through the hook: rc=$rc out='$out' message='$(git log -1 --format=%B | tr '\n' '/')'"; fi
git checkout -q -b squash-unhooked main
git merge -q --squash squash-src >/dev/null 2>&1
git commit -q --no-edit --no-verify
out="$(bash tools/commit-hygiene/ai-attribution.sh check-range HEAD^..HEAD 2>&1)"; rc=$?
if [ "$rc" -eq 1 ] && printf '%s' "$out" | grep -q '1 commit(s) checked, 1 with an attribution line'; then
  ok "check-range refuses a squash committed without the hook"
else bad "check-range on an unhooked squash: rc=$rc out='$out'"; fi
cd "$WORK" || exit 1

echo
if [ "$fails" -eq 0 ]; then echo "PASS: $checks/$checks checks"; exit 0; fi
echo "FAIL: $fails of $checks checks failed"; exit 1
