#!/usr/bin/env node
/**
 * rate.mjs - rate how STYLISH a graphic looks, with a multimodal model.
 *
 * Owned by the `rate-graphic` skill (`SKILL.md` beside this file).
 *
 * ─── ⚠️ READ THIS FIRST: THE SCORE HAS BEEN CALIBRATED, AND IT FAILED ────────
 * This is a PRE-FLIGHT CHECK FOR BREAKAGE AND FACTUAL ERRORS. It is NOT a judge
 * of style, and its number MUST NOT GATE OR RANK ANYTHING.
 *
 * That is a measured result, not a caution. The calibration run (measured
 * 2026-08-09) takes one graphic through ten designer-led rounds of real
 * improvement against a byte-identical rater prompt and finds: the median moved
 * 2.90 -> 2.90, a tie; the two rounds a designer would actually ship scored
 * LOWEST of the late rounds; it hallucinated the defect it was marking down
 * (called a 0-blur shadow "soft blurry" - pixel-probed) and that defect was
 * what it had itself demanded the round before; it reversed itself, demanding a
 * hard shadow and then demanding the blur back two rounds later. Every graphic
 * in the calibration set that had shipped scored 2.6-3.4, so a 4.0 gate
 * rejects all of them.
 *
 * It is NOT blind: a deliberately wrecked control scored 1.4 with an accurate
 * description, and it caught a real map defect that merged two regions into one
 * blob. It sees gross breakage and semantic/factual errors. It does not see
 * design. Use it for the former; never for the latter.
 *
 * Evidence: the raw run - its logged calls, all under one prompt sha - stays
 * with the install that produced it, whose CONTEXT.md names where it lives. A
 * run directory is an install value, so it is not named here; the finding above
 * is what travels.
 *
 * Temperature is not the cause: 0.0 vs 0.2 over five samples on one image gave
 * an identical 0.4 spread. Do not "fix" this by lowering temperature.
 *
 * ─── What it does ────────────────────────────────────────────────────────────
 *   node rate.mjs <image...> [--context "<what it is for>"] [--model <id>]
 *   node rate.mjs --record-pick <image> --over <image>[,<image>...] [--why "..."]
 *
 * Rates one or more images. For each: a COMPOSITION analysis, a COLOUR
 * analysis, a score out of 5, a half-star string, one line on what is
 * strongest, and a list of SPECIFIC, ACTIONABLE improvements. A batch prints a
 * table in the order you passed the images - deliberately NOT sorted by score,
 * because sorting is ranking and this rater cannot rank (see above).
 *
 * ─── v2 and v3: composition and colour as NAMED STEPS before the score ───────
 * The prompt walks the model through STEP 1 composition and STEP 2 colour, each
 * with its own required output field, and only then asks for a number, told
 * explicitly that the score must be a conclusion drawn from those two steps
 * rather than a verdict justified afterwards. v3 is v2 with a different object
 * in the improvement example; its steps and output fields are v2's, so only
 * `prompt_version` and `prompt_sha` tell their records apart.
 *
 * ⚠️ DO NOT EXPECT THIS TO FIX THE CALIBRATION FAILURE, and do not let anyone
 * cite v2 or v3 as a reason to trust the number again. The prompt that FAILED
 * calibration already had a structured chain of thought: the rater prompt kept
 * beside that run asks for an ordered six-part walk-through covering
 * composition and hierarchy, typography, and "colour and material quality",
 * before scoring (it sits in the calibration run's directory). Structured
 * reasoning was present in the instrument that could not resolve craft. v2
 * makes the steps explicit and separately addressable, which is worth trying
 * and may improve the NOTES; it is not evidence about the SCORE. Only a fresh
 * calibration run is evidence about the score, and until one exists the verdict
 * above stands.
 *
 * The improvements are required to be actionable rather than diagnostic, and
 * the prompt says so with an example of each kind. "Ungrounded cutout mug
 * feels lazily assembled" names a problem and leaves the fix to guesswork;
 * "add a contact shadow under the mug and let it overlap the headline
 * baseline" is something a designer can do. ⚠️ Note what that costs, because
 * the skill file says it too: a model that hands you a checklist invites
 * completing the checklist, and a score that rises after you complete it is
 * NOT evidence the advice was good - the advice comes from the same
 * unverified source as the score.
 *
 * ─── The five-star scale is the ONLY scale ───────────────────────────────────
 * The prompt asks for a score out of 5 and the output prints a score out of 5.
 * There is deliberately no second scale anywhere - not in the prompt, not in
 * the log, not in the table. A reader must never have to reconcile two numbers
 * by arithmetic, and the cheapest way to guarantee that is for the second
 * number not to exist.
 *
 * The instrument is a PORT, not a re-derivation. Its prompt shape (a demanding
 * art director, told explicitly where "competent but forgettable" sits and to
 * use the low end, returning strict JSON) was measured on a 0-10 scale; every
 * anchor maps to the 5-point scale by halving, and nothing else about the
 * judging shape differs. Its baseline on one set of six graphics
 * (measured 2026-08-09), converted, is 4.1 / 3.4 / 2.9 / 2.6 / 2.4 / 2.1.
 * ⚠️ Do NOT tune this prompt to reproduce those numbers. They are one sample
 * from one run at temperature 0.2; fitting the prompt to them would be fitting
 * the instrument to the sample and would destroy the only thing it is for.
 *
 * ─── ⚠️ THE PROMPT IS PART OF THE INSTRUMENT - IT IS VERSIONED ───────────────
 * Changing a word of `PROMPT` changes what every score means, and turns every
 * score already in the ratings log into a non-comparison with every score
 * after it. That is not a stylistic concern: the whole point of the log is to
 * accumulate enough model-vs-human pairs to find out whether these ratings
 * track human taste, and pooling scores from two different prompts destroys
 * exactly that.
 *
 * So every log record carries `prompt_version` AND `prompt_sha` - the version
 * is declared by hand (bump `PROMPT_VERSION` when you change the prompt) and
 * the sha is computed from the prompt text at runtime. Both, deliberately: the
 * hand-declared version is the one a human reads, and the sha is what catches
 * the change where somebody edited a word and did not bump the version. When
 * you analyse the log, GROUP BY `prompt_sha` first. Scores from two shas are
 * two instruments, not one instrument with noise.
 *
 * Live example of exactly that: records taken under v1 (`910efe5681b5`, a
 * free-form `reasoning` field) are NOT comparable with anything a later version
 * produces. They are kept, not deleted - a record of what the earlier instrument
 * said is evidence; silently pooling it with a later one would be the mistake.
 * v1 records carry `reasoning`; v2 and v3 records carry `composition` and
 * `colour`, so the shape separates v1 even if someone ignores the version field,
 * and only the version and the sha separate v2 from v3.
 *
 * ─── ⚠️ MEASURED: THE SCORE IS NOT REPRODUCIBLE. THIS IS WHY --repeat EXISTS ─
 * Four runs of one prompt, same model, temperature 0.2, over the same
 * six graphics (measured 2026-08-09):
 *
 *   image-a       2.2 / 1.8 / 2.0 / 2.2      range 0.4
 *   image-b       2.2 / 2.0 / 2.2 / 2.3      range 0.3
 *   image-c       2.2 / 2.1 / 2.1 / 2.2      range 0.1
 *   image-d       2.4 / 2.8 / 3.8 / 2.2      range 1.6   <- a third of the scale
 *   image-e       2.2 / 2.7 / 3.8 / 2.4      range 1.6   <- a third of the scale
 *   image-f       2.1 / 1.8 / 2.1 / 2.1      range 0.3
 *
 * The RANKING reorders between runs: in one run image-d and image-e are
 * joint top at 3.8; in the next they are mid-pack at 2.2 and 2.4. Nothing about
 * the input changed. Four of six images were stable within 0.4 and two were
 * not, so instability is not uniform and you cannot tell from a single run
 * which kind of image you are holding.
 *
 * That is the single most important measured fact about this tool, and it is
 * the reason a single sample must never be presented as a ranking. So this
 * script SAMPLES EACH IMAGE `--repeat` TIMES (default 3), reports the MEDIAN
 * with the observed range beside it, and flags any image whose range exceeds
 * `UNSTABLE_RANGE`. Do not "optimise" the default back to 1: a single-shot
 * number here is measurably capable of naming the wrong winner, and it names
 * it with exactly the same confident formatting as a real one.
 *
 * Every individual sample is logged as its own record - never the median. A
 * derived number written into the log as though it were an observation is how
 * the spread becomes invisible to whoever calibrates this later.
 *
 * PRECISION vs GRANULARITY, since they differ on purpose: the score is one
 * decimal (0.0-5.0) because the main use is RANKING candidates and a
 * half-point-granular score ties them - that baseline has two graphics
 * 0.2 apart, which a half-point score would collapse into a tie and a tie
 * defeats the comparison. The STAR STRING is what carries half-point
 * granularity: `3.4 / 5 ⭐⭐⭐½`. Rendering half stars as a `½` rather than a
 * half-star glyph is deliberate - the half-star codepoints render as tofu in
 * several terminals and in Slack, and a score that displays as a missing glyph
 * is worse than a plain one.
 *
 * ─── Key handling (do not "simplify" this) ──────────────────────────────────
 * The key is the secret named by `secret.name`, read from the project named by
 * `secret.project`, fetched with `gcloud` under the SERVICE ACCOUNT whose key
 * file is named by `credentials.service_account_key_path`. Those three are
 * config keys, not values in this file: which secret store an install reads is
 * per-install, and a credential PATH is the most a config may ever hold.
 * Two properties of the mechanism are load-bearing:
 *
 *   (a) NOT the firebase CLI. That CLI prints its errors to STDOUT, so a failed
 *       fetch does not fail - it silently returns a 544-character English error
 *       message that every shape-based check ("is it non-empty?", "is it long
 *       enough?") accepts as a key. This is why the key is validated
 *       FUNCTIONALLY here (the model probe below IS the validation) and never
 *       by length or prefix. A shape check on a 544-character error passes.
 *
 *   (b) An ISOLATED `CLOUDSDK_CONFIG`. `gcloud auth activate-service-account`
 *       against the shared config repoints the whole MACHINE's gcloud auth,
 *       and only a manual restore puts it back. This script always activates
 *       into a fresh `mktemp -d` and removes it.
 *
 * `GEMINI_API_KEY` in the environment short-circuits both, for a caller who
 * already has one. It is validated by the same probe, never trusted.
 *
 * ─── Model selection: the advertised list is not a list of usable models ─────
 * `/v1beta/models` advertises `gemini-3-pro-preview`, which returns 404 "no
 * longer available" on every call - so does the whole `gemini-2.5-*`
 * generation. Availability is therefore established by PROBING a candidate
 * with a trivial request and falling down the list on any non-200, never by
 * reading the model list and never by a hardcoded assumption. Measured
 * 2026-08-09 against one install's API key: `gemini-3.6-flash` 200,
 * `gemini-3.5-flash` 200, `gemini-flash-latest` 200, `gemini-3.1-pro-preview`
 * 200, `gemini-3-pro-preview` 404, `gemini-3-flash` 404, `gemini-2.5-flash`
 * 404. The probe is one cheap text call and it is what makes a model
 * retirement a graceful downgrade instead of a broken skill.
 *
 * ─── The log is the point, not bookkeeping ──────────────────────────────────
 * Every rating appends a JSONL record to the log named by the config key
 * `ratings_log.path`: the image path and a content hash, the score, both
 * notes, the model and the date. That file is the ONLY thing that can ever
 * tell us whether these ratings track human taste. The calibration signal is
 * DISAGREEMENT - when a human picks a different winner than the model did,
 * that pair is the datum. So `--record-pick` exists to write the human's
 * choice into the same log, next to the model's ranking of the same
 * candidates. A log of model scores with no human verdicts in it can never
 * calibrate anything.
 *
 * The log lives at a durable path (not /tmp) so it survives the session, and
 * it is append-only JSONL specifically so an install that versions it can
 * merge two worktrees' appends without a semantic conflict.
 *
 * ⚠️ It does NOT live in the skill directory, and that is deliberate. A log
 * accumulated from live use is real data about real work: absolute machine
 * paths, unreleased artwork, the product it was made for. This skill tree is
 * publishable, and a corpus like that must not be in it - so the log's
 * location is a CONFIG KEY, `ratings_log.path`, and `ratings.example.jsonl`
 * beside this script is the obviously-fake twin that documents its schema and
 * lets a fresh clone run green with no real data present. Do not move the real
 * log back in here for convenience; the install's `CONTEXT.md` names where it
 * actually is.
 * The rule and its reasoning: `claude-skill/SKILL.md` section 4.
 *
 * --- Configuration: nothing install-specific is hardcoded here --------------
 * Every value that differs between installs lives in `config.json` in this
 * skill's INSTALL CONTEXT - the file `fleet where rate-graphic config.json`
 * names - documented key by key in `config.example.json`;
 * `RATE_GRAPHIC_CONFIG` points the script at a different one. Relative paths
 * in it resolve against THE CONFIG FILE'S DIRECTORY, never the caller's cwd
 * and never this script's directory. A missing required key exits 2 at
 * startup naming the key, before any model call is paid for.
 *
 * The INSTRUMENT is deliberately NOT configurable: `PROMPT`, `PROMPT_VERSION`,
 * `MODEL_CANDIDATES`, `DEFAULT_REPEAT` and `UNSTABLE_RANGE` stay in code,
 * because they are what a score MEANS. A config key able to change the prompt
 * would let two installs append mutually incomparable records to one log,
 * which is the exact failure `prompt_version`/`prompt_sha` exists to catch.
 *
 * ─── Exit codes ─────────────────────────────────────────────────────────────
 *   0  every requested image was rated
 *   1  at least one image could not be rated (the run still prints the rest)
 *   2  the run never reached the model - no key, no usable model, bad usage.
 *      Deliberately distinct from 1: "the graphic scored badly" and "we never
 *      asked anything" must never print as the same outcome, because a caller
 *      that cannot tell them apart will read the comfortable one.
 */

