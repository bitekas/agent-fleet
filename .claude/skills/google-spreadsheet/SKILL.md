---
name: google-spreadsheet
version: 1
description: >
  Read and write Google Sheets and Drive as the agent's OWN Workspace user,
  using a service-account key with domain-wide delegation: the token carries a
  subject claim and therefore acts as a real person-shaped account, so a
  document a colleague shares with the agent is reachable and a document the
  agent creates is owned by it and findable in its Drive. Covers the mechanism
  and why the subject is the default, the scopes and the grant behind them, the
  helper's CLI and importable API, the recipes that matter (open a spreadsheet,
  read and write a range, batchUpdate for drop-downs, conditional formatting,
  frozen rows, column widths and new sheets, create, share, delete, and list
  what is shared with the agent), and the failures that are routinely misread -
  a 403 that is really an unenabled API, a too-narrow scope or a dropped
  subject rather than a missing share, a Drive 404 that hides existence, and
  unauthorized_client as a missing grant. Load before touching any Google Sheet or Drive file from an agent,
  before asking a person to share one, and before debugging a permission error
  against one. Mechanics only, no policy: who may ask the agent for a sheet, and
  what it may write there, live in the agent's charter.
requires_install: true
---

# Google Sheets and Drive, as the agent's own Workspace user

**This file names no host, person, path, email, address, key or agent.** Every
concrete value is a key in the install's `config.json`, written as
`` `identity.subject_template` `` and never as its value; the install's `CONTEXT.md`
carries the local layer a person reads. Both live in the skill's install context,
`<install root>/.claude/skills/google-spreadsheet/` (`fleet where google-spreadsheet`
prints it). An adopter replaces those two files and nothing here.

---

## 1. The mechanism, and why the subject is the default

An agent authenticates to Google with a **service-account key** - a JSON file
holding a private key and the account's own `client_email`. On its own that key
is a robot principal with an address ending `gserviceaccount.com`, and it
is the wrong identity for almost everything an agent is asked to do.

The key is granted **domain-wide delegation** on the Workspace: an
administrator records the service account's numeric client id together with an
explicit scope list. With that grant, a JWT-bearer assertion carrying a `sub`
claim mints a token that **IS** the named Workspace user:

- it reads and writes everything shared with that user;
- what it creates is **owned** by that user, sits in that user's Drive, and
  counts against **that user's** storage quota;
- the address a person shares a document with is the ordinary human-shaped one
  (`identity.subject_template`), which is the address they already know.

**Without `sub` the token is the bare service account**, which is a different
principal that was shared nothing. The symptom is `403 PERMISSION_DENIED` on the
very document a person just shared, and the two identities look like ONE from
the outside - same key, same helper, same agent - which is what makes this trap
expensive. **So the subject is the default here, and dropping it is an explicit
flag.**

Three consequences worth stating on their own, because each is easy to get wrong:

