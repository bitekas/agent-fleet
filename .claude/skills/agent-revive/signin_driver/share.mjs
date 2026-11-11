// The tap-to-solve share: the rules for showing a person the driver's browser,
// and the ONE teardown every path uses. `signin.mjs share` / `unshare` drive it;
// `driver.mjs` calls `stopShare` on quit, on every exit it can observe, and before
// it wipes a run dir a killed predecessor left behind. Node builtins only, so the
// driver can import it without an install.
//
// What a share is: x11vnc on the driver's own Xvfb display (127.0.0.1 only, a
// one-time password from a mode-0600 file), websockify serving noVNC in front of it
// (127.0.0.1 only), and a Tailscale Funnel making that one page public, with a
// detached timer that tears all three down at the expiry. Nothing is shared unless
// `signin.mjs share` is run, and it refuses a driver not started `--app-window`.
//
// ⚠️ THE INPUT RESTRICTION IS ENFORCED BY x11vnc, ON THE SERVER, AND EACH FLAG
// CLOSES A DIFFERENT HOLE. The person may move the pointer and press the LEFT
// button, which includes a left-drag (the puzzle CAPTCHA is a drag), and nothing
// else. Measured 2026-11-01 on x11vnc 0.9.17 with `xinput test-xi2 --root` reading
// the raw events on the display, one flag removed at a time:
//   -input MB          keyboard (RFB KeyEvent) and client-to-server clipboard
//                      (ClientCutText, which x11vnc otherwise writes into
//                      CUT_BUFFER0) never reach X. Alone it still delivers buttons
//                      2 to 8: B allows EVERY button.
//   -buttonmap 1-1=1   the `=1` caps the pointer at one button, so the right, middle,
//                      wheel and side buttons are dropped - also when sent in the
//                      same mask as a left press. Alone it still delivers every key.
//   -nosel             x11vnc manages no X selection or cut buffer in either
//                      direction. Without it, text that lands in an X selection or
//                      CUT_BUFFER0 is pushed to the viewer as ServerCutText, i.e.
//                      onto the person's own clipboard.
//   -safer             no remote control and no reverse connections. Without it any
//                      X client on the display can run `x11vnc -R input:KMBC` and
//                      hand the keyboard back to the viewer: measured, a key then
//                      reached X through the restricted server.
// share.test.mjs proves the combination against a control x11vnc without these
// flags, which DOES deliver every one of those events - so a green there is about the
// flags, not about an observer that cannot see a right-click. Remove any one flag and
// a named assertion there goes red (measured, one flag at a time). The INBOUND
// clipboard is closed twice - by the C missing from -input and by -nosel - so its
// assertion reds only with both gone; neither is redundant, because each also closes
// something the other leaves open. tmux_triage.test.sh pins this line as text,
// because it runs unattended and share.test.mjs does not. A QEMU extended key event
// (RFB message 255, which noVNC sends only to a server that advertises it) is not an
// input path here: x11vnc 0.9.17 drops the connection on it, with or without these
// flags (measured 2026-11-01).
//
// ⚠️ WHAT THE FLAGS CANNOT CLOSE: a left click is a left click. A `target=_blank`
// link on the shared page opens a normal tabbed window whose menu answers a left
// click, so `share` refuses while a second window is open and SKILL.md step 7 says
// to unshare at once if one appears.
//
// ⚠️ x11vnc CAN HANG ON SIGTERM. Measured 2026-11-01: after "caught signal: 15" the
// process sat in a futex wait and never exited. Every kill here therefore escalates
// to SIGKILL after a grace period; a teardown that trusted SIGTERM would leave a VNC
// server on the display with the funnel already gone, reported as torn down.

import { readFileSync, writeFileSync, renameSync, rmSync, readdirSync, readlinkSync, existsSync, chmodSync, lstatSync } from 'node:fs';
import { join, basename } from 'node:path';
import { spawnSync } from 'node:child_process';
import { randomInt } from 'node:crypto';

export const DISPLAY_FILE = 'display.json';   // written by the driver when started --app-window
export const STATE_FILE = 'share.json';       // written by `share`, read by every teardown
export const PASSWORD_FILE = 'vnc.pass';      // the one-time password, mode 0600
export const LOG_FILE = 'share.log';          // x11vnc's, websockify's and the timer's output

