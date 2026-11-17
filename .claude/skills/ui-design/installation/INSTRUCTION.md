# Installing `ui-design`

Three steps. When they are done, `installation/check` exits `0`.

**No step waits for an agent's home.** The install is one file, the design map
in this skill's `CONTEXT.md`, committed in the install repository: the same on
every host and for every agent.

**Two directories.** The skill's own files (`SKILL.md`, `installation/check`,
this procedure) live in the fleet tree; every command below names them through
`CLAUDE_SKILL_DIR`, which a `SKILL.md` load substitutes and this file does not,
so set it once. The design map lives in the skill's **install context**, which
`fleet where ui-design` prints when run from a checkout of the install; call it
`CTX`:

```bash
CLAUDE_SKILL_DIR=<the directory holding this skill's SKILL.md>
CTX=$(fleet where ui-design)
```

**There is no record step.** `check` reads the design map itself and prints
`SKILL.md`'s version instead of comparing a recorded one, because a committed
file that is the same on every host leaves a per-host record nothing to say
(the artifact form, `/claude-skill` section 3).

---

## 1. Obtain the values

Who gives which value, and the `SKILL.md` section each one serves:

- **The design file**: its key, and optionally its link. From whoever owns
  the file. The map writes the key first, as one word, then the link if there
  is one, in any form (`<key> https://...`, `<key> [name](https://...)`). Only
  the key is read; the link is for people and is never parsed.
- **The three stage pages and the scratch area, by id**: the page for 1
  drafts, 2 approved and ready to build, and 3 implemented and merged (section
  1), and the scratch area tooling writes go to (section 6). Each id is read in
  the design tool, where a page's or frame's link carries it, by anyone with the
  file open. Write the id, never the name: names move between nodes. An id
  written here is still resolved again, by id, at the start of each engagement
  (section 4); the map records where to look, not proof that the node is
  unchanged.
- **The two marks**, as literal text, from the design-file owner: the in-build
  mark a frozen frame wears until its work has landed, and the mark for a frame
  a new design supersedes or drops (section 2).
- **Where the screen-number registry lives** (section 3), from the design-file
  owner, in one of three forms, which is how the map writes it:
  - `doc <path>`: a document in the install repository, its path relative to
    the install root (the directory holding `.claude/fleet.json`);
  - `design <id>`: a page or frame in the design file, its id;
  - `link <url>`: another system, its link.
- **Who holds each role**: the design approver (what the product looks like),
  the design-file owner (the file itself: deletions, numbering) and the
  code-change authorizer (building it). From the install's owner. A name here
  says who holds the role; what that person may ask an agent for is still the
  agent's charter.
- **The install's own design-tool skills**, optional: their names, or `none`.
  They outrank `SKILL.md`.

**Where the install also takes definition-of-done, five of these values are
already in its `config.json`** (`fleet where definition-of-done config.json`):
copy them from there, never ask them a second time, and change the two files
together. `check` compares each pair and reports one that differs as NOT
INSTALLED.

| Design map row | definition-of-done `config.json` key |
|---|---|
| Design file | `figma.file_key` |
| Approved page | `figma.pages.incoming` |
| Implemented page | `figma.pages.current` |
| In-build mark | `figma.in_build_marker_prefix` |
| Superseded mark | `figma.deletion_marker_prefix` |

The Design file row's first word, its key, agrees with `figma.file_key`, and
a page id with its key, when they are the same with the spaces around them
ignored on both sides. A mark agrees only character for character, its
trailing space included, so the table writes a mark inside backticks with the
space before the closing backtick, and `check` reads every character between
the backticks as the mark.

## 2. Write `CONTEXT.md`

```bash
mkdir -p "$CTX"
test -e "$CTX/CONTEXT.md" || install -m 644 /dev/null "$CTX/CONTEXT.md"
```

Add this section to `$CTX/CONTEXT.md`, keeping whatever else the file says, and
replace every `<placeholder>`, copying the five values definition-of-done
holds from its `config.json` (step 1). Write a mark inside backticks, so a
trailing space survives as part of it: `check` reads every character between
the backticks. The first paragraph under the heading is the notice that `check`
parses the table: keep it beside the table.

```markdown
## Design map

`installation/check` of the `ui-design` skill reads this table by its row
labels. Keep each label exactly as written and the table under this heading: a
renamed label reads as a missing value, and a table it cannot find is NO
VERDICT.

| Value | Setting |
|---|---|
| Design file | <the design file's key, then optionally its link> |
| Drafts page | <id of page 1, drafts> |
| Approved page | <id of page 2, approved and ready to build> |
| Implemented page | <id of page 3, implemented and merged> |
| Scratch area | <id of the scratch area> |
| In-build mark | `<the in-build mark>` |
| Superseded mark | `<the mark for a superseded or dropped frame>` |
| Screen-number registry | <where the registry lives, in one of the three forms of step 1> |
| Design approver | <who holds the role> |
| Design-file owner | <who holds the role> |
| Code-change authorizer | <who holds the role> |
| Design-tool skills | <their names, or none> |
```

The labels are fixed, and `check` holds them to its own list. A row of the
install's own may be added below them; `check` reads only these.

## 3. Verify

```bash
python3 "${CLAUDE_SKILL_DIR}/installation/check"   # expect: OK: configured (version N) ...
```

Read its line, not only its code. `NOT INSTALLED` names every row still
missing, empty, a placeholder or repeated, a registry value in none of the
three forms, a `doc` registry it cannot open or that holds no text, and a value
that differs from definition-of-done's `config.json`. `NO VERDICT` means it
found no design map table it can read (it reads none inside code or an HTML
comment, and none whose rows have more than two cells: write a `|` inside a
value as `\|`), or that definition-of-done's `config.json` exists and cannot be
compared: not a pass. For `design` and `link` the OK line says the registry was
recorded, not opened: open it once yourself.

---

## Verifying the script itself

```bash
python3 "${CLAUDE_SKILL_DIR}/installation/check.test.py"   # offline, against copies of the fleet's fixture install
```

## After a version bump

A version that asks for a new value adds its row to the template above, and
`check` reports the row missing from an older map. Add the row; there is no
record to redo.
