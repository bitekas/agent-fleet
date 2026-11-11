#!/usr/bin/env node
// Guard on the STORED sign-in profile (`start --profile`, `--port`, `profiles-check`)
// and on the throwaway mode staying what it was. Fake pool, fake config, a temp
// profiles dir; the only pages ever loaded are about:blank, data: URLs and a server
// this file runs on 127.0.0.1. No real site, no real pool, no real account.
//
//   node profiles.test.mjs
//
// ── TWO HALVES ───────────────────────────────────────────────────────────────
//   A  pure: profile.mjs's rules, the driver's refusals (which all happen before a
//      browser is needed), and structural checks on driver.mjs and signin.mjs.
//      Needs node only.
//   B  browser: real drivers (under xvfb-run on Linux without a DISPLAY; through
//      WindowServer on macOS) on the fake pool - a profile kept by
//      `quit` while the run dir goes, a cookie that survives a restart on a stored
//      profile and does not on a throwaway one, a busy profile refused BEFORE
//      Chromium is reached, profiles-check end to end, and no password on any
//      output. Needs signin_driver's node_modules, a chromium build (the driver's
//      browsers/, or PLAYWRIGHT_BROWSERS_PATH), and a display: DISPLAY or xvfb-run
//      on Linux, the console user's Aqua session (launchctl print gui/<uid>) on macOS.
//      Half A also holds that `share` refuses on macOS, naming SKILL.md step 7e, and
//      that the refusal is macOS's alone (on Linux the same call fails for its own
//      reason, never with the macOS text).
//
// ── EXIT CODES: THREE, NEVER TWO ─────────────────────────────────────────────
//   0  PASS        every property holds, in BOTH halves
//   1  FAIL        at least one property is broken - each one is named
//   3  NO VERDICT  a control misbehaved, OR half B could not run on this host.
//                  ⚠️ A run where half B never started is not a smaller pass: the
//                  properties that matter most (the profile survives, the password
//                  stays off every output) live there, and a green that skipped
//                  them is the comfortable lie this exit code exists to refuse.
//
// ── WHY THE CONTROLS ARE LOAD-BEARING ────────────────────────────────────────
// Most of what this file asserts is an ABSENCE - no password in the output, no
// profile in the run dir, no directory created by a read-only check, no second window
// in a busy browser - and an absence is exactly what a run that never exercised the
// path produces. So each absence stands beside a control that proves the path ran:
//   - the password is asserted absent only after `inspect` came back carrying the
//     redaction marker - proof the password really was in the page and crossed the
//     wire; and the scanner is first shown a planted sentinel, so it can find one;
//   - "the profile survives quit" is paired with a cookie that comes back on a
//     restart, and "the throwaway forgets" with the same cookie NOT coming back;
//   - "a busy profile is refused before Chromium" is read from the pre-check's own
//     message, and paired with the first browser's page count staying 1 - a losing
//     launch adds a window to the winner (measured, profile.mjs `profileInUse`);
//   - the storage refusal is first shown a directory it must ACCEPT, so a function
//     that refused everything could not pass the refusals.
// Delete a control and the assertion beside it can no longer fail.

