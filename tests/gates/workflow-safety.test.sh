#!/usr/bin/env bash
# workflow-safety gate: every job of every workflow carries the fork gate and runs
# on one of the two self-hosted label sets; read-only permissions; no secret; only
# push, pull_request and workflow_dispatch. The rules, their reasons, the positive
# control and the exit codes are in gates.py (check_workflow_safety and its header).
exec python3 "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/gates.py" workflow-safety
