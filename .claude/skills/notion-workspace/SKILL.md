---
name: notion-workspace
version: 1
description: >
  Notion MECHANICS for an agent fleet - the two access paths (the hosted MCP
  connector, and the integration token for what the MCP cannot do), the
  workspace and identity keys, the file-upload recipe, the OAuth exchange, and
  the known traps. Universal: no workspace, person, id, email or repo path is
  named here, the concrete values live in `config.json` and `CONTEXT.md` in the
  skill's install context. Load before reading or writing anything in Notion, before
  uploading a file to a page, or before changing anything about the Notion
  integration. Mechanics only, no policy: WHO may ask for a document to change,
  and whose approval an edit needs, are the requesting agent's judgement.
requires_install: true
---

# Notion mechanics

How an agent fleet reaches Notion. There are **two** access paths and they are
not interchangeable:

1. **The hosted MCP connector** - the default for everything it can do.
2. **The integration token** - only for what the MCP genuinely cannot do,
   file uploads above all.

**This file is universal.** It names no workspace, person, email, id or repo
path. The companion files carry all of that:

| File | What it holds | Per install? |
|---|---|---|
| `SKILL.md` (this) | Notion platform mechanics, recipes, traps | universal |
| `CONTEXT.md` | which workspace, which people, which bot, which project, the measured snapshots | **yes** |
| `config.json` | the machine-readable subset: workspace and identity ids, credential PATHS | **yes** |
| `config.example.json` | every key `config.json` must carry, with placeholder values | universal |
| `installation/` | how to install this skill, and `check` to prove it is installed and current | universal |

`CONTEXT.md` and `config.json` live in this skill's **install context**, the
directory `fleet where notion-workspace` prints, never beside this file.

So: **every concrete value below is a config key - look the value up in
`config.json`, and the judgement around it in `CONTEXT.md`.**

**This file also contains no policy.** Whether a document should be edited, who
may ask for it, and how a request is triaged are the calling agent's judgement
and live in its charter, which `CONTEXT.md` names. The standing behaviour:
**only touch documents someone has asked for.**

## Workspace and identities

| Item | Where its value is |
|---|---|
| Workspace | `workspace.name`, `workspace.id` |
| MCP acts as | `mcp.acts_as.name` (`mcp.acts_as.email`), user id `mcp.acts_as.user_id`. A hosted OAuth connector, registered under `mcp.connector_name`, connected out of band. |
| Token acts as | bot `bot.name`, id `bot.user_id`, owned by the Notion user `bot.owner_user_id`, same workspace |
| Token file | the path `token.path` names (mode 600, `ntn_` prefix, 50 characters as measured 2026-09-03) |
| OAuth client credentials | the path `oauth.credentials_path` names (`clientId` / `clientSecret` / `code`) |

Both credential files live outside every checkout, so no ignore rule stands
between them and a commit and the same path resolves from any worktree.
`CONTEXT.md` names where this install keeps them.

**The two paths are different principals.** The MCP writes as the person
`mcp.acts_as.name`; the token writes as the `bot.name` bot. An edit's
attribution in Notion's UI therefore depends on which path made it. Prefer the
token when the write is plainly an automation action and the audit trail should
say so.

**No API root or API version is a config key.** Every REST call below goes to
Notion's own root, `https://api.notion.com`, and carries
`Notion-Version: 2022-06-28`. Both are identical for every install, which by
this tree's convention makes them **mechanism, not values** - and there is no
script here to point at a mock server, so a config key for either would buy
nothing and would teach an adopter that a value with one correct setting needs a
decision.

## Path 1: the MCP connector (default)

Tools: `notion-search`, `notion-fetch`, `notion-create-pages`,
`notion-update-page`, `notion-move-pages`, `notion-duplicate-page`,
`notion-create-database`, `notion-update-data-source`,
`notion-query-data-sources`, `notion-create-comment`, `notion-get-comments`,
`notion-get-users`, `notion-get-teams`, `notion-create-view`,
`notion-update-view`, `notion-create-attachment`, `notion-download-attachment`.

**Use it for everything it can do:** reading pages, writing page bodies,
updating properties, creating pages, comments.

### The `self` diagnostic

`notion-fetch` with the special id `"self"` reports the connected workspace, the
authenticated user, and a **per-tool access map**. Run it first when anything
looks off; it distinguishes "not permitted on this plan" from "broken".

**It is also the only instrument that can prove path 1 is pointed at the
right workspace.** `installation/check --online` verifies the *token* leg
against the live API, but a hosted connector's binding leaves nothing on disk
for a script to read, so no check can speak for path 1. Compare what `self`
returns against `workspace.id` and `mcp.acts_as.user_id` before writing
anything. An agent aimed at the wrong workspace fails silently and looks like it
worked.

