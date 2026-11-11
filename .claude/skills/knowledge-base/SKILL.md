---
name: knowledge-base
version: 1
description: >
  Conventions for a durable, agent-maintained knowledge store - the folder
  structure, the index rule, what belongs in a file and what does not, and the
  checker that enforces the mechanical half of the index rule. Load when
  setting up a knowledge base, adding to one, or deciding whether something is
  worth writing down.
requires_install: true
---

# Knowledge base - conventions

A knowledge store an agent maintains for itself, so that what it learns survives
the conversation that produced it.

**Two stores, routed by SUBJECT.** The install's shared store holds what is true
about the project; each agent's own memory directory holds what is true about
that agent. Both follow every convention in this file - one set of
conventions, two stores. Which fact goes where, and why the split is by subject
and not by who wrote it, is `/agent` section 2, and it is not restated here.

The shared store's root path is `store.root` in this skill's `config.json` in
the install context (`fleet where knowledge-base config.json` prints its path),
and the install's `CONTEXT.md` beside that file names it in words along with
everything else that is specific to the install: who shares the store, what may
be written in it, what may never leave it, and its remote, if it has one.
**This file states the conventions and nothing else does** - there is no
rulebook file at the store root, because a second copy of these rules is exactly
the drift the index rule below exists to prevent. The store root holds an
`index.md` and nothing else that is not knowledge.

---

## Structure

**Hierarchical folders by topic**, as deep as the topic warrants.

```
<store.root>/
  index.md                  the root index, where a reader starts
  <topic>/
    index.md
    <subtopic>/
      index.md
      <thing>.md
    <thing>.md
  <topic>/
    index.md
```

**Create a folder when there is something to put in it, never before.** An
empty branch with an index describing nothing is noise, and the shape of the tree
should report what is actually known rather than what someone once planned to
learn. This applies to the store's own initialization: a fresh store is the root
and its `index.md`, with no topic folders scaffolded ahead of the knowledge that
would go in them.

## Creating a store

**The fleet ships no store.** A new store is a directory holding one file, its
root `index.md`, copied from the fleet's `templates/knowledge-store/index.md`
and edited to say what this store is for; `installation/INSTRUCTION.md` walks
it. The fleet's `examples/knowledge-base/` shows the format with lessons that
each open with a line marking them as examples: read them for the shape. They
are not part of any store, because a store holds what its own install learned.

## The index rule

**Every directory contains an `index.md`** listing its subfolders and files, one
line each - enough to decide whether to open something without opening it.

**After adding, moving, renaming or deleting a file, walk back up to the root
and fix every index that has become wrong.** A new file in `a/b/c/` means
checking `a/b/c/index.md`, then `a/b/index.md`, then `a/index.md`, then the root
- updating each only where it has actually become inaccurate. A new *folder*
almost always changes its parent; a new *file* usually changes only its own
directory's index.

**An index that lies is worse than a missing one.** A missing index makes a
reader list the directory. A wrong one is trusted, and it is read *instead of*
the directory - so its errors propagate silently into work that depends on them.

`check_indexes.py` in this skill enforces the mechanical half of this. Run it
after any change:

```bash
python3 "${CLAUDE_SKILL_DIR}/check_indexes.py" <store.root>
```

It cannot judge whether a description is accurate, only whether the wiring is.
**There is no exempt filename**: every `.md` file in a directory is linked from
that directory's index, including any file at the root, because an exemption is a
hole a reader cannot see from the index they are trusting.

### `index.md` format

```markdown
# <Folder name>

<One or two sentences: what belongs here, and what does not.>

## Subfolders
- [name/](name/index.md) - what it holds

## Files
- [Title](file.md) - the hook: what question this answers
```

Omit an empty section rather than writing "none".

**A link target is the real relative path** - `file.md`, `name/index.md`, or a
bare `name/` for a folder. The checker resolves every link on disk, so an
abbreviated target that a markdown renderer would forgive is reported both as an
unlinked file and as a dangling link.

## Knowledge file format

