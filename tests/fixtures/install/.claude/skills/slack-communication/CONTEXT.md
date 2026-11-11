# slack-communication - fixture install context

FIXTURE. A synthetic install's human layer for this skill, for tests that
resolve the skill's install context. Every value is invented.

| What | Value |
|---|---|
| Workspace | `example.slack.com` (`workspace.team_id` in `config.json`) |
| Bot | Ada's bot, `U0BOTA` |
| Owning agent | `ada`, config directory `/tmp/fleet-fixture/agents/ada/.claude`; policy in its charter, `.claude/agents/ada.md` |

## Channels

| Channel | ID | For |
|---|---|---|
| `#general` | `C0GENRL` | requests to the agents |
| `#ops` | `C0OPSX` | alerts |

## People

| Name | UID | Role |
|---|---|---|
| Ada | `U0ADA` | owner |
| Grace | `U0GRACE` | engineer |
| Alan | `U0ALAN` | engineer |
