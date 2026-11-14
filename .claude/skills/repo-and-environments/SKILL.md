---
name: repo-and-environments
version: 1
description: >
  The repository's environments, the branch-to-environment deploy map, and
  release mechanics, for a mobile app with a cloud backend whose environments
  are selected by branch and deployed by CI - what each environment role is
  for, which branch deploys where and what a push actually triggers, the
  standing rules (the environment is never part of a build profile, there is no
  persistent .env, a consumed public env key fans out to every native-feeding
  source), where a mobile build lands per environment, the version number and
  what advances it, the backmerges (live to landing; release candidate to
  landing and live-copy), how a build gets its configuration and how that is
  proved on the finished artifact, and the git hooks every clone must enable.
  Load before changing anything about environments, branches, deploys or
  releases; before answering "where does this branch ship / which track /
  which cloud project"; before touching an env source file, the env lookup
  table, the ops library, the deploy script or a release workflow; and once
  per clone to enable the hooks.
requires_install: false
---

# The repository and its environments

This skill states which branch deploys where, what each environment is for,
where a mobile build actually lands, how a build gets its configuration, and
the standing rules about landing work. It is the mechanism; the install's
`CONTEXT.md` for this skill (`fleet where repo-and-environments CONTEXT.md`) is
the inventory, and `CONTEXT.md` below always means that file.

**The kind of project it is written for.** A mobile app for iOS and Android
built from one JavaScript codebase with a bundler (the React Native and Expo
shape: a JS bundle embedded in a store build, or served by the bundler to a dev
client), a cloud backend with one project per environment (the Firebase shape:
functions, hosting, a native config file pair per app), environments selected
by branch and deployed by CI (the GitHub Actions shape), and builds shipped to
the two app stores and to a tester-distribution service. Where a passage names a
vendor tool - the Expo build service (EAS), fastlane, firebase-tools,
`dorny/paths-filter`, GitHub Actions - it is a fact about that tool, dated where
it was measured. An install on a different tool keeps the mechanism and maps the
tool in `CONTEXT.md` section 0; a passage whose tool the install does not use
does not apply to it, and `CONTEXT.md` says so.

Two things follow from this pair of files being the statement of record:

- **Every fact here lives here, or in `CONTEXT.md`, and nowhere else.** The
  agent instructions, the headers of the ops scripts, the CI workflows and the
  setup guide point at these two files rather than restating them. Where one of
  them still carries a sentence on these topics, it is a *mechanical* contract
  for someone editing that specific file - never a second statement of policy.
  If you find a second copy of something below, the second copy is the bug:
  delete it and link here.
- **Architecture and design packages are historical records, not policy.**
  Where the install keeps them (`CONTEXT.md` section 8 names them), they record
  decisions as of their date and are deliberately *not* maintained against these
  files. Read them for the full account of how something came to be; read these
  files for what is true now.

Audience: humans, and the agents the install's project instructions point here.

## How this file names things

**This file is the mechanism. `CONTEXT.md` is the install's inventory.
`config.json` in the same install context carries the small structured subset
a script or another skill keys off - the environment role names, the selector
variable, the repository paths and the branch map; everything else is
`CONTEXT.md`.** Three conventions follow, and they are what make the files
composable:

- **Environments are named by ROLE, never by name.** The three standing roles
  are the **dev-machine** environment (`environments.dev_machine`), the
  **shared-dev** environment (`environments.shared_dev`) and the **live**
  environment (`environments.live`). An install may additionally carry a
  **live-copy** environment (`environments.live_copy`): a non-live environment
  that holds a copy of live's data, is deployed on demand and on every
  release-candidate landing during a release window (section 5.2), and is never
  written back to live. The names themselves, and the cloud project behind
  each, are values.
- **Tools are named by ROLE, never by filename**: the deploy script, the dev
  script, the env lookup table, the client env mirror, the release workflow,
  the backmerge workflow, the version file, the bump script, the provenance
  gate. `CONTEXT.md` section 0 is the one table mapping each role to the file
  that plays it in the install. **A runnable command line lives in `CONTEXT.md`,
  not here**, because a command a reader copy-pastes is worth more intact than
  keyed.
- **Section numbers are a contract.** Other documents cite this skill as
  section 4.3, section 6.5, section 2.1 and so on, and `CONTEXT.md` keeps the
  same numbers, so a citation lands in the same place in either file. A section
  keeps its number for the life of the file, even when everything in it turns
  out to be values and the section becomes a pointer into `CONTEXT.md`.
  **The headings are read by a test**: `sections.test.py` beside this file
  holds the cited numbers, and checks that each is a heading exactly once and
  that every "section N" this file and `config.example.json` cite resolves.
  Renumber or delete a heading and that test goes red, which is the point.

---

## 1. The environments

**The environment name is the single selector for everything below.** It is
carried into the app bundle as one public variable
(`environments.selector_var`) and read back by the client from there.

| role | config key | what it is for |
|---|---|---|
| dev-machine | `environments.dev_machine` | Emulators + seed data on your own machine. No cloud project is touched. |
| shared-dev | `environments.shared_dev` | Everyday feature work. **Expected to break from time to time** - that is what it is for. |
| live | `environments.live` | What external testers and real users actually run. |
| live-copy | `environments.live_copy` | Testing what is about to ship against a copy of live's data. Deployed on demand, and on every release-candidate landing during a release window (section 5.2); refreshed on demand; nothing in it is ever written back to live. It holds live users' data, so every channel that could reach a real person or write to live must be absent there by construction; `CONTEXT.md` names how. |

The names, the cloud project each maps to, and which branch deploys to each are
values: `CONTEXT.md` sections 1 and 2.

**WARNING: an emulator-only environment still carries a project label, and that
label may be the name of a real, retired project** - the one the install used
before it split its environments. Where it is, the provenance gate (section 7)
treats that string as a **fingerprint** of the legacy configuration rather than
as an ordinary marker. `CONTEXT.md` section 1 says whether that applies.

**Everything is split per environment, including the app's own identity**: the
cloud project, the telemetry keys, the app name, the icon watermark, the
**bundle id / package name** and the **custom URL scheme**. Distinct
identities, so the builds coexist on one device and each is a distinct app to
Apple, Google and the backend.

**WARNING: IDENTITY IS (ENVIRONMENT x BUILD METHOD), NOT ENVIRONMENT ALONE.**
The environment is still the *only* selector for **configuration**: cloud
project, telemetry, backend URLs; nothing below this line changes that. What
has a second dimension is **identity**. The deploy script requires a build
**method** alongside the environment, and neither defaults:

| method | JS | identifier | scheme |
|---|---|---|---|
| bundled | embedded in the artifact | the environment's bundled identifier | the environment's bundled scheme |
| bundler-served (a dev client; Metro on React Native) | served by the bundler at runtime | the environment's dev-client identifier | the environment's dev-client scheme |

So a bundled and a bundler-served build of the **same** environment are two
different apps and install side by side. **Every one of those identities is
registered**, and `CONTEXT.md` section 1 names the env lookup table's keys for
each and any identity that is not yet buildable. The bundler-served identities
never reach a store or a tester-distribution lane - the deploy script refuses
every distribution target for them.

**WARNING: THE DEV-CLIENT IDENTIFIERS ARE STATED PER ENVIRONMENT, NOT DERIVED BY
APPENDING A SUFFIX.** A derivation that holds for most rows can be wrong for
one (an environment that shares another's bundled identifier, for example), and
deriving then hands that environment **another environment's registered
identifier**, so the two builds overwrite each other on a device with nothing
able to notice: the derived value is not a typo, it is a real identifier that
resolves. `CONTEXT.md` section 1 carries any row that breaks derivation.

**WARNING: ONE WORD DECIDES BUNDLING AND IDENTITY TOGETHER, AND THAT IS THE SAFETY
PROPERTY.** A flag that decided only bundling, leaving identity to come from
elsewhere, makes "a bundler-loading binary carrying the live environment's
identifier" expressible. That build installs *over* the real app and runs
whatever JS the nearest bundler serves. One method flag makes it
**unrepresentable** rather than guarded, and a test enumerates the flag space
and proves it (`CONTEXT.md` section 0 names it). **Do not add an independent
bundling override.**

**WARNING: THE PREFIX RESIDUAL.** Where the live environment's identifier is a
string **prefix** of every other environment's, and each bundled identifier is a
prefix of its own dev-client variant (the usual `com.example.app`,
`com.example.app.dev`, `com.example.app.dev.client` shape), **any substring or
prefix match written against these ids silently counts a non-live build as
live**. Compare whole strings, always. The exact strings and the count of such
relations are in `CONTEXT.md` section 1, re-derived from the identifier set
whenever an environment or a build method is added or removed and never
adjusted by hand; what the identity split does and does not change is section
4.1.

**Two lookup tables hold the environment -> config mapping**, one per runtime,
because a shell script and an app bundle cannot share a module: an ops-side
table (project id, region, bucket, auth domain, functions URL, hosting URL,
admin-SDK key, source files, store lanes, icon variant, app name) and a client
mirror. **Two tables is a tolerable duplication only because a drift guard makes
them one**: a test fails if the two disagree on anything they both declare.

**Non-live builds are visibly badged** so a tester can tell them apart: a
corner icon ribbon and a suffixed app name, both selected from the one selector
variable by the app config.

**WARNING: do not use the app's name as evidence of which environment a build is
talking to**; the provenance gate (section 7) is that evidence. The name shows
only the selector the app config saw, never the backend the bundle talks to,
and section 6.3 is exactly that split. Where the badge does not even distinguish
the dev-machine environment from the shared-dev one - both mapped to the same
suffix and the same ribbon - a build named for the shared-dev environment may be
talking to the dev-machine one. `CONTEXT.md` section 1 names the install's
badges.

---

## 2. Which branch deploys where

**One branch maps to one environment, that map lives in exactly one place, and
an unmapped branch fails the job loudly rather than guessing.** The map is a
value: `branches` in `config.json`, with `CONTEXT.md` section 2 for the
judgement around it. A manual **Run workflow** takes an environment input
instead, plus a job filter and a runner escape hatch that moves the run off a
self-hosted build machine, where the install has one.

**WARNING: the landing branch is itself on the map**, so every merge into it
deploys. There is no branch on the map that merely stores work.

Deploys are **path-filtered**: a doc-only commit deploys nothing, and a change
confined to web-only sibling files (the `.web.<ext>` platform extension the
bundler resolves for web only) deploys web but never queues the long native
builds, because the bundler strips those files from the native bundle, so they
cannot affect it.

**WARNING: that second half is a property of a SCRIPT, not of the filter, however
much the sentence above reads like the latter.** `dorny/paths-filter` cannot
express "these paths, minus the web-only ones": under its default `some`
predicate quantifier a `!` rule is OR'd with the positive rules, so it would
match *more*, not less. The exclusion is therefore a POST-FILTER over the
matched file list, in a script of the install's own (`CONTEXT.md` section 0
names it).

**WARNING: quote every expansion of that file list.** `list-files: shell` emits
shell-ESCAPED paths, and unquoted expansion word-splits without **quote
removal**, so any path the action had to quote arrives with its quotes
attached, fails to match the web-only pattern, and marks the push
native-affecting. The failure is SELECTIVE: a path is left bare when it matches
`^[a-zA-Z0-9,._+:@%/-]+$`, so an ordinary `some/screen.web.tsx` strips
correctly and only paths carrying a metacharacter break - i.e. **every dynamic
route whose filename contains brackets** (a file-based router's `[id].tsx`),
`[` and `]` being unsafe. Unquoted, every push touching a dynamic route queues
both native builds anyway. So that post-filter is a script with a real test, in
the install's scheduled gate (section 3.2), because **a CI-only gate that
inverts does not fail** - it just quietly stops preventing what it exists to
prevent, and nothing in the run's output says so.

**WARNING: a branch on the map need not exist on the remote, and a branch that
exists need not ever have been pushed to.** A lane can be wired end to end and be
reachable only by manual dispatch, or exist on the remote and simply be rarely
driven. Do not read the map as proof that every row has ever run - and equally,
**do not read "rarely used" as "safe to push to"**: a lane that fires deploys
fires them whether or not anybody has used it lately, and burns a build number
(section 4.3) exactly as a busy one does. `CONTEXT.md` section 2 says which
branches are actually on the remote and what a push to each one costs.

### 2.1 A lane with ONE identity is not on the branch map

A repo can carry a publishing lane that is not an environment of the app at
all: for example a public marketing and legal site that deploys to object storage
behind a CDN rather than to any backend environment, driven by its own workflow
on pushes to the landing branch that touch its directory. `CONTEXT.md` section
2.1 has the bucket, the distribution, the region, the workflow and the
credentials, where the install has such a lane.

**Why it is not on the branch -> environment table above.** That table exists
because the app has parallel identities: several cloud projects, several
bundles, several distribution lanes, and a branch is how you select one. Such a
lane has exactly one identity: one public domain, one bucket, one distribution,
no per-environment variants and no environment-selected configuration of any
kind. There is nothing for a second branch to choose between, so it ships from
where work lands (section 3.1) and stops there. **Reading the landing branch's
environment mapping across to such a lane is a category error**: the site is
not a development copy of anything.

**Consequences worth stating, because they differ from every other lane:**

- **There is no second copy of the site.** A push to the landing branch
  touching that directory is live. Content review happens before the merge, not
  between environments - there is nowhere else for a bad edit to be caught.
- **It is a static upload with ONE deploy-time transform, not a build.** Asset
  preparation is run by hand and its outputs are committed. Nothing in this lane
  compiles, bundles, or reads `.env` - **none of section 6 applies to it.**
  **WARNING: the one transform: the workflow does not upload the repository
  directory.** It stages a copy in which every referenced asset filename is
  CONTENT-HASHED and every reference is rewritten to match, then uploads that.
  The repository keeps clean filenames, so opening the page from disk still
  works and an image edit is still just a dropped-in file. It exists for a
  serving path with a cache layer the workflow cannot purge - an outer CDN in
  front of the distribution it invalidates: there a changed image stays stale at
  the outer edge for up to its `max-age` while the `no-cache` HTML around it
  updates at once, and a hard refresh does not help. Practical consequence for
  anyone verifying a deploy: **the live URL of an asset is not its repository
  filename**, so read the name out of the deployed HTML rather than assuming it.
- **The TARGET is committed; only the CREDENTIALS are the CI provider's.** The
  bucket, the distribution and the region are constants in the workflow's own
  `env:` block; the deploy key is repo secrets, deliberately **not** named after
  the cloud SDK's conventional environment variables, which every SDK reads out
  of the process environment and which would therefore authenticate any step
  that happened to receive them.
  The rule behind that split, worth carrying to the next decision: **a value
  belongs in a secret when knowing it grants power, and in the file when it
  merely identifies a target.** A bucket name and a distribution id are public
  facts about where the site is served from, discoverable by anyone who resolves
  the domain, so hiding them buys nothing, and costs the two things committed
  configuration gives for free. A change of deploy target arrives as a **diff**,
  reviewable next to the change that motivated it, instead of happening silently
  in a settings page nobody watches; and `git log` can answer *when did we start
  deploying here, and who changed it*, which a CI variables UI cannot.
  Note the boundary this leaves: the workflow's first step FAILS (it does not
  skip) when a credential is missing, but the committed constants can never be
  *missing*, only **wrong**. A typo'd bucket passes the guard and fails in the
  upload call. **The guard is a credential-presence check, not a deploy
  rehearsal.**