One topic per file, kebab-case name, `.md`. **If the title needs an "and", split
the file.**

```markdown
---
title: <plain-language title>
topic: <folder path>
verify: <command or place that re-proves any live claim - omit if the file makes none>
---
```

Then: the situation, what is true, and why. Link related files by relative path.

## Committing a store write

The store is a git repository, and a path-fenced commit - `git commit -m "..." --
<paths>`, the form that keeps a shared index from publishing someone else's
work - **REFUSES A PATH GIT DOES NOT ALREADY TRACK**:

```
error: pathspec 'codebase/new-thing.md' did not match any file(s) known to git
```

A new knowledge file is untracked by definition, so it needs an explicit
`git add` first. **The refusal writes nothing and changes nothing**, which is the
part that bites: the working tree still holds the new file and the amended
indexes, exactly as it did a moment earlier, so a glance at the directory says
the write is fine. Nothing is committed until someone runs `git log`.

**One untracked path kills the WHOLE commit, including the tracked edits
listed beside it.** `git commit -- new-file.md index.md` with `new-file.md`
untracked leaves the `index.md` edit uncommitted too - so the failure is not
"the new file is missing from the store", it is "the file and its index line are
both still only on disk", which is the one state the file-then-index ordering
above exists to avoid. Verify a store write by what `git log` shows, never by
what the directory shows.

## What to write

**Write what is not derivable.** If a reader could learn it by opening the file,
running the code, or reading version-control history, leave it out. Capture the
decision, the constraint, the reason, the trap.

**Anything that can rot carries the command that re-proves it, never a date.**
IDs, prices, scopes, quotas, API behaviour, who holds which role - all of it
drifts. Put the check in `verify:` and point at the live source instead of
copying its output. A hand-copied list is worse than no list because it gets
trusted; a "last verified" stamp is worse still, because it invites trusting it a
while longer.

**Record what does NOT work, not only what does.** A plausible wrong answer,
stated as wrong, stops the next reader deriving it again. Write it as a standing
fact - "X is not required, because Y works without it" - not as a story about who
tried it.

**Be specific.** "Fails with `missing_scope`, needs `channels:read`" beats "may
not have permission." Exact errors, real paths, real numbers.

**Write for someone arriving cold**, with no memory of the conversation that
produced it. State the situation before the fix.

**Write it when you learn it.** The detail that makes it useful is gone within a
day.

**Correct in place; delete what is wrong.** Stale knowledge is a liability, not a
neutral - it is trusted precisely because someone bothered to write it down.

**File only what you can defend.** Write to the store from something you
measured or read at source - never from a relay. If a fact reached you
second-hand, either go read the source before filing it, or leave it to whoever
measured it. The store states things in the present tense with no provenance, so
a second-hand claim becomes indistinguishable from a measured one the moment it
lands; the commit message can say *how* it is known, but the file cannot, and the
file is what gets read.

**Write axiomatically: no history, no attribution, no dates.** State what is
true, not how it came to be known. Cut "we decided", "as of March", "this was
changed", "it turned out that". A file should read the same the day it is written
and a year later. Where something is genuinely time-bound, that belongs in
`verify:` as a command, not in prose as a claim.

**The bar for writing at all:** *would this have saved me time if I had read it
first?* If no, it is a diary entry, not knowledge.

## When knowledge becomes a workflow

If a file grows past a page and has turned into a *procedure*, it is a skill.
Move the procedure into the agent's skills directory and leave the reasoning
behind.

## A store with more than one writer

A store shared by several agents has concurrent writers, and **the index rule is
the collision surface**: it sends a writer walking from a leaf back up to the
root touching indexes, so two agents adding unrelated knowledge in unrelated
folders still meet at the root index. Whether this install's store is shared, and
who shares it, is in `CONTEXT.md`.

**There is no lock, and inventing one is the wrong fix** - a lock file in a
store with no daemon to release it strands the store the first time an agent is
killed mid-write, which is a worse failure than a lost line. The discipline
instead:

- **Write your own file first and completely**, then fix indexes, innermost
  first, root last. The root index is held for the shortest possible time and is
  the only file two unrelated writers routinely contend for.