import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { appendFileSync, globSync, mkdtempSync, readFileSync, realpathSync, rmSync, existsSync } from 'node:fs';
import { homedir, tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));

// --- configuration ----------------------------------------------------------
// NOTHING install-, deployment- or machine-specific is hardcoded in this file.
// Every value that differs between installs - where the ratings log lives,
// which secret in which project holds the API key, where the service-account
// key file is - lives in config.json in this skill's install context,
// documented key by key in config.example.json; RATE_GRAPHIC_CONFIG points the
// script at a different one.
//
// The INSTRUMENT is deliberately NOT configurable: PROMPT, PROMPT_VERSION,
// MODEL_CANDIDATES, DEFAULT_REPEAT and UNSTABLE_RANGE stay in code below,
// because they are what a score MEANS. A config key able to change the prompt
// would let two installs append records to one log that are not comparable
// with each other, which is the one thing prompt_version/prompt_sha exists to
// prevent.
const REQUIRED = Symbol('required');

/**
 * Which config.json this run reads: RATE_GRAPHIC_CONFIG when set, else the file
 * `fleet where rate-graphic config.json` names, through the fleet's one lookup
 * (lib/fleet-where.mjs, loaded from this file's realpath; its header says why).
 * Two readers resolving differently would mean two config files - and here, two
 * ratings logs. Any failure exits 2 naming the command and the variable that
 * bypasses it: the run never reached the model.
 */
