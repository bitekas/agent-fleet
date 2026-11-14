---
name: claude-skill
version: 2
description: >
  How a skill is written in this tree: the mechanism/values split that lets a
  skill be adopted elsewhere while the agent using it stays private, the
  file layout,
  the three-state install check that distinguishes stale from absent, the
  rule that machine state is discovered rather than written down, the dated
  temporary conventions that bend a skill until an end date or event and are
  then cleaned up and deleted, and the test that says a skill is finished.
  Load before writing a new skill, before restructuring an existing one,
  before adding a script or an install step to one, before writing or ending
  a temporary convention, and before moving one into the fleet repository.
requires_install: false
---

# claude-skill

The conventions every skill follows, in the fleet repository and in an
install's own tree. The install's `CONTEXT.md` for this skill (`fleet where
claude-skill CONTEXT.md`) names its local paths and who rules on open
questions.

The goal these rules serve: the fleet repository, agent-fleet, lets a stranger
reproduce this way of working and contains **no** trace of a particular
machine, company or person, while each install keeps everything specific to it
in its own repository.

---

## 1. The two rules everything follows

**1. A skill is a MECHANISM plus its VALUES, and they live in different files.**
The mechanism is **common**: identical everywhere, and what an adopter starts
from. The values are **specific**: filled in per install, and replaced wholesale
by whoever adopts the skill.

**2. A skill states HOW, never WHO or WHETHER.** Authority, tone, triage and
approval belong to the agent's charter. This is what lets one skill serve
several agents with different permissions, and it is why a skill can be public
while the agent using it is not.

---

## 2. Layout

```
<skill-name>/
  SKILL.md                  the mechanism, + version in frontmatter    COMMON
  config.example.json       every key, placeholder values, comments    COMMON
  config.json               real values for this install               SPECIFIC
  CONTEXT.md                the local human layer                      SPECIFIC
  override/                 local rules that bend behaviour            SPECIFIC
    README.md               what may and may not go in here            COMMON
  temporary/                dated conventions, deleted when they end   SPECIFIC
    <slug>.md               one convention: header, rule, cleanup      SPECIFIC
  installation/
    INSTRUCTION.md          how to install, step by step               COMMON
    check                   prints install state, exits 0/1/2          COMMON
    requirements.txt        packages, if any                           COMMON
                            only where the ecosystem puts its manifest here.
                            An npm-shaped skill's package.json and lockfile
                            live BESIDE the script, because that is where the
                            installer looks.
    *.service.example       system units, placeholdered                COMMON
    *.plist.example         their launchd form (macOS), placeholdered  COMMON
    .install-state.json     what was actually installed, and when      SPECIFIC
  <script>.<ext>            the executable                             COMMON
  <script>.test.<ext>       its test                                   COMMON
  <data>.example.<ext>      the example twin of a real dataset         COMMON
  fixtures/                 test data                                  COMMON

  ...elsewhere, outside the tree:
  <data>.<ext>              the real dataset, at a path config names    SPECIFIC
  <credential>              the real token, at a path config names      SPECIFIC
```

A skill that needs no config, no install and no scripts is `SKILL.md` alone.
**The layout is a contract about where a thing goes if it exists, not a
requirement that it exist.**

### SPECIFIC files live in the install context

**A skill's SPECIFIC files live in `<install root>/.claude/skills/<skill>/`,
never beside the mechanism.** The install root is the directory holding the
install manifest (`.claude/fleet.json`), resolved by the fleet's `fleetlib`;
`fleet where <skill> [<file>]` prints the path. For a skill whose COMMON files
live in the fleet, the two halves are in two repositories: the fleet's skill
directory holds COMMON files only, and a layout gate refuses a `CONTEXT.md`,
`config.json`, `temporary/` or `installation/.install-state.json` there. For a
skill that lives in the install's own tree, the install context IS its
directory, so the same rule puts both halves side by side.

- **A Python script reaches its SPECIFIC files through `fleetlib`**: it puts
  `<fleet root>/lib` on `sys.path`, where the fleet root is
  `Path(os.path.realpath(__file__)).parents[3]` for a script at
  `.claude/skills/<skill>/<script>`, and reads
  `fleetlib.paths.skill_context('<skill>')`. **`realpath`, never `abspath`**:
  an agent reaches a fleet skill through a personal skill link, and through the
  link `abspath(__file__)` is the link path under the agent's config directory,
  three parents above which there is no fleet.
