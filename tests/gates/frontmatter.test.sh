#!/usr/bin/env bash
# frontmatter gate: every SKILL.md frontmatter parses and carries name, version
# and description.
# The rules, the positive control and the exit codes are in gates.py's header.
exec python3 "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/gates.py" frontmatter