const FLEET_WHERE = pathToFileURL(path.join(realpathSync(HERE), '..', '..', '..', 'lib', 'fleet-where.mjs')).href;
const { configFile } = await import(FLEET_WHERE)
  .catch((e) => die2(`config: cannot load ${FLEET_WHERE} (${e.code || e.message})`));
const CONFIG_FILE = (() => {
  try { return configFile('rate-graphic', 'RATE_GRAPHIC_CONFIG'); }
  catch (e) { return die2(`config: ${e.message}`); }
})();
const CONFIG_DIR = path.dirname(CONFIG_FILE);

function loadConfig(file) {
  let raw;
  try {
    raw = readFileSync(file, 'utf8');
  } catch (e) {
    die2(`config: cannot read ${file} (${e.code || e.message})\nCopy config.example.json there and fill it in.`);
  }
  try {
    return JSON.parse(raw);
  } catch (e) {
    die2(`config: ${file} is not valid JSON - ${e.message}`);
  }
}

const CONFIG = loadConfig(CONFIG_FILE);

/**
 * Read a dotted key out of CONFIG. A missing REQUIRED key exits loudly NAMING
 * the key rather than defaulting, because every required value here fails
 * badly when guessed and two of them fail SILENTLY: a guessed ratings-log path
 * writes the run's records where nobody will look for them, and a guessed
 * secret project reads a key from the wrong project. Both of those look like a
 * successful run. Unknown keys are ignored - the _comment keys are
 * documentation (JSON has no comment syntax) and a newer config must stay
 * loadable by an older script.
 */
function cfg(dotted, dflt = REQUIRED) {
  let node = CONFIG;
  for (const part of dotted.split('.')) {
    if (node === null || typeof node !== 'object' || !(part in node)) {
      if (dflt === REQUIRED) die2(`config: ${CONFIG_FILE} is missing required key '${dotted}'`);
      return dflt;
    }
    node = node[part];
  }
  return node;
}

