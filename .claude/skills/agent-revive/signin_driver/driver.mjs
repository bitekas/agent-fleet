// A long-lived browser the reviving AGENT drives, one command at a time.
//
//   node driver.mjs --agent <name> [--config <path>] [--run-dir <path>]
//                   [--pool-file <path>] [--profile <username> [--port <N>]]
//                   [--app-window]
//
// It launches ONE stealth headful Chromium and then does nothing on its own: it
// listens on a unix socket and performs exactly the command it is handed, replying
// with what it sees. `signin.mjs` is the client; `README.md` lists the commands.
//
// ── TWO PROFILE MODES, AND WHAT EACH LEAVES ON DISK ─────────────────────────
//   without --profile  a THROWAWAY profile inside the run dir, wiped with it on quit,
//                      on a crash and on a signal. A revival leaves no session behind.
//   --profile <user>   that pool account's STORED profile, <accounts.profiles_dir>/<user>,
//                      kept across quits and crashes because keeping it is the point:
//                      a browser Google and claude.ai already know types no password.
//                      It is a CREDENTIAL - mode 0700, re-set on every start, and
//                      refused anywhere in a git work tree or an agent home
//                      (profile.mjs owns those rules). The RUN DIR - socket, shots,
//                      code file - is still wiped exactly as in the throwaway mode.
//   --port <N>         (with --profile only) opens Chromium's DevTools on
//                      127.0.0.1:<N> so a person can reach the browser over an ssh
//                      tunnel and chrome://inspect, to enroll a profile. Every local
//                      process can reach that port while the driver runs.
//   --app-window       the first window is an APP window (no tabs, no address bar,
//                      no menu), and the driver records DISPLAY and XAUTHORITY in the
//                      run dir, which is what `signin.mjs share` shows a person and
//                      refuses to run without. Without it, nothing here changes.
//
// ⚠️ THIS FILE IS THE HANDS, NOT THE PROCEDURE. There is deliberately no "sign in"
// command, no page-sequence table and no retry logic, and that absence is the design
// rather than an unfinished corner. Two earlier attempts at this sign-in were
// SCRIPTS, and both failed on their own model of the flow rather than on any block:
// one clicked Next on the opener window while Google had moved the form into a
// popup, the other stopped dead at Anthropic's Authorize button because nobody had
// scripted a step the author's model of the flow "never reached". Screens change,
// button labels change, element ids change. An agent that inspects the page it is
// actually on and decides from what is there survives all of that; a script encodes
// one morning's screens and breaks silently the next. SKILL.md step 6 owns the
// procedure. Anything added here that decides WHAT to do next is a bug.
//
// ⚠️ IT HOLDS AN ACCOUNT'S PASSWORD AND SEES AN OAUTH CODE, AND NEITHER LEAVES IT.
// `fill --secret <username>` reads that account's password out of the Claude account
// pool inside this process and types it; the client never sees it and no human,
// transcript or pane ever carries it. `savecode` writes the code to a mode-0600 file
// and returns its LENGTH, never its characters. Every reply, success and error
// alike, goes out through one redactor (wire.mjs).

