#!/usr/bin/env node
// Guard on the tap-to-solve share (`signin.mjs share` / `unshare`, share.mjs, the
// driver's `--app-window`). Fake pool, fake config, a FAKE tailscale; the only pages
// loaded are data: URLs. Nothing this file runs can make anything public.
//
//   node share.test.mjs
//
// ── TWO HALVES ───────────────────────────────────────────────────────────────
//   A  the input restriction, on a throwaway Xvfb: x11vnc with share.mjs's own
//      arguments, a minimal RFB client written below, and `xinput test-xi2 --root`
//      reading every raw event that reaches the X server - buttons 1 to 8, a chord, a
//      drag, keys, clipboard both ways, an outside `x11vnc -R` trying to widen the
//      input, and a second viewer. Needs xvfb-run, x11vnc, xinput, xprop and stdbuf -
//      no browser.
//   B  the lifecycle, on real drivers: the refusals (no --app-window, two windows, a
//      display not the driver's own), the app window, share, a second share refused,
//      unshare (twice), the expiry timer, a funnel that fails to come up, a funnel that
//      fails to go DOWN (record and timer kept, start refusing), the host-wide setup
//      lock, an x11vnc that can take only ::1, two shares racing, teardown on quit, on
//      SIGTERM, and by the next `start` after a SIGKILL - and the password on no
//      output. Needs signin_driver's node_modules, a chromium build, xvfb-run, x11vnc,
//      websockify and python3.
//
// ── EXIT CODES: THREE, NEVER TWO ─────────────────────────────────────────────
//   0  PASS        every property holds, in BOTH halves
//   1  FAIL        at least one property is broken - each one is named
//   3  NO VERDICT  a control misbehaved, or a half could not run on this host.
//                  ⚠️ Not a smaller pass: every property here is an ABSENCE (no
//                  right-click arrived, no process is left, nothing is public), and
//                  an absence is exactly what a run that never reached its subject
//                  produces.
//
// ── WHY THE CONTROLS ARE LOAD-BEARING ────────────────────────────────────────
//   - "no right-click arrived" is read off an observer that a CONTROL x11vnc - the
//     same arguments minus share.mjs's INPUT_FLAGS - must first show delivering a
//     right, middle, wheel and side click, two keys and a clipboard in each direction.
//     An observer that cannot see those events would otherwise pass every restriction.
//     The remote-control route has its own control: the restriction minus -safer,
//     where an outside `x11vnc -R input:KMBC` must let keys through.
//   - a teardown that must NOT finish is driven by a stand-in that refuses the funnel
//     off, and the funnel is shown still on before "the record was kept" is believed.
//   - the restricted run must show the LEFT click and a left-drag arriving, or it
//     proves only that nothing arrived at all (a dead session, a wrong display).
//   - the tailscale stand-in records every call, and a tripwire `sudo`/`tailscale`
//     first on PATH records any call that bypassed it: the funnel assertions are read
//     from the one, and the other must stay empty.
//   - the password is asserted absent from every output only beside a scanner shown
//     to find a planted copy.
// Delete a control and the assertion beside it can no longer fail.

import { readFileSync, writeFileSync, mkdirSync, mkdtempSync, rmSync, existsSync, statSync, readdirSync, chmodSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { tmpdir, homedir } from 'node:os';
import { spawn, spawnSync } from 'node:child_process';
import net from 'node:net';
import crypto from 'node:crypto';
import { INPUT_FLAGS, x11vncArgs, listenerOwners, setupLock, STATE_FILE, PASSWORD_FILE, LOG_FILE } from './share.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const SKILL = dirname(HERE);
const CLIENT = join(HERE, 'signin.mjs');

// VNC authentication is DES. Node 17+ carries it only in OpenSSL's legacy provider,
// so the test re-runs itself with that provider rather than shipping its own DES.
const desWorks = () => { try { crypto.createCipheriv('des-ecb', Buffer.alloc(8), null); return true; } catch { return false; } };
if (!desWorks() && !process.execArgv.includes('--openssl-legacy-provider')) {
  const r = spawnSync(process.execPath, ['--openssl-legacy-provider', fileURLToPath(import.meta.url), ...process.argv.slice(2)], { stdio: 'inherit' });
  process.exit(r.status ?? 3);
}

let pass = 0, fail = 0;
const inconclusive = [];
const ok = (what, got, want) => {
  if (got === want) { console.log(`ok   - ${what}`); pass++; }
  else { console.log(`FAIL - ${what}: expected ${JSON.stringify(want)}, got ${JSON.stringify(got)}`); fail++; }
};
const control = (what, got, want) => {
  if (got === want) { console.log(`ok   - control: ${what}`); pass++; return true; }
  console.log(`CONTROL BROKEN - ${what}: expected ${JSON.stringify(want)}, got ${JSON.stringify(got)}`); inconclusive.push(what); return false;
};
const sleep = ms => new Promise(r => setTimeout(r, ms));
const has = bin => spawnSync('sh', ['-c', `command -v ${bin}`]).status === 0;
const cmdline = pid => { try { return readFileSync(`/proc/${pid}/cmdline`, 'utf8').split('\0').filter(Boolean); } catch { return []; } };
const alive = pid => !!pid && cmdline(pid).length > 0;
const modeOf = p => (statSync(p).mode & 0o777).toString(8);
const freePort = () => new Promise(r => { const s = net.createServer().listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => r(p)); }); });
const until = async (cond, ms) => { for (const end = Date.now() + ms; Date.now() < end; await sleep(250)) if (await cond()) return true; return !!(await cond()); };
// Whether any process is left in process group `pgid` - its leader may be gone while
// a member (an Xvfb whose xvfb-run was killed) lives on.
const groupMembers = pgid => readdirSync('/proc').filter(d => /^\d+$/.test(d)).filter(d => {
  try { const st = readFileSync(`/proc/${d}/stat`, 'utf8'); return Number(st.slice(st.lastIndexOf(')') + 2).split(' ')[2]) === pgid && cmdline(d).length > 0; } catch { return false; }
});
const groupAlive = pgid => groupMembers(pgid).length > 0;
// The final sweep signals a recorded group only while a member is still one of this
// test's (xvfb-run, Xvfb, or this skill's driver) - never a group whose number the
// kernel has since handed to something else.
const groupIsOurs = pgid => groupMembers(pgid).some(d => /xvfb-run|Xvfb|signin_driver/.test(cmdline(d).join(' ')));
const killGroup = async (pid, ms = 5000) => {
  if (!pid) return;
  for (const sig of ['SIGTERM', 'SIGKILL']) {
    try { process.kill(-pid, sig); } catch { try { process.kill(pid, sig); } catch {} }
    if (await until(() => !alive(pid) && !groupAlive(pid), ms)) return;
  }
};