/**
 * Expand `${VAR:-default}`, then `$VAR` / `${VAR}`. NOTHING does this for us:
 * JSON is a data format and Node expands neither form, so a config naming a
 * credential store as `${SOME_SECRETS_DIR:-$HOME/.some-secrets}` is a literal
 * string until this function runs.
 *
 * `||`, not `??`, on purpose: that is shell `:-` semantics, where an EMPTY
 * variable takes the default too. A caller who exported the variable to "" means
 * "I did not set this", and `??` would hand them a path rooted at "/".
 *
 * ⚠️ An unset variable with NO default is left as the LITERAL `$NAME`, and that
 * is deliberate. The glob then matches nothing and `resolveKey` dies printing
 * the unexpanded pattern, which names the variable nobody set. Substituting ''
 * instead would silently point at a different, possibly existing file - and a
 * run that authenticates with the wrong key succeeds against the right API. Do
 * not "tidy" this into an empty substitution.
 */
function expandVars(p) {
  let s = p;
  // BOUNDED, not `while it changes`. The loop repeats only to reach a nested
  // ${A:-${B:-c}}, which is at most a handful of levels; an env var whose own
  // value re-introduces the pattern would otherwise grow the string forever and
  // this function would never return. A hang is the worst failure available
  // here - it looks like a slow run - so the loop stops and whatever is left
  // stays literal, which fails loudly instead.
  for (let i = 0; i < 10; i += 1) {
    const prev = s;
    s = s.replace(
      /\$\{([A-Za-z_][A-Za-z0-9_]*):-([^{}]*)\}/g,
      (_m, name, dflt) => process.env[name] || dflt,
    );
    if (s === prev) break;
  }
  return s.replace(
    /\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)/g,
    (m, braced, bare) => {
      const v = process.env[braced || bare];
      return v === undefined ? m : v;
    },
  );
}

/**
 * Resolve a config path. RELATIVE PATHS RESOLVE AGAINST THE CONFIG FILE'S
 * DIRECTORY, and that convention is load bearing in every direction it could
 * have gone. cwd-relative would make one config file mean different targets
 * depending on where the caller stood, and this script is run from a repo
 * root, from a worktree and from a skill directory. Script-relative would
 * point into the fleet tree, which is shared by every install on the host and
 * holds none of their files. Relative to the config file, a value means the
 * same file from every caller, because the config file stays where the install
 * put it. Variables are expanded first (see `expandVars`), then a leading `~/`
 * expands against the current user's home; an absolute path is used as given.
 */
function configPath(p) {
  const v = expandVars(p);
  const expanded = v === '~' ? homedir() : v.startsWith('~/') ? path.join(homedir(), v.slice(2)) : v;
  return path.resolve(CONFIG_DIR, expanded);
}

// The ratings log. It lives OUTSIDE the skill tree by design (see the log
// section in the header): a log accumulated from live use is real company
// data, and the skill tree is publishable. Its path is therefore a config key
// and never a path in this directory. `ratings_log.path` is REQUIRED: a
// defaulted log path is how a run's records end up somewhere nobody reads.
const LOG_PATH = configPath(cfg('ratings_log.path'));

/** Candidates in preference order. Each is PROBED before use - see header. */
const MODEL_CANDIDATES = [
  'gemini-3.6-flash',
  'gemini-3.5-flash',
  'gemini-flash-latest',
  'gemini-3.1-pro-preview',
];

// Endpoint, and which secret in which project holds the key. `api.base` is the
// one optional key: the public endpoint is the same for every install, so
// defaulting it costs nothing and a wrong value fails loudly on the first
// call. GEMINI_API_BASE still wins, for probing against a stand-in.
// `secret.name` and `secret.project` are REQUIRED - a guessed project reads a
// key from the wrong project, and that reads as a successful run.
const API_BASE =
  process.env.GEMINI_API_BASE || cfg('api.base', 'https://generativelanguage.googleapis.com/v1beta');
const SECRET_NAME = cfg('secret.name');
const SECRET_PROJECT = cfg('secret.project');

// Path (or glob) to the service-account key file used to READ that secret. A
// PATH, never the key: see claude-skill/SKILL.md section 4. REQUIRED, but only
// consulted when GEMINI_API_KEY is absent from the environment.
const SA_KEY_PATTERN = cfg('credentials.service_account_key_path');

/** Samples per image unless overridden. See the reproducibility block above. */
const DEFAULT_REPEAT = 3;

/** An observed range at or above this is reported as UNSTABLE, not as a score. */
const UNSTABLE_RANGE = 0.5;

const MIME = {
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
  '.gif': 'image/gif',
  '.heic': 'image/heic',
  '.heif': 'image/heif',
};

// ── The prompt ───────────────────────────────────────────────────────────────
// Ported from the proven 0-10 shape by halving every anchor. Change the
// WORDING here only with a reason that is not "the numbers came out low", and
// BUMP PROMPT_VERSION in the same edit - see the header. The `prompt_sha` in
// the log is what catches you if you forget.
//
// ⚠️ THE PROMPT TEXT BELOW IS EXEMPT FROM THIS TREE'S ASCII SWEEP, AND THAT
// EXEMPTION IS LOAD-BEARING. It contains six U+2014 EM DASH characters, which
// the house rule would otherwise turn into hyphens. They must stay byte-exact,
// because PROMPT_SHA is sha256 over this exact text, and every record an
// install's ratings log already holds carries it. Rewriting one dash changes
// the sha, so those records stop grouping with anything produced afterwards -
// silently, because nothing goes red and the version field still says the same
// version. A punctuation sweep would then have created a new instrument without
// bumping PROMPT_VERSION, which is the exact failure the version/sha pair
// exists to catch.
//
// So: if you are normalising punctuation in this file, STOP at the backtick
// below and resume after the closing one. If you genuinely mean to change the
// prompt, bump PROMPT_VERSION in the same edit - a deliberate change is fine,
// an incidental one is the bug. rate.test.mjs pins the sha for this reason and
// will go red if either happens by accident.
const PROMPT_VERSION = 'v3';

