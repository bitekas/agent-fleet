---
name: adding-an-agent
version: 3
description: >
  Add a new long-running agent to a fleet and finish it end to end, from the
  person's own Claude Code session, acting on the target machine over SSH (or
  on this machine itself): interview the person for its name, role,
  personality and who it answers to, one question at a time; write its charter
  from a persona template and prove no placeholder is left; give it a home
  directory, an empty Claude Code config directory and a sign-in (a long-lived
  token by default, a full login, or an API key); create its Slack app from a
  generated manifest at the scope tier the person picks; take every secret in
  without printing it; install and start its daemons as user units of the
  agents user, and its own session and its stall watchdog as system units the
  install's administrator installs (user units when the install has no
  administrator); prove the agents user cannot stop or edit them; get its
  health check clean; and confirm a test message reached it. Load before adding
  an agent, before generating or changing an agent's Slack app manifest, and
  when asked what an agent's Slack bot can or cannot be allowed to do.
requires_install: false
---

# Adding an agent

The procedure for adding one long-running agent to a fleet. It points at the
mechanisms that already exist - the `/agent` home layout, `/scheduled-tasks`,
`/slack-communication`, `/stall-watchdog`, `/agent-revive`, `/safe-box`, the
`fleet` command and the templates in the fleet tree - and restates none of
them: each step names where its mechanism lives, and that file is the authority.

**This skill needs no config.** Every value comes from the interview, from the
install's settings (`fleet settings`), or from the target's host settings file
`fleet install` wrote (`~/.config/agent-fleet/host.json`): `agents_root` is the
directory every agent home sits in, and `fleet_checkout` is the target's fleet
tree, written `<fleet>` below.

**Two machines, and every step says which.** This session runs on the person's
own machine, and the agent runs on the target. A step marked **[here]** runs in
this session. A step marked **[target]** runs as `ssh <target> '<command>'`; a
fenced block marked [target] is written to a file here with its first line
filled, and runs as `ssh <target> bash -s < <file>`. When the target is this
machine, a [target] command runs as it is, without `ssh <target>`, and a block as
`bash <file>`. An SSH command reads no login profile: `fleet` there is
`~/.local/bin/fleet`, and `claude` runs through `bash -lc`, as the agent's unit
starts it. `<target>` (`<host>` there), the agents root and the project's
remote come from `/install-agent-fleet` when it hands over to this skill, and
are asked otherwise.

**A step marked [systemd] is the Linux form; its [launchd] form, for a macOS
target, follows it.** On a macOS target an SSH command's PATH lacks Homebrew,
where tmux and the fleet's python3 are (Apple's /usr/bin/python3 is older than
the fleet's floor), so every [target] command there runs with it in front:
`ssh <target> 'PATH=/opt/homebrew/bin:$PATH <command>'`, and a block as `ssh
<target> 'PATH=/opt/homebrew/bin:$PATH bash -s' < <file>`.

**The two users** (`SETUP.md`, "The two users"). The agents run as a dedicated
**agents user** without sudo, and `<target>` is that user's SSH destination;
every [target] command runs as it. The install's **administrator**, the login
with sudo, installs what the agents user must not be able to stop, disable or
edit: the agent's session unit and its stall watchdog, as system units with
`User=` the agents user. Its SSH destination is `<admin-target>`, and it runs
only the printed root commands. That is the `system` form of section 5 steps 6
and 7. An install whose only user has no sudo at all has no administrator:
the agents run as that user, their units are user units it controls (the
`user` form), the watchdog needs root that nobody on the machine has, and
step 10 reports the agent UNPROTECTED. `/install-agent-fleet` hands over
`<target>`, `<admin-target>` (empty for the user form) and the form; asked
otherwise. On a macOS target the system form's session and watchdog are
LaunchDaemons with `UserName` the agents user, installed root:wheel 644 into
/Library/LaunchDaemons by one root command each, and the user form's are
LaunchAgents in the agents user's own GUI session, which that user controls
(step 10 reports them UNPROTECTED). **A macOS agent in the system form signs in
only with a token or an API key** (question 6).