// ⚠️ ONE SHARE IS SET UP AT A TIME ON THIS HOST, PER VNC PORT. Two set up at once race
// for the same ports, and nothing below them settles that race to exactly one winner:
// x11vnc binds 127.0.0.1 and ::1 one after the other, so two started together can
// split the two or BOTH lose 127.0.0.1 (measured 2026-11-06, x11vnc 0.9.17 on two
// CPUs: 107 splits and 1 double loss in 150 simultaneous starts), and two websockifys
// can both fail (listenerOwners). `signin.mjs share` holds this abstract unix socket
// from its port checks until it exits: binding it is atomic, it writes nothing to
// disk, the kernel drops it however the process ends, and no child inherits it
// (Node opens every fd close-on-exec).
export const setupLock = vncPort => `\0agent-revive-share-${vncPort}`;

// The first window is an app window on this page: no tabs, no address bar, no
// menu. `--app=about:blank` is NOT one - measured 2026-11-01: Chromium opened a
// normal tabbed window for it - so the start page is a data: URL.
export const APP_START = 'data:text/html,<title>sign-in</title>';

export const INPUT_FLAGS = ['-input', 'MB', '-buttonmap', '1-1=1', '-nosel', '-safer'];

export function x11vncArgs({ display, xauthority, vncPort, passwordFile }) {
  return ['-display', display, '-auth', xauthority, '-rfbport', String(vncPort), '-localhost',
    // -nevershared: ONE viewer at a time, and a new one replaces the old - so the
    // person's reconnect after a dropped phone connection is let in, and a second
    // person holding the same link and password is not let in beside them.
    '-passwdfile', passwordFile, '-forever', '-nevershared', '-noxdamage', '-quiet',
    // -norc: a ~/.x11vncrc is read before the command line and could hand back what
    // INPUT_FLAGS take away.
    '-norc', ...INPUT_FLAGS];
}

export function websockifyArgs({ webPort, vncPort, novncDir }) {
  return ['--web', novncDir, `127.0.0.1:${webPort}`, `127.0.0.1:${vncPort}`];
}

// A VNC password is a DES key, so only its first 8 characters count. The alphabet
// drops characters a person misreads on a phone (0/O, 1/l/I, 5/S, 8/B).
const ALPHABET = 'abcdefghjkmnpqrstuvwxyzACDEFGHJKLMNPQRTUVWXYZ2345679';
export const newPassword = () => Array.from({ length: 8 }, () => ALPHABET[randomInt(ALPHABET.length)]).join('');

// ── the share block of config.json ───────────────────────────────────────────
export const SHARE_KEYS = ['vnc_port', 'web_port', 'funnel_port', 'novnc_dir', 'page', 'minutes', 'tailscale'];
export function shareConfig(cfg) {
  const s = cfg?.share;
  const missing = SHARE_KEYS.filter(k => s?.[k] === undefined || s?.[k] === '');
  if (missing.length) throw new Error(`config.json is missing share.${missing.join(', share.')}`);
  for (const k of ['vnc_port', 'web_port', 'funnel_port']) {
    if (!(Number.isInteger(s[k]) && s[k] >= 1 && s[k] <= 65535)) throw new Error(`share.${k} must be a port number, not ${JSON.stringify(s[k])}`);
  }
  return s;
}

// The tailscale command, as an argv prefix: config's `share.tailscale`, or the JSON
// array in AGENT_REVIVE_TAILSCALE. The variable exists so a test points every
// tailscale call at a fake and nothing it runs can make anything public.
// ⚠️ ALWAYS RESOLVED FROM CONFIG OR THE ENVIRONMENT, NEVER FROM A STATE FILE. The run
// dir sits at a predictable path under the system temp dir; a command read out of a
// file there is a command anyone who can plant that file gets run, through `sudo -n`.
export function tailscaleCommand(cfg) {
  if (process.env.AGENT_REVIVE_TAILSCALE) {
    const v = JSON.parse(process.env.AGENT_REVIVE_TAILSCALE);
    if (!Array.isArray(v) || !v.length) throw new Error('AGENT_REVIVE_TAILSCALE must be a JSON array, the command and its leading arguments');
    return v.map(String);
  }
  const v = cfg?.share?.tailscale;
  if (!Array.isArray(v) || !v.length) throw new Error('config.json is missing share.tailscale (the tailscale command, as an argv array)');
  return v.map(String);
}

