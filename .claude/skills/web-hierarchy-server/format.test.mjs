#!/usr/bin/env node
// format.test.mjs - how format.mjs finds and reads its configuration.
//
//   node .claude/skills/web-hierarchy-server/format.test.mjs
//
// Offline and hermetic: no port, no network, no real install. The fleet
// command is a FAKE this file writes into its own tempdir and selects with
// FLEET_BIN, so no real `fleet`, host config or install manifest is consulted,
// and every file it writes is under that tempdir.
//
// WHAT IT MEASURES, and why each leg is here:
//
//   1. WITH WEB_HIERARCHY_CONFIG UNSET, THE CONFIG IS WHAT `fleet where` NAMES.
//      config.json lives in the install, not beside the script, and the fleet
//      command is the one resolver of where an install is. The fake records the
//      arguments it was called with and prints a path; the leg passes only when
//      the arguments are exactly `where web-hierarchy-server config.json` AND
//      the process then used the file the fake named. Driven through BOTH entry
//      points, serve.mjs and build.mjs, because each is a separate script that
//      reaches format.mjs by import, and a resolver that one of them bypassed
//      would be invisible from the other.
//   2. THE VARIABLE WINS, AND THEN THE FLEET IS NOT ASKED AT ALL. The pair of
//      leg 1: without it, a script that always asked the fleet and ignored the
//      variable passes leg 1.
//   3. A FLEET THAT FAILS IS RELAYED, NEVER GUESSED PAST. The fake exits 3 the
//      way `fleet` does on a host with no install; the script must exit 2,
//      relaying the fleet's own line and naming the variable that bypasses it.
//      A fallback to some default file here would serve another install's
//      config with nothing on the page to say so.
//   4. A RELATIVE PATH IN config.json RESOLVES AGAINST THE CONFIG FILE'S
//      DIRECTORY, run from two different working directories. Against the
//      script's directory it would point into the fleet tree, and against the
//      cwd it would mean a different file per caller.
//   5. THE ROSTER: absent means the one shipped beside format.mjs (it loads, so
//      nothing is logged), and a relative path resolves against the config
//      file's directory (a missing one is logged naming that path).
//   6. packages.dir_pattern: a directory mention matching the configured shape
//      expands to the package's files; the same text with no pattern
//      configured expands to nothing (the pair: without it, a matcher that
//      found everything would pass); `docs/design/<slug>`, the value
//      config.example.json ships, compiles to one pinned expression, so an
//      install that keeps that value gets exactly that behaviour; and a pattern
//      without exactly one <slug> is refused.
//
// EXIT CODES - THREE, NEVER TWO:
//   0  PASS      every leg green.
//   1  FAIL      a leg disagreed.
//   2  NO VERDICT the instrument could not be established (the fake fleet
//      could not be written or did not run when it had to). Read a 2 as "this
//      file measured nothing", never as a smaller pass.
import { spawnSync } from 'node:child_process';
import { chmodSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync, existsSync } from 'node:fs';
import { join, dirname, parse } from 'node:path';
import { fileURLToPath } from 'node:url';
import { tmpdir } from 'node:os';

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURE_CFG = JSON.parse(readFileSync(join(HERE, 'fixtures', 'config.fixture.json'), 'utf8'));

const fails = [];
const check = (name, cond, detail = '') => {
  if (cond) return console.log(`  ok   ${name}`);
  fails.push(name);
  console.log(`  FAIL ${name}${detail ? ` - ${detail}` : ''}`);
};
const noVerdict = (why) => {
  console.log(`\nNO VERDICT: ${why}\nThis file measured nothing. Do not read this as a pass.`);
  process.exit(2);
};

const tmp = mkdtempSync(join(tmpdir(), 'web-hierarchy-format-test-'));
process.on('exit', () => { try { rmSync(tmp, { recursive: true, force: true }); } catch { /* best effort */ } });