- **Cache-Control is not incidental.** Where none of the site's source
  filenames are content-hashed, a new URL cannot bust a cache entry. Assets ship
  a long `max-age` and lean on the unconditional invalidation each deploy
  performs; the HTML pages and their stylesheet ship `no-cache`, because they
  are legal documents and must not sit behind a browser TTL after a correction.
- **The deploy identity needs only** list on the bucket, put and delete on its
  contents (the syncs run with delete), and create-invalidation on the
  distribution.

**WARNING: a bucket named after a hostname is NOT a served host.** Naming an
object store after a domain is a convention, not a binding: what a visitor
reaches is decided by DNS and by the CDN distribution's aliases, neither of
which lives in the repository. So read this lane as answering *how the site
gets published*, and **read the served origin off the distribution rather than
off the workflow.** `CONTEXT.md` section 2.1 records what was measured, on what
date, and which host actually serves.

**Verify a marketing deploy against the host that actually serves it**:
confirming first that the distribution still fronts the bucket and that DNS
still points at the distribution, rather than reading a green deploy as a live
site, and read the asset URL out of the served HTML rather than constructing it,
because of the deploy-time content-hashing above.

**WARNING: a placeholder host in social metadata publishes fine and SHARES
badly.** Absolute `og:` URLs pointing at a host that does not serve the site
break every link preview, while the page itself renders perfectly; a *relative*
`og:image` is ignored by every scraper, so there is no failure anywhere to
notice. The corollary worth carrying into any argument about the reach of
marketing imagery: such a page is **not propagating through link previews at
all.** `CONTEXT.md` section 2.1 records whether that is currently the case.

---

## 3. Standing rules

### 3.1 The live branch takes CRITICAL fixes only: no new features, interfaces, or schema changes

The rule, verbatim in `CONTEXT.md` section 3.1: **no new features, interfaces,
or schema changes on the live branch**, and a new feature goes to the landing
branch.

**Read the rule as written - it is wider than "bugfix-only".** The extra two
words close the gap where a change is technically a fix but still changes a
contract. A fix that adds or renames a field in a stored document, changes a
callable's signature or accepted payload, alters a response schema a client or
the backend parses, or changes what a screen or API exposes is an **interface or
schema change** and does not belong on the live branch, however small, and
however obviously it is "the right fix". **When the only fix you can see changes
a contract, that is a signal to escalate, not to proceed.**

Fixes are fine, in this order: **validate, fix, land on the live branch,** and
the backmerge (section 5) carries it to the landing branch on its own.
"Validate" is doing real work there - it is the confirm-the-hypothesis-before-
fixing rule plus the failing-test-first order (`/definition-of-done` Rule 4) -
not a rubber stamp. **A report that does not reproduce is not a fix and does not
earn a live-branch push.**

**WARNING: not every fix qualifies - only a CRITICAL one.** A fix that can wait
ships from the landing branch with everything else, through the release
procedure (`/release`). The live branch is reserved for what cannot wait for
that: data loss, a broken purchase or authentication path, a crash on a common
route, anything actively costing users or money. **A one-line display fix is not
critical**, however obviously correct and however small the diff - "it is only
one line" is an argument for how cheaply it rides in the next release, never an
argument for a direct live-branch push.

**WARNING: this is standing, and it is not re-asked per change.** "Which
environment do you want this fixed on" has one standing answer: **the landing
branch, released through `/release`** - unless the fix meets the critical test
above, in which case it takes the validate-fix-land order in this section.
Asking again per bug spends the decider's attention on a question that is
already settled.

**Why:** the live environment serves real users (`CONTEXT.md` section 3.1 says
who they are in the install), and a store build reaches them as soon as the
store clears review. It is not a place to be landing new behaviour.

#### How a feature reaches the live branch

**A release is cut per `/release`.** That is the route, and it is not restated
here: it owns the step order, what each step proves, and who authorizes the
merge that moves the live branch.

### 3.2 Pushing

**Where nothing on the remote rejects a push** (section 5 on branch protection;
`CONTEXT.md` section 5 records the install's state), landing is pushing: land
the work, push it, and verify origin has it.

Pushing is the delivery channel, so an unpushed batch is undelivered work: CI's
path-filtered release builds are how a change reaches testers and devices.

**Know what your push triggers before you make it.** Section 2 maps branch ->
environment, and **the release workflow's path filters are wider than they
look**: a change touching a path several lanes share - the root package
manifest, a shared service layer, the backend functions tree, the storage
rules; `CONTEXT.md` section 3.2 lists the install's - can queue a web deploy, a
functions deploy **and** native builds for both platforms from one push. A push
to the landing branch touching a single-identity lane's directory (section 2.1)
additionally PUBLISHES that lane, live immediately, with nothing between the
merge and the public page.

**WARNING: KNOW WHAT VERIFIES A PUSH, BECAUSE IT IS USUALLY ALMOST NOTHING.** The
workflows that run on push are DELIVERY pipelines; `CONTEXT.md` section 3.2
lists which workflows run on push and what verification, if any, each carries.
Where a push-time job polices bookkeeping no path filter can see (a test
runner's census of its own declarations, for example), run it outside every
path filter and let nothing depend on it, so it reds the run without holding a
deploy - and read a red there as *recount the bookkeeping*, never as *the
release is broken*. **Where everything else is a scheduled run, it fires on the
default branch only** (`repo.default_branch`), because a `schedule:` trigger
always uses the default branch. Consequences to carry when you push:

- **a feature branch is gated by nothing until it lands** (dispatch the quality
  workflow on a ref to gate one on demand);
- a break surfaces up to one schedule period later, with that period's commits
  to bisect;
- **where no CI job scans pushed commit messages, the local commit-msg hook is
  the whole defence**, and it is silent on a clone where it was never enabled
  (section 3.4).

Run the gates locally; they are all cheap except e2e.

**WARNING: where the release workflow has NO path classification of its own** in
front of its jobs, a documentation-only push to a mapped branch still starts its
resolve and change-detection jobs on the build machine before every deploy job
correctly skips. **Report what will fire when you report the SHAs.**

**WARNING: the corollary nobody expects: a docs-only streak on a branch hides a
broken native build.** The path filter correctly skips the native jobs on a
docs-only push, so the deploy script's SDK-doctor gate is not exercised - and
**that gate can turn red with no repo change at all**. Its "expected" column is
fetched at run time from the SDK vendor's own HTTP endpoint, keyed by the SDK
major; the installed SDK package's bundled compatibility table is consulted only
as a FALLBACK, when that lookup cannot be resolved (`expo-doctor`, measured
2026-09-11). A deploy script that invokes the doctor unpinned fetches the
CHECKER fresh at deploy time as well: both halves of this gate move without the
repository. Two consequences, and neither of them follows from "the installed
package decides": **pinning the SDK package does not stabilise this gate** - the
local table is not what is read - and a vendor patch wave reds every native lane
on every branch with zero repo change. A branch can therefore sit unable to
produce a native build for days with nothing going red. **The first
native-affecting push pays for the whole streak**, and between native pushes a
scheduled gate that runs the same doctor is the only thing that surfaces it.
Recovery is the sanctioned one and only that one: the SDK's own
`install --fix` (re-run it once), then its doctor until it exits clean.
**WARNING: judge that by the DOCTOR's exit code, never `install --fix`'s** - the
latter exits 1 on the dynamic-config plugin write having done exactly the right
thing. `CONTEXT.md` section 3.2 names both commands.
**Where the install automates that recovery on the default branch**, it runs
`install --fix` itself and commits the result as the release bot only inside a
fence: every version that moved is patch-only, every manifest move is a package
the doctor named, every lock entry it did not name hangs off one that it did -
both before and after the fix - and no package it moves carries a vendor patch
(the postinstall the SDK's install triggers re-applies a patch named for the OLD
version, unchecked against the new one, and leaves the new one unpatched when
it no longer fits); anything outside the fence is reverted and the gate stays
red. `CONTEXT.md` section 3.2 names the script, whose header is the whole
policy. A red doctor on the default branch is then left to that gate, because a
hand bump races the bot's, and the by-hand recovery above is for a feature
branch and for a diff the classifier refuses.

**The same shape at a different gate:** a required-argument change to the deploy
script that is not fanned out to the workflow's native call sites leaves every
one of them invoking a script that refuses them - every native build on every
branch broken, with green CI on every docs-only push in between. **A
required-argument change fans out to every caller, and green CI on a push that
skips the job is not evidence the job passes.**

**WARNING: AND A JOB CONCLUSION IS A CLAIM ABOUT THE OUTCOME, NOT ABOUT THE
CAUSE - SO READ YOUR OWN RUN'S JOB-LEVEL CONCLUSIONS AFTER EVERY LANDING, NOT
THE RUN'S.** A GitHub Actions job that exceeds its `timeout-minutes` is
reported `conclusion: cancelled` - the same word GitHub gives an operator
cancellation and a concurrency cancellation, with no API field separating them
(GitHub Actions, measured 2026-09-22).
It is **grey rather than red**, so it survives any scan that looks for red, and
it sits beside green siblings and a successful version bump while the
environment is half-deployed and nothing in the repository says so. **The
discriminator is the DURATION**: a job that ran its ceiling plus a few seconds
of teardown timed out, and supersession is ruled out by reading that job's
`cancel-in-progress` rather than inferred from timing. Read a deploy's
per-function tick list from the **job-scoped** log; the run-level log is not
that artifact. **WARNING: a later push heals the gap only if it exercises the
same lane** - the deploy jobs are path-filtered, so a docs-only successor skips
the deploy and leaves the gap exactly where it was, which is the skipped-job
rule above met from the other side.

**WARNING: a job's ceiling must EXCEED the internal deadline of the tool it
runs, or the job kills the only process able to report the failure.**
`firebase deploy` polls each function operation on a 25-minute
`masterTimeout`, and the budget is **per attempt** - a retried operation gets a
full fresh one (firebase-tools, read in its source 2026-09-22) - so a 30-minute
job around it has no margin for one retry, and the CLI is SIGTERM'd mid-poll
having reported nothing. Derive the floor and write the arithmetic beside the
number (setup + one healthy pass + one full poll deadline + teardown), and **pin
the tool's deadline by reading it from the INSTALLED package** rather than
copying the number into a comment, so a vendor bump reds a gate instead of
silently re-arming the same failure under a ceiling that was correct when it was
written. `CONTEXT.md` section 3.2 says where the install's measurements are
recorded.

**A push that reaches a store also advances the app's version**, landing as a
follow-up commit on the branch you just pushed, and on the live branch that
follow-up is then carried onto the landing branch by a SECOND, dispatched
backmerge run - so a live release advances the landing branch too. What all that
is, when it fires, and how to opt out: **section 4.3**.

### 3.3 Work happens in a worktree: always, and no file class is exempt

Any work that writes to the repo gets **its own git worktree on a fresh
branch**, never a shared checkout and never another session's checkout.
**Nothing is written or committed in the main checkout, ever**: project
instructions, agent memory, agent charters and skill prose included. There is no
exempt class.

**WARNING: the reason is the main checkout's single git index, shared by every
concurrent session: staging your own path fences nothing.** Any session's bare
`git commit` publishes the whole index, including another session's in-flight
files, and an untracked file left loose there lands in someone else's commit
the same way. Exempting prose would save only worktree setup cost; that cost is
the dependency install, and prose needs no dependencies, so `git worktree add`
alone is instant. **An exempt class would be exactly the class that never needs
the exemption.**

**Worktrees live in a declared workspaces directory** - the agent's own, or
`repo.worktrees_dir` for a session working from the shared checkout - never
beside the repo, in `/tmp`, or inside the checkout; `/worktree-workflow`
section 1.3 has the reasoning.

Where the install's dev stack claims a per-worktree port slot (`CONTEXT.md`
section 3.3), an isolated worktree gets a conflict-free emulator and e2e stack
for free.

**Branch off the branch your work lands on.** Which branch that is - for feature
work, for a critical fix to the live line (section 3.1), and for a fix found
while testing a release candidate (`/release`) - is `/worktree-workflow`
section 1.2 ("Cutting, landing, cleaning up"); this is a pointer, not a second
statement of it.

**Name the branch and the commit subject per `/worktree-workflow` section 1.1.**
The shared lanes on the branch map are exempt from its naming rule, as are
release branches and anything CI authors. That skill owns the form, the type
vocabulary, the exemptions and the ref-namespace constraint; this is a pointer,
not a second statement of it.

A fresh worktree has **no installed dependencies**; give it a real, independent
install of every dependency root before doing anything. **WARNING:** hardlinking
from the main checkout is **BANNED** - the shared install's staleness produces
false gate verdicts in isolated trees. `/worktree-workflow` section 1.3 owns the
install line (`repo.install_command`), the roots it covers, and why the failure
is sneaky.

#### The cycle, because SEVERAL AGENTS RUN AT ONCE

Every step below exists because a concurrent writer makes the lazy version fail:
a branch cut hours ago works against a base that no longer exists, and a file
left loose in the main checkout is sitting in someone else's workspace.

1. **Pull the branch you land on regularly, during the work, not only at its
   start.** Refresh before branching, and again whenever the work runs long. The
   cost of a conflict grows with the age of the base you are holding.
2. **A branch AND a worktree, always, before the first write.** **WARNING:**
   never leave files loose in the main checkout, and never write outside a
   worktree.
3. **When the work is finished, merge the branch you land on INTO your branch
   and resolve conflicts there** - in your own worktree, where a broken merge
   harms nobody. Never resolve on the branch you land on. For a release-candidate
   fix that branch is the candidate, never the landing branch
   (`/worktree-workflow` section 1.2).
4. **Then push to the branch you land on.**
5. **Then tidy up, and it is part of the task rather than after it:** delete the
   branch **locally and on origin**, remove the worktree, and delete any local
   temp files the work created. Prune, then confirm the worktree list and the
   remote branch listing are both clean (`CONTEXT.md` section 3.3 has the
   commands). **Work left on an undeleted branch or worktree is an unfinished
   task.** **WARNING: what this sweep must NOT take is `/definition-of-done`
   Rule 3's carve-outs**, and one of them is not durable and looks exactly like
   a temp file: a gate's UNREAD failure evidence, written outside the worktree on
   the one run that produced it. Read that rule before deleting anything a probe
   wrote.

**WARNING: verify the push landed, and verify it by CONTENT.** A silenced
failure (a redirect to `/dev/null` around a cherry-pick or merge) can report
success while pushing nothing. Proving the commit is an ancestor of the remote
branch shows it entered history; grepping the remote branch for the change
proves it is still there. **Do both, and never report "pushed" from an exit
code alone.**

### 3.4 Git hooks: enable them ONCE PER CLONE, or they silently do nothing

The repo ships tracked hooks and a setup script that points `core.hooksPath` at
them (`CONTEXT.md` section 3.4 has the command). **Git does not use tracked
hooks unless `core.hooksPath` points at them, and nothing announces that they
are off.**

**A hook is a gate only on the clones where it is enabled.**

**Each hook has ONE job**, and `CONTEXT.md` section 3.4 names each hook the
install ships and that job. Do not add a second job to a hook - a
commit-message lint in a hook whose job is something else is the usual form -
because a hook that does two things is tested for one.

**Where the commit-msg hook's job is stripping AI-attribution trailers**: a
commit is authored by the agent or person who made it, and no co-author or
provenance trailer naming an assistant survives. That **overrides** an agent
harness's default instruction to add one. Match by trailer **prefix**, so a new
trailer in that family is stripped without editing the hook, and a legitimate
**human** co-author is preserved - the strip is targeted, not blanket.

Do not write a testing-notes section into a commit body for a release note to
pick up: where the store note is one fixed string (section 4.5), nothing reads
it.

**Two more hooks keep private keys out of the repository, through ONE scanner
with a mode flag**: the pre-commit hook refuses a commit that STAGES key
material, and the pre-push hook refuses a push that CARRIES it - a PEM private
key block, a JSON private-key field with a value, or a cloud service-account key
file. Credentials live outside every checkout, and an untracked key file in a
shared checkout is one `git add -A` from a public remote. The patterns and the
binary rule live in the scanner alone, so the two hooks cannot drift apart.

- **At commit time** the scanner reads the **index**, never the working tree, so
  it sees what is being staged under every form of `git commit` (plain, `-a`,
  `-- <paths>`; under `--amend`, the changes added to the commit it replaces)
  and when a conflicted merge, cherry-pick or revert is concluded.
- **At push time** it reads every blob the pushed commits introduce - not the
  tip's tree - down to exactly what the TARGET remote reports holding (one
  `ls-remote` round trip). **WARNING: a remote-tracking ref is not that
  evidence**: another remote's ref, or a stale one for a branch the target has
  deleted, reaches blobs the target lacks, and git uploads them. **WARNING: that
  is the only check some commits ever get: git runs no pre-commit hook for
  `git rebase --continue`, a merge, cherry-pick or revert that completes
  without a conflict, `git am`, or a `--no-verify` commit**, and a key added in
  one commit and deleted in the next is still uploaded by the push.