function tailscale(cmd, args, timeout = 30000) {
  const r = spawnSync(cmd[0], [...cmd.slice(1), ...args], { encoding: 'utf8', timeout });
  if (r.error) throw new Error(`${cmd.join(' ')} ${args.join(' ')}: ${r.error.message}`);
  return r;
}

// This host's public name - read from Tailscale, never written down.
export function publicHost(cmd, timeout = 10000) {
  const r = tailscale(cmd, ['status', '--json'], timeout);
  if (r.status !== 0) throw new Error(`tailscale status exited ${r.status}: ${(r.stderr || '').trim().split('\n')[0]}`);
  const name = JSON.parse(r.stdout)?.Self?.DNSName;
  if (!name) throw new Error('tailscale status --json carries no Self.DNSName');
  return String(name).replace(/\.$/, '');
}

// Whether the funnel serves `port` at all, read from tailscale's own status. A status
// that cannot be read THROWS: "unknown" is never reported as "off".
export function funnelServes(cmd, port) {
  const r = tailscale(cmd, ['funnel', 'status', '--json']);
  if (r.status !== 0) throw new Error(`tailscale funnel status exited ${r.status}: ${(r.stderr || '').trim().split('\n')[0]}`);
  const st = JSON.parse(r.stdout || '{}');
  return !!(st.TCP && st.TCP[String(port)]) || Object.keys(st.AllowFunnel || {}).some(k => k.endsWith(`:${port}`));
}

export const funnelOn = (cmd, port, webPort) => tailscale(cmd, ['funnel', '--bg', `--https=${port}`, `http://127.0.0.1:${webPort}`]);
const funnelOff = (cmd, port) => tailscale(cmd, ['funnel', `--https=${port}`, 'off']);

const statOf = pid => { try { const s = readFileSync(`/proc/${pid}/stat`, 'utf8'); return s.slice(s.lastIndexOf(')') + 2).split(' '); } catch { return null; } };
export const ppidOf = pid => Number(statOf(pid)?.[1]) || null;

// The Xvfb process serving `display`, or null.
export function virtualDisplayPid(display) {
  for (const d of readdirSync('/proc')) {
    if (!/^\d+$/.test(d)) continue;
    let argv;
    try { argv = readFileSync(`/proc/${d}/cmdline`, 'utf8').split('\0'); } catch { continue; }
    if (basename(argv[0] || '') === 'Xvfb' && argv.includes(display)) return Number(d);
  }
  return null;
}

// Every pid holding a LISTENING socket that answers 127.0.0.1:`port` - read from
// /proc/net/tcp{,6} and each process's fds, so "the port answers" can be told apart
// from "MY process answers it". [] when nothing listens; [0] when something does
// and its owner cannot be read.
// ⚠️ THE QUESTION IS 127.0.0.1, NOT "THE PORT", BECAUSE THAT IS WHERE EVERY CLIENT
// CONNECTS: websockify to 127.0.0.1:<vnc_port>, the funnel to 127.0.0.1:<web_port>.
// A listener on 127.0.0.1 or a wildcard (0.0.0.0, ::, ::ffff:127.0.0.1) answers it;
// one on ::1 answers neither. An x11vnc holding only ::1 - its 127.0.0.1 bind refused
// by another process, or lost in a race with another x11vnc (setupLock) - would pass
// a check that counted ::1, and its share's websockify would then proxy to whatever
// holds 127.0.0.1: another share's display, or nothing. Two shares that both pass
// start two websockifys on one port, and two listen()s at the same instant on one
// port can both get EADDRINUSE (measured 2026-11-06, Linux 7.0: 12 of 2000).
// share.test.mjs pins both: a listener on ::1 alone, and a share whose x11vnc can take
// only ::1.
const ANSWERS_V4 = new Set(['0100007F', '00000000']);
const ANSWERS_V6 = new Set(['00000000000000000000000000000000', '0000000000000000FFFF00000100007F']);
export function listenerOwners(port) {
  const hex = port.toString(16).toUpperCase().padStart(4, '0');
  const inodes = new Set();
  for (const [f, answers] of [['/proc/net/tcp', ANSWERS_V4], ['/proc/net/tcp6', ANSWERS_V6]]) {
    let lines = [];
    try { lines = readFileSync(f, 'utf8').trim().split('\n').slice(1); } catch {}
    for (const l of lines) {
      const c = l.trim().split(/\s+/);
      const [addr, p] = c[1].split(':');
      if (c[3] === '0A' && p === hex && answers.has(addr)) inodes.add(c[9]);
    }
  }
  if (!inodes.size) return [];
  const owners = [];
  for (const d of readdirSync('/proc')) {
    if (!/^\d+$/.test(d)) continue;
    let fds;
    try { fds = readdirSync(`/proc/${d}/fd`); } catch { continue; }
    for (const fd of fds) {
      let t;
      try { t = readlinkSync(`/proc/${d}/fd/${fd}`); } catch { continue; }
      const m = /^socket:\[(\d+)\]$/.exec(t);
      if (m && inodes.has(m[1])) { owners.push(Number(d)); break; }
    }
  }
  return owners.length ? owners : [0];
}