// --- the fake fleet ---------------------------------------------------------
// Appends its arguments to FAKE_FLEET_LOG, prints FAKE_FLEET_ERR on stderr when
// set, exits FAKE_FLEET_EXIT when non-zero, and otherwise prints FAKE_FLEET_OUT.
const FAKE = join(tmp, 'fake-fleet');
writeFileSync(FAKE, [
  '#!/bin/sh',
  'printf \'%s\\n\' "$*" >> "$FAKE_FLEET_LOG"',
  '[ -n "$FAKE_FLEET_ERR" ] && printf \'%s\\n\' "$FAKE_FLEET_ERR" >&2',
  '[ "${FAKE_FLEET_EXIT:-0}" != 0 ] && exit "$FAKE_FLEET_EXIT"',
  'printf \'%s\\n\' "$FAKE_FLEET_OUT"',
  '',
].join('\n'));
chmodSync(FAKE, 0o755);

let runN = 0;
/** Run a script of this skill with a scrubbed environment and the fake fleet. */
function run(argv, { env = {}, cwd = tmp, fleetOut = '', fleetExit = 0, fleetErr = '' } = {}) {
  const log = join(tmp, `fleet-calls-${++runN}.log`);
  const childEnv = { ...process.env };
  for (const k of ['WEB_HIERARCHY_CONFIG', 'CLAUDE_CONFIG_DIR', 'FLEET_BIN']) delete childEnv[k];
  Object.assign(childEnv, {
    FLEET_BIN: FAKE, FAKE_FLEET_LOG: log, FAKE_FLEET_OUT: fleetOut,
    FAKE_FLEET_EXIT: String(fleetExit), FAKE_FLEET_ERR: fleetErr,
  }, env);
  const r = spawnSync(process.execPath, argv, { cwd, env: childEnv, encoding: 'utf8', timeout: 60000 });
  const calls = existsSync(log) ? readFileSync(log, 'utf8').trim().split('\n').filter(Boolean) : [];
  return { status: r.status, out: r.stdout || '', err: r.stderr || '', calls };
}
const SERVE = join(HERE, 'serve.mjs');
const BUILD = join(HERE, 'build.mjs');
const helpLine = (out, label) => (out.split('\n').find((l) => l.trim().startsWith(`${label}:`)) || '').split(`${label}:`)[1]?.trim() || '';

/** Write a config variant into its own install directory. */
function installConfig(mutate = null) {
  const dir = join(tmp, `install-${++runN}`);
  mkdirSync(dir, { recursive: true });
  const cfg = structuredClone(FIXTURE_CFG);
  if (mutate) mutate(cfg, dir);
  const file = join(dir, 'config.json');
  writeFileSync(file, JSON.stringify(cfg, null, 2));
  return { dir, file };
}

// --- the instrument, before anything is judged by it -----------------------
// Run the fake directly. If it cannot execute here (no /bin/sh, a noexec temp
// dir), every leg below would read "the script never asked the fleet" as a
// script defect when it is an instrument defect, so that is NO VERDICT.
{
  const log = join(tmp, 'fake-self-check.log');
  const r = spawnSync(FAKE, ['where', 'self-check'], {
    encoding: 'utf8', env: { ...process.env, FAKE_FLEET_LOG: log, FAKE_FLEET_OUT: '/fake/out', FAKE_FLEET_EXIT: '0', FAKE_FLEET_ERR: '' },
  });
  const logged = existsSync(log) ? readFileSync(log, 'utf8').trim() : '';
  if (r.error || r.status !== 0 || r.stdout.trim() !== '/fake/out' || logged !== 'where self-check') {
    noVerdict(`the fake fleet at ${FAKE} does not run here (${r.error?.code || `exit ${r.status}`}, logged "${logged}")`);
  }
}

