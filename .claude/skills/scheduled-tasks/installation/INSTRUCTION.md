# Installing `scheduled-tasks`

Step 1 is install-wide, once. Steps 2 to 5 are **per agent that is to own
schedules**, and need that agent's home; step 5 is also redone once per machine.
When they are done, `installation/check` exits `0` for that agent.

Below, `<home>` is the agent's home directory, `<agents-root>/<agent>`. The
daemon's config and database live in it, at the paths the scheduler's unit
reads (`systemd/README.md` in the fleet tree, "What runs"):

| File | Path |
|---|---|
| config | `<home>/config/scheduler.json` |
| database | `<home>/state/scheduler/tasks.db` |

**Dependencies: none beyond the fleet.** `sched.py`, `sched.test.py` and `check` are
Python 3 standard library plus the fleet's own `lib/fleetlib`, which arrives with the
fleet tree, so there is no `requirements.txt` beside this file. The one thing to
confirm is that `zoneinfo` resolves a real zone name -
`python3 -c "from zoneinfo import ZoneInfo; ZoneInfo('Europe/Berlin')"` - which
on a normal Linux or macOS host comes from the system `/usr/share/zoneinfo` and needs no
pip package. A minimal container without it needs `tzdata`; `check` reports an
unresolvable zone rather than letting every wall-clock schedule be silently wrong.

**What is actually being installed is one agent's schedule store**, not code. The
scripts arrive with the repository. The config and the database do not, because
they are per agent and per machine, so `check` reports per agent rather than per
checkout.

