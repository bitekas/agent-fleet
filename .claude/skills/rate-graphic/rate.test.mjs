#!/usr/bin/env node
/**
 * rate.test.mjs - regression guard for the rate-graphic harness.
 *
 * Run: node .claude/skills/rate-graphic/rate.test.mjs   (from the fleet root, or
 * from anywhere - every path below is resolved from this file's own location).
 * Exits 0 when every check passes, 1 on the first failure reported. Prints one
 * [PASS]/[FAIL] line per check.
 *
 * OFFLINE AND DETERMINISTIC BY CONSTRUCTION. It never makes a model call and
 * never touches the real ratings log. It reads no SPECIFIC file of its own: the
 * one install config it consults is resolved exactly as rate.mjs resolves one
 * (RATE_GRAPHIC_CONFIG, else `fleet where rate-graphic config.json`), so under
 * the fleet's test environment (FLEET_CONTEXT_ROOT at the fixture install) it
 * is the fixture's, and on an install it is that install's - the log a stray
 * case would really hit. When nothing resolves, the install-config checks say
 * SKIP and the log control has nothing to guard, and both say so. Two
 * properties keep the suite off the real log, and both are load-bearing:
 *
 *   (a) EVERY case runs with RATE_GRAPHIC_CONFIG pointed at a config this file
 *       wrote into a temp directory, and with GEMINI_API_KEY and GEMINI_API_BASE
 *       stripped from the child environment. Without the strip, a developer who
 *       happens to export a key would turn this suite into a billed run against
 *       a live model, and it would still print green.
 *   (b) The REAL configured log's size and mtime are fingerprinted before any
 *       case runs and compared afterwards. (Its path is resolved here with `~`
 *       expansion only, so an install whose log path is written with a
 *       variable is fingerprinted at the unexpanded path and this control
 *       cannot see it.) That is the control on property (a):
 *       if a case ever escapes the temp config, this is what notices. Do not
 *       remove it because it "never fails"; a check that cannot fail is the one
 *       that stops being true first.
 *
 *       It is armed in an `exit` handler, not merely as the last check, and that
 *       placement is load-bearing. A control that only runs when the suite runs
 *       to completion cannot report the case it exists for: an escaped write is
 *       most likely in exactly the run that also throws. This was not
 *       hypothetical - the first version of this file put the control last, a
 *       breakage was driven that made every case write to the real log, an
 *       unguarded read of a now-missing temp log aborted the suite before the
 *       control, and the real log was modified with nothing reported. The
 *       handler also fails the run if the suite did not reach its end, because
 *       "passed", "failed" and "never finished" are three outcomes and a harness
 *       that collapses them manufactures the comfortable one.
 *
 * WHY BLACK-BOX. rate.mjs loads its config and dispatches at module scope, so
 * importing it would run it. Behaviour is therefore exercised by spawning it,
 * which is also how it is actually used. Do not "simplify" this into an import.
 *
 * HOW A CASE AVOIDS THE MODEL. Every path that would reach the model is stopped
 * earlier on purpose: a config whose credential glob matches nothing exits 2 in
 * resolveKey() before any fetch. The two cases that DO resolve a key file point
 * at files containing `{}`, which the cloud SDK rejects locally as a malformed
 * key - so those cases assert only what rate.mjs printed BEFORE it shelled out,
 * and they hold identically on a machine with no cloud SDK at all, where the
 * spawn fails with ENOENT instead. Neither reaches a network call.
 *
 * WHAT IT COVERS, and why each part is here:
 *
 *   1. CONFIG LOADING and its failure modes. The whole point of the config split
 *      is that a missing value fails LOUDLY, naming itself. Two of the required
 *      values fail SILENTLY when guessed - a guessed log path writes the run's
 *      records where nobody looks, a guessed secret project reads a key from the
 *      wrong project - so the cases that matter are the failures, not the happy
 *      path.
 *   2. PATH RESOLUTION. Relative config paths resolve against THE CONFIG
 *      FILE'S DIRECTORY, never the caller's cwd and never the script's
 *      directory. Pinned by running the same config from two different working
 *      directories and asserting the same absolute path comes back. This
 *      convention is invisible until it breaks, and when it breaks it writes
 *      records to a second log nobody reads. Variable expansion is pinned here
 *      too, nested `${A:-${B:-/x}}` included: each level falls back only when
 *      its own variable is unset or empty.
 *   2b. CONFIG RESOLUTION. With RATE_GRAPHIC_CONFIG unset the config is the
 *      file `fleet where rate-graphic config.json` names, asked of a FAKE fleet
 *      this file writes and selects with FLEET_BIN; with it set, the fleet is
 *      not asked; a failing fleet is relayed with exit 2, never guessed past.
 *      The fake is run directly first, and a fake that cannot run is NO
 *      VERDICT for those cases rather than a defect charged to rate.mjs.
 *   3. THE LOG-WRITABILITY GATE'S ORDERING. Not that it exists - that it runs
 *      BEFORE key resolution and before any model call. Pinned by breaking BOTH
 *      the log path and the credential path in one config and asserting the LOG
 *      error is the one that comes back. If this ever goes red with the key
 *      error instead, the gate still exists and no longer protects anything:
 *      a typo would cost a full billed run and then throw on the append.
 *   4. THE CREDENTIAL GLOB's three branches - not found, exactly one, more than
 *      one. The multi-match branch matters because choosing among several key
 *      files is a decision, and the wrong one authenticates as the wrong
 *      principal against the right API.
 *   5. THE JSONL RECORD SHAPE, via --record-pick, the one record rate.mjs can
 *      write without a model call.
 *   6. THE PROMPT'S IDENTITY. PROMPT_SHA is sha256 over the prompt text and the
 *      log groups by it, so an accidental edit silently splits the corpus into
 *      two instruments. Pinned by value, together with the six em dashes inside
 *      the prompt that this tree's ASCII sweep must not touch.
 *   7. SKILL CONFORMANCE. SKILL.md is the COMMON half: it must name no
 *      install-specific value. Checked generically - no config VALUE may appear
 *      in it, no absolute path - so the check keeps working after the values
 *      change, and this test file stays common too.
 *
 * NEGATIVE CONTROLS. Every assertion here was proven to go red by breaking the
 * thing it measures on a scratchpad copy of the skill, then reverting. If you
 * add a check, break what it watches and confirm the failure NAMES it before you
 * trust the green. A check that has never failed is not evidence.
 */

