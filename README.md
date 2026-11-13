# agent-fleet

A runtime for running several long-running Claude Code agents on one Linux or
macOS host.
Each agent has its own home directory, its own Claude Code config directory and
its own tmux session; it is reachable over chat, woken by a scheduler, rescued
from a prompt nobody is there to answer, and moved to another account before a
usage cap stops it. The fleet ships the machinery and the shared rules; the
organisation that runs the agents supplies its values.

## Install

On your own computer, install Claude Code, open it - in a checkout of the
project your agents will work in, if you have one - and paste:

```text
Install agent-fleet from https://github.com/bitekas/agent-fleet following its SETUP.md
```

Claude Code follows the `install-agent-fleet` skill. It asks where the fleet
will run (an AWS or Google Cloud instance, or a physical Linux or macOS
machine), and from your computer, over SSH, gets that machine ready, installs
what it needs and the fleet, asks you only what it cannot find out, shows you
the change to your project before committing it, and offers to add your first
agent. `SETUP.md`, "What only you do", lists the few steps that stay with you.
Later, say "Upgrade agent-fleet following ~/agent-fleet/SETUP.md".

Without Claude Code, on the machine the fleet will run on, with nothing
installed yet:

```bash
git clone https://github.com/bitekas/agent-fleet.git <agents-root>/fleet
cd <agents-root>/fleet
git checkout --detach <tag>
python3 bin/fleet install --agents-root <agents-root>
```

`<agents-root>` is the directory your agent homes will sit in, `~/agents` by
default, and `<tag>` the newest release. `SETUP.md` is the rest of the way.

## What it ships

- **Skills** every agent loads by name: the standing agent rules, scheduling,
  chat, the stall watchdog, revival and usage health, the knowledge-store
  conventions, and the conventions for writing a skill (the list is below).
- **Daemons** per agent - a scheduler and one watcher per working chat
  transport - as systemd user units rendered from `systemd/` (launchd
  LaunchAgents on macOS), plus a refresh timer that restarts a daemon whose
  script or config changed.
- **The `fleet` command** (`bin/fleet`): installs the fleet on a host, adopts a
  project as an install (`fleet adopt <project>`: its manifest, and the session
  check that tells every session started there when the fleet is missing,
  outdated or not linked), links each agent's skills, upgrades and rolls back
  the host checkout, resolves an install's settings, runs every skill's install
  check, and reports drift.
- **Templates** (`templates/`): the install manifest, three persona charters
  (a lead engineer, a health doctor, a root orchestrator), the agent's system
  unit and its launchd form, and the root of an empty knowledge store.
  `examples/knowledge-base/` is an example store with a handful of generic
  lessons.
- **A commit gate**: hooks and CI that refuse private values, secrets and
  AI-attribution lines (`CONTRIBUTING.md`, `SECURITY.md`).

## The fleet and the install

The fleet holds MECHANISM - what is true for every organisation. An **install**
is the repository an organisation's agents work in, and it holds the VALUES:
names, ids, paths, people, and how that organisation builds and ships software.

| In the fleet (COMMON) | In the install (SPECIFIC) |
|---|---|
| each skill's `SKILL.md`, scripts, tests, `config.example.json`, `installation/INSTRUCTION.md` and `installation/check` | each skill's `CONTEXT.md`, `config.json`, `installation/.install-state.json`, `override/` and `temporary/`, under `.claude/skills/<skill>/` |
| the conventions vocabulary (`CONVENTIONS.md`) | its own development conventions - definition of done, branch naming, workspace, release, environments, feature checklist - as skills or documents of its own |
| house-rule defaults | its house-rule values |
| persona templates | its agents' charters, `.claude/agents/<agent-name>.md` |
| the knowledge-store mechanism and an empty store root | its filled knowledge store |

**The install manifest, `.claude/fleet.json` in the install repository, joins
the two**: the minimum fleet version the install needs, the skills its agents
link, its chat transports, its conventions, its house rules, where its secrets
live, and the identity its agents use when they contribute to the fleet.
`templates/fleet.example.json` is its fill-in form. Fleet scripts find the
manifest through `lib/fleetlib/`; `fleet settings` prints the resolved values
and `fleet where <skill>` prints where a skill's SPECIFIC files live.