- **A Node script reaches them through the shared `lib/fleet-where.mjs`**,
  loaded from the script's own realpath:
  `join(realpathSync(HERE), '..', '..', '..', 'lib', 'fleet-where.mjs')` for a
  script at `.claude/skills/<skill>/<script>`, never a static relative import,
  which resolves against the link path when symlinks are preserved. Its
  `configFile('<skill>', '<VAR>')` returns `$<VAR>` when set and otherwise asks
  `fleet where <skill> config.json`. A script never re-implements that lookup
  and never keeps its own copy of it.
- **A relative path inside a SPECIFIC `config.json` resolves against the base
  its key's `_comment` in `config.example.json` names**, because the value
  alone cannot say, and the wrong base names a file that is not there, or
  worse, one that is. A script resolves it through fleetlib, never against its
  own directory, and takes one of two bases. The config file's directory is
  the default (`fleetlib.paths.resolve_config_path`): a log, a state file, a
  dataset kept beside the config. A file in the install's REPOSITORY - a
  script the skill runs, a directory of the project's documents - resolves
  against the install root (`fleetlib.paths.resolve_repo_path`, whose default
  root is `fleetlib.paths.install_root()`), since the install context sits
  inside `.claude/skills/<skill>/` and a repository path written relative to
  it would have to climb out of it. A value an agent uses in its own session,
  rather than a script, may take another base when that is what it is for
  (the agent's state directory, its worktree), named the same way.
- **A test runs against the fleet's fixture install** (`tests/fixtures/install/`,
  synthetic values only), selected with `FLEET_CONTEXT_ROOT`, so it needs no
  real install to pass.

---

## 3. Each file

### `SKILL.md` - common

The mechanism: how it works, the calls it makes, the ordering rules, the traps
that cost something to learn.

**It names no host, person, email, absolute path, workspace, channel, id,
dataset or credential.** Where a concrete value is needed to explain something, it refers
to the config key - "the bot user id (`bot.user_id`)" - never to the value.

Frontmatter:

```yaml
---
name: <skill-name>
version: 3                 # integer, bumped on any change requiring a re-install
description: >
  What it does AND when to load it. The "when" is what makes it
  discoverable to an agent that has not read it yet.
requires_install: true     # false means there is no installation/ procedure
---
```

`version` is the load-bearing addition. Without it there is no way to
distinguish *installed* from *installed, but the old one*.

**With `requires_install: false` the version is inert: leave it at `1`.** Nothing
is installed, so nothing can be stale, and there is no `.install-state.json` for
it to be compared against. Bumping it on a rewrite looks like diligence and is
noise - a signal with no receiver, which later reads as evidence that something
needed reinstalling. **Bump it when the INSTALL PROCEDURE changes**, not when the
prose does; `git log` already records the prose.

**A `description` containing a colon must not be a plain scalar.** YAML reads
`description: What it does: and when to load it` as a nested mapping and fails
to parse, so the skill silently does not load - the frontmatter is the only part
of a skill that can break without anything printing an error. The trap fires
during an ASCII sweep, where the obvious substitute for an em dash is a colon.
Keep the separator ASCII as ` - `, or use the folded form `description: >` with
the text indented on the lines below. **The folded form is the safe default for
any description long enough to wrap**, and it is the only form that survives a
later punctuation edit unexamined.

**Every trap carries its reasoning.** A reader told *what* to avoid works around
that one instance; a reader told *why* recognises the next member of the same
class. State what the trap costs when it fires - a wrong asset that passes
review, days of red CI - because that is the part which makes a rule survive
being inconvenient; the incident that taught it belongs in the commit message.

### `config.example.json` / `config.json`

Every key the skill reads, with a placeholder and a comment saying what it is
and how to obtain it. **JSON has no comment syntax, so a comment is a `_comment`
key** - an array at the top of the file for the whole-file preamble, a string
inside each block for that block - which every loader strips and nothing reads.
Say it in the file rather than leaving each author to discover the convention by
reading two other skills. `config.json` is the same keys with real values, made by
copying the example. **The example is the install instructions in
machine-readable form**, and it is what makes the repo adoptable rather than
merely admirable.

**Placeholders are realistic but obviously fake, uniformly**: `acme.slack.com`,
`U0EXAMPLE99`, `/path/to/your/token`, `jane.doe@example.com`. Realistic, so the
shape of the value is legible and an adopter can pattern-match their own onto
it. Obviously fake, so nothing shipped unmodified reaches a real system and a
reviewer can spot an unreplaced placeholder at a glance. Empty strings are the
safer-looking option and the unusable one: they teach the key's name and nothing
about what belongs in it.

### `CONTEXT.md` - specific

The local human layer: who the people are, which workspace, which project,
which conventions hold.