import fs from 'fs';
import os from 'os';
import path from 'path';
import crypto from 'crypto';
import { spawnSync } from 'child_process';
import { fileURLToPath, pathToFileURL } from 'url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const RATE = path.join(HERE, 'rate.mjs');
const FIXTURES = path.join(HERE, 'fixtures');

const read = (p) => fs.readFileSync(p, 'utf8');
const readJson = (p) => JSON.parse(read(p));

const SRC = read(RATE);
const SKILL_MD = read(path.join(HERE, 'SKILL.md'));
const EXAMPLE = readJson(path.join(HERE, 'config.example.json'));
const BASE_CONFIG = read(path.join(FIXTURES, 'config.fixture.json'));

// A relative FLEET_CONTEXT_ROOT / FLEET_HOST_CONFIG means "relative to where
// the runner stood"; every child below runs in a temp cwd, so pin them now.
for (const k of ['FLEET_CONTEXT_ROOT', 'FLEET_HOST_CONFIG']) {
  if (process.env[k]) process.env[k] = path.resolve(process.env[k]);
}

// The install config, resolved by the lookup rate.mjs uses (see the header):
// RATE_GRAPHIC_CONFIG as given, else the fleet's answer when that file exists.
// null when nothing resolves; the checks that need it then SKIP, out loud.
const { configFile } = await import(pathToFileURL(path.join(fs.realpathSync(HERE), '..', '..', '..', 'lib', 'fleet-where.mjs')).href);
const REAL_CONFIG_FILE = (() => {
  let p;
  try { p = configFile('rate-graphic', 'RATE_GRAPHIC_CONFIG'); } catch { return null; }
  return (process.env.RATE_GRAPHIC_CONFIG || fs.existsSync(p)) ? p : null;
})();
const CONFIG = REAL_CONFIG_FILE ? readJson(REAL_CONFIG_FILE) : null;

const failures = [];
function check(name, cond, detail = '') {
  console.log(`[${cond ? 'PASS' : 'FAIL'}] ${name}${detail ? ` - ${detail}` : ''}`);
  if (!cond) failures.push(name);
}

// --- the control on property (b): what the REAL log looked like before we ran -
// Read FIRST, before any case can run. An absent log is a valid state (a fresh
// clone has none) and is recorded as such, so the assertion at the bottom is
// "unchanged", never "exists".
function realConfigPath(p) {
  const expanded = p === '~' ? os.homedir() : p.startsWith('~/') ? path.join(os.homedir(), p.slice(2)) : p;
  return path.resolve(path.dirname(REAL_CONFIG_FILE), expanded);
}
const REAL_LOG = CONFIG?.ratings_log?.path ? realConfigPath(CONFIG.ratings_log.path) : null;
console.log(REAL_LOG ? `real log under guard: ${REAL_LOG}`
  : 'real log under guard: NONE - no install config resolves here, so there is no real log to touch');
function logFingerprint() {
  if (!REAL_LOG) return 'no install config';
  try {
    const s = fs.statSync(REAL_LOG);
    return `size=${s.size} mtimeMs=${s.mtimeMs}`;
  } catch {
    return 'absent';
  }
}
const REAL_LOG_BEFORE = logFingerprint();

// --- scratch space -----------------------------------------------------------
// Every case gets its own directory under one temp tree, removed on exit.
// Nothing here touches the real log or a real credential.
// RESOLVED: rate.mjs makes a relative path absolute against process.cwd(), which the
// kernel reports canonically, so every path this file expects back is the realpath.
// On macOS the two differ: TMPDIR is under /var/folders, a link to /private/var/folders.
const TMP = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'rate-graphic-test-')));

// Set by the last line of the file. Its absence means the suite ABORTED, which
// is a distinct outcome from passing and from failing, and must not be reported
// as either.
let COMPLETED = false;

process.on('exit', () => {
  try { fs.rmSync(TMP, { recursive: true, force: true }); } catch { /* best effort */ }
  // The safety control, armed here so it runs even when the suite throws. See
  // property (b) in the header for why that placement is not decoration.
  const after = logFingerprint();
  const escaped = after !== REAL_LOG_BEFORE;
  if (escaped) {
    console.log(`[FAIL] the REAL ratings log was TOUCHED by this suite - ${REAL_LOG}: ` +
      `before ${REAL_LOG_BEFORE}, after ${after}`);
  }
  if (!COMPLETED) {
    console.log('[FAIL] the suite ABORTED before its last line - no verdict is issued ' +
      'for anything it did not reach');
  }
  if (escaped || !COMPLETED) {
    console.log('\nINCONCLUSIVE OR UNSAFE - see the [FAIL] lines above.');
    // Calling process.exit inside an exit handler is what actually overrides the
    // status; assigning process.exitCode here does not.
    process.exit(1);
  }
});

let caseN = 0;
/**
 * Write a config variant into its own directory. `mutate` receives the parsed
 * fixture and may edit it. By default the log directory exists and the
 * credential glob matches nothing, which is the shape that reaches the furthest
 * into rate.mjs without ever reaching the model.
 */
function makeConfig(mutate = null) {
  const dir = path.join(TMP, `case-${++caseN}`);
  fs.mkdirSync(path.join(dir, 'log'), { recursive: true });
  const cfg = JSON.parse(BASE_CONFIG);
  cfg.ratings_log.path = path.join(dir, 'log', 'ratings.jsonl');
  cfg.credentials.service_account_key_path = path.join(dir, 'no-keys-here', '*.json');
  if (mutate) mutate(cfg, dir);
  const file = path.join(dir, 'config.json');
  fs.writeFileSync(file, JSON.stringify(cfg, null, 2));
  return { file, dir, log: cfg.ratings_log.path };
}

/**
 * Run rate.mjs. The ambient environment is scrubbed of everything that could
 * make this suite reach a live model or a different config - see property (a).
 */
