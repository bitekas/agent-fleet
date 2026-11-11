# Installing `agent`

Step 0 is install-wide, once; step 1 is per agent home. When both are done,
`installation/check` exits `0`.

**Dependencies: none beyond the fleet.** `check` is Python 3 standard library
plus the fleet's own `lib/fleetlib`, which is why there is no
`requirements.txt` beside this file.

**What is installed is a file, not code.** Everything else in this skill is
prose an agent reads. The one thing that has to exist on disk before the rules
can be followed is `blockers/blockers.md` under the agent's own home directory:
the blockers timer reads it, and an agent without it pings nobody, for ever,
while reporting zero blockers - which is indistinguishable from an agent who is
waiting on nothing.

**It is per agent home, not per machine.** Several agents share one host, each
with its own home, and each needs its own file. Run the check as the agent, so
it resolves that agent's home.

**Below, `<skill dir>` is this skill's directory** (the directory the skill was
loaded from), and the install's values are this skill's `CONTEXT.md` in the
install context, whose path `fleet where agent CONTEXT.md` prints.

---

## 0. Write the paths table in `CONTEXT.md` (install-wide, once)

`CONTEXT.md` in the install context maps each directory of `SKILL.md` section 3
to its path on this machine, as a Markdown table. `check` parses one row of it,
so that row has a fixed form: the label `home directory` in the first cell and
the path in backticks in the second. In a path, `<agent>` stands for the agent's
name and `<agents-root>` for `agents_root` in the host settings file; both are
substituted when the row is read. The fleet's default layout, which
`tests/fixtures/install/.claude/skills/agent/CONTEXT.md` also carries:

```markdown
## Paths

| What | Path |
|---|---|
| home directory | `<agents-root>/<agent>` |
| charter | `<agents-root>/<agent>/<project-dir>/.claude/agents/<agent>.md` |
| personal secrets | `<agents-root>/<agent>/secrets/personal` |
| organization secrets | `${FLEET_SECRETS_DIR:-~/.fleet-secrets}` |
| workspaces | `<agents-root>/<agent>/workspaces` |
| playground | `<agents-root>/<agent>/playground` |
| config | `<agents-root>/<agent>/config` |
| agent memory | `<agents-root>/<agent>/state/memory` |
| state | `<agents-root>/<agent>/state` |
| artifacts | `<agents-root>/<agent>/artifacts/<YYYY-MM-DD>/<artifact>` |
| blockers | `<agents-root>/<agent>/blockers/blockers.md` |
| project repository | `<agents-root>/<agent>/<project-dir>` |

`installation/check` parses the `home directory` row above by its label and
its backticked path.
```

Replace `<project-dir>` with the install checkout's directory name. Keep the
last sentence beside the table: relabel the row or drop its backticks and the
check stops measuring, and that sentence is what tells the next editor so. The
`home directory` row must also match the home-layout contract of `SKILL.md`
section 3 (the parent of the agent's `CLAUDE_CONFIG_DIR`, a direct child of the
agents root), or `check` reports that the resolved home does not match the
row.

## 1. Create the blockers file from the template (per agent home)

```bash
HOME_DIR=<the home directory the install's CONTEXT.md names for this agent>
install -d "$HOME_DIR/blockers"
install -m 644 "<skill dir>/templates/blockers.md" "$HOME_DIR/blockers/blockers.md"
```

Copy the template rather than writing a table by hand: its header comment is
what tells the next reader that the file is a scratchpad and not a ledger, and
its column set is what `check` compares an installed file against. **`install
-m 644`, not `cp`:** the fleet tree is read-only and `cp` keeps that mode, which
leaves a file the blockers timer cannot write to.

**Never overwrite an existing `blockers.md`.** It holds live rows - things other
people owe this agent - and they exist nowhere else. To pick up a new template,
copy the rows across into the new file first.

## 2. Prove it

```bash
python3 "<skill dir>/installation/check"     # expect: exit 0, "OK - ... installed"
```

`check` reads the install's `CONTEXT.md` through the fleet's install
resolution, resolves the agent's home from `CLAUDE_CONFIG_DIR` (falling back to
`$HOME`), confirms that path matches the shape the `home directory` row
declares (a `<agents-root>` token in it is the host settings file's
`agents_root`), then opens and reads the file. It exits:

| Exit | Meaning |
|---|---|
| `0` | installed, and its columns match the shipped template |
| `1` | installed but STALE (its columns differ from the template), or a leg it could not measure - no install context, an unparseable row - and the printed line says which |
| `2` | not installed: the file is absent, and the line carries the one-line fix |

### Prove the check can still fail

```bash
python3 "<skill dir>/installation/check" /tmp/no-such-agent-home   # expect: exit 1, NO VERDICT
mkdir -p /tmp/blockers-control && \
  python3 "<skill dir>/installation/check" /tmp/blockers-control   # expect: exit 2, NOT INSTALLED
rm -rf /tmp/blockers-control
```

The optional positional argument exists for exactly this, and it needs no
install context. A check that has never been seen to go red is a check nobody
can distinguish from one that passes unconditionally, and the only other way to
make this one fail is to break a real agent's home. `check.test.py` beside the
check runs these controls and the install-resolution cases offline; run it
whenever you change `check`.