**Why it is separate from `config.json`, since this is the join people merge:**
`config.json` is read by the *script* - ids, paths, intervals - and a wrong
value there **throws**. `CONTEXT.md` is read by the *agent* - that one person
owns design decisions, that a finding is posted one per thread - and a wrong
value there **fails silently as bad judgement**. They fail differently, so they
get checked differently: config can be schema-validated, context can only be
read. Merging them produces a config full of prose or a markdown file full of
ids.

#### Machine state is DISCOVERED, never written down

**Neither of those two files may contain an inventory of one machine.** Not
the Xcode or JDK version, not where an SDK lives, not which runtimes or AVDs
exist, not a tool's version number, and not an absolute path under somebody's
home directory. A repository is worked from several machines and both files are
committed, so a transcribed inventory is **wrong everywhere but the machine it
was written on, while still reading as authoritative** - which is worse than no
inventory at all, because it answers a question the reader should have asked the
machine.

`installation/check` is the inventory. It runs the probes and prints what this
machine actually has, on demand, and it cannot go stale. A skill that wants a
reader to know the local Xcode version tells them to run it.

Three consequences, and each one is a design constraint rather than a style
preference:

1. **`config.json` holds CHOICES, not STATE.** "The device this team
   standardises on" is a choice and belongs there; "the devices this laptop has"
   is state and does not. The test: if the value would still be correct after
   `git clone` onto a fresh machine, it is a choice.
2. **No absolute path.** Derive it instead - a checkout's own location from
   `git worktree list`, a home-relative tool from the resolver the build already
   uses. A path that starts with `/home/` or `/Users/` in a committed config is
   a machine leaking into a shared file.
3. **`installation/.install-state.json` records one entry PER HOST.** A single
   `host` field makes every *other* machine in the fleet report stale, and
   re-recording it un-records the machine before it - so two machines can never
   both be installed. Key the versions by hostname and each machine records
   only itself.

What DOES belong in a skill is a **measured** fact, carried with the date it was
measured and the platform it was measured on: a cold-boot time, a bundle time,
the fact that a write to a booted device does not take effect. Those are
properties of the TOOLS, and the date is a re-check trigger. An inventory is a
property of one machine, and has no re-check trigger at all.

### `override/` - specific, with a common README

Local rules that bend behaviour: *do not post to Slack on Sundays*, *never page
anyone before 09:00*.

**Distinct from `CONTEXT.md` because facts and rules are different things.**
Context states what is true here. Override changes what the agent does. A fact
is stated once; a rule needs precedence.

> **Overrides may only NARROW behaviour, never widen it.** This is the security
> property that makes a specific, unreviewed, behaviour-changing file
> acceptable at all. *"Do not post on Sundays"* is legitimate. *"Also allow
> deploys from anyone"* must be refused by the agent even if written there. **An
> override that grants is a privilege escalation with no review step**, which is
> exactly what an unreviewed file must never be able to do.

`override/README.md` is common and states that rule, so the constraint
travels with the repo rather than living in one team's habits.

**Precedence, most authoritative first:** the agent's charter, then a
`temporary/` convention in force (for the sections it names, and only those),
then `override/`, then `CONTEXT.md`, then `SKILL.md`. The charter outranks
overrides precisely because overrides are unreviewed; the next section says why
a temporary convention sits above them.

### `temporary/` - specific

A convention with an end: a rule that holds from a date or an event until a
date or an event, and then stops - *while a release window is open, fixes for
the released line go to the release branch*. One file per convention,
`<skill>/temporary/<slug>.md`, named for what it governs.

**Distinct from `override/` because it may WIDEN behaviour, and it may because
of where it comes from.** An override is unreviewed, so it may only narrow. A
temporary convention records a ruling by whoever owns the surface it bends, so
it may change behaviour in either direction: route work to a branch the
standing rule closes, or drop a question the standing rule asks. **The commit
that adds the file quotes that ruling and its source**, because that is what
licenses the widening. A file whose adding commit carries no ruling is an
override by another name, and an agent reads it as one: it may only narrow.

**Precedence, while it is in force:** it outranks `SKILL.md`, `CONTEXT.md` and
`override/` for the sections it names under **Bends**, and nothing else. The
agent's charter still outranks it. Before it starts, after it ends, and for
every section it does not name, it has no force at all.

**Dates are allowed in these files.** A start or end date changes what a reader
does, so it is the trigger the "state the fact, not its history" house rule
(`/agent` section 7) carves out, not history: do not sweep it out as history.

#### The file

Every field below is required. Four header lines, then two sections, in this
order:

```markdown
# <what the convention governs, in a few words>

**Starts:** <an ISO date (2026-11-02), or a named event stated so a reader can check it: a branch that exists, a commit on a branch, a run that finished>
**Ends:** <an ISO date, or a named event>
**How to tell it has ended:** <a concrete check a stranger can run, and the result that means "ended">
**Bends:** <each section it changes, by file, number and title: `SKILL.md` section 3.1 "<title>">

## Convention

<the rule itself, in the present tense: what an agent does while it is in
force, and how that differs from each section it bends>

## Cleanup

<everything to undo or revert when it ends, beyond deleting this file and its
pointers, one item per line, each saying how to undo it: a CI or workflow
change, a config value, a branch protection, a scheduled task (including the
one that watches for this convention's end), anything else the convention
introduced. When there is nothing, write `none`, so a reader knows the
question was asked.>
```

**Cleanup is not optional, and `none` is an answer, not a blank.** A convention
routinely leaves things outside its own file - a workflow edited to match it, a
protection set for its window, a scheduled task - and nothing else in the tree
remembers them. Deleting the file without them leaves the convention half in
force with nothing left to say it ever existed.

#### The pointer

**A skill's `temporary/` is not read unless something points there.** So each
section named under **Bends** carries one line at its top, in this form:

```markdown
> **Temporary convention in force:** `temporary/<slug>.md` changes this section until <Ends>. Read it before acting on this section.
```

That line is the one install-specific line a `SKILL.md` may carry, and it is
tolerable only because it is dated and leaves with the file. **A skill whose
`SKILL.md` lives in the fleet never carries it**: that file is shared by every
install and read-only on the host. Its pointer goes at the top of the install's
`CONTEXT.md` for that skill instead, naming each bent section, and an agent
using the skill reads that file before acting on a named section. The fleet
repository holds neither pointers nor `temporary/`.

#### Starting and ending

- **Whoever writes a convention also schedules the check that ends it**, through
  `/scheduled-tasks`, in the same sitting: a one-shot on the end date, or a
  daily check that runs **How to tell it has ended** for an end event. A
  convention with no scheduled end check is a defect from the day it lands,
  because nothing else ever looks.
- **Ending is one change, in this order:** do every item under **Cleanup**, then
  delete the file and every pointer to it. The repo-side undo, the file and its
  pointers go in ONE commit; anything outside the repository (a branch
  protection, a scheduled task) is undone before that commit, and its message
  lists each such item as done. A pointer left without its file, or a file left
  without its pointer, is the half-ended state this rule exists to prevent.
- **An expired file or a dangling pointer still in the tree is a defect**, the
  same class as a stale index row: it reads as current.
- **A reader does not trust the tree to say whether a convention is in force.**
  Before acting on a bent section, check **Starts** and run **How to tell it has
  ended**. Not yet started, or ended: it has no force, whatever the tree says -
  follow the standing sections, and do the ending or report it to the agent that
  scheduled it.

### `installation/` - common, except its state file

`INSTRUCTION.md` is the human procedure. `requirements.txt`,
`*.service.example` and `*.plist.example` (the same unit as a launchd job, for
a macOS host) are the artifacts, placeholdered. **A service unit that names a
user or an agent in its filename gets renamed** (`agent.service.example`, never
`<person>-<agent>-watchdog.service`). Every `<placeholder>` a unit template
carries has a row in the fleet's `SETUP.md` closing checklist, and the
`setup-checklist` gate refuses a template without one.

**`INSTRUCTION.md`'s record step is a command, not a shape to type.** It reads
`version` from `SKILL.md`, writes exactly the shape `check` reads, and adds or
replaces only its own entry: a version typed into the step goes stale at the
next bump, and a shape described in words gets guessed. **Its copy steps use
`install -m <mode>`, never `cp`**: the host fleet checkout is read-only and `cp`
keeps that mode, so the copy refuses its first edit. **It opens by saying which
of its steps are per agent**, because those wait until an agent's home exists.

**`check` is the important one.** It answers, in one line and one exit code:

| Exit | State | What the agent does |
|---|---|---|
| `0` | installed, current | proceed |
| `1` | **installed, but an older version** | do not proceed. Re-run install, then re-check. |
| `2` | not installed | do not proceed. Follow `INSTRUCTION.md`. |

There is no fourth code. A leg the check **cannot measure** reports `1` and says
so in words - see below; do not read the table as three exhaustive states.

**State 1 is the whole reason this exists.** Absent is loud: the import fails,
the binary is missing, something throws. **Stale is silent**: everything
imports, everything runs, and the behaviour is subtly the old one. That is the
failure this design is built to catch.

`check` verifies **real artifacts**, not a marker file: is the package
importable, is the unit loaded, does the binary answer. It then compares the
recorded `.install-state.json` version against `SKILL.md`'s declared `version`.