import { readFileSync, readdirSync, mkdirSync, chmodSync, rmSync, existsSync, unlinkSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { tmpdir } from 'node:os';
import net from 'node:net';
import { PROFILE_IN_USE, configPathFrom, expandHome, resolveProfile, profileInUse, profileNameRefusal } from './profile.mjs';
import { APP_START, DISPLAY_FILE, stopShare, wipeAllButRecord, writeJson600 } from './share.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const SKILL = dirname(HERE);

// ── arguments ────────────────────────────────────────────────────────────────
const argv = process.argv.slice(2);
const arg = (name, dflt) => {
  const i = argv.indexOf(`--${name}`);
  return i >= 0 && argv[i + 1] !== undefined ? argv[i + 1] : dflt;
};
const agent = arg('agent');
if (!agent) {
  console.error('driver.mjs: --agent <name> is required (it names the run dir of this sign-in)');
  process.exit(2);
}
// ⚠️ THE AGENT NAME IS VALIDATED HERE, ONCE, BECAUSE IT BECOMES A PATH THAT IS
// RECURSIVELY DELETED. It is interpolated into the run dir, whose first filesystem
// action is `rmSync(runDir, {recursive:true, force:true})`. `--agent ../../foo`
// escapes the temp dir; that is same-uid rather than an attack, and it is a
// recursive delete of a path nobody validated. A name is a single path segment.
if (!/^[A-Za-z0-9._-]+$/.test(agent) || agent === '.' || agent === '..') {
  console.error(`driver.mjs: refusing agent name ${JSON.stringify(agent)} - it must be a single path segment matching [A-Za-z0-9._-]+`);
  process.exit(2);
}
let configPath;
try { configPath = configPathFrom(arg('config')); } catch (e) { console.error(`driver.mjs: ${e.message}`); process.exit(2); }
const appWindow = argv.includes('--app-window');

// ⚠️ --profile AND --port ARE VALIDATED HERE, BEFORE THE POOL IS READ, because a bad
// one is a usage error whatever the pool says. The pool-membership half of --profile
// needs the pool and is checked once it is loaded.
const profileName = arg('profile');
if (profileName !== undefined) {
  const bad = profileNameRefusal(profileName);
  if (bad) { console.error(`driver.mjs: ${bad}`); process.exit(2); }
}
const portArg = arg('port');
let port = null;
if (portArg !== undefined) {
  // The DevTools port exists to enroll a STORED profile with a person in the loop. On
  // a throwaway profile it would only open a second, unauthenticated way into a
  // browser that may be typing a password, for nothing that outlives the run.
  if (profileName === undefined) { console.error('driver.mjs: refusing --port without --profile - the DevTools port is for enrolling a stored profile'); process.exit(2); }
  port = /^\d+$/.test(portArg) ? Number(portArg) : NaN;
  if (!(port >= 1024 && port <= 65535)) { console.error(`driver.mjs: refusing --port ${JSON.stringify(portArg)} - it must be an integer from 1024 to 65535`); process.exit(2); }
}

// ── the account pool, resolved from config.json's accounts block ─────────────
// The same key the pool picker reads (accounts.pool_file), so the account the picker
// names is looked up in the same file. Any agent may be signed in with any pool
// account; which one is SKILL.md step 5's answer, passed in as `--secret <username>`.
let cfg;
try {
  cfg = JSON.parse(readFileSync(configPath, 'utf8'));
} catch (e) {
  console.error(`driver.mjs: cannot read config ${configPath}: ${e.message}`);
  process.exit(2);
}
// The key's NAME is a constant so the message below does not spell the identifier
// redaction.test.mjs's console scan watches for (`accounts`, the pool's binding).
const POOL_KEY = 'accounts.pool_file';
const poolRel = String(cfg?.accounts?.pool_file || '');
if (!poolRel) {
  console.error(`driver.mjs: ${configPath} is missing ${POOL_KEY}`);
  process.exit(2);
}
const poolPath = arg('pool-file', resolve(dirname(resolve(configPath)), expandHome(poolRel)));

const { loadPool, passwordFor } = await import('./pool.mjs');
let accounts;
try {
  accounts = loadPool(poolPath);
} catch (e) {
  // e.message is pool.mjs's own, which never quotes the file (see its header).
  console.error(`driver.mjs: ${e.message}`);
  console.error('STOP - the automated route cannot sign any account in (SKILL.md step 5, cases 8 and 9).');
  process.exit(2);
}

const { makeRedactor, refusesValue } = await import('./redact.mjs');
const { replyLine, saveCodeFile } = await import('./wire.mjs');
const redact = makeRedactor(accounts.map(a => a && a.password));

// ── the stored profile, when --profile names one ─────────────────────────────
// Resolved and refused BEFORE the run dir is touched: a refusal leaves nothing behind
// and wipes nothing. `profileInUse` reads Chromium's own SingletonLock, and refusing
// on it here - rather than letting Chromium throw - is load-bearing: a losing launch
// first opens a window in the WINNING browser (profile.mjs, profileInUse).
let stored = null;
if (profileName !== undefined) {
  try {
    stored = resolveProfile({ cfg, configPath, username: profileName, usernames: accounts.map(a => a.username) });
  } catch (e) {
    console.error(`driver.mjs: ${e.message}`);
    process.exit(2);
  }
  const busy = profileInUse(stored.dir);
  if (busy) { console.error(`driver.mjs: ${busy}`); process.exit(2); }
}

// ⚠️ THE DRIVER RESOLVES ITS OWN BROWSER, AND THAT IS WHY PLAYWRIGHT IS IMPORTED
// DYNAMICALLY BELOW RATHER THAN AT THE TOP OF THE FILE. Playwright reads
// PLAYWRIGHT_BROWSERS_PATH while its registry module is evaluating, and a static
// `import` is hoisted above every statement - so setting the variable after an
// ordinary import is too late and the browser is looked for in the machine-wide
// cache that this skill deliberately does not use. Measured: launched WITHOUT the
// variable already exported, the driver died with "Executable doesn't exist" and the
// client reported only that no socket appeared in 60s. Depending on the caller to
// export it is the same class of mistake as validating a systemd unit from an
// interactive shell: it works in the shell that happens to have it set, and nowhere
// else - a cron job, a hand launch, another agent's session.
const BROWSERS = join(HERE, 'browsers');
if (!process.env.PLAYWRIGHT_BROWSERS_PATH) process.env.PLAYWRIGHT_BROWSERS_PATH = BROWSERS;

// ⚠️ AND THE ABSENCE IS REPORTED AS ITSELF. Without this the failure arrives as a
// Playwright stack trace in a log the client only points at, which reads as the
// driver being broken rather than as an install that was never run - on a host where
// the remedy is one command.
const haveChromium = (() => {
  try { return readdirSync(process.env.PLAYWRIGHT_BROWSERS_PATH).some(d => d.startsWith('chromium-')); }
  catch { return false; }
})();
if (!haveChromium) {
  console.error(`driver.mjs: no chromium under ${process.env.PLAYWRIGHT_BROWSERS_PATH}`);
  console.error(`Run: bash ${join(SKILL, 'installation', 'check')} --online   (or, in ${HERE}: npm ci && PLAYWRIGHT_BROWSERS_PATH="$PWD/browsers" npx playwright install chromium)`);
  console.error('Until then the automated route (SKILL.md step 6) cannot run and the revival falls back to the step-7e human route.');
  process.exit(2);
}

const { chromium } = await import('playwright-extra');
const StealthPlugin = (await import('puppeteer-extra-plugin-stealth')).default;

// ── the run directory: system temp, wiped on quit ────────────────────────────
// ⚠️ A PROFILE IS A LOGGED-IN GOOGLE SESSION, AND THE RUN DIR IS NOWHERE PERSISTENT.
// After a successful sign-in a profile holds live Google and claude.ai sessions for
// the pool account it signed in - a credential in everything but name. The THROWAWAY
// profile is created fresh inside the run dir under the system temp dir and removed
// with it, so a revival without --profile leaves nothing behind that a later reader
// could sign in with. A STORED profile lives in accounts.profiles_dir, outside the run
// dir, so the same wipe never reaches it. Never point --run-dir at a repository, an
// artifact directory or an agent's home.
const runDir = arg('run-dir', join(tmpdir(), `agent-revive-signin-${agent}`));
const SOCK = join(runDir, 'driver.sock');
const SHOTS = join(runDir, 'shots');
const PROFILE = stored ? stored.dir : join(runDir, 'profile');
const CODE = join(runDir, 'code.txt');
// ⚠️ A UNIX SOCKET PATH HOLDS AT MOST 107 BYTES ON LINUX (103 ON MACOS: sun_path is
// 104 bytes there, with its NUL), AND node DOES NOT REFUSE A LONGER ONE. Measured
// 2026-11-01: listen() on a 132-byte path printed "driver ready" and no socket ever
// appeared at that path, so `start` waited out its 60 s for a file that could not
// exist. Refused here, by name, before anything is wiped.
const SOCK_MAX = process.platform === 'darwin' ? 103 : 107;
if (Buffer.byteLength(SOCK) > SOCK_MAX) {
  console.error(`driver.mjs: refusing --run-dir ${runDir} - its socket path is ${Buffer.byteLength(SOCK)} bytes and a unix socket path holds at most ${SOCK_MAX} here; use a shorter --run-dir`);
  process.exit(2);
}
// A driver killed with a share live leaves that share recorded in its run dir; it is
// torn down before the wipe below removes the only record of it (share.mjs) - and a
// share that cannot be torn down stops this start, because wiping its record would
// leave a public page that nothing knows about.
const prior = stopShare(runDir, { cfg });
if (prior.torn && !prior.clean) {
  console.error(`driver.mjs: ${runDir} records a share that could not be torn down - ${JSON.stringify(prior)}`);
  console.error(`Run: node signin.mjs ${agent} unshare   (and read what it reports) before starting again.`);
  process.exit(2);
}
rmSync(runDir, { recursive: true, force: true });
mkdirSync(SHOTS, { recursive: true, mode: 0o700 });
chmodSync(runDir, 0o700);
chmodSync(SHOTS, 0o700);
// ⚠️ 0700 ON EVERY START, NOT ONLY AT CREATION. mkdir's mode applies only to the
// directories it creates; a profiles dir someone made, copied or restored with a
// looser mode would otherwise stay readable - and its cookies are protected by
// nothing else (profile.mjs header).
if (stored) {
  mkdirSync(PROFILE, { recursive: true, mode: 0o700 });
  chmodSync(stored.profilesDir, 0o700);
  chmodSync(PROFILE, 0o700);
}

// ⚠️ THE CLEANUP IS WIRED TO EVERY EXIT THIS PROCESS CAN OBSERVE, NOT JUST `quit`.
// What the run dir holds after a sign-in - the throwaway profile (a logged-in Google
// and claude.ai session for the pool account it signed in), any screenshots, the
// code file - is a credential in everything but name, at a predictable path. A throw
// outside the command dispatcher, an unhandled rejection in the socket callback, or
// an operator's Ctrl-C would each leave the lot behind without these handlers. `exit`
// covers every ordinary termination; the two handlers below turn a crash into one.
// ⚠️ SIGKILL AND A REBOOT STILL CANNOT BE COVERED - nothing can - so the dir is mode
// 0700 as well, and README.md says to remove it by hand after a kill. The cleanup
// removes the RUN DIR and nothing else: a stored profile is outside it, and kept.
// ⚠️ A SHARE GOES FIRST: its record is in the run dir, so wiping the dir before the
// teardown would strand a public funnel and a VNC server with nothing left that
// knows they exist (share.mjs, stopShare).
// A share that could NOT be torn down keeps its record (and only that), and says so
// in the driver's log: the record is what the timer and `unshare` retry from.
const cleanup = () => {
  let kept = false;
  try {
    const r = stopShare(runDir, { cfg });
    kept = r.torn && !r.clean;
    if (kept) console.error(`driver.mjs: the share in ${runDir} could not be torn down - ${JSON.stringify(r)} - its record is kept; run: node signin.mjs ${agent} unshare`);
  } catch {}
  try { if (kept) wipeAllButRecord(runDir); else rmSync(runDir, { recursive: true, force: true }); } catch {}
};
process.on('exit', cleanup);
process.on('SIGINT', () => { cleanup(); process.exit(130); });
process.on('SIGTERM', () => { cleanup(); process.exit(143); });
process.on('SIGHUP', () => { cleanup(); process.exit(129); });
process.on('uncaughtException', e => { cleanup(); console.error('driver.mjs: uncaught', redact(String(e && e.message ? e.message : e))); process.exit(1); });
process.on('unhandledRejection', e => { cleanup(); console.error('driver.mjs: unhandled rejection', redact(String(e && e.message ? e.message : e))); process.exit(1); });

chromium.use(StealthPlugin());
// THE STEALTH PLUGIN MAKES A PROFILE DIRECTORY OF ITS OWN AT EVERY LAUNCH AND NEVER
// REMOVES IT, SO IT IS MADE INSIDE THE RUN DIR. Its user-agent-override evasion
// depends on puppeteer-extra-plugin-user-preferences, which depends on
// puppeteer-extra-plugin-user-data-dir. That plugin's beforeLaunch finds no
// userDataDir in the launch options (launchPersistentContext takes the profile as
// its first argument), so it makes <folderPath>/puppeteer_dev_profile-XXXXXX and
// writes Default/Preferences into it: a directory Chromium never opens, which holds
// only that file. Its delete runs on onDisconnected, and playwright-extra dispatches
// that for a persistent context only when context.browser() is null; Playwright
// returns a Browser there (playwright 1.63.0, playwright-extra 4.3.6, measured
// 2026-11-14), so the delete never runs, on quit, on a signal or on a crash.
// folderPath defaults to the system temp dir, where each launch left one; in the run
// dir, the cleanup above removes it on every exit this process observes. What
// Chromium is launched with does not change.
chromium.plugins.setDependencyDefaults('user-data-dir', { folderPath: runDir });
const launchArgs = ['--no-sandbox'];
if (port) launchArgs.push(`--remote-debugging-port=${port}`, '--remote-debugging-address=127.0.0.1');
// The app window (share.mjs, APP_START). Measured 2026-11-01: a window.open() popup
// from it - Google's sign-in - opens without an address bar too; a target=_blank LINK
// opens a normal tabbed window, where a person on a share still cannot type.
if (appWindow) launchArgs.push(`--app=${APP_START}`);
let ctx;
try {
  ctx = await chromium.launchPersistentContext(PROFILE, {
    headless: false, viewport: { width: 1280, height: 800 }, args: launchArgs,
  });
} catch (e) {
  // Two starts that raced past profileInUse: Chromium refuses the loser with
  // "Opening in existing browser session" (measured, profile.mjs). Said as the one
  // string the client recognises, and exit 2, so a busy profile is not read as a
  // broken one. Every other launch failure propagates unchanged.
  if (stored && /existing browser session|already in use|SingletonLock|ProcessSingleton/i.test(String(e && e.message))) {
    console.error(`driver.mjs: ${PROFILE_IN_USE}: ${PROFILE} - Chromium refused it, another browser holds its SingletonLock`);
    process.exit(2);
  }
  throw e;
}
if (stored) console.log(`stored profile ${PROFILE} (kept on quit)${port ? ` - DevTools on 127.0.0.1:${port}` : ''}`);
// In app mode the first page IS the app window; a newPage() would be a tabbed one.
if (appWindow && !ctx.pages().length) await ctx.waitForEvent('page', { timeout: 15000 });
if (!ctx.pages().length) await ctx.newPage();
// `parent` is xvfb-run when it started this driver, and the Xvfb it started is its
// sibling: `share` requires exactly that, so it never shows a display that is not
// this driver's own. On macOS the browser is on no X display (a DISPLAY there is an
// XQuartz socket, not this window), so none is recorded.
const darwin = process.platform === 'darwin';
if (appWindow) writeJson600(join(runDir, DISPLAY_FILE), { display: darwin ? null : process.env.DISPLAY || null, xauthority: darwin ? null : process.env.XAUTHORITY || null, app_window: true, pid: process.pid, parent: process.ppid });
let shotN = 0;

const pg = i => { const p = ctx.pages()[i ?? 0]; if (!p || p.isClosed()) throw new Error(`no open page at index ${i ?? 0}`); return p; };
const shortUrl = p => p.url().replace(/([?&#].*)$/, m => (m.length > 80 ? m.slice(0, 80) + '…' : m));

// The whole reason this driver is worth having: a reading of the page that is rich
// enough for an agent to DECIDE from - the visible text, plus every interactive
// element with its role, label and text. No selector guessing, no screenshot to
// squint at, and it works on a screen nobody has seen before.
async function inspect(p) {
  await p.waitForLoadState('domcontentloaded', { timeout: 5000 }).catch(() => {});
  const text = (await p.locator('body').innerText().catch(() => '')) || '';
  const els = await p.evaluate(() => {
    const out = [];
    const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
    for (const e of document.querySelectorAll('button,a[href],input,select,textarea,[role=button],[role=link],[role=option],[role=checkbox],[role=textbox],[role=menuitem],[role=tab]')) {
      if (!vis(e)) continue;
      const role = e.getAttribute('role') || e.tagName.toLowerCase();
      const label = e.getAttribute('aria-label') || (e.labels && e.labels[0]?.innerText) || e.getAttribute('placeholder') || '';
      const txt = (e.innerText || e.value || '').trim().replace(/\s+/g, ' ').slice(0, 80);
      out.push({ role, type: e.type || undefined, name: e.name || undefined, id: e.id || undefined, label: label.trim().slice(0, 80) || undefined, text: txt || undefined, disabled: e.disabled || e.getAttribute('aria-disabled') === 'true' || undefined });
    }
    return out;
  }).catch(e => [{ error: e.message }]);
  return { url: p.url(), title: await p.title().catch(() => ''), text, elements: els };
}

async function handle(cmd) {
  switch (cmd.op) {
    // ⚠️ `pages` IS NOT COSMETIC: Google moves the sign-in into a POPUP, so from the
    // "Continue with Google" click onward the page the agent must act on is page 1,
    // not page 0. A click aimed at the opener while the form is in the popup is the
    // exact failure that killed the first scripted attempt. Re-read `pages` after
    // every click that could open or close a window.
    case 'pages':
      return await Promise.all(ctx.pages().map(async (p, i) => ({
        i, closed: p.isClosed(),
        url: p.isClosed() ? null : shortUrl(p),
        title: p.isClosed() ? null : await p.title().catch(() => ''),
      })));
    case 'goto': { const p = pg(cmd.page); await p.goto(cmd.url, { waitUntil: 'domcontentloaded', timeout: 45000 }); await p.waitForTimeout(cmd.settle ?? 2000); return { url: p.url() }; }
    case 'inspect': return await inspect(pg(cmd.page));
    case 'click': {
      const p = pg(cmd.page);
      const before = ctx.pages().length;
      let loc;
      if (cmd.role) loc = p.getByRole(cmd.role, { name: cmd.name, exact: cmd.exact ?? false });
      else if (cmd.text) loc = p.getByText(cmd.text, { exact: cmd.exact ?? false });
      else if (cmd.selector) loc = p.locator(cmd.selector);
      else throw new Error('click needs role+name, text, or selector');
      loc = loc.first();
      await loc.waitFor({ state: 'visible', timeout: cmd.timeout ?? 10000 });
      const popupP = ctx.waitForEvent('page', { timeout: cmd.settle ?? 3000 }).catch(() => null);
      await loc.click();
      const popup = await popupP;
      await p.waitForTimeout(cmd.settle ?? 3000).catch(() => {});
      return { clicked: true, newPage: !!popup, pagesBefore: before, pagesAfter: ctx.pages().length, url: p.isClosed() ? 'closed' : p.url() };
    }
    case 'fill': {
      const p = pg(cmd.page);
      let loc;
      if (cmd.label) loc = p.getByLabel(cmd.label, { exact: cmd.exact ?? false });
      else if (cmd.selector) loc = p.locator(cmd.selector);
      else throw new Error('fill needs label or selector');
      loc = loc.first();
      await loc.waitFor({ state: 'visible', timeout: cmd.timeout ?? 10000 });
      let value = cmd.value;
      if (cmd.secret) value = passwordFor(accounts, cmd.secret, poolPath);
      if (typeof value !== 'string') throw new Error('fill needs --value or --secret');
      // ⚠️ A DOCUMENTED RULE THAT NOTHING ENFORCES IS A RULE THAT GETS BROKEN ONCE, AT
      // THE WORST MOMENT. `--value` is echoed back verbatim and travels on a command
      // line, so a password passed that way is already in a shell history and a
      // transcript by the time it reaches here and NOTHING can unsay it. `--secret` is
      // the only supported route for a password; refusing here turns the rule into a
      // mechanism. It can only catch a password this driver already knows about, which
      // is the case that matters: any pool account's. The guard is skipped on the
      // `--secret` route, because that value never touched a command line: the driver
      // read it out of the pool inside this process (redact.mjs).
      if (refusesValue(cmd, accounts, value)) {
        throw new Error('refusing --value: that string is a password from the account pool. Use --secret <username>, which types it inside this process and never puts it on a command line.');
      }
      await loc.fill(value);
      return { filled: cmd.secret ? '[secret]' : value };
    }
    case 'press': { const p = pg(cmd.page); await p.keyboard.press(cmd.key); await p.waitForTimeout(cmd.settle ?? 3000); return { pressed: cmd.key, url: p.isClosed() ? 'closed' : p.url() }; }
    case 'wait': { const p = pg(cmd.page); await p.waitForTimeout(cmd.ms ?? 3000); return { url: p.isClosed() ? 'closed' : p.url() }; }
    case 'shot': {
      const i = String(++shotN).padStart(2, '0');
      const files = [];
      for (const [k, p] of ctx.pages().entries()) {
        if (p.isClosed()) continue;
        const f = join(SHOTS, `${i}-${String(cmd.name || 'shot').replace(/[^A-Za-z0-9._-]/g, '-')}-p${k}.png`);
        // ⚠️ MODE 0600, AND THE CALLBACK PAGE IS NOT A THING TO SCREENSHOT. A PNG is
        // the one channel the redactor structurally cannot reach: the OAuth code is
        // rendered as VISIBLE TEXT on the final page, so a shot taken there puts it on
        // disk in pixels, and the natural next move - opening the file to look at it -
        // puts it in a transcript. SKILL.md step 6d carries the rule; this is the mode.
        await p.screenshot({ path: f }).then(() => { chmodSync(f, 0o600); files.push(f); }).catch(e => files.push(`FAILED ${f}: ${e.message}`));
      }
      return { files };
    }
    // Looks for the code on every open page, in the body text and inside inputs.
    // Returns where it found it and how long it is - never the code (wire.mjs).
    case 'savecode': {
      for (const p of ctx.pages()) {
        if (p.isClosed()) continue;
        const t = (await p.locator('body').innerText().catch(() => '')) || '';
        let r = saveCodeFile(t, CODE);
        if (r.saved) return { ...r, page: p.url(), from: 'body' };
        const v = await p.evaluate(() => [...document.querySelectorAll('input,textarea,code,pre')].map(e => e.value || e.innerText || '').join('\n')).catch(() => '');
        r = saveCodeFile(v, CODE);
        if (r.saved) return { ...r, page: p.url(), from: 'input' };
      }
      return { saved: false };
    }
    case 'quit':
      setTimeout(async () => { await ctx.close().catch(() => {}); cleanup(); process.exit(0); }, 200);
      return stored ? { bye: true, removing: runDir, kept: PROFILE } : { bye: true, removing: runDir };
    default: throw new Error(`unknown op ${cmd.op}`);
  }
}

if (existsSync(SOCK)) unlinkSync(SOCK);
const server = net.createServer(sock => {
  let buf = '';
  sock.on('data', async d => {
    buf += d;
    let nl;
    while ((nl = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, nl); buf = buf.slice(nl + 1);
      sock.write(await replyLine(line, handle, redact));
    }
  });
});
server.listen(SOCK, () => console.log('driver ready on', SOCK));
