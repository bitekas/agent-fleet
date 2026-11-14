---
name: install-agent-fleet
version: 1
description: >
  Install agent-fleet on a target machine and adopt a project as its install,
  driven end to end over SSH by Claude Code on the person's own machine - ask
  where the fleet will run (an AWS or Google Cloud instance, or a physical
  Linux or macOS machine) and follow that target's guide, install the target's
  prerequisites after one OK and create the dedicated agents user without sudo
  that runs the agents, clone the fleet there at its newest release tag
  and run `fleet install`, ask the person only what cannot be discovered, one
  question at a time, adopt the project with `fleet adopt` and the attribution
  block, show the diff and commit on the person's OK, hand off to
  adding-an-agent, and close with a summary. Also upgrades the target to a
  newer release. Load when asked to "install agent-fleet" or to "upgrade
  agent-fleet", and when handed "Install agent-fleet from <repository>
  following its SETUP.md".
requires_install: false
---

# Installing agent-fleet

The route from one pasted sentence to a fleet running on a target machine. The
person talks only to this session, on their own machine; every step on the
target runs from here over SSH, and the person never opens a session there.
This file orders steps that are defined elsewhere and restates none of them:
`SETUP.md` in the fleet repository is the manual reference for every step and
lists the steps only the person can do, each `fleet` subcommand prints what it
changed, the guides in `targets/` beside this file own reaching a machine, and
`/adding-an-agent` owns everything about an agent. Where this file and one of
them disagree, they win; correct this file. Asked to upgrade, go straight to
the Upgrade section at the end.

Placeholders used below:

| Placeholder | Is |
|---|---|
| `<clone>` | the clone of the fleet this file was read from, here: `~/agent-fleet` |
| `<admin-host>` | the SSH destination the target guide ends with, `<admin>@<address>`: `<admin>` is the login with `sudo`, the administrator; `localhost` is a target like any other |
| `<agents-user>` | the dedicated user the agents run as, without sudo (step 3 question 9; `agents` unless the person names another) |
| `<host>` | the agents user's SSH destination, `<agents-user>@<address>`, from step 4 on; every [target] step runs as it. With no administrator it is `<admin-host>` itself |
| `<agents-root>` | on the target, the directory the agent homes sit in: `~/agents` of the agents user unless the person names another |
| `<fleet>` | the target's fleet checkout: with an administrator `/opt/agent-fleet`, the administrator's and outside the agents root (step 4 makes it), else `<agents-root>/fleet` |
| `<project>` | the person's checkout of the install repository, here: the git project the agents will work in |
| `<work>` | a temporary working clone of the project on the target (step 6) |
| `<scratch>` | a temporary directory here, for files on their way to or from the target |
| `<kept>` | `~/agent-fleet-install` here (`install -d -m 700`), for a file the person needs after this session: never a secret |
| `<read-back file>` | step 2's `Read back before install` message, word for word, in a file: written in `<kept>` here, copied to the target for step 4 |
| `<tag>` | a release tag, `vX.Y.Z` |

**Two machines, and every step says which.** A step marked **[here]** runs in
this session. A step marked **[target]** runs as `ssh <host> '<command>'`,
and one marked **[admin]** as `ssh <admin-host> '<command>'`; a file goes
either way with `scp`. An SSH command reads no login profile: `fleet` there is
`~/.local/bin/fleet`, and `claude` runs through `bash -lc`, as the agents'
units start it. Questions, diffs and the summary are always here.

**Two users on the target** (`SETUP.md`, "The two users"). The agents run with
every permission prompt off, so whatever their user may do, an agent may do.
They therefore run as a dedicated **agents user** without sudo, and the
**administrator** - the login with sudo, a cloud image's default user or the
person's own account - installs what they must not be able to stop or edit:
each agent's session unit and its stall watchdog, as system units. Every
agent-level step runs as the agents user, over SSH with the person's key, which
step 4 gives it: the least-touch way, since every command then runs as written,
with nothing wrapped in `sudo -u`. The administrator's sudo is used by step 4,
by the root commands `/adding-an-agent` prints, and by the Upgrade section's
root step, each of which says so. This applies on a cloud instance, and on a
physical machine whenever the login has sudo; a login with no sudo at all is
the one case with no administrator (step 2), where the agents run as that login
in user units and the install reports them UNPROTECTED. On macOS the system
units are LaunchDaemons with `UserName` the agents user, which is also the
account that logs in automatically (`targets/macos.md` section 5).

