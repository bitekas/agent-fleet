// The STORED sign-in profile: where one lives, which names may have one, where one
// may never live, whether one is in use, and what a landing URL says about it.
//
// A stored profile is a Chromium user-data dir kept between revivals, one per pool
// account, at `<accounts.profiles_dir>/<username>`. Signed in once (SKILL.md, "Stored
// profiles"), it lets step 6 open a browser Google and claude.ai already know, so no
// password is typed and Authorize is the only click left.
//
// ⚠️ A STORED PROFILE IS A CREDENTIAL, AND EVERY RULE IN THIS FILE FOLLOWS FROM THAT.
// It holds live Google and claude.ai sessions for the account it is named after.
// Playwright launches Chromium with `--password-store=basic` (it is in Playwright's own
// default argument list, measured on 1.63.0), so the cookies are encrypted with
// Chromium's fixed built-in key, not a keyring: anyone who can read the directory can
// sign in as that account. The directory's mode (0700, set by the driver on every
// start) is therefore the whole protection, and WHERE it lives is the other half -
// `storageRefusal` below.
//
// Dependency-free (node: builtins, plus the fleet tree's own lib/fleet-where.mjs,
// itself builtins only), for the same reason as redact.mjs: `profiles.test.mjs`
// pins every rule here with no browser and no `npm ci`, and both the driver and the
// client import this one copy rather than each keeping their own. The one call out
// of process is `fleet where`, made only when no config path was given.

import { existsSync, realpathSync, readlinkSync, lstatSync } from 'node:fs';
import { dirname, join, resolve, basename, sep } from 'node:path';
import { homedir, hostname } from 'node:os';
import { fileURLToPath, pathToFileURL } from 'node:url';

// ⚠️ RESOLVED WITH EVERY SYMLINK FOLLOWED. An agent reaches this skill through a
// personal link, and the unresolved path is that link's directory: four levels up
// from there is the agent's config directory, not the fleet tree. The fleet's one
// `fleet where` lookup is loaded from there (its header says why not statically).
const HERE = realpathSync(dirname(fileURLToPath(import.meta.url)));
export const { fleetWhere } = await import(pathToFileURL(join(HERE, '..', '..', '..', '..', 'lib', 'fleet-where.mjs')).href);

// The key's NAME is a constant so a message can say it without spelling the pool's
// binding identifier, which redaction.test.mjs's console scan watches for.
export const PROFILES_KEY = 'accounts.profiles_dir';

// ⚠️ ONE STRING, IMPORTED BY BOTH SIDES. The driver prints it when a profile is held by
// another browser and the client reads it to report `busy` rather than `error`.
// Spelled twice, the two copies drift and a busy profile reads as a broken one.
export const PROFILE_IN_USE = 'profile in use';

export const expandHome = p => (p.startsWith('~/') ? join(homedir(), p.slice(2)) : p);

/**
 * The config path: an explicit flag, else $AGENT_REVIVE_CONFIG, else the install's
 * config.json through `fleet where`. A failing fleet throws, naming the remedy.
 */
export function configPathFrom(flagValue) {
  const given = flagValue || process.env.AGENT_REVIVE_CONFIG;
  if (given) return given;
  try {
    return fleetWhere('agent-revive', 'config.json');
  } catch (e) {
    throw new Error(`cannot resolve the install's config.json: ${e.message}; pass --config or set AGENT_REVIVE_CONFIG`);
  }
}

/**
 * Why `name` cannot name a profile directory, or null when it can.
 *
 * ⚠️ THE NAME BECOMES A PATH SEGMENT, SO IT IS VALIDATED THE WAY `--agent` IS: one
 * segment, a closed character set, never `.` or `..`. A pool username is an email,
 * so `@` and `+` are in the set; `/` is not, which is what keeps
 * `--profile ../../somewhere` from naming a directory outside `profiles_dir`.
 */
export function profileNameRefusal(name) {
  if (typeof name !== 'string' || !/^[A-Za-z0-9._@+-]+$/.test(name) || name === '.' || name === '..') {
    return `refusing profile name ${JSON.stringify(name)} - it must be a pool username and a single path segment matching [A-Za-z0-9._@+-]+`;
  }
  return null;
}