export function readJson(path) {
  try { return JSON.parse(readFileSync(path, 'utf8')); } catch { return null; }
}
export function writeJson600(path, obj, { exclusive = false } = {}) {
  if (exclusive) { writeFileSync(path, JSON.stringify(obj, null, 1), { mode: 0o600, flag: 'wx' }); return; }
  const tmp = `${path}.tmp`;
  writeFileSync(tmp, JSON.stringify(obj, null, 1), { mode: 0o600 });
  chmodSync(tmp, 0o600);
  renameSync(tmp, path);
}

// ── teardown ─────────────────────────────────────────────────────────────────
const cmdlineOf = pid => { try { const s = readFileSync(`/proc/${pid}/cmdline`, 'utf8'); return s ? s.split('\0') : null; } catch { return null; } };
// ⚠️ A zombie's cmdline is EMPTY: an exited child of the process that started it (the
// `share` client tearing down its own failed start) stays in /proc until reaped, and
// reading it as alive turned a clean teardown into "ALIVE".
const sleepSync = ms => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);

// Kill one process this share started, and its process group (websockify forks a
// child per connection). ⚠️ ONLY after its command line proves it is ours - a pid
// in a state file can have been reused by anything since - and never by pattern.
function killOurs(pid, isOurs) {
  const argv = pid ? cmdlineOf(pid) : null;
  if (!argv || !isOurs(argv)) return 'gone';
  for (const [sig, graceMs] of [['SIGTERM', 3000], ['SIGKILL', 2000]]) {
    try { process.kill(-pid, sig); } catch { try { process.kill(pid, sig); } catch {} }
    for (let t = 0; t < graceMs && cmdlineOf(pid); t += 100) sleepSync(100);
    if (!cmdlineOf(pid)) return sig === 'SIGTERM' ? 'stopped' : 'killed';
  }
  return 'ALIVE';
}
const named = (name, ...has) => argv => argv.some(a => basename(a).startsWith(name)) && has.every(h => argv.includes(h));

/**
 * Tear down the share `st` describes, synchronously (the driver calls it from an
 * 'exit' handler, where nothing asynchronous runs), from the record IN MEMORY - so the
 * `share` client can tear down a half-built share whose file is already gone.
 *   runDir     the run dir, whose password file goes with the share
 *   cmd        the tailscale command (tailscaleCommand), never one from a file
 *   killTimer  false when the caller IS the timer
 * ⚠️ THE ORDER IS THE SETUP'S IN REVERSE, AND IT IS LOAD-BEARING:
 *   1. the funnel - the one step that makes anything public - goes FIRST, so a
 *      teardown cut short (a stop timeout, an x11vnc hung on SIGTERM) has already
 *      taken the page off the internet;
 *   2. x11vnc and websockify;
 *   3. the expiry timer LAST, and only when everything before it is done: a timer
 *      killed ahead of a failing funnel call leaves a public page with nothing that
 *      would ever retry.
 * The funnel is touched only when this share asked for it (`st.funnel`) AND what it
 * serves is still this share's: a port nobody listens on, or one this share's
 * websockify holds. Another agent's later share on the same port is left alone.
 */