const PROMPT = (context) => `You are a demanding art director reviewing a graphic. You are hard to impress, and you use the whole range — especially the low end.

Judge the graphic as a FINISHED PIECE, not as an idea.
${context ? `\nWhat the graphic is for: ${context}\n` : ''}
Work through the analysis BELOW IN ORDER, and only then commit to a number. The score must be a conclusion drawn from what you found in steps 1 and 2 — never a verdict you decide first and then justify. If your analysis did not identify a specific problem, that problem may not appear in your score.

STEP 1 — COMPOSITION. Work through, naming what you actually see and where it sits:
- what the eye hits first, second and third, and whether that order is the one the piece needs;
- the underlying structure: grid, margins, alignment, optical balance, use of empty space;
- scale relationships and hierarchy between the elements;
- anything stranded, floating, ungrounded, colliding, cramped against an edge, or competing for the same job;
- whether the composition still reads at thumbnail size.

STEP 2 — COLOUR. Work through, naming actual colours and where they appear:
- the palette in use and whether it is doing deliberate work or is arbitrary;
- contrast, and specifically any text or element whose legibility is at risk;
- how the colour carries hierarchy and where the eye is pulled;
- surface and material quality: does it read as a considered, physical, printed object, or as an untouched digital template;
- any clash, muddiness, or colour that fights the piece's intent.

STEP 3 — SCORE. Only now, and only from what steps 1 and 2 established.

Score out of 5:
- 2.5 = competent but forgettable. Nothing is wrong with it and nothing is memorable. Most professional work lands here.
- below 2.5 = flawed: muddled hierarchy, default typography, arbitrary colour, no idea.
- 4.0 and up = genuinely good. It would stop you scrolling.
- 5.0 = portfolio work. Reserve it.

Most work is not good. Use the low end.

The improvements must be ACTIONABLE, not diagnostic. Name the specific move a designer should make, not the symptom you noticed.
- Not actionable: "the ungrounded cutout mug feels lazily assembled".
- Actionable: "add a soft contact shadow under the mug and let its base overlap the headline baseline by ~20px so it sits in the space".
Each improvement names WHAT to change, WHERE in the composition, and roughly BY HOW MUCH where a size, weight, spacing or colour is involved.

Reply with STRICT JSON and nothing else — no markdown fence, no prose around it. The keys must appear in this order, because it is the order you must think in:
{"composition": "<STEP 1: your composition analysis, 3-5 sentences, citing specific elements and where they sit>", "colour": "<STEP 2: your colour analysis, 3-5 sentences, naming actual colours and where they appear>", "score": <STEP 3: number between 0.0 and 5.0, one decimal, concluded from steps 1 and 2>, "best": "<one sentence: the single strongest thing about it>", "improvements": ["<specific actionable change>", "<specific actionable change>", "<specific actionable change>"]}`;

/** Identity of the exact prompt text in use, independent of the declared version. */
const PROMPT_SHA = createHash('sha256').update(PROMPT(null)).digest('hex').slice(0, 12);

// ── CLI ──────────────────────────────────────────────────────────────────────

function usage(msg) {
  if (msg) process.stderr.write(`rate.mjs: ${msg}\n\n`);
  process.stderr.write(`Usage:
  node rate.mjs <image...> [--context "<what it is for>"] [--repeat <n>] [--model <id>] [--json] [--no-log]
  node rate.mjs --record-pick <image> --over <image>[,<image>...] [--why "<one line>"]

  --context     one line telling the model what the graphic is for (optional)
  --repeat      samples per image (default ${DEFAULT_REPEAT}). The score is NOT reproducible -
                identical re-runs have moved an image by 1.6 points out of 5 and
                reordered the ranking. Lower this only for throwaway probing.
  --model       force a model id, skipping the availability probe
  --json        print one JSON object instead of the human table
  --no-log      do not append to the ratings log (throwaway probing only)
  --record-pick record the HUMAN's winner among candidates already rated;
                this is what makes the log calibratable - see SKILL.md
`);
  // An explicit --help is a question that was answered: exit 0. A usage ERROR
  // keeps exit 2. Both are "the run never reached the model", so 2 would be
  // defensible for --help too, and it is still wrong: a caller scripting
  // `rate.mjs --help` reads a non-zero status as a broken install and stops.
  // `msg` is what separates them - only a rejection carries one - so a future
  // caller that passes a message for a non-error would silently re-break this.
  process.exit(msg ? 2 : 0);
}

function parseArgs(argv) {
  const out = {
    images: [],
    context: null,
    model: null,
    json: false,
    log: true,
    repeat: DEFAULT_REPEAT,
    pick: null,
    over: [],
    why: null,
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    const next = () => {
      const v = argv[++i];
      if (v === undefined) usage(`${a} needs a value`);
      return v;
    };
    if (a === '--context') out.context = next();
    else if (a === '--repeat') {
      out.repeat = Number(next());
      if (!Number.isInteger(out.repeat) || out.repeat < 1) usage('--repeat needs a positive integer');
    } else if (a === '--model') out.model = next();
    else if (a === '--json') out.json = true;
    else if (a === '--no-log') out.log = false;
    else if (a === '--record-pick') out.pick = next();
    else if (a === '--over') out.over = next().split(',').map((s) => s.trim()).filter(Boolean);
    else if (a === '--why') out.why = next();
    else if (a === '-h' || a === '--help') usage();
    else if (a.startsWith('-')) usage(`unknown flag ${a}`);
    else out.images.push(a);
  }
  return out;
}

// ── Key ──────────────────────────────────────────────────────────────────────

/**
 * Resolve the Gemini key. NEVER validated by shape here - see the header: a
 * failed firebase-CLI fetch is a 544-character string that passes every shape
 * check ever written. The functional probe downstream is the validation.
 */