**The fleet ships no development process.** Where a skill needs one - when is a
task done, how is a branch named - it reads a convention key, and an install
that leaves a key `null` has no such convention: the skill skips that step and
says so.

## The host-checkout model

- **One clone per host**, at `<agents-root>/fleet`, detached at a release tag
  and read-only. Nobody edits it; it moves only with `fleet upgrade <tag>`, and
  back with `fleet upgrade <tag> --rollback`. A file copied out of it keeps the
  read-only mode, so copies are made with `install -m 644`, and removing a clone
  takes `chmod -R u+w <clone>` before the `rm -rf`.
- **Each agent's personal skills directory**,
  `<agents-root>/<agent-name>/.claude/skills/`, holds one symlink per skill
  into the host checkout (`fleet link <agent-name>`). A personal skill outranks
  a project skill of the same name, so removing the links returns an agent to
  whatever its install provides.
- **The daemons and the stall watchdogs run their scripts from the host
  checkout**, so one upgrade reaches every agent: skill text at once, daemons
  at the refresh timer's next run, watchdogs within one cycle.
- **Development happens in worktrees of the host checkout** and lands on
  `main` as `CONTRIBUTING.md` describes; a host takes it when it is tagged.

## Skills

`.claude/skills/SKILLS.md` is the index: what each skill is for and how complete
it is.

- **Installing:** `install-agent-fleet` (from your own computer, over SSH:
  install the fleet on a target machine, adopt a project as its install, and
  upgrade it later), `adding-an-agent`, `safe-box` (a one-time form on
  127.0.0.1 that takes a secret from a person into a file, outside the
  session).
- **Agent rules and writing:** `agent`, `talking-to-humans`, `knowledge-base`,
  `claude-skill`.
- **Keeping a session running and reachable:** `scheduled-tasks`,
  `stall-watchdog`, `self-compact`, `restart`, `soft-restart` (restart one
  agent's own session onto the Claude binary already installed).
- **Chat:** `chat-transport` (the interface every transport implements, and
  the claim helper that decides which one agent acts on a request several
  could take); `slack-communication` (the working transport);
  `discord-communication` and `telegram-communication` (placeholders with the
  same interface, every operation answering "not implemented").
- **Fleet health:** `agent-health` (the usage sweep and the account handover),
  `agent-revive` (triaging a stuck agent and signing it back in).
- **Integrations:** `google-spreadsheet`, `notion-workspace`,
  `web-hierarchy-server` (a live web page of an agent's delegation tree),
  `rate-graphic` (a model's pre-flight check on a generated image).

## Requirements

- Linux with systemd, lingering enabled for the agents' user so their user
  units run with nobody logged in; or macOS (below). tmux; git.
- Python 3.11 or newer, standard library only; the fleet is tested on 3.14.
  Node 22 for the skills that carry a Node sub-package.
- Claude Code, on the agents' user's login PATH.
- `gh`, signed in, for `fleet upgrade`, which reads a tag's CI result through
  it.
- gitleaks at the version `tools/leak-gate/gitleaks.version` pins; `fleet
  install` fetches it.

## macOS hosts

A Mac runs the fleet on Apple Silicon with macOS 13 or newer, its shell
scripts under macOS's own bash 3.2. launchd keeps a user's jobs only while that
user is logged in, so the agents user is the account the Mac logs in
automatically, which is what brings the agents back after a restart, as
lingering does on Linux. With an administrator, each agent's session and stall
watchdog are LaunchDaemons that run as the agents user and that it can neither
stop nor edit; such an agent signs in with a token or an API key only, since a
LaunchDaemon has no window server and no login Keychain. agent-revive's
tap-to-solve share is not on macOS. `SETUP.md`, "A macOS host", lists every
difference and why.

## Documents

- `SETUP.md` - from an empty host to running agents.
- `CONVENTIONS.md` - the conventions slot and the house rules, with their
  defaults.
- `CONTRIBUTING.md` - hooks, branches, commit identity, landing, tags, outside
  pull requests.
- `SECURITY.md` - reporting a vulnerability, and the commit gate's threat model.

## Licence

MIT. See `LICENSE`.
