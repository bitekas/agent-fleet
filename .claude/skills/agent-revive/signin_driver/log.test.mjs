#!/usr/bin/env node
// log.test.mjs - WHERE THE SIGN-IN CLIENT'S LOG GOES, AND THAT ITS MODE HOLDS.
//
//   node .claude/skills/agent-revive/signin_driver/log.test.mjs
//
// The log signin.mjs opens takes the detached driver's raw stdout and stderr - the
// one output stream that does not pass through the driver's redactor - and is kept
// after `quit`. Two properties keep it private, and this file measures both:
//
//   1. THE DEFAULT LOG IS IN A DIRECTORY ONLY THIS USER CAN ENTER:
//      <XDG_STATE_HOME, else ~/.local/state>/agent-revive/, mode 0700, the file
//      0600. A fixed name in the shared temp directory is a name any other local
//      user can create first - as a file of theirs, which the client then cannot
//      narrow and they can read, or as a symlink to a file of ours, which the
//      client then appends to. A directory that is not a real directory this user
//      owns (a symlink planted in its place) is refused, with nothing started.
//   2. A MODE THAT CANNOT BE SET STOPS THE START. The client opens the log and
//      sets 0600 on it; when that fails it exits non-zero naming the log and
//      starts no driver, instead of writing the driver's output into a file of
//      whatever mode it found. Measured with --log /dev/null, which every user
//      may open and only root may chmod.
//
// HOW: `start` with a config path that does not exist. The client opens the log
// and launches the driver, which refuses at once (exit 2, "cannot read config")
// and writes that refusal into the log; the client then prints the log's path.
// No browser, no display and no network is involved, so it runs the same on
// Linux and macOS, with or without the driver's npm install.
//
// CONTROLS: the refusal line is found IN the default log file, which proves the
// path the client printed is the file the driver wrote, not just a string; and
// the client reports the driver's exit in the default case, so the /dev/null
// case's "no driver exit reported" means no driver ran, not a client that never
// reports one.
// Run as root it is NO VERDICT: root may chmod /dev/null, and must not.
//
// Every run uses a temporary HOME, XDG_STATE_HOME and TMPDIR of its own.
// Exit codes: 0 PASS; 1 FAIL; 2 NO VERDICT.
import { spawnSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, rmSync, statSync, lstatSync, readFileSync, readdirSync, symlinkSync, existsSync, writeFileSync, chmodSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { tmpdir } from 'node:os';

const HERE = dirname(fileURLToPath(import.meta.url));
const SIGNIN = join(HERE, 'signin.mjs');
const fails = [];
const check = (name, cond, detail = '') => {
  console.log(`  ${cond ? 'ok  ' : 'FAIL'} ${name}${cond || !detail ? '' : ` - ${detail}`}`);
  if (!cond) fails.push(name);
};
const noVerdict = (why) => { console.log(`\nNO VERDICT: ${why}`); process.exit(2); };
if (process.getuid && process.getuid() === 0) noVerdict('run as root, which may chmod /dev/null; run it as an ordinary user');

const T = mkdtempSync(join(tmpdir(), 'signin-log-test-'));
process.on('exit', () => { try { rmSync(T, { recursive: true, force: true }); } catch { /* best effort */ } });
const mode = (p) => (statSync(p).mode & 0o777).toString(8);

// One `start` in a world of its own: HOME, TMPDIR and (optionally) XDG_STATE_HOME.
function start(name, { xdg = false, args = [] } = {}) {
  const w = join(T, name);
  for (const d of ['home', 'tmp']) mkdirSync(join(w, d), { recursive: true });
  const env = { ...process.env, HOME: join(w, 'home'), TMPDIR: join(w, 'tmp') };
  delete env.XDG_STATE_HOME;
  delete env.DISPLAY;
  if (xdg) env.XDG_STATE_HOME = join(w, 'state');
  const r = spawnSync(process.execPath, [SIGNIN, 'logtest', 'start', '--config', join(w, 'no-such-config.json'),
    '--run-dir', join(w, 'run'), '--no-xvfb', ...args], { env, encoding: 'utf8', timeout: 90000 });
  const printed = (r.stderr.match(/\(log: ([^)\n]+)\)/) || [])[1] || null;
  return { w, r, printed, out: `${r.stdout}${r.stderr}`.trim().slice(-400) };
}

