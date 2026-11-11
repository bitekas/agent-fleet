---
name: safe-box
version: 1
description: >
  Take a secret from a person into a file on a fleet host without the value
  passing through the Claude session: a one-time web form on 127.0.0.1, which
  the person reaches through an SSH tunnel, writes each declared secret to its
  declared file at mode 600 and then exits. Load before asking a person for a
  token, key or password that must end up in a file on a host, and when an
  install or onboarding step offers the person the choice between pasting a
  secret into the session and typing it into a form.
requires_install: false
---

# safe-box

`safe_box.py` serves ONE form, on 127.0.0.1 only, for a list of secrets declared
when it starts. The person reaches it through an SSH local port forward, types a
code the session shows them and one value per secret, and submits once. Each
value is written to its declared file and the process exits.

**This skill needs no config and no install.** It is one Python 3 standard
library script plus the fleet's `lib/fleetlib`, which resolves the two
directories it may write into. Its test, `safe_box.test.py`, runs every check
against broken copies of the script as well, and each copy must fail the check
named for what it breaks.

---

## 1. Two ways in, both allowed

A step that needs a secret from a person offers both, says what each one does
with the value, and the person picks.

| | Paste into the session | safe-box |
|---|---|---|
| Where the value travels | Into the conversation: the session's transcript on the machine running the session, and the requests that session sends to the model. | The person's browser, their SSH tunnel, the host, the file. It never enters the conversation. |
| What the person needs | Nothing beyond the session. | An SSH login to the host and a browser on the same machine. |
| How the file is written | The session writes it with its file-writing tool, then sets mode 600. Never through a command line: a value on a command line is also in the process list and the shell history. | `safe_box.py` writes it, mode 600 from creation. |

safe-box takes single-line values only (section 7). A multi-line secret goes by
the paste route or as a copied file.

## 2. Declaring the secrets

Every secret is declared when the script starts, as `NAME=PATH`. The form shows
the NAMEs; nothing the browser sends can add a name or change a path.

- **NAME** matches `[A-Za-z0-9][A-Za-z0-9._-]*`, at most 64 characters. It is
  the label the person sees, so make it say what to paste: `slack-bot-token`,
  `notion-token`.
- **PATH** may start with `~`. A relative PATH resolves against the fleet
  secrets directory (`FLEET_SECRETS_DIR`, else the install manifest's `secrets`
  key: `/claude-skill` section 4).
- **Where a PATH may point.** After every symlink is resolved, it must lie under
  the fleet secrets directory, or under the personal-secrets directory of an
  EXISTING agent home, `<agents-root>/<agent>/secrets/personal/` (`/agent`
  section 3; `<agents-root>` is `agents_root` in the host settings file). An
  agent home is a directory of the agents root that holds the agent's Claude
  Code config directory, `<agents-root>/<agent>/.claude`, which the install
  creates; a knowledge store or the claims directory there is not one, and a
  path under it is refused. A credential issued to one agent goes in that
  agent's personal directory; the organization's go in the fleet secrets
  directory.
- **Refused at startup, exit 2, before anything is served:** a PATH with a `..`
  component (even one that stays inside a root), a PATH outside both roots, a
  symlink that leads out of them, a home's `secrets/` directory other than
  `secrets/personal/`, the personal directory of an agent home that does not
  exist, a name or a path declared twice, and a file that already exists unless
  the call passes `--replace`.

`--dry-run` checks all of that and prints what would be served and written,
names and paths only, without binding a port or writing anything. Run it first
when a path is new.

## 3. Starting it

Start it as a BACKGROUND command of the session, so the session keeps working
while the person acts, and read its output until the `SAFE-BOX READY` line
appears (section 4). The script ends by itself (section 6); its own
`--timeout` bounds it, and a `timeout` wrapper slightly longer is the backstop.
macOS has no `timeout` command, so on a macOS host the command starts at
`python3` and the script's own `--timeout` is its one bound.
`--ssh-host` is the host name the PERSON uses to log in to the host, which may
differ from the one the session uses; it goes into the printed tunnel command.

**The session runs on the host:**

```bash
timeout 660 python3 "${CLAUDE_SKILL_DIR}/safe_box.py" --timeout 600 --ssh-host <host> \
  slack-bot-token=<agents-root>/<agent>/secrets/personal/slack-bot-token   # linux-only: macOS has no timeout(1); there it starts at python3
```

**The session runs on another machine** and reaches the host over SSH:

```bash
ssh <host> 'cd <install checkout> && timeout 660 python3 <fleet>/.claude/skills/safe-box/safe_box.py \
  --timeout 600 --ssh-host <host> notion-token=notion.token'   # linux-only: a macOS host has no timeout(1); there drop "timeout 660"
```

