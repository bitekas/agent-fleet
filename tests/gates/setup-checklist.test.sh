#!/usr/bin/env bash
# setup-checklist gate: SETUP.md's closing checklist names exactly the keys of
# templates/fleet.example.json and of each skill's config.example.json.
# The rules, the positive control and the exit codes are in gates.py's header.
exec python3 "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/gates.py" setup-checklist
