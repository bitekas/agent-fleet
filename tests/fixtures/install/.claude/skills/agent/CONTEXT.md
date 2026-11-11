# CONTEXT - agent (fixture install)

Synthetic values for the fleet's tests. `<agent>` is the running agent's name;
`<agents-root>` is `agents_root` in the host settings file.

## Paths

| What | Path |
|---|---|
| home directory | `<agents-root>/<agent>` |
| charter | `<agents-root>/<agent>/project/.claude/agents/<agent>.md` |
| personal secrets | `<agents-root>/<agent>/secrets/personal` |
| organization secrets | `${FLEET_SECRETS_DIR:-~/.fleet-secrets}` |
| workspaces | `<agents-root>/<agent>/workspaces` |
| playground | `<agents-root>/<agent>/playground` |
| config | `<agents-root>/<agent>/config` |
| agent memory | `<agents-root>/<agent>/state/memory` |
| state | `<agents-root>/<agent>/state` |
| artifacts | `<agents-root>/<agent>/artifacts/<YYYY-MM-DD>/<artifact>` |
| blockers | `<agents-root>/<agent>/blockers/blockers.md` |
| project repository | `<agents-root>/<agent>/project` |

`installation/check` parses the `home directory` row above by its label and
its backticked path; `installation/check.test.py` pins that parse.