Both refuse rather than pass when they cannot run their own check, never print
the matching line, and name no bypass. **There is no allowlist**: a fixture that
needs a marker builds it at runtime, because an allowlisted path is a path a
real key can be committed under; the test commits the whole tracked tree
through the scanner, which is what keeps that true. Both are enabled by the
same setup script, so they share the per-clone caveat below, and `--no-verify`
skips either.

**Two checks, and neither substitutes for the other:**

| | proves |
|---|---|
| each hook's own unit test | that hook's **logic**, and it passes on a machine where the hook is disabled |
| a CI scan of pushed commit messages | that the commit-msg hook actually **ran** |

**WARNING: WHERE THE SECOND ONE IS ABSENT, THE FIRST CANNOT COVER FOR IT.** A
trailer in a pushed commit is evidence no repo-side test can produce: the hook
test passes happily on a clone where the hook is disabled. A clone whose
`core.hooksPath` was never set runs the hook zero times, its commits reach the
landing branch carrying the trailers, and without the CI scan nothing says so
until someone reads the log. `CONTEXT.md` section 3.4 says which of the two
checks the install has.

**So the enforcement is a per-clone human step: run the setup script once, on
every machine that commits.** Where the CI scan is wanted, **WARNING: it cannot
be a daily job**: such a scan's range is the ref's PREVIOUS TIP to the new one,
so it only works on a `push` event, and any push it misses is excluded from the
next push's range too. Where the install had such a workflow and removed it,
recover it from history rather than rewriting it (`CONTEXT.md` section 3.4 names
the commit).

### 3.5 Taking a bug report: ask two questions, and keep them separate

Two questions, asked separately, on every bug report:

1. **Which environments does it reproduce on?**
2. **Which environments do you want it fixed on?**

**The second is not implied by the first, and asking only the first is the
mistake this rule exists to stop.** The two answers routinely differ, in both
directions: a bug reproducing everywhere may be wanted on the live environment
alone because a build is going out; a bug seen only live may still need the fix
on the landing branch too, or the next release re-introduces it. **Neither
answer is safe to infer** - ask, and write both down in the work order.

The answers decide the work:

- **Answer 1** tells you where to reproduce it. Reproducing it is not optional -
  it is the "validate" in section 3.1, and a report that does not reproduce is
  not a fix.
- **Answer 2** decides which branch you cut from and land on (section 3.3), and
  whether one fix or two pieces of work are needed.
- **Section 3.1 still constrains the answer.** If the fix for something wanted
  on the live branch turns out to need an interface or schema change, the rule
  wins: say so and escalate rather than landing it.

---

## 4. Where a mobile build actually lands

**One distribution channel per environment, declared as a value per environment
and nowhere else.** `CONTEXT.md` section 4 carries the table: channel, store
track, and external-tester group per environment.

**WARNING: only the live environment has a store lane at all.** The other cloud
environments distribute through a **tester-distribution service on iOS and
Android alike**, into a tester group in their own cloud project. The deploy
script's **guard matrix enforces the split in both directions**: a store target
dies on anything but the live environment, and a tester-distribution target
dies on every environment the install does not give that lane (always the
dev-machine one). The tester flow, the ad-hoc device rule and the lane's own
failure modes are section 4.4.

**WARNING: a store target also dies on any BRANCH but a release candidate**, and
the live branch only in CI: the store build is the release-candidate commit the
testers passed (`/release`), so the deploy script refuses to make one from
anywhere else. `CONTEXT.md` section 4 has the install's exact rule.

**The live environment is the sole store environment of any kind**: external or
internal, no other environment reaches App Store Connect at all.

