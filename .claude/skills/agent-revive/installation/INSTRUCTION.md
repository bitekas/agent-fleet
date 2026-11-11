# Installing agent-revive

Two halves. The **read-only tooling** needs `tmux` (already present on any host that
runs agents), `jq`, and a filled-in `config.json`. The **automated sign-in route**
(SKILL.md step 6) additionally needs `node`, a way to run a browser headful
(`xvfb-run` on a Linux host with no X session; on macOS, the agents' user logged in
at the console), and the driver's own dependencies installed
into `signin_driver/`. Run `installation/check` at any point; it prints exactly what
is still missing, and `installation/check --online` installs the driver half.

**The driver's dependencies are per-TREE, not per-host.** `signin_driver/node_modules`
and `signin_driver/browsers` are gitignored, so a fresh clone *and every fresh
worktree* has the source without the install, however green `.install-state.json` is
for this host. `check` measures them in the fleet tree it is run from, which is why a
recorded host can still report STALE - and that reading is about the TREE, not the
branch. On a fleet host, `fleet install` and `fleet upgrade` install them into the
host checkout.

The commands below run from this skill's directory in the fleet tree. `config.json`,
`CONTEXT.md` and `installation/.install-state.json` are the INSTALL's files: they
live in the skill's install context, `<install root>/.claude/skills/agent-revive/`,
which `fleet where agent-revive` prints.

## 1. Point the config at your fleet

```
CTX="$(fleet where agent-revive)"
mkdir -p "$CTX/installation"
install -m 644 config.example.json "$CTX/config.json"   # then edit it
```

`install -m 644`, not `cp`: the fleet tree is read-only and `cp` keeps that mode.

Replace every placeholder in that `config.json`:

- `fleet.agents_home` - the directory your agents live under (each agent is
  `<agents_home>/<name>`).
