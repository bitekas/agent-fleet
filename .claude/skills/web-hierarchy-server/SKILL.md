---
name: web-hierarchy-server
version: 1
description: >
  Surface an agent session's whole delegation hierarchy as a LIVE,
  self-updating web page for a human who cannot see the terminal. A node
  server (serve.mjs) reads the session transcripts the agent harness already
  wrote, builds a spawn-tree graph of the root session and every subagent
  under it (type, task description, model, start/end time, alive or stopped,
  last log line), and serves ONE standalone HTML document at GET / with a
  GET /state JSON snapshot the page polls every 10s to patch itself in place;
  a switch on the page draws all agents (the default) or only the active ones.
  The TREE is served and the LOGS are fetched: a log arrives from
  GET /agent/<id> when the viewer selects that agent, incrementally via
  ?since=<n>, and images come from GET /img/<hash>, so the page stays
  openable at hundreds of agents. Formatting runs server-side, so transcript
  content never passes through an agent's context window. It follows the most recently
  active session by itself, so it outlives any individual session and needs no
  restart when one ends. Load it to start or hand out the viewer, to change
  what the page renders, or to work out why a page is empty or stale; the
  values for this install (which agent, which port, which URL) are in
  CONTEXT.md and config.json in the skill's install context.
requires_install: true
---

# Web hierarchy server

The human an agent works for is often on another device and cannot see the
subagents' terminal. This turns the whole spawn tree into one live page they
open once and watch: a clickable graph up top, the selected agent's full log
below.

This skill's install context - the directory
`fleet where web-hierarchy-server` prints - holds this install's two files:
`CONTEXT.md` names the agent, its port and its URL, and `config.json` holds
every value the scripts read. `config.example.json` beside this file documents
each key. The scripts find `config.json` by asking that same command, or read
the file `WEB_HIERARCHY_CONFIG` names when it is set; a relative path inside it
resolves against its own directory.

Run the checks and scripts by path:

```bash
"${CLAUDE_SKILL_DIR}/installation/check"     # is a server up for this config dir, is it current
node "${CLAUDE_SKILL_DIR}/serve.mjs" --help  # the config, transcript root and port it would use
```

## The one standing rule: ONE server per config dir

A config dir (`CLAUDE_CONFIG_DIR`) is one agent's transcript root, and **exactly
one server serves it**. A second server on the same port is the failure this
rule exists to prevent: whichever process wins the bind serves the page, the
other dies with `EADDRINUSE`, and from the viewer's side the page looks fine
either way. Before starting one, establish that no server is already up for that
config dir (`installation/check` answers it, and never starts anything).

**The durable form is a service unit** (`installation/web-hierarchy-server.service.example`):
machine-start, `Restart=always`, up from boot before any work is delegated, and
surviving reboots. **Installing one needs root**, which is a human's step. On macOS
it is a LaunchAgent in the user's gui domain
(`installation/web-hierarchy-server.plist.example`), installed without sudo. Where
nobody has run it, the server runs as a **detached process** started once
(`setsid nohup ... &` on Linux, `nohup ... &` on macOS, which has no setsid, so it
outlives the session that launched it) - that form
works and does not survive a reboot, which is exactly what `installation/check`
says in words rather than reporting a green.

**Edits to `serve.mjs` or `format.mjs` are LATENT by design.** node loads them
once at process start, so a landed change reaches a running page only at the
next restart. That is expected; it is not a reason to bounce a server that a
viewer is watching, and it IS the reason a "my fix did not take" report is
usually a running process holding the old code.

## The tree is SERVED; the logs are FETCHED

This is the shape of the whole thing, and it is a size rule, not a style.

A session's TREE costs about a kilobyte per agent whatever that agent did. Its
LOGS are unbounded, and rendering one drags its images in with it. Putting every
agent's log in every snapshot makes `GET /` for a 228-agent session **358MB**,
110MB of it base64 image data, re-sent on every 10s poll. Nothing is broken, and
the page cannot be opened.

So the payload is split, and each route carries one kind of thing:

| Route | Carries | Costs |
|---|---|---|
| `GET /` | the whole tree, the ROOT session's log, and that content's images inline as data URIs | one document, complete without a server |
| `GET /state` | the whole tree and NO logs (`?logs=<id>,<id>` names exceptions); `?view=active` narrows the GRAPH to the active view | what the 10s poll pays, every tick, for ever |
| `GET /agent/<id>` | exactly that agent's rendered log | one fetch, when the viewer selects a block |
| `GET /agent/<id>?since=<n>` | only events from index `n` | an empty array for a quiet agent |
| `GET /img/<hash>` | one image by content hash, `immutable` | once per image per viewer, then cached |

