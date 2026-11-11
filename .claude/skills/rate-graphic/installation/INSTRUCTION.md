# Installing `rate-graphic`

Six steps. When they are done, `installation/check` exits `0`.

**Two directories.** The skill's own files (`SKILL.md`, `rate.mjs`, `check`,
this procedure) live in the fleet tree; every command below names them through
`CLAUDE_SKILL_DIR`, which a `SKILL.md` load substitutes and this file does not,
so set it once. The install's files (`config.json`, `CONTEXT.md`,
`installation/.install-state.json`) live in the skill's **install context**,
which `fleet where rate-graphic` prints; call it `CTX`:

```bash
CLAUDE_SKILL_DIR=<the directory holding this skill's SKILL.md>
CTX=$(fleet where rate-graphic)
```

**Dependencies: none to install.** `rate.mjs` is Node standard library plus
`fetch`, and `check` is Python 3 standard library plus the fleet's own library,
which is why there is no
`requirements.txt` beside this file. What the skill needs is a cloud SDK on
PATH, one credential file, and one grant - steps 1, 3 and 4.

---

## 1. The gcloud CLI

`gcloud` must be on PATH for a NON-interactive shell, not only for an
interactive one. `rate.mjs` and `check` both spawn it directly, with no login
profile and no shell initialisation between them and the binary, so a `gcloud`
that only exists because of a line in `.bashrc` is a `gcloud` this skill cannot
reach.

```bash
command -v gcloud && gcloud version
env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  command -v gcloud || echo "NOT reachable from a bare environment - fix PATH"
```

The second line is the one that matters. Install gcloud from the documented
package for this platform if either fails.

## 2. `config.json`

```bash
mkdir -p "$CTX" && install -m 644 "${CLAUDE_SKILL_DIR}/config.example.json" "$CTX/config.json"
```

`install -m 644`, not `cp`: the fleet tree is read-only and `cp` keeps that
mode. Replace **every** placeholder. The `_comment` keys in the file say what each
value is and how to obtain it; the loader ignores them, so keep or delete them
as you like. Four keys are required and `check` refuses to proceed without any
of them, naming it:

- **`ratings_log.path`** - where every rating is appended. It must be OUTSIDE
  the skill tree: a log accumulated from live use is real data about real work,
  and this tree is publishable (`/claude-skill` section 4). The example's
  relative value names the committed obviously-fake twin beside the example, so
  the example read in place runs green with no real data present - **in your
  copy, point it at your own log, or the records land beside your config.** The parent directory must exist; the script refuses to create
  it, because a mistyped path that silently `mkdir -p`s itself produces a second
  log nobody reads.
- **`credentials.service_account_key_path`** - the PATH to the key file, never
  the key. May contain a `*`; it must resolve to exactly ONE file.
- **`secret.name`** and **`secret.project`** - which secret in which cloud
  project holds the multimodal API key. A guessed project reads a key from the
  wrong project, and that reads as a successful run, which is why neither key
  has a default.

**Relative paths in `config.json` resolve against the directory holding
`config.json`** - never the caller's cwd and never the directory holding
`rate.mjs`. This is what lets one config mean one file no matter where the tool
is invoked from.

## 3. The credential

One service-account key file, placed where the glob in step 2 resolves it,
**mode 600**, untracked:

```bash
install -m 600 /dev/null <the path your glob resolves>
cat > <the path your glob resolves> <<'JSON'
{ ... the key you downloaded ... }
JSON
```

**The key file is a credential.** It appears in no file in this skill; only the
path shape does. `check` verifies its permissions as well as its existence,
because a world-readable service-account key is a credential that has already
leaked to every account on the machine.

Keep it outside the skill tree and out of version control, which means a fresh
clone or worktree has NO key at all. `rate.mjs` then fails naming the pattern it
globbed, the config key it came from and the directory it resolved against,
rather than guessing. The install's `CONTEXT.md` records how it restores it.

## 4. The grant

The service account from step 3 must be able to READ the secret from step 2:

```bash
gcloud secrets add-iam-policy-binding <secret.name> \
  --project=<secret.project> \
  --member="serviceAccount:<the account's email>" \
  --role="roles/secretmanager.secretAccessor"
```

**This is the one install leg with no on-disk artifact.** It lives in a cloud
IAM policy, and the only way to establish it is a network call - which is why
`check` does not make that call unless you ask it to, and why it refuses to
report success until you have. See step 6.

## 5. Verify the script offline

```bash
node "${CLAUDE_SKILL_DIR}/rate.test.mjs"   # must print "All checks passed."
```

The suite is offline and deterministic: it never makes a model call and never
touches the real ratings log. If it fails here, stop - the failure is in the
skill, not in your install.

## 6. Record the install, then check

`check` compares this file's record against the `version` in `SKILL.md`.
Without it, an install cannot be told from a stale one, so `check` reports
stale.

It is a **specific** file and is committed like any other, so it reaches
machines that never ran this procedure. It therefore records the host it was
written on, and `check` reports stale anywhere else - run this step once per
machine.

```bash
python3 - "${CLAUDE_SKILL_DIR}/SKILL.md" "$CTX/installation" <<'PY'
import json, re, socket, sys, time, pathlib
here = pathlib.Path(sys.argv[2])
here.mkdir(parents=True, exist_ok=True)
v = int(re.search(r"^version:\s*(\d+)$", pathlib.Path(sys.argv[1]).read_text(), re.M).group(1))
(here / ".install-state.json").write_text(json.dumps(
    {"version": v, "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
     "host": socket.gethostname(), "by": "INSTRUCTION.md"}, indent=2) + "\n")
print("recorded version", v)
PY

"${CLAUDE_SKILL_DIR}/installation/check"                             # artifacts only
RATE_GRAPHIC_CHECK_SECRET=1 "${CLAUDE_SKILL_DIR}/installation/check" # artifacts AND the step-4 grant
```

**Only the second form can exit 0.** The first ends in `NO VERDICT` and exit
`1`, naming the leg it did not measure. That is deliberate and it is the
property most likely to be "simplified" away by someone who finds the extra
variable annoying: exit `0` means proceed, a leg that was never measured cannot
say proceed, and a check that reports green while one of its legs never ran is
worse than no check, because it launders a guess into a confident answer. If you
remove the opt-in, remove the exit `0` with it.

The probe activates the service account into an **isolated `CLOUDSDK_CONFIG`**
and removes it afterwards. Do not "simplify" that either: activating a service
account in the shared config repoints the whole machine's gcloud auth, and
restoring it is a manual step for a person.

---

## Reading the exit code

| Exit | Means | Do |
|---|---|---|
| `0` | every artifact present and current, and the grant measured | proceed |
| `1` | installed, but stale / incomplete / **not fully measured** | read the line; it names which |
| `2` | not installed | follow this file from the top |

Exit `1` is the state worth reading carefully. Absent is loud - the key file is
missing and the first command fails naming it. Stale is silent: everything runs,
the key resolves, the model answers, and the behaviour is subtly the old one.

## Re-installing after a version bump

`check` exits `1` when `SKILL.md` declares a version newer than the recorded
one. Re-read this file from the top: a bump means something here changed, and
the only way to know what is to walk it. Then redo step 6.