**Root on the target** is ONE `sudo` command at a time, run as `ssh
<admin-target> '<command>'`, for three steps only: the agent's session unit in
the system form (section 5 step 6), the stall watchdog's install when the
person wants one (question 7, section 5 step 7) - each step prints its command
- and lingering on a host whose policy refuses a user's own (section 5 step 1).
Where `ssh <admin-target> 'sudo -n true'` exits 0 (a cloud image's user),
Claude runs the command as it is. Otherwise the `sudo` password comes in by
*Handing over a secret* - pasted, into a file here; or by `/safe-box`, into the
fleet secrets directory on the target - and is the standard input of that one
command with `sudo -S -p ""` in place of `sudo`; its file is removed by its
literal path right after. When the person prefers, they run the printed
command themselves. Claude never writes under /etc any other way.

**The person's part, and nothing else:**

1. answering the interview, one question at a time (section 1);
2. the agent's Claude Code sign-in: running `claude setup-token` here and
   handing over the token (the default), approving a sign-in in their browser
   and sending back its code once, or handing over an API key (section 3 step 4);
3. creating the Slack app from the generated manifest, installing it, and
   handing over its bot token (section 4.3 steps 1 to 3);
4. inviting the bot to a channel and posting the test message there (section 6).

Placeholders used below: `<target>` (the SSH destination of the agents user on
the target), `<admin-target>` (the administrator's, *The two users* above),
`<agent-name>` (the lowercase name), `<Agent-Name>` (its display
form), `<home>` (`<agents-root>/<agent-name>`), `<project-dir>` (the install
checkout's directory name inside every agent home), `<watch-job>` (the working
chat transport's `watch.job`, `slack-watch` for Slack), `<uid>` (`id -u` on the
target) and `<scratch>` (a directory here, mode 700, for files on their way to
the target).

**`systemctl --user` needs `XDG_RUNTIME_DIR`**, and a shell without a login
session has none (`<fleet>/systemd/README.md`). When it is unset, put
`export XDG_RUNTIME_DIR=/run/user/$(id -u);` in front of every command below
that calls it, in the same shell call: the shell does not keep it between calls.

## Handing over a secret

The sign-in token or API key and the Slack bot token each go to one file on the
target, mode 600, in the agent's personal-secrets directory (`/agent` section 3),
holding the bare value on one line. Claude names the secret and its file; the
person picks one of two ways:

1. **Paste it into this session.** Claude writes the value with the Write tool
   into `<scratch>/secrets/`, created first with `install -d -m 700`, sends it
   over SSH's standard input, and deletes the local copy:

   ```bash
   ssh <target> 'umask 077 && cat > <target file>' < <scratch>/secrets/<name>
   rm -f <scratch>/secrets/<name>
   ```

   The value goes into no command line and no reply. A shell command a tool
   call runs is in that shell's process arguments, readable by the same user
   while it runs: the Bash tool runs `bash -c "... eval '<command>'"` (measured
   on Claude Code 2.1.290). So the value travels only inside files and
   standard input. It stays in this session's transcript, where the paste put
   it.
2. **`/safe-box`**, where the value never enters this session. Start it on the
   target as a background command of this session, one `NAME=PATH` per secret,
   and read its output until the `SAFE-BOX READY` line:

   ```bash
   ssh <target> 'cd <home>/<project-dir> && timeout 660 python3 <fleet>/.claude/skills/safe-box/safe_box.py --timeout 600 --ssh-host <target> <name>=<target file>'   # linux-only: a macOS target has no timeout(1); there drop "timeout 660"
   ```

   Show the person its `tunnel:` command, its `open:` URL and its code; what
   they do with them, and what each exit means, is `/safe-box` sections 4 to 6
   (exit 0: every file written, mode 600). Pass `--replace` when a file is being
   replaced. Its destinations must lie in an existing agent home's
   `secrets/personal/`, which section 3 step 1 creates first.

`/safe-box` section 1 says what each way does with the value. **When the
sign-in credential and the Slack token are both still to come, take them in one
hand-over**: the person creates and installs the Slack app (section 4.3 steps 1
and 2) and runs `claude setup-token` first, and one safe-box session declares
both names.

Either way, Claude then checks the file without opening it, and sets its mode
when a file that was already there kept another:

```bash
ssh <target> 'ls -l <target file>'    # -rw------- and a size above 0
```

**Claude never prints a secret or quotes it in a reply.** The
commands that use one on the target read it on standard input, by `$(cat
<file>)` into a shell builtin (`printf`), or as a unit's `EnvironmentFile=`, so
it is in no process's arguments there either.

---

## 1. Interview, one question at a time [here]

Load `/talking-to-humans` first: questions go out one at a time - never more per
message than `fleet settings house_rules.questions_per_message`, the key that
rule cites - each numbered against the running total (`Question 1 of 7`) and
carrying a plain-words brief. Ask in this order, because each answer shapes the
next:

1. **Name.** The lowercase name keys everything - the home directory, the unit,
   the charter file, the bot - so it must match `^[a-z][a-z0-9-]{1,30}$`, and
   neither `<agents-root>/<agent-name>` on the target nor the install's
   `.claude/agents/<agent-name>.md` may exist yet. Ask also how people should
   read it (`Ada` for `ada`), the display name: letters, digits, spaces and
   hyphens only, because the agent unit types it inside its boot message, where
   an apostrophe or a dollar sign changes the command (the unit template's
   comment says why).
2. **Role.** What it does, in one line. Offer the persona templates in the
   fleet tree's `templates/personas/` as starting points - lead engineer, health
   doctor, root orchestrator - each with one line on what it is built for.
3. **Personality and voice.** How it writes and talks to people, in a short
   paragraph.
4. **Who it answers to.** Who may direct it, whose approval its work needs, and
   the chat address where it reaches them.
5. **The Slack scope tier** (section 4), when the install's transports include
   Slack (`fleet settings transports.enabled`).
6. **How its Claude Code signs in** (section 3 step 4), default A:
   - **A, a long-lived token** - the person runs `claude setup-token` here
     (one browser approval) and hands the token over. Model requests only: no
     Remote Control and no claude.ai connectors.
   - **B, a full login** - for Remote Control: the person approves a sign-in in
     their browser here and sends back its code once.
   - **C, an API key** - billed per token, from the Claude Console.

   **On a macOS target with an administrator (the system form) only A or C.**
   The session is a LaunchDaemon, which has no window server and no login
   Keychain, so a full login cannot be kept there: section 5 step 6's [launchd]
   block refuses B in that form, and `/agent-revive` and the health agent then
   treat the agent as token-only - an account switch restarts it on another
   token, never through a browser. Say this when asking, and offer A and C only.
7. **The stall watchdog.** A system service that watches the agent's session
   from outside and, when a confirmation prompt has sat unanswered with nobody
   at the terminal, answers it NO, so the session does not hang for ever
   (`/stall-watchdog`). Root installs it: Claude runs the one command as the
   administrator, or prints it for the person to run when they prefer; an
   install with no administrator has nobody who can. Without it a session
   stuck on a prompt stays stuck until someone looks.

**Every answer is the person's.** The tier in particular decides what the agent
is ALLOWED to do in the workspace, which a skill never decides
(`/claude-skill` section 1, rule 2): present the three tiers with what each
permits and what each costs, and recommend none. The watchdog question is
answered the same way. Question 6 carries a default because it is a technical
choice: A, unless the person needs Remote Control or bills by API key.

## 2. The charter [here]

1. Copy the template closest to the role into the person's checkout of the
   install repository (the git top level holding `.claude/fleet.json`),
   writable - the fleet tree is read-only and a `cp` keeps that mode:

   ```bash
   install -D -m 644 "${CLAUDE_SKILL_DIR}/../../../templates/personas/<template>.md" .claude/agents/<agent-name>.md
   ```
2. Replace every placeholder. The interview fills exactly these five:

   | Placeholder | Filled from |
   |---|---|
   | `<agent-name>` | answer 1: the lowercase id, also the home directory and the unit instance name |
   | `<Agent-Name>` | answer 1: the name as people read it |
   | `<agent-role>` | answer 2, one line |
   | `<agent-voice>` | answer 3: personality and tone, a short paragraph |
   | `<answers-to>` | answer 4: who may direct it, whose approval its work needs, and where to reach them |

   Every other placeholder in a template is filled by hand from the install's own
   values (`fleet settings`, the install's charters); its comment in the template
   says what it needs, and where the value is not already known it is one more
   question, asked the same way. Delete the template's `TEMPLATE - ...` header
   line: it names placeholders itself, so the check below finds it when it is
   left in.
3. **Conventions stay cited by slot key** - `definition_of_done`,
   `branch_naming`, `workspace`, `release`, `environments`,
   `feature_checklist` - never by an install's skill or document. The agent
   resolves a key at run time with `fleet settings conventions.<key>`, so a
   change of process is one manifest edit, not an edit to every charter.
4. **Prove no placeholder is left, with a check that is first seen to find
   one:**

   ```bash
   command grep -nE '<[A-Za-z][A-Za-z0-9-]*>' "${CLAUDE_SKILL_DIR}/../../../templates/personas/<template>.md" | head -3   # MUST print lines
   command grep -nE '<[A-Za-z][A-Za-z0-9-]*>' .claude/agents/<agent-name>.md                                               # must print NOTHING
   ```

   The first line is the positive control: the template is a file known to
   contain placeholders, so a pattern that finds none there is blind, and its
   silence on the charter would mean nothing. **If the first line prints nothing,
   issue no verdict**: read the template's header for the placeholder form it
   uses and fix the pattern before trusting the second line. The pattern is
   case-blind on purpose - `<Agent-Name>` is a placeholder too - and an HTML tag
   it also matches costs a look, never a missed placeholder. `command grep`
   bypasses a shell function of the same name that some agent shells define.
5. Land the charter through the install's `workspace` and `branch_naming`
   conventions, and push it, before the agent's first start. This commit, and
   every later one this skill makes in the project, credits no tool: make it
   and check it before the push as `/install-agent-fleet` step 6.7 makes the
   adoption commit (the message from a file, `ai-attribution.sh strip`,
   `commit -F`, `check-range`), because the session adding the agent may have
   started before the project's attribution block existed. The agent unit
   starts the session with its charter (`--agent <agent-name>` in the unit
   template), read from the agent's own checkout on the target, which clones
   the project's remote: a charter that is not on the branch that checkout
   tracks is an agent that boots without one, and nothing reports it.

## 3. Home directory and sign-in [target]

1. **The home layout is `/agent` section 3.** Create each directory in its table
   under `<home>`, at the path the install's `agent` context maps it to (`fleet
   where agent CONTEXT.md`). The personal-secrets directory is mode 700. Install
   the blockers file by `/agent`'s `installation/INSTRUCTION.md` step 1, which
   copies its template writable: a standing agent with its own charter keeps
   that file (`/agent` section 6), and its timer writes to it.
2. **The project checkout.** Clone the install repository's remote into
   `<home>/<project-dir>`, using the SAME directory name every other agent home
   uses: the daemon unit templates are rendered with one project directory for
   every home, so a different name leaves this agent's daemons with no working
   directory. Clone after the charter has landed (section 2 step 5), so the
   checkout holds `.claude/agents/<agent-name>.md`.
3. **An empty config directory.** `install -d -m 700 <home>/.claude` - that path,
   because `fleet link` and the units both derive it from the home. **Never copy
   another agent's config directory: the copy shares its per-install identifiers
   and its rotating sign-in token, so both agents lose their remote registration
   and their sign-in.**
4. **The sign-in, before the unit exists.** Every agent has one credential file,
   `<home>/secrets/personal/claude-auth.env`, which its unit reads as
   `EnvironmentFile=` and its first run below sources; the unit records the
   answer to question 6 as `FLEET_AGENT_AUTH`. By that answer:

   - **A, `token` (the default).** The person runs `claude setup-token` in a
     terminal here: the browser approval of `/login`, after which the token
     prints once and is saved nowhere, valid for one year (vendor docs). They
     hand it over (*Handing over a secret*) as
     `<home>/secrets/personal/claude-credential`, with the name of the Claude
     account they approved it for, and the credential file is made from it
     below. Such a token makes model requests only: Remote Control, claude.ai
     connectors and Claude in Chrome need a full login (vendor docs; Claude
     Code 2.1.317's own messages say the same - measured). Its usage cannot be
     read off the /usage dialog, so the agent's settings carry the status-line
     command that records it (below, after the first run; `/agent-health` step
     4). **One account per agent session is the rule.** With at least as many
     accounts as agents, no account is shared. With fewer accounts than agents
     - one account for the whole fleet, say - several agents may run on one
     account, and it is explicit: the pool records every holder and reports
     "N agents share account X" (`/agent-health` and `/agent-revive` own that
     shared lease). A shared token is technically sound - the vendor docs have
     it set "wherever you want to authenticate", and Claude Code uses an
     environment token as given, never refreshing or replacing it (2.1.317:
     "keeping the user-supplied CLAUDE_CODE_OAUTH_TOKEN instead of adopting the
     stored credential" - measured), unlike the rotating sign-in a copied
     config directory shares - but the agents on one account share its usage
     limits, and revoking the token stops them all.
   - **B, `login`.** Not on a macOS target in the system form (question 6).
     The credential file is empty (the `auth-file` block below
     makes it so). The first run below meets the login-method menu: option 1, *Claude account
     with subscription*, by a bare Enter and never option 2, the metered API
     path (`/agent-revive`, "The one mistake"). Read the sign-in URL off the
     pane, joining its wrapped lines (`/agent-revive` step 4), and send it to
     the person, who opens it in their browser here, approves, and sends back
     the code once; Claude types it into the session with `send-keys -l --
     '<code>'` and then `Enter`. The sign-in stays in `<home>/.claude`.
   - **C, `api-key`.** The person hands over a Claude Console API key as
     `<home>/secrets/personal/claude-credential`, and the credential file is
     made from it below. Every request is billed to that Console account, and
     the agent is in no account pool.

   **The credential file** is what `/agent-health` and `/agent-revive` read to
   tell the account an agent runs as: header lines first, then the variable and
   the value on one line, mode 600 -

   ```
   # fleet-auth: token
   # fleet-account: <the Claude account>
   CLAUDE_CODE_OAUTH_TOKEN=<the token>
   ```

   **Whenever the install has an account pool** (`/agent-health`'s
   `pool_pick.py`), a token enters the pool once and reaches each agent by a
   lease, which writes the credential file with that header; whether a lease
   may share an account follows the rule above, and the pool enforces it.
   Register the account as `/agent-revive`'s "Adding an account to the pool -
   the one way" says, its token on standard input - from the pasted copy here,
   or from the safe-box file on the target, which is then removed:

   ```bash
   ssh <target> 'cd <home>/<project-dir> && python3 <fleet>/.claude/skills/agent-health/pool_pick.py --register <account> --token-stdin --home-agent <agent-name>' < <scratch>/secrets/<name>
   ssh <target> 'cd <home>/<project-dir> && python3 <fleet>/.claude/skills/agent-health/pool_pick.py --register <account> --token-stdin --home-agent <agent-name> < <home>/secrets/personal/claude-credential && rm -f <home>/secrets/personal/claude-credential'
   ```

   An account already in the pool is not registered again. Then take the
   lease for the agent, and with it its credential file. Fill the FIRST line
   and run the block on the target; `<account>` is the account the person
   named, or empty for the pool's own pick:

   ```bash take-lease
   a=<agent-name> home='<home>' fleet='<fleet>' proj=<project-dir> want='<account>'
   pp="$fleet/.claude/skills/agent-health/pool_pick.py"; cd "$home/$proj" || exit 1
   pick=$(python3 "$pp" --agent "$a" --auth token); echo "pick exit $?"
   set -- $(printf '%s' "$pick" | python3 -c 'import json, sys; d = json.load(sys.stdin); u = sys.argv[1] or d.get("pick") or "-"; held = {e["username"]: e.get("leased_by") for e in d.get("accounts", [])}; share = d.get("share") if u == d.get("pick") else bool(held.get(u)); print(u, "--share" if share else "")' "$want")
   if [ -z "${1:-}" ] || [ "$1" = - ]; then echo "NOT TAKEN: the pool names no account for $a; run pool_pick.py --agent $a --auth token and read its reason"; exit 1; fi
   python3 "$pp" --take "$1" --agent "$a" ${2:+"$2"} --install-token "$home/secrets/personal/claude-auth.env" --why install \
     || { echo "NOT TAKEN: --take refused $1 for $a; its reason is above"; exit 1; }
   python3 "$pp" --shares
   ```

   **A lease is shared only with `--share`, and never silently.** The pick
   (`--agent <agent-name> --auth token`, one JSON object) says `"share": true`
   when no free account qualifies and the pool has fewer accounts than agents,
   and an account the person named is shared when another agent holds it; the
   block then passes `--share`, without which `--take` refuses an account
   another agent holds (exit 1, its reason names `--share`), and which the pool
   refuses in turn while it has an account for every agent. The last line
   prints one "N agents share account X" line per shared account: Claude tells
   the person each one. `pool_pick.py`'s header documents every exit.

   **Without a pool, and for B and C**, this block writes the same format from
   the handed-over file, with the value in no command's arguments (`tr` reads it
   on standard input, `printf` is a shell builtin), and removes the bare copy;
   for B it writes the file empty. Fill the FIRST line and run it on the target:

   ```bash auth-file
   home='<home>' auth=<auth-mode> account='<account>'
   src="$home/secrets/personal/claude-credential"; dst="$home/secrets/personal/claude-auth.env"
   case "$auth" in token) var=CLAUDE_CODE_OAUTH_TOKEN ;; api-key) var=ANTHROPIC_API_KEY ;; *) var= ;; esac
   if [ "$auth" = login ]; then
     (umask 077 && : > "$dst")
   elif [ -z "$var" ] || [ ! -s "$src" ] || { [ "$auth" = token ] && [ -z "$account" ]; }; then
     echo "NOT WRITTEN: $auth needs $src and, for a token, the account it belongs to"
   else
     (umask 077 && { printf '# fleet-auth: %s\n' "$auth"; [ -n "$account" ] && printf '# fleet-account: %s\n' "$account"; printf '%s=' "$var"; tr -d '\n' < "$src"; echo; } > "$dst") && rm -f "$src"
   fi
   ls -l "$dst"
   ```

   `<account>` is the Claude account the token belongs to, and empty for B and
   C. The last line shows `-rw-------`, with a size above 0 for A and C.

   **The first run** meets, on its own terminal, every dialog the unit's start
   would otherwise meet and nobody would answer. Fill the FIRST line and run the
   block on the target:

   ```bash first-run
   a=<agent-name> home='<home>' proj=<project-dir> auth=<auth-mode>
   [ "$auth" = token ] && [ ! -e "$home/.claude/.claude.json" ] && printf '{"hasCompletedOnboarding": true}\n' > "$home/.claude/.claude.json"
   env -u TMUX tmux -L "add-$a" new-session -d -s signin -c "$home/$proj" \
     "env -i HOME=$HOME TERM=tmux-256color PATH=/usr/bin:/bin CLAUDE_CONFIG_DIR=$home/.claude /bin/bash -lc 'set -a; . $home/secrets/personal/claude-auth.env; set +a; claude --dangerously-skip-permissions --name $a --agent $a'"
   ```

   On a macOS target `bash -l` reads `~/.bash_profile`, never zsh's files:
   `/install-agent-fleet`'s bootstrap puts `~/.local/bin` (where Claude Code's
   installer puts `claude`) and Homebrew there; with no bootstrap, add the line
   `export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"` to it first.
   `<auth-mode>` is `token`, `login` or `api-key` for A, B or C. `env -i` and
   `bash -l` give the session what the unit gives it: none of the variables a
   Claude Code session exports to its tools (`CLAUDECODE`,
   `CLAUDE_CODE_CHILD_SESSION` and others, which make a new Claude Code process
   treat itself as that session's child), the credential file's variable, and
   `claude` found only on the login PATH. A `claude: command not found` here is
   the unit's first start failing the same way; fix the login profile before
   going on. **The `.claude.json` line is for A**: with only a token in its
   environment, a first run still stops at the login-method menu, whose every
   choice starts a different sign-in; with onboarding marked complete it goes
   straight to the folder-trust question (measured on Claude Code 2.1.317 with
   a stand-in token). An existing `.claude.json` is left as it is.

   Read the pane after each key, dropping any line that shows part of a key:

   ```bash
   ssh <target> 'env -u TMUX tmux -L add-<agent-name> capture-pane -p -t signin' | command grep -v 'sk-ant-'
   ssh <target> 'env -u TMUX tmux -L add-<agent-name> send-keys -t signin <key>'
   ```

   and answer each dialog: the theme (Enter), with C the *Detected a custom API
   key* question (*Yes*, above the preselected *No*; that dialog prints part of
   the key, which is why the capture drops it), with B the sign-in above, the
   security notes (Enter), the folder-trust question (*Yes, I trust this
   folder*) and the bypass-permissions warning (*Yes, I accept*). **The last two
   preselect *No, exit***: an Enter there ends the run. At the ready prompt (the status bar reads `bypass
   permissions on`), type /exit, then
   `env -u TMUX tmux -L add-<agent-name> kill-server`.

   **For A, the status line that records the agent's usage** goes into its
   Claude settings, after the first run, which writes that file. Fill the FIRST
   line and run it on the target:

   ```bash status-line
   home='<home>' fleet='<fleet>'
   cmd="$fleet/.claude/skills/agent-health/usage_statusline.py"
   if [ -x "$cmd" ]; then
     python3 -c 'import json, os, sys; p, c = sys.argv[1:]; d = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}; d["statusLine"] = {"type": "command", "command": c}; t = p + ".fleet-tmp"; open(t, "w", encoding="utf-8").write(json.dumps(d, indent=2) + "\n"); os.replace(t, p)' "$home/.claude/settings.json" "$cmd" && echo "statusLine set in $home/.claude/settings.json"
   else
     echo "NOT SET: $cmd is not an executable file"
   fi
   ```

   Every other key in the file is kept, and a status line already there is
   replaced (`/agent-health` step 4 says why); a file that is not valid JSON
   stops the block with nothing written.

## 4. The Slack app

Only when the install's transports include Slack. The manifest is Slack's
app-manifest JSON, generated and validated by `slack_manifest.py` from the scope
table `slack-scopes.json` beside this file: one row per scope with the token
types Slack grants it, the lowest tier that requests it, why, and the Slack
reference page that says so.

### 4.1 Choosing the tier [here]

Show the person the output of

```bash
python3 "${CLAUDE_SKILL_DIR}/slack_manifest.py" tiers
```

and ask question 5. The tiers are cumulative:

- **minimal** - read and post in the channels it is invited to.
- **standard** - minimal, plus direct messages (people can DM it from its App
  Home Messages tab), reactions, and files.
- **full** - standard, plus managing the workspace with a bot token: create,
  rename and archive channels, invite people to channels, join channels itself,
  user groups, pins, bookmarks, user lookups, Slack Connect invitations.

The same output lists what NO tier can grant, because Slack gives it only to a
USER token: inviting people into the workspace, deactivating members, roles,
deleting or converting channels, workspace settings, editing another member's
profile, workspace-wide search. The `admin.*` abilities also need an Enterprise
plan and an org-wide install by an org admin. A bot token cannot hold any of
them, so the validator refuses one in the bot scopes with that reason.

### 4.2 Generating it [here]

```bash
python3 "${CLAUDE_SKILL_DIR}/slack_manifest.py" generate --tier <tier> \
  --name "<Agent-Name>" --description "<agent-role>" > <tmp>/manifest.json
python3 "${CLAUDE_SKILL_DIR}/slack_manifest.py" generate --tier <tier> \
  --name "<Agent-Name>" --description "<agent-role>" --url
```

The second prints Slack's prefilled create-from-manifest link. `generate`
validates before it prints: an app name over Slack's 35 characters, a
description over 140 or a bot display name over 80 is refused with the rule and
its Slack page, and nothing reaches stdout. A manifest edited by hand is checked
with `validate <file>` the same way.

**Why the manifest is shaped this way** - each property is a `fleet.*` rule in
the validator, so a hand edit that breaks one is refused rather than shipped:

- **No event subscriptions, Socket Mode off.** The agent's watcher POLLS the Web
  API (`/slack-communication`) and reads direct messages with
  `conversations.history`. Slack's App Home page tells an app to subscribe to
  `message.im`; that step is for apps driven by the Events API, which needs a
  public request URL or a Socket Mode client the watcher does not run.
- **Token rotation off.** With rotation the bot token expires every 12 hours,
  while the watcher reads one token file; and rotation cannot be turned off once
  it is on (Slack's token and token-rotation pages), so the mistake is permanent.
- **Org-wide deploy off.** The app is installed to one workspace.
- **`always_online` on.** The agent is always reachable, so its bot shows as
  available.
- **The Messages tab is open exactly when the tier reads DMs.** A writable tab
  without `im:read` and `im:history` lets people write to a bot that never sees
  it.

### 4.3 Creating, installing, storing the token, inviting

Steps 1 to 3 are the person's; Claude hands over the link and the way to pass
the token, and does everything after them.

1. **The person** opens the `--url` link, or goes to
   `https://api.slack.com/apps?new_app=1`, chooses **From a manifest**, picks the
   workspace, pastes `manifest.json`, reviews, **Create**.
2. **The person**, on the app's **OAuth & Permissions** page, clicks **Install
   to Workspace**. A workspace that requires app approval sends the request to
   its admins first.
3. **The person hands over the bot token** from **OAuth Tokens** on the same
   page (*Handing over a secret*), as `<home>/secrets/personal/slack-bot.key`
   on the target, holding the token alone. A token minted for one agent is a
   personal credential (`/agent` section 3), so it does not go in the
   organization store `FLEET_SECRETS_DIR` names.
4. Prove the token holds exactly the tier. The token is read on the target into
   `printf`, a shell builtin, and reaches curl on its standard input as a header
   (`-H @-`), so it is in no command's arguments:

   ```bash
   ssh <target> 'printf "Authorization: Bearer %s\n" "$(cat <home>/secrets/personal/slack-bot.key)" | curl -sS -D- -H @- https://slack.com/api/auth.test' \
     | python3 "${CLAUDE_SKILL_DIR}/slack_manifest.py" granted --tier <tier>
   ```

   Exit 0 is a match; 1 lists what is missing or extra; 2 is NO VERDICT - the
   call never reached Slack, or Slack refused the token, and the line names
   which. Scopes are additive and a token's scopes cannot be
   downgraded (Slack's OAuth guide), so moving an agent DOWN a tier means
   uninstalling the app from the workspace and installing it again, then
   re-running this check until it exits 0.
5. Write the watcher's config from `/slack-communication`'s
   `config.example.json`, here, and copy it to `<home>/config/slack-watch.json`
   on the target, the path its unit reads (section 5 step 3), with `ssh <target>
   'umask 077 && cat > <home>/config/slack-watch.json' < <local copy>`: the bot
   user id, its handle and the team id from the body of the same `auth.test`
   call without `-D-` (`user_id`, `user`, `team_id`, `url`), the token file's
   path, the owner config directory `<home>/.claude`, a `state.dir` under
   `<home>/state`, and a `state.prefix` no other agent uses.
6. **Invite the bot** to each channel it should hear: a member of the channel
   types /invite @<Agent-Name> there. Channel membership is the only control
   over what reaches its session (`/slack-communication`). The person does it in
   the same message that asks for the test post (section 6).
7. Tell the owners of the agents it will talk to: their watcher configs label
   its bot user id, and their charters say what it may ask them and when they
   stay silent - two agents with no such rule answer each other without end
   (`/slack-communication`, the two-node loop).

## 5. Daemons, links and units [target]

In this order; each step needs the one before it. The daemons are the agents
user's user units, installed without root. The agent's own unit and its
watchdog are system units in the system form, each installed by one root
command (*The two users*); in the user form the agent's own unit is a user unit
too, and only the watchdog needs root.

1. **Lingering** [systemd], so the user's service manager runs with nobody
   logged in:

   ```bash
   ssh <target> 'loginctl show-user "$(id -un)" -p Linger'    # Linger=yes
   ```

   When it says `Linger=no`, the agents' user enables it without sudo, where
   the host's polkit policy grants `org.freedesktop.login1.set-self-linger`,
   which systemd's shipped policy does: `loginctl enable-linger`. Ask before
   running it - it keeps that user's services running at boot with nobody
   logged in, which is the point - and run it on the person's OK. A host that
   refuses it needs `sudo loginctl enable-linger <the user>`, by *Root on the
   target* above. Without lingering every unit below stops at the last
   logout and does not start at boot, with nothing to report it. An install
   that created its agents user with `/install-agent-fleet` has it on already:
   `bootstrap-target.sh --install --read-back <read-back file> --agents-user`
   turns it on.

   **[launchd] Automatic login**, its macOS counterpart: the agents' daemons are
   LaunchAgents in the agents user's gui domain, which exists only while that
   user is logged in at the console, so the agents user must be the account that
   logs in at boot:

   ```bash
   ssh <target> 'PATH=/opt/homebrew/bin:$PATH python3 -c "import sys; sys.path.insert(0, sys.argv[1]); from fleetlib import services; print(services.domain_exists())" <fleet>/lib'   # True
   ```

   `False` means no session of the agents user's: `bootstrap-target.sh --install
   --read-back <read-back file> --agents-password-file <file>` makes that user the
   automatic-login account (`/install-agent-fleet`), which needs FileVault off,
   and the Mac restarted to log it in; System Settings, Users & Groups,
   *Automatically log in as*, does the same by hand.
2. **The daemon unit templates** are user units, no root:
   `~/.local/bin/fleet install --agents-root <agents-root> --units all` renders
   the scheduler template and one per working transport. Run it after this
   agent's checkout exists (section 3 step 2): the render names the project
   directory from the agent homes' checkouts, so on a host with no agent home
   yet it stops at exit 3 (`found none`), and on a host that already has agents
   it prints `nothing changed`. Rendering enables nothing.
3. **The configs the daemons read**, one file per daemon in `<home>/config/`,
   at the name its unit reads: `<home>/config/scheduler.json` (the unit sets it
   as `SCHED_CONFIG`) and, per working transport,
   `<home>/config/<watch.job>.json` (as the variable its `transport.json` names
   in `watch.config_env`; `slack-watch.json` and `SLACK_WATCH_CONFIG` for
   Slack). `python3 <fleet>/systemd/agent-daemons.py jobs --json` prints each
   job's config file, relative to the home, and its variable;
   `<fleet>/systemd/README.md` is the table it comes from. The scheduler's per
   `/scheduled-tasks`'s installation steps 2 to 5; the watcher's per 4.3 above.
4. **`fleet link <agent-name>`** links the install's skills into
   `<home>/.claude/skills/`. It reads the install manifest through the home's
   project checkout, which is why the checkout comes first.
5. **Enable this agent's daemons** - the scheduler, and one per working
   transport whose config exists (a job without one is SKIPPED, saying so):

   ```bash
   ssh <target> 'python3 <fleet>/systemd/agent-daemons.py --install <agent-name>'
   ```

   It creates `<home>/state/daemons/` and writes each log's follower cursor
   before the unit's first start; a hand-run `systemctl --user enable --now`
   does neither, and a follower armed after the start never sees its first lines.
   Each log there is written only by its unit: never edit it in place (`sed -i`
   or any rewrite), move, truncate or delete it; read it, or copy it.
6. **The agent's own unit** [systemd], from
   `<fleet>/templates/claude-agent.service.example`, in the install's form
   (*The two users* above): `system`, a system unit the administrator installs,
   or `user`, a user unit installed without sudo. Fill the FIRST line of this
   block and run it on the target as one block; every other line runs as
   written:

   ```bash agent-unit
   a=<agent-name> n='<Agent-Name>' root='<agents-root>' fleet='<fleet>' proj=<project-dir> job=<watch-job> var=<watch-config-env> auth=<auth-mode> form=<unit-form>
   src="$fleet/templates/claude-agent.service.example"; me=$(id -un)
   case "$form" in
     system) unit="$root/$a/config/claude-agent-$a.service" keep=system drop=user ;;
     user) unit="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/claude-agent-$a.service" keep=user drop=system ;;
     *) echo "NOT RENDERED: form=$form is neither system nor user"; exit 1 ;;
   esac
   install -d "${unit%/*}"
   sed -e "/^#$drop: /d" -e "s/^#$keep: //" -e "s|<agent-name>|$a|g" -e "s|<Agent-Name>|$n|g" -e "s|<agents-root>|$root|g" \
       -e "s|<fleet>|$fleet|g" -e "s|<project-dir>|$proj|g" -e "s|<watch-job>|$job|g" -e "s|<agents-user>|$me|g" \
       -e "s|<watch-config-env>|$var|g" -e "s|<auth-mode>|$auth|g" -e "s|<uid>|$(id -u)|g" "$src" > "$unit"
   command grep -cE '<[A-Za-z][A-Za-z0-9-]*>' "$src"                       # control: MUST print a number above 0
   command grep -nE '<[A-Za-z][A-Za-z0-9-]*>|^#(user|system): ' "$unit"   # must print NOTHING
   echo "rendered $unit"
   if [ "$form" = system ]; then
     case "$unit" in *[!A-Za-z0-9._/@+-]*) safe= ;; *) safe=1 ;; esac
     if [ -n "$safe" ] && [ "$(command grep -E '^(User|WantedBy)=' "$unit")" = "$(printf 'User=%s\nWantedBy=multi-user.target' "$me")" ] \
        && ! command grep -qE '<[A-Za-z][A-Za-z0-9-]*>|^#(user|system): ' "$unit"; then
       echo "sudo sh -c \"install -m 644 $unit /etc/systemd/system/claude-agent-$a.service && systemctl daemon-reload && systemctl enable --now --no-block claude-agent-$a.service\""
     else
       echo "NOT RENDERED: $unit holds a placeholder or a form marker, not exactly User=$me and WantedBy=multi-user.target, or a character outside A-Z a-z 0-9 . _ / @ + -; no root command"
     fi
   fi
   ```

   `<agents-root>` and `<fleet>` are `agents_root` and `fleet_checkout` in the
   target's host settings file; `<watch-job>` and `<watch-config-env>` are the
   transport job's name and config variable in `agent-daemons.py jobs --json`;
   `<auth-mode>` is the one section 3 step 4 used; `<unit-form>` is `system`
   or `user`. The two greps are section 2 step 4's check, and the second also
   finds a form marker the render left: when the control prints 0 the pattern
   is blind, and the second line's silence means nothing. The template's
   `#system: ` and `#user: ` lines are the whole difference between the forms
   (its header). The system form is rendered into the agent's config directory
   and printed with ONE root command, refused unless the unit holds exactly
   the agents user's `User=` and `WantedBy=multi-user.target`: a marker the
   `sed` no longer matches would otherwise install a unit that runs the agent
   as root, or never starts at boot. Then verify the rendered file, and in the
   system form run the printed command by *Root on the target*:

   ```bash
   ssh <target> 'systemd-analyze verify <the rendered unit>; echo "verify exit $?"'                                     # system form
   ssh <target> 'XDG_RUNTIME_DIR=/run/user/$(id -u) systemd-analyze --user verify <the rendered unit>; echo "verify exit $?"'  # user form
   ```

   In the user form, load it: `ssh <target> 'systemctl --user daemon-reload'`.
   Then read the unit back, as the agents user; in the system form every
   `systemctl --user` and `journalctl --user` from here to the end of this step
   is the same command without `--user`:

   ```bash
   ssh <target> 'systemctl --user show claude-agent-<agent-name>.service -p LoadState -p TimeoutStartUSec -p Environment'
   ssh <target> 'systemctl --user show claude-agent-<agent-name>.service -p ExecStartPost --value'
   ```

   `verify` exits 0 (it runs offline in a manager of its own; the user form's
   needs only an existing runtime directory); `LoadState=loaded`,
   `TimeoutStartUSec=5min`, and the environment names
   `TMUX_TMPDIR=/run/claude-tmux-<agent-name>` in the system form or
   `TMUX_TMPDIR=/run/user/<uid>/claude-tmux-<agent-name>` in the user form -
   systemd has expanded the template's `%t` - and
   `FLEET_AGENT_AUTH=<auth-mode>`. The `ExecStartPost` value carries the boot
   message whole, from `You are <Agent-Name>` to `your charter names.`

   Before the start: `<home>/<project-dir>/.claude/agents/<agent-name>.md`
   exists, the first run is done (section 3 step 4), the credential file exists
   (`ls -l`: mode 600, empty only for `login`) and, for A,
   `python3 <fleet>/.claude/skills/agent-health/pool_pick.py --read-auth-file
   <home>/secrets/personal/claude-auth.env` names `"auth": "token"` and its
   account without reading the token, and step 5 enabled the daemons.
   Start it without waiting for the start to finish, because the unit sleeps 60
   seconds and then waits for the session to be ready - in the system form the
   printed root command does that, and in the user form the first line below:

   ```bash
   ssh <target> 'systemctl --user enable --now --no-block claude-agent-<agent-name>.service'
   ssh <target> 'systemctl --user is-active claude-agent-<agent-name>.service'              # activating, then active
   ssh <target> 'journalctl --user -u claude-agent-<agent-name>.service -n 20 --no-pager'   # no BOOT MESSAGE NOT SENT line
   ```

   Re-run `is-active` every 15 seconds until it prints `active`, at most 6
   minutes (the unit's own start timeout is 5). A `BOOT MESSAGE NOT SENT` line
   means a dialog held the session: read the pane with `env -u TMUX
   TMUX_TMPDIR=<the unit's TMUX_TMPDIR> tmux capture-pane -p -t
   claude-<agent-name>:0 | command grep -v sk-ant-`, answer it, and end the
   session with `env -u TMUX TMUX_TMPDIR=<the same> tmux kill-server`: the
   unit's `Restart=always` starts it again after its 60-second pre-sleep and
   types the boot message again, and a new agent has no conversation for the
   restart to lose. That works in both forms with no root: the agents user owns
   its session's tmux server, though not the unit.

   **Then prove the session armed its followers**, not merely that the message
   was typed. Only a follower writes a cursor file once the daemons run, and an
   armed one rewrites it at least once a minute (measured on live agents), so a
   few minutes after `active`:

   ```bash
   ssh <target> 'systemctl --user show claude-agent-<agent-name>.service -p ActiveEnterTimestamp --value'
   ssh <target> 'date "+%F %T %Z"; stat -c "%y %n" <home>/state/daemons/*.log.cursor'   # linux-only: the [systemd] form; the [launchd] one below uses stat -f
   ```

   Each cursor's time is later than the moment the unit became active AND within
   about 90 seconds of `date`. Both halves are needed: step 5 wrote every cursor
   before the start, so freshness alone can be that write, and a time after the
   start alone can be a follower that has since ended. A cursor failing either is
   a follower nobody has armed: read the pane for what the session did with its
   first turn.

   **[launchd] The agent's own job**, from `<fleet>/templates/claude-agent.plist.example`
   (its header: the system form is a LaunchDaemon, the user form a LaunchAgent).
   Fill the FIRST line and run the block on the target as one block:

   ```bash agent-plist
   a=<agent-name> n='<Agent-Name>' root='<agents-root>' fleet='<fleet>' proj=<project-dir> job=<watch-job> var=<watch-config-env> auth=<auth-mode> form=<unit-form>
   src="$fleet/templates/claude-agent.plist.example"; me=$(id -un)
   svc() { python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); from fleetlib import services as s; print(s.prefix() if sys.argv[2] == "prefix" else s.unit_dir(sys.argv[2]))' "$fleet/lib" "$1"; }
   prefix=$(svc prefix) || { echo "NOT RENDERED: fleetlib names no launchd prefix"; exit 1; }
   label="$prefix.session.$a"
   case "$form" in
     system) [ "$auth" != login ] || { echo "REFUSED: a macOS agent in the system form runs as a LaunchDaemon, which has no window server and no login Keychain, so it signs in only with a token or an API key (question 6, A or C); nothing rendered"; exit 1; }
             dest="$(svc system)/$label.plist" keep='s|<!--system: \(.*\) -->|\1|' ;;
     user) dest="$(svc user)/$label.plist" keep='/<!--system: /d' ;;
     *) echo "NOT RENDERED: form=$form is neither system nor user"; exit 1 ;;
   esac
   out="$root/$a/config/$label.plist"
   sock="$root/run/claude-tmux-$a/tmux-$(id -u)/default"
   [ ${#sock} -lt 104 ] || { echo "NOT RENDERED: the session's socket $sock is ${#sock} bytes and macOS holds at most 103; use a shorter agents root"; exit 1; }
   install -d -m 755 "$root/run" && install -d "$root/$a/state" "${out%/*}" && touch "$root/$a/state/session.log"
   [ "$form" = system ] || install -d "${dest%/*}"
   sed -e "$keep" -e "s|<launchd-prefix>|$prefix|g" -e "s|<agent-name>|$a|g" -e "s|<Agent-Name>|$n|g" -e "s|<agents-root>|$root|g" \
       -e "s|<fleet>|$fleet|g" -e "s|<project-dir>|$proj|g" -e "s|<watch-job>|$job|g" -e "s|<watch-config-env>|$var|g" \
       -e "s|<auth-mode>|$auth|g" -e "s|<agents-user>|$me|g" "$src" > "$out"
   plutil -lint "$out" >/dev/null || { echo "NOT RENDERED: $out does not lint: a placeholder or a form marker left"; exit 1; }
   got=$(python3 -c 'import plistlib, sys; d = plistlib.load(open(sys.argv[1], "rb")); print(d["Label"], d.get("UserName", "-"))' "$out")
   case "$out$dest" in *[!A-Za-z0-9._/@+-]*) safe= ;; *) safe=1 ;; esac
   if [ "$form" = system ] && [ -n "$safe" ] && [ "$got" = "$label $me" ]; then
     echo "sudo sh -c \"install -m 644 -o root -g wheel $out $dest && launchctl bootstrap system $dest\""
   elif [ "$form" = user ] && [ -n "$safe" ] && [ "$got" = "$label -" ]; then
     echo "install -m 644 $out $dest && launchctl bootstrap gui/$(id -u) $dest"
   else
     echo "NOT RENDERED: $out names '$got', not exactly the label $label with the $form form's UserName ($me in the system form, none in the user form), or a path holds a character outside A-Z a-z 0-9 . _ / @ + -; no command"
   fi
   ```

   `<agents-root>`, `<fleet>`, `<watch-job>`, `<watch-config-env>` and
   `<auth-mode>` are step 6's; `<unit-form>` is `system` or `user`. The label and
   the two directories come from fleetlib (host.json's `launchd_prefix`, and
   /Library/LaunchDaemons or ~/Library/LaunchAgents). `plutil -lint` is the
   placeholder check here: a placeholder is an XML tag to it, so a file with one
   left does not lint. The block refuses B in the system form, a socket path
   macOS cannot bind, and - for the printed command - anything but exactly this
   label with, in the system form, `UserName` the agents user: a marker the
   `sed` no longer matches would otherwise install a session that runs as root.
   It renders into the agent's config directory in both forms and only the
   printed command puts the file where launchd loads it, because launchd reads
   every plist in ~/Library/LaunchAgents at the next login, a refused one
   included. The supervisor creates
   `<agents-root>/run/claude-tmux-<agent-name>`, mode 700, at the start; its log is
   `<home>/state/session.log`.

   Before the start, the same as above (charter, first run, credential file,
   daemons). Start it - in the system form by running the printed root command
   by *Root on the target*, in the user form by running the printed command on
   the target as the agents user - then:

   ```bash
   ssh <target> 'launchctl print system/<label> | grep -E "^[[:space:]](state|pid) ="'  # system form; gui/$(id -u)/<label> for the user form: state = running
   ssh <target> 'tail -n 20 <home>/state/session.log'                                # "boot message sent to claude-<agent-name>", no BOOT MESSAGE NOT SENT
   ```

   The supervisor waits 60 seconds, then up to 3 minutes for the ready status
   bar; re-read the log every 15 seconds, at most 6 minutes. A `BOOT MESSAGE
   NOT SENT` line is the same dialog case as above: answer it in the pane
   (`env -u TMUX TMUX_TMPDIR=<agents-root>/run/claude-tmux-<agent-name> tmux
   capture-pane -p -t claude-<agent-name>:0 | command grep -v sk-ant-`), then
   end the session with `kill-server` on the same socket: the supervisor exits,
   launchd starts it again, and it types the boot message again. Then prove the
   followers armed: each cursor is newer than the session's `started
   claude-<agent-name>` line in that log and within about 90 seconds of now -

   ```bash
   ssh <target> 'grep "started claude-" <home>/state/session.log | tail -1; date "+%F %T"; stat -f "%Sm %N" -t "%F %T" <home>/state/daemons/*.log.cursor'
   ```
7. **The stall watchdog** [systemd] - only when answer 7 was yes. Fill the FIRST
   line of this block and run it on the target; it renders the config, the state
   directory and the unit, and prints the ONE root command that installs and
   starts the unit:

   ```bash watchdog-unit
   a=<agent-name> root='<agents-root>' fleet='<fleet>' proj=<project-dir> form=<unit-form>
   skill="$fleet/.claude/skills/stall-watchdog"; name="claude-agent-$a-stall-watchdog.service"
   out="$root/$a/config/$name"; staged="$root/$a/config/stall-watchdog.json"; state="$root/$a/state/stall-watchdog"
   case "$form" in
     system) dir="/run/claude-tmux-$a"; cfg="/etc/agent-fleet/stall-watchdog/$a.json"; put="install -D -m 644 $staged $cfg && " ;;
     user) dir="/run/user/$(id -u)/claude-tmux-$a"; cfg="$staged"; put="" ;;
     *) echo "NOT RENDERED: form=$form is neither system nor user; no root command"; exit 1 ;;
   esac
   install -d -m 700 "$state"
   install -m 600 "$skill/config.example.json" "$staged"
   python3 -c 'import json, sys; p, d, t, s = sys.argv[1:]; c = json.load(open(p, encoding="utf-8")); c["tmux"].update(tmpdir=d, target=t); c["state"]["dir"] = s; open(p, "w").write(json.dumps(c, indent=2) + "\n")' "$staged" "$dir" "claude-$a:0" "$state"
   sed -e "s|<tmux-dir>|$dir|g" -e "s|^Environment=STALL_WATCHDOG_CONFIG=.*|Environment=STALL_WATCHDOG_CONFIG=$cfg|" \
       -e "s|<agent>|$a|g" -e "s|<user>|$(id -un)|g" -e "s|<checkout>|$root/$a/$proj|g" -e "s|<fleet>|$fleet|g" \
       -e "s|<agents-root>|$root|g" -e "s|<state dir>|$state|g" "$skill/installation/agent-stall-watchdog.service.example" > "$out"
   case "$out$staged" in *[!A-Za-z0-9._/@+-]*) safe= ;; *) safe=1 ;; esac
   if [ -n "$safe" ] && [ "$(command grep -cxE "(Environment=TMUX_TMPDIR|ReadWritePaths)=$dir|Environment=STALL_WATCHDOG_CONFIG=$cfg" "$out")" = 3 ] \
      && ! command grep -nE '<[A-Za-z][A-Za-z0-9 -]*>' "$out"; then
     echo "sudo sh -c \"${put}install -m 644 $out /etc/systemd/system/$name && systemctl daemon-reload && systemctl enable --now $name\""
   else
     echo "NOT RENDERED: $out holds a placeholder or a character outside A-Z a-z 0-9 . _ / @ + -, or does not name the tmux directory $dir and the config $cfg; no root command"
   fi
   ```

   `<unit-form>` is step 6's. Why each part is there:

   - **The tmux directory is the session's.** The example's `<tmux-dir>` is
     filled with the form's: `/run/claude-tmux-<agent-name>`, where a system
     session unit's `%t` puts it, or `/run/user/<uid>/claude-tmux-<agent-name>`
     for a user session; the config's `tmux.tmpdir` is set to the same value.
     The watchdog unit is a system unit in both forms, so it needs the literal
     path.
   - **In the system form the config is root's.** The block stages it in the
     agent's config directory, and the root command installs it to
     `/etc/agent-fleet/stall-watchdog/<agent-name>.json`, mode 644, which the
     unit names: a config the agents user can write is a watchdog it can switch
     off, which is what the privilege split exists to prevent. The second `sed`
     expression points the unit's one `STALL_WATCHDOG_CONFIG=` line at the
     form's config path.
   - **The `if` refuses to print the root command** unless the
     `Environment=TMUX_TMPDIR=`, the tmux `ReadWritePaths=` and the
     `STALL_WATCHDOG_CONFIG=` lines carry the form's values and no placeholder
     is left - a changed example that a `sed` no longer matches prints NOT
     RENDERED instead of a command that installs a blind watchdog, or one that
     reads a config the agent can edit. The placeholder pattern there admits a
     space, because `<state dir>` holds one.
   - **One root command, one `sudo`.** The installs, the reload and the enable
     run inside one `sh -c`, so *Root on the target* above feeds a password,
     where one is needed, once. The paths are checked to hold only characters
     that need no quoting, so the command is the same string wherever it runs.
   - **The state directory exists before the unit starts**: it is a
     `ReadWritePaths=` entry, and a missing one fails the unit (`/stall-watchdog`
     step 4). It stays the agents user's: the watchdog runs as that user and
     writes there.
   - **The config is written fresh** from the example with the three per-session
     values set; every other key keeps the shipped value. A value
     `/stall-watchdog` step 5 tunes (`stall.idle_tail_lines`, when `--probe` says
     INERT) is edited in the staged file and installed again by the same root
     command, and a re-run of this block undoes it.
   - **The unit's `Wants=`/`After=claude-agent-<agent-name>.service`** order the
     two system units in the system form, and order nothing in the user form,
     where the system manager has no unit of that name. Either way the
     watchdog's `Restart=always` brings it up once the session's tmux directory
     exists, and until then it fails at start with 226/NAMESPACE, its documented
     recovery path (`/stall-watchdog` step 4).

   **[launchd] The watchdog job** - only when answer 7 was yes - from the
   stall-watchdog skill's `installation/agent-stall-watchdog.plist.example`: a
   LaunchDaemon running as the agents user in the system form, its config root's
   in /etc/agent-fleet; in the user form a LaunchAgent, which the agents user
   controls (`/stall-watchdog`'s check reports it UNPROTECTED). Fill the FIRST line
   and run it on the target:

   ```bash watchdog-plist
   a=<agent-name> root='<agents-root>' fleet='<fleet>' proj=<project-dir> form=<unit-form>
   skill="$fleet/.claude/skills/stall-watchdog"; me=$(id -un)
   svc() { python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); from fleetlib import services as s; print(s.prefix() if sys.argv[2] == "prefix" else s.unit_dir(sys.argv[2]))' "$fleet/lib" "$1"; }
   prefix=$(svc prefix) || { echo "NOT RENDERED: fleetlib names no launchd prefix"; exit 1; }
   label="$prefix.stall-watchdog.$a" dir="$root/run/claude-tmux-$a"
   out="$root/$a/config/$label.plist"; staged="$root/$a/config/stall-watchdog.json"; state="$root/$a/state/stall-watchdog"
   case "$form" in
     system) cfg="/etc/agent-fleet/stall-watchdog/$a.json" dest="$(svc system)/$label.plist" ;;
     user) cfg="$staged" dest="$(svc user)/$label.plist" ;;
     *) echo "NOT RENDERED: form=$form is neither system nor user; no root command"; exit 1 ;;
   esac
   install -d -m 700 "$state" && { [ "$form" = system ] || install -d "${dest%/*}"; }
   install -m 600 "$skill/config.example.json" "$staged"
   python3 -c 'import json, sys; p, d, t, s = sys.argv[1:]; c = json.load(open(p, encoding="utf-8")); c["tmux"].update(tmpdir=d, target=t); c["state"]["dir"] = s; open(p, "w").write(json.dumps(c, indent=2) + "\n")' "$staged" "$dir" "claude-$a:0" "$state"
   python3 "$skill/installation/render-plist.py" --agent "$a" --agents-root "$root" --checkout "$root/$a/$proj" \
       --state-dir "$state" --tmux-dir "$dir" --config "$cfg" --form "$form" --out "$out" || exit 1
   plutil -lint "$out" >/dev/null || { echo "NOT RENDERED: $out does not lint; no root command"; exit 1; }
   got=$(python3 -c 'import plistlib, sys; d = plistlib.load(open(sys.argv[1], "rb")); e = d["EnvironmentVariables"]; print(d["Label"], d.get("UserName", "-"), e["TMUX_TMPDIR"], e["STALL_WATCHDOG_CONFIG"])' "$out")
   case "$out$staged$dest" in *[!A-Za-z0-9._/@+-]*) safe= ;; *) safe=1 ;; esac
   if [ "$form" = system ] && [ -n "$safe" ] && [ "$got" = "$label $me $dir $cfg" ]; then
     echo "sudo sh -c \"install -d -m 755 /etc/agent-fleet/stall-watchdog && install -m 644 $staged $cfg && install -m 644 -o root -g wheel $out $dest && launchctl bootstrap system $dest\""
   elif [ "$form" = user ] && [ -n "$safe" ] && [ "$got" = "$label - $dir $cfg" ]; then
     echo "install -m 644 $out $dest && launchctl bootstrap gui/$(id -u) $dest"
   else
     echo "NOT RENDERED: $out names '$got', not the label, user, tmux directory $dir and config $cfg of the $form form, or a path holds a character outside A-Z a-z 0-9 . _ / @ + -"
   fi
   ```

   The same reasons as the systemd block above, in launchd's terms: the tmux
   directory is the session supervisor's, `<agents-root>/run/claude-tmux-<agent-name>`;
   in the system form the config is root's and the job a LaunchDaemon with
   `UserName` the agents user, installed with its config by ONE root command; the
   user form prints the agents user's own commands, no sudo, and is UNPROTECTED.
   The last line is refused unless the label, the user, the tmux directory and
   the config are exactly the form's. The job itself is rendered by the
   stall-watchdog skill's `installation/render-plist.py`, as the agents user the
   job runs as: it writes the job's PATH from the tmux on this block's PATH and
   the fleet's interpreter, and prints `NOT RENDERED` instead of a plist when no
   tmux is on that PATH, or when tmux or the interpreter does not run under the
   PATH it would write, because a job whose PATH reaches no tmux runs, captures
   nothing and looks healthy. A target whose tmux is not in Homebrew's directory
   runs this block with that directory in front of PATH as well.

   Before the root command runs, run `/stall-watchdog` step 5 against the live
   session on the target, with `STALL_WATCHDOG_CONFIG=<the staged config>`: the
   offline test, `doctor` (tmux reachable) and `--probe`, whose `prompt match
   False` and `exclusion ARMED` are both required. Then run the printed command
   on the target by *Root on the target* above - or, when the person prefers to
   run it themselves, send them the paths of the rendered unit and the staged
   config, to read first, and the printed line, to run on the target. Once it
   ran: `/stall-watchdog` step 6's proof of capture (the state file newer than
   the service start, with no `capture_error` in it), its step 7 record, and
   its `installation/check` until it exits 0, each with the config the unit
   names (`/etc/agent-fleet/...` in the system form). When answer 7 was no, skip this step; step 9 says what that
   leaves.
8. **The other skills' per-agent steps**, for each skill in the manifest's
   `skills` whose `installation/INSTRUCTION.md` names steps per agent and that
   the steps above do not cover: `google-spreadsheet` (the agent's key, its
   delegation grant and its record) and `web-hierarchy-server` (one server and
   unit per agent). Each instruction says which of its steps those are. The
   install records those steps and `/scheduled-tasks` step 5 write
   (`installation/.install-state.json` in the install context) are committed,
   so they land like the charter and reach the agent's checkout by a pull.
9. **The health check:**

   ```bash
   ssh <target> '~/.local/bin/fleet check-all <agent-name>'   # one row per linked skill's installation/check
   ssh <target> '~/.local/bin/fleet status <agent-name>'      # links, tag, charter step pointers, daemons, watchdog, the agent unit's follower path; exit 1 on drift
   ```

   Every row that is not clean is either fixed, by the instruction of the skill
   it names, or explained in the report (section 7) with the reason it stays.
   A record that has not reached the agent's checkout reads STALE in
   `check-all` until the pull. With answer 7 no, two rows stay and both mean
   the same thing: `check-all`'s `stall-watchdog` row is `2 not installed`, and
   `fleet status` prints `DRIFT ... claude-agent-<agent-name>-stall-watchdog.service
   is not installed, and the install links stall-watchdog` and exits 1. Report
   them as the watchdog the person declined, never as clean.
10. **The privilege check**, as the agents user: can it escape its supervision?

    ```bash
    ssh <target> 'python3 <fleet>/.claude/skills/install-agent-fleet/verify-privileges.py --agent <agent-name>'              # system form
    ssh <target> 'python3 <fleet>/.claude/skills/install-agent-fleet/verify-privileges.py --no-admin --agent <agent-name>'   # user form
    ```

    Read only; one line per fact and a verdict line; its header says what each
    check is and what it does not claim. On a macOS target the same commands
    check the launchd jobs: the session and the watchdog as LaunchDaemons with
    `UserName` the agents user and plists it cannot change. Exit 0 PROTECTED is done. Exit 1 is a
    FAIL line - sudo for the agents user, a unit file, the watchdog's config,
    program or interpreter, the tmux its PATH reaches or a directory searched
    before it, anything in the fleet checkout or the identities `fleet upgrade`
    trusts that it can change, a session unit that is not a system unit or
    runs as anyone else - fixed before the agent counts as added, never
    reported past. Exit 3 NO VERDICT names what it could not measure. Exit 4
    UNPROTECTED is the user form's, and the report says so.

## 6. The test message

The last proof is a message from a person reaching the agent's session. Claude
reads two files the agent's daemons write on the target and runs nothing that
consumes them: a second follower would move the agent's own cursor, and it is
refused while the agent's follower holds the log's lock.

1. **Make a code** nobody has typed before: `check-` and the time,
   `check-$(date +%H%M%S)`.
2. **Ask the person** [here], in one message: invite the bot to a channel it
   should hear (/invite @<Agent-Name>, section 4.3 step 6) if it is not there
   yet, and post the code in that channel; with the standard or full tier, also
   send the bot a direct message of the code followed by `-dm`.
3. **The watcher saw it** [target] - the watcher's log, from the ask until 10
   minutes after it:

   ```bash
   ssh <target> "command grep -bF '<code>' <home>/state/daemons/<watch-job>.log"
   ```

   Re-run it every 15 seconds. It is done when it prints
   `SLACK #<channel> message [ts ...] <sender>: <code>`, and for a DM a
   `SLACK DM ...` line with `<code>-dm`. A channel the bot has just joined
   reaches the watcher at its next rediscovery, within `poll.rediscover_secs`
   (60 by default) of the invite.
