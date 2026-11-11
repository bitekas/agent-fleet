#!/usr/bin/env bash
# range.test.sh - teeth for tools/ci/range.sh, the range both CI checks scan.
#
# Run: bash tools/ci/range.test.sh   (tests/run-all.sh runs it)
#
# A wrong range is the quiet failure of a CI check: an empty range checks no
# commit and reports green. So every case asserts the COMMITS the printed range
# selects (git rev-list), not only its text, and the first push of main is
# shown to select every commit of the history.
set -u
REPO_ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../.." && pwd)"
RANGE="$REPO_ROOT/tools/ci/range.sh"

checks=0; fails=0
ok()  { checks=$((checks + 1)); echo "ok  : $1"; }
bad() { checks=$((checks + 1)); fails=$((fails + 1)); echo "FAIL: $1"; }

for v in $(env | sed -n 's/^\(GIT_[A-Za-z0-9_]*\)=.*/\1/p'); do unset "$v"; done
WORK="$(mktemp -d)" || { echo "FAIL: mktemp"; exit 1; }
trap 'rm -rf -- "${WORK:?}"' EXIT INT TERM HUP
export GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL="$WORK/gitconfig" HOME="$WORK/home"
mkdir -p "$HOME"
printf '[user]\n\tname = Fixture Tester\n\temail = tester@example.com\n[init]\n\tdefaultBranch = main\n' > "$GIT_CONFIG_GLOBAL"
cd "$WORK" || exit 1
git init -q repo && cd repo || exit 1
for n in 1 2 3; do git commit -q --allow-empty -m "chore: main $n"; done
m3="$(git rev-parse HEAD)"; m2="$(git rev-parse HEAD~1)"
git checkout -q -b feat/x
git commit -q --allow-empty -m "feat: x1"; git commit -q --allow-empty -m "feat: x2"
x2="$(git rev-parse HEAD)"
git checkout -q main
git tag -a v1.0.0 -m "release" "$m3"
Z=0000000000000000000000000000000000000000

# rng <env assignments...>: prints "<rc>|<stdout>|<commit count the range selects>"
rng() {
  local out rc count
  out="$(env -u CI_EVENT -u CI_REF -u CI_BEFORE -u CI_AFTER -u CI_PR_BASE -u CI_PR_HEAD "$@" bash "$RANGE" 2>/dev/null)"; rc=$?
  count="-"
  if [ "$rc" -eq 0 ]; then count="$(git rev-list "$out" | wc -l | tr -d ' ')"; fi
  echo "$rc|$out|$count"
}
expect() { # <label> <got> <want>
  if [ "$2" = "$3" ]; then ok "$1"; else bad "$1: got '$2', want '$3'"; fi
}

expect "push to an existing ref: before..after" \
  "$(rng CI_EVENT=push CI_REF=refs/heads/main CI_BEFORE="$m2" CI_AFTER="$m3")" "0|$m2..$m3|1"
expect "first push of main (before all zeros, no origin/main): the whole history, every commit" \
  "$(rng CI_EVENT=push CI_REF=refs/heads/main CI_BEFORE=$Z CI_AFTER="$m3")" "0|$m3|3"
expect "new branch before origin/main exists: the whole history" \
  "$(rng CI_EVENT=push CI_REF=refs/heads/feat/x CI_BEFORE=$Z CI_AFTER="$x2")" "0|$x2|5"
git update-ref refs/remotes/origin/main "$m3"
expect "new branch with origin/main: only the branch's own commits" \
  "$(rng CI_EVENT=push CI_REF=refs/heads/feat/x CI_BEFORE=$Z CI_AFTER="$x2")" "0|$m3..$x2|2"
expect "force push (before not in the clone): the origin/main merge base" \
  "$(rng CI_EVENT=push CI_REF=refs/heads/feat/x CI_BEFORE=1111111111111111111111111111111111111111 CI_AFTER="$x2")" "0|$m3..$x2|2"
expect "main with an unknown before: the whole history, never an empty range" \
  "$(rng CI_EVENT=push CI_REF=refs/heads/main CI_BEFORE=1111111111111111111111111111111111111111 CI_AFTER="$m3")" "0|$m3|3"
expect "tag push of a commit on main: nothing new to check" \
  "$(rng CI_EVENT=push CI_REF=refs/tags/v1.0.0 CI_BEFORE=$Z CI_AFTER="$m3")" "0|$m3..$m3|0"
expect "dispatched run on a branch: the origin/main merge base, as a push that created the ref" \
  "$(rng CI_EVENT=workflow_dispatch CI_REF=refs/heads/feat/x CI_AFTER="$x2")" "0|$m3..$x2|2"
expect "dispatched run on main: the whole history, never an empty range" \
  "$(rng CI_EVENT=workflow_dispatch CI_REF=refs/heads/main CI_AFTER="$m3")" "0|$m3|3"
expect "dispatched run: a before passed by mistake is ignored, never trusted as a push's" \
  "$(rng CI_EVENT=workflow_dispatch CI_REF=refs/heads/main CI_BEFORE="$m2" CI_AFTER="$m3")" "0|$m3|3"
expect "pull request: base..head" \
  "$(rng CI_EVENT=pull_request CI_PR_BASE="$m3" CI_PR_HEAD="$x2")" "0|$m3..$x2|2"
expect "a pushed commit missing from the clone: exit 3, nothing printed" \
  "$(rng CI_EVENT=push CI_REF=refs/heads/main CI_BEFORE=$Z CI_AFTER=2222222222222222222222222222222222222222)" "3||-"
expect "a pull request without its base: exit 2" \
  "$(rng CI_EVENT=pull_request CI_PR_HEAD="$x2")" "2||-"
expect "an unknown event: exit 2" "$(rng CI_EVENT=schedule)" "2||-"

# Both consumers read the printed form: the whole-history form reaches every commit.
out="$(bash "$REPO_ROOT/tools/commit-hygiene/ai-attribution.sh" check-range "$m3" 2>&1)"; rc=$?
if [ "$rc" -eq 0 ] && printf '%s' "$out" | grep -q '3 commit(s) checked'; then ok "check-range reads the bare-head form as the whole history"
else bad "check-range on the bare-head form: rc=$rc out='$out'"; fi

echo
if [ "$fails" -eq 0 ]; then echo "PASS: $checks/$checks checks"; exit 0; fi
echo "FAIL: $fails of $checks checks failed"; exit 1
