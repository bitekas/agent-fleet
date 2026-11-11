#!/usr/bin/env bash
# ai-attribution.sh - the one reader of ai-attribution.ere, the list of lines
# that credit an AI tool in a commit message (a co-author or sign-off trailer,
# a Claude-* provenance trailer, a "generated with" footer). A commit is
# authored by the person or agent who made it; a tool is never credited.
#
# Usage:
#   bash tools/commit-hygiene/ai-attribution.sh strip <msgfile>
#       Delete every matching line and collapse the trailing blank lines the
#       deletion leaves. Silent. The commit-msg hook calls it.
#   bash tools/commit-hygiene/ai-attribution.sh check <msgfile>
#       Print each matching line with its line number.
#   bash tools/commit-hygiene/ai-attribution.sh check-range <a>..<b>
#       Run check over the message of every commit in the range. A bare <b>,
#       or an all-zero <a> (the old value git reports for a ref that a push
#       creates), means the whole history of <b>. CI and pre-push call it.
#
# Exit codes: 0 clean (strip: always, once it ran); 1 an attribution line was
# found (check, check-range); 2 usage error; 3 instrument fault - the pattern
# file is missing or unsafe, grep failed, or the range does not resolve. A 3
# never pronounces on the message, and strip leaves the message untouched.
#
# LOAD-BEARING PROPERTIES - each one is here because removing it opens a hole:
#
#   * ONE LIST, TWO VERDICTS. strip (the hook) and check (CI) read the same
#     file with the same grep flags, so a line the hook would remove is exactly
#     a line CI rejects. A clone whose hook ran never fails CI; a commit made
#     with --no-verify, or in a clone without the hooks, fails it.
#
#   * EVERY PATTERN IS ANCHORED AT THE START OF A LINE. A line that IS an
#     attribution matches; prose that mentions one mid-sentence does not, so
#     nothing a writer meant to say is ever deleted. "Is" includes behind an
#     indent or a `>` quote (lines 5 and 6 are lines 1 and 2 with that prefix;
#     lines 3 and 4 allow any non-alphanumeric prefix): `git merge --squash`
#     writes every squashed message indented, so a squash of commits made
#     without the hook would otherwise pass both this strip and CI's check.
#     Lines 1 to 3 are kept byte for byte as inherited; a new shape is a new
#     line.
#
#   * THE ANCHOR ALSO REACHES THE SUBJECT LINE, so line 2 of the pattern file
#     forbids a subject starting `Claude-<word>:` in any case: strip deletes it
#     silently and git records the next line as the subject. The fleet's
#     `type(scope): subject` form never starts that way, and
#     ai-attribution.test.sh pins both directions.
#
#   * THE PATTERN FILE IS VALIDATED BEFORE USE. `grep -f` reads an empty line
#     as a pattern that matches EVERY line (strip would delete the whole
#     message, check would flag every line), an empty file as no pattern at all
#     (strip and check would pass everything), and a CR at a line end as part
#     of the pattern (that line would never match). Each is exit 3.
#
#   * A GREP ERROR IS A FAULT, NEVER "NO MATCH". grep exits 1 for "no line
#     selected" and 2 for an error. Folding both into success (`|| true`)
#     would turn a missing pattern file into an emptied message file.
#
#   * THE TEMP FILE SITS BESIDE THE MESSAGE FILE, in the directory git has just
#     written to. A bare mktemp under a missing TMPDIR fails, and under set -e
#     that would refuse every commit.
#
#   * LC_ALL=C AND grep -a. The C locale makes the match byte-wise and the same
#     on every host (an emoji before "Generated" is a run of non-alphanumeric
#     bytes); -a keeps grep from answering "binary file matches" instead of
#     printing lines when a message carries a NUL or invalid UTF-8.
set -euo pipefail
export LC_ALL=C

here="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
ere="$here/ai-attribution.ere"

die() { local code="$1"; shift; echo "ai-attribution: $*" >&2; exit "$code"; }
usage() { die 2 "usage: ai-attribution.sh strip <msgfile> | check <msgfile> | check-range <a>..<b>"; }

validate_patterns() {
  [ -r "$ere" ] || die 3 "pattern file missing or unreadable: $ere"
  [ -s "$ere" ] || die 3 "pattern file is empty, so it would match nothing: $ere"
  if grep -q $'\r' "$ere"; then die 3 "pattern file has a CR line ending, so a pattern would never match: $ere"; fi
  if grep -qE '^[[:space:]]*$' "$ere"; then die 3 "pattern file has an empty line, which matches every line: $ere"; fi
}

# check_stream <label>: reads a message on stdin, prints each match, returns 0 none / 1 found.
check_stream() {
  local label="$1" out rc=0
  out="$(grep -a -n -iE -f "$ere")" || rc=$?
  case "$rc" in
    0) while IFS= read -r line; do echo "ai-attribution: $label:${line%%:*}: ${line#*:}"; done <<<"$out"; return 1 ;;
    1) return 0 ;;
    *) die 3 "grep failed (exit $rc) reading $label" ;;
  esac
}

cmd="${1:-}"
case "$cmd" in
  strip)
    [ $# -eq 2 ] || usage
    msg="$2"
    validate_patterns
    [ -f "$msg" ] || die 3 "message file not found: $msg"
    tmp="$(mktemp "${msg}.XXXXXX")"
    rc=0
    grep -a -v -iE -f "$ere" -- "$msg" > "$tmp" || rc=$?
    if [ "$rc" -gt 1 ]; then rm -f -- "$tmp"; die 3 "grep failed (exit $rc); the message is unchanged"; fi
    awk 'BEGIN{blank=0} { if ($0 ~ /^[[:space:]]*$/) { blank++ } else { while(blank>0){print ""; blank--}; print } }' "$tmp" > "$msg"
    rm -f -- "$tmp"
    ;;
  check)
    [ $# -eq 2 ] || usage
    validate_patterns
    [ -f "$2" ] || die 3 "message file not found: $2"
    check_stream "$2" < "$2" || exit 1
    ;;
  check-range)
    [ $# -eq 2 ] || usage
    spec="$2"
    validate_patterns
    case "$spec" in
      ..*) die 2 "git reads ..<b> as HEAD..<b>; pass <a>..<b>, or <b> alone for its whole history" ;;
      *...*) die 2 "a symmetric range is not supported; pass <a>..<b>" ;;
    esac
    base=""; head="$spec"
    if [[ "$spec" == *..* ]]; then base="${spec%%..*}"; head="${spec#*..}"; fi
    [[ "$base" =~ ^0+$ ]] && base=""
    [ -n "$head" ] || usage
    head_sha="$(git rev-parse --verify -q "$head^{commit}")" || die 3 "$head does not name a commit"
    if [ -n "$base" ]; then
      base_sha="$(git rev-parse --verify -q "$base^{commit}")" || die 3 "$base does not name a commit"
      revs="$base_sha..$head_sha"
    else
      revs="$head_sha"
    fi
    commits="$(git rev-list --reverse "$revs")" || die 3 "git rev-list $revs failed"
    total=0; bad=0
    for c in $commits; do
      total=$((total + 1))
      rc=0
      git cat-file commit "$c" | sed '1,/^$/d' | check_stream "${c:0:12}" || rc=$?
      case "$rc" in
        0) ;;
        1) bad=$((bad + 1)) ;;
        *) die 3 "reading the message of $c failed (exit $rc)" ;;
      esac
    done
    echo "ai-attribution: check-range $spec: $total commit(s) checked, $bad with an attribution line"
    [ "$bad" -eq 0 ] || exit 1
    ;;
  *) usage ;;
esac
