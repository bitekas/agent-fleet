# Installing `notion-workspace`

Six steps. When they are done, `installation/check --online` exits `0`.

**Two directories.** The skill's own files (`SKILL.md`, `installation/check`,
this procedure) live in the fleet tree; every command below names them through
`CLAUDE_SKILL_DIR`, which a `SKILL.md` load substitutes and this file does not,
so set it once. The install's files (`config.json`, `CONTEXT.md`,
`installation/.install-state.json`) live in the skill's **install context**,
which `fleet where notion-workspace` prints; call it `CTX`:

```bash
CLAUDE_SKILL_DIR=<the directory holding this skill's SKILL.md>
CTX=$(fleet where notion-workspace)
```

**Dependencies: none.** `check` is Python 3 standard library plus the fleet's
own library, which is why there is no `requirements.txt` beside this file. Everything else in the skill is
`curl` and the MCP tools the client already has.

**Two legs, and they install separately.** Path 1 is the hosted MCP connector,
installed in the client. Path 2 is the integration token, installed on disk. A
working path 2 says nothing about path 1, and `check` reports them separately
for that reason.

---

## 1. Connect the hosted MCP connector (path 1)

In the client that will use this skill, connect its Notion connector and
authorize it **against the workspace this skill is for**. It authenticates as a
**person**, so everything the MCP writes is attributed to whoever authorizes it
here. Choose that account deliberately.

Confirm it, in-session, with the only instrument that can:

```
notion-fetch {"id": "self"}
```

It returns the workspace name and id and the authenticated user. **Compare them
against `workspace.id` and `mcp.acts_as.user_id` in `config.json`** (step 3).
Nothing on disk can do this for you: the binding is an account-level OAuth grant
with no artifact, which is why `check`'s MCP leg reports "ever connected" and
never "connected now".

**A connector authorized against the wrong workspace is the worst outcome
available in this skill**, and it is silent: reads come back plausible, writes
land somewhere nobody in the project will look. Do this comparison before the
first write, not after.

## 2. Obtain the integration token (path 2)

The token belongs to a **Notion integration** owned by a person in the
workspace. Two kinds exist and one of them may be unavailable to you:

- **An internal (token-based) integration** gives you a token directly from its
  settings page. Simplest, when the workspace allows it.
- **An OAuth integration** is required where the workspace **blocks internal
  integrations**. There the token comes out of the OAuth exchange
  (`SKILL.md`, The OAuth exchange) after the integration is installed to the
  workspace. A hand-made internal token in such a workspace returns
  `unauthorized` no matter how correct it looks, so check which kind you need
  before debugging a token.

`CONTEXT.md` records which kind this install has.

Then **share the pages and databases the integration needs with it** from
Notion's UI. An integration reaches nothing by default; its reach is whatever
was shared, and it can end up much wider than the one database you came for.

Put it on disk in a file of its own, never in a config file and never in a
document:

```bash
install -m 600 /dev/null <token path>
printf '%s' 'ntn_...' > <token path>
```

The path is yours to choose and must be readable by the user that runs the
recipes. **Put it outside any checkout**: a path inside one is a different file
in every worktree, so the credential is missing from all but one of them, and
one stray `git add` publishes it. `check` asserts mode `600` on it and refuses to
report OK on an over-permissive credential.

**Optional, and only needed to re-authorize later:** the OAuth client
credentials, as a JSON file carrying `clientId`, `clientSecret` and `code`, also
mode `600`. Take them from the integration's settings page.

## 3. Create `config.json`

```bash
mkdir -p "$CTX" && install -m 644 "${CLAUDE_SKILL_DIR}/config.example.json" "$CTX/config.json"
```

`install -m 644`, not `cp`: the fleet tree is read-only and `cp` keeps that
mode. Then replace **every** placeholder. The `_comment` keys in the file say what
each value is and how to obtain it, including what is deliberately NOT a key;
nothing reads them, so keep or delete them.

**A `config.json` whose key names do not match `config.example.json` fails
LOUDLY, naming the key that could not be resolved.** That is why a key-name
change does not move `SKILL.md`'s `version`: `version` exists to catch the state
where everything still runs and the behaviour is silently the old one, and an
unresolvable key name is never that state - it stops before anything runs.
Measured: `NOT INSTALLED: config.json is missing token.path`.