function resolveKey() {
  const fromEnv = (process.env.GEMINI_API_KEY || '').trim();
  if (fromEnv) return { key: fromEnv, source: 'env:GEMINI_API_KEY' };

  // The key FILE is named by config (`credentials.service_account_key_path`),
  // resolved against the config file's directory when relative. It is globbed rather
  // than read literally because a provisioned key filename usually carries a
  // per-project suffix nobody wants to paste into a config; a value with no
  // `*` in it globs to itself, so one code path serves both.
  const pattern = configPath(SA_KEY_PATTERN);
  const matches = globSync(pattern).sort();
  if (!matches.length) {
    die2(
      `no service-account key matched ${pattern}\n` +
        `(config key 'credentials.service_account_key_path' in ${CONFIG_FILE},\n` +
        ` resolved against the config file's directory ${CONFIG_DIR})\n` +
        `The key deliberately lives OUTSIDE the skill tree, so a clone that has\n` +
        `never been provisioned has none. Either put one where that pattern\n` +
        `points, fix the config key, or export GEMINI_API_KEY yourself.\n` +
        `If the pattern above still contains a literal $NAME, that variable is\n` +
        `unset - the path was never expanded, and nothing guessed a substitute.`,
    );
  }
  if (matches.length > 1) {
    // Never silent: choosing among several key files is a decision, and the
    // wrong one authenticates as the wrong principal against the right API.
    process.stderr.write(
      `rate.mjs: ${matches.length} files matched ${pattern}; using ${matches[0]}\n`,
    );
  }
  const keyFile = matches[0];

  // Isolated CLOUDSDK_CONFIG - activating the SA in the shared config would
  // repoint this whole machine's gcloud auth. See header (b). The directory then
  // holds the activated account's credentials, so it is removed on every way
  // out. die2() is process.exit, and an exit inside the try skips the finally:
  // a failure is RECORDED inside, and die2 runs only after the finally removed
  // the directory.
  const cfg = mkdtempSync(path.join(tmpdir(), 'rate-graphic-gcloud-'));
  let failure;
  try {
    const env = { ...process.env, CLOUDSDK_CONFIG: cfg };
    execFileSync('gcloud', ['auth', 'activate-service-account', `--key-file=${keyFile}`, '-q'], {
      env,
      stdio: ['ignore', 'ignore', 'pipe'],
    });
    const key = execFileSync(
      'gcloud',
      ['secrets', 'versions', 'access', 'latest', `--secret=${SECRET_NAME}`, `--project=${SECRET_PROJECT}`],
      { env, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] },
    ).trim();
    if (key) return { key, source: `secret-manager:${SECRET_PROJECT}/${SECRET_NAME}` };
    failure = `Secret Manager returned nothing for ${SECRET_NAME}`;
  } catch (e) {
    failure = `could not fetch ${SECRET_NAME} via the service account: ${String(e.stderr || e.message || e).trim()}`;
  } finally {
    rmSync(cfg, { recursive: true, force: true });
  }
  return die2(failure);
}

// ── Model ────────────────────────────────────────────────────────────────────

async function callModel(model, key, parts, temperature) {
  const res = await fetch(`${API_BASE}/models/${model}:generateContent`, {
    method: 'POST',
    headers: { 'x-goog-api-key': key, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      contents: [{ parts }],
      generationConfig: { temperature, responseMimeType: 'application/json' },
    }),
  });
  const body = await res.text();
  return { ok: res.ok, status: res.status, body };
}

/**
 * Establish a USABLE model by probing. The advertised model list is not a list
 * of usable models (header): `gemini-3-pro-preview` is advertised and 404s on
 * every call. This probe is also what functionally validates the key - a bad
 * key fails every candidate with 401/403, and we exit 2 rather than reporting
 * a model problem.
 */
async function pickModel(forced, key) {
  const candidates = forced ? [forced] : MODEL_CANDIDATES;
  const failures = [];
  for (const m of candidates) {
    const r = await callModel(m, key, [{ text: 'Reply with the single word OK.' }], 0);
    if (r.ok) return m;
    failures.push(`${m} -> HTTP ${r.status}`);
    if (r.status === 401 || r.status === 403) {
      die2(`the API key was refused (HTTP ${r.status}). Fetched key is not valid.\n  ${r.body.slice(0, 300)}`);
    }
  }
  die2(`no usable model. Probed:\n  ${failures.join('\n  ')}`);
}

// ── Rating ───────────────────────────────────────────────────────────────────

function extractJson(body) {
  const outer = JSON.parse(body);
  const text = (outer?.candidates?.[0]?.content?.parts || [])
    .map((p) => p.text)
    .filter(Boolean)
    .join('');
  if (!text) throw new Error(`model returned no text (finishReason=${outer?.candidates?.[0]?.finishReason})`);
  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/);
  return JSON.parse((fenced ? fenced[1] : text).trim());
}

async function rateOne(file, model, key, context) {
  const bytes = readFileSync(file);
  const ext = path.extname(file).toLowerCase();
  const mimeType = MIME[ext];
  if (!mimeType) throw new Error(`unsupported image extension ${ext || '(none)'}`);

  const r = await callModel(
    model,
    key,
    [
      { text: PROMPT(context) },
      { inline_data: { mime_type: mimeType, data: bytes.toString('base64') } },
    ],
    0.2,
  );
  if (!r.ok) throw new Error(`HTTP ${r.status}: ${r.body.slice(0, 300)}`);

  const parsed = extractJson(r.body);
  const score = Number(parsed.score);
  if (!Number.isFinite(score) || score < 0 || score > 5) {
    throw new Error(`model returned an out-of-range score: ${JSON.stringify(parsed.score)}`);
  }
  const improvements = Array.isArray(parsed.improvements)
    ? parsed.improvements.map((s) => String(s).trim()).filter(Boolean)
    : String(parsed.improvements ?? '')
        .split('\n')
        .map((s) => s.trim())
        .filter(Boolean);
  return {
    file,
    sha256: createHash('sha256').update(bytes).digest('hex').slice(0, 16),
    composition: String(parsed.composition ?? '').trim(),
    colour: String(parsed.colour ?? '').trim(),
    score: Math.round(score * 10) / 10,
    best: String(parsed.best ?? '').trim(),
    improvements,
  };
}