// --- leg 1: no variable -> the file `fleet where` names --------------------
{
  const inst = installConfig();
  const r = run([SERVE, '--help'], { fleetOut: inst.file });
  check('serve.mjs asks the fleet exactly once, for this skill\'s config.json',
    r.calls.length === 1 && r.calls[0] === 'where web-hierarchy-server config.json', JSON.stringify(r.calls));
  check('serve.mjs --help succeeds on the config the fleet named', r.status === 0, `exit ${r.status}: ${r.err.trim()}`);
  check('serve.mjs --help reports the config file the fleet named',
    helpLine(r.out, 'config') === inst.file, `got "${helpLine(r.out, 'config')}"`);
}
{
  // build.mjs: the named config lacks a required key, so the refusal itself is
  // the proof of which file was read - it names the file and the key.
  const inst = installConfig((c) => { delete c.labels; });
  const r = run([BUILD, join(tmp, 'never-written.html')], { fleetOut: inst.file });
  check('build.mjs asks the fleet for this skill\'s config.json',
    r.calls.length === 1 && r.calls[0] === 'where web-hierarchy-server config.json', JSON.stringify(r.calls));
  check('build.mjs reads the file the fleet named (refusing it names that file and the key)',
    r.status === 2 && r.err.includes(inst.file) && r.err.includes("'labels.root_owner'"), `exit ${r.status}: ${r.err.trim()}`);
}

// --- leg 2: the variable wins, and the fleet is not asked ------------------
{
  const inst = installConfig();
  const decoy = installConfig();
  const r = run([SERVE, '--help'], { env: { WEB_HIERARCHY_CONFIG: inst.file }, fleetOut: decoy.file });
  check('WEB_HIERARCHY_CONFIG wins over the fleet', helpLine(r.out, 'config') === inst.file, `got "${helpLine(r.out, 'config')}"`);
  check('with WEB_HIERARCHY_CONFIG set the fleet is not asked at all', r.calls.length === 0, JSON.stringify(r.calls));
}

// --- leg 3: a failing fleet is relayed, never guessed past -----------------
{
  const r = run([SERVE, '--help'], { fleetExit: 3, fleetErr: 'fleet: FAKE-NOT-INSTALLED-LINE' });
  check('the fake fleet was asked (positive evidence the failure path was reached)', r.calls.length === 1, JSON.stringify(r.calls));
  check('a failing fleet makes serve.mjs exit 2', r.status === 2, `exit ${r.status}`);
  check('...relaying the fleet\'s own line', r.err.includes('FAKE-NOT-INSTALLED-LINE'), r.err.trim());
  check('...naming the command and the bypass variable',
    r.err.includes('where web-hierarchy-server config.json') && r.err.includes('WEB_HIERARCHY_CONFIG'), r.err.trim());
  check('...and serving nothing: no usage text was printed', !r.out.includes('usage:'), r.out.trim());
}
{
  const r = run([SERVE, '--help'], { fleetOut: '' });
  check('a fleet that prints no path is refused, not read as the cwd', r.status === 2 && /printed no path/.test(r.err), `exit ${r.status}: ${r.err.trim()}`);
}

// --- leg 4: relative config paths resolve against the config file ----------
{
  const inst = installConfig((c) => { c.transcripts.config_dir = 'agent-home/.claude'; });
  const want = join(inst.dir, 'agent-home', '.claude', 'projects');
  const a = run([SERVE, '--help'], { fleetOut: inst.file, cwd: tmp });
  const b = run([SERVE, '--help'], { fleetOut: inst.file, cwd: parse(tmp).root });
  check('a relative transcripts.config_dir resolves against the config file\'s directory',
    helpLine(a.out, 'transcripts') === want, `got "${helpLine(a.out, 'transcripts')}", want "${want}"`);
  check('...identically from a different working directory',
    helpLine(b.out, 'transcripts') === want, `got "${helpLine(b.out, 'transcripts')}"`);
}