- **The ask to a person is always "share it with `<the agent's Workspace
  address>`"**, never the `gserviceaccount.com` one. A document shared with the
  service account is reachable only by a token with no subject, which is not how
  anything else in this skill works.
- **A file cannot be created without a subject at all.** A service account has
  no Drive storage quota of its own, so the create is refused
  `403 storageQuotaExceeded`. With the subject set the same call succeeds, in
  that user's Drive, against that user's quota - which makes this the most
  concrete argument for the subject being the default.
- **The grant is per WORKSPACE, not per cloud project.** A key issued in one
  project acts as the user for documents anywhere in that Workspace's Drive.

### The scopes, and that the grant is the authority on them

Tokens are minted for the scopes in `scopes.*`. **Those values must match the
delegation entry exactly: a scope the grant does not list mints nothing**,
whatever the key could otherwise do, and the refusal happens before any API is
reached.

**The grant is the authority, and `config.json` is a claim about it.**
**READ AND WRITE ARE DIFFERENT SCOPES, and a grant routinely lists only one
of them.** An install whose Drive scope is read-only reads and lists as the user
and is refused on sharing, trashing and deleting - **including on files that
user owns outright**, which is what makes that refusal read like a sharing
problem when it is nothing of the kind. An install with no Drive scope at all
cannot even ask Drive who it is. That is a property of the Workspace, not of
this skill, and widening it is an administrator's edit **first** - changing
`config.json` alone mints nothing. Probe what is actually granted rather than
assuming (section 6), and record the answer in `CONTEXT.md`.

---

## 2. The helper

One file, `gsheets.py`, stdlib plus PyJWT. It is the only minter: a second copy
of the JWT dance is where the `sub` claim silently goes missing. Run it as
`"${CLAUDE_SKILL_DIR}/gsheets.py"`; the command lines below abbreviate that to
`gsheets.py`. With no `--config` and no `$GSHEETS_CONFIG` it reads the install
context's `config.json`.

```
gsheets.py [--as USER] [--sa-only] [--config PATH] [--json] <command>

  whoami                          mint a token and print the identity it acts as
  get <id>                        a spreadsheet's title, url and sheets
  values <id> <range>             read an A1 range (TSV, or --json)
  write <id> <range> <json>       write an A1 range; JSON, or @FILE, or -
  batch <id> <file>               POST a batchUpdate body; file, or -
  create <title>                  a spreadsheet owned by the acting user
  share <id> <email> [--role R]   share a file with a person
  delete <id> [--permanent]       trash a file (recoverable) or destroy it
  list [query]                    what is shared with the acting user