Two consequences worth knowing before changing anything here:

- **`since` indexes the tree's own `count`.** A tree row carries the agent's
  real event count even though its log was not rendered, and that number is what
  a client hands back as `since`. Both come out of the same transcript parse, and
  they have to: derive one of them somewhere else and a client silently skips or
  repeats events, with nothing to see but a log that is subtly wrong.
- **`GET /img/<hash>` is content-addressed, so an answer is cached for ever.**
  That is why an unknown hash is a 404 and never an empty 200 - an empty 200 is a
  permanently broken image for that viewer, and no reload fixes it.

**Nothing goes red if this split is lost.** Put every log in `GET /state`, or
inline images into every snapshot, and the tree is right, the labels are right,
the page renders, and it is hundreds of megabytes. The SIZE is the property under protection; the size legs
in `serve.test.mjs` (6-9) are the only thing that can see it regress, and each is
a PAIR - absent here, present there - because "X is absent" is otherwise true for
all the wrong reasons.

## What a SAVED page has, and what it does not

`GET /` is one standalone HTML document: inline CSS and JS, no external
assets, and a baked-in snapshot that renders with no server at all. What is baked
is **the whole tree and the root session's log**, with that content's images as
data URIs.

**Not baked: every other agent's log.** Those are not in the document; they
arrive from `/agent/<id>` on selection. So a page saved to disk, or one whose
server has died, shows the complete graph and the root session's log, and shows
nothing when a subagent block is clicked. The images inside those logs are the
same story: they render from `/img/<hash>` and there is no server behind a saved
file.

**For a frozen record of EVERY log in one file, use `build.mjs`** - the static
bake inlines every agent's log and every image, because a keepsake has
nothing to fetch from. That is the one caller that asks `snapshot()` for all the
logs (`logsFor: null`).

## How it follows sessions

A server is long-lived; a Claude session is not: ending a session, an update and
a unit restart all mint a new session id. So the server **re-picks the most
recently active session on every snapshot** rather than resolving one at startup,
and serves a *"waiting for a session..."* page while none exists yet - the normal
state at boot. "Most recently active" includes the ROOT transcript, not just
subagent files: a freshly started session that has not delegated yet is followed
immediately and rendered as a root-only tree, and the spawn tree grows from its
first delegation. Nothing needs restarting when a new session begins; the page
detects the id change and rebuilds its logs.

`--session=<id>` pins one session instead (a frozen view for debugging).

**Every project slug under the config dir is scanned**, not one. A session's
transcript lands under the project slug of its CWD, so a session working in a
git worktree writes under the WORKTREE's slug; pinning one slug makes every
worktree session invisible while the page still renders perfectly.

## Which agent a page says it is showing

The root block is labelled with the fleet member the config dir belongs to,
resolved through `config.json`'s `fleet.by_config_dir`. **The key is derived, not
the raw basename**, and the derivation is the part worth reading:

> `format.mjs`'s `fleetKey()` takes the config dir's basename, EXCEPT when that
> basename is the literal `.claude`, where it takes the PARENT directory's
> basename instead. A fleet that gives each agent a home directory puts every
> config dir at `<home>/<agent>/.claude`, so keyed by basename all of them
> collide on one entry and every agent's page is labelled with whichever agent
> that entry names.

That failure is silent: the page renders completely and says the wrong name, and
a viewer with two pages open cannot tell them apart and does not know they
cannot. A literal `.claude` entry is honoured as a fallback, so a
single-agent install keyed `.claude` keeps its label; it cannot distinguish
two agents and should not be used where more than one exists. The same derived
key picks the default port from `config.json`'s `servers`, for the same reason:
a basename match would hand every agent the first entry's port.

## Files

- `serve.mjs` - the live server: `GET /`, `GET /state`, `GET /agent/<id>` and
  `GET /img/<hash>` (see the route table above). **The primary tool.**
  `--port=N`, `--host=<addr>`, `--cap=KB`, `--session=<id>`, each defaulting
  from `config.json`; `--help` prints the usage, the resolved config path, the
  transcript root and the default port, and binds nothing. `--port=0` takes an
  ephemeral port and the banner prints the one it actually got.
- `format.mjs` - the shared formatter: transcript parsing, spawn-tree layout,
  per-event HTML, the theme CSS, and the one place local values are read
  (`cfg()` over the `config.json` that `fleet where` names, or over
  `WEB_HIERARCHY_CONFIG` when that is set).
- `build.mjs` - optional STATIC snapshot (`node build.mjs <out.html>`): bakes the
  current state into one self-contained file for a frozen, shareable record.
  Use for a keepsake, not the live view.
