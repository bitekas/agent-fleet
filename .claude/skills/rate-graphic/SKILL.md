---
name: rate-graphic
version: 2
description: >
  Pre-flight check on a GENERATED graphic using a multimodal model - a
  composition analysis, a colour analysis, a list of specific fixes, and a
  score out of 5. Load after generating a poster, social card, marketing image
  or exported screen art, to catch gross breakage and factual/semantic errors
  before a human sees it. It is NOT a judge of style: calibration measured
  that it cannot resolve design quality, so its number MUST NOT gate, rank or
  drive iteration. Read section 1 before acting on anything it outputs.
requires_install: true
---

# rate-graphic

Runs a generated graphic past a multimodal model and reports what it sees:
a composition analysis, a colour analysis, specific fixes, and a score out of 5.

```bash
node "${CLAUDE_SKILL_DIR}/rate.mjs" <image...> \
  [--context "<what the graphic is for>"] [--repeat <n>] [--json]
```

Install-specific values live in `config.json` in this skill's install context
(the file `fleet where rate-graphic config.json` names, which is how `rate.mjs`
finds it; `RATE_GRAPHIC_CONFIG` overrides it), documented key by key in
`config.example.json` beside this file: where the ratings log is, which secret
in which project holds the API key, and the path to the service-account key
file that reads it. A relative path in it resolves against its own directory.
`CONTEXT.md`, beside it, is the local human layer. Nothing in this file names
any of those values, and nothing needs editing here to adopt the skill.

---

## 1. What this tool is, and what it is not

**It is a pre-flight check for gross breakage and factual/semantic errors in
artwork. It is not a judge of style.**

That is a measured verdict, not a caution: the rater fails calibration
(measured 2026-08-09). The calibration set is one run of logged calls under ONE
prompt sha, over ten rounds of the same graphic, with a per-call rating log and a
rendered progression sheet. The raw run stays with the install that produced it, and
that install's `CONTEXT.md` names where it lives; a raw-evidence path is an
install value and is often not even present in a fresh clone, so it is not
named here. The finding below is the part that travels.

What the calibration measures:

| finding | measurement |
|---|---|
| It cannot resolve craft | ten designer-led rounds of real improvement leave the median at **2.90 -> 2.90**, a tie |
| It prefers the wrong work | the two rounds a designer would actually ship score **lowest** of the late rounds |
| It hallucinates the defect it marks down | flags a "soft blurry drop shadow" that pixel-probes at **0px blur** - the treatment it demands the round before |
| It reverses itself | demands a hard 0px shadow, then two rounds later a 30px blur |
| Its ceiling is the instrument's, not the work's | **every shipped graphic in the calibration set scores 2.6-3.4**; a 4.0 bar rejects all of them |

**It is not blind, and that is the part worth keeping.** A deliberately wrecked
control - hero deleted, magenta block over the wordmark - scores 1.4 with an
accurate description, and it catches a real map defect: a solid fill merging two
neighbouring regions into one blob, leaving location dots outside any region. It sees gross
breakage and semantic/factual errors reliably. It does not see design.

So use it to answer *"is anything obviously broken or wrong in this image?"*
Read the composition and colour notes for that. Do not use it to answer *"is
this good?"* or *"which of these is best?"* - it has been measured against both
questions and it cannot answer either.

## 2. DO NOT ITERATE ON A LOW SCORE

When you rate a graphic you generated and the number comes back low, you **stop
there and report it**. You do not regenerate, you do not adjust the design to
raise the number, and you do not loop until the score improves.

**This is permanent, not provisional.** The calibration measures the estimates
as inaccurate, so the rule is the settled conclusion of a measurement, not a
placeholder.

**And never treat the `fix:` list as a work order.** Executing every
top-ranked instruction at once produces **the worst graphic in the calibration
set**, and a single instruction (scaling the hero element by 15%) introduces a
real content occlusion. The fixes are worth reading as observations
about what the model noticed. They are not a plan.

A score that rises after you follow the advice is not evidence the advice was
good - it measures only that the model likes work that followed its own
instructions.

