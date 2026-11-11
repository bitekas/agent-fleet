#!/usr/bin/env bash
# range.sh - the commit range a CI run checks, printed on stdout in the form
# leak_gate.py --range and ai-attribution.sh check-range both read: `<a>..<b>`,
# or a bare `<b>` for the whole history of b. Why it chose that range goes to
# stderr. The leak and commit-hygiene jobs both call it, so they always check
# the same commits.
#
# Inputs (environment, set by the workflow from the event; never interpolated
# into a shell line):
#   CI_EVENT     github.event_name: push | pull_request | workflow_dispatch
#   CI_REF       github.ref, e.g. refs/heads/main
#   CI_BEFORE    push: github.event.before (all zeros when the push created the ref)
#   CI_AFTER     push, workflow_dispatch: github.sha
#   CI_PR_BASE   pull_request: github.event.pull_request.base.sha
#   CI_PR_HEAD   pull_request: github.event.pull_request.head.sha
# The clone must be a full one (actions/checkout fetch-depth: 0).
#
# Rules:
#   * pull_request: <base>..<head>, the commits the pull request adds.
#   * push of an existing ref: <before>..<after>.
#   * push that created the ref (before is all zeros), or whose <before> is not
#     in the clone (a force push): merge-base(origin/main, after)..after for any
#     ref but main, else the whole history of <after>. This is what makes the
#     FIRST push of main check every commit rather than none.
#   * workflow_dispatch (a run started by hand, which has no before): the rule
#     of a push that created the ref. A CI_BEFORE passed with it is ignored.
#
# Exit codes: 0 printed a range; 2 usage (unknown event, missing input);
# 3 a named commit is not in the clone (no range is printed, so no job can
# report a verdict over an empty one).
set -euo pipefail

die() { local code="$1"; shift; echo "range: $*" >&2; exit "$code"; }
is_null() { [[ -z "$1" || "$1" =~ ^0+$ ]]; }
have_commit() { git rev-parse -q --verify "$1^{commit}" >/dev/null 2>&1; }

case "${CI_EVENT:-}" in
  pull_request)
    base="${CI_PR_BASE:-}"; head="${CI_PR_HEAD:-}"
    [ -n "$base" ] && [ -n "$head" ] || die 2 "pull_request needs CI_PR_BASE and CI_PR_HEAD"
    have_commit "$head" || die 3 "pull request head $head is not in the clone"
    have_commit "$base" || die 3 "pull request base $base is not in the clone"
    echo "range: pull request: $base..$head" >&2
    echo "$base..$head"
    ;;
  push | workflow_dispatch)
    head="${CI_AFTER:-}"; before="${CI_BEFORE:-}"
    [ "$CI_EVENT" = push ] || before=""
    [ -n "$head" ] || die 2 "$CI_EVENT needs CI_AFTER"
    have_commit "$head" || die 3 "pushed commit $head is not in the clone"
    if ! is_null "$before" && have_commit "$before"; then
      echo "range: push to an existing ref: $before..$head" >&2
      echo "$before..$head"
    elif [ "${CI_REF:-}" != "refs/heads/main" ] && have_commit refs/remotes/origin/main \
         && base="$(git merge-base refs/remotes/origin/main "$head")"; then
      echo "range: new ref, rewritten history or dispatched run: origin/main merge base $base..$head" >&2
      echo "$base..$head"
    else
      echo "range: first push or dispatched run of main, or no common base with origin/main: the whole history of $head" >&2
      echo "$head"
    fi
    ;;
  *) die 2 "CI_EVENT must be push, pull_request or workflow_dispatch (got '${CI_EVENT:-}')" ;;
esac
