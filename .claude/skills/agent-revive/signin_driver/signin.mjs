#!/usr/bin/env node
// The client. One command per invocation, one JSON reply printed, then it exits -
// which is the shape an agent drives: look, decide, act, look again.
//
//   node signin.mjs <agent> start [--config P] [--run-dir D] [--log F] [--no-xvfb]
//                                 [--pool-file P] [--profile <username> [--port N]]
//                                 [--app-window]
//   node signin.mjs <agent> pages
//   node signin.mjs <agent> inspect [--page N]
//   node signin.mjs <agent> goto <url> [--page N]
//   node signin.mjs <agent> click --role <role> --name <text> [--page N] [--exact]
//   node signin.mjs <agent> click --text <text> [--page N]
//   node signin.mjs <agent> click --selector <css> [--page N]
//   node signin.mjs <agent> fill --label <text> --value <text> [--page N]
//   node signin.mjs <agent> fill --label <text> --secret <username> [--page N]
//   node signin.mjs <agent> press --key <key> [--page N]
//   node signin.mjs <agent> wait [--ms N] [--page N]
//   node signin.mjs <agent> shot --name <slug>
//   node signin.mjs <agent> savecode
//   node signin.mjs <agent> quit
//   node signin.mjs <agent> share [--minutes N] [--config P]
//   node signin.mjs <agent> unshare [--config P]
//   node signin.mjs profiles-check [--profile <username>] [--config P] [--pool-file P]
//
// The log (--log) defaults to <XDG_STATE_HOME, else ~/.local/state>/agent-revive/,
// a directory of mode 0700, and is always mode 0600: `start` refuses otherwise.
//
// ⚠️ `--profile <username>` OPENS THAT POOL ACCOUNT'S STORED PROFILE, AND `quit` KEEPS
// IT. Without it the profile is a throwaway inside the run dir, wiped on quit. A stored
// profile is a signed-in credential, kept only in accounts.profiles_dir at mode 0700
// (profile.mjs). `--port N` (with --profile) opens DevTools on 127.0.0.1:N for a person
// to enroll it; `start` then prints that person's steps.
//
// ON MACOS the driver draws headful through WindowServer, in the console user's Aqua
// session, so `start` never wraps it in xvfb-run (there is no X server to start), and
// `share` is not available: x11vnc shares only an X11 display, so `share` exits 2
// naming SKILL.md step 7e, the human route (the person signs in in their own
// incognito browser). Everything else is the same on both systems.
//
// ⚠️ `share` MAKES THE DRIVER'S BROWSER PUBLIC, FOR ONE PERSON TO TAP ONE PUZZLE. It
// runs only against a driver started `--app-window` on a virtual display, prints ONE
// JSON object - the public URL, the PATH of the one-time password file (never the
// password) and the expiry - and arms a detached teardown at --minutes (default
// config share.minutes). The person can move the pointer and LEFT-click, nothing
// else (share.mjs). `unshare` tears it all down and is safe to repeat; `quit`, and
// every exit the driver observes, tear it down too.
//
// `profiles-check` reports each stored profile as signed `in`, `out` or `unknown` at
// claude.ai and at Google, or `busy` / `absent`, as ONE JSON object. It launches the
// driver on each profile, visits the two sites and reads where each lands; it types
// nothing and clicks nothing.
//
// ⚠️ `--secret <username>` PASSES A USERNAME, NEVER A PASSWORD. The password is read
// and typed inside the driver process. Nothing that records - a command line, a
// shell history, a tool result, a transcript - ever holds it. There is deliberately
// no way to pass a password through this client, and adding one would defeat the
// entire arrangement.
//
// ⚠️ `savecode` PRINTS A FILE PATH AND A LENGTH, NEVER THE CODE. Paste it with
// `tmux send-keys -l -- "$(cat <file>)"`, which moves the code from the file to the
// pane without it passing through anything that keeps a copy. And paste it AT ONCE:
// a code is worthless within about a minute (SKILL.md step 6).