- `identities.json` + `avatars/` - the display-name roster, used unless
  `identities.file` names another one.
- `serve.test.mjs` + `fixtures/` - the test: it starts a real server on an
  ephemeral port against a synthetic transcript tree, asserts the tree, drives
  every route (tree without logs, one agent's log and nobody else's, `?since`
  shipping only what is new, an image served by hash byte for byte), and then
  DELETES one subagent's transcript and requires the tree AND the per-agent route
  to lose it. Its header states why each leg is there, which pair each size leg
  is half of, and why the negative control is the load-bearing part. Leg 11
  requires `GET /state?view=active` to drop the stopped block that the default
  view draws.
- `view.test.mjs` - the "active only" rule on its own (`filterView()` over a
  synthetic tree): alive blocks, the blocks above them and the root, with the
  stopped siblings and children next to them dropped, and "all" returning every
  row unchanged.
- `format.test.mjs` - how the config is found and read: through `fleet where`
  when `WEB_HIERARCHY_CONFIG` is unset (a fake fleet selected by `FLEET_BIN`),
  the variable winning, a failing fleet relayed rather than guessed past,
  relative paths, the roster default, and `packages.dir_pattern`.
- `installation/` - the unit template, the install procedure, and `check`.

## What the page shows

It reads like the Claude Code console in the dark-colorblind
(dark-daltonized) theme - palette taken verbatim from the Claude Code bundle
(black background, white monospace text, tool bullets in success-blue `#3399ff`,
errors `#ff6666`, dim result lines with "... +N lines" expanders, thinking
markers, task and user messages framed like console input).

- **Spawn-tree graph.** The root session is the top node; every parentless agent
  hangs off it. Blue = alive (with a rotating spinner arc beside the time range;
  static under `prefers-reduced-motion`), grey = stopped. Click a block to show
  that agent's full log below.
- **An "all / active only" switch above the graph.** "all" is the default and
  draws every block. "active only" draws the blue blocks, every block above
  one of them, and the root: the alive flag is the one that colours a block,
  so the switch never disagrees with the colours. The blocks above stay
  because a parent waiting on a long child writes nothing to its own
  transcript and reads as stopped while the child runs; without them the
  child would hang from nothing. With nothing alive the view is the root
  alone. The switch narrows the GRAPH only: the stamp still counts the whole
  session (plus "N shown"), and a from-link or `#a-<id>` to a hidden agent
  still opens its log. The choice is remembered per viewer in the browser's
  `localStorage`; where storage is blocked the switch still works for that
  visit. `format.mjs`'s `filterView()` is the rule; `view.test.mjs` pins it.
- **Per-agent task description on every block.** Source of truth: the spawning
  `Agent` call's `description`, which the harness copies into
  `agent-<id>.meta.json`. Fallback when absent: the first line of the agent's
  task prompt. The description wraps and the block grows to fit it.
- **The last log line on every block, as a hover tooltip.** At a few hundred
  agents it is the only thing that separates two blocks with the same type and
  the same description, and for an alive agent it is what it is doing right now.
  It rides in the TREE because it is the one piece of log content cheap enough
  to: plain text, clamped, never HTML - the moment it renders markup it drags
  images and expanders into every snapshot.
- **Model on every block.** `parseTranscript` reads the model off the
  transcript's assistant turns (the `claude-` prefix stripped); when the agent
  has not answered yet, the coarse alias in its `.meta.json` stands in. A node
  with neither renders no line rather than a placeholder.
- **Named agents with avatars.** Each block shows a name, its avatar, the
  agentType, the description, the model and the time range, so five concurrent
  agents of one type are distinguishable at a glance.
  - The name is a **display label only**: assigned from the roster at
    `identities.file` as a pure function of (agentType, spawn order within that
    type), recomputed from the transcripts on every refresh. **Nothing is stored
    anywhere**, and the agents do not know their own names - the harness owns
    the transcripts and this formatter is a read-only observer.
  - Spawn order, **not** a hash of the agent id: with N names and N agents a
    hash collides by pigeonhole; spawn order cannot.
  - **`names` order is load-bearing - append only.** Reordering or inserting
    mid-list silently renames every past session's graph.
  - **`avatar` = the role's silhouette; `portraits` = optional bespoke art for a
    name.** The avatar identifies the ROLE, the name identifies the AGENT.
  - An agentType absent from the roster renders unnamed, as does the root
    session, which is a person's and not an agent's.
  - **A roster that will not load is not a runtime error**: every block renders
    with no name and no avatar, which reads as a design choice rather than a
    fault. It is logged to stderr, and `installation/check` resolves the path as
    one of its legs - that leg is the only thing standing between a missing
    roster and nobody noticing for weeks.