- `fleet.tmux.tmpdir` / `fleet.tmux.target` - how this fleet names each agent's tmux
  socket dir and session (with `<agent>` and `<uid>` substituted). With `TMUX_TMPDIR`
  set to the socket dir, tmux resolves the socket at `<tmpdir>/tmux-<uid>/default`.
  The socket dir is a fallback: an agent whose unit can be read is reached at the
  unit's own `TMUX_TMPDIR`. `/run/user/<uid>/claude-tmux-<agent>` for agents run as
  user units (the fleet's template), `/run/claude-tmux-<agent>` for system units.
- `fleet.systemd_unit` - the service unit name pattern; `--bootstrap-prompt` reads
  the bootstrap prompt out of this unit's `ExecStartPost`.
- `accounts.pool_file` - the absolute path to the fleet's Claude account pool, a
  JSON list of `{ username, password, token_file, home_agent }`, mode 0600, outside
  this tree; its shape is `secrets/claude-account-pool.example.json`. This skill
  never contains a credential. Accounts enter it only through agent-health's
  `pool_pick.py --register <username> --token-stdin` (or `--password-stdin`), which
  reads the credential from standard input and creates the pool, the lease file and
  the usage ledger the first time (SKILL.md step 5, "Adding an account to the
  pool").
- `accounts.lease_file` - the absolute path to the lease file,
  `{ "<username>": { "agent", "since" } }`. `--register` creates it as `{}`; then
  one `pool_pick.py --take <account> --agent <agent>` per agent already signed in
  (`tmux_triage.sh <agent> --current-account` names its account); after that only
  `pool_pick.py --take` writes it.
- `accounts.handover_ledger_file` (optional) - the handover ledger `--take` and
  `--record` append to, under the reviving agent's home.
- `accounts.tokens_dir` (optional) - where `--register --token-stdin` writes the
  account tokens; default `claude-account-tokens` beside the pool file.
- `accounts.ledger_file` - agent-health's usage ledger (`parse_usage.py --init`
  creates it).
- `accounts.exclude` - `{ username, reason }` for every pool account no pick may name.
- `accounts.profiles_dir` - the absolute path for the stored sign-in profiles, one
  per pool account, beside the pool file in the organization secrets. The driver
  refuses one inside a git work tree or under an agents home, and creates it mode
  0700 at the first enrollment (SKILL.md, "Stored profiles"), so it need not exist.
- `share.*` - the tap-to-solve share (SKILL.md step 7): the local VNC and noVNC
  ports, a Funnel port the tailnet lets this node use and nothing else on the node
  serves, where noVNC is installed, the page the link opens, the default minutes, and
  the tailscale command as an argv array (`["sudo", "-n", "tailscale"]` where the
  agent's user is not the tailscale operator). `config.example.json` explains each.

`CONTEXT.md`, in the same install context, records the concrete values chosen for
this install, and names who performs the real-browser sign-in - one person, or an
ORDER of people with a timeout between them. The pool picker (agent-health's
`pool_pick.py`) and the recovery-code minter (google-spreadsheet's `gsheets.py`) are
the sibling skills in the fleet tree; they are not configured here.

## 2. Make sure tmux and jq are present

```
sudo apt-get install -y jq                  # Debian/Ubuntu; tmux is already present
```

## 2b. Install the sign-in driver

```
bash installation/check --online            # npm ci + the browser, into signin_driver/
```

Or by hand, which is the same two commands:

```
cd signin_driver && npm ci
PLAYWRIGHT_BROWSERS_PATH="$PWD/browsers" npx playwright install chromium
```

`xvfb-run` is needed on a Linux host with no X session (`sudo apt-get install -y
xvfb`). **Headful is a requirement, not a preference**: Google rejects a headless
browser at the identifier step, so a host with neither `DISPLAY` nor `xvfb-run` has
no automated route and every revival there falls back to SKILL.md step 7e. On macOS
the browser draws through WindowServer, which exists for the agents' user only while
that user is logged in at the console: automatic login for that user is what keeps
the automated route available after a reboot.

## 2c. Install the tap-to-solve share

Linux only. On macOS there is nothing to install: the share needs an X11 display
for x11vnc, `share` exits 2 there naming SKILL.md step 7e, and `installation/check`
reports the share as not on macOS without counting it against the install. The
config's `share` block is not needed on macOS.

```
sudo apt-get install -y x11vnc novnc websockify     # Debian/Ubuntu
```

and Tailscale, with Funnel allowed for this node and `share.funnel_port` in the
tailnet policy, and the agent's user able to run `share.tailscale` unattended - a
`sudo -n` grant for `tailscale`, or `sudo tailscale set --operator=<user>` and a
plain `["tailscale"]`. `installation/check` runs x11vnc and websockify, reads noVNC's
page, and asks tailscale - through that same command - for this node's name and its
funnel capability. Without the share, the human step falls back to SKILL.md step 7e.

## 3. Record the install

Write `installation/.install-state.json` in the install context (`$CTX` above),
keyed by host, so `check` can tell installed-and-current from stale on every machine
the committed file travels to. The shape is `hosts` -> this host -> its record, and
the version comes from `SKILL.md`'s frontmatter:

```bash
python3 - SKILL.md "$CTX/installation/.install-state.json" <<'PY'
import json, re, socket, sys, time, pathlib
skill, state = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
v = int(re.search(r"^version:\s*(\d+)$", skill.read_text(), re.M).group(1))
doc = json.loads(state.read_text()) if state.exists() else {}
doc.setdefault("hosts", {})[socket.gethostname()] = {
    "version": v, "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "by": "INSTRUCTION.md"}
state.parent.mkdir(parents=True, exist_ok=True)
state.write_text(json.dumps(doc, indent=2) + "\n")
print("recorded version", v, "on", socket.gethostname())
PY
```

Then run `installation/check` and confirm it exits 0. Its verdict covers the
config's credential paths too: an `accounts.pool_file` that does not exist yet
keeps it from 0 whatever the record says.

## 4. Run the test

```
bash tmux_triage.test.sh
node signin_driver/redaction.test.mjs
node signin_driver/profiles.test.mjs        # needs the driver install from step 2b
node signin_driver/share.test.mjs           # needs 2b and 2c; makes nothing public
```

All offline and all must pass. `profiles.test.mjs` runs real browsers on a fake pool
and a temp profiles dir, loading nothing beyond `data:` URLs and a server it runs on
127.0.0.1; on a tree without the driver install it exits 3, NO VERDICT.
`redaction.test.mjs` needs no `node_modules` at all - that is deliberate, so the
guard on an agent's password runs on every clone rather than only where the browser
install finished. It exits **3 = NO VERDICT**
when one of its own controls misbehaves; 3 is not a smaller pass.

`tmux_triage.test.sh` is offline and must pass. It covers the pane classification, the wrapped-URL join (and
proves a naive grep would truncate), the bootstrap-prompt extraction, the pool table
`--accounts` renders from the real pool picker, the current-account lookup and its config-dir
resolution order, and the assertion that no password ever reaches the output. The
sign-in itself is a human real-browser step, and an account switch drives a live
session's keystrokes; neither is exercised by this test. A green run means the
scripted read-only parts behave - not that any agent can be revived or switched.