import net from 'node:net';
import { spawn } from 'node:child_process';
import { existsSync, openSync, closeSync, fchmodSync, mkdirSync, lstatSync, unlinkSync, chmodSync, statSync, readFileSync, readdirSync, writeFileSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { tmpdir, homedir, hostname, userInfo } from 'node:os';
import { randomBytes } from 'node:crypto';
import { PROFILE_IN_USE, SITES, configPathFrom, profilesDirOf, profileNameRefusal, profileInUse, siteState, landedAt, storageRefusal } from './profile.mjs';
import { DISPLAY_FILE, STATE_FILE, PASSWORD_FILE, LOG_FILE, x11vncArgs, websockifyArgs, newPassword, shareConfig, tailscaleCommand, publicHost, funnelServes, funnelOn, virtualDisplayPid, ppidOf, listenerOwners, readJson, writeJson600, stopShare, teardown, setupLock } from './share.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const argv = process.argv.slice(2);
const PROFILES_CHECK = argv[0] === 'profiles-check';
const agent = argv[0];
const op = PROFILES_CHECK ? 'profiles-check' : argv[1];

if (!agent || !op || agent === '--help' || agent === '-h') {
  const src = (await import('node:fs')).readFileSync(fileURLToPath(import.meta.url), 'utf8');
  process.stdout.write(src.split('\n').slice(1).filter(l => l.startsWith('//')).join('\n') + '\n');
  process.exit(agent ? 0 : 2);
}

const flag = name => {
  const i = argv.indexOf(`--${name}`);
  return i >= 0 && argv[i + 1] !== undefined && !argv[i + 1].startsWith('--') ? argv[i + 1] : undefined;
};
const has = name => argv.includes(`--${name}`);
const num = name => (flag(name) === undefined ? undefined : Number(flag(name)));

const runDir = flag('run-dir') || join(tmpdir(), `agent-revive-signin-${agent}`);
const SOCK = join(runDir, 'driver.sock');

// ⚠️ THE DEFAULT LOG LIVES IN A DIRECTORY ONLY THIS USER CAN ENTER, <XDG_STATE_HOME,
// else ~/.local/state>/agent-revive/, mode 0700. The log is the ONE output stream in
// this design that does not go through the driver's redactor (launchDriver), and it
// is permanent. A fixed name in the shared temp directory is a name any other local
// user can create first: as a file of theirs, which this client then cannot narrow
// and they can read, or as a symlink to a file of ours, which this client then
// appends to. log.test.mjs measures the directory, the modes and the refusals.
const LOG_DIR = join(process.env.XDG_STATE_HOME || join(homedir(), '.local', 'state'), 'agent-revive');
const logPath = flag('log') || join(LOG_DIR, `signin-${agent}.log`);
function die(msg, code = 1) { console.error(msg); process.exit(code); }

// The default log directory, created 0700 and refused unless it is a real directory
// this user owns: a symlink planted in its place would send the log elsewhere.
function privateLogDir() {
  try { mkdirSync(LOG_DIR, { recursive: true, mode: 0o700 }); } catch (e) { die(`cannot create the log directory ${LOG_DIR}: ${e.message}`, 1); }
  const st = lstatSync(LOG_DIR);
  if (!st.isDirectory() || st.uid !== process.getuid()) die(`refusing the log directory ${LOG_DIR}: it is not a directory this user owns (a symlink or another user's); nothing was started`, 1);
  try { chmodSync(LOG_DIR, 0o700); } catch (e) { die(`cannot make the log directory ${LOG_DIR} mode 0700: ${e.message}`, 1); }
}

// ── launching a driver, and waiting for it: shared by `start` and `profiles-check` ─
// Returns the child and the log offset this launch's lines start at.
function launchDriver({ agent: a, runDir: rd, log, extra = [] }) {
  if (dirname(log) === LOG_DIR) privateLogDir();
  let fd;
  try { fd = openSync(log, 'a', 0o600); } catch (e) { die(`cannot open the log ${log}: ${e.message}; no driver was started`, 1); }
  // ⚠️ MODE 0600, OR NOTHING STARTS. This file takes the detached process's stdout
  // AND stderr unredacted, lives outside the run dir so `quit` never removes it, and
  // is append-only and permanent. A file whose mode cannot be set (another user's,
  // one this user may write and not chmod) would carry that output at whatever mode
  // it had, so the failure stops the start instead of being ignored.
  try { fchmodSync(fd, 0o600); } catch (e) {
    closeSync(fd);
    die(`cannot make the log ${log} mode 0600 (${e.code || e.message}): it takes the driver's unredacted output, so no driver was started; pass --log <a file of yours>, or leave --log out for the private default`, 1);
  }
  const offset = statSync(log).size;
  const args = [join(HERE, 'driver.mjs'), '--agent', a, '--run-dir', rd];
  if (flag('config')) args.push('--config', flag('config'));
  if (flag('pool-file')) args.push('--pool-file', flag('pool-file'));
  args.push(...extra);
  // xvfb-run supplies the virtual display a headful browser needs on a Linux host with
  // no X session. `--no-xvfb` is for a host that already has a real DISPLAY. macOS has
  // no X server to start: Chromium draws through WindowServer.
  const useXvfb = process.platform !== 'darwin' && !has('no-xvfb') && !process.env.DISPLAY;
  const cmd = useXvfb ? 'xvfb-run' : process.execPath;
  const cmdArgs = useXvfb ? ['-a', process.execPath, ...args] : args;
  // ⚠️ THE CHILD'S ENVIRONMENT IS SCRUBBED OF THE DEBUG SWITCHES, NOT INHERITED
  // WHOLESALE. `DEBUG=pw:api` in whatever shell launched this makes Playwright log
  // every call's ARGUMENTS - including the password `fill --secret` types - into that
  // append-only log. The driver's own careful redaction is irrelevant to a library
  // writing straight to stderr, and nobody would connect the two.
  const childEnv = { ...process.env };
  for (const k of ['DEBUG', 'DEBUG_COLORS', 'NODE_DEBUG', 'PWDEBUG', 'PLAYWRIGHT_DEBUG']) delete childEnv[k];
  const child = spawn(cmd, cmdArgs, { detached: true, stdio: ['ignore', fd, fd], env: childEnv });
  child.unref();
  return { child, offset, xvfb: useXvfb };
}

// ⚠️ IT WAITS FOR THE SOCKET OR FOR THE DRIVER'S EXIT, WHICHEVER COMES FIRST. A
// driver that refuses (a bad name, an unknown account, a profile in use, no
// chromium) exits within a second; a wait on the socket alone reports that refusal
// 60 s later as "did not start", with the reason sitting unread in the log. The
// refusal's own lines are printed instead, and its exit code (2) is passed on.
function waitForSocket(sock, child, ms) {
  return new Promise(res => {
    let exited = null;
    child.once('exit', (code, signal) => { exited = { code, signal }; });
    const deadline = Date.now() + ms;
    const tick = () => {
      if (existsSync(sock)) return res({ ok: true });
      if (exited) return res({ ok: false, ...exited });
      if (Date.now() >= deadline) return res({ ok: false, timeout: true });
      setTimeout(tick, 500);
    };
    tick();
  });
}

// The lines THIS launch wrote to the shared, append-only log.
const logSince = (log, offset) => { try { return readFileSync(log).subarray(offset).toString('utf8').trim(); } catch { return ''; } };

// Whether a driver answers on `sock` - a socket FILE is not a living driver.
function sockAlive(sock) {
  return new Promise(res => {
    const probe = net.createConnection(sock);
    probe.on('connect', () => { probe.end(); res(true); });
    probe.on('error', () => res(false));
    setTimeout(() => { try { probe.destroy(); } catch {} res(false); }, 2000);
  });
}

// One JSON command to a driver, one parsed reply back.
function send(sock, cmd) {
  return new Promise((res, rej) => {
    const s = net.createConnection(sock);
    let buf = '';
    s.on('connect', () => s.write(JSON.stringify(cmd) + '\n'));
    s.on('data', d => {
      buf += d;
      if (!buf.includes('\n')) return;
      s.end();
      const line = buf.split('\n')[0];
      try { res(JSON.parse(line)); } catch { res({ ok: false, error: 'unparseable reply', raw: line }); }
    });
    s.on('error', rej);
  });
}

// ── start: launch the driver detached, then wait for its socket ──────────────
// ⚠️ IT WAITS FOR THE SOCKET RATHER THAN FOR A TIMER, and reports a launch failure
// as one. A backgrounded process that never started is indistinguishable from a
// slow one, and "the browser is still coming up" is the comfortable reading of
// both; the driver's log is the evidence, so its path is printed either way.
if (op === 'start') {
  // ⚠️ A SOCKET FILE IS NOT A LIVING DRIVER, AND TREATING IT AS ONE DEADLOCKS THE
  // OPERATOR AT THE WORST MOMENT. A SIGKILL or a crash leaves the socket behind;
  // `start` then refused ("already listening") while `quit` failed with
  // ECONNREFUSED, so neither command worked and the remedy was in neither message -
  // and this lands AFTER `/login` has been typed into a live agent's pane, where only
  // a code finishes the revival. So probe it: if nothing answers, the file is a
  // corpse and is removed.
  if (existsSync(SOCK)) {
    const alive = await sockAlive(SOCK);
    if (alive) die(`a driver is already listening on ${SOCK} - 'quit' it first, or pass a different --run-dir`, 1);
    console.error(`removing a stale socket at ${SOCK} (nothing answered it)`);
    try { unlinkSync(SOCK); } catch (e) { die(`could not remove the stale socket ${SOCK}: ${e.message}`, 1); }
  }
  const log = logPath;
  const profile = flag('profile');
  const port = flag('port');
  // A bare `--profile` would otherwise start a THROWAWAY browser without a word, and
  // the caller would believe it was on the stored one.
  if (has('profile') && profile === undefined) die('start: --profile needs a username', 2);
  if (has('port') && port === undefined) die('start: --port needs a number', 2);
  const extra = [];
  if (profile !== undefined) extra.push('--profile', profile);
  if (port !== undefined) extra.push('--port', port);
  if (has('app-window')) extra.push('--app-window');
  const { child, offset, xvfb } = launchDriver({ agent, runDir, log, extra });
  const w = await waitForSocket(SOCK, child, 60000);
  if (w.ok) {
    const out = { ok: true, started: true, pid: child.pid, sock: SOCK, run_dir: runDir, log, xvfb };
    if (has('app-window')) out.app_window = true;
    if (profile !== undefined) {
      const configPath = configPathFrom(flag('config'));
      out.profile = profile;
      out.profile_dir = join(profilesDirOf(JSON.parse(readFileSync(configPath, 'utf8')), configPath), profile);
      out.profile_kept_on_quit = true;
    }
    if (port !== undefined) {
      // Positive evidence the port is up, rather than the flag having been passed:
      // Chromium that cannot bind its DevTools port says so in its log and carries
      // on, and the person on the other end of the tunnel then sees nothing at all.
      out.port = Number(port);
      out.port_answers = await fetch(`http://127.0.0.1:${port}/json/version`, { signal: AbortSignal.timeout(5000) }).then(r => r.ok, () => false);
      // ⚠️ THE TAILSCALE NAME, NOT hostname(): a laptop resolves this host only by its
      // tailnet DNS name, and a bare hostname in the first step fails before the
      // person reaches anything. The login is the account running this driver.
      let sshHost;
      try { sshHost = publicHost(tailscaleCommand(JSON.parse(readFileSync(configPathFrom(flag('config')), 'utf8')))); }
      catch (e) { sshHost = hostname(); out.ssh_host_warning = `the Tailscale name could not be read (${e.message}); ${sshHost} resolves only on this host's own network`; }
      out.person_steps = [
        `ssh -L ${port}:127.0.0.1:${port} ${userInfo().username}@${sshHost}`,
        `in desktop Chrome open chrome://inspect -> Configure... -> add localhost:${port}`,
        'click "inspect" under the page target: the sign-in runs in that screencast - the agent types the account and its password, you clear what it cannot (a CAPTCHA, a device prompt)',
        'the Google sign-in opens as a POPUP, its own target in chrome://inspect - inspect it too',
      ];
    }
    console.log(JSON.stringify(out, null, 1));
    process.exit(0);
  }
  if (!w.timeout) {
    const why = w.code === null ? `was killed by ${w.signal}` : `exited ${w.code}`;
    die(`driver ${why} before creating ${SOCK}:\n${logSince(log, offset) || '(it wrote nothing)'}\n(log: ${log})`, w.code || 1);
  }
  die(`driver did not create ${SOCK} within 60s - read ${log} (it is the evidence; an absent socket is a launch failure, not earliness)`, 1);
}

// ── profiles-check: is each stored profile still signed in? ──────────────────
// ⚠️ IT READS, AND IT NEVER SIGNS ANYTHING IN. It sends the driver `goto`, `wait` and
// `quit` and no other command - no fill, no click, no key - so a profile that has
// expired is reported, never repaired: a refresh is enrollment, with a person in
// reach (SKILL.md, "Stored profiles"). profiles.test.mjs pins that command set.
// The reading of a landing URL lives in profile.mjs (`siteState`), not in the driver:
// deciding what a page means is procedure, and the driver is the hands.
//
// ⚠️ A PROFILE THAT DOES NOT EXIST IS REPORTED `absent` AND NEVER LAUNCHED: the driver
// creates a missing profile dir, so launching it would turn a read into a write.
// A profile another browser holds is `busy`, also without a launch (profile.mjs,
// profileInUse: a losing launch opens a window in the winner).
//
// AGENT_REVIVE_PROFILES_CHECK_SITES (a JSON list of {site, url}) replaces the two
// sites; it exists so profiles.test.mjs drives the whole loop against data: URLs and
// never reaches a real site.
if (op === 'profiles-check') {
  let configPath, cfg, profilesDir;
  try {
    configPath = configPathFrom(flag('config'));
    cfg = JSON.parse(readFileSync(configPath, 'utf8'));
    profilesDir = profilesDirOf(cfg, configPath);
  } catch (e) { die(`profiles-check: ${e.message}`, 2); }
  const refusal = storageRefusal(profilesDir, { agentsHome: cfg?.fleet?.agents_home });
  if (refusal) die(`profiles-check: ${refusal}`, 2);
  const one = flag('profile');
  if (has('profile') && one === undefined) die('profiles-check: --profile needs a username', 2);
  if (one !== undefined) { const bad = profileNameRefusal(one); if (bad) die(`profiles-check: ${bad}`, 2); }
  const sites = process.env.AGENT_REVIVE_PROFILES_CHECK_SITES ? JSON.parse(process.env.AGENT_REVIVE_PROFILES_CHECK_SITES) : SITES;
  const names = one !== undefined ? [one]
    : existsSync(profilesDir) ? readdirSync(profilesDir, { withFileTypes: true }).filter(d => d.isDirectory()).map(d => d.name).sort() : [];
  const log = flag('log') || join(LOG_DIR, 'signin-profiles-check.log');
  const report = { ok: true, profiles_dir: profilesDir, profiles: {} };
  for (const [i, name] of names.entries()) report.profiles[name] = await checkProfile(name, i);
  report.ok = Object.values(report.profiles).every(p => p.status !== 'error');
  console.log(JSON.stringify(report, null, 1));
  process.exit(report.ok ? 0 : 1);

  async function checkProfile(name, i) {
    const dir = join(profilesDir, name);
    if (!existsSync(dir)) return { status: 'absent' };
    const busy = profileInUse(dir);
    if (busy) return { status: 'busy', detail: busy };
    const a = `profiles-check-${process.pid}-${i}`;
    const rd = join(tmpdir(), `agent-revive-signin-${a}`);
    const sock = join(rd, 'driver.sock');
    const { child, offset } = launchDriver({ agent: a, runDir: rd, log, extra: ['--profile', name] });
    const w = await waitForSocket(sock, child, 60000);
    if (!w.ok) {
      // A driver still starting after 60 s would go on to hold the profile with nobody
      // to quit it; its whole process group is signalled, and its cleanup runs.
      if (w.timeout) { try { process.kill(-child.pid, 'SIGTERM'); } catch {} }
      const said = logSince(log, offset);
      if (said.includes(PROFILE_IN_USE)) return { status: 'busy', detail: said.split('\n').find(l => l.includes(PROFILE_IN_USE)) };
      return { status: 'error', error: w.timeout ? 'the driver did not start within 60s' : `the driver exited ${w.code ?? w.signal}`, driver_said: said.split('\n').slice(-5), log };
    }
    const out = { status: 'checked' };
    const landed = {};
    try {
      for (const { site, url } of sites) {
        let r = await send(sock, { op: 'goto', url, settle: 3000 });
        let at = r.ok ? r.result.url : null;
        let state = at ? siteState(site, at) : 'unknown';
        // A redirect made by the page's own script lands after domcontentloaded, so
        // `unknown` is re-read a few times before it is reported.
        for (let n = 0; state === 'unknown' && at && n < 5; n++) {
          r = await send(sock, { op: 'wait', ms: 2000 });
          if (r.ok) { at = r.result.url; state = siteState(site, at); }
        }
        out[site] = state;
        landed[site] = at ? landedAt(at) : `no page: ${r.error || 'no reply'}`;
      }
    } catch (e) {
      out.status = 'error';
      out.error = `lost the driver mid-check: ${e.message}`;
    } finally {
      await send(sock, { op: 'quit' }).catch(() => {});
      if (child.exitCode === null && child.signalCode === null) await new Promise(r => { child.once('exit', r); setTimeout(r, 20000); });
    }
    out.landed = landed;
    return out;
  }
}

// ── share / unshare: show the driver's browser to ONE person, then take it back ─
// ⚠️ ORDER IS LOAD-BEARING. The host-wide setup lock (share.mjs, setupLock) is taken
// before the port checks, so no two run dirs' shares are set up at once. The record
// is created EXCLUSIVELY next (it is the run dir's lock: a second `share` of this run
// dir fails on it), the expiry timer is armed next, the record is rewritten before
// each process and before the funnel, and the funnel - the step that makes anything
// public - is last, marked `requested` before it is asked for. So a share that fails
// half-way, or whose client is killed half-way, is torn down by the same teardown
// every other path uses, and still has its timer. Every readiness check asks whether
// THIS share's process holds the listener on 127.0.0.1 (share.mjs, listenerOwners),
// never only whether something answers on the port. Nothing prints the password: the
// JSON names its FILE, and the reader of that file is the process that posts it
// (SKILL.md step 7b).
if (op === 'share' && process.platform === 'darwin') {
  die('share: not on macOS - the tap-to-solve share needs an X11 display (x11vnc), and macOS draws through WindowServer. Use SKILL.md step 7e, the human route: the person signs in with the chosen pool account in their own incognito browser', 2);
}
if (op === 'share' || op === 'unshare') {
  const configFlag = flag('config');
  let cfg = null, cfgErr = null;
  try { cfg = JSON.parse(readFileSync(configPathFrom(configFlag), 'utf8')); } catch (e) { cfgErr = e.message; }
  const portAnswers = p => new Promise(res => {
    const c = net.createConnection(p, '127.0.0.1');
    c.on('connect', () => { c.destroy(); res(true); });
    c.on('error', () => res(false));
    setTimeout(() => { c.destroy(); res(false); }, 1000);
  });
  // Polls `ok` until it holds, the process it waits on exits, or the deadline.
  const waitFor = async (ok, ms, child) => {
    for (const end = Date.now() + ms; Date.now() < end; await new Promise(r => setTimeout(r, 250))) {
      if (child && (child.exitCode !== null || child.signalCode !== null)) return false;
      if (await ok()) return true;
    }
    return false;
  };

  if (op === 'unshare') {
    // --after/--share-id are the expiry timer's: it sleeps, then tears down only the
    // share it was armed for, never kills itself, and retries a teardown that could
    // not finish - it is the last thing still holding that share's record.
    const after = num('after');
    const onlyId = flag('share-id');
    if (after !== undefined) await new Promise(r => setTimeout(r, after));
    let r = stopShare(runDir, { cfg, onlyId, killTimer: after === undefined });
    for (let n = 0; after !== undefined && r.torn && !r.clean && n < 3; n++) {
      await new Promise(res => setTimeout(res, 20000));
      r = stopShare(runDir, { cfg, onlyId, killTimer: false });
    }
    const out = { ok: r.refused ? false : r.torn ? r.clean : true, unshared: r.torn, ...r };
    if (r.torn && !r.clean) out.remedy = `the record is kept in ${join(runDir, STATE_FILE)}; fix what is named above and run unshare again`;
    // Nothing recorded HERE, yet the funnel port serves: another run dir's share, or
    // one whose record was removed by hand. Said loudly, and not acted on - turning it
    // off would end another agent's share with nothing to tell it why.
    if (!r.torn && !onlyId && cfg) {
      try {
        const fp = shareConfig(cfg).funnel_port;
        if (funnelServes(tailscaleCommand(cfg), fp)) {
          out.ok = false;
          out.funnel_still_serves = fp;
          out.remedy = `unshare the agent whose share this is, or: ${tailscaleCommand(cfg).join(' ')} funnel --https=${fp} off`;
        }
      } catch (e) { out.funnel_check_error = e.message; }
    }
    console.log(JSON.stringify(out, null, 1));
    process.exit(out.ok ? 0 : 1);
  }

  if (cfgErr) die(`share: cannot read config: ${cfgErr}`, 2);
  let sc, cmd;
  try { sc = shareConfig(cfg); cmd = tailscaleCommand(cfg); } catch (e) { die(`share: ${e.message}`, 2); }
  if (has('minutes') && flag('minutes') === undefined) die('share: --minutes needs a number', 2);
  const minutes = Number(flag('minutes') ?? sc.minutes);
  if (!(minutes > 0 && minutes <= 60)) die(`share: --minutes must be above 0 and at most 60, not ${flag('minutes') ?? sc.minutes}`, 2);

  // ── what is shared must be exactly this driver's one app window ──
  if (!existsSync(SOCK) || !(await sockAlive(SOCK))) die(`share: no live driver on ${SOCK} - start one with --app-window first`, 1);
  const disp = readJson(join(runDir, DISPLAY_FILE));
  if (!disp?.app_window) die('share: refusing - this driver was not started with --app-window, so its window carries an address bar. quit it and start again with --app-window', 2);
  if (!disp.display || !disp.xauthority) die(`share: refusing - the driver recorded no DISPLAY and XAUTHORITY (${disp.display}, ${disp.xauthority})`, 2);
  // A share shows the WHOLE display. Only the Xvfb that the driver's own xvfb-run
  // started holds nothing but this browser: not a desktop's display (a driver started
  // --no-xvfb), and not another agent's Xvfb that took the same display number.
  const xvfb = virtualDisplayPid(disp.display);
  if (!xvfb || ppidOf(xvfb) !== disp.parent) die(`share: refusing - ${disp.display} is not an Xvfb started by this driver's own xvfb-run, and a share shows the WHOLE display`, 2);
  if (existsSync(join(runDir, STATE_FILE))) die(`share: this driver is already shared (${join(runDir, STATE_FILE)}) - unshare first`, 1);
  const open = ((await send(SOCK, { op: 'pages' }).catch(() => null))?.result || []).filter(p => !p.closed);
  if (open.length !== 1) die(`share: refusing - ${open.length} windows are open (${open.map(p => p.url).join(', ')}); a share starts from the single app window, and any other window may carry an address bar`, 2);
  // Held from the port checks until this process exits (share.mjs, setupLock).
  const lock = net.createServer();
  const locked = await new Promise(res => { lock.once('error', e => res(e.code || e.message)); lock.listen({ path: setupLock(sc.vnc_port) }, () => res(true)); });
  if (locked !== true) die(locked === 'EADDRINUSE' ? `share: another share on 127.0.0.1:${sc.vnc_port} is being set up on this host - try again once it has finished` : `share: cannot take the setup lock: ${locked}`, 1);
  lock.unref();
  for (const p of [sc.vnc_port, sc.web_port]) if (await portAnswers(p)) die(`share: 127.0.0.1:${p} is already in use - is another share live? unshare it first`, 1);
  let host;
  try {
    if (funnelServes(cmd, sc.funnel_port)) die(`share: the funnel already serves port ${sc.funnel_port} - another share is live; unshare it first`, 1);
    host = publicHost(cmd);
  } catch (e) { die(`share: tailscale: ${e.message}`, 1); }

  // ── build it ──
  const id = randomBytes(6).toString('hex');
  const statePath = join(runDir, STATE_FILE);
  const state = { id, vnc_port: sc.vnc_port, web_port: sc.web_port, funnel_port: sc.funnel_port, display: disp.display, pids: {} };
  try { writeJson600(statePath, state, { exclusive: true }); }
  catch (e) { die(e.code === 'EEXIST' ? `share: this driver is already shared (${statePath}) - unshare first` : `share: cannot write ${statePath}: ${e.message}`, 1); }
  const shareLog = join(runDir, LOG_FILE);
  const pwFile = join(runDir, PASSWORD_FILE);
  // A teardown from the record IN MEMORY: the file may already be gone (a concurrent
  // teardown, or a driver that wiped its run dir), and what this client started must
  // go with it either way.
  const fail = msg => {
    const t = teardown(state, { runDir, cmd });
    if (t.clean) { if (readJson(statePath)?.id === id) rmSync(statePath, { force: true }); }
    else { try { writeJson600(statePath, state); } catch {} }
    die(`share: ${msg} - torn down: ${JSON.stringify(t)} (log: ${shareLog})`, 1);
  };
  // Rewrites the record only while it is still THIS share's: a teardown that removed
  // it mid-setup is not undone by the next save.
  const save = () => { if (readJson(statePath)?.id !== id) throw new Error('the share record was removed while the share was being set up - a teardown ran'); writeJson600(statePath, state); };
  try {
    writeFileSync(pwFile, newPassword() + '\n', { mode: 0o600 });
    chmodSync(pwFile, 0o600);
    const fd = openSync(shareLog, 'a');
    chmodSync(shareLog, 0o600);
    const launch = (bin, args) => { const c = spawn(bin, args, { detached: true, stdio: ['ignore', fd, fd] }); c.on('error', () => {}); c.unref(); return c; };
    const expires = new Date(Date.now() + minutes * 60000).toISOString();
    const timer = launch(process.execPath, [fileURLToPath(import.meta.url), agent, 'unshare', '--run-dir', runDir,
      '--share-id', id, '--after', String(Math.round(minutes * 60000)), ...(configFlag ? ['--config', configFlag] : [])]);
    state.pids.timer = timer.pid; state.expires_at = expires; save();

    const vnc = launch('x11vnc', x11vncArgs({ display: disp.display, xauthority: disp.xauthority, vncPort: sc.vnc_port, passwordFile: pwFile }));
    state.pids.x11vnc = vnc.pid; save();
    if (!vnc.pid) fail('x11vnc could not be run - is it installed? (installation/check)');
    if (!(await waitFor(() => listenerOwners(sc.vnc_port).includes(vnc.pid), 15000, vnc))) fail(`x11vnc did not take 127.0.0.1:${sc.vnc_port}`);
    const ws = launch('websockify', websockifyArgs({ webPort: sc.web_port, vncPort: sc.vnc_port, novncDir: sc.novnc_dir }));
    state.pids.websockify = ws.pid; save();
    if (!ws.pid) fail('websockify could not be run - is it installed? (installation/check)');
    const page = String(sc.page).replace(/^\//, '');
    const pageServed = async () => listenerOwners(sc.web_port).includes(ws.pid)
      && fetch(`http://127.0.0.1:${sc.web_port}/${page}`, { signal: AbortSignal.timeout(2000) }).then(r => r.ok, () => false);
    if (!(await waitFor(pageServed, 15000, ws))) fail(`websockify did not serve ${page} from ${sc.novnc_dir} on 127.0.0.1:${sc.web_port}`);

    state.funnel = 'requested'; save();
    const on = funnelOn(cmd, sc.funnel_port, sc.web_port);
    if (on.status !== 0 || !funnelServes(cmd, sc.funnel_port)) fail(`the funnel did not come up (exit ${on.status}: ${String(on.stderr || '').trim().split('\n')[0]})`);
    state.funnel = 'on'; save();
    console.log(JSON.stringify({
      ok: true, shared: true, url: `https://${host}:${sc.funnel_port}/${page}`, password_file: pwFile, expires_at: expires, minutes,
      input: 'pointer and LEFT button only (a left-drag included): no right, middle, wheel or side button, no keyboard, no clipboard; one viewer at a time',
    }, null, 1));
    process.exit(0);
  } catch (e) { fail(e.message); }
}

// ── every other command: one JSON line to the driver, one reply back ─────────
const cmd = { op };
if (op === 'goto') { cmd.url = argv[2]; if (!cmd.url || cmd.url.startsWith('--')) die('goto needs a url', 2); }
if (flag('page') !== undefined) cmd.page = num('page');
if (flag('role')) cmd.role = flag('role');
if (flag('name')) cmd.name = flag('name');
if (flag('text')) cmd.text = flag('text');
if (flag('selector')) cmd.selector = flag('selector');
if (flag('label')) cmd.label = flag('label');
if (flag('value') !== undefined) cmd.value = flag('value');
if (flag('secret')) cmd.secret = flag('secret');
if (flag('key')) cmd.key = flag('key');
if (num('ms') !== undefined) cmd.ms = num('ms');
if (num('settle') !== undefined) cmd.settle = num('settle');
if (num('timeout') !== undefined) cmd.timeout = num('timeout');
if (has('exact')) cmd.exact = true;
if (op === 'shot') cmd.name = flag('name') || 'shot';

if (!existsSync(SOCK)) die(`no driver socket at ${SOCK} - run: node signin.mjs ${agent} start`, 1);

let parsed;
try { parsed = await send(SOCK, cmd); } catch (e) {
  die(`socket error: ${e.message} (is the driver still alive? its log is ${logPath}). If it died, 'start' again - it removes a stale socket by itself.`, 1);
}
if (parsed.raw !== undefined) { console.log(parsed.raw); process.exit(1); }
console.log(JSON.stringify(parsed, null, 1));
process.exit(parsed.ok ? 0 : 1);
