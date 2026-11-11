# Installing `knowledge-base`

Four steps. When they are done, `installation/check` exits `0`.

**Dependencies: none beyond the fleet.** `check_indexes.py` is Python 3
standard library only; `check` adds the fleet's own `lib/fleetlib`. If
`python3` runs, the skill runs.

**What is actually being installed is the store**, not code. The scripts arrive
with the fleet; the store root does not, because it is a repository of its own,
outside the fleet and the install. That asymmetry is the whole reason this
procedure exists and is why `check` reports per machine rather than per
checkout.

**Two directories are named below.** `<skill dir>` is this skill's directory
(the directory the skill was loaded from), which holds the COMMON files.
`<context>` is this skill's install context, which holds the SPECIFIC ones -
`config.json`, `CONTEXT.md` and `installation/.install-state.json`:

```bash
CONTEXT=$(fleet where knowledge-base)
mkdir -p "$CONTEXT/installation"
```

---

## 1. Decide where the store lives, and write it down

Pick a directory that has no other purpose. Everything under it is read as
knowledge, so a path shared with anything else will be indexed as if it were
knowledge and will fail the checker forever.

**The store is its own git repository, never nested inside another
checkout.** Its commit log is where each fact's measurement and date live
(`SKILL.md`, "Committing a store write"), and a store inside another checkout
is a set of files that repository's commits and branches move under it. A
remote is optional: with one, the store reaches every machine that clones it;
without one, a second machine starts empty.

One property is worth deciding deliberately rather than inheriting:

- **Shared by every agent, or one per agent.** A store inside one agent's home
  directory is that agent's alone. A store beside them is the fleet's, and it
  then has concurrent writers - `SKILL.md`, "A store with more than one writer",
  is what an agent does about that.

Record the answer in `$CONTEXT/CONTEXT.md`, in words. `config.json` records the
path; `CONTEXT.md` records what kind of store it is, who shares it, what may and
may not be written in it, its remote and branch if it has one, and the commit
identity form an agent uses outside its service unit (`SKILL.md`, "A store with
a remote, and the author of a commit"). A wrong value in the first throws; a
missing sentence in the second fails silently as bad judgement.

## 2. Create `config.json`

```bash
install -m 644 "<skill dir>/config.example.json" "$CONTEXT/config.json"
```

`install -m 644`, not `cp`: the fleet tree is read-only and `cp` keeps that
mode.

Then set `store.root` to the absolute path from step 1. The `_comment` keys say
what the value is; they are documentation and nothing reads them, so keep or
delete them.

## 3. Create the store: the root, and its index

```bash
ROOT=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["store"]["root"])' "$CONTEXT/config.json")
mkdir -p "$ROOT"
```

Then create `$ROOT/index.md` from the fleet's empty-store root index, and edit
it to say what this store is, what belongs in it and what does not:

```bash
install -m 644 "$(realpath "<skill dir>/../../..")/templates/knowledge-store/index.md" "$ROOT/index.md"
git -C "$ROOT" init
```

`realpath` matters: `<skill dir>` is usually the agent's personal skill link,
and three directories above the link is the agent's home, not the fleet. The
root index lists no subfolders and no files on a fresh store, so both sections
are omitted rather than written empty; `templates/index.md` in this skill is
the shape every later folder index takes.

**Create nothing else.** No topic folders, no placeholder files. `SKILL.md`
states the rule and it applies to the store's own first minute: a folder is
created when there is something to put in it. A store scaffolded with empty
topics reports what someone once planned to learn instead of what is known, and
every one of those folders is a lie the index rule then obliges someone to
maintain.

Verify the store is a valid knowledge tree before recording anything:

```bash
python3 "<skill dir>/check_indexes.py" "$ROOT"      # expect: indexes clean: 1 checked under ...
```

## 4. Record the install on this machine

`check` compares this machine's record against the `version` in `SKILL.md`.
Without it, the install cannot be told from a stale one, so `check` reports
stale.

It is a **specific** file and is committed with the install like any other, so
it reaches machines that never ran this procedure and where the store therefore
does not exist. It keeps **one entry per host**, and this step adds or replaces
only this machine's entry - run it once per machine. A file holding a flat
single-host record is converted on the way, keeping that host's entry.

```bash
python3 -c '
import json, re, socket, sys, time, pathlib
skill, state = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
v = int(re.search(r"^version:\s*(\d+)$", (skill / "SKILL.md").read_text(), re.M).group(1))
old = json.loads(state.read_text()) if state.exists() else {}
hosts = old.get("hosts") or ({old["host"]: {k: x for k, x in old.items() if k != "host"}} if old.get("host") else {})
hosts[socket.gethostname()] = {"version": v, "by": "INSTRUCTION.md",
                               "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
state.write_text(json.dumps({"hosts": hosts}, indent=2) + "\n")
print("recorded version", v, "for", socket.gethostname())
' "<skill dir>" "$CONTEXT/installation/.install-state.json"

python3 "<skill dir>/installation/check"     # expect: OK: installed and current (version N) ...
```

---

## Verifying the scripts themselves

```bash
python3 "<skill dir>/check_indexes.test.py"         # offline, no store needed - must print ALL CHECKS PASSED
python3 "<skill dir>/installation/check.test.py"    # offline, against the fleet's fixture install
```

Both build throwaway trees in a temp directory and never touch the real store,
so they are safe to run at any time and prove their subjects can still fail:
every rule `check_indexes.py` enforces has a fixture that breaks exactly that
rule, and every state `check` reports has a case that produces it.

## Reading `check`'s exit 1

Exit `1` has three causes and the printed line names which:

- **a version or host problem** - no record for this machine, or a version
  behind `SKILL.md`'s: redo step 4, or the whole procedure if the version moved.
- **the store fails `check_indexes.py`** - an index does not match the directory
  it describes. Re-installing will not fix it. Fix the indexes, innermost first.
- **NO VERDICT** - no install context resolved, or `config.json` could not be
  read: the store was never looked at. The line names what was missing.

## Re-installing after a version bump

`check` exits `1` when `SKILL.md` declares a version newer than this machine's
record. Re-read this file from the top: a bump means something here changed,
and the only way to know what is to walk it. Then redo step 4.

**The version tracks this procedure, not the prose.** A change to what belongs
in a knowledge file changes no artifact on disk and bumps nothing; a change to
what a store root must contain does.