import { readFileSync, writeFileSync, mkdirSync, mkdtempSync, rmSync, existsSync, statSync, chmodSync, symlinkSync, readdirSync, realpathSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { tmpdir, hostname, userInfo, homedir } from 'node:os';
import { spawn, spawnSync } from 'node:child_process';
import http from 'node:http';
import net from 'node:net';
import {
  PROFILE_IN_USE, PROFILES_KEY, profileNameRefusal, profilesDirOf, storageRefusal,
  resolveProfile, profileInUse, siteState, landedAt, fleetWhere, configPathFrom,
} from './profile.mjs';

const HERE = realpathSync(dirname(fileURLToPath(import.meta.url)));
const SKILL = dirname(HERE);
// The fixture install context, unless the runner already named one (tests/run-all.sh does).
process.env.FLEET_CONTEXT_ROOT ??= join(SKILL, '..', '..', '..', 'tests', 'fixtures', 'install');
const CLIENT = join(HERE, 'signin.mjs');
let pass = 0, fail = 0;
const inconclusive = [];
const ok = (what, got, want) => {
  if (got === want) { console.log(`ok   - ${what}`); pass++; }
  else { console.log(`FAIL - ${what}: expected ${JSON.stringify(want)}, got ${JSON.stringify(got)}`); fail++; }
};
const control = (what, got, want) => {
  if (got === want) { console.log(`ok   - control: ${what}`); pass++; }
  else { console.log(`CONTROL BROKEN - ${what}: expected ${JSON.stringify(want)}, got ${JSON.stringify(got)}`); inconclusive.push(what); }
};
const modeOf = p => (statSync(p).mode & 0o777).toString(8);

// ⚠️ SHORT, ON PURPOSE: a run dir holds the driver's unix socket, and a socket path
// holds at most 107 bytes on Linux and 103 on macOS (driver.mjs refuses a longer one).
// A long TMPDIR is a host this half cannot run on, said as such rather than as a
// driver failure.
const T = mkdtempSync(join(tmpdir(), 'sipt-'));
const PW_A = 'SENTINEL-alpha-pw-6e1f*?[x]';
const PW_B = 'SENTINEL-beta-pw-77c2';
const SENTINELS = [PW_A, PW_B];
const POOL = join(T, 'pool.json');
writeFileSync(POOL, JSON.stringify([
  { username: 'alpha@example.com', password: PW_A, home_agent: 'x' },
  { username: 'beta@example.com', password: PW_B, home_agent: 'y' },
]));
chmodSync(POOL, 0o600);
const PROFILES = join(T, 'profiles');
// The agents home every config here names: a temp directory, so no case depends on
// where this host keeps its real agents.
const AH = join(T, 'agents');
const writeConfig = (name, accountsExtra) => {
  const p = join(T, name);
  writeFileSync(p, JSON.stringify({ fleet: { agents_home: AH }, accounts: { pool_file: POOL, ...accountsExtra } }));
  return p;
};
const CONFIG = writeConfig('config.json', { profiles_dir: PROFILES });

// Every byte any client call or driver log produces is collected and scanned for the
// passwords at the end.
const transcript = [];
// ⚠️ EVERY DRIVER `start` LAUNCHED IS RECORDED, AND THE FINAL TEARDOWN SIGNALS ITS
// WHOLE PROCESS GROUP. The client spawns the driver detached (its own group: xvfb-run,
// Xvfb, node, Chromium), so a half B that throws between a start and its quit would
// otherwise leave a live browser - and a profile it keeps writing into - behind this
// test. SIGTERM reaches the driver's own cleanup, which removes its run dir.
const started = new Set();
const childEnv = { ...process.env };
for (const k of ['DEBUG', 'DEBUG_COLORS', 'NODE_DEBUG', 'PWDEBUG', 'PLAYWRIGHT_DEBUG']) delete childEnv[k];
// THE BROWSERS WRITE INTO A HOME OF THIS RUN'S OWN. Chromium keeps state under
// $XDG_CONFIG_HOME/google-chrome-for-testing (macOS: under $HOME/Library) and ibus
// under $XDG_CONFIG_HOME/ibus; inherited, those land in the runner's or the operator's
// real home on every run. The host settings keep the path the real HOME gave them
// (fleetlib's default), so `fleet where` resolves as it would have.
childEnv.FLEET_HOST_CONFIG ||= join(homedir(), '.config', 'agent-fleet', 'host.json');
childEnv.HOME = join(T, 'home');
childEnv.XDG_CONFIG_HOME = join(T, 'home', '.config');
mkdirSync(childEnv.XDG_CONFIG_HOME, { recursive: true });
// ⚠️ ASYNCHRONOUS, NEVER spawnSync: half B's pages are served from THIS process, and
// a spawnSync blocks its event loop, so the browser's request would wait on a server
// that cannot answer until the client returns - which it does only after the
// driver's 45 s navigation timeout. Every visit then reads as a broken page.
function client(args, { env = {}, timeout = 120000 } = {}) {
  const t0 = Date.now();
  return new Promise(res => {
    const c = spawn(process.execPath, [CLIENT, ...args], { env: { ...childEnv, ...env } });
    let stdout = '', stderr = '';
    c.stdout.on('data', d => { stdout += d; });
    c.stderr.on('data', d => { stderr += d; });
    const kill = setTimeout(() => c.kill('SIGTERM'), timeout);
    c.on('close', status => {
      clearTimeout(kill);
      transcript.push(stdout, stderr);
      let json = null;
      try { json = JSON.parse(stdout); } catch {}
      if (json && json.started && json.pid) started.add(json.pid);
      res({ status, stdout, stderr, json, ms: Date.now() - t0, pid: c.pid });
    });
  });
}

try {
  // ══ HALF A: pure ═══════════════════════════════════════════════════════════
  // ── profile names ──
  for (const good of ['alpha@example.com', 'first.last+tag@example.com', 'a_b-c']) ok(`profile name ${good} is accepted`, profileNameRefusal(good), null);
  for (const bad of ['../x', 'a/b', '.', '..', '', 'x y', 'a\\b', undefined]) ok(`profile name ${JSON.stringify(bad)} is refused`, typeof profileNameRefusal(bad), 'string');

  // ── where a profile may live ──
  // ⚠️ CONTROL FIRST: a refusal that refused everything would pass every refusal below.
  const plain = join(T, 'plain', 'profiles');
  const home = { agentsHome: AH };
  control('a plain temp directory is ACCEPTED (so the refusals below are not vacuous)', storageRefusal(plain, home), null);
  ok('with no fleet.agents_home the check REFUSES, never skips the agents-home rule',
     /fleet\.agents_home is not set/.test(storageRefusal(plain, {}) || ''), true);
  const repo = join(T, 'repo');
  mkdirSync(join(repo, '.git'), { recursive: true });
  ok('a profiles dir inside a git clone is refused', /git work tree/.test(storageRefusal(join(repo, 'secrets', 'profiles'), home) || ''), true);
  const wt = join(T, 'worktree');
  mkdirSync(wt, { recursive: true });
  writeFileSync(join(wt, '.git'), 'gitdir: /nowhere\n');
  ok('...and inside a git WORKTREE, whose .git is a file', /git work tree/.test(storageRefusal(join(wt, 'p'), home) || ''), true);
  symlinkSync(join(repo, 'secrets'), join(T, 'innocent-link'));
  control('the symlinked path does not itself name the repository (so only resolving it can catch it)', join(T, 'innocent-link', 'profiles').includes(join(T, 'repo')), false);
  ok('...and through a symlink into one, resolved before the check', /git work tree/.test(storageRefusal(join(T, 'innocent-link', 'profiles'), home) || ''), true);
  ok('a profiles dir under <fleet.agents_home>/<agent> is refused', /agents home/.test(storageRefusal(join(AH, 'ada', 'profiles'), home) || ''), true);
  ok('...and under the agents home itself', /agents home/.test(storageRefusal(join(AH, 'profiles'), home) || ''), true);
  symlinkSync(join(AH, 'ada'), join(T, 'agent-link'));
  ok('...and through a symlink into it, resolved before the check', /agents home/.test(storageRefusal(join(T, 'agent-link', 'profiles'), home) || ''), true);
  ok('a sibling of that agents home is not caught by a prefix match', storageRefusal(`${AH}-other/p`, home), null);
  ok('a RELATIVE profiles_dir resolves against the config file, i.e. into this skill tree, and is refused',
     typeof storageRefusal(profilesDirOf({ accounts: { profiles_dir: 'profiles' } }, join(SKILL, 'config.json')), home), 'string');
  // The install's value must be one the driver accepts, or the first enrollment dies.
  // Read from the install context `fleet where` resolves (the fixture install in the
  // fleet's CI); this stats ancestors for a `.git` entry and reads nothing else.
  let installCfgPath = '', installCfg = null;
  try { installCfgPath = fleetWhere('agent-revive', 'config.json'); installCfg = JSON.parse(readFileSync(installCfgPath, 'utf8')); } catch (e) { installCfgPath = e.message; }
  ok(`the install context's config.json carries ${PROFILES_KEY} (${installCfgPath})`, typeof installCfg?.accounts?.profiles_dir, 'string');
  ok("...and the driver would accept where it points", installCfg && storageRefusal(profilesDirOf(installCfg, installCfgPath), { agentsHome: installCfg?.fleet?.agents_home }), null);
  // ── the config path: a flag, else $AGENT_REVIVE_CONFIG, else `fleet where` ──
  // The expected install path is built here from FLEET_CONTEXT_ROOT, not taken from
  // fleetWhere, so a configPathFrom that skipped the fleet call cannot agree with it.
  const savedCfgEnv = process.env.AGENT_REVIVE_CONFIG, savedBin = process.env.FLEET_BIN;
  delete process.env.AGENT_REVIVE_CONFIG;
  ok('configPathFrom: an explicit path wins', configPathFrom('/x/flag.json'), '/x/flag.json');
  process.env.AGENT_REVIVE_CONFIG = '/x/env.json';
  ok('configPathFrom: else $AGENT_REVIVE_CONFIG', configPathFrom(undefined), '/x/env.json');
  delete process.env.AGENT_REVIVE_CONFIG;
  ok('configPathFrom: else the install context, through fleet where', configPathFrom(undefined),
     join(realpathSync(process.env.FLEET_CONTEXT_ROOT), '.claude', 'skills', 'agent-revive', 'config.json'));
  process.env.FLEET_BIN = join(T, 'no-such-fleet');
  let whereErr = '';
  try { configPathFrom(undefined); } catch (e) { whereErr = e.message; }
  ok('configPathFrom: a fleet command that fails throws, naming the remedy', /pass --config or set AGENT_REVIVE_CONFIG/.test(whereErr), true);
  if (savedBin === undefined) delete process.env.FLEET_BIN; else process.env.FLEET_BIN = savedBin;
  if (savedCfgEnv !== undefined) process.env.AGENT_REVIVE_CONFIG = savedCfgEnv;
  let missing = '';
  try { profilesDirOf({ accounts: {} }, 'cfg.json'); } catch (e) { missing = e.message; }
  ok(`a config without ${PROFILES_KEY} is refused by name`, missing.includes(PROFILES_KEY), true);
  const resolved = resolveProfile({ cfg: { fleet: { agents_home: AH }, accounts: { profiles_dir: PROFILES } }, configPath: CONFIG, username: 'alpha@example.com', usernames: ['alpha@example.com'] });
  ok('a pool username resolves to <profiles_dir>/<username>', resolved.dir, join(PROFILES, 'alpha@example.com'));
  let notPool = '';
  try { resolveProfile({ cfg: { fleet: { agents_home: AH }, accounts: { profiles_dir: PROFILES } }, configPath: CONFIG, username: 'nobody@example.com', usernames: ['alpha@example.com'] }); } catch (e) { notPool = e.message; }
  ok('a username in no pool entry is refused', /not a username in the account pool/.test(notPool), true);

  // ── in use: Chromium's SingletonLock ──
  const lockDir = join(T, 'lockprobe');
  mkdirSync(lockDir);
  ok('no SingletonLock: not in use', profileInUse(lockDir), null);
  symlinkSync(`${hostname()}-${process.pid}`, join(lockDir, 'SingletonLock'));
  ok('a lock held by a live pid on this host: in use, said with the shared string', (profileInUse(lockDir) || '').startsWith(PROFILE_IN_USE), true);
  rmSync(join(lockDir, 'SingletonLock'));
  const dead = spawnSync(process.execPath, ['-e', '0']).pid;
  symlinkSync(`${hostname()}-${dead}`, join(lockDir, 'SingletonLock'));
  ok('a lock whose pid is dead is stale, not in use (Chromium reclaims it)', profileInUse(lockDir), null);
  rmSync(join(lockDir, 'SingletonLock'));
  symlinkSync('some-other-host-4242', join(lockDir, 'SingletonLock'));
  ok("a lock taken on another host is in use", (profileInUse(lockDir) || '').startsWith(PROFILE_IN_USE), true);

  // ── reading a landing URL ──
  const table = [
    ['claude', 'https://claude.ai/login', 'out'], ['claude', 'https://claude.ai/login?returnTo=%2F', 'out'],
    ['claude', 'https://claude.ai/logout', 'out'], ['claude', 'https://claude.ai/new', 'in'],
    ['claude', 'https://claude.ai/chat/0b1c', 'in'], ['claude', 'https://claude.ai/recents', 'in'],
    ['claude', 'https://claude.ai/', 'unknown'], ['claude', 'https://claude.ai/cdn-cgi/challenge-platform/x', 'unknown'],
    ['claude', 'https://claude.ai.example.com/new', 'unknown'], ['claude', 'https://example.com/new', 'unknown'],
    ['google', 'https://myaccount.google.com/', 'in'], ['google', 'https://accounts.google.com/v3/signin/identifier?x=1', 'out'],
    ['google', 'https://accounts.google.com/ServiceLogin?service=accountsettings', 'out'],
    ['google', 'https://www.google.com/account/about/', 'out'], ['google', 'https://www.google.com/', 'unknown'],
    ['google', 'https://myaccount.google.com.example.com/', 'unknown'], ['claude', 'not a url', 'unknown'],
    ['google', 'data:text/html,x', 'unknown'], ['other', 'https://claude.ai/new', 'unknown'],
  ];
  for (const [site, url, want] of table) ok(`siteState(${site}, ${url}) = ${want}`, siteState(site, url), want);
  ok('landedAt drops the query and the fragment', landedAt('https://accounts.google.com/v3/signin/identifier?continue=x#y'), 'accounts.google.com/v3/signin/identifier');
  ok('landedAt does not echo a data: URL', landedAt('data:text/html,<p>secret-ish</p>'), 'data:');

  // ── structural: who decides, what is kept, what is wiped ──
  const drv = readFileSync(join(HERE, 'driver.mjs'), 'utf8');
  const cli = readFileSync(join(HERE, 'signin.mjs'), 'utf8');
  const prof = readFileSync(join(HERE, 'profile.mjs'), 'utf8');
  ok('driver.mjs reads no landing URL (it is the hands; profile.mjs + the client decide)', /siteState|SITES/.test(drv), false);
  const siteUrl = /https:\/\/[a-z.]*(claude\.ai|google\.com)/;
  ok('the two sites are named in profile.mjs and nowhere in the client', siteUrl.test(cli), false);
  control('...and profile.mjs really does name them (so the absence above means something)', siteUrl.test(prof), true);
  ok('the "profile in use" string is written once, in profile.mjs', [drv, cli].some(s => /['"`]profile in use/.test(s)), false);
  const rms = [...drv.matchAll(/rmSync\(\s*([^,)]+)/g)].map(m => m[1].trim());
  control('the rmSync scan found the driver\'s deletes', rms.length >= 2, true);
  ok('every rmSync in driver.mjs deletes the RUN DIR and nothing else', rms.every(a => a === 'runDir'), true);
  ok('without --profile the profile is the throwaway inside the run dir', drv.includes("const PROFILE = stored ? stored.dir : join(runDir, 'profile');"), true);
  ok("without --port the browser's arguments are exactly ['--no-sandbox']", drv.includes("const launchArgs = ['--no-sandbox'];") && /args: launchArgs/.test(drv), true);
  const pcStart = cli.indexOf("if (op === 'profiles-check') {");
  // The block ends at the NEXT top-level section header, whatever it is - a fixed
  // end marker swallowed the share block's `pages` call once a section was added
  // between them.
  const pcEnd = cli.indexOf('\n// ── ', pcStart);
  control('the profiles-check block is locatable', pcStart > 0 && pcEnd > pcStart, true);
  const pcOps = [...cli.slice(pcStart, pcEnd).matchAll(/op:\s*'(\w+)'/g)].map(m => m[1]);
  control('...and its commands were found (so the set below is not vacuously small)', pcOps.includes('goto'), true);
  ok('profiles-check sends goto, wait and quit and nothing else - it types and clicks nothing',
     pcOps.every(o => ['goto', 'wait', 'quit'].includes(o)), true);
  const importsOf = src => (src.match(/^[ \t]*import .*from ['"]([^'"]+)['"]/gm) || []).map(l => l.replace(/.*from ['"]([^'"]+)['"].*/, '$1'));
  control('the import scanner resolves a specifier', importsOf(prof).includes('node:fs'), true);
  ok('profile.mjs imports only node: builtins (so half A needs no install)', importsOf(prof).every(m => m.startsWith('node:')), true);

  // ── the driver's refusals, driven through the real client ──
  // Each happens before the browser is needed (--no-xvfb: no display either), must
  // come back FAST with the driver's own reason and exit 2, and must create nothing.
  const refuse = async (what, args, re, cfg = CONFIG) => {
    const rd = join(T, `r-${pass + fail}`);
    const r = await client(['sipt-refuse', 'start', '--config', cfg, '--run-dir', rd, '--log', join(T, 'refuse.log'), '--no-xvfb', ...args]);
    ok(`${what}: exit 2`, r.status, 2);
    ok(`${what}: the driver's reason reaches the caller`, re.test(r.stderr), true);
    ok(`${what}: reported at once, not after the 60 s socket wait`, r.ms < 20000, true);
    ok(`${what}: no run dir was made`, existsSync(rd), false);
  };
  await refuse('--profile ../x', ['--profile', '../x'], /single path segment/);
  await refuse('--profile for an account not in the pool', ['--profile', 'nobody@example.com'], /not a username in the account pool/);
  await refuse('--port without --profile', ['--port', '39999'], /refusing --port without --profile/);
  await refuse('--port out of range', ['--profile', 'alpha@example.com', '--port', '80'], /integer from 1024 to 65535/);
  await refuse('profiles_dir inside a git work tree', ['--profile', 'alpha@example.com'], /git work tree/, writeConfig('cfg-repo.json', { profiles_dir: join(repo, 'profiles') }));
  ok('...and nothing was created there', existsSync(join(repo, 'profiles')), false);
  await refuse('profiles_dir under an agents home', ['--profile', 'alpha@example.com'], /agents home/, writeConfig('cfg-home.json', { profiles_dir: join(AH, 'x', 'profiles') }));
  await refuse(`no ${PROFILES_KEY} in the config`, ['--profile', 'alpha@example.com'], new RegExp(PROFILES_KEY.replace('.', '\\.')), writeConfig('cfg-none.json', {}));
  const bare = await client(['sipt-refuse', 'start', '--config', CONFIG, '--run-dir', join(T, 'r-bare'), '--log', join(T, 'refuse.log'), '--no-xvfb', '--profile']);
  ok('a bare --profile is refused, not quietly run on a throwaway profile', bare.status === 2 && /--profile needs a username/.test(bare.stderr), true);
  ok('none of the refusals created the profiles dir', existsSync(PROFILES), false);

  // `share` on macOS: refused before anything is read, naming the human route.
  const sh = await client(['sipt-share', 'share', '--config', CONFIG, '--run-dir', join(T, 'r-share')]);
  const macText = /not on macOS/.test(sh.stderr) && /step 7e/.test(sh.stderr);
  if (process.platform === 'darwin') ok('share on macOS: exit 2, not on macOS, naming SKILL.md step 7e', `${sh.status}:${macText}`, '2:true');
  else ok('share on Linux fails for its own reason, never with the macOS refusal', `${sh.status !== 0}:${macText}`, 'true:false');

  // ══ HALF B: real browsers ══════════════════════════════════════════════════
  const browsers = process.env.PLAYWRIGHT_BROWSERS_PATH || join(HERE, 'browsers');
  const haveChromium = (() => { try { return readdirSync(browsers).some(d => d.startsWith('chromium-')); } catch { return false; } })();
  const haveModules = existsSync(join(HERE, 'node_modules', 'playwright-extra'));
  const darwin = process.platform === 'darwin';
  const haveDisplay = darwin
    ? spawnSync('/bin/launchctl', ['print', `gui/${process.getuid()}`], { stdio: 'ignore' }).status === 0
    : !!process.env.DISPLAY || spawnSync('sh', ['-c', 'command -v xvfb-run']).status === 0;
  const sockLen = Buffer.byteLength(join(T, 'rb', 'driver.sock'));
  const sockMax = darwin ? 103 : 107;
  const notHere = [!haveModules && 'no node_modules in signin_driver (npm ci there)', !haveChromium && `no chromium under ${browsers}`,
    !haveDisplay && (darwin ? 'no Aqua session (nobody logged in at the console)' : 'no DISPLAY and no xvfb-run'),
    sockLen > sockMax && `TMPDIR is too long for a unix socket (${sockLen} bytes)`].filter(Boolean);
  if (notHere.length) {
    inconclusive.push(`half B did not run: ${notHere.join('; ')}`);
  } else {
    try {
      await halfB(browsers);
      // Positive evidence for the run's own home (childEnv above): on Linux Chromium
      // writes its config under XDG_CONFIG_HOME, so it must have landed in this run's.
      if (process.platform === 'linux') {
        ok("the browsers wrote their config under this run's own XDG_CONFIG_HOME, not the caller's",
          existsSync(join(childEnv.XDG_CONFIG_HOME, 'google-chrome-for-testing')), true);
      }
    } catch (e) {
      console.log(`FAIL - half B threw before it finished: ${String(e && e.stack || e).split('\n').slice(0, 3).join(' | ')}`);
      fail++;
    }
  }
} finally {
  const alive = pid => { try { process.kill(pid, 0); return true; } catch { return false; } };
  for (const pid of started) if (alive(pid)) { try { process.kill(-pid, 'SIGTERM'); } catch {} }
  for (let n = 0; n < 40 && [...started].some(alive); n++) await new Promise(r => setTimeout(r, 250));
  // ⚠️ THE SENTINEL SCAN RUNS OVER EVERYTHING EITHER HALF PRODUCED, including each
  // driver's own log, which is the one stream the redactor never sees.
  for (const f of readdirSync(T)) if (f.endsWith('.log')) transcript.push(readFileSync(join(T, f), 'utf8'));
  const all = transcript.join('\n');
  control('the sentinel scanner finds a planted password (so its silence below means something)', SENTINELS.some(s => `x ${PW_A} y`.includes(s)), true);
  ok('no password from the pool appears on any stdout, stderr or driver log', SENTINELS.some(s => all.includes(s) || all.includes(JSON.stringify(s).slice(1, -1))), false);
  try { rmSync(T, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 }); }
  catch (e) { console.log(`note: could not remove ${T}: ${e.message}`); }
}

async function halfB(browsers) {
  // The tailscale stand-in answers `status --json` for the person's ssh step, so the
  // test reads no real tailnet (share.mjs, tailscaleCommand).
  const env = {
    PLAYWRIGHT_BROWSERS_PATH: browsers, FAKE_TAILSCALE_STATE: join(T, 'ts.json'),
    AGENT_REVIVE_TAILSCALE: JSON.stringify([process.execPath, join(SKILL, 'fixtures', 'fake-tailscale.mjs')]),
  };
  // A server on 127.0.0.1: /set sets a persistent cookie, /show prints the cookie the
  // browser sent, /form is a password field to type into.
  const server = http.createServer((req, res) => {
    if (req.url === '/set') { res.setHeader('Set-Cookie', 'sipt=persisted; max-age=3600; Path=/'); res.end('<p>set</p>'); return; }
    if (req.url === '/show') { res.setHeader('Content-Type', 'text/html'); res.end(`<p>cookie=[${req.headers.cookie || ''}]</p>`); return; }
    res.setHeader('Content-Type', 'text/html');
    res.end('<form><input type="password" id="pw" aria-label="Password"></form>');
  });
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const base = `http://127.0.0.1:${server.address().port}`;
  const freePort = await new Promise(r => { const s = net.createServer().listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => r(p)); }); });
  const run = (agent, rd, args, opts) => client([agent, ...args, '--run-dir', rd, '--log', join(T, `${agent}.log`)], { env, ...opts });
  const quitAndWait = async (agent, rd, pid) => {
    const r = await run(agent, rd, ['quit']);
    const deadline = Date.now() + 20000;
    const alive = () => { try { process.kill(pid, 0); return true; } catch { return false; } };
    while ((alive() || existsSync(rd)) && Date.now() < deadline) await new Promise(res => setTimeout(res, 250));
    return r;
  };
  const showCookie = async (agent, rd) => { await run(agent, rd, ['goto', `${base}/show`]); return (await run(agent, rd, ['inspect'])).json?.result?.text || ''; };
  const typePassword = async (agent, rd) => {
    await run(agent, rd, ['goto', `${base}/form`]);
    const f = await run(agent, rd, ['fill', '--selector', '#pw', '--secret', 'alpha@example.com']);
    ok(`${agent}: fill --secret is answered with the marker, not the value`, f.json?.result?.filled, '[secret]');
    const i = await run(agent, rd, ['inspect']);
    control(`${agent}: inspect of the filled field carries the redaction marker - the password really crossed the wire`, i.stdout.includes('[PW]'), true);
  };
  try {
    // ── the throwaway mode, unchanged ──
    const ra = join(T, 'ra');
    let s = await run('sipt-a', ra, ['start', '--config', CONFIG]);
    ok('throwaway start: exit 0', s.status, 0);
    ok('throwaway start: the reply carries exactly the keys it always has', Object.keys(s.json || {}).join(','), 'ok,started,pid,sock,run_dir,log,xvfb');
    ok('throwaway start: its profile is inside the run dir', existsSync(join(ra, 'profile')), true);
    ok('throwaway start: no profiles dir is made', existsSync(PROFILES), false);
    await run('sipt-a', ra, ['goto', `${base}/set`]);
    await typePassword('sipt-a', ra);
    let q = await quitAndWait('sipt-a', ra, s.json?.pid);
    ok("throwaway quit: the reply carries exactly the keys it always has", Object.keys(q.json?.result || {}).join(','), 'bye,removing');
    ok('throwaway quit: the run dir, profile included, is gone', existsSync(ra), false);
    s = await run('sipt-a', ra, ['start', '--config', CONFIG]);
    ok('throwaway restart: exit 0', s.status, 0);
    control('a throwaway restart does NOT bring the cookie back (so the stored-profile cookie below is the profile, not the server)',
            (await showCookie('sipt-a', ra)).includes('sipt=persisted'), false);
    await quitAndWait('sipt-a', ra, s.json?.pid);

    // ── the stored profile ──
    mkdirSync(PROFILES, { mode: 0o755 });
    chmodSync(PROFILES, 0o755);
    control('the profiles dir starts at 0755 (so the 0700 below is the driver\'s doing)', modeOf(PROFILES), '755');
    const rb = join(T, 'rb');
    s = await run('sipt-b', rb, ['start', '--config', CONFIG, '--profile', 'alpha@example.com', '--port', String(freePort)]);
    ok('stored start: exit 0', s.status, 0);
    const pdir = join(PROFILES, 'alpha@example.com');
    ok('stored start: names the profile dir', s.json?.profile_dir, pdir);
    ok('stored start: says it is kept on quit', s.json?.profile_kept_on_quit, true);
    ok('stored start: the DevTools port answers', s.json?.port_answers, true);
    ok("stored start: the person's ssh step tunnels that port to this login at the TAILSCALE name, which a laptop resolves",
       (s.json?.person_steps || [])[0], `ssh -L ${freePort}:127.0.0.1:${freePort} ${userInfo().username}@sharetest.example-tailnet.invalid`);
    ok('...with no fallback warning', s.json?.ssh_host_warning, undefined);
    ok('stored start: the profiles dir is 0700', modeOf(PROFILES), '700');
    ok('stored start: the profile dir is 0700', modeOf(pdir), '700');
    ok('stored start: there is no profile inside the run dir', existsSync(join(rb, 'profile')), false);
    await run('sipt-b', rb, ['goto', `${base}/set`]);
    await typePassword('sipt-b', rb);

    // a second driver on the same profile
    const rc = join(T, 'rc');
    const busy = await run('sipt-c', rc, ['start', '--config', CONFIG, '--profile', 'alpha@example.com']);
    ok('a second driver on a busy profile: exit 2', busy.status, 2);
    ok('...saying "profile in use"', busy.stderr.includes(PROFILE_IN_USE), true);
    ok('...from the pre-check, before Chromium was reached', /held by a live browser/.test(busy.stderr), true);
    ok('...promptly', busy.ms < 20000, true);
    await new Promise(r => setTimeout(r, 3000));
    ok('...and the first browser gained no window', ((await run('sipt-b', rb, ['pages'])).json?.result || []).length, 1);
    const pcLog = join(T, 'pc-busy.log');
    const pcBusy = await client(['profiles-check', '--config', CONFIG, '--profile', 'alpha@example.com', '--log', pcLog], { env });
    ok('profiles-check on the busy profile: exit 0', pcBusy.status, 0);
    ok('...reports it busy', pcBusy.json?.profiles?.['alpha@example.com']?.status, 'busy');
    ok('...without launching a driver', existsSync(pcLog), false);

    q = await quitAndWait('sipt-b', rb, s.json?.pid);
    ok('stored quit: the reply names the kept profile', q.json?.result?.kept, pdir);
    ok('stored quit: the run dir is gone', existsSync(rb), false);
    ok('stored quit: the profile dir is still there', existsSync(pdir), true);
    control('...and Chromium really used it (it holds Default/)', existsSync(join(pdir, 'Default')), true);
    ok('stored quit: the lock is released', profileInUse(pdir), null);

    s = await run('sipt-b', rb, ['start', '--config', CONFIG, '--profile', 'alpha@example.com']);
    ok('stored restart: exit 0', s.status, 0);
    ok('stored restart: the cookie set before the quit comes back', (await showCookie('sipt-b', rb)).includes('sipt=persisted'), true);
    await quitAndWait('sipt-b', rb, s.json?.pid);

    // A password typed into a stored profile must not be written into it.
    const files = [];
    const walk = d => { for (const e of readdirSync(d, { withFileTypes: true })) { const p = join(d, e.name); if (e.isDirectory()) walk(p); else if (e.isFile()) files.push(p); } };
    walk(pdir);
    const holds = p => { const b = readFileSync(p); return [Buffer.from(PW_A, 'utf8'), Buffer.from(PW_A, 'utf16le')].some(n => b.includes(n)); };
    const planted = join(T, 'planted.bin');
    writeFileSync(planted, Buffer.concat([Buffer.from('xx'), Buffer.from(PW_A, 'utf16le')]));
    control('the profile scanner finds a planted password, UTF-16 included', holds(planted), true);
    control('the profile scan has files to read', files.length > 10, true);
    ok('the typed password is in no file of the stored profile', files.filter(holds).map(f => f.slice(pdir.length)).join(','), '');

    // ── profiles-check, end to end, on data: and 127.0.0.1 only ──
    mkdirSync(join(PROFILES, 'stranger'));
    const pc = await client(['profiles-check', '--config', CONFIG, '--log', join(T, 'pc.log')],
      { env: { ...env, AGENT_REVIVE_PROFILES_CHECK_SITES: JSON.stringify([{ site: 'claude', url: `${base}/show` }]) } });
    const alpha = pc.json?.profiles?.['alpha@example.com'] || {};
    ok('profiles-check: one JSON object on stdout', pc.json !== null, true);
    ok('profiles-check: the stored profile is checked', alpha.status, 'checked');
    ok('profiles-check: a landing it cannot read is unknown, never in', alpha.claude, 'unknown');
    ok('profiles-check: it says where the page landed', alpha.landed?.claude, `${base.slice(7)}/show`);
    ok('profiles-check: a directory that is no pool account is an error', pc.json?.profiles?.stranger?.status, 'error');
    ok('profiles-check: ...which makes the exit 1', pc.status, 1);
    ok('profiles-check: its drivers leave no run dir behind', readdirSync(tmpdir()).some(d => d.startsWith(`agent-revive-signin-profiles-check-${pc.pid}-`)), false);
    ok('profiles-check: the profile is kept', existsSync(join(pdir, 'Default')), true);
    const pcAbsent = await client(['profiles-check', '--config', CONFIG, '--profile', 'beta@example.com', '--log', join(T, 'pc2.log')], { env });
    ok('profiles-check --profile <an account with none>: absent', pcAbsent.json?.profiles?.['beta@example.com']?.status, 'absent');
    ok('...exit 0', pcAbsent.status, 0);
    ok('...and it did not create one', existsSync(join(PROFILES, 'beta@example.com')), false);
  } finally {
    server.close();
  }
}

console.log('');
if (inconclusive.length) {
  console.log(`NO VERDICT - ${inconclusive.join('; ')}`);
  console.log(fail ? `(and ${fail} assertion(s) FAILED above - those are real)` : 'Do NOT read this as a pass.');
  process.exit(fail ? 1 : 3);
}
console.log(`passed ${pass}, failed ${fail}`);
process.exit(fail === 0 ? 0 : 1);
