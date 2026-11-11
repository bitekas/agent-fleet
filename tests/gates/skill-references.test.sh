#!/usr/bin/env bash
# skill-references gate: every backticked `/name` in fleet prose is a fleet skill.
# The rules, the positive control and the exit codes are in gates.py's header.
exec python3 "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/gates.py" skill-references