function run(argv, { configFile = null, cwd = TMP, env = {} } = {}) {
  const childEnv = { ...process.env };
  delete childEnv.GEMINI_API_KEY;
  delete childEnv.GEMINI_API_BASE;
  delete childEnv.RATE_GRAPHIC_CONFIG;
  if (configFile) childEnv.RATE_GRAPHIC_CONFIG = configFile;
  Object.assign(childEnv, env);
  const r = spawnSync(process.execPath, [RATE, ...argv], {
    encoding: 'utf8', env: childEnv, cwd, timeout: 60000,
  });
  return { status: r.status, stdout: r.stdout || '', stderr: r.stderr || '' };
}

/** A file rate.mjs will accept as "exists" without ever reading it as an image. */
function touchImage(dir, name) {
  const p = path.join(dir, name);
  fs.writeFileSync(p, '');
  return p;
}

// ===========================================================================
// 1. Config loading and its failure modes
// ===========================================================================
{
  const ok = makeConfig();
  const r = run(['--help'], { configFile: ok.file });
  check('valid config: --help prints the usage block',
    /Usage:/.test(r.stderr) && r.stderr.includes('--record-pick'), `status=${r.status}`);
  // An explicit --help is a question that was answered, so it exits 0. Its twin
  // lives in section 6, where every usage ERROR is asserted to keep exit 2: the
  // pair is the whole check, because "--help exits 0" alone is also satisfied by
  // a usage() that exits 0 for everything, which would report a rejected
  // invocation as a successful run.
  check('valid config: an explicit --help exits 0',
    r.status === 0, `status=${r.status}`);
  check('--help names the sampling default, which is part of the instrument',
    /default 3\b/.test(r.stderr), 'DEFAULT_REPEAT reached the usage text');
}

// A missing REQUIRED key must name the key. All four are required for the same
// reason: guessing any of them fails badly, and two of them fail SILENTLY.
for (const key of ['ratings_log.path', 'credentials.service_account_key_path',
  'secret.name', 'secret.project']) {
  const [group, leaf] = key.split('.');
  const bad = makeConfig((c) => { delete c[group][leaf]; });
  const r = run(['--help'], { configFile: bad.file });
  check(`missing required key '${key}' is refused with exit 2`, r.status === 2, `status=${r.status}`);
  check(`missing required key '${key}' NAMES the key`,
    r.stderr.includes(`missing required key '${key}'`), r.stderr.split('\n')[0]);
}

// The optional key falls back to a default rather than failing. It is the ONLY
// optional key: the public endpoint is the same for every install.
{
  const noApi = makeConfig((c) => { delete c.api; });
  const r = run(['--help'], { configFile: noApi.file });
  check('api.base is optional (its absence is not a startup failure)',
    !/missing required key/.test(r.stderr), r.stderr.split('\n')[0]);
}

// DECISION PINNED: unknown keys are IGNORED, not rejected. A config written for
// a newer version of the skill must still load under an older script, and the
// _comment keys the config files document themselves with are unknown keys too.
{
  const extra = makeConfig((c) => { c.wildcard = { nope: 1 }; c.secret.future_key = 'x'; });
  const r = run(['--help'], { configFile: extra.file });
  check('unknown keys are ignored, not rejected',
    !/missing required key/.test(r.stderr) && /Usage:/.test(r.stderr), r.stderr.split('\n')[0]);
}

// A broken config file is a startup failure that says so and names the file.
{
  const dir = path.join(TMP, 'broken'); fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, 'config.json');
  fs.writeFileSync(file, '{ "ratings_log": { "path": ');
  const r = run(['--help'], { configFile: file });
  check('malformed JSON config is refused, naming the file',
    r.status === 2 && /is not valid JSON/.test(r.stderr) && r.stderr.includes(file),
    r.stderr.split('\n')[0]);
}
{
  const missing = path.join(TMP, 'does-not-exist.json');
  const r = run(['--help'], { configFile: missing });
  check('absent config file is refused, naming the path and the remedy',
    r.status === 2 && r.stderr.includes(missing) && /config\.example\.json/.test(r.stderr),
    r.stderr.split('\n')[0]);
}

// ===========================================================================
// 2. Path resolution: the CONFIG FILE'S DIRECTORY, never the caller's cwd
// ===========================================================================
// This is the convention that makes one config mean one file no matter where
// the tool is invoked from. It is invisible until it breaks, and the way it
// breaks is a second ratings log nobody reads. Proven by running the SAME
// config from two different working directories and demanding the same answer.
{
  const rel = makeConfig((c) => { c.ratings_log.path = 'no-such-relative-dir/ratings.jsonl'; });
  const expected = path.join(path.dirname(rel.file), 'no-such-relative-dir');
  const a = run(['x.png'], { configFile: rel.file, cwd: TMP });
  const b = run(['x.png'], { configFile: rel.file, cwd: path.parse(TMP).root });
  check('a relative ratings_log.path resolves against the config file\'s directory',
    a.stderr.includes(expected), a.stderr.split('\n')[0]);
  check('the same relative path resolves identically from a different cwd',
    a.stderr === b.stderr && b.stderr.includes(expected), 'cwd does not move the target');
  check('the error names the config key, the config file and the resolved path',
    /'ratings_log\.path'/.test(a.stderr) && a.stderr.includes(rel.file) && a.stderr.includes(expected),
    'a path failure has to be diagnosable without reading the source');
}
{
  const home = makeConfig((c) => { c.ratings_log.path = `~/no-such-home-dir-${process.pid}/r.jsonl`; });
  const r = run(['x.png'], { configFile: home.file });
  check('a leading ~/ in a config path expands against the home directory',
    r.stderr.includes(path.join(os.homedir(), `no-such-home-dir-${process.pid}`)),
    r.stderr.split('\n')[0]);
}