// Every LISTEN socket on `port`, from /proc/net/tcp{,6}, as [address, isLoopback].
function listeners(port) {
  const hexPort = port.toString(16).toUpperCase().padStart(4, '0');
  const out = [];
  for (const f of ['/proc/net/tcp', '/proc/net/tcp6']) {
    let lines = [];
    try { lines = readFileSync(f, 'utf8').trim().split('\n').slice(1); } catch {}
    for (const l of lines) {
      const [, local, , st] = l.trim().split(/\s+/);
      const [addr, p] = local.split(':');
      if (st !== '0A' || p !== hexPort) continue;
      out.push([addr, addr === '0100007F' || addr === '00000000000000000000000001000000']);
    }
  }
  return out;
}

// ── a minimal RFB 3.8 client: VNC authentication, then raw client messages ───
function rfb(port, password) {
  return new Promise(resolve => {
    const s = net.createConnection(port, '127.0.0.1');
    let buf = Buffer.alloc(0), after = Buffer.alloc(0), ready = false, closed = false;
    s.on('close', () => { closed = true; });
    const waiters = [];
    const pump = () => { while (waiters.length && buf.length >= waiters[0].n) { const w = waiters.shift(); const b = buf.subarray(0, w.n); buf = buf.subarray(w.n); w.res(b); } };
    s.on('data', d => { if (ready) after = Buffer.concat([after, d]); else { buf = Buffer.concat([buf, d]); pump(); } });
    s.on('error', e => resolve({ authOk: false, reason: `socket: ${e.message}` }));
    const read = n => new Promise(res => { waiters.push({ n, res }); pump(); });
    const rev = b => { let r = 0; for (let i = 0; i < 8; i++) if (b & (1 << i)) r |= 1 << (7 - i); return r; };
    (async () => {
      await read(12);
      s.write('RFB 003.008\n');
      const types = [...await read((await read(1))[0])];
      if (!types.includes(2)) return resolve({ authOk: false, reason: `no VNC auth offered: ${types}` });
      s.write(Buffer.from([2]));
      const challenge = await read(16);
      const key = Buffer.alloc(8);
      Buffer.from(password).copy(key, 0, 0, 8);
      for (let i = 0; i < 8; i++) key[i] = rev(key[i]);
      const c = crypto.createCipheriv('des-ecb', key, null);
      c.setAutoPadding(false);
      s.write(Buffer.concat([c.update(challenge), c.final()]));
      if ((await read(4)).readUInt32BE(0) !== 0) {
        const n = (await read(4)).readUInt32BE(0);
        const reason = (await read(n)).toString();
        s.destroy();
        return resolve({ authOk: false, reason });
      }
      s.write(Buffer.from([1]));
      const init = await read(24);
      await read(init.readUInt32BE(20));
      ready = true;
      after = Buffer.concat([after, buf]);
      const msg = (...parts) => s.write(Buffer.concat(parts));
      resolve({
        authOk: true,
        pointer: (mask, x, y) => { const b = Buffer.alloc(6); b[0] = 5; b[1] = mask; b.writeUInt16BE(x, 2); b.writeUInt16BE(y, 4); msg(b); },
        key: (down, sym) => { const b = Buffer.alloc(8); b[0] = 4; b[1] = down ? 1 : 0; b.writeUInt32BE(sym, 4); msg(b); },
        cut: text => { const t = Buffer.from(text); const b = Buffer.alloc(8); b[0] = 6; b.writeUInt32BE(t.length, 4); msg(b, t); },
        received: () => after,
        isClosed: () => closed,
        close: () => s.destroy(),
      });
    })();
  });
}

// One X display from xvfb-run, held by a sleeper, for half A.
async function throwawayDisplay() {
  const c = spawn('xvfb-run', ['-a', '-s', '-screen 0 1280x800x24', 'sh', '-c', 'echo "$DISPLAY $XAUTHORITY"; exec sleep 600'], { detached: true, stdio: ['ignore', 'pipe', 'ignore'] });
  let line = '';
  c.stdout.on('data', d => { line += d; });
  await until(() => line.includes('\n'), 15000);
  const [display, xauthority] = line.trim().split(' ');
  return { pid: c.pid, display, xauthority };
}

// The events `xinput test-xi2 --root` saw, as { buttons:Set, keys, heldMotion }.
function parseXi2(text) {
  const buttons = new Set();
  let keys = 0, heldMotion = 0, held = false;
  for (const ev of text.split('EVENT type').slice(1)) {
    const name = (ev.match(/\((\w+)\)/) || [])[1];
    const detail = Number((ev.match(/detail:\s*(\d+)/) || [])[1]);
    if (name === 'RawButtonPress') { buttons.add(detail); if (detail === 1) held = true; }
    if (name === 'RawButtonRelease' && detail === 1) held = false;
    if (name === 'RawKeyPress') keys++;
    if (name === 'RawMotion' && held) heldMotion++;
  }
  return { buttons, keys, heldMotion };
}