**The external-attachment mechanism is deliberately branch-free.** The
submission lane always sets the release note; whether it *also* attaches the
external group and submits for **Beta App Review** is decided purely by whether
that environment's tester-group id is **non-empty**: the lane derives the
`groups`, `distribute_external` and `submit_beta_review` arguments (fastlane
pilot's) from that one value. So disabling external publication is emptying one
value, needing no change to the script or the workflow, and re-enabling it is
restoring that value in **three** places in one commit: the env lookup table,
the matching assertion in its test, and the table in `CONTEXT.md`. Nothing else
needs touching.

**WARNING: that one value also decides whether the lane WAITS for the store to
finish processing the build**, because the upload tool cannot distribute a build
that is still processing: an empty group id buys back the whole processing
wait, and restoring one silently costs it again. The coupling is expressed in
the lane (the wait is derived from the same boolean) rather than written down
twice, so it cannot drift - but it means restoring a group id lengthens the
native job, and the job's timeout was sized against a measurement taken with or
without that wait. **Re-measure the store lane's cost after changing one**,
rather than reading the recorded figure as still current in either direction.

**WARNING: the submission lane runs on the store path only, which is the live
environment only**; the other environments take the tester-distribution path
and never touch it. Their group ids are empty anyway - belt-and-braces behind a
guard matrix that will not route them here at all, exactly like their empty
store track. **Keep the empty values.** An environment whose lane is unreachable
today is one ruling away from being reachable tomorrow, and an empty group id is
what makes that safe by default.

**Do not add environment branching to that script and do not add an `if:` key
to the workflow step. The empty-group skip *is* the mechanism**, and it is what
lets the entire policy live in one value per environment in the env lookup
table.

Only a build that reaches the **external** group needs Beta App Review at all.
How long that review actually takes for a given app is an observation that
moves; `CONTEXT.md` section 4 says where the current measurement is recorded,
and it is not what the general mechanism implies.

### 4.1 The identity split: what is not shared, and the ONE thing that is

**Each environment ships as its OWN app identity.** Per-environment, not shared:
the bundle id and package name, the custom URL scheme, the store app record
(live environment only - the others never reach App Store Connect, and the
submission tool resolves the record from the artifact's own bundle id, so no app
record id is declared anywhere in the repo), and one Apple App ID, ad-hoc
provisioning profile, backend app registration and OAuth client per identifier
per project. The values are `CONTEXT.md` section 4.1.

Two things are **shared across every environment**, and the second is the one
that bites:

- **one build-service project**, deliberately, for all of them;
- **one `build` counter**: a single integer in the tracked version file, global
  across every environment, **not** per-environment. So **every rule in section
  4.3 applies.** **WARNING:** its owner is the build config's
  `appVersionSource: "local"` (EAS), a tracked file that CI advances.

#### Where package names differ, there is no eviction hazard. Do not re-derive it.

Where two environments do not share a package name, and the non-live one has no
store track at all, a non-live build **cannot** be published to the live track
and **cannot** evict a live release from it. The whole class - *"the newest
versionCode wins, so builds from different environments land in the same
place"* - depends on **one package name in one track**, and neither holds.

**What DOES hold, and it is the part worth carrying forward:**

- **The one shared counter is one counter.** A number consumed by any
  environment's upload is consumed for the repo. Section 4.3's receipt rules and
  the live-to-landing handoff (section 5) all rest on that.
- **But only the LIVE environment burns.** A store upload makes that number
  unusable forever on that store; a tester-distribution upload does not -
  re-using a number there is accepted, not rejected. So the *counter* is shared
  while the *irreversibility* is live-only. Section 4.3 states this as its own
  note.
- **The backmerge (section 5) must still not deploy.** The eviction is not what
  that rests on: the constraint stands on other grounds, and section 5 says what
  they are and where the install records its ruling on them. **Do not relax it
  as a tidy-up.**

If you arrive here from *"the build on the track isn't the one we shipped"*:
where only the live environment can put a build on that track, "a dev build
evicted it" is not the answer. Check the version file, the release run's
receipt, and whether the upload is still processing.

### 4.2 ONE place declares the store track

**The env lookup table's per-environment store track is the whole truth**
(`CONTEXT.md` section 4.2 names the key). The deploy script reads it at the
store dispatch and passes it to the submission tool as the track. Change it
there and nowhere else.

> **WARNING: do not add a second declaration of the track.** Where the build
> config has no submit block (EAS), this is the only place the track is stated,
> and it must stay that way. **Two declarations of one fact means every
> half-edit is a live bug**: shipping to one track while *printing* or
> annotating the other. That class is unrepresentable rather than merely
> documented - and a mirrored key, a comment carrying a value, or an
> "informational only" second copy re-creates it.

Where the live track is pinned to a pre-launch track until the first public
release, flip it **here and nowhere else**.

### 4.3 The version number: one tracked file, and what advances it

**The app's version lives in the repo.** One tracked file at the repo root holds
three integers - `major`, `minor`, `build` - and the app config turns them into
everything a store and the runtime see. **That is the whole mapping; there is no
other producer:**

| from the version file | becomes (Expo app config) | seen as |
|---|---|---|
| `major.minor.build` dot-joined | `version` | iOS `CFBundleShortVersionString` / Android `versionName` - the string a tester reads |
| `build` as a **string** | `ios.buildNumber` | iOS `CFBundleVersion` |
| `build` as a **number** | `android.versionCode` | Play `versionCode` |
| `build` as a **number** | an `extra` field | the analytics build property |

The runtime contract the analytics layer is coded against: the version property
is the full dotted **string**, and the build property is the same number as a
**number**. Two properties, not one, deliberately: an integer can be
range-filtered and binary-searched ("everything after build N") and a version
string cannot. **WARNING: nothing in TypeScript enforces that type** - the
`extra` bag is `Record<string, any>` - so it is pinned by a test instead.

**WARNING:** where the version file was adopted after builds had already
shipped, the build-number analytics series has a discontinuity at the adoption:
every earlier build reported whatever constant it carried. `CONTEXT.md` section
4.3 records it where it applies.

#### The principle: a build number names an ASSEMBLY, not a place on a branch

**A mobile build uniquely identifies the assembly, and bumps the build number no
matter which branch it happens on.** (The install's ruling, verbatim, is
`CONTEXT.md` section 4.3.)

Everything below follows from that sentence plus section 4.1's one-counter
fact, and the sentence is worth keeping because it answers the question the
rules alone provoke: *why doesn't the live branch just inherit the build number
of the landing-branch build it was merged from?* Because the number identifies
**the thing that was assembled and uploaded**, and those are two different
assemblies pointing at two different backends. A number that identified a
branch position would collide the instant two branches shipped, and **there is
exactly one counter for every environment.**

**WARNING: the counter counts *uploads to whatever channel the environment uses*,
not *store submissions***: the non-live environments do not upload to a store at
all (section 4), and the counter is still one and still shared. The principle is
the reason it works out that way: the number names an **assembly**, and a
tester-distribution build is as much an assembly a tester can be sitting on as a
store one. The tester question the principle exists to answer, *"which build are
you on?"*, is asked far more often of a non-live build than of a live one.

#### The rules

| what happened | `build` | `minor` | `major` |
|---|---|---|---|
| a run **uploaded to its environment's distribution channel** from the landing branch | +1 | - | - |
| ...from any other non-live mapped branch | +1 | - | - |
| ...from the live branch | +1 | **+1** | - |
| ...from a manual dispatch | +1 | +1 only if the ref is the live branch | - |
| a run that built nothing, or failed, or uploaded nothing | - | - | - |
| you decide the app is 2.0 | - | - | **by hand, always** |

Two escape hatches, matched **case-insensitively** anywhere in **any** commit
message in the push: one suppressing the `build` bump and one suppressing the
`minor` bump (the exact markers are in `CONTEXT.md` section 4.3). They are
independent; a live-branch push may use either, both, or neither.

**WARNING: two things about the opt-outs that no green run will tell you.**
1. **Suppressing the build bump after a real LIVE upload arms a rejection.** The
   next store upload reuses a number both stores have already burned, and it is
   refused, hours later, in a store console nobody is watching, behind a green
   release run. The opt-out is for a push you do not intend to ship. **The
   tooling obeys you; it does not second-guess you.**
   *(On a non-live branch the same suppression is merely untidy:
   tester-distribution accepts a repeated number, so two different assemblies
   end up claiming one build number and a tester can no longer tell them apart.
   Bad, not fatal; see the burn note below.)*
2. **The marker is matched in the message TEXT**, so a commit that merely *talks
   about* the opt-out - documenting it, quoting it in a changelog - suppresses
   the bump. Inherent to a text marker; stated here rather than left to be
   rediscovered.

**`build` never resets on a minor bump.** Play rejects a `versionCode` that goes
down, and resetting after a minor bump would be exactly that.

#### When it advances: a SUCCESSFUL UPLOAD, not a job finishing

**WARNING: THE RECEIPT AND THE BURN HAVE DIFFERENT SCOPES: the single easiest
thing on this page to get half-right.**

|  | scope |
|---|---|
| **the receipt**, hence the `build` bump | **every** environment. The deploy script's tester-distribution arm writes it exactly as the store arm does, so a non-live build advances the version file just like a live one. It means *"uploaded to this environment's distribution channel"*, not *"submitted to a store"*. |
| **the BURN**: the number becoming permanently unusable | **the live environment only.** Apple and Google reject a re-used build number forever. Tester distribution does not - a re-upload of the same number is accepted. |

So everything below about **burned numbers** - the two human-intervention
states, the two-pushes collision, the suppressed-bump rejection - is a **live
environment** hazard list. A non-live build cannot land you in any of them. The
reason the receipt still fires for those environments anyway is the
assembly-identity principle above, not a store constraint. Where the receipt's
variable keeps a store-flavoured name it has outgrown, `CONTEXT.md` section 4.3
says why it was not renamed; read that before assuming the name means what it
says.

The bump job runs **after** the platform build jobs and nothing depends on it:
**the build ships the *current* number, the bump prepares the *next* one, so
nobody ever tests a version that never shipped.**

**WARNING: what it keys on is the thing that matters.** A build that fails
**before it uploads** must keep its number and stay retriable *as itself*; but
once an upload has gone through, the stores reject that number forever. Those
two requirements are only distinguishable by an actual upload, so the deploy
script writes a **receipt file** at the single point where an upload is known to
have happened (after the submission lane returned 0), and each build job exports
that as an output. **The bump gates on those outputs, never on a job's
conclusion**, which is equally true of a run that built and shipped nothing. It
also uses `if: always()`, because a GitHub Actions job whose `needs` were
skipped is itself skipped: with `if: success()` one failed platform would
silently suppress the bump even though the *other* platform had already burned
the number.

**WARNING: THE STATES THAT NEED A HUMAN: THERE ARE TWO, ONE PER PLATFORM.** They
are the same shape: **the failure happens AFTER the upload**, so the number is
burned on the store, but the deploy script dies before the receipt is written,
so no bump happens and the next release reuses a dead number. The receipt is
deliberately conservative: it is written only where an upload is *known* to have
succeeded, and this is the price of that, paid on a path nothing automated can
safely recover.

- **Android: the post-upload digest check.** A verification step runs *after*
  the upload, comparing the store's stored artifact digest to the local
  artifact (the submission tool never does). If it fails, the versionCode **is
  already burned**, and the deploy script's error tells you to halt the release
  in the store console.
- **iOS: the post-upload work the lane still does.** After the binary is
  uploaded the lane waits for the build to appear and sets the release note; for
  an environment **with a tester-group id** it additionally waits on Apple's
  full processing states and submits for external review. A failure in any of
  those leaves the build number burned on App Store Connect while the lane
  returns non-zero and the deploy script dies. **Check the build's state in App
  Store Connect before doing anything else**: the upload itself may well have
  been fine.
  **WARNING: and read the inverse: on an environment with an EMPTY tester-group
  id the lane does not wait for processing at all, so a processing REJECTION
  happens entirely outside the run.** The job is green, the receipt is written,
  the version file has already advanced - and the build is dead in the console.
  **WARNING: the wait is not an acceptance check either**: it ends on a FAILED
  build exactly as on a good one, and the upload tool exits 0 either way, so it
  is an observation of a terminal state. Restoring a group id restores the WAIT,
  not a check. **A green native job means UPLOADED, never ACCEPTED.** The human
  store step in `/release` section 12 is the only place acceptance is ever
  established.

Where the deploy script's own die string is platform-neutral about this
(`CONTEXT.md` section 4.3 quotes it byte-exact), believe it on **both**
platforms.

In either case: sort the store side out, **and advance the version file by hand
in the same sitting**. Deliberately not automated: **a run that has just failed
a post-upload check is the last thing that should be trusted to update a
counter.**

#### WARNING: A BURNED NUMBER IS RECOVERED BY A NEW PUSH, NEVER BY "RE-RUN JOBS"

**This is the one to read at 2am.** It follows from where the number comes from.

The platform build jobs check out with a bare checkout, **no `ref:`**, so they
build **the pushed commit**. Only the bump job checks out the branch by name,
because it has to commit onto the branch tip. **The bump commit therefore lands
minutes *after* the push that earned it** (`CONTEXT.md` section 4.3 records the
install's measured delay), and two things follow:

1. **Two native-affecting pushes inside one build window collide.** Run A
   uploads N, writes its receipt, and bumps N to N+1. A second native-affecting
   push made *while A was still building* has a tree that predates the bump
   commit, so run B builds **N again**, and both stores reject it as already
   used. The lane fails, no receipt, no bump.
2. **Re-running a BUILD job cannot recover it.** The re-run checks out the same
   commit, reads the same version file, and is rejected identically. **It is not
   a retry; it is a second attempt at a dead number.** Recovery is a **new push**
   (which picks up the bump commit), or a manual dispatch, which takes the
   branch tip.

**WARNING: THE BUMP JOB IS THE OPPOSITE CASE, AND THE TWO ARE ROUTINELY
CONFLATED.** Re-running the **bump** job is safe and is a valid recovery: it
recognises its own bump commit by a trailer carrying the run id (`CONTEXT.md`
section 4.3 names it), adopts it, and re-dispatches the backmerge **without
consuming a second build number**. So the rule reads: *a build job's re-run is a
dead number; the bump job's re-run is a retry.* Everything above is about the
first.

**WARNING: WHICH BUTTON, THEREFORE, DECIDES WHICH RULE APPLIES.** "Re-run failed
jobs" restarts only what went red, so a failed bump alone re-runs alone and
adopts. "Re-run **all** jobs" restarts the build jobs too, which rebuild the
number already uploaded; both stores refuse it, `uploaded` comes back false, and
the bump job is then **skipped entirely** - so the recovery you reached for does
not run and the release is red for an unrelated reason.

**WARNING: a run id is constant across attempts and is why this works.**
`GITHUB_RUN_ATTEMPT` is what increments. Without the trailer, every attempt
mints a fresh successor: one uploaded assembly consumes one number per attempt,
the store versions in between never exist, and nothing goes red - every attempt
succeeds at doing the wrong thing. Pin it with a test that executes the real
step (`CONTEXT.md` section 4.3 names it).

**Operationally:** do not push native-affecting commits to a release branch
while a release from that branch is in flight - wait for the bump commit to
land, or dispatch instead. If an **upload** was rejected for a reused number,
push (an empty commit is enough); never re-run the build. If the **bump** job is
what went red, "Re-run failed jobs" is the right move once whatever blocked it
(usually a conflicted backmerge) has been cleared.

This is the cost of assigning the number at **commit time** rather than at build
time (an upload-time allocator could not collide). Its benefit is section 4.3's
whole premise: **the number is a property of the tree, readable in the repo,
reviewable in a diff.** It is **loud**: the store rejects, the lane goes red,
nothing ships silently. That is why it is documented here rather than fixed.
Making the build jobs check out the branch tip would fix the collision by
costing the property that makes the release auditable: the artifact would be
built from the tip **at checkout time**, not from the commit that triggered the
run, so "which commit is in build N" would stop having an answer the run itself
can give. **That trade is a ruling for the install's owner**; `CONTEXT.md`
section 4.3 records whether it has been made.

#### What triggers the bump, and the loop it must not create

The bump job hangs off the platform build jobs, so it **inherits their trigger**
(section 2). There is deliberately **no second predicate**: a second copy of
that decision drifts from the first.

The bump commits the version file and pushes it, which is a push to a release
branch, so **the loop is closed three independent ways, none of them
load-bearing alone**:

1. the push uses the CI provider's automatic default token (`GITHUB_TOKEN` on
   GitHub Actions), and pushes by that token create **no workflow run** (the
   same property the backmerge rests on, section 5) - never swap it for a PAT or
   App token;
2. **the version file appears in no paths filter**, so even a run that did fire
   would build nothing;
3. a `[skip ci]` marker in the commit subject.

**WARNING: LAYER 3 IS NOT SCOPED TO THE BRANCH THE BUMP WAS MADE ON, AND THAT
COSTS A WHOLE RELEASE.** `[skip ci]` is evaluated against the **HEAD COMMIT of a
push**, not against who authored it or where it was authored - and against that
commit's whole message, body included: GitHub reads `[skip ci]`, `[ci skip]`,
`[no ci]`, `[skip actions]` and `[actions skip]` anywhere in it, so a body that
merely quotes the marker suppresses the push too (GitHub Actions, measured
2026-10-11). So when a bump
commit is the landing branch's tip and the landing branch is merged into the
live branch, **the bump commit becomes the head of *that* push and suppresses the
live release entirely**: no release run, no backmerge run, no red, nothing to
notice the absence of. The push succeeds and the branch advances, deploying
nothing. A fast-forward of any size whose head is such a commit creates no run
at all (`CONTEXT.md` section 4.3 records the install's measurement). **The
window is widest exactly when you are releasing**: any native-affecting push to
the landing branch ends in a bump commit minutes later, so releasing shortly
after one is precisely when the tip IS that commit.

- **Check the landing branch's tip before a release push.** A head commit whose
  message (subject or body) carries `[skip ci]` means the push will no-op.
- **Recovery, and it is not a lesser option:** dispatch the release workflow on
  the live branch with the all-jobs filter. Every deploy job's `if:` carries a
  dispatch-and-all clause, so a dispatch force-runs everything regardless of the
  path filter, which also makes it structurally immune to section 5.1's
  empty-diff failure.
- **Never read a successful push as a fired release.** Confirm a run exists FOR
  THE PUSHED SHA. That is a different check from "the run went green", and it is
  the only one that catches this.

Do **not** repair this by dropping `[skip ci]` from the bump commit: the marker
is load-bearing elsewhere and must stay recognisable.

**WARNING: layer 2 has a cost, and it is the intended trade: editing the version
file ALONE triggers no build.** A hand-rolled `major` bump therefore ships only
when it rides along with a real change, or via a manual dispatch.

#### WARNING: THE HANDOFF: layer 1 also hides the bump from the landing branch, so the bump job DISPATCHES the backmerge

**Without this, the landing branch is blocked outright after every live
release.** Everything in this section so far is about the bump not triggering a
*build*. The same silence has a second consequence: it hides the bump commit
from the **backmerge workflow** too, and that commit is the only place the live
branch's new number exists.

**The sequence, in the order the events occur:**

1. The landing branch bumps itself to build N and sits there.
2. A release merges the landing branch into the live branch, handing N across.
3. The live release **uploads N**. Burned on both stores forever, for every
   environment: there is one counter for the whole app identity (section 4.1).
4. The bump job advances the **live branch** to N+1 and pushes it.
5. The landing branch still holds N. Its next native build uploads N and is
   **refused**.

The backmerge triggers on push to the live branch, so it runs at step 3's push,
**before** step 4's commit exists. Step 4's push is made with the default token,
which creates no workflow run. **So the one commit that carries the new number
is precisely the one commit no `push:` trigger can see**, and without the
handoff the landing branch is **guaranteed** to collide after every live
release, on both platforms.

**The fix is a `workflow_dispatch`, which is one of the two documented
exceptions to the default token's no-trigger rule.** After pushing the live
branch's bump, the bump job dispatches the backmerge (hence `actions: write` on
that job), and a following step **waits for the landing branch to actually
contain the bump commit** before the run may go green: **a dispatch is a
request, not a result**, and this is exactly the class of failure that stays
invisible until a release is rejected days later.

**WARNING: it is a DISPATCH and deliberately not a second bump written into the
backmerge**, for two reasons, the second of which is the non-obvious one:

- there stays exactly **one** implementation of the bump rules and one place
  that writes the file;
- the landing branch receives the live branch's version file by **ordinary git
  merge**, so the two branches' version-file histories stay **linear**. A second
  bump on the landing side would make them diverge, and then *every* subsequent
  backmerge conflicts on that file and fails loudly: measured in a handoff
  test, not assumed. Note the consequence for any hand-repair: **set the landing
  branch to the live branch's current version file exactly**, do not invent an
  intermediate value.
  **WARNING: one generalization of that instruction.** It is right whenever the
  live value dominates field-wise, which is the normal case. It is wrong in
  exactly one situation: if the landing branch raced **ahead** on `build` (two
  non-live native uploads inside one release window), the live value would move
  the counter **backwards** over a number an upload already consumed. The
  general rule, and what CI applies automatically (below), is the **field-wise
  maximum** of the two, each of `major`/`minor`/`build` taken independently.
  Hand-repairing to the live value exactly remains correct advice; just check
  `build` first.

**What this does NOT fix, stated so nobody reads more into it than is there.**
Two things, neither reachable from the live-to-landing direction:

- **The reverse direction.** The landing branch's own bumps reach the live
  branch only through the human release merge. So immediately after a live
  release both branches hold the same *next* number, unconsumed; a **hotfix**
  cut straight off the live branch while the landing branch also ships native in
  the same window can still have one of the two rejected. Same in-flight-window
  race as "A BURNED NUMBER IS RECOVERED BY A NEW PUSH" above: loud, store-side,
  recovered by a new push.
- **Every other mapped branch.** A release from one uploads, consumes a number
  from the one shared sequence **globally** (section 4.1) - burning it only where
  that environment is the live one, per the receipt/burn table above - and bumps
  its own branch alone, unless the install routes that branch's bump to another
  branch; no other branch learns. There is no backmerge on those edges.
  `CONTEXT.md` section 2 says which such branches exist on origin, what a push
  to each one costs, and where each one's bump lands.

##### The divergent counter: resolved automatically

Two branches each mint a successor to the version file from a common base, so
the dispatched backmerge hits a version-file conflict. **It is resolved
automatically rather than by hand.**

**The backmerge COMPUTES the version file instead of merging it as content.**
When the version file is the **only** conflicted path, the workflow reconciles
it via the bump script's reconcile mode - **field-wise maximum** - logs both
inputs, the result and which side won each field, records that in the merge
commit, and completes the merge. **The rule stays in the bump script alone**, so
there is still exactly one implementation of the version rules.

**WARNING: the fence is the whole point, and it is not a blanket
auto-resolve.** Any other conflicted path, or the version file **plus** anything
else, still fails loudly, with the same guidance output. The version file is the
one file here whose correct merged value is **computable** from the two sides;
for every other file "what did the author mean" needs a human. **Both halves are
pinned by a test** that asserts the call and the fence over the real workflow
YAML, replays the conflict, asserts that the fix-removed arm still reproduces
it, checks the resolved **value**, and proves the fence holds in both
directions.

**WARNING: do not re-file this as a timing bug.** The competing bumps arrive by
unrelated routes with nothing in common but their shape: one from a **human
re-run of a failed platform job**, one from a hotfix committed **single-parent
straight off the live branch** with no overlap at all. **A fix scoped to any
release window catches one and misses the other**; this one is at the merge
point, where both necessarily arrive.

Still true: in that window both branches may have *already* uploaded the same
number (the reverse-direction race above), which this does not address. And a
**hand** resolution still means a human push to the landing branch, which
**does** deploy the shared-dev environment, so time it deliberately.

#### WARNING: the build config and the version file are ONE decision in TWO files

The version file is authoritative **only because** the build config says
`"appVersionSource": "local"` (EAS). Flip that to `"remote"`, or restore
`autoIncrement` on the store profile, and the build service's server-side
counter silently becomes authoritative: every number the app config computes is
overwritten at build time, the version file becomes decorative, CI keeps
incrementing a file nobody reads, and **nothing fails.** **The build config is
comment-less JSON and cannot warn its own next editor**, so the warning lives in
a test, which is the only thing that makes that flip fail rather than ship.

#### The gates

Four tests pin this section: the build-config coupling and the produced fields
**and their types** (by evaluating a copy of the app config beside a *mutated*
version file, so it proves the factory really reads the file); the branch-to-
field table with both opt-outs proven to suppress **and** proven not to when
absent, and that `build` never resets; what a push actually fires, in both
directions, including version-file-alone means **no build**; and the handoff
above, with each workflow-file assertion re-run against a mutated copy so **a
grep that stopped matching cannot pass as an all-clear**, plus a replay of whole
release cycles whose **positive control** is that deleting the handoff
reproduces the outage. `CONTEXT.md` section 0 names the files.

**WARNING:** where they run in the install's scheduled gate rather than on push
(section 3.2), they catch a break on the default branch within one schedule
period rather than within minutes of the push, and catch nothing at all on a
feature branch until it lands. Run them locally when you change their subjects,
or dispatch the quality workflow on your branch.

### 4.4 The tester-distribution lane: both platforms

**How it is wired.** Three values per environment in the env lookup table: the
per-platform **app ids** (which are per-app ids, *not* the bundle id and *not*
the project id) and the tester-group alias. The deploy script hands the artifact
to the distribution CLI, authenticated with that environment's own admin-SDK
key. Its release note names the uploaded build, read from the artifact itself,
so a tester can tell two builds of one version apart (section 4.5).

**WARNING: an empty value means "this environment has no lane", so it is also
what an unfilled app id looks like.** The distribution step therefore **dies**
on an empty app or group rather than uploading a build that reaches nobody. Keep
that guard even though the guard matrix already restricts the lane to the right
environments: **the two catch different mistakes.**

**WARNING: WHICH ENVIRONMENTS THE LANE SERVES IS A PER-INSTALL FACT, AND IT
MOVES.** The non-live environments are the usual answer; a live environment may
also be given the lane deliberately, for a release-regression pass on a build
carrying the live identity. Where that is done, the relaxation is gated on the
ad-hoc signing profile and the store guard is left exactly as it was, so the
invariant "no non-store build can reach a store" is untouched while the POLICY
"the live environment ships only through the stores" is what bends. Read
`CONTEXT.md` section 4 for the install's map rather than assuming the usual
answer - and note that the moment a live environment gains a lane, an empty
value there stops meaning "no lane by design" and starts meaning UNPROVISIONED,
which is a change to what the paragraph above is telling you.

**WARNING: iOS ad-hoc has a structural cost that Android does not, and it
surprises every new tester.** This channel can only install an **ad-hoc** iOS
build (hence a sideload signing mode is *required* with it, and a release-signed
build is rejected). **Ad-hoc profiles embed an explicit device list**, so for
each NEW iOS device: register the UDID, **then rebuild and re-upload** - the
device cannot install any build made before it was registered. Already-
registered team devices skip all of this. Apple's ceiling is 100 devices per
device class per membership year, and removals only take effect at the annual
renewal reset. Android testers just accept the invite and install.

**Symptom worth recognising:** an ad-hoc profile that has expired, or a build
predating a tester's UDID registration, fails at *install* time on the device,
not in the release run, which stayed green because the upload genuinely
succeeded. **A green release run is not evidence that anyone can install the
build.**

**What this lane does NOT do:** it does not touch any store (section 4), and it
does not **burn** a build number (section 4.3), though it does advance one.

---

### 4.5 The store release note is a FIXED STRING

Every store release ships one constant, quoted byte-exact in `CONTEXT.md`
section 4.5. It lives in **one** place in the deploy script, and one helper puts
it on disk for whichever uploader is about to read it.

**WARNING: nothing computes it, and nothing may start computing it.** A note
generated from commit messages couples every commit message to a public text
whose store reader learns nothing from it, and a commit message is not written
for a generator to read, so **a half-restored generator would ship an empty note
rather than fail.**

**WARNING: something must still WRITE it.** Each uploader requires the file to
exist and reads whatever it holds. **Deleting a call to the note writer does not
remove a release note: it ships an empty one, which no store rejects and no test
sees.**

**Caps do not bite at a short fixed string** (Play 500 characters; TestFlight
4000 **bytes**, counted as bytes by the upload tool itself, fastlane pilot,
which is why a character count is not enough). **WARNING: keep any replacement
short**: an over-cap Play note is silently truncated on the live lane, with no
repair short of rewriting history.

**To change the wording**, edit the one constant and nothing else.

**The tester-distribution lane (section 4.4) ships the constant only as a
fallback.** Its note is one line naming the uploaded build - version,
environment letter, commit (marked when the build tree was dirty), build date,
branch - read out of the ARTIFACT's embedded app config by the provenance gate's
own member reader, never from the checkout doing the upload: its reader is a
tester telling two builds of one version apart, not a store reader. An artifact
that carries no build provenance, or whose config cannot be read, gets the
constant and ONE warning line saying why, so **that note is never empty
either**, for the reason above. `CONTEXT.md` section 4.5 has the format, the
helper and the test that pins both regimes.

**To fix the note on an ALREADY-published Play release**, a notes-only lane
exists for exactly that: **run by hand, never from CI**, because it opens its
own store edit and two open edits collide. **WARNING:** nothing builds the
metadata directory for that lane, so write it yourself first - the recipe is in
`CONTEXT.md` section 4.5. A TestFlight note is edited by hand in App Store
Connect; there is no lane for it.

## 5. The backmerge: live -> landing, and release candidate -> landing and live-copy

One workflow carries a commit that lands on a release line to every branch that
must hold it too, with **one mode per source branch** and one merge
implementation behind both (`CONTEXT.md` section 5 names the files):

- **live mode**, on **every push to the live branch**: the live branch is merged
  into the landing branch. Everything in this section above section 5.1
  describes it.
- **release-candidate mode**, on every push to a release-candidate branch:
  section 5.2.

The live mode's rules:

**It is UNCONDITIONAL, and that is a ruling rather than an implementation
detail** (the install's ruling is quoted in `CONTEXT.md` section 5): one
trigger, one job, no `if:`, no `needs:`, no `workflow_run` gate. **The
unconditionality is deliberate and load-bearing.**

**WARNING: the practical consequence: a failed or skipped release must still
reach the landing branch.** Anyone tempted to "fix" something by making the
backmerge wait on a successful release, or by gating it on the release workflow
at all, is proposing to reintroduce exactly the divergence it is built to
prevent: **a live commit sitting on one branch only, invisible, behind a green
check.** That fix is ruled out. See section 5.1 for the defect that tempts
people into it - **fixed on the release side, which is where this section
requires it to be fixed.**

**WARNING: it runs TWICE per live release, and the second run is the
load-bearing one.** The release's bump job dispatches this workflow after it
pushes the live branch's new version file: the only way the landing branch ever
learns the new build number, because that commit is itself a default-token push
and no `push:` trigger can see it. Section 4.3's *THE HANDOFF* has the full
account. Two things follow for anyone editing this workflow: **the
`workflow_dispatch:` key is not a convenience handle and must not be removed**,
and **renaming this workflow requires updating the dispatch call in the release
workflow in the same commit**. Both breakages are silent here and surface as a
store rejection at the next release. Note that the dispatch does NOT gate the
backmerge on release success: the first, push-triggered run still happens
unconditionally, exactly as the ruling requires; the dispatched run is an
additional pass carrying one more commit.

**Why it exists:** a fix committed straight onto the live branch lives only
there until something carries it across, and the landing branch knows nothing
about it meanwhile. Cut the next release branch or merge from the landing branch
inside that window and **the fix vanishes silently** - for a store-track fix,
that means shipping a regression to the public. The workflow makes that
divergence **structurally impossible** instead of something a human has to
remember.

**It syncs the branches; it deliberately does NOT deploy.** The release workflow
triggers on push to the landing branch and deploys the shared-dev environment,
native builds included, so an automatic build would fire right after every live
release.

**WARNING: THE NO-DEPLOY PROPERTY DOES NOT REST ON THE EVICTION HAZARD, AND IT
IS NOT TO BE RELAXED ON THAT HAZARD'S ABSENCE.** Where package names differ, the
eviction is unreachable (section 4.1). **But the property has at least one other
live effect**, unrelated to identity: a bookkeeping merge that carries no new
work would otherwise fire a **full deploy** - functions, hosting, and native
builds uploaded to the testers' group, burning a build number on the way
(section 4.3). **Whether the no-deploy property is retained on those grounds is
a policy question** for the install's owner; `CONTEXT.md` section 5 records
whether it has been ruled. Until it is, the property stands exactly as built,
and the sections below describe live machinery. **"The eviction cannot happen" is
not sufficient grounds to swap the token or add a trigger**: it retires one
reason out of at least two.

**The mechanism that prevents it:** the backmerge pushes with the CI provider's
**automatic default token** (`GITHUB_TOKEN`), and events triggered by that token
*do not create new workflow runs* (only `workflow_dispatch` and
`repository_dispatch` are exempt). **Never swap it for a PAT, a GitHub App
token, a deploy key, or a create-pull-request-style action configured with
one**: every one of those *does* trigger workflows, and doing so silently arms
the clobber. Ordinary landing-branch pushes from feature work still deploy
normally.

Related properties, each deliberate: the workflow declares `contents: write`
(and `actions: write`, for section 5.2's dispatch) where the repo's default
workflow permissions are read-only (measure it, do not assume it; `CONTEXT.md`
section 5 records the install's); on conflict it **fails loudly** naming the
conflicting paths rather than skipping or auto-resolving (**a silent skip would
recreate the exact divergence it prevents, behind a green check**); and it never
force-pushes or resets the landing branch, which is shared trunk. Resolving such
a conflict by hand ends in a **human** push to the landing branch, which *does*
trigger the deploy: the workflow's own error output says so.

**WARNING: ONE FENCED EXCEPTION to "fails loudly".** When the version file is
the **only** conflicted path, the workflow does not merge it as content; it
**computes** it (section 4.3's reconcile). Everything else in the sentence above
holds: any other path, or the version file **plus** anything else, still fails
loudly with the same guidance. **The comparison is exact string equality against
the whole conflicted set**, so a same-named file in a subdirectory does **not**
qualify. A `major` disagreement between the two sides is **refused** outright -
taking it field-wise would pair one side's hand-chosen `major` with the other's
`minor`, a version nobody chose - and falls through to the loud failure.

**Branch protection changes this, and the failure will read as a git problem.**
Where the plan or the repo's settings make branch protection unavailable,
nothing rejects the backmerge push. **WARNING: whoever enables protection on the
landing branch must revisit this workflow:** a required-review or
required-status-check rule would start rejecting the bot's push, and the default
token is not a repo admin, so it cannot bypass one. **The workflow would begin
failing on its first run after the change** - loud, but easy to misread as a git
problem rather than a policy one. `CONTEXT.md` section 5 records the current
state.

**The observable to re-check after any change to the token, the trigger or the
push step:** a live push produces a backmerge run and a release run for the live
branch, and **no release run appears on the landing branch.**

### 5.1 A release's path filter must diff against the pushed branch's own previous tip

**The release workflow passes the pushed ref as the path filter's `base:`.**
That one line reads like boilerplate; this section is what it buys, so that
nobody deletes it.

The release workflow decides what to deploy with `dorny/paths-filter`. With
**no `base:`**, that input's documented default (quoting the action's own
`action.yml`) is: *"Defaults to repository default branch... If it references
same branch it was pushed to, changes are detected against the most recent
commit before the push."* So, with the default branch being the landing
branch:

- a push to the **landing branch** -> base is the pushed branch -> the filter
  diffs against the commit before the push. **Correct**, which is why the
  default goes unnoticed.
- a push to any **other release branch** -> base is the landing branch -> the
  filter diffs the release branch **against the landing branch**, not against
  the previous release tip.

Two things follow. First, structurally, **any change already present on the
landing branch reads as "nothing changed"** on a release push, whatever it
actually touched. Second, the sharp edge: **the backmerge and the release fire
on the very same push**, so they race. If the backmerge advances the landing
branch first, it then contains everything the release branch has, **the diff
comes back empty, and every deploy job is skipped while the workflow reports
green.** A release that silently deploys nothing, behind a check mark.

**The fix is on the release side: diff against the pushed branch's previous
tip.** Passing the pushed ref as `base:` makes base and head equal inside the
action, which is its documented switch to the before-SHA path - verified by
reading the pinned dist, where equal refs resolve the base to the push's
`before` SHA (`CONTEXT.md` section 5.1 names the pin read). The landing branch's
behaviour is unchanged (it takes that path by coincidence of being the default
branch); the fix makes it true **by construction** on every release branch, and
**removes the race entirely rather than arbitrating it**. The tempting
alternative - gating the backmerge on release success, or serialising the two -
is **ruled out** by the unconditional ruling in section 5: a failed release must
still reach the landing branch.

**What it looks like when it fires.** A merge into a release branch is pushed
and the release run completes **green with every deploy job skipped** (a job
outside the path filter still runs): no functions deploy, no web deploy, no
native builds, no store submission. The change-detection log line names the two
refs it compared and every filter reads false. It does **not** need the
backmerge to win the race: **a fast-forward merge makes the release branch
byte-identical to the landing branch at push time, so the diff is empty on its
own.** The race is one way to reach the empty diff; **an ordinary merge-based
release is the other, and it is deterministic.** This is not
intermittent-by-timing; it fires on the most common release path there is.

**WARNING: a run that skips every DEPLOY job is not by itself evidence of this
bug**: a push touching only agent or docs paths skips them *correctly*. **Read
the change-detection refs in the log before diagnosing** (`CONTEXT.md` section
5.1 quotes the line).

### 5.2 The release-candidate mode: the candidate reaches the landing branch, then the live-copy branch, on every landing

**During a release window, every push to the release-candidate branch** (the
cut, each fix landing, an approved cherry-pick) runs the backmerge workflow in
its release-candidate mode, which does the two things `/release` section 10
requires after every landing, in this order:

1. **merges the candidate into the landing branch**, so no fix found in testing
   sits on the release candidate only;
2. **moves the live-copy branch to the candidate and redeploys it**, so the
   live-copy environment tests what is about to ship.

**The live-copy branch only ever holds commits the landing branch has**, which
is what lets the live-copy promotion keep fast-forwarding after the window. That
is why the order is fixed: when the landing-branch merge fails, the live-copy
branch is not touched, and the run says to re-run once the landing branch holds
the candidate. For the newest release candidate on the remote only:

| the live-copy branch... | the job |
|---|---|
| carries a commit the candidate lacks that is not a version bump (the landing branch was promoted to it during the window, or something was pushed to it) | **refuses, loudly**: the live-copy environment is not running the candidate, and only a person may decide what it runs instead |
| already contains the candidate's tip | leaves it; redeploys it only when no release-workflow run on it has its tip as head (an earlier run moved it and its redeploy failed) |
| is an ancestor of the candidate's tip | **fast-forwards** it |
| carries version bumps the candidate lacks, and nothing else | **merges** the candidate into it, with the same fence and reconcile as every backmerge, merges THAT merge commit into the landing branch, and only then moves the live-copy branch to it |

A push to an **older** release candidate leaves the live-copy branch on the
newest one and is still merged into the landing branch.

**The live-copy promotion refuses while a window is open** - while the newest
release candidate is not yet contained in the live branch - unless its explicit
flag is given (`CONTEXT.md` section 2), because promoting the landing branch
mid-window is exactly how the live-copy branch comes to carry commits the
candidate lacks.

**WARNING: a landing that changes a workflow file cannot be pushed by the
default token**, a fast-forward to commits already in the repository included,
and no permission grants it (GitHub Actions, community-reported; `CONTEXT.md`
section 5.2 says whether the install's runs have shown it). That is an accepted
limit, not a gap to close with a person's credential: the job recognises the
refusal, never retries it - a retry is refused identically - and reports it as
an explicit, actionable refusal, **"downstream this landing by hand"**, naming
the workflow files and the commands for every edge still owed. It is the
expected outcome of a window's FIRST landing whenever the landing branch changed
a workflow since the live-copy branch was last promoted; landings that leave the
workflows alone go through unattended.

**WARNING: the redeploy is a DISPATCH, and it costs a whole deploy.** The job's
pushes use the default token, so the live-copy push starts no run; the job
dispatches the release workflow on the live-copy branch instead (one of the
token's two documented exceptions), then waits, bounded, for a NEW run whose
head is the commit it pushed, and goes red if none appears or if it could not
read the run list before dispatching - **a dispatch is a request, not a
result.** A dispatch carries no before-SHA, so the release workflow's path
filter cannot choose for it: it runs with the all-jobs filter, and every landing
that moves the live-copy branch redeploys it whole, both native builds and one
number from the shared counter included.

**The landing-branch merge deploys nothing**, by the same default-token rule as
the live mode. **WARNING: so the shared-dev environment does not receive the
candidate's fixes on the next ordinary landing-branch push either**: the release
workflow's path filter compares only that push's own before and after, and the
backmerge's merge sits before both. A lane redeploys them only when a later push
touches that lane's paths. The merge carries **one rule the live mode does
not**: where the install commits a gate-outcome file (`CONTEXT.md` section 5.2
names it), it keeps the TARGET's side, conflicted or not, because the
candidate's copy attests a gate run on the candidate and is a stale green
anywhere else (`/release` section 10). The version file conflicts by design
here too and is computed exactly as in the live mode.

**WARNING: the job reads only branch tips, never the pushed SHA**, because
several pushes to the candidate start no run: a `[skip ci]` head, and the
release workflow's own version bump after a tester build of the candidate,
which is a default-token push. Whatever they carried rides the next run - the
next real push, or a dispatch of the backmerge workflow on the candidate's ref.
The live-copy redeploy is a dispatch, and skip markers apply only to push and
pull request events, so it starts even when the live-copy branch's new tip is a
`[skip ci]` commit.

**WARNING: the workflow file is read from the PUSHED commit**, so a release
candidate gets this mode only if its own tree carries the workflow and its
script. A candidate cut before they landed stays inert until both are carried
onto it - inside a window that is an approved cherry-pick (`/release`, the
release window's rule 2).

**WARNING: one concurrency group per source branch, and the live branch's keeps
its name.** A run still pending when a newer one queues in the same group is
cancelled, which is harmless only within one branch, where the newer run merges
the tips it fetches. Across branches it is not: a candidate push would cancel
the live mode's dispatched run that the release's bump job is waiting on, and
the newest candidate's run would cancel an older candidate's whose fix it never
merges. Runs for different branches may therefore run at once; their
landing-branch pushes retry on rejection.

---

## 6. How a build gets its configuration

### 6.1 The source files

**There is no persistent `.env` in the repo.** A set of tracked source files is
the truth, and the dev and deploy scripts **materialize `.env` from exactly one
of them per invocation, then delete it** (the deploy script on exit via a
top-level trap; the dev script on teardown, restarting the bundler with a
cleared cache when the target environment flips).

**WARNING: a `.env` the deploy script finds already present is a running dev
stack's, and the deploy script never takes it over.** The stack keeps that file
for its whole life and its bundler reloads the env whenever the file changes.
So the deploy script writes a `.env` only where none exists and deletes only the
one it wrote; one that is byte-identical to what the build needs is used as it
stands and left in place, and a different one is refused before it is touched,
naming the dev script.

The shape, which is what matters:

| source file | feeds |
|---|---|
| the dev-machine environment's file | local dev and dev-machine native builds; the web bundle and native share it |
| one file per cloud environment | the **native** build for that environment: backend public config, the environment selector, and the telemetry slots |
| one web file per cloud environment, where the install ships a web bundle | the **web** bundle for that environment: the backend subset only, **no telemetry** (analytics and crash reporting never ship to web) |

The materializer copies a cloud environment's file verbatim. For the
dev-machine environment it additionally rewrites the functions URL to this
machine's host and appends the dev stack's emulator ports; that mechanical
detail lives in the script's header, next to the code that does it. `CONTEXT.md`
section 6.1 names the files.

**Never create `.env.local` or `.env.production`.** Those are the framework's own
higher-precedence dotenv files, and the footgun this kills is **a stale local
override silently shipping emulator URLs into a cloud bundle**. `.gitignore`
lists both defensively, in case something regenerates them.

### 6.2 Telemetry slots: ONE project per sink, separated by an `environment` label

**A telemetry sink can be a single project shared by every environment**, with
the environments separated by an **`environment` tag on the events** rather than
by having a project each. Where that is the posture, the cloud environments'
source files carry the **same** key or DSN, byte-for-byte, and what separates
them is the tag the client passes at init, sourced from the one selector.
`CONTEXT.md` section 6.2 says which sinks are configured that way, and what each
environment's slot holds.

**WARNING: an environment whose telemetry slot is EMPTY reports NOTHING, and
says nothing about it.** Where the enable gate is a truthiness check, **every
crash, captured error and breadcrumb is a silent no-op**. That cuts both ways,
and both directions are load-bearing:

- a non-empty slot on a non-live environment is what keeps it reporting at all,
  and the `environment` tag is what keeps its events from being
  indistinguishable from real user events;
- an intentionally **empty** slot is a **second, independent false clause**
  beside the environment gate, and it is not an unfinished fan-out. It satisfies
  section 6.5 (which requires the key to be **present**, not to carry a value)
  while making a *partial* environment override - some keys arriving from the
  repo, others not - unable to put a live telemetry key beside a true
  "real backend" flag. **Nothing sends from that environment either way; that is
  what a redundant layer looks like while it is working.**

**Source-map upload is a separate axis from reporting, and only it needs a
token.** The upload token is a build-machine CI secret, per environment; the
deploy script skips the upload when the DSN **or** the token is empty, so an
environment with no token still reports normally with **unsymbolicated**
frames. Nothing in the runtime reads the token. **No code change turns
symbolication on later, just the secret.**

**WARNING: a key pointing at a project that does not exist sends every event
nowhere, silently** - the same failure as an empty slot.

Three consequences, each of which someone will otherwise rediscover the hard
way:

- **A telemetry key does not identify an environment.** What does is the
  `environment` super property on every event, read from the one existing
  selector. It rides alongside a build-type property (debug vs release), which
  is a **different axis**: a release build routinely points at a non-live
  backend. **Do not introduce a second environment selector for telemetry.**
- **WARNING: a dashboard tile must filter *"`environment` is not set OR
  `environment` = X"*, NEVER `environment = X`.** No event emitted before the
  property was introduced carries it at all, so the naive filter silently drops
  the entire history. (Same trap as any boolean flag added later, where
  `= false` excludes every person who has no value.) **The proof a tile is
  filtered right: no historical headline number moves** when the filter is
  applied.
- **A dev-machine build sends nothing, for TWO independent reasons, and both are
  load-bearing.** The enable gate needs a non-empty key **and** a real backend
  (plus a release build); the dev-machine environment fails both. Pin the
  backend clause with a client probe that supplies a non-empty key **on
  purpose**, so that it proves the *gate* rather than the config. The empty key
  is the second layer. One consequence worth stating: a local checkout, a
  developer's transient `.env`, and every e2e materialization hold **no live
  telemetry credential.**

**Knock-on for section 7's provenance gate.** A key **shared** across cloud
environments is a **positive** marker (the target environment's key must be
present in the artifact) but contributes nothing to the **negative** half, since
the gate exempts a marker shared with the target. So cross-environment
discrimination rests on the markers that are genuinely per-project - and an
environment whose slot is empty emits **no marker at all**, which means a cloud
environment's key is **not** exempted when its artifact is scanned for foreign
markers. **For an environment that runs the gate's negative half only, an empty
slot therefore *increases* discriminating power rather than reducing it.** The
per-environment marker census is a value: `CONTEXT.md` section 6.2.

**Two classes of secret are deliberately *not* env-source values, and must never
become ones**: a **build-time** upload token, which reaches a build from the
build machine's environment, and a **server-side** operations key, which comes
from a secret manager. **The allowlist in section 6.4 is precisely the guard
that should stop anyone putting either into a source file.**

The per-environment **admin-SDK** keys are the same shape: no single constant
exists; a helper globs the key file for the environment's project out of a
credential store that lives OUTSIDE the checkout, which CI materializes from a
per-environment repo secret.

### 6.3 The repo is the env source, explicitly delivered and enforced

Every native build is a **local** build. **The environment is chosen only by
which source file gets materialized**: one build profile serves every cloud
environment, there is no push of variables to the build service, and there are
no named build "flavors".

**State the mechanism, never the assumption.** Assuming how the values arrive is
how a build ships the wrong configuration, and the provenance gate exists to
catch exactly that:

> **WARNING: an EAS build profile that names no `environment:` does NOT opt out
> of the build service's Environment-Variables store.** With no `environment:`
> named, eas-cli *infers* one from the profile's **shape**, mapping YOUR profile
> names onto the SERVICE's own environment names, which are not yours
> (`CONTEXT.md` section 6.3 has the install's inferred mapping) - and injects that environment's stored variables **above** the repo
> `.env`. Worse: the `.env` file **never enters the local-build sandbox at all**
> (it is gitignored, and there is no `.easignore` exemption), so anything the
> store does not supply falls through to **hardcoded defaults in source**. So a
> store holding a retired project's config and **no environment selector** makes
> *every* release build - each cloud environment alike - ship with the retired
> project's config and, worse, **no environment label**. Where an absent selector
> resolves to the dev-machine environment, that arms the emulator gate and points
> every backend service at cloud hostnames on emulator ports: every request
> black-holes, anonymous sign-in never completes, nothing reaches any project.
> **The regression is the missing label, not the legacy values**, which is why
> the provenance gate (section 7) asserts the embedded environment selector and
> not only the backend markers. `CONTEXT.md` section 6.3 records where the
> install's account of such a failure lives.

Two in-repo mechanisms carry env delivery, and they are what makes it sound:

1. **DELIVERY**: the deploy script exports the materialized `.env` into its own
   process before invoking the build. The local-build plugin spawns the build
   with `{...serviceEnvVars, ...process.env}`, so **the parent shell's values
   structurally outrank anything the service injects** - and, since the file
   itself never reaches the sandbox, that export is the **only** channel by
   which public env values reach the bundle at all.
2. **PROOF**: the provenance gate inspects the finished artifact and fails the
   build on any foreign environment identity (section 7).

Purging the store and pinning every build profile's `environment:` explicitly
are both worth doing, and **neither of them is a durable guarantee**: a store
can be repopulated from a web UI in thirty seconds, leaving no trace in the
repo. **The export and the gate are what survive that.**

> **WARNING: read any "what stays / what goes" list as a claim to re-verify, not
> as a fact.** Such a list is written once, at a migration, and then decays
> every time something else leaves; nothing flags it when it does. `CONTEXT.md`
> section 6.3 carries the install's list. **When you remove something from the
> build service's side of the boundary, go and correct it.**

### 6.4 The env export allowlist is a blast-radius control

**The exporter refuses any key that is not the framework's public prefix, and
that refusal is a security control, not tidiness. Do not relax it as a matter of
style.**

The reason is the precedence that makes the function work at all. The file is
exported **wholesale** into the local build, and the build CLI hands that
environment down to gradle, xcodebuild, the bundler and every other child
process. **With no key filter, any identifier in the file becomes an exported
variable in the build**, so a single `.env` line could set `PATH`, `LD_PRELOAD`,
`NODE_OPTIONS` or `HOME` and take over the build, or carry a service-account key
into every child. Fed a hostile file, an unfiltered exporter exports
`LD_PRELOAD` (the next exec's `ld.so` complains about it) and leaks an API key to
children (`CONTEXT.md` section 6.4 records the install's measurement).

The allowlist is the right shape because the exported environment has exactly
**one** legitimate consumer: the framework inlining its public-prefixed values
into the JS bundle. Nothing else in a build is supposed to be configured from
this file, so **a non-public-prefixed key is always either a mistake or an
attack**, and the refusal costs no legitimate configuration.

Under the deploy script's `set -euo pipefail` this refusal **aborts a real
build**, which is intended: **a half-delivered environment is the failure mode
the function exists to prevent.** If a build ever legitimately needs some other
variable, **export it from the calling script**; do not widen the allowlist to
smuggle it in through a file that is read wholesale.

The other two refusals (a line that is not `KEY=VALUE`; a *quoted* value) and the
reason the function cannot use `source`/`set -a` are mechanical properties of the
implementation, documented at the function itself and pinned by a test **whose
negative controls demonstrate the failure modes rather than merely asserting the
happy path.** `CONTEXT.md` section 6.4 names the function, the prefix and the
test.

### 6.4b The FUNCTIONS deploy has no dotenv channel at all

Everything in sections 6.1-6.4 describes how configuration reaches a **client**
bundle: web or native. **None of it applies to a functions deploy**, and the
difference matters because the natural assumption is wrong in a way that fails
*silently*.

The deploy script materializes `.env` and exports it on exactly two paths: the
web deploy and the mobile build. The functions deploy calls **neither**. So the
environment selector does not exist in the functions deploy, and section 6.4's
allowlist is not the obstacle: **there is no channel for it to filter.**

**WARNING: and a variable invented for the purpose would reach nothing,
silently.** firebase-tools discovers functions by spawning the built module and
reading the manifest it prints, and it builds that child's environment as an
**allowlist, not an inheritance** (`CONTEXT.md` section 6.4b cites the version
and the lines read):

```js
const env = { ...envs, FUNCTIONS_CONTROL_API: "true", HOME: process.env.HOME,
              PATH: process.env.PATH, NODE_ENV: process.env.NODE_ENV,
              __FIREBASE_FRAMEWORKS_ENTRY__: process.env.__FIREBASE_FRAMEWORKS_ENTRY__ };
```

`process.env` is never spread in. So even an `export` the deploy script already
makes does not reach discovery *by inheritance*, and an invented
`<APP>_ENV=<environment>` would reach nothing at all: **the reading code would
fall through to its default on every real deploy while passing every local test
that ran with the variable set.** That is a false green of the same family as
section 6.3's: **the mechanism looks verified because it was verified in the
wrong environment.**

**What does arrive comes from the CLI itself**, derived from the resolved
`--project` target: it loads the project's own env and spreads `FIREBASE_CONFIG`
and `GCLOUD_PROJECT` into the environment passed to discovery. `GCLOUD_PROJECT`
is also on the CLI's **reserved-key** list, so a user `.env` cannot shadow it.

**Therefore: the project id is the only sound env channel into a deploy-time
function option** - and a sound one, since a credential can only mint tokens for
its own project, so **the deploy is already pinned to the id being read.** The
env lookup table is the environment-to-id map.

Where a function option must vary per environment (a trigger's memory, for
example), **make it fail safe UP**: only a **positive match on a known non-live
project id** lowers the ceiling, so an unrecognized id, a rename, or a new
environment gets headroom rather than a cliff. Gate it with a probe that
**reproduces the discovery environment offline** (`env -i` scrubbed to exactly
the allowlist above) instead of describing it. `CONTEXT.md` section 6.4b names
the install's consumer, its values and its sizing measurement.

### 6.5 The fan-out invariant

**Every consumed public env key must appear in EVERY source file that feeds a
NATIVE build, empty when deferred (`KEY=`), never omitted.**

**Why an absent key is dangerous where an empty one is safe.** A key the repo's
file does not define is not in the materialized `.env`, so the exporter cannot
export it, **so the repo outranks *nothing* for it.** Whatever supplies it
instead (a build-service leftover, a stale shell variable) rides in **unopposed
and unmarked**, and the provenance gate has no marker for a key it does not know
exists. That is exactly the shape of the failure in section 6.3. The subtlety
that makes the rule work: **an empty value is still a *present* key** in
`process.env`, so it still wins. **Deferring a key means writing it empty, not
leaving it out.**

(Where a config module throws at startup naming the missing variable, a
*backend* key at least fails loudly rather than silently defaulting to a legacy
value. **Other keys have no such guard.**)

**The scope test is "does this file feed a native build", and nothing else.**
Two carve-outs follow from it, and one tempting mis-scoping does not:

- **The web sources are exempt.** They feed a plain export, which never invokes
  the native build service, so no build-service environment is resolved and
  **nothing can ride in unopposed**. Independently, telemetry never ships to
  web: the bundler resolves no-op web siblings and a verify script enforces it,
  so adding telemetry slots there would describe a world the bundle split
  specifically prevents.
- **Runtime-supplied keys belong in no source file.** Keys exported per-process
  by the dev or e2e runner, and emulator ports appended to the materialized
  `.env` by the materializer, are never inlined *from* a tracked source, so
  **their absence is correct: writing them in is the bug, not the fix.**
  `CONTEXT.md` section 6.5 lists them.
- **WARNING: the dev-machine source is NOT exempt.** A dev-machine native build
  runs the exact injection path this rule exists for. The tempting
  counter-argument - *"telemetry is off there anyway"* - is about the wrong
  layer: **that is what the app *does with* a key at runtime, while this rule is
  about what gets inlined into the artifact.** So its telemetry slots are
  **present and empty**.
  **WARNING:** where that environment is the **only** one whose slot is empty,
  do not read it as "like every other environment's unprovisioned slot": it is a
  deliberate posture with a second-layer argument behind it (section 6.2).
  **WARNING: PRESENT is the whole requirement; a VALUE is not.** This bullet is
  routinely misread as demanding that those slots be *filled*. It does not, and
  the sentence above says so directly: **deferring a key means writing it empty,
  not leaving it out.** An empty value is a **present key** and outranks
  anything the build service would inject, which is the entire mechanism this
  invariant is built on. Filling a slot adds nothing here and, for a
  shared-project sink specifically, **removes a layer** (section 6.2 has the
  cost).

**WARNING: state this invariant in at most one other place, and only as a
check.** Where the install carries it in a consistency-scan template - a
**one-line checklist item** inside a prompt sent verbatim to a subagent, with a
pointer back to this section (`CONTEXT.md` section 6.5 names the file) - **that
copy is an actionable check, not a second statement of the rule**: it must not
carry the rationale or the carve-outs, and it must cite this section so a reader
lands here. The project instructions carry a pointer only. **If you change the
rule, change it here and re-read that one line; if you find rationale creeping
back into the template, delete it.**

---

### 6.6 The SECOND env channel: native backend config files

Everything above section 6.5 describes **one** channel: public env values
delivered from a tracked source file into the build's process environment.
**There is a SECOND, and it is a different shape, so the rules that guard the
first do not automatically guard it.**

The native analytics SDK reads its project identity from **native config files**
(a per-platform pair: an iOS plist and an Android JSON file), not from the env.
The app config selects the pair from the one selector and points the native
project at it. **So the *selector* is the same one selector as everywhere else,
but the *payload* travels as a file copied into the native project by a config
plugin at prebuild, never through the dotenv path.** Which environments have a
pair is a value (`CONTEXT.md` section 6.6).

**Six properties, each load-bearing:**

- **PER-ENVIRONMENT, NEVER A SINGLE CHECKED-IN FILE.** A single checked-in
  plist belongs to one project, and prebuild copies it into the native project
  **regardless**, so **every artifact, live included, ships a stale
  cross-project file** that nothing reads.

- **AN ENVIRONMENT WITH NO PAIR FORCES CONDITIONAL PLUGIN REGISTRATION.** Both
  halves of the analytics config plugin **hard-throw** when their config-file
  key is absent (read in the installed package's source). Registering them
  unconditionally would kill a dev-machine native build in prebuild. An
  environment that points at emulators has **no backend project to identify**,
  so **the correct answer is no pair and no plugins** - not a placeholder, and
  emphatically not pointing it at another environment's real config, which would
  be the stale-file failure above wearing a different hat.
  **WARNING: note the asymmetry with section 6.5, and do not "fix" it**: the
  dev-machine source is **not** exempt from the dotenv fan-out invariant, but the
  dev-machine environment **is** exempt here. **The rules differ because the
  failure modes differ**: an absent env key lets something else supply it
  unopposed, whereas an absent native config pair lets *nothing* supply it at
  all.

- **WARNING: THE SDK IS NOT THE ONLY CONSUMER, AND THE SECOND ONE READS THE FILE
  FOR BEHAVIOUR RATHER THAN IDENTITY.** A sign-in plugin registered as a **bare
  string with no options** selects the vendor's backend mode and derives the
  app's **iOS OAuth callback URL scheme** from the same plist's
  `REVERSED_CLIENT_ID`. So the practical consequence a reader of the bullet
  above would otherwise not derive: **re-fetching a plist can silently change
  the app's callback scheme**, not just the project it identifies, and a wrong
  scheme means sign-in never returns from the browser.
  That entry is **UNCONDITIONAL**, the exact opposite of the pair above, and
  that is not an oversight: every one of its mods early-returns when the config
  file is null, so an environment with no pair prebuilds to a no-op instead of
  throwing. **Verify it in the plugin source and then measure it on a real
  prebuild** for an environment with no pair (no scheme, no file copied, exit 0)
  and for two with pairs (each getting its OWN scheme: one environment shows a
  scheme is written, only two show each gets a different one); `CONTEXT.md`
  section 6.6 cites the install's evidence. **WARNING: the gate that can actually fail for it is an
  app-config test**, because the scheme is written at PREBUILD and the config
  dump, the SDK doctor and the bundle-verify scripts are **structurally blind to
  it.**

- **THESE FILES ARE SNAPSHOTS OF REMOTE CONSOLE STATE.** Unlike a source file
  authored in the repo, a native config pair is *fetched*, and **a human can
  change it underneath the repo at any time with no signal in git.** It happens
  on the ordinary timescale of console work: a pair committed before an OAuth
  client is registered is silently stale minutes later. **Re-fetch and diff
  before trusting a committed pair for anything provenance-related.** The recipe
  is reproducible and non-interactive - list the platform apps for the project,
  then read each app's config, authenticated with a JWT minted from that
  environment's own key (`CONTEXT.md` section 6.6 has it).
  **WARNING: guard every call on the credential's own project**: the key's
  identity and its project field must both equal the expected project, **because
  a machine's ambient application-default credential may resolve to an entirely
  different environment** (`CONTEXT.md` section 6.6 says which one it resolves
  to on the install's machines). **WARNING:** the vendor CLI also works, but only
  with a **scrubbed `HOME`**: with the real one it prefers its cached user login
  and **ignores `GOOGLE_APPLICATION_CREDENTIALS` entirely.**

- **COMMITTING THEM IS SAFE, AND IT IS THE VENDOR'S DOCUMENTED INTENT.** Per the
  vendor's own API-keys documentation (`CONTEXT.md` section 6.6 links it), keys
  in these files only *identify* the project and app; authorization comes from
  IAM, security rules and app attestation, and such keys "do not need to be
  treated as secrets". The files carry project id, project number, storage
  bucket, app ids, browser/mobile API keys and public OAuth client ids: **all
  already extractable from any shipped binary**, and the same class of value
  already committed in the env source files. **The real secrets remain the
  gitignored admin-SDK keys used to *fetch* them.**

- **WARNING: SIXTH: THE IDENTIFIERS INSIDE THESE FILES ARE IDENTITY-BEARING
  VALUES.** Each pair's `BUNDLE_ID` / Android `package_name` **must equal that
  environment's bundled identifier**, which makes it **the primary evidence of
  which environment a native config belongs to**, not an opaque marker to be
  told apart by other fields. Two consequences:
  - **The gate does a KEYED LOOKUP, not a marker match.** It selects the client
    entry *by* the expected identifier and then checks that entry, rather than
    scanning the file for a set of expected strings. **That distinction is the
    whole defence against the prefix residual (section 1)**: a marker-bag scan
    for the live identifier matches happily **inside** a longer one, so a
    substring-shaped check would pass a non-live config as live. The keyed form
    cannot. **Do not "simplify" it back into a string search.**
  - **A wrong pair is a wrong IDENTITY, not just a wrong project.** Fetching the
    pair for the wrong app **inside the right project** - easy, wherever a
    project still holds a retired registration - produces a file that looks
    project-correct and is **identity-wrong**. Re-fetch by the app whose bundle
    id equals the environment's identifier, and diff before trusting a committed
    pair. `CONTEXT.md` section 6.6 says whether any project of the install
    still holds such a registration.

**WARNING: a gate that watches only the JS bundle is blind to this channel**: it
would let a wrong-project native config through while reporting green, at
precisely the point it exists to watch. That is why the provenance gate carries a
native-config stratum. **If you add a third env channel, extend the gate in the
same commit or the claim in section 7 stops being true.**

---

## 7. What makes all of this falsifiable

The provenance gate runs **after every native build and before the artifact is
dispatched anywhere.** It answers one question: *is this artifact talking to the
environment I asked for?* (It skips, **loudly, never silently**, a
bundler-served build, which embeds no JS at all; the deploy script's guard
matrix already forbids shipping one of those, so **every artifact that can leave
the machine is gated**.) Its member reader also serves, in a second mode that
issues no verdict, anything else that needs a value out of the artifact's
embedded config (the tester-distribution note, section 4.5), so a second
extractor never has to exist.

It asserts that the artifact's **JS bundle** carries the target environment's
backend and telemetry identity markers, **no other environment's**, not the
legacy fingerprint, and that **the artifact's embedded resolved config declares
the environment selector EQUAL to the target.**

**That last layer is the one that catches section 6.3's signature
specifically:** perfect backend markers with the selector reading as the
dev-machine environment - because, as section 1 notes, the app's *name* cannot
tell those two apart.

It also asserts the **second env channel** (section 6.6): the embedded **native
config** must belong to the target environment's project, and to no other. Same
shape as the JS layers: **a positive assertion, a negative one against every
other environment, and an absolute census** that makes a marker set which shrinks
*or appears* a fault at **exit 2** rather than a smaller green. Three things
about it are worth knowing before you read a result:

- **It cannot use project ids, auth domains or storage buckets**, because the app
  config bakes every environment's hostnames into `associatedDomains` /
  `intentFilters`, so they appear in **every** artifact legitimately. The
  markers are the per-(environment, **platform**) app id, API key and project
  number, which exist only inside a native config.
- **It checks its own instrument before issuing a verdict.** A member that does
  not yield a structural token every such config carries **has not been read**,
  and the gate then reports **exit 2 (no verdict)** rather than a pass or a
  violation.
- **WARNING: an UNVALIDATED half fails CLOSED.** Where a platform's config does
  not ship verbatim (a build plugin compiles it into a resource table, and nobody
  has yet measured whether that table stores these values in a byte-greppable
  form), a missing *target* marker is **exit 2 with an encoding diagnostic, not
  exit 1** - while a foreign marker *found* stays exit 1, since **that cannot be
  a reading error.** **The first real CI build on that platform is what
  validates it**; only after one has passed may that branch be tightened. **Do
  not tighten it on the strength of the test suite**, whose fixtures prove the
  script's logic and not the encoding. `CONTEXT.md` section 7 records whether
  that validation has happened.

The consequence of the census being strict in both directions: **adding a config
pair for an environment requires bumping that environment's census row in the
same commit** - the gate exits 2 until you do, naming the row and the value.
**That is designed behaviour, not a bug to route around.**

It exists because **a build *can* be handed an environment from somewhere other
than the repo** (a build-service store does exactly that, section 6.3). It is
what turns "the repo is the only env channel" from a claim into **something that
fails a build when it stops being true.** It has its own regression suite.

---

## 8. Where the rest lives

| you want | read |
|---|---|
| set up a machine (toolchain, CLIs, per-project keys and secrets) | the repo's setup guide |
| run the dev stack | the dev script, bare, for usage - it is the only sanctioned way |
| build or deploy anything | the deploy script's `--help` and its header |
| the mechanical env-file contract for a *new* script that exports, serves or builds | the ops library's header |
| the environment -> config lookup table itself | the env lookup table's header |
| the app's version / build number - where it lives, what advances it, and the opt-outs | section 4.3 above + the version file |
| deploy a publishing lane that is not on the branch map | section 2.1 above + that lane's workflow |
| project conventions (agent-facing) | the project instructions |
| the definition of done | `/definition-of-done` |
| the worktree and landing discipline in full | `/worktree-workflow` |
| how a release is actually cut, step by step | `/release` |
| how the environment split and its env delivery were designed | the install's architecture records - historical, see the note at the top of this file |

`CONTEXT.md` section 0 maps every role named above to the file that plays it in
the install, and section 8 there names the install's own documents for each row.

**This skill states how the machinery works, never whether a given change may be
made.** Who authorizes a code change, a release, or a change to one of the
rulings `CONTEXT.md` records is the agent's charter and the install's
`CONTEXT.md`, never this file.