// VARIABLE EXPANSION. A credential store lives outside every checkout, so a
// config path has to be able to name a location that is neither repo-relative
// nor a machine-specific literal. NOTHING expands one for us: JSON is a data
// format and Node expands neither `$VAR` nor `${VAR:-default}`, so without
// expandVars() the value below reaches globSync() as an eleven-character
// directory name that happens to look like a variable.
//
// The LAST case is the negative control and it is the load-bearing one. Delete
// it and the three above still pass while an unset variable could be collapsed
// to '' - which points the glob at a DIFFERENT, possibly existing key file, and
// a run that authenticates with the wrong key succeeds against the right API.
// Nothing else in this suite can see that happen.
{
  const v = makeConfig((c) => {
    c.ratings_log.path = `\${TEST_STORE:-~/no-such-defaulted-${process.pid}}/r.jsonl`;
  });
  const r = run(['x.png'], { configFile: v.file });
  check('${VAR:-default} falls back when VAR is unset',
    r.stderr.includes(path.join(os.homedir(), `no-such-defaulted-${process.pid}`)),
    r.stderr.split('\n')[0]);
  const r2 = run(['x.png'], { configFile: v.file,
    env: { TEST_STORE: path.join(TMP, `set-${process.pid}`) } });
  check('${VAR:-default} takes VAR when it is set',
    r2.stderr.includes(path.join(TMP, `set-${process.pid}`)), r2.stderr.split('\n')[0]);
  // Shell `:-` semantics: an EMPTY variable is unset. `??` here would hand the
  // caller a path rooted at '/'.
  const r3 = run(['x.png'], { configFile: v.file, env: { TEST_STORE: '' } });
  check('an EMPTY VAR takes the default too (shell :- semantics)',
    r3.stderr.includes(path.join(os.homedir(), `no-such-defaulted-${process.pid}`)),
    r3.stderr.split('\n')[0]);
}
{
  const bare = makeConfig((c) => {
    c.ratings_log.path = '$TEST_NEVER_SET_VAR/r.jsonl';
  });
  const r = run(['x.png'], { configFile: bare.file });
  check('NEGATIVE CONTROL: an unset $VAR with no default stays literal, naming itself',
    r.stderr.includes('$TEST_NEVER_SET_VAR'), r.stderr.split('\n')[0]);
}
// NESTED DEFAULTS, ${A:-${B:-/x}}: the shape a secrets path takes when it
// honours a fleet-wide variable, then an install's own, then a home default.
// Three cases, one per level, because each level is a separate fallback and a
// one-pass expander gets exactly one of them wrong: it leaves the inner
// default unexpanded inside the outer one. Each expected path is unique to its
// level, so no case can pass on another level's answer.
{
  const deepest = path.join(TMP, `nested-default-${process.pid}`);
  const v = makeConfig((c) => {
    c.ratings_log.path = `\${TEST_NEST_A:-\${TEST_NEST_B:-${deepest}}}/r.jsonl`;
  });
  const env0 = { TEST_NEST_A: '', TEST_NEST_B: '' };
  const r = run(['x.png'], { configFile: v.file, env: env0 });
  check('${A:-${B:-/x}} with A and B unset takes the innermost default',
    r.stderr.includes(`directory does not exist: ${deepest}`), r.stderr.split('\n')[0]);
  const fromB = path.join(TMP, `nested-b-${process.pid}`);
  const r2 = run(['x.png'], { configFile: v.file, env: { ...env0, TEST_NEST_B: fromB } });
  check('${A:-${B:-/x}} with only B set takes B',
    r2.stderr.includes(`directory does not exist: ${fromB}`), r2.stderr.split('\n')[0]);
  const fromA = path.join(TMP, `nested-a-${process.pid}`);
  const r3 = run(['x.png'], { configFile: v.file, env: { TEST_NEST_A: fromA, TEST_NEST_B: fromB } });
  check('${A:-${B:-/x}} with A set takes A, whatever B is',
    r3.stderr.includes(`directory does not exist: ${fromA}`), r3.stderr.split('\n')[0]);
}

// ===========================================================================
// 2b. Config resolution: RATE_GRAPHIC_CONFIG, else `fleet where`
// ===========================================================================
// The fake fleet appends its arguments to FAKE_FLEET_LOG, prints FAKE_FLEET_ERR
// on stderr when set, exits FAKE_FLEET_EXIT when non-zero, and otherwise
// prints FAKE_FLEET_OUT. Each case below runs rate.mjs with NO
// RATE_GRAPHIC_CONFIG unless it says otherwise.
{
  const FAKE = path.join(TMP, 'fake-fleet');
  fs.writeFileSync(FAKE, [
    '#!/bin/sh',
    'printf \'%s\\n\' "$*" >> "$FAKE_FLEET_LOG"',
    '[ -n "$FAKE_FLEET_ERR" ] && printf \'%s\\n\' "$FAKE_FLEET_ERR" >&2',
    '[ "${FAKE_FLEET_EXIT:-0}" != 0 ] && exit "$FAKE_FLEET_EXIT"',
    'printf \'%s\\n\' "$FAKE_FLEET_OUT"',
    '',
  ].join('\n'));
  fs.chmodSync(FAKE, 0o755);
  let n = 0;
  const viaFleet = (argv, { out = '', exit = 0, err = '', configFile = null } = {}) => {
    const log = path.join(TMP, `fleet-calls-${++n}.log`);
    const r = run(argv, { configFile, env: {
      FLEET_BIN: FAKE, FAKE_FLEET_LOG: log, FAKE_FLEET_OUT: out, FAKE_FLEET_EXIT: String(exit), FAKE_FLEET_ERR: err,
    } });
    return { ...r, calls: fs.existsSync(log) ? read(log).trim().split('\n').filter(Boolean) : [] };
  };
  const self = spawnSync(FAKE, ['where', 'self-check'], { encoding: 'utf8', env: {
    ...process.env, FAKE_FLEET_LOG: path.join(TMP, 'fleet-self.log'), FAKE_FLEET_OUT: '/fake/out', FAKE_FLEET_EXIT: '0', FAKE_FLEET_ERR: '' } });
  const fakeRuns = !self.error && self.status === 0 && String(self.stdout).trim() === '/fake/out';
  if (!fakeRuns) {
    console.log(`[NO VERDICT] the fake fleet does not run here (${self.error?.code || `exit ${self.status}`}); ` +
      'section 2b measured nothing and issues no verdict about rate.mjs');
    failures.push('section 2b: NO VERDICT, the fake fleet does not run');
  } else {
    // The named config lacks secret.project, so the refusal names the file read.
    const named = makeConfig((c) => { delete c.secret.project; });
    const r = viaFleet(['--help'], { out: named.file });
    check('no RATE_GRAPHIC_CONFIG: rate.mjs asks the fleet once, for this skill\'s config.json',
      r.calls.length === 1 && r.calls[0] === 'where rate-graphic config.json', JSON.stringify(r.calls));
    check('...and reads the file the fleet named (refusing it names that file and the key)',
      r.status === 2 && r.stderr.includes(named.file) && r.stderr.includes("'secret.project'"), r.stderr.split('\n')[0]);

    const ok = makeConfig();
    const r2 = viaFleet(['--help'], { out: named.file, configFile: ok.file });
    check('RATE_GRAPHIC_CONFIG set: the fleet is not asked', r2.calls.length === 0, JSON.stringify(r2.calls));
    check('RATE_GRAPHIC_CONFIG set: its file is the one read', r2.status === 0 && /Usage:/.test(r2.stderr), r2.stderr.split('\n')[0]);

    const r3 = viaFleet(['--help'], { exit: 3, err: 'fleet: FAKE-NOT-INSTALLED-LINE' });
    check('a failing fleet: asked once (positive evidence the path was reached)', r3.calls.length === 1, JSON.stringify(r3.calls));
    check('a failing fleet is exit 2, relaying its line and naming the bypass',
      r3.status === 2 && r3.stderr.includes('FAKE-NOT-INSTALLED-LINE') && r3.stderr.includes('RATE_GRAPHIC_CONFIG'),
      r3.stderr.split('\n')[0]);
    const r4 = viaFleet(['--help'], { out: '' });
    check('a fleet that prints no path is exit 2, not read as the cwd',
      r4.status === 2 && /printed no path/.test(r4.stderr), r4.stderr.split('\n')[0]);
  }
}