export function teardown(st, { runDir, cmd, cmdError, killTimer = true } = {}) {
  const out = { torn: true, id: st.id, processes: {} };
  if (st.funnel) {
    try {
      if (!cmd) throw new Error(cmdError || 'no tailscale command');
      if (funnelServes(cmd, st.funnel_port)) {
        const owners = listenerOwners(st.web_port);
        if (owners.length === 0 || owners.includes(st.pids?.websockify)) {
          const off = funnelOff(cmd, st.funnel_port);
          out.funnel_off = !funnelServes(cmd, st.funnel_port);
          if (!out.funnel_off) out.funnel_error = `the funnel still serves port ${st.funnel_port} after 'funnel --https=${st.funnel_port} off' (exit ${off.status}: ${String(off.stderr || '').trim().split('\n')[0]})`;
        } else {
          out.funnel_off = true;
          out.funnel_note = `port ${st.funnel_port} is still on, serving 127.0.0.1:${st.web_port} for pid ${owners.join(',')} - another share's, left alone`;
        }
      } else out.funnel_off = true;
    } catch (e) { out.funnel_off = false; out.funnel_error = e.message; }
  }
  if (st.pids?.x11vnc) out.processes.x11vnc = killOurs(st.pids.x11vnc, named('x11vnc', '-rfbport', String(st.vnc_port)));
  if (st.pids?.websockify) out.processes.websockify = killOurs(st.pids.websockify, named('websockify', `127.0.0.1:${st.web_port}`));
  const pw = join(runDir, PASSWORD_FILE);
  rmSync(pw, { force: true });
  out.password_removed = !existsSync(pw);
  out.clean = out.funnel_off !== false && !Object.values(out.processes).includes('ALIVE');
  if (killTimer && out.clean && st.pids?.timer) out.processes.timer = killOurs(st.pids.timer, named('signin.mjs', 'unshare', st.id));
  return out;
}

/**
 * Tear down the share recorded in `runDir`. Idempotent: with no share recorded it
 * does nothing and says so. The record is removed only once the teardown was clean -
 * otherwise it is the only thing left that knows the share exists, and the next
 * teardown (the timer, the driver's exit, a second `unshare`) works from it.
 *   cfg        the parsed config.json, for the tailscale command
 *   onlyId     tear down only the share with this id (the expiry timer)
 * ⚠️ A run dir that is not a 0700 directory owned by this user is not read at all:
 * its path is predictable, so a record in someone else's directory is a planted one.
 */
export function stopShare(runDir, { cfg, onlyId, killTimer = true } = {}) {
  let ls;
  try { ls = lstatSync(runDir); } catch { return { torn: false, reason: 'no run dir' }; }
  if (!ls.isDirectory() || ls.uid !== process.getuid() || (ls.mode & 0o077)) {
    return { torn: false, refused: true, reason: `${runDir} is not a 0700 directory owned by this user - not reading a share record from it` };
  }
  const statePath = join(runDir, STATE_FILE);
  const st = readJson(statePath);
  if (!st) return { torn: false, reason: 'no share is recorded in this run dir' };
  if (onlyId && st.id !== onlyId) return { torn: false, reason: `the recorded share is ${st.id}, not ${onlyId}` };
  let cmd = null, cmdError;
  try { cmd = tailscaleCommand(cfg); } catch (e) { cmdError = e.message; }
  const out = teardown(st, { runDir, cmd, cmdError, killTimer });
  if (out.clean) rmSync(statePath, { force: true });
  return out;
}

// Everything in the run dir except the share's record and log - for a driver that
// exits with a share it could not tear down: the throwaway profile, shots and code
// still go, and the record stays for the teardown that will retry.
export function wipeAllButRecord(runDir) {
  for (const e of readdirSync(runDir)) if (e !== STATE_FILE && e !== LOG_FILE) rmSync(join(runDir, e), { recursive: true, force: true });
}