**The access map is per plan and it drifts.** The statuses are plan limits
rather than faults. `CONTEXT.md` records this install's last measured snapshot
with its date; read the **live** map rather than that snapshot, because tools
leave and join the map, and status strings change, between measurements weeks
apart. A table of statuses is a convenience;
the call is the truth.

### What the MCP cannot do

**It cannot put a binary file on a page.** `notion-create-attachment` accepts
exactly one of:

- `content` - inline **UTF-8 text only** (HTML, Markdown, CSV, JSON, SVG, ...),
  capped at **200 KiB** after encoding; or
- `source_url` - a **public** HTTPS URL that must not redirect, require cookies
  or headers, or resolve to a private address. Download must finish within one
  minute, capped at 5 MiB on free workspaces and 50 MiB on paid.

There is **no file-path parameter**. A PNG sitting on the machine you are
running on cannot reach a Notion page through the MCP. That is the entire reason
path 2 exists.

### The trap: file bytes inlined through the model

Told to "upload these images", an agent tries to make the bytes *qualify* as
text: base64 in a code block, or a PNG rewritten as an SVG wrapper. It then dies
with:

```
Claude's response exceeded the 32000 output token maximum
```

**That error IS the diagnosis: something is inlining file content through the
model's own response.**

Two corollaries, both counter-intuitive:

- **Smaller batches never help.** One image still exceeds the budget.
- **The size maths is not the blocker.** A 786px q80 JPEG base64'd into an SVG
  wrapper fits all nine screenshots of the verification below inside 200 KiB
  comfortably. The blocker is the *model being in the byte path at all*.

The fix is never a smaller image. The fix is path 2, where the bytes go
machine-to-machine and never enter a response.

## Path 2: the integration token

**Only for what path 1 cannot do.** It is not a general-purpose replacement:
the MCP is the default and has better ergonomics.

- **Never print the token, never commit it, never paste it into a chat, ticket
  or document surface.**
- **Provenance:** a workspace can **block internal (token-based)
  integrations**. Where it does, only **OAuth** integrations are installable
  there and a hand-made internal token will never work, no matter how correct it
  looks. `CONTEXT.md` records which kind this install has, and whether that
  block is why.
- **Scope:** an integration's reach is whatever it was granted, and it can be
  much wider than the one database you came for. `CONTEXT.md` records what this
  install's token was verified to reach. **Where the breadth is intentional it
  is still reach, not permission to roam.**

Resolve the token through the one resolver there is, so no recipe embeds a path.
`installation/check --token-path` prints the file that `token.path`
resolves to on this machine (and exits non-zero, printing nothing, if it does not
resolve):

```bash
T=$(cat "$("${CLAUDE_SKILL_DIR}/installation/check" --token-path)")
curl -sS https://api.notion.com/v1/users/me \
  -H "Authorization: Bearer $T" -H "Notion-Version: 2022-06-28"
```

That call is also the check on the whole path-2 leg: it returns the workspace,
the bot and the bot's owner, so its output is what `workspace.*`, `bot.*` and
`mcp.acts_as.user_id` are verified against.

It reports the workspace's upload ceiling too, as
`bot.workspace_limits.max_file_upload_size_in_bytes`. That is a **workspace**
limit and plan-dependent, so read it rather than assume it; `CONTEXT.md` records
this install's last measured value. Very large files use Notion's multi-part
upload flow rather than the single-part `send` below.

### File-upload recipe (proven end to end)

Measured 2026-07-29: the recipe puts 9 PNGs on a real page, confirmed by
read-back. `CONTEXT.md` names the page that verification used, and its current
state.

**1. Create the upload.** Returns `{id, status: "pending"}`.

```bash
curl -sS -X POST https://api.notion.com/v1/file_uploads \
  -H "Authorization: Bearer $T" -H "Notion-Version: 2022-06-28" \
  -H 'Content-Type: application/json' \
  -d '{"filename":"screen-01.png","content_type":"image/png"}'
```

**2. Send the bytes.** `multipart/form-data`, field name **`file`**. Moves the
upload to `status: "uploaded"`.

```bash
curl -sS -X POST "https://api.notion.com/v1/file_uploads/$ID/send" \
  -H "Authorization: Bearer $T" -H "Notion-Version: 2022-06-28" \
  -F "file=@$LOCAL_FILE;type=image/png"
```

**3. Attach it as a block.** `$PAGE_ID` is the target page, supplied per call by
whoever asked for the upload: it is not a config key, because there is no such
thing as *the* page this skill writes to.

```bash
curl -sS -X PATCH "https://api.notion.com/v1/blocks/$PAGE_ID/children" \
  -H "Authorization: Bearer $T" -H "Notion-Version: 2022-06-28" \
  -H 'Content-Type: application/json' \
  -d '{"children":[{"type":"image","image":{
        "type":"file_upload","file_upload":{"id":"'"$ID"'"},
        "caption":[{"type":"text","text":{"content":"Home, screen 01"}}]}}]}'
```