```

- **`--as USER`** acts as another Workspace user for one invocation;
  `GSHEETS_SUBJECT` does it for a whole process. Neither changes **which key**
  signs - one agent's key can only impersonate users its own grant covers.
- **`--sa-only`** drops the subject. It has exactly two jobs: proving a denial
  is about the SHARE rather than the delegation, and touching something the
  service account itself owns. **It is not a fallback to try when a call fails.**
- **`--json`** prints the raw API response, for anything the formatted output
  does not carry.
- **`GSHEETS_CONFIG`** points the helper at a different config entirely -
  another agent, another domain, another key store.

**`whoami` is a comparison, not an announcement.** It mints a token, asks Drive
who that token is, and **compares** the answer with the identity that was asked
for, exiting non-zero when they differ. That matters because a wrong
`identity.subject_template` mints perfectly and acts as somebody else; only the
comparison can see it. It prints the identity and **never the token**.

### Exit codes

| | |
|---|---|
| `0` | ok |
| `1` | usage or configuration error - nothing was attempted |
| `2` | the credential is missing, unreadable, or not a service-account key |
| `3` | the mint was refused - delegation or subject. **No API was reached** |
| `4` | an API call failed or was denied |

**Three codes rather than one, because they have three different repairs
performed by three different people.** A caller that collapses them reports
"permission denied" for a machine that simply has no key on it.

### Importable

Anything the CLI does not cover is a call, not a new script:

```python
import gsheets
gsheets.token(gsheets.scope("sheets"))            # cached per (scope, subject)
gsheets.call(url, scope_url, method=, data=, params=, subject=)
gsheets.drive_list("mimeType='application/vnd.google-apps.spreadsheet'")
gsheets.spreadsheet(id) / values(id, rng) / write_values(id, rng, rows)
gsheets.batch_update(id, {"requests": [...]}) / create(title)
gsheets.share(id, email, role=) / trash(id) / delete_permanently(id)
```

Tokens are cached per **(scope, subject)** - both, because one process routinely
holds tokens for two scopes and more than one subject, and a cache keyed on
scope alone hands a token for the wrong identity to a caller that asked for
another. That call succeeds; it just writes to the wrong Drive.

---

## 3. Recipes

### Open a spreadsheet and list its sheets

```
gsheets.py get <spreadsheet-id>
```

The id is the long segment of a document's URL that follows `/d/`. The
output carries each sheet's **`sheetId`**, which is what every `batchUpdate`
request below addresses - the tab's *name* is not an identifier and changes when
somebody renames it.

### Read a range

```
gsheets.py values <id> 'Sheet1!A1:D40'
gsheets.py values <id> 'Sheet1'          # the whole sheet
```

**Trailing empty cells and rows are simply ABSENT from the response.** Rows
come back ragged and short, so index by header position, never by assuming every
row has the same length.

### Write a range

```
gsheets.py write <id> 'Sheet1!A1:B2' '[["a","b"],["c","d"]]'
gsheets.py write <id> 'Sheet1!A1:B2' @rows.json
```

Values are written as if a person typed them (`USER_ENTERED`), so `=SUM(A1:A5)`
becomes a formula, `2026-09-14` a date, and `007` the number 7. **`--raw` stores
them literally** - which is what you want for identifiers with leading zeroes,
anything that begins with `=` or `+`, and text that merely looks like a date.

An empty string clears a cell; a `null` in the array leaves it alone.

**A write into a MERGED range keeps the anchor cell's value and silently
drops the rest.** No error, no warning, and the response's `updatedCells` counts
what you sent rather than what survived. Unmerge before writing. A merged cell
also blocks a column drag across it in the UI, so for banding and headers prefer
filling each cell over merging them.

**A literal range inside a formula is rewritten when a person drags a column
endpoint**, so a formula written as `B2:D2` silently shrinks or shifts as the
sheet is edited around it. Anchor to the header row instead, and let the
reference be a WHOLE ROW - whole-row references survive column moves:

```
=INDEX(2:2, MATCH("Area", $1:$1, 0) + 1)
```

### batchUpdate - everything that is not cell content

The values endpoints carry **content only**. Structure and formatting -
drop-downs, conditional formatting, frozen rows, column widths, merges, a new
sheet, protected ranges - are all requests in one `batchUpdate` call:

```
gsheets.py batch <id> requests.json
```

Every request addresses a range by `sheetId` plus **half-open, zero-based**
indices: `startRowIndex: 0, endRowIndex: 1` is the first row only. Off-by-one
here is the single most common mistake in this API, and it does not error - it
formats the wrong cells.

A file holding several of the common ones:

```json
{"requests": [
  {"updateSheetProperties": {
     "properties": {"sheetId": 0, "gridProperties": {"frozenRowCount": 1}},
     "fields": "gridProperties.frozenRowCount"}},

  {"setDataValidation": {
     "range": {"sheetId": 0, "startRowIndex": 1, "startColumnIndex": 2,
               "endColumnIndex": 3},
     "rule": {"condition": {"type": "ONE_OF_LIST",
                            "values": [{"userEnteredValue": "Yes"},
                                       {"userEnteredValue": "No"}]},
              "showCustomUi": true, "strict": true}}},

  {"addConditionalFormatRule": {
     "index": 0,
     "rule": {"ranges": [{"sheetId": 0, "startRowIndex": 1}],
              "booleanRule": {
                "condition": {"type": "TEXT_EQ",
                              "values": [{"userEnteredValue": "No"}]},
                "format": {"backgroundColor": {"red": 1, "green": 0.9, "blue": 0.9}}}}}},

  {"updateDimensionProperties": {
     "range": {"sheetId": 0, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 3},
     "properties": {"pixelSize": 220}, "fields": "pixelSize"}},

  {"autoResizeDimensions": {
     "dimensions": {"sheetId": 0, "dimension": "COLUMNS",
                    "startIndex": 3, "endIndex": 8}}},

  {"addSheet": {"properties": {"title": "Notes", "gridProperties": {"rowCount": 200,
                                                                    "columnCount": 12}}}}
]}
```

Three things that are not obvious, each a debugging session when missed:

- **`showCustomUi: true` is what draws the drop-down arrow.** Without it the
  rule still validates, and the cell looks like an ordinary cell, so the feature
  reads as not working.
- **`strict: true` REJECTS a value outside the list; `false` only warns.** Pick
  deliberately: strict breaks a paste of otherwise good data, lenient lets a
  typo through.
- **`fields` is a mask and it is mandatory on every `update*` request.** It says
  which properties to touch; anything it names and the body omits is **cleared**.
  `"fields": "*"` on a partial body is how a sheet loses its other properties.

A rule is removed with `setDataValidation` carrying no `rule`, and
`deleteConditionalFormatRule` by index - and conditional-format indices
**renumber as you delete**, so delete from the highest index downwards.

**`addConditionalFormatRule` APPENDS, and is not idempotent.** Re-running a
script that adds rules stacks duplicates that render **identically**, so the
sheet looks right while its rule list grows on every run until it is unusable.
Two consequences, and they are different jobs:

- **A writer deletes the rules it manages before re-adding them**, in one
  `batchUpdate`, highest index first.
- **A verifier COUNTS the rules, never asks whether one exists.** "Is the rule
  there?" is green on one rule and on eleven copies of it, so an existence check
  cannot see this failure at all - which is the only reason it survives.

Conditional-format ranges are positional `GridRange`s. There is no header-driven
form of them, so they do not survive a column move the way a whole-row formula
reference does; re-derive them when the sheet's shape changes.

### Create a spreadsheet

```
gsheets.py create 'Title'
```

It is owned by the acting user, in that user's Drive, against that user's quota.
Then `batch` it into shape and `share` it.

**This is a Sheets-API call, so it needs only the Sheets scope** - but
`share` and `delete` below are Drive calls and need a Drive **write** scope.
Where the grant has no Drive write scope, an agent can create a spreadsheet it
then cannot share or delete through the API: a person does both from the Drive
UI. Check `CONTEXT.md` for what this install is actually granted before
promising either.

### Share a file

```
gsheets.py share <file-id> person@example.com --role writer
```

Needs a Drive **write** scope in the grant. Roles: `reader`, `commenter`,
`writer`, `fileOrganizer`, `organizer`. No
notification email is sent unless `--notify` is passed - a share that silently
appears in "Shared with me" is usually what is wanted from automation, and an
unexpected mail from a robot account is not.

### Delete a file

```
gsheets.py delete <file-id>              # trashed: recoverable for ~30 days
gsheets.py delete <file-id> --permanent  # irrecoverable
```

Both need a Drive **write** scope in the grant; under a read-only one they are
refused with `403 insufficient authentication scopes` even for a file the acting
user owns.

**Trash is the default deliberately.** A file id is one paste away from being
the wrong file id, and Drive's permanent delete has no undo.

### Read a Doc, a PDF or any other Drive file

Not everything shared with the agent is a spreadsheet, and the two routes are
different calls:

```python
gsheets.call(f"{drive_base}/files/{id}/export", gsheets.scope("drive"),
             params={"mimeType": "text/plain"}, raw=True)      # a Google Doc
