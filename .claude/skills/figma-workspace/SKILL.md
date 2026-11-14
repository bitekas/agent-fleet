---
name: figma-workspace
version: 1
description: >
  Figma MECHANICS for an agent fleet - the two access paths (the hosted Figma
  MCP connector for design context, metadata, screenshots and canvas writes;
  the REST API with personal access tokens for FILE COMMENTS), whose seat and
  rate limits each path spends, the comments helper (threads, anchor names,
  filters, a "what is new" cursor, replies), the separate read and write
  tokens, and the traps. Universal: no file, person, team or token path is
  named here; the concrete values live in `config.json` and `CONTEXT.md` in the
  skill's install context. Load before reading or answering comments on a
  Figma file, before any Figma MCP call, and before changing anything about the
  Figma tokens or the connector. Mechanics only, no policy: WHETHER an agent
  may comment, and who may ask it to, are its charter's call.
requires_install: true
---

# Figma mechanics

How an agent fleet reaches Figma. There are **two** access paths and they are
not interchangeable:

1. **The hosted Figma MCP connector** - design context, metadata, screenshots,
   variables, and writing to the canvas.
2. **The REST API with personal access tokens** - file comments: reading them
   threaded with their anchors named, seeing what is new since the last look,
   and posting a reply. The helper `figma_comments.py` is this path.

**This file is universal.** It names no file, person, team, seat or token path.
The companion files carry all of that:

| File | What it holds | Per install? |
|---|---|---|
| `SKILL.md` (this) | Figma platform mechanics, the helper's contract, traps | universal |
| `CONTEXT.md` | whose tokens and seat these are, which files, the posting convention, token expiry dates, who may post | **yes** |
| `config.json` | the machine-readable subset: file keys, token PATHS, the name-lookup choice, the post prefix, the state directory | **yes** |
| `config.example.json` | every key `config.json` must carry, with placeholder values | universal |
| `installation/` | how to install this skill, and `check` to prove it is installed and current | universal |

`CONTEXT.md` and `config.json` live in this skill's **install context**, the
directory `fleet where figma-workspace` prints, never beside this file.

**This file contains no policy.** Whether an agent may post a comment, which
requests it answers, and how a design request is triaged belong to the calling
agent's charter, which `CONTEXT.md` names. **Design work itself** - how frames
are laid out, exported or compared against code - belongs to the
design skill the install has, which `CONTEXT.md` names; this skill is only how
an agent reaches Figma.

---

## 1. Both paths act as a PERSON

Neither path has a bot identity. Everything an agent does through them is done
as some person's account, and that account's seat decides what the agent can
do and how often. (Figma's one non-person credential, the plan access token of
Organization and Enterprise plans, is outside this skill.)

| | Path 1: MCP connector | Path 2: personal access token |
|---|---|---|
| Acts as | whoever signed the connector in (OAuth) | whoever generated the token |
| Reaches | every file that person can open | every file that person can open, not only the files in `config.json` |
| Writes appear as | that person | that person |
| Budget | per person, by seat and plan | per person who generated the token, per plan of the file read |
| Lifetime | until the grant is revoked | at most 90 days |

**A read-only seat is a throttle, not only a permission.** Figma's limits, per
its docs read 2026-11-14:

- **MCP tool calls:** a View or Collab seat gets up to 20 a month on every plan;
  a Full or Dev seat on a paid plan gets a daily and a per-minute budget that
  grows with the plan (the Starter plan lists none for it). `whoami` and a few
  write-side tools are exempt.
- **REST:** the comments endpoints are Tier 2 (up to 5 a minute on a View or
  Collab seat). Reading file content (`GET /v1/files/<key>`, `.../nodes`) is
  Tier 1, and for a View or Collab seat **the rate-limits page contradicts
  itself**: its table says "Up to 20/month", while its own prose examples say
  "up to 6 per month" and "a maximum of 6 requests monthly". Plan for 6.
- **Writing to the canvas** through the MCP: the MCP overview page says it
  "requires the remote Figma MCP server and a Full seat to write outside your
  drafts"; the write-to-canvas page says it "Requires edit access to the
  file", on Professional, Education, Organization and Enterprise plans, and is
  in beta.

So the seat of the person behind each path is a fact the install records in
`CONTEXT.md`: an agent on a View seat that loops over file reads spends the
month's Tier 1 budget within its first few calls, and the symptom is a 429 on
a call that worked an hour ago.