**This file and every skill it hands off to are READ BY PATH from `<clone>`.**
In a skill read that way, a skill named as `/adding-an-agent` is
`<clone>/.claude/skills/adding-an-agent/SKILL.md`; a command it runs on the
agent's machine is a [target] command; and `${CLAUDE_SKILL_DIR}` is that
skill's directory in `<clone>` for a [here] command and in `<fleet>` for a
[target] one.

**An answer the request already carries is used, not asked again** - the target,
an agents root, a transport, a time zone, "no units", an OK to install or to
commit. Step 2's report lists each one back, so the person can correct it, and
that report is REQUIRED, never skipped because the request answered
everything: it is its own message, headed `Read back before install` and sent
before step 3, even in an unattended session where nobody will answer it, and
the closing summary lists the same values again as taken from the request. A
request that answers everything then runs to the end without stopping, which is
how an unattended session runs this skill.

**Secrets: two ways in, and never echoed.** Every secret the install needs - a
cloud credential, a `sudo` password, the macOS agents user's password, a
Claude sign-in token or API key, a chat bot token - is asked for with both
ways offered, and the person picks:

1. **Paste it into this session.** Claude writes it with the file-edit tool
   into a file in `~/.agent-fleet-secrets/` here (made with `install -d -m 700`),
   never into a shell command: a command's text is the shell's argument list
   (measured: Claude Code runs each command as `bash -c ... eval '<command>'`),
   which other processes on the machine can read in `/proc`. It then sends that
   file over SSH on standard input straight into the secret's destination - a
   mode-600 file (`ssh <host> 'umask 077 && cat > <destination>' < <file>`),
   or, for a `sudo` password, the standard input of the one `sudo -S -p ""`
   invocation that needs it, with nothing written on the target - removes the
   local file by its literal path once its last use is done, and never repeats
   the value. The prompt says that a pasted secret stays in this session's
   transcript on this computer.
2. **`/safe-box`**: a one-time form on 127.0.0.1 that writes each declared
   secret into its file at mode 600; Claude never sees the values. A secret
   whose file is on the target, once the fleet is there, is served there - its
   section 3 gives the form for a session on another machine - and the person
   gets its tunnel command, URL and code. A secret needed before that, the
   `sudo` password the key install and step 4 read, is served here from
   `<clone>` with `FLEET_SECRETS_DIR=~/.agent-fleet-secrets`, and the person
   opens the URL on this computer, with no tunnel.

Either way, Claude checks only that the destination is there and not empty
(`test -s`), never its content.

**Root on the target, in this skill, is one step**: `bootstrap-target.sh
--install --read-back <read-back file>` under ONE `sudo -S` (step 4) [admin]. A cloud
image's user runs `sudo` without a password; on a physical machine the
password comes in by either way above, and the target guide's key install
uses the same file.
Claude asks ONCE before that step, saying what it will install and why, and
never runs it silently. On macOS the one restart after it (step 4) is asked
for the same way, unless the person restarts the Mac themselves.

**The running session's own config directory is never linked** (`fleet link`;
it is `$CLAUDE_CONFIG_DIR`, else `~/.claude`) unless the person asks for exactly
that. A personal skill link reaches every project that config directory ever
opens, not only this one, and it outranks the project's own skill of the same
name.

**The session check `fleet adopt` adds (step 6) speaks in sessions started in
the project**, this one included after a compaction. While this skill runs,
its notice describes the install in progress: finish the step in hand rather
than act on it.

---

## 1. Where the fleet will run [here]

Load `/talking-to-humans` first: every question in this skill goes out one per
message (the house rule `questions_per_message`, whose fleet default is one,
`CONVENTIONS.md`), numbered against the running total, with a plain-words brief
and the value this run uses when the person has no preference. A target guide's
questions join the same count.

**The first question is where the fleet will run**:

| Answer | Guide |
|---|---|
| an AWS instance | `targets/aws.md` |
| a Google Cloud instance | `targets/gcp.md` |
| a physical Linux machine - another one, or this one | `targets/linux.md` |
| a physical macOS machine | `targets/macos.md` |

