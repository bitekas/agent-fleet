#!/usr/bin/env node
// fleet-where.test.mjs - the fleet's one Node `fleet where` lookup (fleet-where.mjs).
//
//   node lib/fleet-where.test.mjs
//
// Offline and hermetic: the fleet command is a FAKE this file writes into its own
// tempdir, so no real `fleet`, host config or install manifest is consulted, and
// every file it writes is under that tempdir.
//
// WHAT IT MEASURES, and what each leg costs to remove:
//
//   1. FLEET_BIN SELECTS THE COMMAND, the arguments are exactly
//      `where <skill> <file>`, and the answer is the LAST line of its output.
//      Every skill test that fakes the fleet selects its fake this way; a lookup
//      that ignored FLEET_BIN would send those tests to the real fleet.
//   2. A FLEET THAT FAILS THROWS, NEVER GUESSES: a non-zero exit (its stderr line
//      relayed), no output, and a command that cannot run each throw naming the
//      command. A fallback file here is another install's config, read with
//      nothing on the page to say so.
//   3. configFile: THE VARIABLE WINS AND THEN THE FLEET IS NOT ASKED; an empty
//      variable counts as unset; a failure names the variable that bypasses it.
//      Without the "not asked" half, a lookup that always asked the fleet and
//      ignored the variable would pass the first half.
//   4. WITHOUT FLEET_BIN THE COMMAND IS bin/fleet IN THE HELPER'S OWN TREE,
//      FOUND THROUGH ITS REALPATH. Run in a child under --preserve-symlinks,
//      importing the helper through a symlinked directory, because only then is
//      the module's URL the LINK path: under Node's default resolution the URL
//      is already the real path, and a helper that dropped realpath would pass.
//      Its CONTROL proves the child really saw the link path; when it does not,
//      this leg cannot tell realpath from no realpath and the file issues no
//      verdict.
//   5. THE HELPER IMPORTS ONLY node: BUILTINS. agent-revive's profile.mjs loads
//      it, and that module's tests run on a clone with no `npm ci`; a package
//      import here would make them need one. The scanner is proven live first
//      (it must find node:child_process), because an empty match list satisfies
//      `every()` whatever the regex does.
//
// EXIT CODES - THREE, NEVER TWO:
//   0  PASS        every leg green.
//   1  FAIL        a leg disagreed.
//   2  NO VERDICT  the instrument is not established: the fake fleet does not run
//                  here, or leg 4's control did not fire. Read a 2 as "this file
//                  measured nothing", never as a smaller pass.
import { spawnSync } from 'node:child_process';
import { chmodSync, copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { tmpdir } from 'node:os';

const HERE = dirname(fileURLToPath(import.meta.url));
const SUBJECT = join(HERE, 'fleet-where.mjs');
const { fleetWhere, configFile } = await import(pathToFileURL(SUBJECT).href);

const fails = [];
const noVerdict = [];
const check = (name, cond, detail = '') => {
  if (cond) return console.log(`  ok   ${name}`);
  fails.push(name);
  console.log(`  FAIL ${name}${detail ? ` - ${detail}` : ''}`);
};
const thrown = (fn) => { try { fn(); return ''; } catch (e) { return e.message; } };
const attempt = (fn) => { try { return fn(); } catch (e) { return `THREW ${e.message}`; } };

const tmp = mkdtempSync(join(tmpdir(), 'fleet-where-test-'));
process.on('exit', () => { try { rmSync(tmp, { recursive: true, force: true }); } catch { /* best effort */ } });

// --- the fake fleet ---------------------------------------------------------
// Appends its arguments to FAKE_FLEET_LOG, prints FAKE_FLEET_ERR on stderr when
// set, exits FAKE_FLEET_EXIT when non-zero, and otherwise prints FAKE_FLEET_OUT.
const FAKE_SRC = [
  '#!/bin/sh',
  'printf \'%s\\n\' "$*" >> "$FAKE_FLEET_LOG"',
  '[ -n "$FAKE_FLEET_ERR" ] && printf \'%s\\n\' "$FAKE_FLEET_ERR" >&2',
  '[ "${FAKE_FLEET_EXIT:-0}" != 0 ] && exit "$FAKE_FLEET_EXIT"',
  'printf \'%s\\n\' "$FAKE_FLEET_OUT"',
  '',
].join('\n');
const writeFake = (file) => { mkdirSync(dirname(file), { recursive: true }); writeFileSync(file, FAKE_SRC); chmodSync(file, 0o755); };
const FAKE = join(tmp, 'fake-fleet');
writeFake(FAKE);

let runN = 0;
const calls = (log) => (existsSync(log) ? readFileSync(log, 'utf8').trim().split('\n').filter(Boolean) : []);
/** Point the process at the fake with these answers; returns the call log path. */
function fake({ out = '', exit = 0, err = '', bin = FAKE } = {}) {
  const log = join(tmp, `calls-${++runN}.log`);
  Object.assign(process.env, { FLEET_BIN: bin, FAKE_FLEET_LOG: log, FAKE_FLEET_OUT: out, FAKE_FLEET_EXIT: String(exit), FAKE_FLEET_ERR: err });
  return log;
}

// --- the instrument, before anything is judged by it -----------------------
{
  const log = fake({ out: '/fake/out' });
  const r = spawnSync(FAKE, ['where', 'self-check'], { encoding: 'utf8' });
  if (r.error || r.status !== 0 || r.stdout.trim() !== '/fake/out' || calls(log).join() !== 'where self-check') {
    console.log(`\nNO VERDICT: the fake fleet at ${FAKE} does not run here (${r.error?.code || `exit ${r.status}`}).`);
    console.log('This file measured nothing. Do not read this as a pass.');
    process.exit(2);
  }
}

// --- leg 1: FLEET_BIN, the arguments, the last line -------------------------
{
  const want = join(tmp, 'install', 'a-skill', 'config.json');
  const log = fake({ out: `a progress line\n${want}` });
  const got = attempt(() => fleetWhere('a-skill', 'config.json'));
  check('the fake named by FLEET_BIN is asked exactly once, with `where <skill> <file>`',
    calls(log).length === 1 && calls(log)[0] === 'where a-skill config.json', JSON.stringify(calls(log)));
  check('the answer is the last line of its output', got === want, `got "${got}"`);
  fake({ out: 'relative/x.json' });
  const rel = attempt(() => fleetWhere('a-skill', 'x.json'));
  check('a relative answer is made absolute', rel === resolve('relative/x.json'), `got "${rel}"`);
}

// --- leg 2: a failing fleet throws, never guesses ---------------------------
{
  const log = fake({ exit: 3, err: 'fleet: FAKE-NOT-INSTALLED-LINE' });
  const m = thrown(() => fleetWhere('a-skill', 'config.json'));
  check('the failing fake was asked (positive evidence the failure path was reached)', calls(log).length === 1, JSON.stringify(calls(log)));
  check('a non-zero exit throws, naming the command, the status and the relayed line',
    m.includes('where a-skill config.json') && m.includes('exited 3') && m.includes('FAKE-NOT-INSTALLED-LINE'), m || 'no throw');
  fake({ out: '' });
  const m2 = thrown(() => fleetWhere('a-skill', 'config.json'));
  check('no output throws "printed no path", never resolves to the cwd', /printed no path/.test(m2), m2 || 'no throw');
  fake({ bin: join(tmp, 'no-such-fleet') });
  const m3 = thrown(() => fleetWhere('a-skill', 'config.json'));
  check('a command that cannot run throws "cannot run", naming it and the cause',
    m3.includes(`cannot run \`${join(tmp, 'no-such-fleet')} where a-skill config.json\``) && m3.includes('ENOENT'), m3 || 'no throw');
}

// --- leg 3: configFile -----------------------------------------------------
{
  const VAR = 'FLEET_WHERE_TEST_CONFIG';
  const fleetAnswer = join(tmp, 'install', 'from-fleet.json');
  let log = fake({ out: fleetAnswer });
  process.env[VAR] = 'from-env.json';
  const fromEnv = attempt(() => configFile('a-skill', VAR));
  check('the variable wins, resolved against the cwd', fromEnv === resolve('from-env.json'), `got "${fromEnv}"`);
  check('...and then the fleet is not asked at all', calls(log).length === 0, JSON.stringify(calls(log)));
  process.env[VAR] = '';
  log = fake({ out: fleetAnswer });
  const fromFleet = attempt(() => configFile('a-skill', VAR));
  check('an empty variable counts as unset: the fleet answers', fromFleet === fleetAnswer, `got "${fromFleet}"`);
  check('...asked once, for the skill\'s config.json', calls(log).length === 1 && calls(log)[0] === 'where a-skill config.json', JSON.stringify(calls(log)));
  delete process.env[VAR];
  fake({ exit: 3, err: 'fleet: FAKE-NOT-INSTALLED-LINE' });
  const m = thrown(() => configFile('a-skill', VAR));
  check('a failure relays the fleet\'s line and names the variable that bypasses it',
    m.includes('FAKE-NOT-INSTALLED-LINE') && m.includes(`set ${VAR} to name the config file directly`), m || 'no throw');
}

// --- leg 4: the default command, through the helper's realpath --------------
// A scratch fleet tree: bin/fleet is a fake with an answer of its OWN (it ignores
// FAKE_FLEET_OUT, which the child sets to a decoy, so no other fake can produce
// this answer), lib/ holds a byte copy of the subject and a probe that reports its
// own module URL. An agent-side link points at that lib/, and a child imports both
// through the link with symlinks preserved.
{
  const tree = join(tmp, 'tree');
  mkdirSync(join(tree, 'bin'), { recursive: true });
  writeFileSync(join(tree, 'bin', 'fleet'), '#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$FAKE_FLEET_LOG"\necho /tree/bin-fleet-answer.json\n');
  chmodSync(join(tree, 'bin', 'fleet'), 0o755);
  mkdirSync(join(tree, 'lib'), { recursive: true });
  copyFileSync(SUBJECT, join(tree, 'lib', 'fleet-where.mjs'));
  writeFileSync(join(tree, 'lib', 'where-am-i.mjs'), 'export const url = import.meta.url;\n');
  mkdirSync(join(tmp, 'agent'), { recursive: true });
  const link = join(tmp, 'agent', 'lib');
  symlinkSync(join(tree, 'lib'), link);
  const log = join(tmp, 'tree-calls.log');
  const src = `const p = await import(${JSON.stringify(pathToFileURL(join(link, 'where-am-i.mjs')).href)});
const h = await import(${JSON.stringify(pathToFileURL(join(link, 'fleet-where.mjs')).href)});
console.log(JSON.stringify({ probe: p.url, answer: (() => { try { return h.fleetWhere('a-skill', 'config.json'); } catch (e) { return 'THREW ' + e.message; } })() }));`;
  const env = { ...process.env, FAKE_FLEET_LOG: log, FAKE_FLEET_OUT: '/decoy/not-the-tree-bin.json', FAKE_FLEET_EXIT: '0', FAKE_FLEET_ERR: '' };
  delete env.FLEET_BIN;
  const r = spawnSync(process.execPath, ['--preserve-symlinks', '--input-type=module', '-e', src], { encoding: 'utf8', env, timeout: 60000 });
  let got = null;
  try { got = JSON.parse(r.stdout.trim().split('\n').pop()); } catch { /* got stays null */ }
  const linkUrl = pathToFileURL(join(link, 'where-am-i.mjs')).href;
  if (got?.probe !== linkUrl) {
    noVerdict.push(`leg 4: the child did not load the helper through the link path (probe ${got?.probe || r.stderr.trim()})`);
    console.log(`  NO VERDICT leg 4 control: the module URL is not the link path, so realpath cannot be told apart`);
  } else {
    console.log('  ok   control: the child loaded the helper through the LINK path (so the leg below can see realpath)');
    check('without FLEET_BIN the command is bin/fleet in the helper\'s own tree, found through its realpath',
      got.answer === '/tree/bin-fleet-answer.json' && calls(log).join() === 'where a-skill config.json', `${JSON.stringify(got)} calls ${JSON.stringify(calls(log))}`);
  }
}

// --- leg 5: Node builtins only ----------------------------------------------
// Every `from '<spec>'` (an import or re-export on one line or several) and every
// bare `import '<spec>'`, in the code with comment lines removed.
{
  const code = readFileSync(SUBJECT, 'utf8').split('\n').filter((l) => !/^\s*(\/\/|\/?\*)/.test(l)).join('\n');
  const specs = [...code.matchAll(/\bfrom\s*['"]([^'"]+)['"]|^\s*import\s*['"]([^'"]+)['"]/gm)].map((m) => m[1] || m[2]);
  if (!specs.includes('node:child_process')) {
    noVerdict.push(`leg 5: the import scanner did not find node:child_process (found ${JSON.stringify(specs)})`);
    console.log('  NO VERDICT leg 5 control: the import scanner found nothing it must find');
  } else {
    console.log('  ok   control: the import scanner finds node:child_process (so the list below is real)');
    check('every static import is a node: builtin', specs.every((s) => s.startsWith('node:')), JSON.stringify(specs));
    check('no dynamic import or require outside comments', !/\bimport\s*\(|\brequire\s*\(/.test(code));
  }
}

// --- verdict ----------------------------------------------------------------
for (const k of ['FLEET_BIN', 'FAKE_FLEET_LOG', 'FAKE_FLEET_OUT', 'FAKE_FLEET_EXIT', 'FAKE_FLEET_ERR']) delete process.env[k];
if (noVerdict.length) {
  console.log(`\nNO VERDICT - ${noVerdict.length} control(s) did not fire:\n  - ${noVerdict.join('\n  - ')}`);
  console.log('This file has not established its instrument. Do not read this as a pass.');
  process.exit(2);
}
if (fails.length) {
  console.log(`\nFAIL - ${fails.length} check(s):\n  - ${fails.join('\n  - ')}`);
  process.exit(1);
}
console.log('\nPASS - FLEET_BIN, the arguments and the last line, failures thrown, configFile, the default command through realpath, builtins only.');
process.exit(0);
