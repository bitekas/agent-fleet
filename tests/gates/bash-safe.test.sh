#!/usr/bin/env bash
# bash-safe gate: every extensionless Python script carries the claude-skill
# section 3 hand-off line as line 2, byte for byte.
# The rules, the positive control and the exit codes are in gates.py's header.
exec python3 "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/gates.py" bash-safe