4. **The agent received it** [target] - the follower moves its cursor past a
   line only after printing the line to the agent's Monitor, so the cursor is
   the agent's own receipt. As soon as step 3 prints, read the log's size, then
   the cursor:

   ```bash
   ssh <target> 'wc -c < <home>/state/daemons/<watch-job>.log; cat <home>/state/daemons/<watch-job>.log.cursor'
   ```

   The cursor's `offset` reaches that size within 60 seconds. One that stays
   below it is a session that did not receive the line: its follower is not
   armed, which step 6 of section 5 checks.
5. **Nothing in 10 minutes**: `systemctl --user is-active
   agent-<watch-job>@<agent-name>` on the target, the last lines of the
   watcher's log (`WATCH-CONFIG`, `WATCH-GUARD` and `WATCH-ERROR` name their
   cause), and whether the bot is a member of the channel. Ask the person to
   post again only after the cause is fixed.

Whether the agent answers the message is its charter's decision, not part of
this check.

## 7. The report [here]

One message to the person (`/talking-to-humans`), covering:

- the agent, the target, its unit and how to look at it: `systemctl status
  claude-agent-<agent-name>` on the target (`systemctl --user status` in the
  user form; on macOS `launchctl print system/<label>`, or
  `gui/<uid>/<label>` in the user form), and the session itself with `ssh -t
  <target> 'env -u TMUX TMUX_TMPDIR=<the unit's TMUX_TMPDIR> tmux attach -t
  claude-<agent-name>'`;