/**
 * Collapse N samples of one image into what gets REPORTED. The headline number
 * is the MEDIAN, not the mean: one wild sample (measured: 2.2 among three 3.8s)
 * drags a mean toward a value no run ever produced, while the median stays a
 * score the model actually gave. The `range` travels with it always - a median
 * printed without its spread is the single-shot problem wearing a disguise.
 *
 * The notes shown are the MEDIAN SAMPLE's own notes, so the printed reasoning,
 * best and fixes are one coherent critique from one run rather than a blend of
 * three that no reviewer ever wrote.
 */
function collapse(samples) {
  const sorted = [...samples].sort((a, b) => a.score - b.score);
  const mid = sorted[Math.floor((sorted.length - 1) / 2)];
  const lo = sorted[0].score;
  const hi = sorted[sorted.length - 1].score;
  return {
    ...mid,
    score: mid.score,
    n: samples.length,
    lo,
    hi,
    range: Math.round((hi - lo) * 10) / 10,
    unstable: hi - lo >= UNSTABLE_RANGE,
    samples: samples.map((s) => s.score),
  };
}

/** Half-star string. `½` rather than a half-star glyph - see header. */
function stars(score) {
  const halves = Math.round(score * 2);
  return '⭐'.repeat(Math.floor(halves / 2)) + (halves % 2 ? '½' : '');
}

// ── Log ──────────────────────────────────────────────────────────────────────

function logRecord(rec) {
  appendFileSync(LOG_PATH, JSON.stringify(rec) + '\n');
}

/**
 * Fail NOW if the configured log cannot be appended to. What is checked is the
 * PARENT DIRECTORY, because appendFileSync creates a missing file but not a
 * missing directory above it.
 *
 * WARNING - this gate is load-bearing, and if it is removed nothing goes red.
 * Without it, a typo in `ratings_log.path` costs N model calls first and then
 * throws on the append: the run is billed, the notes are printed, and the
 * records - the only thing that can ever calibrate this rater - are lost. Do
 * not "simplify" it away on the grounds that appendFileSync would have failed
 * anyway. WHEN it fails is the entire point.
 *
 * It also refuses to CREATE the directory, deliberately. A mistyped path that
 * silently mkdir -p's itself produces a second log nobody ever reads, and a
 * split log is worse than a missing one: the first is invisible, the second is
 * loud. Making a new location is a decision, so it stays a human's.
 */
function requireWritableLog() {
  const dir = path.dirname(LOG_PATH);
  if (!existsSync(dir)) {
    die2(
      `the ratings log's directory does not exist: ${dir}\n` +
        `(config key 'ratings_log.path' = ${JSON.stringify(cfg('ratings_log.path'))}\n` +
        ` in ${CONFIG_FILE}, resolved against its directory to\n` +
        ` ${LOG_PATH})\n` +
        `Create it with mkdir -p, or fix the config key. Nothing was rated: the\n` +
        `log is checked BEFORE any model call, so a typo here costs no API spend.`,
    );
  }
}

function die2(msg) {
  const e = new Error(msg);
  e.__rate_graphic_die = true;
  process.stderr.write(`rate.mjs: ${msg}\n`);
  process.exit(2);
}

// ── Modes ────────────────────────────────────────────────────────────────────

function recordPick(args) {
  if (!args.over.length) usage('--record-pick needs --over <the candidates it beat>');
  const rec = {
    kind: 'human_pick',
    ts: new Date().toISOString(),
    picked: path.resolve(args.pick),
    over: args.over.map((p) => path.resolve(p)),
    why: args.why || null,
  };
  // --no-log suppresses this write exactly as it suppresses a rating write.
  // One flag, one meaning: a --no-log that silently still wrote here made a
  // throwaway probe leave a calibration datum in the corpus, which is the
  // record type that must NEVER be accidental - it is the human's verdict.
  const beat = `${path.basename(rec.picked)} over ${rec.over.map((p) => path.basename(p)).join(', ')}`;
  // Say where it went, or say plainly that it went nowhere. Same contract as
  // printTable's log line: a reader who cannot see the path cannot tell a logged
  // run from a --no-log one, and here the two are worth very different amounts.
  if (args.log) {
    logRecord(rec);
    process.stdout.write(
      `Recorded the human pick: ${beat}\n` +
        `Appended to ${LOG_PATH}\n` +
        `This is the calibration datum - a model score with no human verdict beside it proves nothing.\n`,
    );
  } else {
    process.stdout.write(
      `--no-log: the human pick ${beat} was NOT recorded.\n` +
        `A pick outside the log calibrates nothing; drop --no-log to keep it.\n`,
    );
  }
}