- **Re-read an index immediately before editing it**, and edit by adding or
  amending your own line rather than rewriting the file. An index rewritten from
  a copy read minutes ago silently deletes whatever landed in between.
- **After a write, run `check_indexes.py` over the whole store, not your subtree.**
  It is the only thing that will tell you another writer's line went missing under
  yours, and it is cheap enough to run every time.
- **A lost index line is recoverable and a lost knowledge file is not**, which is
  why the order above is file-then-index and never the reverse.

## A store with a remote, and the author of a commit

A store is a git repository, so its `git log` is where a fact's measurement and
its date live, which is why a file carries neither. Whether it has a remote is
discovered from git itself (`git -C <store.root> remote -v`); the install's
`CONTEXT.md` names the remote and its branch for a reader.

- **When the store has a remote, every commit is followed by `git push`.** A
  commit that is not pushed is a memory only this machine has: the point of the
  store is that the next agent reads it, on this machine or another, and an
  unpushed commit is invisible to every reader but this one. `git status -sb`
  showing the branch ahead of its upstream is unfinished work, not finished
  work.
- **`git pull --ff-only` before writing**, whenever another machine may have
  pushed since the last read. The store has concurrent writers across machines
  as well as within one (the section above), and the index rule's
  innermost-first walk performed against a stale root index deletes a line that
  landed elsewhere. A pull that cannot fast-forward means another machine wrote
  in between: replay your own unpushed commits on top of it, re-run
  `check_indexes.py`, and never force-push a store.
- **A commit to the store names the agent that made it.** Every agent on a host
  commits as the same OS user, whose global git identity names a person or the
  machine, so an unqualified commit attributes an agent's knowledge to someone
  who never wrote it, and `git log --format=%an` stops answering *which agent
  learned this*. Inside an agent's service unit the environment supplies the
  identity (`GIT_AUTHOR_*` and `GIT_COMMITTER_*`), so a plain `git commit` is
  attributed correctly. Outside it - an ad-hoc session, another machine, a
  session whose unit has not restarted since its identity was set - the identity
  goes on the command, in the form the install's `CONTEXT.md` gives:

  ```
  git -c user.name=<Agent> -c user.email=<the agent's address> commit -- <paths>
  ```

  **Which case you are in is a fact about YOUR SESSION, not about the disk**: a
  unit change reaches a session only from its next restart, so `env | grep
  GIT_AUTHOR` is the discriminator and the unit file is not. Empty means the
  flags are required, and a commit made without them succeeds, looks ordinary,
  and is misattributed silently - so confirm with `git log -1 --format='%an
  <%ae>'` after the first store commit of a session.

The root sits outside every project checkout, so cloning a project does not
bring the store: a machine gets it by cloning the remote, and
`installation/check` exits `2` until it does. Relocating it is an edit to
`store.root` and a move of the directory, which is what the path being a config
key buys.

## What this install decides

Three things are deployment-specific and are decided in `config.json` and
`CONTEXT.md`, never here:

1. **The root path** (`store.root`), stated in `CONTEXT.md` and pointed at from
   the standing brief every agent loads, so it is never guessed. Where the
   install has no shared store, project knowledge goes to the agent's own config
   directory; agent-specific knowledge goes to the agent's memory directory when
   it exists, otherwise to the same fallback, and a subagent's goes to its
   caller's. Both stores are git repositories; `git init` either if it is not
   one. **Neither store lives inside the project repository.** Anything else - a
   default location an agent reaches for silently - splits a store in two,
   which is the failure the two-store rule exists to prevent.
2. **Confidentiality.** What may live in the store *and* what may never leave it.
   These are different rules and the second is the one that gets forgotten: a
   store permitted to hold sensitive material still must not feed external
   services.
3. **Whether capture is agent-initiated or human-initiated.** Both work; deciding
   by accident does not. An agent that writes down everything it encounters
   produces a store curated by nobody, which is how a knowledge base becomes an
   archive nobody reads.