// Drive one x11vnc with `args` and report what reached the X server.
//   remote  before the keys, try to widen the input from OUTSIDE the session, the way
//           any X client on the display can: `x11vnc -R input:KMBC`.
//   second  at the end, open a second session and report whether it closed the first.
async function probeInput(X, port, args, password, { remote = false, second = false } = {}) {
  const xenv = { ...process.env, DISPLAY: X.display, XAUTHORITY: X.xauthority };
  spawnSync('xprop', ['-root', '-remove', 'CUT_BUFFER0'], { env: xenv });
  const obs = spawn('stdbuf', ['-oL', 'xinput', 'test-xi2', '--root'], { env: xenv, stdio: ['ignore', 'pipe', 'ignore'] });
  let seen = '';
  obs.stdout.on('data', d => { seen += d; });
  const vnc = spawn('x11vnc', args, { detached: true, stdio: 'ignore' });
  const out = {};
  try {
    await until(() => listeners(port).length > 0, 15000);
    await sleep(700);
    out.listeners = listeners(port);
    out.wrong = await rfb(port, 'not-it-9');
    const c = await rfb(port, password);
    out.authOk = c.authOk;
    if (!c.authOk) { out.reason = c.reason; return out; }
    const click = async mask => { c.pointer(mask, 120, 120); await sleep(150); c.pointer(0, 120, 120); await sleep(250); };
    c.pointer(0, 200, 200); await sleep(200);
    await click(1);          // left
    await click(4);          // right
    await click(2);          // middle
    await click(8);          // wheel up
    await click(16);         // wheel down
    await click(32);         // button 6
    await click(64);         // button 7
    await click(128);        // button 8 - Back, in Chromium
    await click(1 | 4);      // left and right in one mask
    c.pointer(1, 300, 300); await sleep(120); c.pointer(1, 350, 320); await sleep(120); c.pointer(1, 400, 340); await sleep(120); c.pointer(0, 400, 340);
    await sleep(250);
    if (remote) out.remote = spawnSync('x11vnc', ['-display', X.display, '-auth', X.xauthority, '-R', 'input:KMBC', '-sync'], { encoding: 'utf8', timeout: 15000 }).status;
    for (const sym of [0x61, 0xff0d]) { c.key(true, sym); await sleep(80); c.key(false, sym); await sleep(200); }
    c.cut('PROBE-CUT-IN');
    await sleep(800);
    out.cutBuffer = spawnSync('xprop', ['-root', 'CUT_BUFFER0'], { env: xenv, encoding: 'utf8' }).stdout.trim();
    spawnSync('xprop', ['-root', '-f', 'CUT_BUFFER0', '8s', '-set', 'CUT_BUFFER0', 'PROBE-CUT-OUT'], { env: xenv });
    await sleep(2500);
    out.serverCut = c.received().includes(Buffer.from('PROBE-CUT-OUT'));
    if (second) {
      const c2 = await rfb(port, password);
      await until(() => c.isClosed(), 3000);
      out.secondAuth = c2.authOk;
      out.firstClosed = c.isClosed();
      if (c2.close) c2.close();
    }
    c.close();
    await sleep(500);
  } finally {
    await killGroup(vnc.pid, 3000);
    obs.kill('SIGTERM');
    await until(() => obs.exitCode !== null || obs.signalCode !== null, 3000);
  }
  return { ...out, ...parseXi2(seen) };
}

const T = mkdtempSync(join(tmpdir(), 'shrt-'));
const outputs = [];                 // every stdout/stderr/log, scanned for the passwords
const passwords = [];               // every one-time password a share wrote
const started = new Set();          // every driver `start` launched, killed at the end
const sharePids = new Set();        // every share process seen, killed at the end if a teardown under test failed
let X = null;