## 3. The number must not gate or rank anything

- **No threshold gate.** Every shipped graphic in the calibration set scores
  2.6-3.4, so any bar worth setting rejects work that has already shipped. If anyone proposes an
  aesthetic-score gate, quote the ceiling probe in the evidence above.
- **No ranking.** The script deliberately prints results **in the order you
  passed them, not sorted by score** - sorting is ranking, and this rater cannot
  rank. Do not add a sort; its absence is load-bearing.
- **No choosing between candidates.** If you need a winner picked, a human picks
  it. Then record that pick (section 6).

## 4. The score is not reproducible either

**Measured 2026-08-09**, independently of the calibration run.
Four runs of one prompt, one model, temperature 0.2, over the same six graphics:

| graphic | four identical runs | range |
|---|---|---|
| image-a | 2.2 / 1.8 / 2.0 / 2.2 | 0.4 |
| image-b | 2.2 / 2.0 / 2.2 / 2.3 | 0.3 |
| image-c | 2.2 / 2.1 / 2.1 / 2.2 | 0.1 |
| image-d | 2.4 / 2.8 / **3.8** / 2.2 | **1.6** |
| image-e | 2.2 / 2.7 / **3.8** / 2.4 | **1.6** |
| image-f | 2.1 / 1.8 / 2.1 / 2.1 | 0.3 |

With identical input, the ranking reorders between runs.

**Temperature is not the cause** - 0.0 against 0.2, five samples on one image,
give an identical 0.4 spread. Do not try to fix this by lowering temperature.

So the script samples each image **3x by default** and prints the **median with
the observed range**, marking any range >= 0.5 as `UNSTABLE`. Never report a
`--repeat 1` number as though it were a measurement.

## 5. The prompt is the instrument, and it is versioned

`PROMPT_VERSION` is currently **v3**. Every log record carries
`prompt_version` and a runtime-computed `prompt_sha`, and **analysis groups by
`prompt_sha` first** - two shas are two instruments, not one instrument with
noise.

- **v1** (`910efe5681b5`) asks for a free-form `reasoning` field.
- **v2** (`cefdcbe7cdca`) walks the model through **STEP 1 composition** and
  **STEP 2 colour** as named steps with their own output fields, and only then
  asks for a score, telling it explicitly that the number must be a conclusion
  drawn from those two steps rather than a verdict justified afterwards.
- **v3** (`d71a370dd1df`) is v2 with a different object in the improvement
  example. Its steps and output fields are v2's, so only `prompt_version` and
  `prompt_sha` tell a v3 record from a v2 one.

**v2 and v3 are not a reason to trust the number.** The v1 prompt, which fails
calibration, already carries a structured chain of thought: an ordered six-part
walk-through covering composition and hierarchy, typography, and "colour and
material quality" before scoring. Structured reasoning is present in the
instrument that cannot resolve craft. The named steps make the analysis
explicit and separately addressable, which plausibly improves the **notes**; it
is not evidence about the **score**. Only a fresh calibration run is evidence
about the score, and until one exists section 1 stands.

**Bump `PROMPT_VERSION` in the same edit that changes `PROMPT`.** The `prompt_sha`
is what catches you if you forget. Never tune the prompt to move the numbers.

## 6. The log

Every rating appends a JSONL record to the log named by the config key
`ratings_log.path` - one record per **sample**, never the median, because a derived
number written as though it were an observation hides the spread.

**That log does not live in this directory, and must not be moved into
it.** A log accumulated from live use is real data about real work: the machine
paths it names, the artwork it rated, the product it was made for. So its
location is a config key, the file itself sits outside the skill tree, and
`ratings.example.jsonl` beside this file is the obviously-fake twin that
documents the record format. `config.example.json`, read in place, points at
the twin, so a fresh clone runs green with no real data present; the twin is a
fixture and the script appends to whatever `ratings_log.path` names, so an
install points that key at its own log. The install's `CONTEXT.md` names where
its log actually is. The rule and its reasoning: `/claude-skill` section 4.
The one-half sign and the star emoji in the twin's `stars` field are what
`stars()` prints, so an ASCII sweep must leave that data alone.