// --- leg 5: the roster ------------------------------------------------------
{
  const inst = installConfig();
  const r = run([SERVE, '--help'], { fleetOut: inst.file });
  check('no identities key: the shipped roster loads (nothing is logged about it)',
    r.status === 0 && !/identities:/.test(r.err), r.err.trim());
  // Positive evidence for the line above, which "nothing logged" alone cannot
  // give: a formatter that loaded no roster and logged nothing would pass it.
  // The shipped roster's first software-engineer name must be assigned.
  const src = `import('${join(HERE, 'format.mjs')}').then((m) => console.log(JSON.stringify({
    path: m.identitiesPath,
    name: m.assignIdentities([{ id: 'a1', meta: { agentType: 'software-engineer' }, startTs: 1 }]).get('a1')?.name || null,
  })));`;
  const imp = run(['--input-type=module', '-e', src], { fleetOut: inst.file });
  let got = null;
  try { got = JSON.parse(imp.out.trim().split('\n').pop()); } catch { /* got stays null */ }
  const shipped = JSON.parse(readFileSync(join(HERE, 'identities.json'), 'utf8'))['software-engineer'].names[0];
  check('...and it IS the shipped roster: its path, and its first name assigned to the first agent of a role',
    got?.path === join(HERE, 'identities.json') && got?.name === shipped, `${JSON.stringify(got)} want ${shipped}`);
  const rel = installConfig((c) => { c.identities = { file: 'roster/ids.json' }; });
  const r2 = run([SERVE, '--help'], { fleetOut: rel.file });
  check('a relative identities.file resolves against the config file\'s directory',
    r2.err.includes(join(rel.dir, 'roster', 'ids.json')) && /not loaded/.test(r2.err), r2.err.trim());
}

// --- leg 6: packages.dir_pattern -------------------------------------------
{
  const repo = join(tmp, 'repo');
  mkdirSync(join(repo, 'pkgs', 'alpha'), { recursive: true });
  writeFileSync(join(repo, 'pkgs', 'alpha', 'design.md'), '# fixture\n');
  writeFileSync(join(repo, 'pkgs', 'alpha', 'notes.txt'), 'not a package artifact\n');
  const probe = (pattern) => {
    const inst = installConfig((c) => { c.packages = { repo_root: repo, dir_pattern: pattern }; });
    const src = `import('${join(HERE, 'format.mjs')}').then((m) => {
      console.log(JSON.stringify({
        found: m.detectPackagePaths('the package is at pkgs/alpha/ - read it'),
        shipped: m.pkgDirRegExp('docs/design/<slug>').source,
      }));
    });`;
    const r = run(['--input-type=module', '-e', src], { fleetOut: inst.file });
    try { return { ...JSON.parse(r.out.trim().split('\n').pop()), status: r.status, err: r.err }; }
    catch { return { found: null, status: r.status, err: r.err }; }
  };
  const on = probe('pkgs/<slug>');
  check('format.mjs imports with a dir_pattern config', on.found !== null, on.err.trim());
  check('a directory mention matching packages.dir_pattern expands to its artifact files',
    JSON.stringify(on.found) === JSON.stringify([join(repo, 'pkgs', 'alpha', 'design.md')]), JSON.stringify(on.found));
  const off = probe(null);
  check('the same text with no dir_pattern configured expands to nothing',
    Array.isArray(off.found) && off.found.length === 0, JSON.stringify(off.found));
  check('docs/design/<slug> compiles to its pinned expression',
    on.shipped === /(?:\/[\w.\-]+)*\/?docs\/design\/[\w.\-]+/.source, on.shipped);
  const bad = installConfig((c) => { c.packages = { repo_root: repo, dir_pattern: 'pkgs/alpha' }; });
  const r = run([SERVE, '--help'], { fleetOut: bad.file });
  check('a dir_pattern without exactly one <slug> is refused naming the key',
    r.status === 2 && r.err.includes('packages.dir_pattern'), `exit ${r.status}: ${r.err.trim()}`);
}

// --- verdict ----------------------------------------------------------------
if (fails.length) {
  console.log(`\nFAIL - ${fails.length} check(s):\n  - ${fails.join('\n  - ')}`);
  process.exit(1);
}
console.log('\nPASS - config resolution through the fleet, relative paths, roster, package pattern.');
process.exit(0);
