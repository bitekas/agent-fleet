#!/usr/bin/env bash
# layout gate: no SPECIFIC file in a skill, no .claude/agents/ or .claude-plugin/,
# no committed gitleaks configuration, no symlink leaving the repository, and no
# Claude Code configuration beyond the pinned attribution-only .claude/settings.json.
# The rules, the positive control and the exit codes are in gates.py's header.
exec python3 "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/gates.py" layout