**There is a second sanctioned form, for an install whose subject is not the
machine**: derive staleness from the ARTIFACT rather than from a recorded
version, by comparing the installed artifact against the template the skill
ships. Use it when the install is per-USER-of-the-skill rather than per host -
one file per agent home, one config per tenant - because `.install-state.json`
records one entry per HOST, so it would read as authoritative while being wrong
for every subject but the last one installed. It is the stronger form where it
applies: a marker file can lie about an artifact, and an artifact compared
against its own template cannot. **A skill taking this form still declares a
`version`, and its `check` PRINTS it** rather than comparing it - a version
nothing reads at all is the inert signal described above, which later reads as
evidence that something needed reinstalling.

**A `check` with no `config.json` to read may resolve its values out of
`CONTEXT.md` instead, and that coupling must be declared where the value
lives.** It is a by-content parse of prose a person edits: relabel the row and
the check stops measuring. Put a back-pointer beside that row in `CONTEXT.md`
saying the check parses it, and make the check report `NO VERDICT` rather than a
green when the parse fails, so a reformat costs coverage loudly instead of
silently.
A marker file alone can lie; artifacts cannot.

**"Does the binary answer" means RUN IT, and the same holds for every other
artifact: verify each one by PERFORMING the operation the skill performs on it,
never by asking whether it exists.** `os.path.exists`, `getsize`, `isfile`,
`isdir`, `os.access` and `shutil.which` are all stat(2)/access(2)-class - they
answer from the inode or the permission bits and open, connect to or execute
nothing. Every one of them is GREEN on an artifact the skill cannot use: a token
file that is present, the right size and unreadable; an executable on `PATH`
whose `#!` interpreter is missing; a config the process cannot reach, which
`exists()` reports as False and a caller then treats as *absent and therefore
optional* - a skip indistinguishable from a pass. So open the file and read a
byte, connect to the socket, execute the binary with `--version`, and write the
real operation's own errno into the failure line. **Each such leg carries its
negative control and its rationale in the check's header**, because a control
whose reasoning lives only in a commit message reads as decorative to the next
person who opens the file - and if the control PASSES, the check issues NO
VERDICT rather than a green.

```json
// installation/.install-state.json   (specific)
{ "hosts": {
    "the-machine-it-ran-on": { "version": 2, "installed_at": "2026-08-01T09:14:00Z",
                               "by": "INSTRUCTION.md" } } }
```

`SKILL.md` says `version: 3`, this machine's entry says `2`, artifacts present
-> exit `1`.

**An install leg with no on-disk artifact reports exit `1` and says so in words.**
An account-level OAuth grant, a connector binding, a scope granted in someone
else's console: no script can measure it, and a network probe that fails cannot
tell a revoked grant from a flaky link. Both `1` and `2` mean do-not-proceed, so
either would be safe; `1` is the nearer bucket because the artifacts that CAN be
measured are installed. **What carries the information is the printed line, not
the code** - it must say which leg was unmeasurable and how a human confirms it,
because `NO VERDICT` reported as `installed` is the marker-file lie wearing a
different hat.

**`.install-state.json` keys each record by the HOST it was written on, and
`check` reads only this machine's entry.** The state file is committed, so it
travels to machines that never ran the install; without a host key every one of
them reads "installed and current", and with a single host field every machine
but the last one recorded reads stale. Recording on one machine adds or
replaces that machine's entry and leaves the others alone.

**A `check` written in Python opens its docstring with a SHELL HAND-OFF,
because its name does not say what runs it.** `installation/check` has no
extension, so `bash installation/check` is a command a reader reaches for, and
bash does not refuse a Python file: it reads it as shell, and command
substitution EXECUTES every backticked example in the docstring - an
`npm install` written there as prose runs in the caller's working directory. So
line 2, directly under the shebang, is this line, byte for byte:

```
"""[" -f "${BASH_SOURCE:-$0}" ] || { echo "a Python script: run it with python3" >&2; exit 126; }; exec python3 "${BASH_SOURCE:-$0}" "$@" || exit # sh/bash: hand off to python3 before reading the docstring
```