**A comment posted with a token appears under its owner's name.** A reader
cannot tell an agent wrote it unless the text says so; `post.prefix` puts that
text in front of every comment the helper posts (section 3).

## 2. Path 1: the hosted MCP connector

**Use it for what it does well:** reading a design's structure and context,
metadata, screenshots and variables, and writing to the canvas. The vendor
ships skills for this path, and its server instructions name the one to load
before a tool: **load the vendor's `figma-use` skill before any `use_figma`
call**, and its design-to-code skill before `get_design_context`. The
vendor's own word on skipping one: common, hard-to-debug failures.

**Delegate large reads to a subagent with a call budget.** One page's
`get_metadata` can run to about a megabyte, which burns a session's context in
one call; on a View or Collab seat each call is also one of that month's 20.
Brief the subagent with the file key, the node ids it may touch, and the number
of calls it may make, and take back a summary.

**`whoami` is the diagnostic.** It names the signed-in account, its plans and
its seat on each, and it is exempt from the rate limits. Run it first when a
call is refused or throttled, and before the first write of a session: an
agent signed in as the wrong person writes as that person, and nothing
downstream notices.

**Comments through the MCP.** The connector's own tool list, read 2026-11-14,
carries a comment READ tool (`get_comments`, with filters and a cursor of its
own) that Figma's published tool list does not document, and no tool that posts
a comment (the schema was read; the tool was not called). The tool list
drifts; read the live one. This skill reads comments through path 2
regardless, because path 2 works unattended with no session, keeps its cursor
in the agent's state, posts replies, and spends the Tier 2 budget rather than
the MCP's monthly one.

## 3. Path 2: personal access tokens

**Three tokens, three roles, each a file of its own** (`config.json`
`tokens.*.path`, mode 600, outside every checkout):

| Role | Scope | Used for | When null |
|---|---|---|---|
| `read` | `file_comments:read` | every comments read | required |
| `write` | `file_comments:write` | `reply`, `post` | the install is READ-ONLY: every write verb refuses before it builds a request |
| `content` | `file_content:read` | anchor names (section 4) | names come from the read token, or not at all (`names.token`) |

**Read and write are separate tokens on purpose.** An install that only reads
holds no token that can post, so no bug, prompt or mistyped verb can post for
it. That holds only if the read and content tokens are issued WITHOUT
`file_comments:write`, each in a file of its own: `installation/check` refuses
a read or content path equal to the write path, and nothing can see a token's
scopes before a call. Whether an agent may post at all is still its charter's
call; the separate token only makes "it cannot" true where the install wants
it.

**A token file holds one line**: the token, and nothing else that is not
printable non-space ASCII. A second line, a pasted space, a control character
or a byte that is not ASCII (a file that is not text at all) is refused before
use, naming the file and never the value: such a value is rejected by the HTTP
layer, whose error quotes it.

- **A token is never printed, never put in argv, never logged.** The helper
  reads it from its file inside the process and sends it only as the
  `X-Figma-Token` header. Everything it prints - errors, warnings, and the
  listing itself - is scrubbed of the loaded tokens and of anything shaped like
  one (`figd_...`), because an error body is server text and a comment's text
  is whatever a person pasted into it. There is no command-line option that
  takes a token.
- **A redirect is never followed.** urllib's default handler re-sends a
  request's headers, the token among them, to the redirect target on any host
  and any scheme. The REST API never redirects, so the helper's opener refuses
  every redirect and reports the 3xx as an API error, exit 4.
- **A token is named by path, under the organization secrets variable**
  (`/claude-skill` section 4): `${FLEET_SECRETS_DIR:-<fallback>}/<file>`.