- the privilege check's verdict line, and every line of it that is not ok;
- how it signs in (A, B or C), and for A when the token expires (one year
  from `claude setup-token`) and that a new one replaces the credential file
  the same way;
- the test message: the watcher's line and the time it arrived, and the cursor
  that shows the agent received it;
- the stall watchdog: installed and capturing, or declined;
- every `fleet check-all` and `fleet status` row that is not clean, each with
  its reason.

## 8. Done means

- the charter's placeholder check printed nothing, after its positive control
  printed lines; the agent unit's check the same;
- no secret was printed, and each secret file on the target is mode 600;
- with Slack, `granted --tier <tier>` exits 0;
- `claude-agent-<agent-name>.service` is active - a system unit running as the
  agents user, or in the user form a user unit - with lingering on for the
  agents user (on macOS: its session job is running, a LaunchDaemon with
  `UserName` the agents user or in the user form a LaunchAgent, with automatic
  login on for the agents user), its boot message was sent, and both follower
  cursors are fresh;
- the privilege check (section 5 step 10) exits 0, or 4 in the user form, which
  the report states as UNPROTECTED;
- the test message is in the watcher's log and the follower's cursor has passed
  it, and a DM the same for the standard and full tiers;
- `fleet check-all <agent-name>` and `fleet status <agent-name>` are clean,
  except the rows section 5 step 9 names when the watchdog was declined, which
  the report explains;
- with the watchdog, its `installation/check` exits 0.