`<fleet>` is `fleet_checkout` in the host's settings file
(`~/.config/agent-fleet/host.json`), and `<install checkout>` is the install's
checkout on that host: run from inside it, the fleet secrets directory resolves
through its manifest. On a host with no install yet, put
`FLEET_SECRETS_DIR=<dir>` before `timeout` instead. The single quotes keep the
local shell from expanding anything; the script expands `~` itself.

Flags: `--timeout SECONDS` (default 600, at most 3600), `--port PORT` (default 0,
a free port), `--max-refused N` (default 5), `--replace`, `--ssh-host HOST`,
`--dry-run`.

## 4. The ready line, and what the person is shown

```
SAFE-BOX READY port=<port> path=/<token>/ code=<XXXX-XXXX> expires=<YYYY-MM-DDTHH:MM:SSZ> names=<name>,<name>
tunnel: ssh -N -L <port>:127.0.0.1:<port> <ssh-host>
open: http://127.0.0.1:<port>/<token>/
```

The first line is the machine-readable one: split on spaces, then each field on
its first `=`. `<token>` is 192 random bits; the code is eight characters.
Show the person the `tunnel:` command, the `open:` URL and the code, in the
session. The URL and the code let whoever holds them SUBMIT values for the
declared names until the session ends, never read one; keep the script's output
where only the session sees it, never in a shared channel.

## 5. What the person does

1. In a terminal on their own machine, run the `tunnel:` command and leave it
   running. If that local port is taken, change the FIRST number to a free one
   and use the same number in the URL.
2. Open the `open:` URL in a browser on that same machine.
3. Type the code, paste each value into its field, press **Write**. The page
   then lists each name as written.
4. Close the page, and stop the tunnel with Ctrl-C.

A **404 after Write** means the code (or the URL) was wrong: go back, retype,
submit again. Every refused request counts, and the `--max-refused`-th ends the
session; the session then starts a new one. A person sitting at the host itself
skips step 1 and opens the URL there.

## 6. How it ends

| Last line | Exit | Meaning |
|---|---|---|
| `SAFE-BOX END complete written=<n>/<n>` | 0 | every declared secret is in its file |
| `SAFE-BOX END complete written=<k>/<n>`, k < n | 1 | the submission arrived; the `<name>: NOT written (<reason>) <path>` lines say which failed and why |
| `SAFE-BOX END timeout written=0/<n>` | 1 | nobody submitted within `--timeout`: nothing written |
| `SAFE-BOX END too-many-refused written=0/<n>` | 1 | `--max-refused` refused requests: nothing written |
| `SAFE-BOX END signal written=0/<n>` | 1 | stopped by SIGTERM, SIGINT or SIGHUP: nothing written |
| `safe-box: refused, nothing served or written: ...` on stderr | 2 | a declaration was refused at startup (section 2); a usage line instead means a flag was wrong |
| `safe-box: cannot listen on ...` on stderr | 3 | the port cannot be bound |

Each written file is reported as `<name>: written (<bytes> bytes) <path>`, never
with its content. Exit 0 says the file exists; that a consumer can USE it is
the consumer's own check, run next (the skill that needed the secret has one).

## 7. What it writes, exactly

- **The value as submitted, nothing added**: no trailing newline, no trimming,
  UTF-8.
- **A password field drops line breaks.** A token, a password or a JSON
  document survive it (JSON never needs a line break); a PEM private key does
  not.
- **Atomically, mode 600 from creation:** a temp file in the destination
  directory, created 0600, written, synced, then renamed into place
  (`--replace`) or hard-linked (otherwise, so a file that appeared after startup
  is never overwritten: its name is reported NOT written). Missing parent
  directories are created 700. Nothing is written anywhere else.
- **One submission per session.** It carries every declared name; a submission
  with an undeclared field, a missing field or a repeated field writes nothing.

## 8. Threat model

- **The network.** The listener is 127.0.0.1, never a wildcard, so no other
  machine reaches it. The person reaches it through their own SSH login, which
  authenticates them and encrypts the traffic; the form has no TLS of its own.
- **Other users of the host** can connect to a 127.0.0.1 port. They need the
  192-bit path and the code, which only the session's output holds; a wrong
  path, code or Host header is a 404 that counts, and the `--max-refused`-th
  ends the session.
- **The value's path.** Only the POST body carries it: never a URL (the form
  posts), a log line (the server's request log is off; each request is printed
  as method and status), stdout or stderr, a process argument, the environment,
  or a temp file outside the destination directory. Core dumps are off.
- **The destinations** are fixed at startup and confined, after symlink
  resolution, to the fleet secrets directory and the agents' personal-secrets
  directories (section 2).
- **Out of scope:** a process running as the same user or as root on the host,
  which can read the files themselves; and the person's own browser and machine.
