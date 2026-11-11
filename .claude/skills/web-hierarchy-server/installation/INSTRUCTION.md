# Installing `web-hierarchy-server`

Five steps. When they are done, `installation/check` exits `0`.

**Two directories.** The skill's own files (`SKILL.md`, the scripts, this
procedure) live in the fleet tree; every command below names them through
`CLAUDE_SKILL_DIR`, which a `SKILL.md` load substitutes and this file does not,
so set it once. The install's files (`config.json`, `CONTEXT.md`,
`installation/.install-state.json`) live in the skill's **install context**,
which `fleet where web-hierarchy-server` prints; call it `CTX`:

```bash
CLAUDE_SKILL_DIR=<the directory holding this skill's SKILL.md>
CTX=$(fleet where web-hierarchy-server)
```

**Dependencies: none beyond node.** `serve.mjs`, `format.mjs`, `build.mjs` and their
tests are node standard library only, which is why there is no
`requirements.txt` and no `package.json` beside this file. `installation/check`
is Python 3 standard library only. Step 3 additionally needs systemd and root.

**Install-wide and per agent.** Step 1's `config.json` is install-wide, once, and
lists every server the machine runs. Steps 2, 3 and 5 are per agent - one server
and one unit per agent's config directory - and need that agent's home and its
signed-in Claude Code config directory, whose transcripts the server reads. Step
4's record is once per machine.

**Who runs which step.** Steps 1, 2, 4 and 5 need nothing privileged. **Step 3
needs root**, so on a machine where an agent is the only one present it does not
happen and the server runs in the interim form step 2 describes -
`installation/check` then reports that leg as needing attention, in words, and
never as a green.

---

## 1. `config.json`

```bash
mkdir -p "$CTX" && install -m 644 "${CLAUDE_SKILL_DIR}/config.example.json" "$CTX/config.json"
```

`install -m 644`, not `cp`: the fleet tree is read-only and `cp` keeps that
mode. Then replace **every** placeholder. The `_comment` keys in the file say what
each value is and how a wrong one fails; they are ignored by the loader, so you
may keep or delete them.

Four that are easy to get wrong:

- **`transcripts.config_dir`** is the fallback for a run with
  `CLAUDE_CONFIG_DIR` unset. Wrong value, and the viewer finds A session,
  renders it completely, and it belongs to a different agent. Nothing on the
  page says so. Write it home-relative (`~/...`) when the agents root is under
  the home directory: an absolute path in a committed config is one machine
  leaking into a shared file. When the agents root is outside the home
  directory, `~/` cannot reach it and the absolute path is the correct value.
  The same holds for each `servers` entry's `config_dir`.
- **`fleet.by_config_dir`** is keyed by the DERIVED key, not the raw basename:
  the basename, except that a basename of `.claude` is replaced by the parent
  directory's basename. `~/agents/ada/.claude` is keyed `ada`. Get this wrong
  and every page in the fleet is labelled with one agent's name while rendering
  another's work.
- **`identities.file`** is best left null, which means the roster shipped with
  the skill. A path you set must resolve (relative to `config.json`'s
  directory). A roster that will not load is not a runtime error: every block
  just renders with no name and no avatar, which reads as a design choice.
  `check` is what catches it.
- **`servers`** must list every server this machine runs, with its unit name and
  port, whether or not the unit is installed yet. It is what `check` reads to
  know what to verify, and what `serve.mjs` uses to pick a default port for the
  config dir it is running under.

## 2. Start one server per agent

**ONE server per config dir.** Before starting anything, establish that none is
already up for it:

```bash
"${CLAUDE_SKILL_DIR}/installation/check"   # names who holds the configured port, starts nothing
```

The durable form is step 3. Until a unit exists, start the server as a
**detached process that outlives the shell that launched it**:

```bash
setsid nohup env CLAUDE_CONFIG_DIR=<this agent's config dir> \
  WEB_HIERARCHY_CONFIG="$CTX/config.json" \
  node "${CLAUDE_SKILL_DIR}/serve.mjs" > <a log path outside the repo> 2>&1 &   # linux-only: macOS has no setsid; see below
```