A shell reads `""` + `"["` as the test command. When it can name the file - bash
in `BASH_SOURCE`, sourced or not, any shell in `$0` - it replaces itself with
python3 on that file and its arguments before reaching line 3, so `bash check`
returns exactly the verdict `python3 check` does. When it cannot (the script
arrived on stdin, through a pipe, `-c` or `<(...)`), handing python3 a pipe gives
a wrong verdict - a silent `0` among them - so it refuses with one line and exit
`126`. Python reads the line as the OPENING of the module docstring, so the
docstring stays the first statement; that only works above a `"""` docstring,
never a `'''` one. `|| exit` stops a shell that would otherwise carry on after a
failed `exec` - bash with `execfail` on, or an interactive shell. **It hands off
rather than refusing outright** because exit `2` already means *not installed -
follow `INSTRUCTION.md`*: the line never issues a check verdict of its own, only
the shell's `126` and `127`. In the fleet repository a CI gate pins the line on
every extensionless Python script; the install's `CONTEXT.md` says how the
install pins its own.

### Scripts and tests - common

**The executable hardcodes nothing.** Reading `config.json` is one way to satisfy
that and not the only one: a script that takes every path as an argument satisfies
it better, because it stays fixture-testable offline with no config present. Read
config for values a CALLER should not have to know; take arguments for values that
differ per invocation. Adding a config loader to a script that correctly takes
arguments is a regression, not conformance.
**The test ships with it**: a skill whose script has no test is a skill nobody
can safely change later, and in a public repo that is the difference between a
contribution and a regression.

---

## 4. The fifth category, which is never a file

**Neither a credential nor real data appears in any of the above.**
`config.json` holds a **path to** the thing, never the thing. A leaked config is
then embarrassing rather than exploitable, and `config.example.json` can show
the path shape safely.

Two kinds of content qualify, and they fail identically:

- **Credentials.** A token, key, password, cookie jar or service-account file.
  It lives outside the skill tree entirely.
- **Any real-people or company dataset.** Names, postal addresses, contact
  details, identity rosters, workspace URLs, and any corpus accumulated from
  live use - a rating log keyed to real work, a captured message history. It
  lives outside the skill tree, `config.json` names its path under a key the
  script reads, and **the skill ships an example twin**: the real file's name
  with `.example` before its extension, the same format, obviously-fake
  contents. `config.example.json` points at the twin, so a fresh clone runs and
  its tests pass with no real data present, and `config.json` is the one file an
  adopter repoints. The twin is also the schema documentation for the real file,
  which is why it is a working instance and not a description of one.

The single test both obey: **a leaked skill tree should be embarrassing, not
exploitable.** A roster of real addresses is exploitable. The shape of that
roster is not.

**Where "outside the skill tree" IS, is a per-install decision**, so the path
lives in `config.json` and the location is named in `CONTEXT.md`. It is not
stated here on purpose: an absolute path in this document would be exactly the
value the document forbids. But **pick one location per repository and record it
in `CONTEXT.md` before the second skill needs it**, or every conversion invents
its own and the corpus scatters.

**A credential is named through `FLEET_SECRETS_DIR`, never by its literal
path.** A skill's `config.json` writes `${FLEET_SECRETS_DIR:-<fallback>}/<file>`,
where `<fallback>` is the install's default location for its organization
secrets and may itself name the install's own older variable, one level deep:
`${FLEET_SECRETS_DIR:-${<LEGACY_VAR>:-$HOME/<dir>}}/<file>`. Fleet scripts expand
the value with `fleetlib.expand.value` and find the directory itself with
`fleetlib.paths.secrets_dir()`, which reads `FLEET_SECRETS_DIR`, then the
variable the install manifest names in `secrets.legacy_env`, then
`secrets.default_dir`. The store is per user and per machine: a committed
absolute path resolves to a directory that does not exist under another user (a
CI runner) or on another machine. **Prose a human reads - a setup document, a
README, an error message someone is copying from - spells the absolute path
out instead**, because a blocked reader cannot expand a shell parameter in their
head. Both forms are correct; do not "simplify" either into the other. A
credential issued to one agent is not an organization secret: it lives in that
agent's own home (`/agent` section 3).

**The twin is APPEND-HAZARDOUS, and this bites every skill whose script writes
back.** `config.example.json` points at the twin so a fresh clone runs green;
that same clone, left on the example config, appends real records into the
obviously-fake file until it stops being obviously fake. Say so in the example
config itself, and have the script name the resolved path in its output so a
logged run is distinguishable from a discarded one.

**Move the real file out; never copy it, and never delete it.** A copy leaves
the original inside the tree, which is the entire problem restated. A delete
loses data the skill was accumulating on purpose. Relocating means the file
arrives at its new path intact, the consumer still reads it *through the config
key* (verify this by running the consumer, not by reading it), and `CONTEXT.md`
names the new path - because a path that exists only in a `config.json` is a
path nobody can restore after that file is replaced wholesale by an adopter.

---

## 5. Repo root

