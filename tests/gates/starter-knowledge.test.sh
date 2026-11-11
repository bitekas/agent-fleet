#!/usr/bin/env bash
# starter-knowledge gate: examples/knowledge-base passes check_indexes.py and
# every lesson carries the EXAMPLE marker.
# The rules, the positive control and the exit codes are in gates.py's header.
exec python3 "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/gates.py" starter-knowledge