/** `accounts.profiles_dir` as an absolute path (relative to the config file's dir), or an Error. */
export function profilesDirOf(cfg, configPath) {
  const raw = String(cfg?.accounts?.profiles_dir || '');
  if (!raw) throw new Error(`${configPath} is missing ${PROFILES_KEY}`);
  return resolve(dirname(resolve(configPath)), expandHome(raw));
}

// The path with every symlink in it resolved, including one whose target does not
// exist yet. The directory itself may not exist (it is created at the first
// enrollment), so realpath alone would throw; and without resolving each component,
// a symlink from an innocent-looking path into a repository or an agent home walks
// straight past the refusal below - dangling or not.
function realish(p, depth = 0) {
  const abs = resolve(p);
  try { return realpathSync(abs); } catch {}
  const parent = dirname(abs);
  if (parent === abs || depth > 40) return abs;
  const here = join(realish(parent, depth + 1), basename(abs));
  let link = null;
  try { if (lstatSync(here).isSymbolicLink()) link = readlinkSync(here); } catch {}
  return link === null ? here : realish(resolve(dirname(here), link), depth + 1);
}

/**
 * Why a stored profile may not live under `dir`, or null when it may.
 *
 * ⚠️ A STORED PROFILE IN A REPOSITORY OR AN AGENT HOME IS A STANDING IMPERSONATION.
 * In a git work tree it is one `git add -A` (or one bare commit in a shared index)
 * from being pushed; in an agent's home it sits beside that agent's own files, where
 * a later reader takes it for the agent's and anything that sweeps the home sweeps
 * it. So both are refused before anything is created, whatever the config says. The
 * check runs on the symlink-resolved path, and it walks every ancestor for a `.git`
 * entry - a directory in a clone, a FILE in a worktree, both count.
 *
 * The agents home is the one the install's config names, `fleet.agents_home` - the
 * root every agent home sits under, read by tmux_triage.sh for the same purpose. ⚠️
 * WITHOUT IT THE CHECK REFUSES rather than skipping the rule: a guard that passes
 * whenever its input is missing is a guard that passes on every misconfigured host.
 */
export function storageRefusal(dir, { agentsHome } = {}) {
  if (!agentsHome) {
    return `refusing ${PROFILES_KEY} ${dir}: fleet.agents_home is not set, so whether it lies under an agents home cannot be checked`;
  }
  const real = realish(dir);
  const root = realish(expandHome(String(agentsHome)));
  if (real === root || real.startsWith(root + sep)) {
    return `refusing ${PROFILES_KEY} ${dir}: it resolves to ${real}, under an agents home - a stored profile there is a standing impersonation of an agent. Keep it with the organization's secrets.`;
  }
  for (let cur = real; ; cur = dirname(cur)) {
    if (existsSync(join(cur, '.git'))) {
      return `refusing ${PROFILES_KEY} ${dir}: it resolves to ${real}, inside the git work tree at ${cur} - a stored profile there is one commit away from being published.`;
    }
    if (dirname(cur) === cur) break;
  }
  return null;
}

/**
 * Resolve `--profile <username>` to its directory, or throw an Error saying why not.
 * `usernames` is the pool's list; the name must be in it, because a profile is ONE
 * pool account's sign-in and a directory named after anything else is a profile
 * nobody can account for.
 */
export function resolveProfile({ cfg, configPath, username, usernames }) {
  const bad = profileNameRefusal(username);
  if (bad) throw new Error(bad);
  if (!(usernames || []).includes(username)) {
    throw new Error(`refusing profile ${JSON.stringify(username)} - it is not a username in the account pool`);
  }
  const profilesDir = profilesDirOf(cfg, configPath);
  const refusal = storageRefusal(profilesDir, { agentsHome: cfg?.fleet?.agents_home });
  if (refusal) throw new Error(refusal);
  return { profilesDir, dir: join(profilesDir, username) };
}

/**
 * Who holds the profile, read from Chromium's own `SingletonLock` - a symlink whose
 * target is `<host>-<pid>` - or null when nobody does. Reads the link, never the
 * profile's contents.
 */
