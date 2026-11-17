#!/usr/bin/env bash
# install-section gate: every SKILL.md ends with one `## Install` section, and
# the skill's files agree with it.
# The rules, the positive control and the exit codes are in gates.py's header.
exec python3 "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/gates.py" install-section