On macOS, which has no `setsid`, the same line starts with `nohup env ...`: the
process is backgrounded and ignores the hangup, and the LaunchAgent in step 3 is
its durable form.

Then **confirm it by reading the log**, not by the absence of an error:
`setsid` detaches, so a failure to start is silent at the terminal, and an
unwritable log path means the process dies with nothing anywhere to say so.
The log's first lines are the banner with the URL; `curl -s
http://127.0.0.1:<port>/state | head -c 200` is the second confirmation.

**Start it from the fleet tree the server should keep running from** (the host
checkout), never from a git worktree that will be deleted: node holds the files
it loaded, but a restart (or the unit in step 3) resolves the path again, and a
path that no longer exists fails at the worst moment.

## 3. The service unit, one per agent (needs root)

`installation/web-hierarchy-server.service.example` is the template. Instantiate
it once per agent:

```bash
sed -e 's|YOUR_USER|<the user the agent sessions run as>|g' \
    -e 's|AGENTS_ROOT|<the directory holding the agent homes>|g' \
    -e 's|YOUR_AGENT|<this agent>|g' \
    -e 's|/path/to/your/install-checkout|<the install checkout>|g' \
    -e 's|/path/to/your/fleet|<the fleet checkout>|g' \
    -e 's|PORT|<this server's port>|g' \
    -e 's|agent N|agent 1|g' \
    "${CLAUDE_SKILL_DIR}/installation/web-hierarchy-server.service.example" > /tmp/web-hierarchy-1.service
```

Read the result before installing it; the template's `REPLACE` comments mark
every value, and a `sed` that missed one leaves the placeholder visible.

**Name each file by ordinal or by the agent's config-dir name, never by a
person or a persona.** The template ships with the skill; a person's name in a
shipped filename is a local value leaking into a common artifact.

**One config dir per unit.** `Environment=CLAUDE_CONFIG_DIR` is the single value
that decides which agent's tree a server shows, and it wins over
`transcripts.config_dir`. Two units pointed at the same config dir give you two
copies of one agent and no view of the other.

**Each unit gets its own port**, matching its entry in `config.json`'s `servers`.

```bash
sudo cp /tmp/web-hierarchy-1.service /etc/systemd/system/
sudo systemctl daemon-reload
# stop the step-2 detached process FIRST, or the unit loses the bind:
sudo systemctl enable --now web-hierarchy-1.service
systemctl is-enabled web-hierarchy-1.service   # enabled
journalctl -u web-hierarchy-1.service -n 20    # the startup banner
```

`enable` is what makes it a machine-start service; `--now` starts it this once.

A unit that dies immediately with `exit 127` is the PATH trap the template's
`bash -lc` exists for: systemd starts a unit with a bare PATH and no login
profile, so a node installed by a version manager is not on it.

**On macOS the unit is a LaunchAgent, and it needs no root.**
`installation/web-hierarchy-server.plist.example` is the template, with
placeholders in angle brackets; `config.json`'s `servers` is keyed by its label,
`<launchd-prefix>.web-hierarchy.<n>`:

```bash
sed -e 's|<launchd-prefix>|com.agent-fleet|g' -e 's|<n>|1|g' \
    -e 's|<agents-root>|<the directory holding the agent homes>|g' \
    -e 's|<agent>|<this agent>|g' \
    -e 's|<install-checkout>|<the install checkout>|g' \
    -e 's|<fleet>|<the fleet checkout>|g' \
    -e 's|<port>|<this server port>|g' \
    "${CLAUDE_SKILL_DIR}/installation/web-hierarchy-server.plist.example" > /tmp/web-hierarchy-1.plist
plutil -lint /tmp/web-hierarchy-1.plist     # a placeholder left in does not parse
install -m 644 /tmp/web-hierarchy-1.plist ~/Library/LaunchAgents/com.agent-fleet.web-hierarchy.1.plist
# stop the step-2 detached process FIRST, or the job loses the bind:
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.agent-fleet.web-hierarchy.1.plist
launchctl print gui/$(id -u)/com.agent-fleet.web-hierarchy.1   # state = running
tail -n 20 <agents-root>/<agent>/state/web-hierarchy-server.log   # the startup banner
```