Every identity value comes from one of two calls, so read them rather than
typing them:

```bash
# path 2's own answer: workspace name/id, bot name/id, bot owner, upload ceiling
T=$(cat <the token file from step 2>)
curl -sS https://api.notion.com/v1/users/me \
  -H "Authorization: Bearer $T" -H "Notion-Version: 2022-06-28"
```

```
# path 1's answer: workspace name/id, and the PERSON the connector acts as
notion-fetch {"id": "self"}
```

Three that are easy to get wrong:

- **`workspace.name` / `workspace.id`** are enforced against the live token by
  `check --online`. A wrong value there is refused rather than used, because the
  alternative is an agent quietly serving a different workspace.
- **`mcp.acts_as.*`** is the connector's **person**, not the bot. It is the only
  block no shell can verify; `self` is what verifies it.
- **`oauth.redirect_uri`** must be the exact value registered with the
  integration, or `null`. Do not guess one: an exchange attempted with a wrong
  or missing `redirect_uri` **revokes the authorization code**, and every retry
  afterwards reports "code has been revoked", which sends you debugging the
  wrong thing.

## 4. Write `CONTEXT.md`

In `$CTX`, beside `config.json`.

`config.json` is what a script reads; `CONTEXT.md` is what the agent reads.
Nothing enforces it, which is exactly why it has to be written by hand: a wrong
value here fails silently as bad judgement rather than loudly as an error.

It has to answer, at minimum: **whose workspace this is and which project it
serves**; who the MCP path writes as and who the token path writes as, and
therefore what a write's attribution will look like; where the credential files
live and which ignore rule covers them; which integration kind this install has
and why; what the token was verified to reach; the measured snapshots with their
dates (the per-tool access map, the upload ceiling); which agents may use the
surface and whose charter governs a request.

**Lead it with the wrong-workspace risk.** It is the failure mode that no code
path in this skill can catch.

## 5. Verify both legs

```bash
"${CLAUDE_SKILL_DIR}/installation/check"            # offline: artifacts, modes, MCP record, version
"${CLAUDE_SKILL_DIR}/installation/check" --online   # plus one live identity compare against the API
```

`--online` is the one instrument that catches `config.json` and the key file
having drifted apart. Offline, the identity keys are unverified and the line
says so rather than implying they passed.

Then the leg no script can reach:

```
notion-fetch {"id": "self"}     # compare against workspace.id / mcp.acts_as.user_id
```

A line beginning `NO VERDICT` is neither a pass nor a failure: it means the
check could not measure that leg. Read what it names before deciding anything.

## 6. Record the install

`check` compares this file against the `version` in `SKILL.md`. Without it, the
install cannot be told from a stale one, so `check` reports stale.

It is a **specific** file and is committed like any other, so it reaches
machines that never ran this procedure. It therefore records the host it was
written on, and `check` reports stale anywhere else - run this step once per
machine.

**Write it only if the install genuinely IS current on this machine.** If a leg
is unfinished, leave the file absent and let `check` exit `2`; a state file
written ahead of the install is the one lie this design cannot detect.

```bash
python3 - "${CLAUDE_SKILL_DIR}/SKILL.md" "$CTX/installation" <<'PY'
import json, re, socket, sys, time, pathlib
here = pathlib.Path(sys.argv[2])
here.mkdir(parents=True, exist_ok=True)
v = int(re.search(r"^version:\s*(\d+)$",
                  pathlib.Path(sys.argv[1]).read_text(), re.M).group(1))
(here / ".install-state.json").write_text(json.dumps(
    {"version": v, "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
     "host": socket.gethostname(), "by": "INSTRUCTION.md"}, indent=2) + "\n")
print("recorded version", v)
PY

"${CLAUDE_SKILL_DIR}/installation/check" --online    # expect: OK: installed and current (version N), ...
```

---

## Re-installing after a version bump

`check` exits `1` when `SKILL.md` declares a version newer than the recorded
one. Re-read this file from the top: a bump means something here changed, and
the only way to know what is to walk it. Then redo step 6.