- **from/to headers.** The task prompt and every inter-agent message carry
  `from: <spawner> - to: <agent> - HH:MM:SS`; the from-id is clickable and
  selects that agent. The root session's own prompts come from a person, so they
  carry `config.json`'s `labels.root_owner` instead.
- **One-line tool units.** `Bash`/`Read`/`Write` calls pair with their results
  into a single collapsed line; click expands the full command and the result.
- **File changes as diffs.** `Edit`/`Write`/`NotebookEdit` render as the
  console's Edit display: file-path header, line-number gutters, context rows,
  and the colorblind diff colors.
- **Handover packages.** When a message references artifact files, or a package
  directory of the shape `packages.dir_pattern` describes, a foldable block lists
  the deliverables, each collapsed: `.md` unfolds to its text, images unfold
  inline, `.html` unfolds to an inert escaped-source view and is never embedded
  live. A relative path in a message is resolved against `packages.repo_root`.
- **Images as click-to-open thumbnails**, everywhere they appear, deduplicated
  by content hash so a diagram quoted in dozens of messages costs one copy. An
  image the document BAKED IN is a data URI and clicking it opens a Blob URL
  (browsers block opening a `data:` URI as a top-level navigation); every other
  image renders as `<img data-img="<hash>">` with no data at all and is fetched
  from `/img/<hash>`, which the browser then caches permanently because the URL
  is the content hash.
- **An alive agent's last line animates.** Its leading marker cycles six
  Claude-style spinner frames in claude-orange, like the console's progress
  indicator, and downgrades to the static marker the moment a later event
  appends or the agent stops. Those six glyphs, and the box-drawing, dash,
  ellipsis and bullet characters inside the scripts' string literals, are
  FUNCTIONAL output: they are what the page draws. An ASCII sweep that
  normalises them changes what the program emits, which is a product change
  wearing a punctuation sweep's clothes. **Sweep by offset, never by line:**
  `format.mjs` carries a large CSS template literal whose lines begin with `/*`
  and `*`, so a line-based "is this a comment" test edits the emitted
  stylesheet while believing it edits source. The guard is asserting that the
  non-ASCII content of every string literal is byte-identical before and after.

**The served page is ONE STANDALONE HTML DOCUMENT**: inline CSS and JS, zero
external assets, and the tree plus the root session's log baked in with their
images as data URIs - see *What a SAVED page has* above for what that does and
does not survive the server dying. Polling and the per-agent fetches are the
live-update mechanism on top. Everything is gzipped when the client accepts it,
which matters through a forwarded or tunnelled port.

**Thinking is not recoverable.** Subagent transcripts persist extended thinking
as an encrypted signature with empty plaintext, so the page marks *where* each
agent thought and cannot show the content. The rest of the protocol is complete.

## Triage: the page is empty, stale, or will not load

1. **Is the server up?** `curl -so /dev/null -w "%{http_code}"
   http://127.0.0.1:<port>/` on the machine itself. `installation/check` answers
   the same question with more detail and starts nothing.
2. **"Waiting for a session..." is not a fault** when the config dir has no
   session transcript yet. Any session, delegating or not, is followed as soon
   as its root transcript appears.
3. **The page shows the wrong agent's work.** `CLAUDE_CONFIG_DIR` in the
   server's environment wins over `transcripts.config_dir`; a server launched
   without it falls back to the config file. Nothing on the page says which was
   used, which is why that key is one of `check`'s legs.
4. **An edit did not take.** node holds the code from process start: restart the
   server (a human action on a unit; on a detached process, kill it and start
   one). Confirm afterwards, because a restart that raced a still-bound port
   leaves the OLD process serving.
5. **A forwarded port goes stale while still looking connected** after the host
   reboots. Re-establish the forward rather than debugging the server.
6. **The graph is there and a block's log stays empty.** The log is a separate
   fetch (`/agent/<id>`), so check that route directly:
   `curl -s "http://127.0.0.1:<port>/agent/<id>" | head -c 200`. A 404 means the
   server no longer sees that transcript - the usual cause is a session change
   under a page that has been open a while, and a reload fixes it. **A SAVED
   page shows nothing here and that is by design**: only the tree and the root
   log are in the document.
7. **A thumbnail is blank in a log.** Images come from `/img/<hash>`; a 404 there
   means the hash was evicted from the server's bounded image store, and
   re-selecting that agent re-renders its log and re-inserts it. A blank
   thumbnail on a SAVED page is the same by-design gap as (6).