Records taken under one version are **not comparable** with anything another
version produces. They are kept rather than deleted: what the earlier instrument
said is evidence. v1 records carry `reasoning`; v2 and v3 records carry
`composition` and `colour`, so the record shape separates v1 even if someone
ignores the version field, and only the version and the sha separate v2 from v3.

When a human picks between candidates this tool has looked at, record it:

```bash
node "${CLAUDE_SKILL_DIR}/rate.mjs" \
  --record-pick candidate-b.png --over candidate-a.png,candidate-c.png \
  --why "b reads at thumbnail size, a doesn't"
```

The calibration question is settled for style, so this is not about
qualifying the score. It is worth keeping for the narrower claim section 1 does make -
whether the tool reliably catches breakage - and for noticing if a future model
behaves differently.

## 7. Using it

```bash
# what you should be using it for: does this generated image contain anything broken?
node "${CLAUDE_SKILL_DIR}/rate.mjs" poster.png \
  --context "Instagram 4:5 promo poster for Acme Coffee, an example cafe app"
```

`--context` is one line telling the model what the graphic is for; it changes the
critique, so keep it consistent across images you look at together. The context
line above is a PLACEHOLDER in the house shape (`Acme ...`, obviously fake):
replace it with your own product, and note that whatever you pass is written
verbatim into every log record's `context` field, so it is one of the ways real
product detail reaches the log. `ratings.example.jsonl` uses the same
placeholder, so the example invocation and the example record read as one
worked instance.

Exit codes: `0` everything rated, or an explicit `--help`; `1` some image failed
and the rest printed; `2` **the run never reached the model** (no key, no usable
model, bad usage). A request for the usage text is not a usage error, so it does
not share an exit code with one.
The `2` is deliberately distinct - "the graphic scored badly" and "we never asked
anything" must never print as the same outcome, because a caller that cannot tell
them apart will read the comfortable one.

## 8. Mechanics worth knowing before you debug it

Full detail is in the `rate.mjs` header; the traps, briefly:

- **The key** is the secret named by `secret.name`, read from the project named
  by `secret.project` with `gcloud` under the service account whose key file is
  named by `credentials.service_account_key_path` (a config key holds the *path*
  to a credential, never the credential) - **not** the firebase CLI, which prints
  its errors to stdout so a failed fetch silently becomes a 544-character "key"
  that passes every length or prefix check. The key is validated **functionally**
  (the model probe is the validation), never by shape.
- **The endpoint (`api.base`) is the one OPTIONAL config key**, and the only one
  with a default: the public endpoint is the same for every install, so
  defaulting it costs nothing and a wrong value fails loudly on the first call.
  Every other key is required and its absence is a startup failure naming the
  key, because each of the others fails badly when guessed and two of them fail
  SILENTLY - a guessed log path writes the run's records where nobody looks, and
  a guessed secret project reads a key from the wrong project. Both of those
  read as a successful run.
- **The gcloud config is isolated** (`CLOUDSDK_CONFIG` into a fresh temp dir).
  Activating a service account in the shared config repoints the whole machine's
  gcloud auth, and restoring it is a manual step for a person.
- **The advertised model list is not a list of usable models.**
  `gemini-3-pro-preview` is advertised and 404s on every call, as does the whole
  `gemini-2.5-*` generation. The script probes a candidate with a trivial request
  and falls down a list. `gemini-3.6-flash` is the current default.
- **The service-account key file is normally gitignored**, so a fresh clone or
  worktree has no key at all. The script fails naming the pattern it globbed,
  the config key it came from and the directory it resolved against, rather than
  guessing. The concrete fix for an install is in its `CONTEXT.md`.
- **The ratings log is checked before the first model call**, not at append
  time: a typo in `ratings_log.path` would otherwise cost a full run of model
  calls and then throw on the append, so the run is billed and the records are
  lost. The script refuses to create a missing log directory, because a mistyped
  path that silently creates one produces a second log nobody reads.