The gui domain exists while the user is logged in at the console; a Mac host runs
with automatic login for the agents' user, which is what brings it back after a
reboot. A job that exits 127 at once is the same login-PATH trap as above.

## 4. Record the install

`check` compares this file against the `version` in `SKILL.md`. Without it, the
install cannot be told from a stale one, so `check` reports it as needing
attention.

It is a **specific** file and is committed like any other, so it reaches
machines that never ran this procedure. It therefore records **one entry per
host**, and `check` reads the entry for the host it runs on: a single `host`
field would make every other machine report stale, and re-recording it would
un-record the machine before it.

```bash
python3 - "${CLAUDE_SKILL_DIR}/SKILL.md" "$CTX/installation" <<'PY'
import json, re, socket, sys, time, pathlib
here = pathlib.Path(sys.argv[2])
here.mkdir(parents=True, exist_ok=True)
state_file = here / ".install-state.json"
v = int(re.search(r"^version:\s*(\d+)$", pathlib.Path(sys.argv[1]).read_text(), re.M).group(1))
state = json.loads(state_file.read_text()) if state_file.exists() else {}
state.setdefault("hosts", {})[socket.gethostname()] = {
    "version": v,
    "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "by": "INSTRUCTION.md",
}
state_file.write_text(json.dumps(state, indent=2) + "\n")
print("recorded version", v, "for", socket.gethostname())
PY
```

## 5. Check

```bash
"${CLAUDE_SKILL_DIR}/installation/check"   # one line per leg; 0 current, 1 stale or unmeasurable, 2 not installed
```

It reads system state and changes none of it. Lines worth knowing before you see
them:

- **`systemd: <unit> is 'not-found' - the durable form is NOT installed`** - step
  3 has not been run. The line says whether a server from this skill is
  nevertheless answering on the port, which is the step-2 form: the page works
  now and will not come back after a reboot.
- **`NO VERDICT - the negative control PASSED`** - the leg's own control did not
  fire, so the leg measured nothing and no verdict is issued about the subject.
  That is an instrument fault to fix, not a failure to work around.
- **`STALE - ... port N is held by pid P running <other path>`** - a server from
  a different checkout. That is the failure this check exists for: the port
  answers, the page renders, and it is not the install you think it is.
- **`version: this machine has no entry`** - the state file travelled here with
  the repo; the install did not. Run step 4 on this machine.
- **`scripts: serve.mjs resolves its config to X, but this check read Y`** - the
  fleet command and this check disagree about which install is in force. Every
  other line describes Y, and the server reads X.

---

## After installing

**Nothing.** No arming step, no cron. Give the viewer the URL:

```
http://<the machine's address on your VPN or LAN>:<the port>/
```

That URL answers only once `server.host` in `config.json` is set to that VPN or
LAN address (or to `0.0.0.0`, every interface) and the server has restarted:
the default is `127.0.0.1`, which serves this machine alone, and anyone who
can reach the address set reads every agent's transcript.

## Picking up a change to `serve.mjs` or `format.mjs`

node loads those files once, at process start, so an edit is latent in every
running server. Restart the unit (`sudo systemctl restart <unit>`; on macOS
`launchctl kickstart -k gui/$(id -u)/<label>`), or kill and
re-launch the detached process. **Confirm afterwards**: a restart that raced a
still-bound port leaves the OLD process serving, and the page looks identical.

## Running the test

```bash
node "${CLAUDE_SKILL_DIR}/serve.test.mjs"    # 0 pass, 1 fail, 2 NO VERDICT
node "${CLAUDE_SKILL_DIR}/format.test.mjs"   # how the config is found and read
```

It starts a real server on an ephemeral port against `fixtures/`, asserts the
rendered tree, then deletes one subagent's transcript and requires the tree to
lose it. It touches no real transcript and no configured port, so it is safe to
run while a server is up.

## Re-installing after a version bump

`check` reports needing attention when `SKILL.md` declares a version newer than
this host's recorded one. Re-read this file from the top: a bump means something
in the install procedure changed, and the only way to know what is to walk it.
Then redo step 4.
