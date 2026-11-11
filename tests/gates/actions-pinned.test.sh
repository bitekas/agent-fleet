#!/usr/bin/env bash
# actions-pinned gate: every `uses:` under .github/ is pinned by a full commit SHA.
# The rules, the positive control and the exit codes are in gates.py's header.
exec python3 "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/gates.py" actions-pinned