function printTable(results, model, logPath) {
  const width = Math.max(...results.map((r) => path.basename(r.file).length), 4);
  const pad = (s, n) => String(s).padEnd(n);
  const lines = [];
  lines.push(
    `model: ${model}   temperature: 0.2   prompt: ${PROMPT_VERSION} (${PROMPT_SHA})   ${new Date().toISOString().slice(0, 10)}`,
  );
  // Where the records went. Printed because the log's location is a config key,
  // not a fixed file beside this script: a reader who cannot see the path cannot
  // tell a logged run from a --no-log one.
  lines.push(logPath ? `log:   ${logPath}` : 'log:   (--no-log: nothing was recorded)');
  lines.push('');
  const n = results[0]?.n ?? 1;
  lines.push('(listed in the order you passed them - this is NOT a ranking; see below)');
  lines.push('');
  lines.push(`  ${pad('GRAPHIC', width)}  SCORE${n > 1 ? '            ACROSS ' + n + ' RUNS' : ''}`);
  lines.push(`  ${'-'.repeat(width)}  ${'-'.repeat(n > 1 ? 33 : 14)}`);
  for (const r of results) {
    const spread = n > 1 ? `  ${r.lo.toFixed(1)}-${r.hi.toFixed(1)}${r.unstable ? '  UNSTABLE' : ''}` : '';
    lines.push(
      `  ${pad(path.basename(r.file), width)}  ${pad(`${r.score.toFixed(1)} / 5 ${stars(r.score)}`, 14)}${spread}`,
    );
  }
  const unstable = results.filter((r) => r.unstable);
  if (n > 1 && unstable.length) {
    lines.push('');
    lines.push(
      `  ⚠️  ${unstable.length} of ${results.length} moved by >= ${UNSTABLE_RANGE.toFixed(1)} across identical re-runs.`,
    );
    lines.push('     For those, this tool has no opinion about where they rank. Two graphics');
    lines.push('     whose ranges overlap are TIED here, whatever the medians say.');
  }
  lines.push('');
  lines.push('Notes (worth more than the numbers):');
  for (const r of results) {
    lines.push('');
    lines.push(
      `  ${path.basename(r.file)}  -  ${r.score.toFixed(1)} / 5${r.n > 1 ? `  (median of ${r.n}: ${r.samples.map((s) => s.toFixed(1)).join(', ')})` : ''}`,
    );
    if (r.composition) lines.push(`    composition: ${r.composition}`);
    if (r.colour) lines.push(`    colour:      ${r.colour}`);
    if (r.best) lines.push(`    best:        ${r.best}`);
    for (const imp of r.improvements) lines.push(`    fix:         ${imp}`);
  }
  lines.push('');
  lines.push('THIS NUMBER MUST NOT GATE OR RANK ANYTHING. Calibrated 2026-08-09 over ten');
  lines.push('designer-led rounds: the median moved 2.90 -> 2.90, the two rounds a designer');
  lines.push('would actually ship scored LOWEST of the late rounds, and it marked down a');
  lines.push('defect that pixel-probing showed was not there. Every shipped graphic in the');
  lines.push('calibration set scored 2.6-3.4, so a 4.0 bar rejects all of them.');
  lines.push('');
  lines.push('What it IS good for: gross breakage and factual/semantic errors in artwork');
  lines.push('(a wrecked control scored 1.4 with an accurate description, and it caught a');
  lines.push('real map defect). Read the composition and colour notes for THAT. Do not');
  lines.push('iterate to raise the number, and do not treat the fixes as a work order -');
  lines.push('one round executed all of them at once and produced the worst graphic of the');
  // The evidence PATH is install-specific and deliberately not printed from
  // here: this string ships to every adopter, and a path into one install's
  // checkout is noise everywhere else. SKILL.md carries the finding.
  lines.push('run. The calibration finding: section 1 of the skill\'s SKILL.md.');
  process.stdout.write(lines.join('\n') + '\n');
}

// ── Main ─────────────────────────────────────────────────────────────────────

async function main() {
  const args = parseArgs(process.argv.slice(2));

  // Before the key, before the model, before any spend: prove the configured
  // log can take the records this run is about to produce. See
  // requireWritableLog for why the ordering is the property, not the check.
  // `args.log` is the single gate on every write this script makes, in both
  // modes, so it is also the single gate on checking that the log can take one.
  if (args.log) requireWritableLog();

  if (args.pick) return recordPick(args);
  if (!args.images.length) usage('give at least one image path');

  for (const f of args.images) {
    if (!existsSync(f)) die2(`no such file: ${f}`);
  }

  const { key } = resolveKey();
  const model = await pickModel(args.model, key);

  const runId = createHash('sha256')
    .update(String(Date.now()) + args.images.join('\0'))
    .digest('hex')
    .slice(0, 12);

  const results = [];
  const failures = [];
  for (const f of args.images) {
    const samples = [];
    for (let i = 0; i < args.repeat; i++) {
      try {
        const r = await rateOne(f, model, key, args.context);
        samples.push(r);
        if (args.log) {
          // One record per SAMPLE, never the median - see the header. A derived
          // number logged as an observation hides the spread from calibration.
          logRecord({
            kind: 'rating',
            ts: new Date().toISOString(),
            run_id: runId,
            sample: i + 1,
            of: args.repeat,
            image: path.resolve(f),
            sha256: r.sha256,
            score: r.score,
            stars: stars(r.score),
            composition: r.composition,
            colour: r.colour,
            best: r.best,
            improvements: r.improvements,
            model,
            prompt_version: PROMPT_VERSION,
            prompt_sha: PROMPT_SHA,
            temperature: 0.2,
            context: args.context || null,
            batch: args.images.length > 1 ? args.images.map((x) => path.resolve(x)) : null,
          });
        }
      } catch (e) {
        failures.push({ file: f, sample: i + 1, error: String(e.message || e) });
        process.stderr.write(`rate.mjs: could not rate ${f} (sample ${i + 1}): ${e.message || e}\n`);
      }
    }
    if (samples.length) results.push(collapse(samples));
  }

  if (!results.length) die2('no image could be rated');

  // Deliberately NOT sorted by score. Sorting is ranking, and the calibration
  // run (measured 2026-08-09) shows that this rater cannot rank design work -
  // the two rounds a designer would actually ship scored LOWEST of the late
  // rounds. A table sorted by score invites exactly the misuse the evidence
  // forbids, so results print in the order the caller passed them. Do not add
  // a sort as a convenience; it is load-bearing that it is absent.

  if (args.json) {
    process.stdout.write(
      JSON.stringify(
        {
          model,
          temperature: 0.2,
          prompt_version: PROMPT_VERSION,
          prompt_sha: PROMPT_SHA,
          log: args.log ? LOG_PATH : null,
          ratings: results.map((r) => ({ ...r, stars: stars(r.score) })),
          failures,
        },
        null,
        2,
      ) + '\n',
    );
  } else {
    printTable(results, model, args.log ? LOG_PATH : null);
  }

  process.exit(failures.length ? 1 : 0);
}

main().catch((e) => {
  if (e && e.__rate_graphic_die) process.exit(2);
  process.stderr.write(`rate.mjs: ${e && e.stack ? e.stack : e}\n`);
  process.exit(2);
});