// ===========================================================================
// 3. The log-writability gate runs BEFORE key resolution and before any spend
// ===========================================================================
// The ORDERING is the property, not the existence of the check. Both the log
// path and the credential path are broken in one config; the log error is the
// one that must come back. If key resolution ever moves ahead of this gate, the
// gate still runs, nothing goes red anywhere else, and a typo in the log path
// silently costs a full run of model calls before throwing on the append.
{
  const both = makeConfig((c, dir) => {
    c.ratings_log.path = path.join(dir, 'no-such-log-dir', 'ratings.jsonl');
  });
  const img = touchImage(both.dir, 'a.png');
  const r = run([img], { configFile: both.file });
  check('with BOTH the log dir and the key glob broken, the LOG failure is reported',
    r.status === 2 && /the ratings log's directory does not exist/.test(r.stderr),
    r.stderr.split('\n')[0]);
  check('...and the key-resolution failure is NOT reached',
    !/no service-account key matched/.test(r.stderr),
    'the gate is ahead of key resolution, which is what makes it free');
  check('the log gate says in words that nothing was billed',
    /costs no API spend/.test(r.stderr), 'the reassurance is the actionable half');
}
// The gate refuses to CREATE the directory. A mistyped path that silently
// mkdir -p's itself produces a second log nobody reads, which is worse than a
// missing one: the first is invisible, the second is loud.
{
  const both = makeConfig((c, dir) => {
    c.ratings_log.path = path.join(dir, 'no-such-log-dir', 'ratings.jsonl');
  });
  const img = touchImage(both.dir, 'a.png');
  run([img], { configFile: both.file });
  check('the log gate does NOT create the missing directory',
    !fs.existsSync(path.join(both.dir, 'no-such-log-dir')),
    'making a new log location stays a human decision');
}
// --no-log skips the gate entirely, because nothing will be written.
{
  const both = makeConfig((c, dir) => {
    c.ratings_log.path = path.join(dir, 'no-such-log-dir', 'ratings.jsonl');
  });
  const img = touchImage(both.dir, 'a.png');
  const r = run([img, '--no-log'], { configFile: both.file });
  check('--no-log skips the log gate (a broken log path is not consulted)',
    !/the ratings log's directory does not exist/.test(r.stderr), r.stderr.split('\n')[0]);
  check('--no-log then fails at key resolution instead, still before any model call',
    r.status === 2 && /no service-account key matched/.test(r.stderr), r.stderr.split('\n')[0]);
}

// ===========================================================================
// 4. The credential glob: not found, exactly one, more than one
// ===========================================================================
{
  const c = makeConfig();
  const img = touchImage(c.dir, 'a.png');
  const r = run([img], { configFile: c.file });
  check('glob NOT FOUND: exit 2', r.status === 2, `status=${r.status}`);
  check('glob NOT FOUND: names the pattern it globbed',
    r.stderr.includes(path.join(c.dir, 'no-keys-here')), r.stderr.split('\n')[0]);
  check('glob NOT FOUND: names the config key it came from',
    /'credentials\.service_account_key_path'/.test(r.stderr));
  check('glob NOT FOUND: names the directory it resolved against',
    r.stderr.includes(`resolved against the config file's directory ${c.dir}`),
    'a glob failure must be diagnosable without the source');
  check('glob NOT FOUND: offers the environment short-circuit as a way out',
    /GEMINI_API_KEY/.test(r.stderr));
}
// One match and several matches. Both of these DO resolve a key file, so both
// go on to shell out to the cloud SDK - which cannot succeed, because the files
// contain `{}` and are rejected as malformed before any network call, and which
// need not even exist, because a missing SDK fails the same spawn. So both
// cases assert only what rate.mjs itself printed BEFORE shelling out.
{
  const one = makeConfig((c, dir) => {
    fs.mkdirSync(path.join(dir, 'keys'));
    fs.writeFileSync(path.join(dir, 'keys', 'sa-only.json'), '{}');
    c.credentials.service_account_key_path = path.join(dir, 'keys', 'sa-*.json');
  });
  const img = touchImage(one.dir, 'a.png');
  const r = run([img], { configFile: one.file });
  check('glob ONE MATCH: the not-found branch is not taken',
    !/no service-account key matched/.test(r.stderr), r.stderr.split('\n')[0]);
  check('glob ONE MATCH: no ambiguity warning is printed',
    !/files matched/.test(r.stderr), 'a single match is not a decision');
}
{
  const many = makeConfig((c, dir) => {
    fs.mkdirSync(path.join(dir, 'keys'));
    fs.writeFileSync(path.join(dir, 'keys', 'sa-a.json'), '{}');
    fs.writeFileSync(path.join(dir, 'keys', 'sa-b.json'), '{}');
    c.credentials.service_account_key_path = path.join(dir, 'keys', 'sa-*.json');
  });
  const img = touchImage(many.dir, 'a.png');
  const r = run([img], { configFile: many.file });
  check('glob MULTI-MATCH: warns, naming the count',
    /2 files matched/.test(r.stderr), r.stderr.split('\n')[0]);
  check('glob MULTI-MATCH: names the file it chose, and it is the sorted first',
    r.stderr.includes(`using ${path.join(many.dir, 'keys', 'sa-a.json')}`),
    'silence here would authenticate as the wrong principal against the right API');
}

// ===========================================================================
// 5. The JSONL record shape (--record-pick is the one record with no model call)
// ===========================================================================
{
  const c = makeConfig();
  const picked = touchImage(c.dir, 'b.png');
  const overA = touchImage(c.dir, 'a.png');
  const overC = touchImage(c.dir, 'c.png');
  const r = run(['--record-pick', 'b.png', '--over', 'a.png,c.png', '--why', 'b reads at thumbnail size'],
    { configFile: c.file, cwd: c.dir });
  check('--record-pick exits 0', r.status === 0, `status=${r.status} ${r.stderr.trim()}`);
  check('--record-pick names the log it appended to',
    r.stdout.includes(c.log), 'a reader who cannot see the path cannot tell a logged run from a --no-log one');

  // Read defensively: if the record did not land HERE it landed somewhere else,
  // and that is a finding to report, not an exception to die on.
  const lines = fs.existsSync(c.log)
    ? read(c.log).trim().split('\n').filter(Boolean) : [];
  check('--record-pick appends to the CONFIGURED log', fs.existsSync(c.log), c.log);
  check('--record-pick appends exactly one line', lines.length === 1, `${lines.length} line(s)`);
  let rec = null;
  try { rec = JSON.parse(lines[0]); } catch { /* rec stays null */ }
  check('the appended line is valid JSON', rec !== null, lines[0]?.slice(0, 80));
  if (rec) {
    check('record kind is human_pick', rec.kind === 'human_pick', JSON.stringify(rec.kind));
    check('record ts is an ISO 8601 instant',
      typeof rec.ts === 'string' && !Number.isNaN(Date.parse(rec.ts)), rec.ts);
    check('picked is an ABSOLUTE path, not the relative one passed in',
      rec.picked === picked, rec.picked);
    check('over is an array of absolute paths, in the order given',
      Array.isArray(rec.over) && rec.over.length === 2 &&
      rec.over[0] === overA && rec.over[1] === overC, JSON.stringify(rec.over));
    check('why is carried verbatim', rec.why === 'b reads at thumbnail size', rec.why);
    check('a human_pick record carries no score, model or prompt fields',
      !('score' in rec) && !('model' in rec) && !('prompt_sha' in rec),
      'it is the human half of the pair; a model field here would be a fabrication');
  }
}
{
  const c = makeConfig();
  touchImage(c.dir, 'b.png');
  const r = run(['--record-pick', 'b.png'], { configFile: c.file, cwd: c.dir });
  check('--record-pick without --over is refused, naming what is missing',
    r.status === 2 && /--record-pick needs --over/.test(r.stderr), r.stderr.split('\n')[0]);
  check('--record-pick without --over writes nothing',
    !fs.existsSync(c.log) || read(c.log) === '', 'a refused command must not half-log');
}
{
  // --no-log suppresses the human-pick write exactly as it suppresses a rating
  // write. One flag, one meaning. The record type makes it matter more here than
  // anywhere else: a human_pick is the human's verdict, the datum every score in
  // the corpus is calibrated against, and one written by a throwaway probe is
  // indistinguishable from one a person meant.
  //
  // The check has two halves and needs both. The write assertion alone is
  // satisfied by a script that refuses the combination outright, and the exit-0
  // assertion alone is satisfied by the bug this replaced. The block above it -
  // the same command WITHOUT --no-log - is the regime control: without it, a
  // recordPick() that had stopped writing under every condition would read here
  // as a working --no-log.
  const c = makeConfig();
  touchImage(c.dir, 'b.png'); touchImage(c.dir, 'a.png');
  const r = run(['--record-pick', 'b.png', '--over', 'a.png', '--no-log'],
    { configFile: c.file, cwd: c.dir });
  const lines = fs.existsSync(c.log) ? read(c.log).trim().split('\n').filter(Boolean) : [];
  check('--record-pick --no-log is accepted, not refused', r.status === 0,
    `status=${r.status} ${r.stderr.trim()}`);
  check('--record-pick --no-log writes NO record', lines.length === 0,
    `${lines.length} line(s) in ${c.log}`);
  check('--record-pick --no-log SAYS that nothing was recorded',
    /--no-log: the human pick .* was NOT recorded/.test(r.stdout) && !r.stdout.includes(c.log),
    'silence, or a path printed beside no write, is how a lost pick goes unnoticed');
}
{
  // The other half of the same gate, and the half every other case is blind to:
  // main() runs requireWritableLog() only when args.log, so a --no-log run must
  // not be refused for a log directory it is never going to touch. Every case
  // above runs with a log directory makeConfig() created, which makes the gate a
  // no-op there - reverting main()'s gate to `args.pick || args.log` leaves the
  // whole suite green without this block. A missing directory is the only shape
  // that separates the two.
  const c = makeConfig((cfg, dir) => {
    cfg.ratings_log.path = path.join(dir, 'no-such-dir', 'ratings.jsonl');
  });
  touchImage(c.dir, 'b.png'); touchImage(c.dir, 'a.png');
  const r = run(['--record-pick', 'b.png', '--over', 'a.png', '--no-log'],
    { configFile: c.file, cwd: c.dir });
  check('--record-pick --no-log is not gated on a log directory it never writes to',
    r.status === 0 && !/does not exist/.test(r.stderr),
    `status=${r.status} ${r.stderr.split('\n')[0]}`);
  check('--record-pick --no-log with a missing log dir still creates nothing',
    !fs.existsSync(path.dirname(c.log)), path.dirname(c.log));
}

// ===========================================================================
// 6. Usage and the exit-code contract
// ===========================================================================
// Exit 2 is deliberately distinct from 1: "the graphic scored badly" and "we
// never asked anything" must never print as the same outcome, because a caller
// that cannot tell them apart will read the comfortable one. Every case below
// is a never-asked-anything case, so every one of them is a 2. The twin of this
// block is in section 1: an explicit --help exits 0, and only a REJECTION
// carries a message. Neither half is a check on its own.
{
  const c = makeConfig();
  const cases = [
    [[], 'give at least one image path', 'no arguments'],
    [['--frobnicate'], 'unknown flag --frobnicate', 'an unknown flag, named back'],
    [['x.png', '--repeat', '0'], '--repeat needs a positive integer', 'zero samples'],
    [['x.png', '--repeat', 'abc'], '--repeat needs a positive integer', 'a non-numeric repeat'],
    [['x.png', '--repeat', '1.5'], '--repeat needs a positive integer', 'a fractional repeat'],
    [['x.png', '--context'], '--context needs a value', 'a flag with its value missing'],
    [['x.png', '--model'], '--model needs a value', 'another flag with its value missing'],
  ];
  for (const [argv, expect, why] of cases) {
    const r = run(argv, { configFile: c.file });
    check(`usage: ${JSON.stringify(argv)} is refused with exit 2 (${why})`,
      r.status === 2 && r.stderr.includes(expect), `${r.status}: ${r.stderr.split('\n')[0]}`);
  }
}
{
  const c = makeConfig();
  const r = run([path.join(c.dir, 'not-a-real-image.png')], { configFile: c.file });
  check('a nonexistent image is refused BEFORE key resolution, naming the file',
    r.status === 2 && /no such file: /.test(r.stderr) &&
    !/no service-account key matched/.test(r.stderr), r.stderr.split('\n')[0]);
}

// ===========================================================================
// 7. The prompt's identity
// ===========================================================================
// PROMPT_SHA is sha256 over the prompt text, every log record carries it, and
// analysis groups by it. An accidental edit - a punctuation sweep is the likely
// one - changes the sha without changing PROMPT_VERSION, and silently splits the
// accumulated corpus into two instruments that look like one. This pins both
// halves by value.
{
  const OPEN = 'const PROMPT = (context) => `';
  const at = SRC.indexOf(OPEN);
  check('the prompt template can be located in the source', at >= 0);
  if (at >= 0) {
    const start = at + OPEN.length;
    const end = SRC.indexOf('`;\n', start);
    const template = SRC.slice(start, end);
    // Positive evidence that the extraction reached the real prompt. Without
    // this, a failed extraction would hash an empty string and the sha check
    // below would report on nothing at all while looking like it ran.
    check('the extracted text really is the prompt (length and named steps)',
      template.length > 2000 && template.includes('STEP 1') &&
      template.includes('STEP 2') && template.includes('STEP 3'),
      `${template.length} chars`);

    // PROMPT(null): the context interpolation collapses to the empty string.
    const promptNull = template.replace(
      '${context ? `\\nWhat the graphic is for: ${context}\\n` : \'\'}', '');
    check('the context interpolation was substituted out',
      !promptNull.includes('${context'), 'otherwise the sha is of the wrong text');
    const sha = crypto.createHash('sha256').update(promptNull).digest('hex').slice(0, 12);

    // The pinned pair. If you MEANT to change the prompt, bump PROMPT_VERSION
    // and update both values here in the same edit - and know that every record
    // already in the log belongs to the old instrument and must not be pooled
    // with the new one.
    check('PROMPT_VERSION is still v3', /const PROMPT_VERSION = 'v3';/.test(SRC));
    check('PROMPT_SHA is still d71a370dd1df (the identity the log groups by)',
      sha === 'd71a370dd1df', `computed ${sha}`);

    // The ASCII-sweep exemption, pinned by count. The house rule normalises
    // em dashes to hyphens everywhere; inside this template that rule would
    // change the sha. Naming the character by escape keeps THIS file pure
    // ASCII, so a sweep over the tree cannot quietly rewrite the guard into
    // one that forbids nothing and still reports green.
    const emDashes = (template.match(/\u2014/g) || []).length;
    check('the 6 em dashes inside PROMPT are still byte-exact (sweep exemption)',
      emDashes === 6, `found ${emDashes}; see the note above PROMPT_VERSION in rate.mjs`);
  }
}
// The absence of a sort is load-bearing: sorting is ranking, and the calibration
// established that this rater cannot rank. A source guard, and its limits are
// worth stating - it sees a sort spelled these ways and no other, so it is a
// tripwire against the obvious "restore the convenience", not a proof.
{
  const sorts = (SRC.match(/results[\s\S]{0,20}\.sort\(/g) || []);
  check('results are not sorted before printing (sorting is ranking)',
    sorts.length === 0, sorts.join(' | '));
}

// ===========================================================================
// 8. Skill conformance: SKILL.md is the COMMON half
// ===========================================================================
{
  const dotted = (obj, prefix = '') => Object.entries(obj)
    .filter(([k]) => !k.startsWith('_'))
    .flatMap(([k, v]) => (v && typeof v === 'object' && !Array.isArray(v))
      ? dotted(v, `${prefix}${k}.`) : [`${prefix}${k}`]);
  const leaves = (obj) => Object.entries(obj)
    .filter(([k]) => !k.startsWith('_'))
    .flatMap(([, v]) => (v && typeof v === 'object' && !Array.isArray(v)) ? leaves(v) : [v]);

  // Every key the example declares is documented in SKILL.md. The example is
  // the COMMON statement of the keys, so this holds with no install present.
  for (const k of dotted(EXAMPLE)) {
    check(`SKILL.md names the config key ${k}`, SKILL_MD.includes(`\`${k}\``),
      'a key nothing documents is a key nobody fills in');
  }

  // The install's config against the mechanism. Only where one resolves (see
  // the header); otherwise one SKIP line says these were not run.
  if (!CONFIG) {
    console.log('[SKIP] no install config resolves here: the install config checks did not run');
  } else {
    const keys = dotted(CONFIG);
    check('the install config and config.example.json declare the same keys',
      JSON.stringify(keys.sort()) === JSON.stringify(dotted(EXAMPLE).sort()),
      `config=${keys.sort().join(',')} example=${dotted(EXAMPLE).sort().join(',')}`);
    // The values themselves must appear NOWHERE in SKILL.md - that is the whole
    // mechanism/values split, and it is what lets an adopter fill in config.json
    // and CONTEXT.md without editing SKILL.md.
    for (const v of leaves(CONFIG)) {
      if (typeof v !== 'string' || v.length < 3) continue;
      check(`SKILL.md does not contain the install value ${JSON.stringify(v)}`, !SKILL_MD.includes(v));
    }
  }
  check('SKILL.md names no absolute path', !/(^|[\s(`])\/(home|Users|opt|srv)\//.test(SKILL_MD));
  check('SKILL.md names no agent charter path', !SKILL_MD.includes('.claude/agents/'));

  // The ASCII sweep, pinned. The characters being BANNED are written as \u
  // escapes so this file stays pure ASCII: a guard that must contain the very
  // bytes it forbids is a guard the next sweep over this tree can silently
  // rewrite, after which it forbids nothing and still reports green.
  // Emoji, box drawing, arrows and the one-half sign are deliberately NOT in
  // this list, because it is applied to rate.mjs too, where they carry
  // meaning: the one-half in particular is what stars() PRINTS and what every
  // record in the log holds. SKILL.md is held to plain ASCII throughout by the
  // fleet's ASCII gate; this list is the part of that rule rate.mjs shares.
  const SWEPT = { '\u2014': 'em dash', '\u2013': 'en dash', '\u2026': 'ellipsis',
    '\u201c': 'left curly quote', '\u201d': 'right curly quote',
    '\u2018': 'left curly apostrophe', '\u2019': 'right curly apostrophe',
    '\u00a0': 'non-breaking space' };
  for (const [file, text] of [['SKILL.md', SKILL_MD]]) {
    for (const [ch, name] of Object.entries(SWEPT)) {
      check(`${file} contains no ${name}`, !text.includes(ch),
        text.includes(ch) ? `line ${text.slice(0, text.indexOf(ch)).split('\n').length}` : '');
    }
  }
  // rate.mjs, outside the exempt prompt template, obeys the same rule.
  {
    const at = SRC.indexOf('const PROMPT = (context) => `');
    const outside = at < 0 ? SRC : SRC.slice(0, at) + SRC.slice(SRC.indexOf('`;\n', at) + 3);
    for (const [ch, name] of Object.entries(SWEPT)) {
      check(`rate.mjs outside PROMPT contains no ${name}`, !outside.includes(ch));
    }
    check('rate.mjs still keeps the one-half it prints for a half star',
      SRC.includes('\u00bd'), 'stars() writes it and every rating record holds it');
  }

  // Frontmatter: the four keys the layout requires, in the order it requires.
  const fm = SKILL_MD.match(/^---\n([\s\S]*?)\n---\n/);
  check('SKILL.md has frontmatter', !!fm);
  if (fm) {
    const topLevel = fm[1].split('\n').filter((l) => /^[a-z_]+:/.test(l)).map((l) => l.split(':')[0]);
    check('frontmatter is name, version, description, requires_install in that order',
      JSON.stringify(topLevel) === JSON.stringify(['name', 'version', 'description', 'requires_install']),
      topLevel.join(','));
    check('frontmatter version is an integer', /^version: \d+$/m.test(fm[1]));
    check('frontmatter declares requires_install: true', /^requires_install: true$/m.test(fm[1]));
    // The description is a folded block scalar. A description containing a
    // colon as a plain scalar parses as a nested mapping and the skill silently
    // does not load - the one part of a skill that can break with nothing
    // printing an error.
    check('description is a folded block scalar, not a plain one',
      /^description: >\s*$/m.test(fm[1]), 'the only form that survives a punctuation edit unexamined');
  }

  // requires_install: true is a promise about files on disk.
  check('installation/INSTRUCTION.md exists (requires_install: true promises it)',
    fs.existsSync(path.join(HERE, 'installation', 'INSTRUCTION.md')));
  check('installation/check exists and is executable',
    fs.existsSync(path.join(HERE, 'installation', 'check')) &&
    !!(fs.statSync(path.join(HERE, 'installation', 'check')).mode & 0o111));

  // The example twin: the schema documentation for a log that lives elsewhere.
  const twin = path.join(HERE, 'ratings.example.jsonl');
  check('the example ratings twin ships beside the skill', fs.existsSync(twin));
  if (fs.existsSync(twin)) {
    const recs = read(twin).trim().split('\n').filter(Boolean);
    let allJson = true;
    for (const l of recs) { try { JSON.parse(l); } catch { allJson = false; } }
    check('every line of the twin is valid JSON', allJson, `${recs.length} record(s)`);
    const kinds = new Set(recs.map((l) => JSON.parse(l).kind));
    check('the twin documents both record kinds the script writes',
      kinds.has('rating') && kinds.has('human_pick'), [...kinds].join(','));
    check('config.example.json points ratings_log.path at the twin',
      EXAMPLE.ratings_log.path === 'ratings.example.jsonl', EXAMPLE.ratings_log.path);
    if (CONFIG) {
      check('the install config does NOT point at the twin (it would accumulate real records)',
        realConfigPath(CONFIG.ratings_log.path) !== twin, realConfigPath(CONFIG.ratings_log.path));
      check('the real log is configured OUTSIDE the skill directory',
        !realConfigPath(CONFIG.ratings_log.path).startsWith(HERE + path.sep),
        realConfigPath(CONFIG.ratings_log.path));
    }
  }
}

// ===========================================================================
// 9. The control on this suite's own safety property
// ===========================================================================
// Everything above ran with a temp config. If any case escaped it, the real log
// moved. This reports it on the happy path, in reading order; the exit handler
// installed at the top reports it in every other path, including an abort, and
// is what forces the non-zero status. Both, deliberately - one is legible, the
// other is unskippable.
check('the REAL ratings log was not touched by this suite',
  logFingerprint() === REAL_LOG_BEFORE,
  `${REAL_LOG}: before ${REAL_LOG_BEFORE}, after ${logFingerprint()}`);

// ===========================================================================
COMPLETED = true;
console.log(failures.length
  ? `\n${failures.length} FAILED:\n  ${failures.join('\n  ')}`
  : '\nAll checks passed.');
process.exit(failures.length ? 1 : 0);