// --- 1. the default log, under ~/.local/state --------------------------------------
{
  const { w, r, printed, out } = start('default');
  const dir = join(w, 'home', '.local', 'state', 'agent-revive');
  if (!printed) noVerdict(`start printed no log path (exit ${r.status}): ${out}`);
  if (!existsSync(printed) || !readFileSync(printed, 'utf8').includes('cannot read config')) {
    noVerdict(`the driver's refusal is not in the file start named (${printed}), so nothing below is about that file: ${out}`);
  }
  // The signal case 2 reads for "a driver ran": present here, where one did.
  if (!/driver exited/.test(r.stderr)) noVerdict(`start did not report the driver's exit, so its absence in case 2 would mean nothing: ${out}`);
  check('the default log is under ~/.local/state/agent-revive/', dirname(printed) === dir, printed);
  check('that directory is mode 700', existsSync(dir) && mode(dir) === '700', existsSync(dir) ? mode(dir) : 'absent');
  check('the log is mode 600', mode(printed) === '600', mode(printed));
  const strays = readdirSync(join(w, 'tmp')).filter((f) => f.endsWith('.log'));
  check('no log in the shared temp directory', strays.length === 0, strays.join(', '));
  // A second start appends to the same file and leaves both modes as they are.
  chmodSync(printed, 0o644);
  const again = spawnSync(process.execPath, [SIGNIN, 'logtest', 'start', '--config', join(w, 'no-such-config.json'),
    '--run-dir', join(w, 'run'), '--no-xvfb'], { env: { ...process.env, HOME: join(w, 'home'), TMPDIR: join(w, 'tmp'), XDG_STATE_HOME: '' }, encoding: 'utf8', timeout: 90000 });
  check('a log found at 644 is narrowed to 600 by the next start', mode(printed) === '600' && again.status !== 0,
    `${mode(printed)}, exit ${again.status}`);
}

// --- 1b. XDG_STATE_HOME names the state root -----------------------------------------
{
  const { w, printed, out } = start('xdg', { xdg: true });
  check('with XDG_STATE_HOME set, the log is under $XDG_STATE_HOME/agent-revive/',
    printed === join(w, 'state', 'agent-revive', 'signin-logtest.log'), `${printed} | ${out}`);
}

// --- 1c. a planted symlink in place of the directory is refused ------------------------
{
  const name = 'planted';
  const w = join(T, name);
  const elsewhere = join(w, 'elsewhere');
  mkdirSync(elsewhere, { recursive: true });
  mkdirSync(join(w, 'home', '.local', 'state'), { recursive: true });
  symlinkSync(elsewhere, join(w, 'home', '.local', 'state', 'agent-revive'));
  const { r, out } = start(name);
  check('a symlink where the log directory belongs is refused: non-zero exit, nothing written through it',
    r.status !== 0 && /log directory/.test(r.stderr) && readdirSync(elsewhere).length === 0
    && lstatSync(join(w, 'home', '.local', 'state', 'agent-revive')).isSymbolicLink(), `exit ${r.status}: ${out}`);
}

// --- 2. a log whose mode cannot be set stops the start ---------------------------------
{
  const { r, out } = start('devnull', { args: ['--log', '/dev/null'] });
  check('--log /dev/null (mode cannot be set): exit non-zero naming the log and 0600',
    r.status !== 0 && r.stderr.includes('/dev/null') && r.stderr.includes('0600'), `exit ${r.status}: ${out}`);
  check('...and no driver was started (no driver exit is reported, unlike case 1)',
    !/driver exited|cannot read config/.test(r.stderr), out);
}

if (fails.length) {
  console.log(`\nFAIL - ${fails.length} check(s):\n  - ${fails.join('\n  - ')}`);
  process.exit(1);
}
console.log('\nPASS - the default log is private (0700 directory, 0600 file), and a mode that cannot be set stops the start.');
process.exit(0);
