#!/usr/bin/env bash
# run-all.sh - discover every fleet test, print the census, run each one, and
# exit non-zero unless every discovered test ran and passed, or was skipped on
# this operating system by tests/platforms.json.
#
# Usage: bash tests/run-all.sh        (from any directory; CI's test jobs run it)
#
# Portable bash: it runs under macOS's /bin/bash 3.2 as well as bash 5. So no
# associative arrays (results are indexed by the test's position), no GNU
# `timeout` (tests/runner.py), and no "${a[@]}" of an array that can be empty
# while set -u is on (bash before 4.4 calls that an unbound variable).
#
# Discovery: every *.test.py, *.test.sh and *.test.mjs under .claude/skills/,
# bin/, lib/, systemd/ and tools/, excluding node_modules/. Runners: python3,
# bash, node. Each runs from the repository root with a 15-minute timeout
# (`tests/runner.py timeout`: on expiry the test's whole process group is
# killed).
#
# Platforms: tests/platforms.json lists the tests that run on one operating
# system only (linux or macos), each with its reason. On the other system such a
# test is not run: the census and the run print it as SKIPPED with the reason.
# An entry that names no discovered test, or carries no reason, fails the run
# before any test runs (`tests/runner.py platforms` names every finding).
#
# Environment: FLEET_HOST_CONFIG=tests/fixtures/host.json always, and
# FLEET_CONTEXT_ROOT=tests/fixtures/install when that fixture install has a
# manifest; FLEET_CONTEXT_ROOT is unset otherwise, and FLEET_LEAK_DENY_FILE is
# always unset. So no test reads this host's real host config, install or deny
# list: when the fixture host config is absent, a test sees a machine that is
# not a fleet host. The census prints which of these applied.
#
# Exit codes: 0 every discovered test ran and passed, or was skipped by
# tests/platforms.json; 1 a test failed, a discovered test has no recorded
# result (the run did not cover the census), or tests/platforms.json is
# invalid; 2 nothing was discovered, so there is no verdict.
set -uo pipefail

root="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
cd "$root" || exit 2

unset FLEET_LEAK_DENY_FILE
export FLEET_HOST_CONFIG="$root/tests/fixtures/host.json"
if [ -f "$root/tests/fixtures/install/.claude/fleet.json" ]; then
  export FLEET_CONTEXT_ROOT="$root/tests/fixtures/install"
else
  unset FLEET_CONTEXT_ROOT
fi
case "$(uname -s)" in
  Linux) os=linux ;;
  Darwin) os=macos ;;
  *) os="$(uname -s)" ;;
esac

roots=()
for d in .claude/skills bin lib systemd tools; do [ -d "$d" ] && roots+=("$d"); done
tests=()
if [ "${#roots[@]}" -gt 0 ]; then
  while IFS= read -r -d '' f; do tests+=("${f#./}"); done < <(
    find "${roots[@]}" -name node_modules -prune -o -type f \
      \( -name '*.test.py' -o -name '*.test.sh' -o -name '*.test.mjs' \) -print0 | sort -z)
fi

echo "== census: ${#tests[@]} test(s) under: ${roots[*]:-<no test roots>}"
echo "   FLEET_HOST_CONFIG=$FLEET_HOST_CONFIG ($([ -f "$FLEET_HOST_CONFIG" ] && echo present || echo absent))"
echo "   FLEET_CONTEXT_ROOT=${FLEET_CONTEXT_ROOT:-<unset: no fixture install>}"
if [ "${#tests[@]}" -eq 0 ]; then
  echo "== NO VERDICT: no test was discovered"
  exit 2
fi

logdir="$(mktemp -d)" || { echo "== NO VERDICT: cannot create a log directory"; exit 2; }
trap 'rm -rf -- "${logdir:?}"' EXIT

# why[i]: empty when tests[i] runs here, else "<only>-only: <reason>"
platforms=tests/platforms.json
if ! python3 "$root/tests/runner.py" platforms "$platforms" "$os" "${tests[@]}" \
    >"$logdir/skips" 2>"$logdir/platforms.err"; then
  sed 's/^/   /' "$logdir/platforms.err"
  echo "== FAIL: $platforms is invalid (findings above); no test ran"
  exit 1
fi
why=()
i=0
for t in "${tests[@]}"; do
  why[$i]=""
  while IFS=$'\t' read -r p only reason; do
    [ "$p" = "$t" ] && why[$i]="$only-only: $reason"
  done <"$logdir/skips"
  i=$((i + 1))
done

nskip="$(grep -c . "$logdir/skips")"
echo "   platform: $os, bash $BASH_VERSION ($platforms: $nskip test(s) skipped here)"
i=0
for t in "${tests[@]}"; do
  if [ -n "${why[$i]}" ]; then echo "   $t  [SKIPPED on $os: ${why[$i]}]"; else echo "   $t"; fi
  i=$((i + 1))
done

result=()
fails=0
skipped=0
i=0
for t in "${tests[@]}"; do
  if [ -n "${why[$i]}" ]; then
    result[$i]=SKIPPED
    skipped=$((skipped + 1))
    echo "SKIP  $t  (${why[$i]})"
    i=$((i + 1))
    continue
  fi
  case "$t" in
    *.test.py)  runner=(python3) ;;
    *.test.sh)  runner=(bash) ;;
    *.test.mjs) runner=(node) ;;
  esac
  log="$logdir/$(echo "$t" | tr '/' '_').log"
  start=$SECONDS
  python3 "$root/tests/runner.py" timeout 900 -- "${runner[@]}" "$t" >"$log" 2>&1 </dev/null
  rc=$?
  secs=$((SECONDS - start))
  if [ "$rc" -eq 0 ]; then
    result[$i]=PASS
    echo "PASS  ${secs}s  $t"
  else
    result[$i]="FAIL($rc)"
    fails=$((fails + 1))
    echo "FAIL  ${secs}s  $t  (exit $rc; output follows)"
    sed 's/^/      | /' "$log"
  fi
  i=$((i + 1))
done

missing=0
i=0
for t in "${tests[@]}"; do
  if [ -z "${result[$i]:-}" ]; then echo "NOT RUN  $t"; missing=$((missing + 1)); fi
  i=$((i + 1))
done
echo "== ${#tests[@]} discovered, $((${#result[@]} - skipped)) ran, $skipped skipped, $fails failed, $missing not run"
[ "$fails" -eq 0 ] && [ "$missing" -eq 0 ] && [ "${#result[@]}" -eq "${#tests[@]}" ] || exit 1
exit 0
