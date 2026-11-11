# Setting up a fleet

From an empty Linux or macOS host to agents running. Each step names the file
or skill that owns its details; this document is the order they go in, and it
restates none of them. A Mac follows the same steps with the differences "A
macOS host" (in section 1) lists.

Placeholders used below: `<agents-root>` (the directory every agent home sits
in), `<user>` (the agents user, the OS user every agent runs as), `<admin>`
(the administrator; both: "The two users"), `<tag>` (a release tag,
`vX.Y.Z`), `<agent-name>` (an agent's lowercase name), `<home>` (that agent's
home, `<agents-root>/<agent-name>`), `<project-dir>` (the install checkout's
directory name inside every agent home) and `<fleet>` (the fleet checkout:
`/opt/agent-fleet`, the administrator's, on a host with an administrator;
`<agents-root>/fleet` on one without).

## Install with Claude Code

On your own computer, install Claude Code
(https://code.claude.com/docs/en/setup), open it - in a checkout of the project
your agents will work in, if you have one - and paste:

```text
Install agent-fleet from https://github.com/bitekas/agent-fleet following its SETUP.md
```

Claude Code asks where the fleet will run - an AWS or Google Cloud instance, or
a physical Linux or macOS machine - and from your computer, over SSH, gets that
machine ready, installs what it needs and the fleet itself, asks you only what
it cannot find out, one question at a time, shows you the change to your
project before it commits anything, and offers to add your first agent. You
never open a session on that machine. Later, say "Upgrade agent-fleet
following ~/agent-fleet/SETUP.md".

**A Claude Code session handed one of those sentences** has none of the fleet's
skills yet. It:

1. clones the repository into `~/agent-fleet` on the machine it runs on, or
   fetches into the clone already there (`git -C ~/agent-fleet fetch --tags
   origin`), and checks out the newest release tag, which `git describe --tags
   --abbrev=0 --match 'v[0-9]*' origin/HEAD` names (a clone `fleet install`
   made read-only moves with `fleet upgrade <tag>` instead); `git` is all this
   needs, and when it is missing the session installs it, asking first;
2. reads `~/agent-fleet/.claude/skills/install-agent-fleet/SKILL.md` and
   follows it: from its first step to install, its Upgrade section to upgrade.

### What only you do

Installing Claude Code on your computer and pasting the sentence starts it.
After that, these are the only steps that stay with you, each for the reason
given; Claude prompts you for each one when it comes up:

1. **Turn SSH on, on a physical machine where it is off** (the skill's
   `targets/linux.md` or `targets/macos.md` walks you through it). Until SSH
   answers, nothing can reach the machine except someone sitting at it.
2. **A `sudo` password, on a machine whose `sudo` asks for one.** Only you
   know it. It goes to the `sudo -S` invocations that install what the machine
   needs and each agent's system units ("The two users"), and to nothing else.
3. **The Claude sign-in, for each account** (`/adding-an-agent`, option A by
   default). The vendor issues a sign-in to a person, in a browser.
4. **The Slack app and its token** (`/adding-an-agent`): create the app from
   the manifest Claude generates and install it to your workspace. Creating and
   installing an app is a workspace administrator's action in Slack.
5. **Invite the agent's bot to its channel and post the test message**
   (`/adding-an-agent` section 6). Only a member of the channel can invite the
   bot, and only a person's message proves the agent hears the channel.

That is all, except in two cases, each a secret of its own: a cloud provider's
credential, when the target is a cloud instance (its guide in `targets/` says
how to make one with the least access), and a GitHub token for `gh` on the
target before its first upgrade, because `fleet upgrade` reads a release's CI
result through it. When the project is not on GitHub, or `gh` is not signed in
on your computer, the repository's owner also grants the target read access to
it.

**Every secret comes in one of two ways, your pick each time.** Paste it into
the session: Claude writes it straight to its destination over SSH, keeps it
out of every command line, never repeats it, and it stays in that session's
transcript on your computer. Or type it into `/safe-box`, a one-time form on
127.0.0.1 - on your computer, or on the target through an SSH tunnel Claude
gives you the command for - so Claude never sees it.

Your answers to Claude's questions, and your OK before it installs packages,
commits to your project or pushes, are yours by design.

**Your computer shows the fleet's notice.** The project now carries the session
check (`CONVENTIONS.md`, "Adopted projects"), and a computer that only drives
the install has no fleet, so every Claude Code session you start in the project
there opens with the notice that agent-fleet is missing. That is by design: the
project's workflow depends on the fleet's skills. To have them in your own
sessions too, with Python 3.11 or newer and Node with npm on your computer:

```bash
install -d ~/agents
python3 ~/agent-fleet/bin/fleet install --agents-root ~/agents --units none
~/.local/bin/fleet link --config-dir ~/.claude --install <your checkout of the project>
```

`~/agent-fleet` is then read-only, and moves to a newer release with `fleet
upgrade <tag>`.

**Without Claude Code**, on the machine the fleet will run on, with nothing
installed yet:

```bash
git clone https://github.com/bitekas/agent-fleet.git <fleet>
git -C <fleet> checkout --detach <tag>
python3 <fleet>/bin/fleet install --agents-root <agents-root>
```

`<tag>` is the newest release: `git describe --tags --abbrev=0 --match 'v[0-9]*'
origin/HEAD`, run in the clone, prints it. With an administrator ("The two
users") the clone and `--part checkout` are the administrator's and `--part
agents` the agents user's (section 3); with none, one user runs it as it
stands. Sections 1 to 3 say what each line needs and does, and what `--units
refresh` adds; continue with section 4.

## The two users

The agents run Claude Code with every permission prompt off, so whatever their
OS user may do, an agent may do. With sudo that includes becoming root; with a
watchdog unit or config their user may stop or edit, it includes switching off
the one thing that answers for a hung session. A fleet host therefore has two
users:

| User | Who | What it does |
|---|---|---|
| the administrator, `<admin>` | the login with sudo: a cloud image's default user, or the person's own account on a physical machine | installs the prerequisites and creates the agents user (`install-agent-fleet`'s `bootstrap-target.sh`); owns the fleet checkout, `<fleet>` (`/opt/agent-fleet`), outside the agents root, and clones, installs (`fleet install --part checkout`) and upgrades it (`fleet upgrade`) without sudo; installs each agent's session unit and stall watchdog as system units, one printed root command each (`/adding-an-agent`); on an upgrade, re-installs those only when the release changed what they were rendered from (section 9). Its sudo is used for nothing else |
| the agents user, `<user>` | a dedicated account with no sudo and a locked password, which the bootstrap creates with the administrator's SSH keys | owns the agents root (mode 750, in its own group, which the bootstrap adds the administrator to so `fleet upgrade` can read the installs) and every agent home, and only reads the fleet checkout, through its skill links; runs `fleet install --part agents`, `fleet link`, every agent session (through the system units, as `User=`) and the daemons (its own user units, lingering on). It can neither change the fleet checkout, nor stop, disable or edit the system units that run and watch its agents, nor the watchdog's config under `/etc/agent-fleet/` |

This applies on every cloud instance, and on a physical machine whenever the
login has sudo. A login with no sudo at all has no administrator: the agents run
as that login, their units are user units it controls, a watchdog needs root
that nobody on the machine has, and the install reports itself UNPROTECTED. On
macOS the same split applies in launchd's terms: the agents user is a standard
account that also logs in automatically, so it has a password, macOS's to keep;
the system units are LaunchDaemons with `UserName` the agents user; and its
agents sign in only with a token or an API key, since a LaunchDaemon has no
window server and no login Keychain (`install-agent-fleet`'s
`targets/macos.md`, section 5).

The check, as the agents user, at the end of an install and of each added
agent - it prints facts, never a secret, and FAILs when the agents user can use
sudo, or change or stop what supervises it:

```bash
python3 <fleet>/.claude/skills/install-agent-fleet/verify-privileges.py --agent <agent-name>
```

`--no-admin` is the form with no administrator, where it reports UNPROTECTED
instead of failing. It FAILs, too, when the agents user can change any file or
directory of the fleet checkout, or a directory above it: the checkout is the
code every agent runs.

## 1. The host

1. The two users above. On a host with an administrator, `install-agent-fleet`'s
   `bootstrap-target.sh --install --read-back <read-back file> --agents-user
   <user>`, run by `<admin>` through sudo with the skill's step-2 read-back
   message saved in that file (without it it refuses), creates `<user>` and
   every per-user part of steps 2 to 4 for it; every command below that is not
   marked otherwise runs
   as `<user>`.
2. Packages: git, tmux, Python 3.11 or newer (the fleet is tested on 3.14),
   Node 22 with npm, and Claude Code, with `claude` on `<user>`'s login PATH;
   and `gh`, signed in, for `fleet upgrade`, which reads a tag's CI result
   through it.
3. Lingering, so the agents' user units run with nobody logged in. As `<user>`:

   ```bash
   loginctl enable-linger
   ```

   systemd's own policy lets a user turn lingering on for themselves; where a
   site policy refuses it, `<admin>` runs `sudo loginctl enable-linger <user>`.

4. The agents root:

   ```bash
   install -d <agents-root>
   ```

   `fleet install` (section 3) creates the claims directory in it,
   `<agents-root>/claims`, mode 700: the one directory per host where the claim
   helper records which agent took a request several could take.

5. The organization secrets directory - the organization's, the project's and
   the infrastructure's credentials - mode 700, beside the agent homes and never
   inside one:

   ```bash
   install -d -m 700 ~/.fleet-secrets
   ```

   The fleet finds it as `$FLEET_SECRETS_DIR`, else the variable the install
   manifest's `secrets.legacy_env` names, else the manifest's
   `secrets.default_dir`, which the template sets to `~/.fleet-secrets`; a
   skill's `config.json` names a credential in it as
   `${FLEET_SECRETS_DIR:-~/.fleet-secrets}/<file>`. An install that keeps the
   directory elsewhere writes that path in `secrets.default_dir` (step 4) and
   as the fallback of every such config path. An agent's own credentials - its
   chat bot token, a service account issued in its name - go in its
   personal-secrets directory instead (`/agent` section 3).

### A macOS host

Every step of this document applies, with these differences.
`install-agent-fleet`'s `targets/macos.md` is how a Mac is reached and made
ready, and `/adding-an-agent` renders and installs each agent's jobs; neither
is restated here.

- **The machine**: Apple Silicon, and macOS 13 or newer (`targets/macos.md`
  section 1 says why). The fleet's shell scripts run under macOS's own
  `/bin/bash` 3.2 and its BSD userland (`CONTRIBUTING.md`, section 5).
- **Python**: Homebrew's `/opt/homebrew/bin/python3`, 3.11 or newer, runs every
  job; macOS's own `/usr/bin/python3` is older. `FLEET_PYTHON` names another
  interpreter, and `fleet install` refuses one older than 3.11.
- **Automatic login instead of lingering** (step 3): the agents' daemons are
  jobs in launchd's per-user domain, which exists only while that user is
  logged in at the console. So the agents user is the account the Mac logs in
  automatically, with FileVault off, or a restart waits at the unlock screen
  (`targets/macos.md` sections 4 and 5). `fleet install` refuses a Mac where
  the user has no such domain.
- **The agents root** (step 4) is outside the folders macOS privacy protection
  keeps a launchd job from reading (Desktop, Documents, Downloads and the like);
  `fleet install` refuses one inside them.
- **Jobs instead of units**: the daemons are LaunchAgents rendered from
  `systemd/*.plist.in` (`systemd/README.md`, "macOS: launchd"), and each agent's
  session and stall watchdog are rendered from the plist examples the closing
  checklist names. Every label starts with the host settings' `launchd_prefix`,
  `com.agent-fleet` by default. With an administrator the session and the
  watchdog are LaunchDaemons it installs root-owned, running as the agents user
  ("The two users"); `fleet status` and the checks read launchd.
- **Sign-in**: an agent whose session is a LaunchDaemon signs in only with a
  long-lived token or an API key, since a LaunchDaemon has no window server and
  no login Keychain: `/adding-an-agent` refuses a full login for it, and
  `/agent-revive` switches its account by token.

Not on macOS, and why:

- **agent-revive's tap-to-solve share**: x11vnc shares an X11 display, which
  macOS does not have. `share` exits 2 there, naming the human route
  (`/agent-revive` step 7e).
- **The stall watchdog's sandbox** (`ProtectSystem`, `ProtectHome`,
  `ReadWritePaths`, `NoNewPrivileges`): launchd has no namespacing. The watchdog
  runs as the agent's user, the boundary its session already has.
- **Restart back-off**: launchd waits a fixed 10 seconds before it restarts a
  daemon that exited, where its systemd unit backs off from 10 seconds to 5
  minutes.
- **A process's environment**: macOS shows another process's arguments, never
  its environment, so a daemon's config is verified from its job definition
  (`launchctl print`), not from the process.

## 2. The agent home layout

Every agent home is `<agents-root>/<agent-name>/`, laid out as `/agent` section
3 describes: personal secrets, workspaces, playground, config, state,
artifacts, blockers, and the agent's own checkout of the install repository.
`/adding-an-agent` creates one per agent in step 7.

## 3. Clone and install the fleet

With an administrator, the checkout is the administrator's and outside the
agents root (`bootstrap-target.sh` made `/opt/agent-fleet` for it), and each user
runs its own part; `fleet install` refuses a part run by the wrong user, and
the agents part a checkout the agents user could change:

```bash
# as <admin>:
git clone https://github.com/bitekas/agent-fleet.git /opt/agent-fleet
git -C /opt/agent-fleet checkout --detach <tag>
/opt/agent-fleet/bin/fleet install --agents-root <agents-root> --part checkout
# as <user>:
/opt/agent-fleet/bin/fleet install --agents-root <agents-root> --part agents --units refresh
```

With no administrator, one user runs both parts at once:

```bash
git clone https://github.com/bitekas/agent-fleet.git <agents-root>/fleet
git -C <agents-root>/fleet checkout --detach <tag>
<agents-root>/fleet/bin/fleet install --agents-root <agents-root> --units refresh
```

`--part checkout` enables the commit hooks on the checkout, installs each
skill's Node sub-package and makes the tracked files and directories
read-only, writes its user's host settings (for `fleet upgrade`) and, the first
time, the identities `fleet upgrade` trusts (below); `--part agents` does
everything else below.

**The identities `fleet upgrade` trusts** for its outside-work refusal are
`~/.config/agent-fleet/identities.json` of the checkout's owner (beside its host
settings), never an install manifest, which the agents user may edit. The first
`fleet install --part checkout` (or `--part all`) writes it from the installs'
`upstream.identity` it can read, and `fleet identities --add <email>`, as the
checkout's owner, adds one: on a new host, before any agent exists, add the
install manifest's `upstream.identity.email` that way. A manifest identity the
file lacks is ignored, and the upgrade names it. With no file, one user owning
both the checkout and the agents root trusts the manifests, as nothing there
could keep the agents from editing either; with an administrator a contributing
host's upgrade is refused until the file exists (section 9). Nothing the fleet runs writes into the
checkout: Python writes no bytecode there (`PYTHONDONTWRITEBYTECODE` in every
unit and in `fleet`'s own runs).

`fleet install` creates the claims directory when it is absent, writes the
host settings file (`~/.config/agent-fleet/host.json`: agents root, fleet
checkout, claims directory), enables the commit hooks on the checkout, makes
its tracked files and directories read-only, installs each skill's Node
sub-package, fetches gitleaks at the pinned version into `~/.local/bin`, links
`~/.local/bin/fleet` and `~/.local/bin/claude-attach`, and renders the user
units `--units` names: `refresh` the refresh timer, which it enables; `all`
also the daemons' unit templates, which need an agent home holding its checkout
of the install repository, so `/adding-an-agent` runs it with the first agent
(step 7); `none` nothing. It never writes under /etc, it refuses to run from a
linked worktree, and running it again prints `nothing changed`.

The read-only checkout has two consequences:

- **A copy keeps the mode of its source**, so a `cp` out of the checkout is a
  0444 file that the first edit, or the first daemon write, refuses. Every copy
  step here and in the skills' instructions sets the mode instead:
  `install -m 644 <src> <dst>` for a file people edit, `install -m 600` for a
  daemon config or anything else only its owner reads.
- **Removing a clone** - a trial clone, a retired host - needs its write bits
  back first: `chmod -R u+w <clone> && rm -rf <clone>`.

## 4. The install manifest

The install repository is the one the agents work in; every agent home holds a
checkout of it at `<project-dir>`. **It is a git repository**: the fleet finds
the manifest as `.claude/fleet.json` at the top of the git work tree it runs in
(from outside one, through the agent's `CLAUDE_CONFIG_DIR`), so a plain
directory holding the file resolves nothing. If your agents have no repository
yet, `git init` one. A repository takes the fleet by being adopted, from its
top level:

```bash
fleet adopt .
```

`fleet adopt <project>` writes `.claude/fleet.json` from
`templates/fleet.example.json` when the repository has none, and never over an
existing one. It merges the fleet's session check into `.claude/settings.json`,
keeping every key and hook already there, and refuses a settings file that is
not valid JSON. A repeat prints `nothing changed`. The session check is a
SessionStart hook: every session started in the repository runs it, and it puts
one notice into the session when the fleet is missing on the host, older than
the manifest's `fleet.min_tag`, or not linked for the session's config
directory, and nothing otherwise (`CONVENTIONS.md`, "Adopted projects"). An
interactive session runs it once the folder's workspace trust dialog is
accepted; a `claude -p` session runs it at once.

Replace every value of the manifest; each `_comment` says what it is. Then, from that checkout,
`fleet settings` prints the resolved settings with the fleet defaults applied.
`fleet settings` refuses a manifest with an unknown, mistyped or missing key, a
value still in the template's placeholder form (one `<...>` with a space
inside), or a convention or `upstream.deny_list` that names a file this checkout
does not have (a convention skill is `.claude/skills/<name>/SKILL.md`; a doc path
holding a `<placeholder>` is not followed), by naming the key.

- **`conventions`** is the slot for your development process (`CONVENTIONS.md`).
  Point a key at one of your own skills or documents, or leave it `null`: then
  you have no such convention, and the skills that read it skip that step and
  say so.
- **`house_rules`** are the fleet's writing and cadence defaults; change only
  what you want different (`CONVENTIONS.md`).
- **`upstream`** matters only if your agents contribute to the fleet:
  `deny_list` names your private deny list for the commit gate, or is `null`
  when you have no private values.

Commit `.claude/fleet.json` and `.claude/settings.json` in the install
repository. They are the install's, and they stay there.

## 5. Each skill's install context, install-wide

For every skill in the manifest's `skills`, `fleet where <skill>`, run from a
checkout of the install repository, prints its install context,
`<install root>/.claude/skills/<skill>/`. Create there:

- `CONTEXT.md`: what this install's values are and who they belong to, as the
  skill's `SKILL.md` says its context holds. It is prose, except where a check
  parses it: the `agent` skill's carries a paths table whose row form its
  `installation/INSTRUCTION.md` step 0 gives.
- `config.json`, for a skill that ships a `config.example.json` and reads its
  config from the install context, copied with `install -m 644` and every
  placeholder replaced.

`tests/fixtures/install/.claude/skills/<skill>/`, where it exists, holds a
worked `CONTEXT.md` and `config.json` with synthetic values.

**A daemon's config is not in the install context.** It is one file per agent,
in the agent's config directory, at the name its unit reads:
`<home>/config/scheduler.json` for the scheduler,
`<home>/config/<watch.job>.json` for each working chat transport's watcher
(`<home>/config/slack-watch.json` for Slack), and for the stall watchdog
`/etc/agent-fleet/stall-watchdog/<agent-name>.json`, root's, where an
administrator installs it ("The two users"), else
`<home>/config/stall-watchdog.json`. `systemd/README.md`,
"What runs", is the table the daemon units are rendered from, and
`python3 <fleet>/systemd/agent-daemons.py jobs --json` prints it.

Then follow each skill's `installation/INSTRUCTION.md` where it has one, doing
now only the steps that are install-wide. A step that needs an agent - its
home, its own credential, its own daemon - waits for step 7; an instruction
that has such steps opens by saying which they are. The skills with per-agent
steps are `agent`, `scheduled-tasks`, each working chat transport,
`stall-watchdog`, `google-spreadsheet` and `web-hierarchy-server`.

A config names a credential's PATH; the credential itself is a file of its own,
mode 600, in a secrets directory, and never in the repository. A skill's install is recorded
by the command its instruction's "Record the install" step gives, which reads
the version from that skill's `SKILL.md`; never write that file by hand.

## 6. The knowledge store

Install `/knowledge-base` by its `installation/INSTRUCTION.md`: the store root
is a directory outside every agent home and its own git repository, never
nested inside another checkout, holding `templates/knowledge-store/index.md` as
its only file. `examples/knowledge-base/` shows what a filled store looks like;
nothing from it is copied in.

## 7. Add each agent

Load `/adding-an-agent` in a Claude Code session and follow it, once per agent;
it acts on the host over SSH, or on the machine it runs on. It is the authority
for every step of adding one: the interview, the charter from a template in
`templates/personas/`, the home, the empty config directory and its sign-in (a
long-lived token from `claude setup-token` by default, which makes model
requests only - Remote Control needs the full-login option), every secret taken
in without being printed, the chat app, the daemon configs, the per-agent steps
of the skills in step 5, `fleet link`, the daemon user units, the agent's own
unit from `templates/claude-agent.service.example` (on macOS
`templates/claude-agent.plist.example`) and its stall watchdog from
`/stall-watchdog` (system units the administrator installs, "The two users"),
the health check, the privilege check, and a test message that proves the
agent hears its channel.

## 8. Check until clean

```bash
fleet check-all <agent-name>   # every linked skill's installation/check, one table
fleet status <agent-name>      # links, tag, session check, charter step pointers, daemons, watchdog; exit 1 on any drift
```

Repeat for every agent until each table is clean and `fleet status` exits 0,
and the privilege check ("The two users") exits 0 - or 4, UNPROTECTED, on a
host with no administrator.

`fleet status` reads this machine's systemd - the user's manager and the
system's, read-only - whatever `HOME` it runs under; on macOS, launchd's user
and system domains. A trial install on a host that already runs a fleet
therefore reports that host's units of the same names.

## 9. Upgrading

```bash
fleet upgrade <tag>              # refuses a dirty checkout, an untagged or failing commit
fleet upgrade <tag> --rollback   # to an older tag
```

Skill text takes effect at once in every running session, daemons at the
refresh timer's next run, and watchdogs within one cycle; no session restarts.
`fleet upgrade` runs as the checkout's owner - the administrator, or with no
administrator the one user - and refuses anyone else, naming the owner; it needs
no root. It reads every install's manifest under the agents root, so the
administrator must be able to read that directory (it says so, changing
nothing, when it cannot). An install's `fleet.min_tag` is read from its manifest
as it stands: an edited floor can only make an upgrade go on or stop, and the
person runs it. On a host whose agents contribute to the fleet (an install
declares `upstream`, or the identities file names anyone) it refuses a commit
whose author or committer is not a trusted identity, as outside work for the
repository owner to review, and refuses outright while it trusts no identity,
naming `fleet identities --add`. A host whose agents do not contribute skips
that check, saying so, and trusts the release tag: annotated, published on
origin, on `main`, CI green and clean in the leak backstop. Its one root step is
the administrator's, and only when the release changed a file the system units
were rendered from - `templates/claude-agent.service.example`, or the stall
watchdog's unit example or `config.example.json`; on macOS
`templates/claude-agent.plist.example` or the watchdog's plist example or its
`installation/render-plist.py` in their place: re-render each agent's unit
or watchdog by `/adding-an-agent` section 5 step 6 or 7 and install it with the
root command that prints. A unit installed again restarts nothing; its new
shape applies at the next restart.
For a MAJOR tag, try one agent first: `fleet link <agent-name> --from <a worktree
at the tag>` and `fleet pin-daemons <agent-name> --from <same>`, then upgrade
the host and return that agent with `fleet link <agent-name>` and
`fleet pin-daemons <agent-name> --clear`.

## Closing checklist

Every placeholder an install fills, by file. Tick a line when the file holds a
real value for every key it names, except a key its line says keeps the
example's value or stays out of the file.

**`.claude/fleet.json`**, from `templates/fleet.example.json`:

- [ ] `schema`
- [ ] `fleet.repo`, `fleet.min_tag`
- [ ] `skills`
- [ ] `transports.enabled`, `transports.default`
- [ ] `conventions.definition_of_done`, `conventions.feature_checklist`,
      `conventions.branch_naming`, `conventions.workspace`,
      `conventions.release`, `conventions.environments`,
      `conventions.people_notes`
- [ ] `house_rules.questions_per_message`
- [ ] `house_rules.blocker_chase.every_minutes`, `house_rules.blocker_chase.tz`,
      `house_rules.blocker_chase.days`, `house_rules.blocker_chase.start`,
      `house_rules.blocker_chase.end`
- [ ] `house_rules.state_the_fact`
- [ ] `house_rules.times.cities[].name`, `house_rules.times.cities[].tz`
- [ ] `house_rules.ascii_skill_prose`
- [ ] `secrets.legacy_env`, `secrets.default_dir`
- [ ] `upstream.identity.name`, `upstream.identity.email`,
      `upstream.deny_list`, `upstream.outside_pr_reviewer`

**Each skill's `config.json`**, from that skill's `config.example.json`, for
every skill in the manifest's `skills` that ships one: every key the example
carries outside its `_comment` keys, one line per skill.

- [ ] `adding-an-agent` - none: it needs no config.
- [ ] `agent-revive` - `fleet.agents_home`, `fleet.tmux.tmpdir`,
      `fleet.tmux.target`, `fleet.systemd_unit`, `fleet.daemons[].name`,
      `fleet.daemons[].pattern`, `accounts.pool_file`, `accounts.lease_file`,
      `accounts.ledger_file`, `accounts.handover_ledger_file`,
      `accounts.tokens_dir`, `accounts.profiles_dir`,
      `accounts.exclude[].username`, `accounts.exclude[].reason`,
      `recovery.mailbox`, `share.vnc_port`, `share.web_port`,
      `share.funnel_port`, `share.novnc_dir`, `share.page`, `share.minutes`,
      `share.tailscale`
- [ ] `google-spreadsheet` - `identity.agent`, `identity.subject_template`,
      `credential.key_path`, `api.sheets_base`, `api.drive_base`,
      `scopes.sheets`, `scopes.drive`
- [ ] `knowledge-base` - `store.root`
- [ ] `notion-workspace` - `workspace.name`, `workspace.id`,
      `mcp.connector_name`, `mcp.acts_as.name`, `mcp.acts_as.email`,
      `mcp.acts_as.user_id`, `bot.name`, `bot.user_id`, `bot.owner_user_id`,
      `token.path`, `oauth.credentials_path`, `oauth.redirect_uri`
- [ ] `rate-graphic` - `ratings_log.path`,
      `credentials.service_account_key_path`, `secret.name`, `secret.project`,
      `api.base`
- [ ] `restart` - `service.unit`, `service.reattach_command` (each keeps its
      <agent> token, which the reading agent fills),
      `service.reboot_command`, `stack.teardown_command`,
      `stack.stray_process_patterns`, `handoff.file`
- [ ] `scheduled-tasks`, one file per agent - required:
      `owner.claude_config_dir`, `db.path`, `defaults.tz`; optional, both or
      neither: `requester.directory_file`, `requester.directory_key`; every
      other key stays out of the file, because the scheduler carries its default:
      `db.busy_timeout_secs`, `loop.tick_secs`,
      `loop.max_active_tasks`, `loop.max_fires_per_tick`,
      `loop.resync_lag_secs`, `eval.timeout_secs`, `eval.max_errors`,
      `eval.max_due_slots`, `emit.max_line_chars`, `emit.reason_chars`,
      `emit.requester_chars`, `emit.title_chars`, `emit.min_interval_secs`,
      `emit.replay_grace_secs`, `emit.replay_max`,
      `emit.alert_min_interval_secs`, `requester.id_pattern`,
      `add.simulate_days`, `add.fires_per_day_warn`,
      `retention.auto_archive_days`, `retention.runs_per_task`,
      `retention.purge_days`
- [ ] `slack-communication` - `workspace.domain`, `workspace.team_id`,
      `bot.user_id`, `bot.handle`, `bot.display_name`, `token.path`,
      `owner.claude_config_dir`, `state.dir`, `state.prefix`, `poll.poll_secs`,
      `poll.sweep_secs`, `poll.sweep_budget`, `poll.rediscover_secs`,
      `poll.recent_join_window_secs`, `poll.dm_baseline_window_secs`,
      `slack.api_base`, `known_users.<user-id>`
- [ ] `stall-watchdog`, one file per agent - `tmux.tmpdir`, `tmux.target`,
      `stall.stall_secs`, `stall.poll_secs`, `stall.idle_tail_lines`,
      `stall.known_prompts[].name`, `stall.known_prompts[].match`,
      `stall.known_prompts[].keys`, `stall.known_prompts[].notice`,
      `state.dir`, `state.prefix`, `owner.claude_config_dir`; keep the
      example's value unless the terminal UI changed: `stall.prompt_patterns`,
      `stall.idle_patterns`, `action.deny_key`, `action.notice`
- [ ] `web-hierarchy-server` - `server.host`, `server.cap_kb`,
      `server.preferred_ip_prefix`, `transcripts.config_dir`,
      `transcripts.projects_subdir`, `identities.file`, `packages.repo_root`,
      `packages.dir_pattern`, `labels.root_owner`,
      `fleet.by_config_dir.<config-dir-key>`, `servers.<unit-name>.config_dir`,
      `servers.<unit-name>.port`

**Each charter**, `.claude/agents/<agent-name>.md`, from a persona template:

- [ ] the five the `/adding-an-agent` interview fills: `<agent-name>`,
      `<Agent-Name>`, `<agent-role>`, `<agent-voice>`, `<answers-to>`
- [ ] the ones each template's opening comment lists, filled by hand:
      `<transport-skill>`, `<watch-job>` (every template); `<peer-agents>`,
      `<escalation-order>` (lead engineer); `<revive-channel>`,
      `<agents-root>` (health doctor); `<agents-channel>`, `<intake-agents>`,
      `<agents-root>` (root orchestrator)

**Each agent's session unit**, from `templates/claude-agent.service.example`:

- [ ] `<agent-name>`, `<Agent-Name>`, `<agents-root>`, `<fleet>`,
      `<project-dir>`, `<watch-job>`, `<watch-config-env>`, `<uid>`,
      `<agents-user>`, `<auth-mode>`

**On macOS, each agent's session job**, from `templates/claude-agent.plist.example`,
by `/adding-an-agent` section 5 step 6, through the stall-watchdog skill's
`installation/render-plist.py --job session`:

- [ ] `<launchd-prefix>`, `<agent-name>`, `<Agent-Name>`, `<agents-root>`,
      `<fleet>`, `<project-dir>`, `<watch-job>`, `<watch-config-env>`,
      `<auth-mode>`, `<python>`, `<path>`, which the renderer derives from where
      tmux, `claude` and `<python>` are and follows with `/opt/homebrew/bin`,
      `/usr/local/bin` and the system directories, and in the system form
      `<agents-user>`
- [ ] `<uid>` stays: it is only in the opening comment, which the step does
      not fill

**Each agent's stall-watchdog unit**, from `.claude/skills/stall-watchdog/installation/agent-stall-watchdog.service.example`:

- [ ] `<agent>`, `<user>`, `<checkout>`, `<fleet>`, `<agents-root>`,
      `<state dir>`, `<tmux-dir>`

**On macOS, each agent's stall-watchdog job**, from `.claude/skills/stall-watchdog/installation/agent-stall-watchdog.plist.example`,
by `/adding-an-agent` section 5 step 7, through the skill's `installation/render-plist.py`:

- [ ] `<launchd-prefix>`, `<agent>`, `<user>`, `<checkout>`, `<fleet>`,
      `<agents-root>`, `<state dir>`, `<tmux-dir>`, `<python>`, and `<path>`,
      which the renderer derives from where tmux and `<python>` are
- [ ] `<rendered>`, `<uid>` stay: they are only in the opening comment's
      commands, which the rendered file does not keep

**Each agent's web-hierarchy-server unit**, from `.claude/skills/web-hierarchy-server/installation/web-hierarchy-server.service.example`,
by the `sed` in its `installation/INSTRUCTION.md` step 3:

- [ ] `YOUR_USER`, `AGENTS_ROOT`, `YOUR_AGENT`, `PORT`,
      `/path/to/your/install-checkout`, `/path/to/your/fleet`, `agent N`

**On macOS, each agent's web-hierarchy-server job**, from `.claude/skills/web-hierarchy-server/installation/web-hierarchy-server.plist.example`,
by the `sed` in its `installation/INSTRUCTION.md` step 3:

- [ ] `<launchd-prefix>`, `<n>`, `<agents-root>`, `<agent>`,
      `<install-checkout>`, `<fleet>`, `<port>`
- [ ] `<rendered>` stays: it is only in the opening comment's install
      commands, which the `sed` does not fill

**The proof that none is left**, with a check that is first seen to find one:

```bash
command grep -nE '<[A-Za-z][A-Za-z0-9-]*>' <agents-root>/fleet/templates/personas/lead-engineer.md | head -3   # MUST print lines
command grep -nE '<[A-Za-z][A-Za-z0-9-]*>' .claude/agents/*.md                                                # must print nothing
```

If the first line prints nothing the pattern is blind, and the silence of the
second means nothing: fix the pattern before trusting it. Run the second line
over each filled unit file the same way - for the stall-watchdog unit with
`'<[A-Za-z][A-Za-z0-9 -]*>'`, whose `<state dir>` holds a space, and for the
web-hierarchy-server unit by grepping for each of its tokens above, which carry
no angle brackets. A filled plist is proved by `plutil -lint <file>` instead,
which refuses a placeholder left outside a comment, an unclosed tag to the XML
parser (the render steps named above run it); its first check is the same
command over the unfilled example, which must fail. Then read each
`config.json` against its example: a placeholder
value there is a string such as `your-restart-command` or
`<absolute path to the pool file>`, which no single pattern finds. An `<agent>`
token that the example's comment says the reading script or agent fills
(agent-revive's `fleet` block, restart's `service.unit` and
`service.reattach_command`) stays.