Read that guide beside this file and follow it. It ends when `ssh -o
BatchMode=yes <admin-host> true` exits 0 from here, and names `<admin-host>`;
step 2 takes over from there. A macOS host is supported from fleet release v1.1.0 on, and
`targets/macos.md` says what it needs.

## 2. Detect, and say what is there

**This step ends with one message whose first line is
`Read back before install`, and step 3 does not start until that message is
sent.** It is the person's one chance to correct an answer before anything is
installed. **Write the same message, word for word, into `<read-back file>` as
well as sending it**: step 4's `bootstrap-target.sh --install --read-back
<read-back file>` takes that file, prints it at the top of its output and keeps
a copy on the target, and refuses (exit 2, nothing changed) without it, or when
its first line is not exactly `Read back before install` or no answer follows,
naming the message.

Read only, before any change. The message is compact (`/talking-to-humans`
rule 6): what was detected, with every answer taken from the request listed
back beside it. A request that already carries every answer still gets it,
printed before step 3, even when nobody is there to read it; the closing
summary's list of the same answers comes too late to stand in for it.

| What | Where | How |
|---|---|---|
| the administrator | admin | `sudo -n true` exits 0: sudo with no password. Else `id -nG` lists `sudo`, `admin` or `wheel`: sudo with a password. Else the login has no sudo, and there is no administrator: `<host>` is `<admin-host>`, units are user units, and the report says the agents will be UNPROTECTED |
| prerequisites | admin | `bootstrap-target.sh --check` (step 4), copied there first; it changes nothing |
| the agents user | admin | `getent passwd <agents-user>` (on macOS `dscl . -read /Users/<agents-user> UniqueID`), for a name the request gave or an earlier install used; step 4's check reads the rest |
| host settings | target | `~/.config/agent-fleet/host.json`: its `agents_root` and `fleet_checkout` (once the agents user exists) |
| fleet checkout | target | whether `<fleet>` is a clone, and its tag: `git -C <fleet> describe --tags --exact-match` |
| agent homes | target | every directory under `<agents-root>` holding a `.claude/` directory, other than `fleet` |
| install repository | here | `git rev-parse --show-toplevel` in the session's directory, and its remote and branch (`git remote -v`, `git status -sb`); whether its branch carries `.claude/fleet.json` and the session check in `.claude/settings.json` |

**Outside a checkout of the project**, ask which repository the agents will
work in, by its remote URL, and clone it into `<scratch>` with the person's own
access: that clone is `<project>`. A project with no remote cannot reach the
target's agents, who clone it; creating one is the person's.

## 3. Ask what cannot be discovered [here]

**Only after step 2's `Read back before install` message has been sent**, the
message step 4's `<read-back file>` carries. All the remaining questions
come now, so the long machine work after them runs without stopping. Questions
2 to 7 fill the install manifest, so they are asked
only for a new one: a branch that already carries a `.claude/fleet.json` holds
the install's own answers, and its `skills` answers question 3. Questions 8
and 9 are asked either way. In this order:

2. **Chat transport** -> `transports.enabled`, `transports.default`. A transport
   is a skill directory holding a `transport.json`
   (`<clone>/.claude/skills/*/transport.json`); show every one, and say that one
   whose `status` is not `working` is "not yet" and cannot be enabled. `skills`
   keeps `chat-transport` and each enabled transport's skill. An agent's bot
   token is that agent's own credential and `/adding-an-agent` sets it up.
3. **Optional skills** -> `skills`. Each skill `<clone>/README.md` lists under
   "Integrations" needs its own credential and config, and `agent-revive` signs
   a stuck agent back in through a browser on the target, which needs the
   browser's system libraries there. Keep the ones the person wants and remove
   the rest from `skills`; adding one later is a manifest edit plus that
   skill's `installation/INSTRUCTION.md`. **Each group in
   `<clone>/templates/skill-groups.json` is ONE more item**, read from that
   file when asking, never from a list written here: its name and, in one
   line, what its `_comment` says it is, and that its skills fill conventions
   keys of question 7. Yes adds every name in the group's `skills` to the
   manifest's `skills`; no adds nothing to `skills`. The proposal, when the
   request does not answer it: yes when
   `<project>` is a code repository the agents will change, no otherwise; the
   person decides.
4. **Where credentials and the knowledge store live on the target** ->
   `secrets.default_dir` (SETUP section 1 step 5; the template's
   `~/.fleet-secrets` is the proposal) and the knowledge store's root
   (`/knowledge-base`'s `installation/INSTRUCTION.md` step 1; propose
   `<agents-root>/knowledge-base`, shared by every agent). Paths only.
   `secrets.legacy_env` stays `null` unless the person names a variable the
   target already exports for that directory.
5. **Working hours and time zone** -> `house_rules.blocker_chase` `tz`, `days`,
   `start` and `end`: when agents may re-ask a person about an open blocker.
   Propose this machine's zone (`timedatectl show -p Timezone --value`, or
   `readlink /etc/localtime`) with the fleet's default days and hours
   (`CONVENTIONS.md`).
6. **Reference cities** -> `house_rules.times.cities`: the clocks every time a
   person reads is shown in, in order. Propose the city of question 5's zone.
7. **Development conventions** -> the `conventions` keys in
   `CONVENTIONS.md`'s table. When question 3 took a group, propose the values
   its `conventions` in `<clone>/templates/skill-groups.json` gives, as they
   stand, for the keys it fills. For every other key, and for every key when no
   group was taken, look through `<project>` - a contributing guide, a `docs/`
   directory, the project's own `.claude/skills/` - and propose a value:
   `{"doc": "<repo-relative path>"}`, `{"skill": "<name>"}` (the project's own
   `.claude/skills/<name>/SKILL.md`, or a fleet skill `skills` lists), or
   `null`. The project's own skill or document may stand in for a group's value
   when the person prefers it. `null` is a full answer: a skill that reads a
   `null` key skips that step and says so.
8. **Claude accounts** -> how many Claude accounts the person has for the
   agents. With two or more, step 9 offers a `doctor` agent and the account
   pool: doctor moves an agent onto the account with the most headroom before a
   usage cap stops it, and revives a stuck one. With one, say that doctor can
   still revive a stuck agent but has no second account to move one to.
9. **The agents user** -> `<agents-user>`, when step 2 found an administrator:
   the name of the user the agents run as, `agents` proposed. Say what it is
   for in one line - the agents run with every prompt off, and this user has
   no sudo, so they cannot become root or switch off their own watchdog - and
   that step 4 creates it, with the person's key. A name that is already an
   account is used as it is, unless step 4's check finds it has sudo. On macOS
   the agents user is also the account that logs in automatically, so it has a
   password, which the person chooses and which comes in as a secret (step 4),
   and the Mac needs FileVault off (`targets/macos.md` sections 4 and 5). Its
   agents then run as LaunchDaemons and sign in only with a token or an API
   key; say so when asking.

**`upstream`** is for an install whose agents commit to the fleet repository
itself (SETUP section 4). Remove the block unless the request says they will;
when it does, its values are one more question.

**Units.** The fleet runs each agent's daemons as user units on the target, so
units are wanted unless the request says otherwise (a trial install, a machine
that only holds the checkout); step 5 then installs with `--units none` instead
of `--units refresh`.

## 4. The target's prerequisites and the agents user [admin]

`bootstrap-target.sh`, beside this file, owns this step, and its header gives
the exact commands: copy it to the target, run `--check`, which changes
nothing, and show the person what is missing; then copy `<read-back file>` to
the target too and, on the person's one OK, run
`--install --read-back <read-back file>` (its path on the target) under one
`sudo -S`, fed by the password's file -
here when it was pasted, on the target when it came through `/safe-box`, either
removed by its literal path afterwards - or by nothing on a machine whose
`sudo` asks for none. Without step 2's message in that file `--install`
refuses, naming the message. Always pass `--with-node`, because `fleet install` runs
`npm ci` in every Node sub-package of the fleet; add
`--with-browser` only when question 3 kept `agent-revive`; with an
administrator, add `--agents-user <agents-user>`, and `--agents-root
<agents-root>` when the person named a root other than `~/agents`. That makes
the agents user with no sudo, its agents root, lingering and Claude Code its
own, gives it the administrator's `authorized_keys`, so the person's key
reaches `<host>` too, makes `/opt/agent-fleet`, the administrator's, for the
fleet checkout (`--checkout <dir>` names another, never inside the agents
root), and adds the administrator to the agents user's group, so it reads the
agents root (mode 750) at its next login. `--install` ends by checking again and exits by that
check: step 5 starts only on its 0, and on `ssh -o BatchMode=yes <host> true`
exiting 0 from here.

**On macOS** the agents user is a standard account and the automatic-login
account, in place of lingering, and both need its password (question 9). It
comes in by either way above into a file here and goes to the target as
`ssh <admin-host> 'umask 077 && cat > /tmp/agents-password' < <that file>`;
add `--agents-password-file /tmp/agents-password` to `--install`, and remove
both copies by their literal paths once it has exited. Without the file
`--install` refuses (exit 2, nothing changed), and with FileVault on it reports
UNSUPPORTED (exit 3). It also gives the account its own group for the agents
root, Remote Login access and a `~/.bash_profile` PATH holding `~/.local/bin`
and Homebrew, where `claude` and the fleet's python3 are; there is no browser
check. Then the Mac restarts once, so the agents user is the one logged in:
the person restarts it at the Mac, or, on their OK, `ssh <admin-host> 'sudo -S
-p "" shutdown -r now' < <password file>` - a second root step, asked for on its
own. `/adding-an-agent` step 1 checks that the agents user's session is
there.

## 5. The fleet on the target [target]

Skip each part step 2 found done.

1. **Clone, and pin the newest release** - the newest tag on the default
   branch, the only tags `fleet upgrade` takes. With an administrator the
   clone is the administrator's [admin]:

   ```bash
   git clone <repository URL> <fleet>
   git -C <fleet> checkout --detach "$(git -C <fleet> describe --tags --abbrev=0 --match 'v[0-9]*' origin/HEAD)"
   ```

   `<repository URL>` is the one the request names; `<clone>` here is on the
   same tag (`git -C <clone> checkout --detach <tag>` when it is not). A
   checkout that is already there is never cloned again; moving it to a newer
   tag is the Upgrade section.
2. **Install**: `python3 <fleet>/bin/fleet install --agents-root <agents-root>
   --units refresh`, or `--units none` (step 3). With an administrator it is
   two parts, each refused for the wrong user: first `... --part checkout`
   [admin] (hooks, Node sub-packages, read-only mode), then `... --part agents
   --units refresh` [target]. Then, on a contributing host - the manifest keeps
   `upstream` (step 3) - record the identity `fleet upgrade` trusts for outside
   work, the project manifest's `upstream.identity.email` (read it here, in
   `<clone>`), as the checkout's owner: `python3 <fleet>/bin/fleet identities
   --add <email>` ([admin] with an administrator, else [target]). Upgrade
   trusts that file only, never a manifest an agent can edit. On any other host
   record nothing: an identity in that file makes the host a contributing one,
   and a host that is not skips the outside-work check and trusts the release
   tag (`CONVENTIONS.md`, "Contributing to the fleet"). SETUP section 3 says what it
   writes, the claims directory among it; `refresh` renders the refresh timer
   and enables it. The daemons' own unit templates need an agent's checkout of
   the project to render, so `/adding-an-agent` runs `--units all` with the
   first agent. A second run prints `nothing changed`.
3. **The organization secrets directory**, at question 4's path: SETUP section
   1 step 5.
4. **The knowledge store**, at question 4's root: SETUP section 6. It is its own
   repository on the target, outside the project.

## 6. The project change

It is made on the target, where the fleet and the machine's name are, in a
working clone of the project; shown here; and committed and pushed here, from
`<project>`, with the person's own access - nothing on the target can push
before an agent exists. The target's agents then clone it from the remote.

1. **The target reads the project's repository** [target]: `git ls-remote
   <remote> HEAD` exits 0. When it does not and the remote is on GitHub with
   `gh` signed in here, give the target user an SSH key (`ssh-keygen -t ed25519
   -N "" -f ~/.ssh/id_ed25519` when it has none) and, after the person's OK, add
   its public half as a read-only deploy key from here (`gh repo deploy-key
   add`). The target then uses the remote's SSH form
   (`git@github.com:<owner>/<repo>.git`), accepting GitHub's host key on first
   use (`GIT_SSH_COMMAND='ssh -o StrictHostKeyChecking=accept-new'`), and that
   form is the one handed on. Otherwise granting that access is the person's
   (SETUP, "What only you do"). Each agent's own access is
   `/adding-an-agent`'s.
2. **The working clone** [target]: `git clone --branch <branch> <remote>
   <work>`, `<branch>` the one `<project>` is on, `<work>` a new temporary
   directory.
3. **Adopt** [target]: `fleet adopt <work>`. It writes `.claude/fleet.json` from
   the template when there is none, and merges into `.claude/settings.json` the
   session check that tells every session started in the project when the fleet
   is missing, older than `fleet.min_tag`, or not linked (`CONVENTIONS.md`,
   "Adopted projects").
4. **Files Claude writes in `<work>`** go through `<scratch>`: `scp` the file
   here, change it with the file-edit tool, `scp` it back; a new file is written
   in `<scratch>` and copied over.
   - **The attribution block**: `.claude/settings.json` carries
     `"attribution": {"commit": "", "pr": ""}` at its top level, so Claude Code
     adds no attribution line to the project's commits and pull requests. An
     `attribution` object already there keeps its other keys and gets these two
     set to `""`, and every other key of the file stays as it is; `python3 -m
     json.tool` on it, on the target, proves it still parses.
   - **The manifest**: in `.claude/fleet.json`, every placeholder and every
     example value is replaced with step 3's answers. `fleet.repo` is the URL
     the fleet was cloned from; `fleet.min_tag` is the tag step 5 checked out,
     the release this install was set up against. The `_comment` keys are
     documentation: keep or delete them. `fleet settings`, run in `<work>` on
     the target, exits 0; a refusal names its key.
5. **Each skill's install context** [target]: SETUP section 5, for each skill
   in `skills`, its install-wide steps only, run in `<work>` (`fleet where
   <skill>` there names the directory). Values come from the host settings, the
   manifest and step 3; the `agent` skill's `<project-dir>` is the project's
   directory name. `<clone>/tests/fixtures/install/` shows each file's shape
   with synthetic values; never copy a value from it. A value that belongs to
   one agent - its bot, its token, its key, its home - waits for
   `/adding-an-agent`. A value only the person can give that is not an agent's
   is one more question, asked as in step 3. A "Record the install" step
   records the machine it runs on, which is why this step runs on the target.
6. **Show the diff** [here]: `ssh <host> 'git -C <work> add -A && git -C
   <work> status --short && git -C <work> diff --cached'`, printed WHOLE in the
   session before step 7's question - never a file list, a summary or its
   opening lines in its place, however long it is: the OK is an OK to what the
   person saw. When it is too long for one message, it goes over several, or
   is written to `<kept>/project-change.diff` and the question names that path
   and says the person must open the file before answering. Text the session
   writes in its place (condensed, abridged or reformatted) is a summary: it is
   called one, never the whole change, and it names the file holding the exact
   diff.
7. **Commit only on the person's explicit OK to that diff** [here]. An OK in the
   request counts when it says this commit may be made without asking; the diff
   is shown anyway. Carry the change here as one patch and apply it to
   `<project>`:

   ```bash
   ssh <host> 'git -C <work> diff --cached --binary' > <scratch>/project-change.patch
   git -C <project> apply --index <scratch>/project-change.patch
   ```

   A patch that does not apply means `<project>` is not at its remote branch's
   commit: say so, and ask whether to pull first.

   Commit the way the project commits: by the conventions `workspace` and
   `branch_naming` when question 7 set them, and by the project's own
   instructions to Claude Code; when neither says how, ask - never invent a
   branch or a message policy. Commit only the patch's paths - the ones `git -C
   <work> diff --cached --name-only` lists on the target - so nothing else the
   person has staged rides along, with a message that credits no tool (no
   `Co-Authored-By`, no `Generated with`): the attribution block this patch adds
   governs the sessions that load it, and this commit is made before any does.
   Write the message with the file-edit tool into
   `<scratch>/commit-message.txt`, then:

   ```bash
   bash <clone>/tools/commit-hygiene/ai-attribution.sh strip <scratch>/commit-message.txt
   git -C <project> commit -F <scratch>/commit-message.txt -- <paths>
   (cd <project> && bash <clone>/tools/commit-hygiene/ai-attribution.sh check-range HEAD^..HEAD)   # exit 0, else no push
   ```

   `strip` deletes every line the fleet's own commit hook would, and
   `check-range` reads the commit as it was made: exit 1 names the line. Never
   push a commit it does not pass. This one is still local, so it may be
   repaired: strip the message file again, `git -C <project> commit --amend -F
   <scratch>/commit-message.txt`, and check again.
   Push on the same OK: the target's agents clone the project from its remote,
   so the commit has to reach the branch they track before an agent is added.
8. **Clean up**: `rm -rf` `<work>` on the target and the patch here, each by its
   literal path.

## 7. Agent homes that already exist [target]

Only when step 2 found agent homes. `fleet link <agent-name>` for each one the
person names; a Claude Code config directory that is no agent's home is linked
with `fleet link --config-dir <dir> --install <install root>` only when the
person names that directory. Then `fleet check-all <agent-name>` and `fleet
status <agent-name>` for each, read by step 8's rule.

## 8. Check [target]

`fleet status` exits 0, or every `DRIFT` row is one of:

- a credential the person supplies - named by its path, never its value;
- a value, a unit or a record that waits for `/adding-an-agent`;
- a step SETUP lists under "What only you do", with the exact prompt for it.

Fix anything else and run it again. `fleet check-all <agent-name>` comes with
an agent: `/adding-an-agent` runs it for each agent it adds.

Then the privilege check, as the agents user - `--no-admin` when step 2 found
no administrator, and an `--agent <agent-name>` for each agent step 7 linked:

```bash
ssh <host> 'python3 <fleet>/.claude/skills/install-agent-fleet/verify-privileges.py [--no-admin] [--agent <agent-name>]...'
```

It is read only and prints facts, never a secret; its header lists each check.
Exit 0 is PROTECTED. Exit 1 is a FAIL line - the agents user can use sudo, or
change or stop what supervises it, or anything in the fleet checkout - and the
install does not go on until it is fixed. Exit 3 is NO VERDICT and names what it
could not measure. Exit 4 is the no-administrator form's UNPROTECTED, which the
closing summary states. On macOS it reads launchd instead of systemd: each
agent's session and watchdog must be loaded in the system domain from a plist
in `/Library/LaunchDaemons` the agents user cannot change, with `UserName` the
agents user, and the watchdog's config, program and interpreter out of the
agents user's reach; a LaunchAgent is the no-administrator form. On both
systems the tmux the watchdog runs is checked too, as its PATH reaches it,
with every directory searched before it: a tmux in a directory the agents user
can change, such as its own `~/.local/bin`, leaves the watchdog unprotected and
FAILs. A tmux the administrator installed (the distribution's `/usr/bin/tmux`,
Homebrew's installed as the administrator) passes.

## 9. Hand off, then close [here]

1. **Offer `/adding-an-agent`.** It owns every step of an agent - the
   interview, the charter, the home, the sign-in, the chat app, the units, the
   health check - and this skill restates none of them. Hand it `<host>` as its
   `<target>`, `<admin-host>` as its `<admin-target>` and the unit form
   (`system` with an administrator, `user` without one), and the project's
   remote. When the person accepts, follow it, then come back here.
2. **With two or more accounts (question 8), offer doctor**: one more agent
   through `/adding-an-agent`, from the health-doctor persona template, and
   each account registered in the account pool as `/agent-revive`'s "Adding an
   account to the pool - the one way" says, its credential on standard input
   [target]. Each account signs in by `/adding-an-agent`'s sign-in, option A
   unless the person picks another, and its secrets come in by either way
   above.
3. **The closing summary**, compact: the answers taken from the request,
   listed as such; what was done (the target and how it is
   reached - `<admin-host>` for the administrator and `<host>` for the agents
   user - its fleet checkout and tag, the units choice, the project commit, the
   knowledge store, each agent added, and the privilege check's verdict line
   with any line of it that is not ok), every line that `ssh <host> 'cd
   <agents-root>/<an agent>/<project-dir> && python3
   <fleet>/.claude/skills/agent-health/pool_pick.py --shares'` prints, repeated
   as it is - one "N agents share account X" per shared account, so a share is
   never silent; none when nothing is shared or there is no pool - and what is
   left, each item with who
   does it and the exact command or file. Say that a session opened in the
   project on a machine without the fleet, or under a config directory the
   fleet's skills are not linked for, shows the session check's notice, and
   that SETUP's "Your computer shows the fleet's notice" links them here. Its
   last line is how to upgrade later: say "Upgrade agent-fleet following
   ~/agent-fleet/SETUP.md" to Claude Code here, or "upgrade agent-fleet" to an
   agent whose install keeps this skill in `skills`.

   A file the summary hands the person - the Slack app's `manifest.json`, a
   diff too long to print - is in `<kept>`, never in `<scratch>`, which does
   not outlive this session, and the summary names it by its full path.

---

## Upgrade

On "upgrade agent-fleet", this section is the whole procedure. Steps 1 to 3
run as the checkout's owner - [admin] with an administrator, else [target] -
and step 5's re-renders [target] and root step [admin]; `<host>` is the agents
user's destination the person names, or the one the last install's summary
named; the questions are here.

1. `git -C <fleet> fetch --tags origin`. The newest release is `git -C <fleet>
   describe --tags --abbrev=0 --match 'v[0-9]*' origin/HEAD`; the current one is
   the tag in `fleet status`'s first row. When they are the same, say so and
   stop.
2. Show the person what changes: `git -C <fleet> log --oneline
   <current>..<newest>`. A new MAJOR version is tried on one agent first, as
   SETUP section 9 describes; which agent is the person's question.
3. `fleet upgrade <newest>`. It refuses, changing nothing (exit 2), a dirty or
   writable checkout, a tag CI has not passed, a leak finding, and, on a
   contributing host, commits made by anyone other than a trusted identity
   (elsewhere it skips that check and prints why); report its line as it is. `--reviewed-outside` and `--ack-leak` are passed only on the repository
   owner's explicit go for that tag, never on this skill's judgement. It reads
   the tag's CI result through `gh`, signed in on the target: when it is not,
   the person writes a GitHub token into the file Claude names here, and Claude
   copies it over, runs `gh auth login --with-token < <file>` there, and
   removes the copy by its literal path.
4. Tell the person when each part takes effect, as SETUP section 9 states it.
5. **The one root step, and only when the range touched what root installed.**
   `fleet upgrade` itself needs no root: it runs as the checkout's owner, and
   refuses anyone else, naming the owner. It reads the installs' manifests
   under the agents root, which the administrator reads through the agents
   user's group (step 4), and on a contributing host trusts for outside work
   only the identities `fleet identities` lists: a manifest identity missing
   there is ignored and named, and a new maintainer is added with `fleet identities --add <email>`
   on the repository owner's word. The administrator installed rendered copies of three files, so
   when `git -C <fleet> diff --stat <current>..<newest> --
   templates/claude-agent.service.example
   .claude/skills/stall-watchdog/installation/agent-stall-watchdog.service.example
   .claude/skills/stall-watchdog/config.example.json` (on macOS
   `templates/claude-agent.plist.example` and the watchdog's
   `installation/agent-stall-watchdog.plist.example` and
   `installation/render-plist.py` in place of the two unit examples) lists any
   of them,
   re-render each agent's affected unit or watchdog with `/adding-an-agent`
   section 5 step 6 or 7 [target] and run the root command it prints [admin],
   by that skill's *Root on the target*: installing a unit restarts nothing, and
   the new shape applies at the agent's next restart. A step 7 re-render
   rewrites the watchdog's config from the example, so a value tuned in it is
   set again in the staged file first. With no administrator (user units) the
   same steps run without root. Then `verify-privileges.py` as in step 8.
6. `fleet status`, and `fleet settings` in an agent's checkout of the project:
   a newer fleet that refuses a manifest key names it, and a charter pointer
   (`/<skill> step N`) that a renumbered skill no longer resolves is a `DRIFT`
   row naming the charter and its line, which the charter's owner fixes.
   `<clone>` here moves to the same tag [here].

**Taking a skill group later** - the install declined it, or it is new in this
release - is a change to the project, made, shown and committed as step 6 of
the install makes one: in `.claude/fleet.json`, add every name in the group's
`skills` (`<fleet>/templates/skill-groups.json`) to `skills`, set each key its
`conventions` names to that value unless the person keeps the install's own,
and raise `fleet.min_tag` to a release that carries the group; then, as step 6
item 5 does, run each group skill's install-wide steps in `<work>`, so its
install context is part of the change. `fleet settings` in `<work>` exits 0
before the diff is shown. Once the commit is on the branch the agents track,
`fleet link <agent-name>` for each agent [target], then each group skill's
per-agent and per-host steps (its `installation/INSTRUCTION.md` says which),
and `fleet status`.
