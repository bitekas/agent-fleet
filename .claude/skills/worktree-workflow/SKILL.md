---
name: worktree-workflow
version: 1
description: >
  Workspace isolation and branch-landing discipline for a git repository that
  several agent sessions write at once - EVERY write to the repo happens in its
  own git worktree on a fresh branch, with no exempt file class and nothing ever
  written or committed in the main checkout; how a branch and a commit subject
  are NAMED (the install's forms and its closed list of branch types), so a
  shared trunk written by many agents says who wrote each line; which branch to
  cut from and land on; where worktrees live (an agent's own workspaces
  directory, or `repo.worktrees_dir` for a session working from the shared
  checkout); the `workspace.md` every worktree carries; creating one as a
  spawned agent (`EnterWorktree` is refused for cwd-pinned subagents - use
  `git worktree add`); the per-worktree REAL dependency install
  (`repo.install_command`; hardlinking installed dependencies from the main
  checkout is BANNED); and the evidence rules - state the SHA you read, an
  all-clear needs stronger evidence than a finding, and a claim's provenance
  travels with the claim. Load before creating a worktree, before committing
  anything, before removing a branch or worktree, and before reporting that
  something is landed, missing, or fine.
requires_install: false
---

# Worktrees, branches, and evidence

**This file names no absolute path, no branch, no agent and no repository.**
It is for a git repository that several agent sessions write at the same time,
and it is the same for every such repository. Every concrete value is a key in
the install's `config.json` for this skill, written here as `repo.worktrees_dir`
and never as the value; the human layer is the install's `CONTEXT.md` for this
skill. `fleet where worktree-workflow` prints the directory holding both.

What the install's `CONTEXT.md` carries, because a person needs it to judge and
no key can hold it:

| Topic | What it says |
|---|---|
| the checkout and the workspaces | the main checkout, each agent's workspaces directory, the shared-checkout workspaces directory, and the one listing that finds every worktree |
| which branch to cut from and land on | the worktree-facing slice of the branch-to-environment map, one row per kind of work (section 1.2) |
| the names | example branches, subjects and authors in this install's forms; the exempt lanes and CI subjects, byte-exact; the names no agent may take and what each breaks; whether anything enforces the forms or the type list |
| the dependency roots | every root `repo.install_command` covers and what a missing one looks like, plus the roots deliberately left out |
| credentials | where the credentials the repository reads live, and whether a fresh worktree needs a step to reach them |
| the dev stack | what `repo.dev_stack_command` brings up, and whether it claims a per-worktree port slot |
| who reviews | the person or role a `workspace.md` `review:` field usually names |

## 1. Every write happens in a worktree. Nothing happens in the main checkout.

**Any work that writes to the repo is done in its own git worktree on a fresh
branch.** This binds the root instance working alone exactly as it binds a
spawned team, and it has **no exempt file class**: the project instructions
(`CLAUDE.md`), agent charters and skill prose all go through a worktree like
everything else. Never work in another instance's checkout, and never share a
worktree with another live agent. The main checkout (`repo.root`) is never
written to.

**Why there is no exemption: the main checkout has ONE git index, shared by
every concurrent session.** `git add <your path>` does not fence your commit:
any session's bare `git commit` publishes *everything* staged, including another
session's in-flight files. An untracked file left loose in the shared tree lands
in someone else's `git add` the same way, and is invisible to its author while
it does.

**No file class is cheap enough to deserve an exemption.** The setup cost of a
worktree is the dependency install (`repo.install_command`); a change that needs
no installed dependencies - prose, a charter, a skill - needs no install, and
for it `git worktree add` alone is instant. The class that looks like it
deserves an exemption is exactly the class that costs nothing to isolate.

Two more reasons the default is universal: a branch is cheap and reversible
while a dirty shared trunk is neither, and where the install's dev stack
(`repo.dev_stack_command`) claims a **per-worktree port slot**, isolated work
gets a conflict-free local stack for free.

**A repository that is not the install's own follows its own contributing
rules.** An upstream or vendor repository states its branch names, subject form
and commit identity in its own contributing document, and that document
outranks this file there; the worktree and evidence rules below still hold.

### 1.1 Naming: the branch and the commit subject

**The install's forms are `naming.branch` and `naming.subject`**, and every
agent-created branch and every agent-authored commit subject follows them. A
form is built from these segments, and the install's form says which it uses:

| Segment | What it is |
|---|---|
| `<agent>` | the lowercase name of the standing agent the work is for (below) |
| `<Agent>` | the same name, capitalised |
| `<type>` | the BRANCH type: one name from the install's closed list, `naming.types` |
| `<kind>` | the COMMIT's conventional type (`feat`, `fix`, `docs`, `chore`, `test`, ...); not drawn from `naming.types`, and held to a list only where the install's `CONTEXT.md` names one |
| `<scope>` | what part of the repository the change touches |
| `<slug>` | what the work is, in a few words, in the case `naming.slug_case` names |
| `<subject>` | the change in a few words |

Any `[skip ci]`-style marker the subject carries stays where it already is, at
the end.

**`naming.types` is a closed list of branch types, each with its meaning.** Pick
from it, never beside it. It governs the branch's `<type>` only: a subject's
`<kind>` is the commit's own conventional type, and a `fix` subject on a branch
whose type is `bug` is the form working, not a violation. Whether anything enforces the list - a hook, a CI check - is
the install's to state in `CONTEXT.md`, and **where nothing does, it says so in
words**, so that a reader does not assume otherwise: a reader who believes a
gate exists stops looking for what the gate would have caught, which is the more
expensive half. Unenforced, the vocabulary drifts, and it drifts in the hands of
careful agents, each reaching for a word that describes its work better than
the listed types do. **Conform meanwhile** - pick the nearest listed type - **and
carry a recurring violation UPWARD as a question about the convention**, not
only as a correction to the agent: whether a type earns a place, or whether the
rule needs the enforcement it lacks, is a decision, and quietly conforming leaves
the next agent to rediscover the same gap. **Never rename, delete or otherwise
touch another agent's live branch or worktree to tidy this up.** Report it and
leave it.

**`<agent>` resolves to the STANDING AGENT the work is for, not to your
immediate spawner and not to your agent type**: the first named agent below the
human in the delegation chain your `workspace.md` records (section 2). Stated
that way it has ONE answer at any depth - a subagent three hops down takes the
same name as the persona at the top of its chain, so an engagement's branches
are contiguous however deeply it fanned out. Taking your spawner's name instead
scatters one engagement across as many namespaces as it had hops; taking your
agent TYPE puts every engagement in the fleet into a handful of shared
namespaces, which is the collision the agent segment exists to prevent.

**Check an agent's name against every filter the install runs over a commit
message, and against the reserved branch prefixes, BEFORE adopting the name.** A
subject prefix sits at the very start of the subject line, which is exactly
where a trailer-stripping filter looks, and a filter that eats a subject line
does it silently and exits 0. The install's `CONTEXT.md` records the names it
cannot give an agent, and what each one breaks.

**Why the agent goes on both, where the form carries it: a shared trunk is
written by many agents at once, and the views used to read it show no author.**
Where each agent session has its own identity, the author and committer fields
name the agent - the environment each agent session runs under supplies them,
with a per-checkout `git config user.name`/`user.email` as the fallback for a
clone used outside it, and a clone with neither falls back to the machine's
global identity; where agents share one identity, the prefix is the only thing
on the line that names the writer. `CONTEXT.md` carries this install's values.
Either way `git log --oneline` prints no author, so without the
prefix it cannot answer *who made this and can I ask them about it* without a
`git show` per line - and a branch listing carries no author field to print,
which is exactly the question asked of a branch nobody has deleted. A per-agent
branch segment also gives each agent its own ref namespace, so two agents cannot
collide on an obvious `docs/readme`-shaped name, and one agent's outstanding
work is `git branch --list '<agent>/*'`.

**Exempt from both forms:** the shared lanes - the landing branch
(`repo.landing_branch`), the branch serving the live environment
(`environments.live`), and every other branch on the branch-to-environment map -
plus release branches, which are lane artifacts rather than any agent's branch.
Also exempt is anything CI creates or authors: a version bump, a status or
report commit, a backmerge, and the merge commits git writes for you. **A CI commit
has no agent to name**, and CI's own subjects are read by other machinery, so
prefixing them would break it. `CONTEXT.md` names this install's lanes and CI
subjects, byte-exact.

**A branch may NEVER be named a bare prefix of the form** - a bare `<agent>`, a
bare `<agent>/<type>`, or in a form that starts with `<type>`, a bare `<type>`.
Git stores branches as nested refs under `refs/heads/`, so a ref named exactly
`<agent>` occupies a FILE at the path where `<agent>/<type>/<slug>` needs a
DIRECTORY, and **one stray branch named for a prefix makes every branch under
that prefix impossible**:

```
fatal: cannot lock ref 'refs/heads/<agent>/chore/x': 'refs/heads/<agent>' exists;
cannot create 'refs/heads/<agent>/chore/x'
```

Measured on git 2.x, 2026-09-09, in all three shapes: the bare name blocks every
branch under it, a bare `<agent>/<type>` blocks every branch under THAT, and it
is symmetric - an existing `<agent>/chore/x` equally refuses a later bare
`<agent>`. The message does name the squatting ref, so it is diagnosable; what
makes it worth a warning anyway is that it arrives as a failure of the branch
you just tried to create, at the moment you are starting work, and the squatter
may be months old and belong to somebody else.

**Nothing sweeps such a ref up on its own.** What keeps the namespace clean is
the delete step of the cycle below, which removes each branch locally and on
origin as its work lands. A branch left undeleted is already an unfinished task;
this is one more thing it costs, and the one form of it that costs somebody
else.

### 1.2 Cutting, landing, cleaning up

**Which branch you cut from and land on depends on the work**: a fix for the
live line cuts from the branch serving the live environment
(`environments.live`) and backmerges to the landing branch
(`repo.landing_branch`); where the install cuts release candidates, a fix for one
found in its testing cuts from and lands on that release candidate branch, which
is then back-merged into the landing branch (`/release`); feature work cuts from
the landing branch. The branch-to-environment map is single-sourced by
`/repo-and-environments`, and the install's `CONTEXT.md` carries the
worktree-facing slice of it - deriving it a second time from memory is how work
lands on the wrong line. When the work is done, merge the branch you land on INTO
your branch - the landing branch for feature work, the release candidate for a
release-candidate fix, and never the landing branch there, because that is the
landing-to-candidate flow a release window forbids - and resolve conflicts **in
your own worktree**, push, then delete the branch and worktree, locally and on
origin. Work lingering on an undeleted branch or worktree is an unfinished task,
not a finished one.

**Who lands it:** whoever owns the work. For a spawned subagent that is the
**caller**, not the subagent: a "completed" subagent whose branch and worktree
still linger is the caller's task to close out.

**Never park a finished merge on the main checkout's local landing branch
(`repo.landing_branch`).** That ref is cross-session mutable state: another
session's push sweeps whatever is parked below it to origin, and the checked-out
branch itself moves between your turns, so a commit made there can land on a
stranger's feature branch. Landing from your own worktree avoids both. **Never
`git checkout` a different branch in a checkout holding someone else's
uncommitted work.** If you find a commit of yours on a stranger's branch,
recovery is add-only: cherry-pick it onto the landing branch from a throwaway
worktree, **leave the stray commit where it is** (identical content makes their
merge a no-op), and tell them: rewriting history another session is building on
is worse than the duplication.

**Verify a push by the commit itself, never by an exit code or a symmetric
ancestry check.** `git merge-base --is-ancestor <landing> origin/<landing>` is
*tautologically true* when neither ref moved, so it prints success while your
commit sits elsewhere. Grep `origin/<landing>` for the change.

**And never PIPE the command whose exit code is the verdict.** A pipeline's
status is its LAST command's, so `if git push ... | sed 's/^/  /'; then echo
accepted; else exit 9; fi` prints **accepted** on a push rejected
non-fast-forward: the `if` reads `sed`'s zero. The piped form is not wrong on one
arm, it is **constant** - it answers `accepted` to exit 1 and exit 0 alike - so
it is a check with no discriminating power sitting in the gate position. It
survives review because the pipe looks COSMETIC: it is there to indent output
under a heading, and nothing about `| sed` reads as logic. Neither shell setting
is a blanket fix (`set -o pipefail` repairs this case and CAUSES the `grep -q`
SIGPIPE class), so the rule is the one that makes the question not arise:
capture the output to a file or a variable and test the status directly -
`cmd > "$LOG" 2>&1; RC=$?`, print the log, then `[ $RC -eq 0 ] || { echo
REFUSED; exit 9; }`.

**Commit form: `git commit -- <paths>`,** which commits those paths straight
from the working tree and parks nothing in the index. Path-fencing protects the
**index, not the tree**: `git commit -- <path>` commits that path's
*working-tree* content, so if two agents ever edit the same file, whoever commits
first necessarily carries the other's uncommitted edits. That is the second half
of why one worktree per agent is absolute. When history must be reconciled under
a live committer, **merge rather than rebase**.

**`git commit -F <file>` with NO pathspec commits the INDEX, not the working
tree - the opposite edge of the same rule, and it loses your own work instead of
publishing somebody else's.** An unstaged working-tree change (a revert, a hand
edit made after the last `git add`) is simply not in the commit, while the
previously staged files are. Nothing reports it: the worktree, the gate run and
the report all honestly describe a tree that was never committed, and the pushed
branch still carries the code the report says is gone. Two habits close it, and
the second is the one that is not obvious:

- **`git status --porcelain` is EMPTY before you push** - nothing unstaged, and
  nothing untracked that belongs to the task.
- **The landing check compares CONTENT, never file names.** `git diff
  --name-only <base>...HEAD` lists the file whether or not your change to it is
  in the diff, so *"the file is in the diff"* is not *"my change is in the
  diff"*. Read the hunk: `git diff <base>...HEAD -- <file>`.

### 1.3 Creating one

**Every worktree lives in a declared workspaces directory**: your own agent
home's `workspaces` directory (`/agent` section 3), or `repo.worktrees_dir` for a
session working from the shared checkout. Not beside the repo, not in `/tmp`, not
under `.claude/worktrees/`. Two reasons, and both are why it is a rule rather
than a preference: **a declared location makes orphans findable** (scattered
across ad-hoc directories beside the repo, in `/tmp` and under
`.claude/worktrees/`, "is anything still checked out?" has no cheap answer and an
abandoned tree is invisible until someone goes looking; one `ls` across the
declared directories answers it, and the install's `CONTEXT.md` writes that
listing out), and **it keeps worktrees out of the repo tree**: one under
`.claude/worktrees/` sits inside the very checkout it exists to be isolated from.

**A cwd-pinned subagent CANNOT use `EnterWorktree`**: the Claude Code tool
refuses with "blocked for a cwd-pinned subagent", which is most spawned agents
(Claude Code behaviour, observed by 2026-08-05; re-check after an upgrade).
This is not a failure and needs no escalation: `git worktree add <abs-path> -b
<branch> <base>` gives identical isolation, and agent threads reset their cwd
between bash calls so absolute paths were required anyway. Reach for `git
worktree add` first.

**Report the worktree path and branch you ACTUALLY landed on**: the harness can
force an agent into its own `worktree-agent-<id>` off the dispatch-time base
rather than the branch its brief named (Claude Code behaviour, observed by
2026-07-20), and supervision pointed at the named
branch then sees nothing.

**Within that directory, give the worktree a uniquely-named path you own**,
always empty, never a name another session might pick. **If `git worktree add`
refuses ("already exists"), stop: the path belongs to someone else.** A tool
declining to act is information about the world, not an obstacle to route
around; the next step after a routed-around refusal is operating on another
agent's state, which is how a shared tree gets corrupted.

**A fresh worktree has NO installed dependencies, and the failure is sneaky.** A
worktree starts with the tracked files only: no `node_modules`, no virtualenv,
no build output. Where a resolver walks upward - Node resolves a bare specifier
from the importing file's directory up through every parent's `node_modules` - a
worktree below a directory that has its own installed tree finds THAT tree, so
things appear to work until something under a secondary root dies with "Cannot
find module". Give every worktree a real, independent install: run the full
install line for the repo (`repo.install_command`), which covers **every root
that carries its own lockfile**, not just the top one.

- **Hardlinking the installed dependencies from the main checkout (`cp -al`) is
  BANNED.** Every worktree then inherits the main checkout's install state, which
  goes stale with no signal in git: phantom type-check errors on clean commits,
  each first read as a broken branch, merges held for a fault that is not in the
  branch, and a checkout that cannot boot the dev stack at all. A real
  per-worktree install makes the whole class unrepresentable.
- Its worst form, stated because the mechanism recurs: `cp -al` into a directory
  that **already had** `node_modules` creates `node_modules/node_modules`. Two
  copies of a package that carries a React context (or any module-level
  singleton) in one resolution graph become two distinct identities, so a
  provider and the consumer it wraps stop seeing each other and the app throws on
  every page load and never renders - which reads as a catastrophic code
  regression rather than a broken tree. **A total wipeout that takes down things
  your change cannot reach is a BROKEN EXPERIMENT until proven otherwise.**
- **The obvious roots are never all the roots, and the ones you miss are
  invisible until something RUNS.** A bare specifier resolves from the IMPORTING
  file upward, so a script living under a secondary root resolves its
  dependencies from **that** root's `node_modules` and from nowhere else - which
  is why a root with its own committed lockfile needs its own install even though
  nothing at the top level references it. The install's `CONTEXT.md` enumerates
  every such root; `repo.install_command` is the line that covers them, and it is
  the single source for that list.
  - **A STANDARD gate can depend on a root that an install line covering
    only the obvious roots omits, and it reports
    that as a code failure.** A gate that drives a script under a secondary root
    reds a worktree installed with only the obvious roots - a no-verdict or a
    failure carrying a module-not-found error, **on a perfectly clean tree** - a
    phantom red that reads as a broken branch, and installing the missing root
    turns it green with zero code changes. So: if the worktree will run the gate,
    install every root, and read a module-not-found error in a gate as a claim
    about the WORKTREE before it is a claim about the code.
- **An untracked credential directory is IGNORED, so a fresh worktree does not
  have it at all**: the same bootstrapping class as the missing dependencies.
  Any script that resolves a credential by globbing that directory dies there for
  a reason that looks like a broken script rather than a missing file. Symlink
  the directory into the worktree, or run a purely READ-ONLY credential script
  from the main checkout, which is a read and not a repo write. An install that
  keeps its credentials outside every checkout has no such step; `CONTEXT.md`
  says which this install is.

**The SCRATCHPAD is shared by every agent in a session, so a generic filename
there is a live hazard, not just a collision.** Two agents that each write a
harness to `teeth.sh` overwrite each other, so re-running "its" script executes
the other's harness, against whatever tree that one targets. A log another
worktree's run clobbers mid-analysis is well-formed and its numbers are real;
they just describe a different tree, and nothing catches it being quoted as
yours. So: **name every scratchpad file for its agent AND task**
(`teeth-<agent>-<task>.sh`, not `teeth.sh`); **write evidence you intend to cite to a
path you alone own** (`/tmp/<your-task>-evidence/`) in the first place;
**confirm a log names the worktree you ran in before quoting its numbers**; and a
script that mutates source must take its target worktree as an **explicit
argument**, never infer it from `cwd`: inference is what puts one agent's re-run
in another's tree.

## 2. Every workspace carries a `workspace.md` naming its owner

**The FIRST thing you do after `git worktree add` (before the dependency install,
before reading a line of code) is write `workspace.md` at the worktree root.**
The repository ignores it - a `/workspace.md` line in its `.gitignore`, or in the
shared `.git/info/exclude` where the repository must not carry the line - so it
never lands and never appears in a diff. Check that it is ignored (`git
check-ignore -v workspace.md`) before relying on it; an unignored one is the
loose untracked file of section 1.

**Why it exists:** a directory listing must answer *"whose is this, and is it
still running"*. With many worktrees live at once it cannot otherwise: a
finished workspace, an abandoned one, and one holding the only copy of
uncommitted work are indistinguishable, so a workspace one reap from real data
loss looks exactly like one safe to remove, and unattributable files cannot be
assigned to anyone.

```markdown
# workspace: <branch name>
created: 2026-01-05T09:00Z
by: <agent type> (agent <agent id>), in <your workspaces dir>/<name>
chain: <the human at the top> -> root -> orchestrator-<engagement> -> me
task: <one line - what this workspace exists to do>

plan:
  1. <the steps, written BEFORE starting>
  2. <...>

lands on: <branch>   base: <SHA you cut from>
review: <who must see this before it lands, and what they must see>

## cleanup
may be removed when: <the conditions, ALL of them, stated as checks>
harvest first: <ignored paths that exist ONLY here, or "none">
how: <the exact commands>
who may: <the owning agent, or anyone who has verified the conditions>

## status
2026-01-05T09:00Z  created, dependency install running
2026-01-05T09:40Z  fix implemented
2026-01-05T10:15Z  BLOCKED - waiting on a ruling about X
```

- **`by`**: your agent type and id, and the absolute path. An id lets the next
  reader ask whether you are still alive.
- **`chain`**: **the whole delegation path up to the human**, not just your
  commissioner. "orchestrator-lint -> me" is useless three hours later when that
  orchestrator has finished; the full chain survives it, and it is what tells a
  reader whether the work was ever authorized. It is also what `<agent>` in the
  branch form resolves against (section 1.1).
- **`task` / `plan` / `lands on` / `base`**: enough to judge, without asking,
  whether the work is superseded. **Write the plan before starting**: a plan
  recorded afterwards is a description and cannot show that the work drifted
  from what was commissioned. When it drifts, append to `status` rather than
  editing the plan: the difference between them is the useful artifact.
- **`review`**: name the person or role **and what they must actually see**. A
  bare name is not a review; "<that person>, before/after screenshots at every
  fixed viewport" is. A workspace that lands without its named review has
  bypassed the one check it was given. The install's `CONTEXT.md` names who
  usually reviews.
- **`status`**: appended, never rewritten. This is what distinguishes "stalled"
  from "finished and forgotten": **a workspace whose last line is hours old and
  whose agent is gone is a reap candidate; one that says BLOCKED is not.** Append
  a line whenever the state changes, and **write the final line before you stand
  down**, saying whether the work landed and where: a workspace that ends without
  one is indistinguishable from a crashed agent and gets treated as such.

**The `cleanup` block is what lets a stranger act safely without finding you
first, and it is not optional.** Write it **when you create the workspace**,
while you still know what only exists here.

- **`may be removed when`**: the conditions as *checks a stranger can run*, not
  adjectives. Baseline: the branch is proven **landed** (`git merge-base
  --is-ancestor <sha> origin/<landing-branch>`, after a fetch) **or pushed**
  (`git ls-remote --heads origin <branch>`), the tree is clean, and no process of
  yours is alive. **An empty `ls-remote` is ambiguous**: this workflow mandates
  deleting the branch on landing, so absence is the expected state of
  *completed* work. Use ancestry or content, never absence.

  **The reap gate is THREE parts, all printed, and none of them may be written as
  `cmd && echo OK`.** `git merge-base --is-ancestor HEAD origin/<landing> && echo
  "CONFIRMED LANDED"` produces one output on success and NONE on failure, so it
  cannot fail: on a refused push it prints nothing, and every destructive step
  chained after it - local branch delete, origin delete, `worktree remove` - runs
  unguarded, over a branch that has not landed. A gap reads as *nothing
  happened*, never as a refusal. Write every gate as a hard `if ... ; then ... ;
  else echo FAIL; exit 1; fi` that exits non-zero on the bad path.

  **And ANCESTRY ALONE NEVER LICENSES AN `rm`, because it is the same answer from
  the wrong tree.** A worktree and its main checkout share one object store and
  one ref namespace, so `git merge-base --is-ancestor <tip> origin/<landing>` is
  answerable identically from either - including from the main checkout that a
  failed `cd` into an already-removed worktree leaves you standing in, where it
  prints OK. Ancestry establishes that the WORK is safe; it says nothing about
  the thing you are about to DELETE being the thing you measured. So gate on all
  three, never any one: **(1)** `[ "$(git rev-parse HEAD)" = "$RECORDED_TIP" ]`
  against a SHA written down BEFORE the landing - a literal comparison, never a
  re-derivation, because a re-derivation from the wrong tree agrees with itself;
  **(2)** `git status --porcelain` empty; **(3)** ancestry. While it lasts, a
  deleted branch is not a deleted commit: `git cat-file -e <sha>^{commit}`
  recovers the tip so it can be re-created and re-pushed.
- **`harvest first`**: the field this convention exists for. Ignored artifacts
  are invisible to every git-shaped instinct: they never appear in `status`,
  never block a `worktree remove`, and die silently at both merge and reap. Name
  their absolute paths (a screenshot review pack, reference trees, capture
  scripts) or write **`none`**, so a reader knows the question was asked.
  Harvest **on the completion signal, never on a supervision snapshot**: a
  harvest taken from a poll is already stale, and misses whatever the work wrote
  after it.
- **`how`**: the actual commands, including branch deletion **local and on
  origin**, and `git worktree prune`. A half-reaped workspace leaves a stale entry
  that makes `git worktree add` refuse the path later.
- **`who may`**: normally you. Silence means *nobody but the owner*, and a
  workspace whose owner is gone gets escalated, not guessed at.

**It is a record, not a lock.** It does not reserve the directory and it does
not authorize anyone to reap another agent's workspace: a worktree is removed
only once its branch is proven landed or pushed. `workspace.md` makes that
judgement possible; it does not make it automatic.

## 3. Evidence rules

### 3.1 "Is this work landed?" is a question about CONTENT, not about a SHA

`--is-ancestor` cannot answer it. Rebase, cherry-pick and squash relocate a
branch's commits to new SHAs, so `git merge-base --is-ancestor <sha>
origin/<landing>` returning false is entirely consistent with the change being
fully shipped, byte-identical under different SHAs. **Check the content** (`git
diff <branch>:<path> origin/<landing>:<path>`) before concluding anything is
unlanded, and especially before telling anyone it was lost.

- **A false ALARM is not the harmless direction of this error.** It spends other
  people's attention on a non-problem and it manufactures fake evidence: a
  plausible reconstruction of a loss reads exactly like a verified one, and can
  end up written into the project instructions as a rule's justifying incident.
  **A rule earns its place from a verified incident, never from a plausible
  reconstruction of one.**
- **CHECK THE FRAME BEFORE YOU CHECK THE FACT: the commonest form of this error
  is a correct answer to the wrong question.** `--is-ancestor` against the
  default landing branch for work that landed on a feature branch returns "not an
  ancestor": true, and irrelevant. **The landing branch is whatever the
  engagement declared (`repo.landing_branch` is only the DEFAULT), never assumed
  by reflex.** Name the frame in the claim itself: *"contained in
  `origin/<agent>/feature/x`"* and *"contained in `origin/<landing>`"* are
  different statements. The same discipline binds a worker whose base disagrees
  with its brief: it diffs base against branch tip **before** concluding the
  brief is wrong, because "the brief is stale" and "my base is behind" are
  indistinguishable from the worker's seat.
- **THE MIRROR ERROR, AND IT POINTS THE WRONG WAY BY DEFAULT: AN ABSENT REMOTE
  BRANCH IS NOT EVIDENCE OF "UNPUSHED".** An empty `git ls-remote --heads origin
  <branch>` is ambiguous between *never pushed* and *merged, then deleted* - and
  since this workflow **mandates deleting the branch on landing**, absence is the
  expected state of **completed** work, so the naive reading is backwards more
  often than not. **A local ref outliving the remote one is the signature of
  exactly this.** Compounding cause: **a read of `origin/*` without a preceding
  `git fetch` is a read of history, not of origin.** The check that answers it is
  content or ancestry against the landing branch, after a fetch.
- **A DIFF HAS TWO FRAMES OF REFERENCE (the tree AND the base) and the base is
  the one nobody checks.** Diffing a landing-branch-based worktree against some
  feature branch renders the entire branch divergence as *that worktree's
  changes*; and an enumeration under an assumed path prefix reports a worktree
  **absent from disk** when the prefix is wrong. Both are the right question asked
  in the wrong frame. So: **name the base explicitly** in any diff you will act on
  (`git diff <base>...<tip>`, with `<base>` derived rather than assumed), and
  **prove a path exists before concluding from its absence**: `[ -d "$p" ] || {
  echo "NO SUCH PATH: $p"; exit 2; }`. An enumeration that finds nothing must
  distinguish *looked and found nothing* from *looked in the wrong place*.

### 3.2 State the SHA you read

On a repo with concurrent committers the artifact is the only shared clock, so
any report about the tree ("this row is missing", "that gap is still open") is
stale the moment it is written. Name the commit you read the claim from, and
re-read at HEAD before reporting a gap.

**A GATE RESULT IS A CLAIM ABOUT A TREE, SO EVERY GATE LINE A WORKER REPORTS
CARRIES THE TREE IT MEASURED**: `git rev-parse HEAD` and `pwd -P` from the SAME
shell as the run, plus the census number the gate itself named. Put it in the
brief, not in the reporter's judgement. A tree can change UNDER a run with
nothing in git to show for it: a file-level write that moves no HEAD (`git
checkout <sha> -- .`, `git restore --source`, an untarred archive, a `cp -r` into
a variable-resolved path) leaves no reflog entry, and once undone, a clean
`status`. What the recorded HEAD and `pwd -P` buy is that such a run is visible
in its own output rather than reconstructed hours later from a log. **A log's
birth time is not the run's start time** when `>` truncated a file an earlier
session had left at that path.

- **An ALL-CLEAR needs stronger evidence than a finding, because it is a
  directive to stop looking.** A wrong finding costs one check and announces
  itself; a wrong all-clear is silent. The usual mechanism: a grep of the
  **working tree** while an uncommitted fix is in flight cannot distinguish
  *never broken* from *already fixed*. **An absence is a claim about a revision:
  name it.**
- **A finding about ANOTHER agent's branch must name the SHA it was read at.**
  Parallel agents on separate branches cannot see each other's commits at all (a
  scan reads its own branch's **base**, not the other branch's HEAD), so a
  perfectly accurate report can describe code fixed an hour earlier on a branch
  the reporter is structurally blind to. This is the anticipated cost of branch
  isolation, and the report-don't-fix rule is what keeps it from becoming a nasty
  merge; the SHA is what lets the recipient tell "still open" from "already
  closed".
- **"THE STRUCTURE FORBIDS IT" IS WEAKER THAN "I LOOKED AND IT IS NOT THERE",
  wherever a manual override exists - and one almost always does.** "No branch
  maps an environment to that branch, so nothing could have deployed" is
  branch-shaped and therefore incomplete: a release workflow that carries
  `workflow_dispatch` accepts a manual deploy from any ref. **Name the override
  that would falsify your structural argument** (`workflow_dispatch`, a console
  edit, an admin SDK write, someone's laptop); if one exists, the argument is a
  hypothesis and a census is the answer. A structural inference that happens to
  be correct is indistinguishable in a report from a measurement, and the reader
  cannot tell and will not ask. **Cheap observation beats elegant topology** - and
  pair the census with a freshness cross-check, so a zero means *absent* rather
  than *stale*.
- **When your count disagrees with a worker's, suspect your parser first.** A
  recount of a shell array that drops backslash-continued entries agrees with
  itself every time it is repeated. **A disagreement about a number is evidence
  about the instrument, not yet about the fact.**
- **EXTRACT A FILE FROM A REF FOR INSPECTION WITH `git archive <ref> <path> | tar
  -x -C <dir>` - never `git checkout <ref> -- <path>` or `git restore
  --source`.** The latter two write the SHARED git index even when `--work-tree`
  redirects where the file lands, so the extracted copy is left STAGED in the
  main checkout, where any concurrent session's bare `git commit` publishes it.
  `git archive` touches no index and no ref, so reading evidence stays a read.

### 3.3 An artifact's self-description is the one field nothing else can see

A lifecycle field in an artifact's own header - `DRAFT`/`FROZEN`, "awaiting
approval", "dispatch only after sign-off" - is a claim about the **engagement**,
whose truth lives entirely outside the document. Citation sweeps, ownership
analyses and anchor audits check an artifact against **the code** and against
**itself**, so none of them can see such a field go stale: a package can read
DRAFT through its approval and through the implementation that followed it.

**Whenever the state of the work changes (frozen, approved, dispatched,
superseded), update the artifact's own status field in the same act.** Record the
**evidence**, not just the claim: the question as asked and the answer verbatim,
so a reader can audit the ratification rather than trust it; and where a stamp
was applied after the fact by someone who was not the approver, say so.

**The artifact you author alone is the one nobody audits: especially if your
role is auditing everyone else.** Sole authorship removes the reader who would
have caught it, and the auditing role supplies the confidence that makes checking
feel unnecessary. Put your own tracking files on the same sweep you run over
everything else, and put them on it *first* when you have just found the class
somewhere else.

### 3.4 Citations: unambiguous paths, symbols beside line numbers

- **Cite repo-relative and complete.** A bare `index.ts:330` resolves as many
  ways as the tree has files of that name, and a tool built to check one such
  citation lands on the wrong file and produces a false verdict.
- **Line anchors rot on every landing, by pure positional drift.** An unrelated
  insertion above a cited block moves it with no semantic change, which is
  exactly why it is dangerous: the argument built on the anchor stays valid while
  the pointer silently does not. **Rebase and anchor-audit are ONE operation**,
  re-run after *every* rebase. **Name the symbol beside the line**
  (`parseConfig` at `src/config.ts:357`) so a stale number is self-correcting.
  Beware partial invalidation: when a landing touches one cited file and not
  another, a spot-check on the untouched one returns clean and you conclude both
  are fine.
- **There is a LADDER above line numbers: a wrong POINTER misleads, a wrong
  ADDRESS manufactures a false failure, a wrong MECHANISM forecloses a question.**
  A stale URL that redirects offsite makes a diligent check report "NOT VERIFIED"
  against a correctly-deployed page: a false negative that reads as rigour.
  Worse, a design can justify a choice with *"the SDK reports neither X nor Y"*
  while the code uses a different API that does: the ruling right, the stated
  reason false.
- **A wrong mechanism is the worst of the three, because MECHANISMS ARE WHAT
  IMPLEMENTERS TRUST MOST AND VERIFY LEAST.** A wrong line number is caught the
  first time someone follows it; a wrong mechanism is never followed, it is
  believed - and it CLOSES a question permanently, leaving the next reader
  "impossible" where the truth was "we chose not to, and it is one property
  away." **So when a design states WHY something cannot be done, that is a
  load-bearing claim needing provenance.** Record capability decisions as CHOICES
  with their real rationale, **name the forgone capability**, and state the
  precision of the claim: "documented API" versus "read in the vendored source".

### 3.5 Provenance travels with the claim

**"Inference" stated in a confident register still arrives as fact, and a relay
chain launders source class**: a vendor README read by one agent, relayed by a
second and repeated by a third acquires two hops of apparent corroboration and
becomes indistinguishable from a measurement. A whole build effort can be scoped
around a constraint nobody measured that way - and a *correction* explicitly
labelled "inference" travels just as far, wrong or not. **Labelling the source
class is necessary and not sufficient; the register has to match it.** Say where
a claim was read *from* (file, package manifest, SHA, measured run), and when you
have not read the mechanism, say so in words that survive one relay.

- **Rank the sources: when a failure has produced an ARTIFACT (a CI log, a stack
  trace, an error string), that artifact outranks any structural reasoning about
  the failure, and it is usually sitting unread.** A build log commonly says in
  plain text which component refused, why, and what the remedy is, while
  explanation after explanation is argued from the component's manifest.
- **A green from an instrument that cannot fail is not evidence.** A CI **job
  conclusion** is not a verdict on the thing you meant to test: a job can fail on
  a post-build step after the build itself succeeded, and pass a step that never
  ran the check. A validation endpoint that accepts a fabricated identifier,
  returns a clean pass and silently discards the data is the same class, and
  some vendors' are built that way.
- **COMMITTING a relayed number is the strongest laundering step of all: once it
  is in a tracked file it stops looking like hearsay and starts looking like a
  record.** A number re-sourced later can turn out to have no origin but a
  comment its own author wrote, repeating a figure handed down by a supervisor:
  no run and no commit behind it. **The artifact becomes its own
  corroboration.** Never commit a number you did not produce without naming what
  produced it, and when you strike one, **leave the reason**: a silently deleted
  number teaches nobody.

### 3.6 Reading other people's claims

- **A GUARD'S COMMENT DESCRIBES THE BUG IT PREVENTS, IN THE PRESENT TENSE: read
  out of context it is indistinguishable from a bug report.** A clear comment
  explaining why a guard checks one condition and not another ("an outage that
  looks exactly like the guard working") can be traced, relayed upward as a
  shipped defect, and reach a person as one, while it was neither shipped nor a
  defect. **The clarity is what makes it travel** (a vague comment would be
  ignored) and each relay hop adds apparent corroboration. **So establish WHICH
  TREE EXHIBITS THE SYMPTOM, separately from which file explains it.** The tell is
  a claim whose mechanism is fully specified but whose *observation* is nobody's:
  no failing run, no user report. Ask "who saw this happen, and where?" **A hazard
  note is evidence a hazard was CONSIDERED, which is nearly the opposite of
  evidence it is live**: this is not an argument for vaguer comments.
- **AN INDEPENDENT READ IS ONLY INDEPENDENT IF THE SECOND READER CANNOT INFER THE
  ANSWER YOU WANT.** Withholding your hypothesis is the control, not the second
  opinion. A peer commissioned **cold** (the raw allegation and the questions,
  never the commissioner's reading) can converge *and* return findings the first
  reader did not have; framed as *"confirm this is a non-bug"* it most likely
  confirms it, and two convergent readings are then **one reading counted twice
  while looking exactly like corroboration**. This matters most for an all-clear,
  which a primed second reader cannot supply. Hand over the CLAIM and the
  QUESTIONS, and say plainly that disagreement is the useful outcome.
- **A DOCUMENTED FACT IS NOT A DRAWN CONSEQUENCE.** A subsystem can be inert in
  production for weeks while its own design document says so in plain English
  the entire time: nothing stale or wrong, and nobody joining the true statement
  to its consequence. A statement about a PRECONDITION reads as configuration
  trivia; only a statement about its CONSEQUENCE alarms anyone. **When you record
  an unfinished precondition, write the consequence beside it in operational
  terms**: not "the error-reporting key is empty" but "therefore every caught
  error is discarded and 'no error reports' means nothing."
  - **Reader side: when you reason from an ABSENCE of alerts, errors or events,
    first prove the sink is ARMED.** "No crash reports", "no error rows" are all
    satisfied by a dead pipe, and the dead-pipe reading is indistinguishable from
    the healthy one. **The inverse retires live hypotheses on evidence that never
    existed**: a post-fix search that is **empty by construction** must not be
    read as eliminating a cause. Where no positive control on the same instrument
    is possible, look on a **different** instrument.