**This section describes the fleet repository's root - agent-fleet - not an
install's `.claude/skills/` directory.** An install's tree has its own index
instead, one row per skill, updated in the same commit that adds one; do not
read the absence of these files from an install as a gap.

- **`README.md`** - what the fleet is, the fleet-versus-install split (COMMON files in the fleet, SPECIFIC files in the install, the install manifest joining them), the skill list and the host-checkout model.
- **`SETUP.md`** - the stranger's path: the agent home layout (`/agent` section 3), clone the fleet, `fleet install`, create the install manifest from `templates/fleet.example.json`, fill each skill's `config.json` from its `config.example.json` and its `CONTEXT.md`, obtain each credential, `fleet link`, then `fleet check-all` until it is clean. Ends with a checklist of every placeholder that must be replaced.
- **`fleet check-all`** - runs every linked skill's `installation/check` with the agent's install context and prints one table. **This is what an agent runs at session start** to know what it actually has.
- **`.claude/skills/SKILLS.md`** - the fleet's own skill index, one row per skill, updated in the same commit that adds one; and **`CONVENTIONS.md`**, the conventions slot and the house rules with their keys and defaults.

**Common and specific describe WHAT A FILE IS, not where git keeps it.** What
makes a file specific is that it describes one install, and that an adopter
replaces it wholesale rather than editing around it. In an install a specific
file is committed like any other. In the fleet the split has a mechanical
guard: its layout gate refuses a specific file anywhere under its
`.claude/skills/`, and the only specific files in the fleet repository are the
synthetic ones under `tests/fixtures/install/`.

---

## 6. The test that says a skill is finished

> **Could a stranger at another company clone this, fill in
> `config.example.json` and `CONTEXT.md`, run `installation/check` until it
> exits 0, and have the skill work - without editing `SKILL.md`?**

If it needs a `SKILL.md` edit, the split is not done. Run the test **per skill
as each one is converted**, never once at the end.

---

## 7. Rules for the conversion work itself

- **No em dashes anywhere**, except where one is inside a byte-exact quotation
  of text living outside the skill - the fifth protected class below, which this
  rule would otherwise contradict. Hyphens everywhere else. This is a house
  rule (`ascii_skill_prose`, `/agent` section 7), and **the fleet's CI enforces
  it**: its ASCII gate fails on any non-ASCII character in a `.md` under
  `.claude/skills/`, `templates/`, `examples/` or the root documents, fixtures
  excluded. An install's own skills are covered only by whatever that install
  runs. Where nothing runs, say that plainly rather than writing "it is
  checked": a reader who believes a gate exists stops looking for regressions it
  would have caught, so a claimed-but-absent gate is worse than an acknowledged
  manual rule.
- **Convert one skill at a time. Do not bulk copy.** The point of one-at-a-time
  is that each skill gets the portability test in section 6 applied to it
  individually.
- **Copy a skill from the landing branch of its home repository, not from a
  working tree.** A checkout can be hundreds of commits behind, and copying from
  disk then imports a stale skill that looks current.
- **Verify by content, not by exit code.** A `git push` can print success and
  carry nothing; an API write can return `ok` and change nothing. Read the
  result back before saying it is done.
- **Never batch a write with the message announcing it.** Write, read back, then
  speak.
- **Never merge two files that describe different installations of the same
  thing.** Two `CONTEXT.md` files for two Slack workspaces merge into one file
  that points an agent at the wrong workspace, which is the worst outcome
  available here. Universal mechanics in `SKILL.md`, per-install values in
  `CONTEXT.md`, and never the two mixed.
- **Where two sources genuinely disagree, leave an `UNRESOLVED` marker and take
  it to the owner.** Do not silently pick a side; leave the safer reading in
  force until it is ruled on.
- **A skill with no `SKILL.md` is not a skill.** A directory of scripts cannot
  be loaded. Either write one or keep it out of the fleet.

### The ASCII sweep, and what it must not touch

Converting a skill includes normalising em dashes, en dashes, ellipses, curly
quotes and non-breaking spaces to ASCII. Emoji are kept, except in a file a
pure-ASCII gate covers: the fleet's allows none in a `.md`.

**The sweep covers the whole skill, not only its prose.** `SKILL.md`,
`CONTEXT.md`, every README and install instruction, and equally **script source
- its comments and its string literals alike**. A curly quote in a comment is
the same house-rule breach as one in a heading, and a no-break space inside a
string literal is worse than either, because it changes what the program does
rather than how it reads. A sweep stopped at the prose leaves the majority of a
scripted skill's characters unexamined while reporting the skill converted.

**Six classes of non-ASCII are functional and a naive sweep breaks them:**