**Installing is not arming.** Nothing in this procedure starts a daemon, and a
provisioned scheduler that is never started fires nothing, for ever, silently.
Running the daemon as a service and arming its follower are `SKILL.md` section 8
(the install's `CONTEXT.md` names its unit), and `check` reports the arming state as
information without failing on it.

---

## 1. Decide how many schedulers this deployment runs, and write it down

The choice is **one shared scheduler, or one per agent**, and it is not a detail:

- **One** means a single owner, a single database, and every other agent's daemon
  refusing quietly at the owner guard. Simple, and correct where one agent holds
  the conversations.
- **One per agent** means each agent owns its own schedules and its own database,
  and no agent can see another's. That is the right shape where several agents
  hold separate conversations, and it is why nothing here assumes a single owner.

Record the answer in this skill's `CONTEXT.md` in the install context (`fleet where
scheduled-tasks CONTEXT.md` prints the path), in words, with the agents
that have a scheduler and the ones that deliberately do not. `check` will not tell
you: it reports the agent that invoked it and says so in its own output, because a
roster in code is a second copy of `CONTEXT.md` that goes stale with nothing going
red.

## 2. Create the directory, 0700

The database holds every schedule the agent has ever been given, and predicates
run **in the daemon's process** - `SKILL.md` section 13 is explicit that the AST
allow-list is not a security boundary and that the modes are what make it
acceptable. So the mode is load-bearing, not hygiene.

```bash
install -d -m 700 <home>/state/scheduler
```

It is in the agent's `state/` (`/agent` section 3), where durable per-agent
state lives. **Not under a cache directory** - a cache is a place things get
deleted from - and **not inside the directory the harness owns and sweeps**.

## 3. Create the config, 0600

Write a file holding the three keys `sched.py` refuses to start without, and
nothing else:

```bash
install -m 600 /dev/null <home>/config/scheduler.json
```

```json
{
  "owner": {"claude_config_dir": "<home>/.claude"},
  "db": {"path": "<home>/state/scheduler/tasks.db"},
  "defaults": {"tz": "<an IANA zone, such as Europe/Berlin>"}
}
```

| Key | Value |
|---|---|
| `owner.claude_config_dir` | the `CLAUDE_CONFIG_DIR` of the agent that owns this scheduler. Realpath-compared on both sides, so a tilde and an absolute path work equally. |
| `db.path` | the database in the directory from step 2 - the lock is created beside it |
| `defaults.tz` | an IANA name. A wall-clock schedule is a LOCAL concept, and a daily 09:00 job running at 09:00 UTC in a Tokyo deployment is off by nine hours with nobody getting an error about it. |

`config.example.json` beside `sched.py` carries every key with its default and
its explanation; it is the reference for a tunable, not a file to copy.

Nothing here names a chat transport: which transports an origin may use, and the id
shapes each one checks, come from the fleet's transport registry (each working
transport skill's `transport.json`).

And `requester.directory_file` / `requester.directory_key`, if this deployment has a
roster that maps a chat user id to a display name - point them at that roster's own
file rather than copying it, so there is one roster on the machine. Without them a task
row still records who asked, but the caller must pass the display name: `add` REFUSES an
id-shaped `--requester` it cannot resolve rather than storing an id nobody can read.

**These two are OPTIONAL and outside what the skill `version` tracks**, so an
existing install owes no re-install for them. Adding them to a config that
lacks them is a one-line edit made whenever that agent wants id resolution, not a
provisioning step - and `check` verifies them by actually performing the lookup, so a
config that declares them and cannot resolve them reports STALE rather than OK. Set both
or neither: one alone resolves nothing and `check` refuses it.

**Leave every other key out.** The three above, and `requester` if you have a roster,
are the only ones with no sensible default; everything else keeps the value
`config.example.json` shows, which is `sched.py`'s own default, and a copied value
is a copy that drifts - one place to change a tunable, not one per agent. A
tunable an agent genuinely needs different is the one key added to its file.

**Do not point `SCHED_CONFIG` at `config.example.json` itself.** Its
`owner.claude_config_dir` matches no agent and its `db.path` is a literal
placeholder, so a daemon on it arms against nothing and reports nothing. `check`
refuses an unedited copy for the same reason, and `sched.test.py` pins it.

## 4. Point `SCHED_CONFIG` at it

`sched.py` resolves its config **at import**, from `SCHED_CONFIG`, with a fallback
beside the script that deliberately does not exist. So the variable must reach
every process that runs `sched.py` for that agent - the daemon and the CLI alike -
and every one of them must name **the same file**.

**Two files is the failure this design cannot catch.** A launcher that exports
`SCHED_CONFIG` (or `SCHED_DB`) inconsistently gets two daemons, two databases and
every task firing twice, with nothing anywhere reporting it, because each daemon is
behaving correctly against the database it was told about. `sched.py doctor` prints
the resolved config and database; it is the only thing that proves which one a
session is actually talking to.

**The units set it, and both derive it from the home.** The scheduler's unit,
`agent-sched@<agent>`, sets `SCHED_CONFIG=<home>/config/scheduler.json`, and the
agent's own system unit sets the same value for the session, so the daemon and every
CLI call the session makes read one file. A shell that runs `sched.py` as that agent
by hand exports the same path. The install's `CONTEXT.md` records any agent whose
scheduler is set up differently.

## 5. Record the install

`check` compares `installation/.install-state.json` in the install context against the
`version` in `SKILL.md`. Without it, an install cannot be told from a stale one, so
`check` reports stale. Run the block below from this skill's directory in the fleet
tree (it reads `SKILL.md` there) **as the agent**: with `SCHED_CONFIG` set to the
agent's config and `CLAUDE_CONFIG_DIR` set to `<home>/.claude`. It asks `fleet where`
for the state file's path, and from the fleet tree `fleet where` finds the install
through `CLAUDE_CONFIG_DIR`; without it the block stops at `fleet where`, exit 3.

It is a **specific** file and is committed like any other, so it reaches machines
that never ran this procedure and agents that have no scheduler. It records
**per host, then per agent** - a single flat record would make every other machine
and every other agent read as installed, and re-recording one would un-record the
one before it.

```bash
python3 - <<'PY'
import json, os, pathlib, re, socket, subprocess, time
f = pathlib.Path(subprocess.run(
    ["fleet", "where", "scheduled-tasks", "installation/.install-state.json"],
    capture_output=True, text=True, check=True).stdout.strip())
f.parent.mkdir(parents=True, exist_ok=True)
cfg = json.load(open(os.environ["SCHED_CONFIG"]))
agent = cfg["owner"]["claude_config_dir"]
v = int(re.search(r"^version:\s*(\d+)$",
                  pathlib.Path("SKILL.md").read_text(), re.M).group(1))
doc = json.loads(f.read_text()) if f.exists() else {}
doc.setdefault("_comment", [
    "What was actually installed, per host and then per agent. Written by",
    "installation/INSTRUCTION.md step 5, read by installation/check.",
    "Committed, so it reaches machines that never ran the procedure - which is",
    "exactly why it is keyed by host, and why each machine records only itself.",
])
doc.setdefault("hosts", {}).setdefault(socket.gethostname(), {})[agent] = {
    "version": v,
    "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "by": "INSTRUCTION.md",
}
f.write_text(json.dumps(doc, indent=2) + "\n")
print("recorded", agent, "version", v)
PY

./installation/check     # expect: OK: installed and current (version N), ...
```

Repeat steps 2-5 for each further agent. Step 5 is also the step to redo on a new
machine, after steps 2-4 there.

**Adopting this skill from another deployment: empty `hosts` in
`.install-state.json` first.** It is committed, so a clone arrives carrying the
previous deployment's hosts and agent identifiers. `check` handles that correctly -
it reports stale and names the record step - but until it is cleared, its message
quotes somebody else's agent paths at your operators, which reads as a
misconfiguration of yours.

---

## Verifying the scripts themselves

```bash
python3 sched.test.py    # offline, no install needed - must print ALL CHECKS PASSED
```

It forces `SCHED_CONFIG` at `config.example.json` and drops `SCHED_DB` before it
imports `sched.py`, so it is hermetic: it cannot be pointed at a live database by
whatever environment happened to run it, and it passes identically on a machine
with no install at all. Every temporary database it opens is in a temp directory.

## Verifying a real config before trusting it

```bash
SCHED_CONFIG=<home>/config/scheduler.json python3 sched.py doctor
```

`doctor` prints the resolved config, the database and whether a daemon is armed.
**Read the resolved values, not the fact that it exited 0** - a config that
resolves to the wrong database resolves perfectly.

Then dry-run a real predicate before anything is scheduled on it, across a DST
boundary for anything on a wall clock:

```bash
python3 sched.py simulate --predicate-file p.py --start <a date near a DST change> --days 6
```

## Reading `check`'s exit codes

| Exit | Meaning |
|---|---|
| `0` | installed and current **for the agent that invoked it**. Never a statement about any other agent. |
| `1` | the artifacts are there but something is wrong. The printed line says which, and distinguishes a version or record problem - redo step 5, or the whole procedure - from a mode, timezone or database problem, which re-installing will not fix. |
| `2` | not installed for this agent: no `SCHED_CONFIG`, no config file, a config that does not parse or is missing a required key, an unedited example, or no database directory. |

## Re-installing after a version bump

`check` exits `1` when `SKILL.md` declares a version newer than the recorded one.
Re-read this file from the top: a bump means something here changed, and the only
way to know what is to walk it. Then redo step 5 for each agent on this machine.

**The version tracks this procedure, not the prose.** A change to how a predicate
is written changes no artifact on disk and bumps nothing; a change to what a
config must contain, or where the database goes, does.
