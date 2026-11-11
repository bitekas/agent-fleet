// fleet-where.mjs - the one way a Node script in this fleet tree asks where an
// install file lives. A skill's SPECIFIC files (config.json, CONTEXT.md) live in
// the install context, never beside the script, and `fleet where <skill> <file>`
// is the one resolver of that context. A Node script never re-derives it and
// never keeps its own copy of this lookup: two copies are how two readers end up
// on two config files with nothing to say so.
//
// Load it from the script's REALPATH, never by a static relative import:
//
//   const HERE = dirname(fileURLToPath(import.meta.url));
//   const { configFile } = await import(pathToFileURL(
//     join(realpathSync(HERE), '..', '..', '..', 'lib', 'fleet-where.mjs')).href);
//
// An agent reaches a fleet skill through a personal skill link. Node resolves a
// static specifier against the module's URL, which is the link path whenever
// symlinks are preserved (--preserve-symlinks, NODE_PRESERVE_SYMLINKS=1), and
// three directories above the link there is no fleet: the static form dies with
// ERR_MODULE_NOT_FOUND there, the realpath form loads (measured on Node 22).
//
// Node built-ins only. The agent-revive sign-in driver's pure half imports this
// through profile.mjs and must run on a clone with no `npm ci`; fleet-where.test.mjs
// pins the import list.
//
// Properties, each load-bearing:
//   * FLEET_BIN, when set, is the fleet command (a test points it at a fake);
//     otherwise it is bin/fleet in THIS fleet tree, found through this file's
//     realpath, so a canary tree resolves with its own code. It is run by path,
//     never looked up on PATH: a service unit starts with a bare PATH that holds
//     no `fleet`.
//   * A fleet that cannot run, exits non-zero or prints no path THROWS, naming
//     the command and relaying its last stderr line. It never falls back to a
//     guessed file: a guessed config is another install's, read with nothing on
//     the page to say so. Each caller turns the throw into its own refusal
//     (exit 2 for a script that has not started its work yet).
//   * The path is the LAST line of the output, made absolute.

import { realpathSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const FLEET_ROOT = resolve(realpathSync(dirname(fileURLToPath(import.meta.url))), '..');

/** The fleet command: $FLEET_BIN, else bin/fleet in this fleet tree. */
const fleetBin = () => process.env.FLEET_BIN || join(FLEET_ROOT, 'bin', 'fleet');

/**
 * `fleet where <skill> <file>`: the absolute path of an install file. Throws an
 * Error naming the command when it cannot run, exits non-zero, or prints no path.
 */
export function fleetWhere(skill, file) {
  const bin = fleetBin();
  const how = `\`${bin} where ${skill} ${file}\``;
  const r = spawnSync(bin, ['where', skill, file], { encoding: 'utf8', timeout: 60000, stdio: ['ignore', 'pipe', 'pipe'] });
  const last = (s) => String(s || '').trim().split('\n').pop();
  if (r.error) throw new Error(`cannot run ${how} (${r.error.code || r.error.message})`);
  if (r.status !== 0) throw new Error(`${how} exited ${r.status}: ${last(r.stderr) || 'no output'}`);
  const p = last(r.stdout);
  if (!p) throw new Error(`${how} printed no path`);
  return resolve(p);
}

/**
 * Which config.json a skill's script reads: $<envVar> when set (resolved against
 * the cwd), and then the fleet is not asked; else `fleet where <skill> config.json`.
 * A failure throws fleetWhere's message with the variable that bypasses it.
 */
export function configFile(skill, envVar) {
  if (process.env[envVar]) return resolve(process.env[envVar]);
  try {
    return fleetWhere(skill, 'config.json');
  } catch (e) {
    throw new Error(`${e.message}; set ${envVar} to name the config file directly`);
  }
}