try {
  // ── structural: the expiry timer exists before anything is public ──
  // A client killed between the funnel coming up and the timer being armed would
  // leave a public page with nothing to take it down; the order closes that window.
  const cli = readFileSync(CLIENT, 'utf8');
  const [timerAt, funnelAt] = [cli.indexOf("'--share-id', id"), cli.indexOf('funnelOn(cmd')];
  control('the share block\'s timer and funnel calls are locatable', timerAt > 0 && funnelAt > 0, true);
  ok('share arms its expiry timer BEFORE it turns the funnel on', timerAt < funnelAt, true);

  // ── listenerOwners: "MY process holds the port", not "something answers" ──
  const probeSrv = net.createServer();
  await new Promise(r => probeSrv.listen(0, '127.0.0.1', r));
  const heldPort = probeSrv.address().port;
  ok('listenerOwners names the process holding a listening port', listenerOwners(heldPort).includes(process.pid), true);
  await new Promise(r => probeSrv.close(r));
  ok('...and nothing once it is closed', listenerOwners(heldPort).length, 0);
  // A listener on ::1 alone answers nobody here: websockify and the funnel connect to
  // 127.0.0.1, and x11vnc's two listeners can split between two processes (share.mjs,
  // listenerOwners). Counting it is what let two racing shares both pass.
  const v6Srv = net.createServer();
  const v6Port = await new Promise(r => { v6Srv.once('error', () => r(null)); v6Srv.listen(0, '::1', () => r(v6Srv.address().port)); });
  if (v6Port === null) inconclusive.push('the ::1 listener check did not run: no IPv6 loopback on this host');
  else {
    control('a listener on ::1 alone is on the port (so the empty answer below is about the address)',
      listeners(v6Port).map(([a]) => a).join(','), '00000000000000000000000001000000');
    ok('...and listenerOwners does not count it: nothing there answers 127.0.0.1', listenerOwners(v6Port).length, 0);
    await new Promise(r => v6Srv.close(r));
  }

  // ══ HALF A: the input restriction ═════════════════════════════════════════
  const needA = ['xvfb-run', 'x11vnc', 'xinput', 'xprop', 'stdbuf'].filter(b => !has(b));
  if (needA.length) inconclusive.push(`half A did not run: missing ${needA.join(', ')}`);
  else if (!desWorks()) inconclusive.push('half A did not run: no DES in this node, even with --openssl-legacy-provider');
  else {
    X = await throwawayDisplay();
    control('xvfb-run produced a display and an auth file', !!(X.display && X.xauthority && existsSync(X.xauthority)), true);
    const pwFile = join(T, 'a.pass');
    writeFileSync(pwFile, 'Abc23xyz\n', { mode: 0o600 });
    const port = await freePort();
    const subjectArgs = x11vncArgs({ display: X.display, xauthority: X.xauthority, vncPort: port, passwordFile: pwFile });
    const tail = subjectArgs.slice(-INPUT_FLAGS.length);
    control('INPUT_FLAGS are the tail of the arguments share runs (so the control below differs by them alone)', JSON.stringify(tail), JSON.stringify(INPUT_FLAGS));
    const controlArgs = subjectArgs.slice(0, -INPUT_FLAGS.length);

    const C = await probeInput(X, port, controlArgs, 'Abc23xyz');
    const instrument = [
      control('CONTROL x11vnc: the session authenticates', C.authOk, true),
      control('CONTROL: a left click reaches X', C.buttons?.has(1), true),
      control('CONTROL: a right click reaches X (so the observer can see one)', C.buttons?.has(3), true),
      control('CONTROL: a middle click reaches X', C.buttons?.has(2), true),
      control('CONTROL: wheel up and down reach X', C.buttons?.has(4) && C.buttons?.has(5), true),
      control('CONTROL: side buttons 6, 7 and 8 reach X', [6, 7, 8].every(b => C.buttons?.has(b)), true),
      control('CONTROL: two key presses reach X', C.keys, 2),
      control('CONTROL: client clipboard text reaches X (CUT_BUFFER0)', /PROBE-CUT-IN/.test(C.cutBuffer || ''), true),
      control('CONTROL: X clipboard text reaches the client (ServerCutText)', C.serverCut, true),
    ].every(Boolean);

    // The remote-control route needs its own control: the restriction WITHOUT -safer,
    // on which an outside `x11vnc -R input:KMBC` must hand the keyboard back.
    const noSafer = subjectArgs.filter(a => a !== '-safer');
    control('the -safer control differs from the share by -safer alone', subjectArgs.length - noSafer.length, 1);
    const R = await probeInput(X, port, noSafer, 'Abc23xyz', { remote: true });
    const remoteRouteReal = control('CONTROL: without -safer, a remote `-R input:KMBC` lets keys through (so the route is real)', R.keys > 0, true);

    const S = await probeInput(X, port, subjectArgs, 'Abc23xyz', { remote: true, second: true });
    ok('x11vnc refuses a wrong password', S.wrong?.authOk, false);
    if (control('the restricted session authenticates (so what follows is about its input)', S.authOk, true) && instrument) {
      control('a LEFT click reaches X through the restriction (so an absence below is not a dead session)', S.buttons.has(1), true);
      ok('a left-DRAG reaches X: pointer motion arrives while button 1 is held', S.heldMotion > 0, true);
      ok('no right click reaches X', S.buttons.has(3), false);
      ok('no middle click reaches X', S.buttons.has(2), false);
      ok('no wheel (buttons 4, 5) reaches X', S.buttons.has(4) || S.buttons.has(5), false);
      ok('no side button (6, 7, 8) reaches X', [6, 7, 8].some(b => S.buttons.has(b)), false);
      ok('the LEFT button is the only one that reaches X - a left+right chord included', [...S.buttons].join(','), '1');
      ok('no key press reaches X (RFB KeyEvent: a letter and Return)', S.keys, 0);
      if (remoteRouteReal) ok('...even after an outside `x11vnc -R input:KMBC`, which -safer refuses', S.remote !== 0 && S.keys === 0, true);
      control('a second viewer authenticates (so the check below is about sharing)', S.secondAuth, true);
      ok('ONE viewer at a time: a second session replaces the first', S.firstClosed, true);
      ok('client clipboard text does not reach X', /PROBE-CUT-IN/.test(S.cutBuffer || ''), false);
      ok('X clipboard text does not reach the client', S.serverCut, false);
      ok('x11vnc listens on loopback only - no wildcard, no external address', S.listeners.length > 0 && S.listeners.every(([, lo]) => lo), true);
    }
  }

  // ══ HALF B: the lifecycle on real drivers ═════════════════════════════════
  const browsers = process.env.PLAYWRIGHT_BROWSERS_PATH || join(HERE, 'browsers');
  const haveChromium = (() => { try { return readdirSync(browsers).some(d => d.startsWith('chromium-')); } catch { return false; } })();
  const notHere = [!existsSync(join(HERE, 'node_modules', 'playwright-extra')) && 'no node_modules in signin_driver (npm ci there)',
    !haveChromium && `no chromium under ${browsers}`, ...['xvfb-run', 'x11vnc', 'websockify'].filter(b => !has(b)).map(b => `no ${b}`),
    !desWorks() && 'no DES', Buffer.byteLength(join(T, 'rb', 'driver.sock')) > 107 && 'TMPDIR is too long for a unix socket'].filter(Boolean);
  if (notHere.length) inconclusive.push(`half B did not run: ${notHere.join('; ')}`);
  else {
    try { await halfB(browsers); } catch (e) {
      console.log(`FAIL - half B threw before it finished: ${String(e && e.stack || e).split('\n').slice(0, 3).join(' | ')}`);
      fail++;
    }
  }
} finally {
  for (const pid of started) if (groupIsOurs(pid)) await killGroup(pid);
  for (const pid of sharePids) if (cmdline(pid).join(' ').includes(T)) await killGroup(pid);
  if (X) await killGroup(X.pid);
  for (const f of readdirSync(T)) if (f.endsWith('.log')) outputs.push(readFileSync(join(T, f), 'utf8'));
  const leaks = needles => { const all = outputs.join('\n'); return needles.filter(n => all.includes(n)); };
  outputs.push('a planted line carrying Zq7xPw2m');
  control('the password scan finds a password planted in the collected output (so its silence below means something)', leaks(['Zq7xPw2m']).length, 1);
  outputs.pop();
  if (passwords.length) ok(`none of the ${passwords.length} one-time passwords appears on any stdout, stderr, driver log or share log`, leaks(passwords).join(','), '');
  try { rmSync(T, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 }); } catch (e) { console.log(`note: could not remove ${T}: ${e.message}`); }
}

