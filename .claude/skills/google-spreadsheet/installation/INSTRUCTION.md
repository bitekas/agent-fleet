# Installing `google-spreadsheet`

Five steps. When they are done, `installation/check --online` exits `0`.

**The install has two halves and they are installed separately.** Step 1 is
machine-wide (a Python package). Steps 2 to 5 are **per agent** (one key file,
one config, one delegation grant, one record) and need the agent's home, which
is why `.install-state.json` is keyed by host and then by agent. A working
install for one agent says nothing about another.

**Two of the five steps are not yours to perform.** The delegation grant and the
API enablement happen in consoles that only an administrator can reach. Plan for
that rather than discovering it at the last step.

The commands below run from this skill's directory in the fleet tree.
`config.json`, `CONTEXT.md` and `installation/.install-state.json` are the
INSTALL's files: they live in the skill's install context,
`<install root>/.claude/skills/google-spreadsheet/`, which
`fleet where google-spreadsheet` prints.

---

## 1. The Python dependency

```
python3 -m pip install -r installation/requirements.txt
```

**PyJWT alone is not enough and its absence is invisible.** `import jwt`
succeeds without the cryptography backend, and the first RS256 signature then
dies with `NotImplementedError: Algorithm 'RS256' could not be found` from
inside the first real call - which reads as a broken helper rather than a
missing package. That is why the requirement names the `[crypto]` extra
explicitly, and why `check` SIGNS rather than importing.

## 2. Get a service-account key for the agent

A Google Cloud service account, in any project of the organization, with a JSON
key downloaded. The `client_email` inside it ends `gserviceaccount.com`.

Install it where `credential.key_path` will resolve, with the mode set in the
same command so it is never briefly world-readable:

```
install -m 0600 <downloaded>.json <the path credential.key_path resolves to>
chmod 0700 <the directory holding it>
```

**It is a live credential that signs as a person.** It never goes in this
skill's tree, never into the repository, and never into a config file - only its
PATH does.

## 3. Have an administrator grant domain-wide delegation

**A Workspace administrator**, in the Admin console: Security > API controls >
Domain-wide delegation > Add new. It takes two things:

- the service account's **numeric client id** (the `client_id` field of the key
  file, not the email);
- the **exact scope list** the agent needs.

**Name read and write scopes separately, and ask for what is actually
needed.** A grant that lists a read-only Drive scope produces an agent that can
read and list and cannot share, trash or delete - **including its own files** -
and the refusal looks exactly like a missing share. A scope the entry does not
list mints nothing, whatever the key could otherwise do.

**Also have the APIs enabled on the project that issued the key** (Sheets,
Drive). A missing enablement arrives as a `403` at call time, which is the same
status as a missing share and a different repair entirely.

## 4. Write `config.json`

```
CTX="$(fleet where google-spreadsheet)"
mkdir -p "$CTX/installation"
install -m 644 config.example.json "$CTX/config.json"
```

`install -m 644`, not `cp`: the fleet tree is read-only and `cp` keeps that
mode.

Then fill in `identity.agent`, `identity.subject_template`,
`credential.key_path`, the two `api` bases and the `scopes` **the grant in step
3 actually lists**. Every key is required; a missing one is a startup failure
naming it.

Prove the identity before trusting anything else:

```
./gsheets.py whoami
```

It mints a token and **compares** the identity Drive reports with the one asked
for. A wrong `subject_template` mints perfectly and acts as somebody else, so
this comparison - not the mint - is the proof.

## 5. Record the install

Add this host and this agent to `installation/.install-state.json` in the install
context (`$CTX` above). The shape is `hosts` -> this host -> the agent -> its
record, the agent being `$GSHEETS_AGENT` or else `identity.agent`, the name
`check` looks the record up by; the version comes from `SKILL.md`:

```bash
python3 - SKILL.md "$CTX/config.json" "$CTX/installation/.install-state.json" <<'PY'
import json, os, re, socket, sys, time, pathlib
skill, cfg, state = (pathlib.Path(p) for p in sys.argv[1:4])
agent = os.environ.get("GSHEETS_AGENT") or json.loads(cfg.read_text())["identity"]["agent"]
v = int(re.search(r"^version:\s*(\d+)$", skill.read_text(), re.M).group(1))
doc = json.loads(state.read_text()) if state.exists() else {}
doc.setdefault("hosts", {}).setdefault(socket.gethostname(), {})[agent] = {
    "version": v, "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "by": "INSTRUCTION.md"}
state.parent.mkdir(parents=True, exist_ok=True)
state.write_text(json.dumps(doc, indent=2) + "\n")
print("recorded", agent, "version", v, "on", socket.gethostname())
PY
```

**Add, never replace.** The file is committed and travels to machines that never
ran this procedure; each machine and each agent records only itself, and
overwriting another entry un-installs that agent as far as `check` is concerned.

Then:

```
installation/check --online
```

---

## Uninstalling

Remove the key file, remove this host's entry from `.install-state.json`, and
ask the administrator to remove the delegation entry. **The grant is the part
that matters**: it outlives the key file and any new key for the same service
account inherits it.