- **A token lives at most 90 days**, and none is issued without an expiry
  (Figma's changelog entry 2025-04-28). `CONTEXT.md` records each token's
  expiry date, and a reminder through `/scheduled-tasks` renews it before
  then. An expired token answers 401 `Invalid token` (section 6).
- **A token reaches every file its owner can open.** `files` in `config.json`
  is a convenience for `--file`, not a fence.

### The helper

```
figma_comments.py list  [--file F] [--unresolved] [--since T] [--author A]... [--anchor X] [--json]
figma_comments.py new   [--file F] [the same filters] [--peek] [--json]
figma_comments.py reply <comment-id> [--file F] [--message TEXT | --message-file PATH] [--dry-run]
figma_comments.py post  --node NODE-ID [--offset X,Y] [--file F] [--message ...] [--dry-run]
```

Invoke it as `"${CLAUDE_SKILL_DIR}/figma_comments.py"`. Common options:
`--file` (an alias from `files`, a file key, or a Figma URL - a branch URL
gives the branch key; may be left out when `files` has one entry), `--json`,
`--config` (default: the install context's `config.json`, or
`$FIGMA_WORKSPACE_CONFIG`), `--state-dir` (default: `state.dir`, or
`$FIGMA_STATE_DIR`). Reading options: `--no-names`, `--refresh-names`.

- **`list`** prints every thread: the root comment with its number, state
  (`OPEN`, or `RESOLVED` and when), time, author and id, WHERE it is anchored
  (section 4), its text, and its replies oldest first. Filters:
  - `--unresolved` - open threads only;
  - `--since T` - comments created at or after `T` (ISO 8601; a time with no
    zone is read as UTC);
  - `--author A` - a user handle (any case) or user id, repeatable;
  - `--anchor X` - a node id exactly, or part of a frame or page name (needs
    names; with names unavailable only a node id matches).

  A thread is shown when it passes `--unresolved` and `--anchor` and at least
  one of its comments passes `--since` and `--author`; a root that does not
  match itself is printed as `(context)`, and in `--json` every comment carries
  `match`.
- **`new`** is "what is new since I last looked", in one call: the comments the
  cursor has not seen, each thread with its root as context, and the threads
  resolved or reopened since. It advances the cursor unless `--peek`. With a
  filter it marks seen only what it showed, and leaves resolution changes for
  an unfiltered run, so a filtered look never swallows what it did not
  display. It advances only once its output is written: with stdout closed,
  it exits `1` and the comments stay new. The FIRST `new` reports everything;
  run it once to set a baseline.
- **`reply`** posts into a thread. Figma accepts a reply only to a ROOT
  comment, so a reply id given here is followed to its root, and the helper
  says so. It reads the comments first (read token) to find the thread.
- **`post`** posts a new comment pinned to a node (`--node`, a frame's id) at
  `--offset X,Y` inside it, from its top-left corner (default `0,0`).
- **Both write verbs** take the text from `--message`, `--message-file` or
  stdin, put `post.prefix` in front of it unless it already starts with it
  (`{agent}` is the posting agent's name, its home directory's, `{Agent}` the
  same capitalised), send it with the WRITE token, print the new comment's id,
  and mark it seen in the cursor. `--dry-run` prints the request (method, URL,
  body; never a token) and sends no POST (`reply` still reads the comments to
  find the thread). With no write token configured they refuse before anything
  is read or built.
- **Once the POST succeeded, the verb exits 0 and prints the id**, whatever
  happens next: a cursor that cannot be updated, a response that does not
  parse or is not a comment object (the id is then "unknown"), or a closed
  stdout, is a warning on stderr. An exit that said "not posted" after a post is
  how a retry posts it twice under a person's name. A write whose outcome is
  UNKNOWN - the request may have been sent and the answer was lost (a timeout,
  a broken connection, a 5xx) - exits `5`: read the thread before retrying.

**Nothing resolves a thread.** The REST API has no call that resolves or
reopens one (per Figma's docs, read 2026-11-14): resolving is a person's act in
Figma's UI. The helper sends only GETs and the comment POST, and offers no
delete, though the API has one for a token owner's own comments.

`--json` output: `{"file": {"key", "name"}, "names_note", "threads": [...]}`,
each thread `{"id", "number", "resolved", "resolved_at", "created_at",
"author": {"id", "handle"}, "message", "match", "new", "orphan", "parent_id"
(an orphan's missing parent, else null), "anchor": {"kind", "link", and for a
node "node_id", "offset", "name", "type", "page", "status"; for the canvas
"x", "y"}, "replies": [...]}`. `new` adds `resolved_since_last`, `reopened_since_last` and
`cursor` (`path`, `advanced`, `first_look`).

**Exit codes:** `0` ok (for a write: posted); `1` usage, configuration or
local state (nothing was posted); `2` a token file missing, unreadable, empty,
not one line, or not mode 600, or no write token for a write verb; `3` Figma
refused the token (401 invalid or expired, 403 a missing scope - the message
names the scope that call needs - or no access to the file); `4` any other
API failure, every transport failure included (404, 429, a timeout, a
truncated body, network), with nothing posted; `5` a write whose outcome is
unknown. 2, 3 and 4 are three repairs by three different people: the
machine's operator, the token's owner, and nobody. 5 is never retried blind.

## 4. Anchors and their names

A root comment is pinned one of two ways (Figma's comment types, read
2026-11-14):

- **to a node** - `client_meta` carries `node_id` (the frame it is pinned to)
  and `node_offset` (`x`, `y` inside it); a region comment adds
  `region_width`, `region_height` and `comment_pin_corner`;
- **to the canvas** - `client_meta` is a Vector (`x`, `y`) or a Region (`x`,
  `y`, `region_width`, `region_height`, `comment_pin_corner`), and nothing names
  the page.

**A reply carries no anchor of its own** (measured: `client_meta` is null on
every reply). Its anchor is its root's, so the helper prints anchors per
thread.

**A node id is not something a person can use.** The helper prints every
anchor as a NAME and a LINK - `frame "Checkout" on page "Screens"
https://www.figma.com/design/<key>?node-id=1-2` - and never a bare node id in
its readable output (the id stays in `--json` for agents).

**The name needs a file-content read, which a comments token cannot make.**
`names.token` in `config.json` says which token the lookup uses:
`"content"` (a separate `file_content:read` token), `"read"` (the read token
also carries `file_content:read`), or `null` (no lookup). The lookup is:

1. `GET /v1/files/<key>?depth=2` - the file's name, every page, and every
   top-level node on each page, with their names (status `ok`).
2. Only for the anchors that call did not name: `GET /v1/files/<key>/nodes?ids=...&depth=1`.
   An entry there has its name and no page, because this endpoint returns no
   ancestors (status `name_only`, printed "page not resolved"): a nested node,
   or a top-level one newer than the cached depth-2 read. A null entry is a node
   the file no longer has (status `deleted`): the comment still carries the
   old id.

**So one lookup is up to TWO Tier 1 calls**, and on a View or Collab seat
Tier 1 is a handful a month (section 1). `GET /v1/files/<key>?ids=...` returns
"everything between the root node and the listed nodes", which could name a
nested anchor's page in one call; it also returns each listed node's whole
subtree, and it is not measured, so the helper does not use it.

**Names are cached** in the agent's state directory (`names-<key>.json`) for
`names.cache_hours` after the depth-2 read; a nodes read for a new anchor adds
to the cache without moving that time, so a renamed frame shows its new name
at most `names.cache_hours` after the read that named it. A scope refusal is
cached the same way, so a token without `file_content:read` costs one Tier 1
call per window, not one per run. `--refresh-names` reads again now.

**A failed lookup degrades the names, never the listing**, whatever failed:
a missing scope, a timeout, a 429. The reason is printed once, in the
listing's header (and on stderr when the lookup was tried in this run), with
the scope that would supply the names; each anchor then prints as
`<name unavailable>` with its link.

## 5. The cursor and the state directory

`new`'s cursor is the SET of comment ids already seen, plus the set of threads
seen resolved, one file per design file: `cursor-<key>.json`. A set and not a
timestamp, because a timestamp cursor misses a comment that becomes visible
after a later one was read, and a clock is not needed to compare ids.

It lives in the AGENT's state directory (`/agent` section 3): `state.dir`,
whose `{home}` is the calling agent's home - the parent of
`CLAUDE_CONFIG_DIR`, which must be a direct child of the host's agents root.
The name cache lives beside it. `--state-dir` or `$FIGMA_STATE_DIR` names
another place; a state directory inside a git work tree is refused, because a
cursor in a checkout is a different file in every worktree and one `git add`
from a commit. **Deleting a cursor is not cleanup**: the next `new` reports
every comment on the file as new.

**Two runs at once can lose a cursor update, never a comment.** The cursor is
read, changed and replaced whole (atomically, but without a lock), so of two
interleaved runs on one file the last to write wins: a comment the other one
showed, or a resolution it recorded, is reported again by the next `new`. Run
one `new` per agent per file at a time when a repeat matters.

## 6. Traps

Each was read on 2026-11-14 in Figma's REST documentation - the comments,
comment types, scopes, rate limits, personal access tokens, errors and changelog
pages under `https://developers.figma.com/docs/rest-api/` - and is marked
**measured** where a real read-only call confirmed it on that date.

- **No pagination.** `GET /v1/files/<key>/comments` returns every comment in
  one response whose only key is `comments`; `page_size` and `cursor` are
  ignored (measured). How long a list can grow before that one response
  becomes a problem: not measured.
- **Newest first.** The list comes newest root first (measured); the helper
  sorts threads itself rather than relying on it.
- **A root's `parent_id` is the empty string, not absent** (measured). A test
  for the key's presence turns every root into a reply.
- **`order_id` is a STRING** - the number shown on the pin in Figma - though
  the docs type it Number; set on roots only (measured).
- **`resolved_at` is set on roots only** (measured): resolution belongs to the
  thread.
- **Timestamps are UTC**, ISO 8601 with milliseconds and `Z`:
  `2026-01-10T09:00:00.000Z` (measured). An agent comparing them to a local
  time converts first.
- **`client_meta` carries an undocumented `stable_path`** (measured: a list of
  one id equal to `node_id`, or null). Nothing here reads it.
- **Missing scope is 403 in two body shapes** (measured):
  `{"status": 403, "err": "Invalid scope(s): ... requires the file_content:read scope"}`
  and `{"error": true, "status": 403, "message": "Invalid scope: ... requires
  the ... current_user:read scope.", "i18n": null}`. The helper reads both and
  passes Figma's text on, which names the scope.
- **An invalid token is 401** `{"status": 401, "err": "Invalid token"}`
  (measured with a malformed token), though the docs' error table lists only
  403 for refusals. An EXPIRED or revoked token: per the docs, not measured;
  the helper reports any 401 as invalid, expired or revoked.
- **A comments token has no whoami.** `GET /v1/me` needs `current_user:read`
  and answers a comments-only token with 403 (measured). The comments read
  itself is the probe: `installation/check --online` makes it.
- **A wrong file key is 404** `{"status": 404, "err": "Not found"}` (measured).
  A file the token's owner cannot open: per the docs, not measured.
- **429 carries `Retry-After`** in seconds, with `X-Figma-Plan-Tier`,
  `X-Figma-Rate-Limit-Type` (`low` for View and Collab seats, `high` for Full
  and Dev) and `X-Figma-Upgrade-Link`; the budget is a leaky bucket per user per
  plan (per the docs; no 429 was provoked). A successful response carries no
  rate-limit header at all (measured), so the remaining budget cannot be read
  ahead of a call. The helper reports a 429 and does not retry.
- **A deleted anchor keeps its node id.** The nodes endpoint answers null for an
  id the file does not have (per the docs, not measured: the token measured
  lacks `file_content:read`).
- **Reply to a root only.** `comment_id` in a POST must name a root comment
  (per the docs); the helper follows a reply to its root.

## 7. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `CredentialError: no write token is configured` | The install is read-only (`tokens.write.path` null). Intended where no agent may post; otherwise the token's owner issues a `file_comments:write` token. |
| `AuthError: ... HTTP 401 Invalid token` | Expired (90 days at most), revoked or mistyped. The token's owner generates a new one; `CONTEXT.md` names the owner and the expiry. |
| `AuthError: ... lacks the scope` | The token was issued without the scope Figma's message names. A new token with it, from its owner. |
| Every anchor `<name unavailable ...>` | `names.token` is null, or its token lacks `file_content:read`: the reason says which. |
| `ApiError: rate limited ... Retry-After N` | The token owner's budget for that tier is spent; on a View or Collab seat Tier 1 is a handful a month (section 1). Wait, or raise `names.cache_hours`. |
| `WriteUnknown: ... may have been posted` (exit 5) | The POST was sent and its answer lost. Read the thread with `list` or `new` before posting again. |
| `CredentialError: ... does not hold one line` | The token file carries a second line, a space or a control character. Rewrite it with the token alone. |
| `new` reports every comment at once | First look, or the cursor was deleted. Expected once. |
| `ConfigError: ... not an agent home` | `CLAUDE_CONFIG_DIR` is not under the host's agents root: run as the agent, or pass `--state-dir`. |
| An MCP call refused or throttled | Run the connector's `whoami`: wrong account, or a View or Collab seat out of its month. |

## Related

- **This install's values:** `config.json` (file keys, token paths, choices) and
  `CONTEXT.md` (whose tokens and seat, expiry dates, the posting convention, who
  may post), both in the install context (`fleet where figma-workspace`)
- **Install and its state:** `installation/INSTRUCTION.md`, `installation/check`
- **Policy:** the calling agent's charter, named in `CONTEXT.md`
- **Design work:** the design skill the install has, named in `CONTEXT.md`
- **Closest sibling:** the `/notion-workspace` skill