gsheets.call(f"{drive_base}/files/{id}", gsheets.scope("drive"),
             params={"alt": "media"}, raw=True)                # an uploaded file
```

**`files.export` is for Google's own editor formats** (Docs, Slides, Drawings) -
they have no bytes to download. **`alt=media` is for everything uploaded as a
file** - a PDF, an image, a CSV. Using either on the other kind is a 403 whose
message is about the file type rather than about permission.

### List what is shared with the agent

```
gsheets.py list
gsheets.py list "mimeType='application/vnd.google-apps.spreadsheet'"
gsheets.py list "name contains 'tracker' and trashed = false"
```

**`supportsAllDrives` and `includeItemsFromAllDrives` are both sent on every
page, and neither is optional.** Without them, content on a **shared drive** is
absent from the result with no error and no marker. A silently short list reads
exactly like a correct answer, which is why this one is enforced in the helper
rather than left to each caller.

---

## 4. The failures, and why they are not interchangeable

**Diagnose in this order. The order is the diagnosis:** a token that MINTS
proves the delegation exists, which is what separates "not delegated" from "not
shared".

| What you see | What it means | Who repairs it |
|---|---|---|
| `unauthorized_client` at the mint | no delegation grant for this service account, or the grant omits this scope. **Nothing was reached** | a Workspace administrator |
| `invalid_grant` at the mint | the subject is not a live user in that Workspace - a typo, a group address, a suspended account - or the machine clock is far out | whoever set the subject |
| `403` with `SERVICE_DISABLED` | **the API is not enabled on the key's cloud project.** Not a sharing problem at all | a project owner |
| `403` `insufficient authentication scopes` | **the identity is right and the SCOPE is too narrow.** Not a sharing problem either - it denies the acting user's OWN files | a Workspace administrator, then `scopes` |
| `403` `storageQuotaExceeded` | a create ran **without a subject**: a service account has no Drive storage | set the subject |
| `403` otherwise | the identity is real; the document is not shared with it | the document's owner |
| `404` from Drive | **Drive hides existence.** "Not shared with you" and "no such file" are the same 404 | the document's owner, or nobody |
| `404` from Sheets | the spreadsheet id does not resolve for this identity | check the id |
| `401` | the token was rejected - usually a clock far out of step | the machine |

Two of these are routinely misread:

- **A `403` is usually NOT about sharing.** Four unrelated causes wear that
  one status and their repairs have nothing in common - and two of them fire on
  documents the acting user owns outright, where "ask them to share it" is
  advice that cannot work. **Match on the message**, never on the status. The
  helper does this and says which one it saw.
- **A `404` from Drive is never evidence that a file is gone.** Existence is
  hidden on purpose. Treat it as "this identity cannot see it" and check the
  share before concluding anything about the file.

---

## 5. Rules

- **Never print the key or a token.** Not to stdout, not into a log, not into a
  message. An access token is a live credential for as long as it lasts, and a
  transcript is forever. The helper scrubs anything token- or key-shaped out of
  every error body it renders; keep that property if you touch it.
- **The key file is mode `0600`, in a directory mode `0700`, outside this
  skill's tree.** `credential.key_path` is a PATH and never the key.
- **Ask for a share to the agent's Workspace address**, never the
  `gserviceaccount.com` one (section 1).
- **Read before you write, and say which document.** These calls act on live
  documents that people are editing at the same time; there is no dry run and no
  undo on a values write.
- **A write to a range somebody else is editing overwrites their work
  silently.** Sheets has no locking and the API does not merge. Where a document
  has a live human editor, append rather than overwrite, or agree a range.
- **WHO may ask for a document, and what the agent may write in one, is the
  agent's charter** and not this file.

---

## 6. Proving it works

```
python3 "${CLAUDE_SKILL_DIR}/installation/check"            # offline: config, PyJWT can SIGN, the key signs, its mode
python3 "${CLAUDE_SKILL_DIR}/installation/check" --online   # also mints and asks Drive who it is
"${CLAUDE_SKILL_DIR}/gsheets.py" whoami                     # the same identity proof, on demand
python3 "${CLAUDE_SKILL_DIR}/gsheets.test.py"               # the offline guard: no network, no credential
```

**The delegation grant has no artifact on this machine.** It is an entry in
an administrator's console; nothing on disk changes when it is granted or
revoked, so the offline check says explicitly that it did not measure it and
names the instrument that does. An offline `OK` is a claim about the artifacts
on this machine and never about the grant.

**To find out what the grant actually covers, mint against each scope
INDIVIDUALLY - read and write separately:** a scope in the entry returns a
token, one outside it is refused `unauthorized_client` before any API is
touched. (The refusal arrives as HTTP 401 carrying that error code, so read the
code and not the status - a 401 here is a missing GRANT, not a bad key.) That probe costs nothing, touches no document, and is
the only honest answer to "can this agent write to Drive?" - record what it says
in `CONTEXT.md` rather than inferring it from what the key *could* do.
