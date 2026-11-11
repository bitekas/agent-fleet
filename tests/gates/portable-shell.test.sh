#!/usr/bin/env bash
# portable-shell gate: no tracked shell script or shell block uses a construct
# that macOS's bash 3.2 or BSD userland cannot run, unless its line is marked
# `# linux-only: <reason>`. The rules, the positive control and the exit codes
# are in gates.py's header.
exec python3 "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/gates.py" portable-shell