export function profileHolder(dir) {
  let target;
  try { target = readlinkSync(join(dir, 'SingletonLock')); } catch { return null; }
  const m = /^(.*)-(\d+)$/.exec(target);
  if (!m) return { host: target, pid: null, alive: true, here: false };
  const pid = Number(m[2]);
  let alive = false;
  try { process.kill(pid, 0); alive = true; } catch (e) { alive = !!(e && e.code === 'EPERM'); }
  return { host: m[1], pid, alive, here: m[1] === hostname() };
}

/**
 * The PROFILE_IN_USE message when another browser holds `dir`, or null.
 *
 * ⚠️ THIS IS CHECKED BEFORE A BROWSER IS LAUNCHED, AND LAUNCHING ANYWAY IS NOT HARMLESS.
 * Measured 2026-11-01 (Playwright 1.63.0, chromium-1243): a second launch on a profile
 * a live browser holds throws "Opening in existing browser session" within ~35 ms -
 * but Chromium first FORWARDS its command line to the running browser, which opens a
 * new about:blank window in it. On a live sign-in that window shifts `pages`, so the
 * agent driving it acts on the wrong page - the exact failure the driver's header
 * names. Refusing on the lock first means the second driver never reaches Chromium.
 * The driver still catches the throw, for two starts that race past this check.
 * A lock whose pid is dead on this host is stale and is not "in use": Chromium
 * reclaims it on launch.
 */
export function profileInUse(dir) {
  const h = profileHolder(dir);
  if (!h) return null;
  if (!h.here) return `${PROFILE_IN_USE}: ${dir} is locked by a browser on host ${h.host}${h.pid ? ` (pid ${h.pid})` : ''}`;
  if (h.alive) return `${PROFILE_IN_USE}: ${dir} is held by a live browser, pid ${h.pid} - quit that driver first (signin.mjs <agent> quit)`;
  return null;
}

// ── reading a landing URL: signed in, signed out, or unknown ─────────────────
// Used by `signin.mjs profiles-check`, the client, never by the driver: deciding what
// a page MEANS is procedure, and the driver is the hands (driver.mjs header).
//
// ⚠️ `unknown` IS A REAL ANSWER, NOT A GAP TO FILL. Each `in` below is a landing that
// only a signed-in browser reaches, and each `out` is a sign-in page; anything else -
// a Cloudflare interstitial on claude.ai's root, a consent page, an error, a redirect
// that has not happened yet - reads `unknown`. Widening `in` to "any claude.ai page
// that is not /login" would read the interstitial as signed in, which is the green
// this check must never give. The real test of a profile stays SKILL.md step 6:
// whether `goto` on the sign-in URL lands on Authorize.
export const SITES = [
  { site: 'claude', url: 'https://claude.ai/' },
  { site: 'google', url: 'https://myaccount.google.com/' },
];

export function siteState(site, url) {
  let u;
  try { u = new URL(url); } catch { return 'unknown'; }
  const host = u.hostname;
  const path = u.pathname;
  if (site === 'claude') {
    if (host !== 'claude.ai') return 'unknown';
    if (/^\/(login|logout)(\/|$)/.test(path)) return 'out';
    if (/^\/(new|chats?|recents|projects?|onboarding)(\/|$)/.test(path)) return 'in';
    return 'unknown';
  }
  if (site === 'google') {
    if (host === 'myaccount.google.com') return 'in';
    if (host === 'accounts.google.com' && /signin|ServiceLogin|InteractiveLogin|AccountChooser/i.test(path)) return 'out';
    if (host === 'www.google.com' && /^\/account\/about(\/|$)/.test(path)) return 'out';
    return 'unknown';
  }
  return 'unknown';
}

/** Where a page landed, without its query or fragment - for a report a person reads. */
export function landedAt(url) {
  let u;
  try { u = new URL(url); } catch { return String(url).slice(0, 80); }
  if (u.protocol === 'http:' || u.protocol === 'https:') return `${u.host}${u.pathname}`;
  return u.protocol === 'data:' ? 'data:' : u.href.slice(0, 80);
}