async function halfB(browsers) {
  const POOL = join(T, 'pool.json');
  writeFileSync(POOL, JSON.stringify([{ username: 'alpha@example.com', password: 'SENTINEL-share-pw-1d4', home_agent: 'x' }]), { mode: 0o600 });
  const novnc = join(T, 'novnc');
  mkdirSync(novnc);
  writeFileSync(join(novnc, 'vnc.html'), '<p>stand-in for noVNC</p>');
  const vncPort = await freePort(), webPort = await freePort();
  const CONFIG = join(T, 'config.json');
  writeFileSync(CONFIG, JSON.stringify({
    fleet: { agents_home: join(T, 'agents') },
    accounts: { pool_file: POOL, profiles_dir: join(T, 'profiles') },
    // ⚠️ share.tailscale names a path that does not exist: if the variable below were
    // ever ignored, the share fails to run tailscale at all rather than reaching a real one.
    share: { vnc_port: vncPort, web_port: webPort, funnel_port: 10000, novnc_dir: novnc, page: 'vnc.html?autoconnect=1', minutes: 10, tailscale: ['/nonexistent/tailscale-must-not-run'] },
  }));
  const FAKE = join(T, 'ts.json');
  const bin = join(T, 'bin');
  mkdirSync(bin);
  for (const b of ['sudo', 'tailscale']) {
    writeFileSync(join(bin, b), `#!/bin/sh\necho "${b} $*" >> '${join(T, 'tripwire.txt')}'\nexit 97\n`);
    chmodSync(join(bin, b), 0o755);
  }
  const env = {
    PLAYWRIGHT_BROWSERS_PATH: browsers, PATH: `${bin}:${process.env.PATH}`, FAKE_TAILSCALE_STATE: FAKE,
    AGENT_REVIVE_TAILSCALE: JSON.stringify([process.execPath, join(SKILL, 'fixtures', 'fake-tailscale.mjs')]),
  };
  const childEnv = { ...process.env };
  for (const k of ['DEBUG', 'DEBUG_COLORS', 'NODE_DEBUG', 'PWDEBUG', 'PLAYWRIGHT_DEBUG', 'DISPLAY']) delete childEnv[k];
  // THE BROWSERS WRITE INTO A HOME OF THIS RUN'S OWN. Chromium keeps state under
  // $XDG_CONFIG_HOME/google-chrome-for-testing (macOS: under $HOME/Library) and ibus
  // under $XDG_CONFIG_HOME/ibus; inherited, those land in the runner's or the operator's
  // real home on every run. The host settings keep the path the real HOME gave them
  // (fleetlib's default), so `fleet where` resolves as it would have.
  childEnv.FLEET_HOST_CONFIG ||= join(homedir(), '.config', 'agent-fleet', 'host.json');
  childEnv.HOME = join(T, 'home');
  childEnv.XDG_CONFIG_HOME = join(T, 'home', '.config');
  mkdirSync(childEnv.XDG_CONFIG_HOME, { recursive: true });
  const client = (args, extraEnv = {}) => new Promise(res => {
    const c = spawn(process.execPath, [CLIENT, ...args], { env: { ...childEnv, ...env, ...extraEnv } });
    let stdout = '', stderr = '';
    c.stdout.on('data', d => { stdout += d; });
    c.stderr.on('data', d => { stderr += d; });
    const kill = setTimeout(() => c.kill('SIGTERM'), 120000);
    c.on('close', status => {
      clearTimeout(kill);
      outputs.push(stdout, stderr);
      let json = null;
      try { json = JSON.parse(stdout); } catch {}
      if (json && json.started && json.pid) started.add(json.pid);
      res({ status, stdout, stderr, json });
    });
  });
  const run = (agent, rd, args, extraEnv) => client([agent, ...args, '--run-dir', rd, '--config', CONFIG, '--log', join(T, `${agent}.log`)], extraEnv);
  const funnel = () => { try { return JSON.parse(readFileSync(FAKE, 'utf8')).funnel; } catch { return {}; } };
  const tsCalls = () => { try { return readFileSync(`${FAKE}.log`, 'utf8'); } catch { return ''; } };
  const stateOf = rd => { try { return JSON.parse(readFileSync(join(rd, STATE_FILE), 'utf8')); } catch { return null; } };
  const ourX11vnc = (port = vncPort) => readdirSync('/proc').filter(d => /^\d+$/.test(d)).some(d => { const a = cmdline(d); return a[0]?.endsWith('x11vnc') && a.includes(String(port)); });
  const share = async (agent, rd, extra = [], extraEnv) => {
    const r = await run(agent, rd, ['share', ...extra], extraEnv);
    for (const pid of Object.values(stateOf(rd)?.pids || {})) sharePids.add(pid);
    try { const pw = readFileSync(join(rd, PASSWORD_FILE), 'utf8').trim(); if (pw) passwords.push(pw); } catch {}
    try { outputs.push(readFileSync(join(rd, LOG_FILE), 'utf8')); } catch {}
    return r;
  };
  const allGone = async (what, st, rd) => {
    try { outputs.push(readFileSync(join(rd, LOG_FILE), 'utf8')); } catch {}
    const pids = ['x11vnc', 'websockify', 'timer'].map(k => st?.pids?.[k]).filter(Boolean);
    control(`${what}: the share had its three processes (so their absence below means something)`, pids.length, 3);
    const gone = await until(() => !pids.some(p => alive(p) || groupAlive(p)), 15000);
    ok(`${what}: x11vnc, websockify and the timer are gone, with their process groups`, gone, true);
    ok(`${what}: the funnel serves nothing`, JSON.stringify(funnel()), '{}');
    ok(`${what}: the password file is gone`, existsSync(join(rd, PASSWORD_FILE)), false);
  };
  // The colour at (x, y) of the X display a driver draws on, read from the screen
  // itself: page screenshots stop at the viewport and cannot see an address bar.
  const GREEN = 'data:text/html,<body style="margin:0;background:rgb(0,200,0)"></body>';
  const pixel = (rd, x, y) => {
    const environ = (() => { try { return readFileSync(`/proc/${driverNode(rd)}/environ`, 'utf8').split('\0'); } catch { return []; } })();
    const xenv = Object.fromEntries(environ.filter(e => /^(DISPLAY|XAUTHORITY)=/.test(e)).map(e => e.split(/=(.*)/s).slice(0, 2)));
    const r = spawnSync('sh', ['-c', `xwd -root -silent | convert xwd:- -crop 1x1+${x}+${y} -depth 8 txt:-`], { env: { ...process.env, ...xenv }, encoding: 'utf8' });
    return ((r.stdout || '').match(/#([0-9A-F]{6})/i) || [])[1]?.toUpperCase() || `none (${(r.stderr || '').trim().split('\n')[0]})`;
  };
  const canSeeScreen = has('xwd') && has('convert');
  // The node process itself - xvfb-run's own argv names driver.mjs and the run dir too,
  // and SIGKILLing IT leaves the driver running.
  const driverNode = rd => readdirSync('/proc').filter(d => /^\d+$/.test(d)).map(Number).find(d => { const a = cmdline(d); return a[0] === process.execPath && a[1]?.endsWith('driver.mjs') && a.includes(rd); });

  // ── refused without --app-window ──
  const ra = join(T, 'ra');
  let s = await run('shrt-a', ra, ['start']);
  ok('throwaway start: exit 0', s.status, 0);
  let r = await share('shrt-a', ra);
  ok('share on a driver started WITHOUT --app-window: exit 2', r.status, 2);
  ok('...naming --app-window as the reason', /--app-window/.test(r.stderr), true);
  ok('...and nothing was started or made public', !ourX11vnc() && !existsSync(join(ra, STATE_FILE)) && !tsCalls().includes('--bg'), true);
  if (!canSeeScreen) inconclusive.push('the address-bar check did not run: no xwd or no convert');
  else {
    await run('shrt-a', ra, ['goto', GREEN]);
    await sleep(500);
    control('a TABBED window shows its toolbar where the app window shows the page (so the pixel check can see an address bar)', pixel(ra, 640, 72) !== '00C800', true);
  }
  await run('shrt-a', ra, ['quit']);

  // ── the app window ──
  const rb = join(T, 'rb');
  s = await run('shrt-b', rb, ['start', '--app-window']);
  ok('start --app-window: exit 0', s.status, 0);
  ok('start --app-window: the reply says so', s.json?.app_window, true);
  const pages = (await run('shrt-b', rb, ['pages'])).json?.result || [];
  ok('start --app-window: ONE window, the app window on its data: start page', pages.length === 1 && /^data:text\/html/.test(pages[0].url), true);
  const chrome = readdirSync('/proc').filter(d => /^\d+$/.test(d)).map(d => cmdline(d)).find(a => a.some(x => x.startsWith('--app=data:')) && a.some(x => x.includes(join(rb, 'profile'))));
  ok('...and Chromium was launched with --app', !!chrome, true);
  if (canSeeScreen) {
    await run('shrt-b', rb, ['goto', GREEN]);
    await sleep(500);
    ok('start --app-window: no tab strip and no address bar - the page is drawn where they would be', [pixel(rb, 640, 30), pixel(rb, 640, 72)].join(','), '00C800,00C800');
  }
  ok('start --app-window: the display is recorded, mode 0600', existsSync(join(rb, 'display.json')) && modeOf(join(rb, 'display.json')), '600');

  // ── a share being set up elsewhere on this host holds the setup lock ──
  // Two shares set up at once race for one set of ports with no guaranteed winner
  // (share.mjs, setupLock). While the lock is held, a share must refuse before it
  // starts anything.
  const held = net.createServer();
  const holding = await new Promise(res => { held.once('error', () => res(false)); held.listen({ path: setupLock(vncPort) }, () => res(true)); });
  control('the test holds the setup lock for the configured vnc port', holding, true);
  r = await share('shrt-b', rb);
  ok('share while another share is being set up on this host: exit 1, saying so', r.status === 1 && /is being set up on this host/.test(r.stderr), true);
  ok('...and nothing was started, recorded or made public', !ourX11vnc() && !existsSync(join(rb, STATE_FILE)) && JSON.stringify(funnel()) === '{}', true);
  if (r.status === 0) await run('shrt-b', rb, ['unshare']);
  await new Promise(res => held.close(res));

  // ── share ──
  r = await share('shrt-b', rb, ['--minutes', '10']);
  ok('share: exit 0', r.status, 0);
  ok('share: ONE JSON object on stdout', r.json?.shared, true);
  ok('share: the URL is the Tailscale name, the funnel port and the page', r.json?.url, 'https://sharetest.example-tailnet.invalid:10000/vnc.html?autoconnect=1');
  ok('share: it names the password FILE', r.json?.password_file, join(rb, PASSWORD_FILE));
  const pw = existsSync(join(rb, PASSWORD_FILE)) ? readFileSync(join(rb, PASSWORD_FILE), 'utf8') : '';
  ok('share: the password file holds one 8-character password', /^[A-Za-z0-9]{8}\n$/.test(pw), true);
  ok('share: ...mode 0600', existsSync(join(rb, PASSWORD_FILE)) && modeOf(join(rb, PASSWORD_FILE)), '600');
  ok('share: the expiry is 10 minutes out', Math.abs(Date.parse(r.json?.expires_at) - Date.now() - 600000) < 60000, true);
  let st = stateOf(rb);
  ok('share: x11vnc, websockify and the expiry timer run', ['x11vnc', 'websockify', 'timer'].every(k => alive(st?.pids?.[k])), true);
  const running = cmdline(st?.pids?.x11vnc).join(' ');
  ok('share: the running x11vnc carries the input restriction half A proved', running.includes(INPUT_FLAGS.join(' ')), true);
  ok('share: both ports listen on loopback only', [vncPort, webPort].every(p => listeners(p).length > 0 && listeners(p).every(([, lo]) => lo)), true);
  ok('share: the page is served through websockify', await fetch(`http://127.0.0.1:${webPort}/vnc.html`).then(x => x.status, () => 0), 200);
  ok('share: the funnel serves the funnel port, to websockify', funnel()['10000'], `http://127.0.0.1:${webPort}`);
  ok('share: the session takes the password from the file', (await rfb(vncPort, pw.trim())).authOk, true);

  r = await share('shrt-b', rb);
  ok('a second share of a shared driver: exit 1, already shared', r.status === 1 && /already shared/.test(r.stderr), true);
  ok('...and the live share is untouched', stateOf(rb)?.id === st?.id && alive(st?.pids?.x11vnc), true);

  // ── unshare, twice ──
  r = await run('shrt-b', rb, ['unshare']);
  ok('unshare: exit 0, clean', r.status === 0 && r.json?.unshared === true && r.json?.clean === true, true);
  await allGone('unshare', st, rb);
  ok('unshare: the state is gone', existsSync(join(rb, STATE_FILE)), false);
  r = await run('shrt-b', rb, ['unshare']);
  ok('unshare again: exit 0, nothing to do', r.status === 0 && r.json?.unshared === false, true);

  // ── the expiry timer ──
  r = await share('shrt-b', rb, ['--minutes', '0.1']);
  st = stateOf(rb);
  ok('share --minutes 0.1: exit 0', r.status, 0);
  ok('the expiry timer tears the share down by itself', await until(() => !existsSync(join(rb, STATE_FILE)), 40000), true);
  await allGone('expiry', st, rb);

  // ── a funnel that does not come up ──
  r = await share('shrt-b', rb, [], { FAKE_TAILSCALE_FAIL: 'funnel-on' });
  ok('a funnel that fails: share exits 1 saying so', r.status === 1 && /funnel did not come up/.test(r.stderr), true);
  ok('...and what it had started is torn down', await until(() => !ourX11vnc(), 10000) && !existsSync(join(rb, STATE_FILE)) && !existsSync(join(rb, PASSWORD_FILE)), true);

  // ── teardown on quit ──
  await share('shrt-b', rb);
  st = stateOf(rb);
  await run('shrt-b', rb, ['quit']);
  ok('quit: the driver exits and its run dir goes', await until(() => !existsSync(rb), 20000), true);
  await allGone('quit', st, rb);

  // ── teardown on SIGTERM ──
  s = await run('shrt-b', rb, ['start', '--app-window']);
  await share('shrt-b', rb);
  st = stateOf(rb);
  control('a share is live before the signal', alive(st?.pids?.websockify), true);
  await killGroup(s.json?.pid, 20000);
  ok('SIGTERM: the run dir goes', await until(() => !existsSync(rb), 20000), true);
  await allGone('SIGTERM', st, rb);

  // ── a SIGKILLed driver's share, torn down by the next start ──
  s = await run('shrt-b', rb, ['start', '--app-window']);
  await share('shrt-b', rb);
  st = stateOf(rb);
  const drv = driverNode(rb);
  control('the driver process is found', !!drv, true);
  try { process.kill(drv, 'SIGKILL'); } catch {}
  await until(() => !alive(drv), 10000);
  control('after a SIGKILL the share outlives its driver (so the next check means something)', alive(st?.pids?.websockify) && funnel()['10000'] !== undefined, true);
  s = await run('shrt-b', rb, ['start', '--app-window']);
  ok('the next start on that run dir: exit 0', s.status, 0);
  await allGone('next start after a SIGKILL', st, rb);
  await run('shrt-b', rb, ['quit']);
  await until(() => !existsSync(rb), 20000);

  // ── a teardown that cannot finish keeps its record, its timer and the page OFF the next wipe ──
  const OFF_FAILS = { FAKE_TAILSCALE_FAIL: 'funnel-off' };
  s = await run('shrt-b', rb, ['start', '--app-window']);
  await share('shrt-b', rb);
  st = stateOf(rb);
  r = await run('shrt-b', rb, ['unshare'], OFF_FAILS);
  ok('unshare whose funnel-off fails: exit 1, not clean, saying why', r.status === 1 && r.json?.clean === false && /funnel/.test(r.json?.funnel_error || ''), true);
  ok('...keeps the record, so a retry knows the share exists', stateOf(rb)?.id, st?.id);
  ok('...keeps the expiry timer, the retry that needs nobody', alive(st?.pids?.timer), true);
  control('...and the funnel really is still on (the fake refused the off)', funnel()['10000'] !== undefined, true);
  r = await run('shrt-b', rb, ['unshare']);
  ok('the retry, once the funnel answers: exit 0, clean', r.status === 0 && r.json?.clean === true, true);
  await allGone('a retried unshare', st, rb);
  await run('shrt-b', rb, ['quit']);
  await until(() => !existsSync(rb), 20000);

  s = await run('shrt-b', rb, ['start', '--app-window'], OFF_FAILS);
  await share('shrt-b', rb);
  st = stateOf(rb);
  await run('shrt-b', rb, ['quit']);
  await until(() => !driverNode(rb), 20000);
  ok('quit with a funnel-off that fails: the run dir keeps the record and the log and NOTHING else', existsSync(rb) ? readdirSync(rb).sort().join(',') : 'gone', [LOG_FILE, STATE_FILE].sort().join(','));
  control('...and the funnel is still on (so the record is the only thing that knows)', funnel()['10000'] !== undefined, true);
  r = await run('shrt-b', rb, ['start', '--app-window'], OFF_FAILS);
  ok('a start over a record it cannot tear down refuses (exit 2) rather than wiping it', r.status === 2 && /could not be torn down/.test(r.stderr) && stateOf(rb)?.id === st?.id, true);
  r = await run('shrt-b', rb, ['unshare']);
  ok('unshare then clears it: exit 0, clean', r.status === 0 && r.json?.clean === true, true);
  await allGone('unshare after a failed quit', st, rb);

  // ── refused unless the app window is the only window ──
  s = await run('shrt-b', rb, ['start', '--app-window']);
  await run('shrt-b', rb, ['goto', `data:text/html,<button id=b onclick="window.open('about:blank','w','popup,width=300,height=300')">open</button>`]);
  await run('shrt-b', rb, ['click', '--selector', '#b']);
  control('the page opened a second window', ((await run('shrt-b', rb, ['pages'])).json?.result || []).length, 2);
  r = await share('shrt-b', rb);
  ok('share with a second window open: exit 2, naming the windows', r.status === 2 && /windows are open/.test(r.stderr), true);
  ok('...and nothing was started', !ourX11vnc() && !existsSync(join(rb, STATE_FILE)), true);
  await run('shrt-b', rb, ['quit']);
  await until(() => !existsSync(rb), 20000);

  // ── refused on a display that is not the driver's own Xvfb ──
  const X2 = X || await throwawayDisplay();
  if (!X) X = X2;
  const rd = join(T, 'rd');
  s = await run('shrt-d', rd, ['start', '--app-window', '--no-xvfb'], { DISPLAY: X2.display, XAUTHORITY: X2.xauthority });
  control('a driver started --no-xvfb onto another Xvfb is up', s.status, 0);
  r = await share('shrt-d', rd);
  ok("share on a display the driver's own xvfb-run did not start: exit 2", r.status === 2 && /not an Xvfb started by this driver/.test(r.stderr), true);
  ok('...and nothing was started', !ourX11vnc() && !existsSync(join(rd, STATE_FILE)), true);
  await run('shrt-d', rd, ['quit']);
  await until(() => !existsSync(rd), 20000);

  // ── a share whose x11vnc can take only ::1 is refused ──
  // The split two shares at once produce some of the time (share.mjs, listenerOwners),
  // made deterministic: a socket bound to 127.0.0.1:<vnc_port> WITHOUT SO_REUSEADDR and
  // never listening refuses x11vnc's 127.0.0.1 bind while answering no connect, so the
  // pre-checks pass and x11vnc comes up on ::1 alone. websockify would then proxy to
  // whatever holds 127.0.0.1 - another share's display, or nothing - so the share must
  // not come up. Fresh ports in a second config: a TIME_WAIT left on the shared vnc
  // port by the steps above would refuse the blocker's own bind.
  if (!has('python3')) inconclusive.push('the ::1-only x11vnc check did not run: no python3 to hold the blocker socket');
  else {
    const v6Vnc = await freePort(), v6Web = await freePort();
    const CONFIG_V6 = join(T, 'config-v6.json');
    const cfgV6 = JSON.parse(readFileSync(CONFIG, 'utf8'));
    Object.assign(cfgV6.share, { vnc_port: v6Vnc, web_port: v6Web });
    writeFileSync(CONFIG_V6, JSON.stringify(cfgV6));
    const blocker = spawn('python3', ['-c', "import socket, sys\ns = socket.socket()\ns.bind(('127.0.0.1', int(sys.argv[1])))\nprint('bound', flush=True)\nsys.stdin.read()", String(v6Vnc)],
      { stdio: ['pipe', 'pipe', 'ignore'] });
    let bound = '';
    blocker.stdout.on('data', d => { bound += d; });
    control('a socket holds 127.0.0.1:<vnc_port> bound, without SO_REUSEADDR, not listening', await until(() => bound.includes('bound'), 10000), true);
    await run('shrt-b', rb, ['start', '--app-window']);
    let ended = false, sawV6Only = false;
    const pending = client(['shrt-b', 'share', '--run-dir', rb, '--config', CONFIG_V6, '--log', join(T, 'shrt-b.log')]).then(x => { ended = true; return x; });
    while (!ended) {
      const l = listeners(v6Vnc);
      if (ourX11vnc(v6Vnc) && l.length > 0 && l.every(([a]) => a === '00000000000000000000000001000000')) sawV6Only = true;
      await sleep(100);
    }
    r = await pending;
    for (const pid of Object.values(stateOf(rb)?.pids || {})) sharePids.add(pid);
    try { const p = readFileSync(join(rb, PASSWORD_FILE), 'utf8').trim(); if (p) passwords.push(p); } catch {}
    control("while it ran, the share's x11vnc listened on ::1 alone (so the refusal below is about 127.0.0.1)", sawV6Only, true);
    ok('a share whose x11vnc holds ::1 but not 127.0.0.1: exit 1, x11vnc did not take 127.0.0.1', r.status === 1 && /x11vnc did not take 127\.0\.0\.1/.test(r.stderr), true);
    ok('...and nothing is left running, recorded or public (x11vnc, record, funnel)',
       [ourX11vnc(v6Vnc), existsSync(join(rb, STATE_FILE)), JSON.stringify(funnel())].join(','), 'false,false,{}');
    if (r.status === 0) await client(['shrt-b', 'unshare', '--run-dir', rb, '--config', CONFIG_V6, '--log', join(T, 'shrt-b.log')]);
    blocker.stdin.end();
    blocker.kill();
    await until(() => blocker.exitCode !== null || blocker.signalCode !== null, 5000);
    await run('shrt-b', rb, ['quit']);
    await until(() => !existsSync(rb), 20000);
  }

  // ── two shares at once: one wins, the other takes nothing of the winner's with it ──
  // Exactly one, every time: the setup lock lets one share set up at a time, so one
  // x11vnc and one websockify are started. Unserialized, two x11vncs started together
  // split 127.0.0.1 and ::1 or both lose 127.0.0.1, and two websockifys can both fail
  // (share.mjs, setupLock and listenerOwners) - no winner, or a winner showing the
  // other share's display.
  const rc = join(T, 'rc');
  await Promise.all([run('shrt-b', rb, ['start', '--app-window']), run('shrt-c', rc, ['start', '--app-window'])]);
  const [b, c] = await Promise.all([share('shrt-b', rb), share('shrt-c', rc)]);
  const winner = b.status === 0 ? rb : c.status === 0 ? rc : null;
  ok('two shares at once: exactly one succeeds', [b.status, c.status].filter(x => x === 0).length, 1);
  for (const x of [b, c]) if (x.status !== 0) console.log(`note: a losing share stopped at: ${x.stderr.trim().split('\n')[0]}`);
  const loserRd = winner === rb ? rc : rb;
  const ws = stateOf(winner || rb);
  ok("...the winner's x11vnc holds the port, and is the only x11vnc on it",
     !!ws && listenerOwners(vncPort).includes(ws.pids.x11vnc) && readdirSync('/proc').filter(d => /^\d+$/.test(d)).filter(d => { const a = cmdline(d); return a[0]?.endsWith('x11vnc') && a.includes(String(vncPort)); }).length === 1, true);
  ok("...the winner's page is still public", funnel()['10000'], `http://127.0.0.1:${webPort}`);
  ok('...the loser left no record and no timer', !existsSync(join(loserRd, STATE_FILE)) && !readdirSync('/proc').some(d => { const a = cmdline(d); return a.includes('unshare') && a.includes(loserRd); }), true);
  r = await run(winner === rc ? 'shrt-c' : 'shrt-b', winner || rb, ['unshare']);
  await allGone('the winner, unshared', ws, winner || rb);
  await Promise.all([run('shrt-b', rb, ['quit']), run('shrt-c', rc, ['quit'])]);
  await until(() => !existsSync(rb) && !existsSync(rc), 20000);

  ok('no call reached a real sudo or tailscale (the PATH tripwire is empty)', existsSync(join(T, 'tripwire.txt')) ? readFileSync(join(T, 'tripwire.txt'), 'utf8') : '', '');
  control('...while the stand-in took the funnel calls (so the tripwire was not simply bypassed by nothing)', tsCalls().includes('"--bg"'), true);
}

console.log('');
if (inconclusive.length) {
  console.log(`NO VERDICT - ${inconclusive.join('; ')}`);
  console.log(fail ? `(and ${fail} assertion(s) FAILED above - those are real)` : 'Do NOT read this as a pass.');
  process.exit(fail ? 1 : 3);
}
console.log(`passed ${pass}, failed ${fail}`);
process.exit(fail === 0 ? 0 : 1);