Notion copies the bytes into its own storage, so nothing needs to stay
reachable afterwards. `GET /v1/file_uploads` lists past uploads with their
status, which is a quick way to confirm step 2 landed.

**On read-back the block reports `image.type == "file"`, not
`"file_upload"`.** `file_upload` is the *write* form only. An agent verifying
its own upload by grepping for `file_upload` will wrongly conclude it failed.

## Verification discipline

**Notion writes can silently no-op. Always re-fetch and read the page back
before reporting that a change landed.** A returned page id is not evidence the
content changed.

**Paginate the read-back.** `/v1/blocks/{id}/children` caps at
`page_size=100` and sets `has_more`. Blocks can also nest, so an image inside a
column or toggle is invisible to a flat listing. A single unpaginated call on
the verification page above reports **zero** images when there are nine, all
past block 100. A shallow read-back is how you "verify" a success into a false
failure, or the reverse.

```python
# walk children recursively, following has_more
def walk(bid, depth=0):
    cur = None
    while True:
        u = f"https://api.notion.com/v1/blocks/{bid}/children?page_size=100" + (
            f"&start_cursor={cur}" if cur else "")
        d = get(u)
        for b in d["results"]:
            visit(b)
            if b.get("has_children") and depth < 4:
                walk(b["id"], depth + 1)
        if not d.get("has_more"):
            break
        cur = d["next_cursor"]
```

Prefer `update_content` (targeted search-and-replace) over `replace_content`
(whole body) for edits. It is cheaper and cannot accidentally drop sections.

## Authoring style

Whatever authoring-style rule an install imposes on Notion documents applies to
**three** places, and only one of them is obvious: the body, the **title**, and
the **property values**. Sweep the title and the property fields too, because
that is exactly where it gets missed.

The rule itself is local, not a mechanic: `CONTEXT.md` states this install's,
and who checks it.

## The OAuth exchange

Only needed if the integration is ever re-authorized. Exchange:
`POST /v1/oauth/token`, HTTP Basic auth of `client_id:client_secret`, body
`{grant_type: "authorization_code", code, redirect_uri}`. The client id and
secret come out of the file `oauth.credentials_path` names.

**Authorization codes are single-use AND single-mistake.** An exchange
attempted *without* `redirect_uri` fails **and revokes the code**. Every retry
afterwards then reports "code has been revoked", which tells you nothing about
the real problem and sends you debugging the wrong thing.

**Use `oauth.redirect_uri` when it is set. When it is `null`, get the exact
value from whoever configured the integration before attempting the exchange,
and write it into that key so the next attempt does not have to ask.** Do not
guess a parameter you can simply ask for: here a guess costs the code, not just
a retry.

## Credential hygiene

A credential file handed to you can arrive mode `0644` and need `chmod 600`.
**Check permissions on any credential file you are handed**, and fix them before
first use rather than after. `installation/check` asserts the mode on both
files, so an over-permissive one is caught before a run rather than after a
leak.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Claude's response exceeded the 32000 output token maximum` while "uploading" | File content is being inlined through the model. Stop; switch to path 2. Smaller batches will not help. |
| MCP attachment rejected for a PNG/JPEG | Expected. `notion-create-attachment` takes UTF-8 text or a public URL only. Use path 2. |
| A tool returns an upgrade prompt | Plan limit, not a fault. Check `notion-fetch {"id":"self"}` for that tool's status. |
| Read-back shows none of what you just wrote | Unpaginated or non-recursive listing. Follow `has_more` and descend into `has_children`. |
| Uploaded image "missing" but upload said `uploaded` | You are matching on `file_upload`. The attached block reads back as `image.type == "file"`. |
| `"code has been revoked"` on every OAuth retry | The first attempt was malformed (usually a missing `redirect_uri`) and burned the code. Get a fresh code and the exact `redirect_uri`. |
| Token call returns `unauthorized` | Confirm with `GET /v1/users/me`. If the workspace blocks internal integrations (`CONTEXT.md` says whether it does), a hand-made internal token will never work there. |
| `self` names a workspace other than `workspace.name` | The connector is bound to the wrong workspace. Stop before writing anything and re-read `CONTEXT.md`; nothing downstream will notice this for you. |

## Related

- **This install's values:** `config.json` (ids and credential paths) and
  `CONTEXT.md` (people, project, measured snapshots), both in the install
  context (`fleet where notion-workspace`)
- **Install and its state:** `installation/INSTRUCTION.md`, `installation/check`
- **Policy, authorization, triage:** the calling agent's charter, named in
  `CONTEXT.md`
- **Closest sibling surface:** the `/slack-communication` skill