1. **Prompt-matching glyphs.** Watchdog-style skills match terminal output on
   box-drawing and spinner characters. Strip them and the matcher stops
   recognising prompts, which is its only job.
2. **Captured terminal fixtures.** They are real pane output and must stay
   byte-exact, or the tests that use them mean nothing.
3. **Deliberate mojibake in tests.** A test asserting what an em dash becomes
   under a wrong encoding contains that broken sequence on purpose. A "remove
   non-ASCII" pass deletes the worked example of the bug the test exists to
   catch.
4. **A program's own rendered output, stored as data.** A log of past runs, a
   committed output snapshot, an example twin: the characters in it are what the
   code PRINTS, so sweeping them makes the data document a format the program
   does not produce, and rewrites observations that were recorded rather than
   written. A half-star written as a fraction because the glyph is tofu in half
   the terminals it lands in is the shape of this: it looks purely decorative
   and it is a measurement.
5. **A byte-exact quotation of text living OUTSIDE the skill.** A `SKILL.md`
   quotes a code comment, a section title, or a marker an operator types by hand
   so a reader can grep for it. Sweep the quotation and the grep silently returns
   nothing. Confirm the outside text still carries that byte sequence before
   trusting an inherited note that a character is protected: the note is only as
   good as its last check, and a stale protection is worth nothing.
6. **Text whose bytes are hashed into an identity that stored data references.**
   A prompt hashed to a short sha that every stored record carries, so that
   records made under different wordings are never compared. Sweeping em
   dashes out of such a prompt changes the sha and orphans every record made
   before it - **and nothing goes red**, because the human-facing version label
   beside it still reads the same. This is the sharpest member of the set: the
   text is INPUT, not output, so classes 1 to 4 do not cover it, and the damage
   is to data the sweeper never opens.

**The fleet's ASCII gate exempts no class inside a `.md`.** There a protected
character lives in a script, a fixture or a data file, which the gate does not
read; a fleet `.md` that must quote one names it by its codepoint (`U+00D7`).

**In a file whose job is recognising terminal output, class 1 is the default
reading**: treat every non-ASCII character in it as functional until the code
that consumes it proves otherwise. Read the consumer. The character itself
cannot tell you which class it is in, and a spinner glyph looks exactly as
decorative as a decorative one.

**Vendored dependencies are never swept.** A `node_modules/` or equivalent
inside a skill is someone else's code at a pinned version. **Whether it is
committed or installed changes only which way the sweep is wasted, never
whether it is.** Committed, normalising it makes the skill's own diff unreadable
and breaks any checksum over it. Ignored, it is worse: the edit appears in no
diff and no review, and the next install discards it silently - **an unauditable
change is a worse outcome than a noisy one.** Either way the sweep is undone by
the next install. Exclude the whole directory rather than exempting files inside
it one at a time; a per-file exemption list goes stale the moment the dependency
is bumped.

**Verify after any sweep, per file and not per tree:** every `config.json` and
data file still parses, every script still compiles, and every test suite still
passes. Per file, because a tree-wide check that goes red tells you a sweep
broke something and not which sweep.

**A skill's PROSE can itself be a machine-read artifact, and the sweep list does
not warn you.** A table in a `SKILL.md` can be regex-parsed at runtime by a
capture harness, keyed on a multiplication sign inside the row. Normalising that
one character passes every check in the list above - the file is not a config, not
a data file, not a script, and has no test - and breaks every screen capture in
the repository, surfacing on whoever next runs one rather than on whoever edited
the table. **Before sweeping any `SKILL.md`, grep the repo for something that READS it
by path**, and separate the readers from the merely-citing: a comment naming the
file survives anything, a parser does not. Then say so IN the prose, next to the
structure that is load-bearing, because the person who edits that table will never
read the parser.

**A swept file with no test gets an explicit substitute, never a shrug.** Find
the smallest real invocation that reaches each line you edited - a usage guard,
an error branch, a dry run against a fixture - exercise them, and then
**enumerate what remains unreached**. "It compiles" is not verification, and an
unstated gap is indistinguishable from a claimed one.

**The instrument that measures the sweep is itself a check, and it fails
silently.** A counting one-liner carrying literal target characters through a
shell argument degrades on the way - a no-break space arrives as a plain space
and the check then reports clean on a file full of them. Name the targets by
explicit codepoint escape in a **file** the shell never rewrites, and prove the
checker on a fixture that is known to contain each target before trusting a
clean result from it.

---

## 8. Correcting this document

**If you find something here that does not match reality, this document is wrong
and should be corrected in place.** A convention that quietly drifts from the
world is worse than no convention. The same applies to the install's
`CONTEXT.md` for this skill.
