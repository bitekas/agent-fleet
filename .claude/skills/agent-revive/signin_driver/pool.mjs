// Reading the Claude account pool, the one file this driver takes a password from.
//
// The pool (`accounts.pool_file` in the install's config.json) is a JSON LIST of
// { username, password, home_agent }, and it holds EVERY pool account's password,
// so the only things allowed out of this module are usernames, an entry's index,
// and a password handed to the caller in-process. `--pool-file` may instead name an
// agent's own credential file, which holds ONE { username, password } object; it is
// read as a one-entry pool.
//
// ⚠️ THE JSON PARSER'S OWN ERROR MESSAGE IS WITHHELD, AND THAT IS THE POINT OF THIS
// FILE. V8's `JSON.parse` quotes the text around the fault: a pool whose password
// was hand-edited in without its quotes fails as
//   Unexpected token 's', ..."password":sentinel-l"... is not valid JSON
// i.e. with a slice of the password in the message. The driver's caller logs a
// start-up failure to a permanent file that nothing redacts (its redactor does not
// exist yet - it is built FROM this file's passwords), so passing that message on
// writes a password to disk. Measured on node 22. redaction.test.mjs pins it: its
// control proves the raw parser message DOES carry the sentinel, and its assertion
// that this module's does not.
//
// Dependency-free (node: builtins only) so redaction.test.mjs runs on a clone with
// no install - the same rule as redact.mjs and wire.mjs.

import { readFileSync } from 'node:fs';

/**
 * Load the pool: a JSON list of entries, or a single entry object (an agent's own
 * credential file). Returns [{ username, password }] in file order; throws an Error
 * whose message names the path and the defect and never a byte of the file.
 */
export function loadPool(path) {
  let text;
  try {
    text = readFileSync(path, 'utf8');
  } catch (e) {
    throw new Error(`cannot read the pool file ${path} (${e && e.code ? e.code : 'read error'})`);
  }
  let raw;
  try {
    raw = JSON.parse(text);
  } catch {
    throw new Error(`the pool file ${path} is not valid JSON (the parser's message is withheld: it quotes the file)`);
  }
  if (raw && typeof raw === 'object' && !Array.isArray(raw)) raw = [raw];
  if (!Array.isArray(raw) || raw.length === 0) {
    throw new Error(`the pool file ${path} must be a non-empty JSON list of { username, password, home_agent }, or one { username, password } object`);
  }
  return raw.map((e, i) => {
    if (!e || typeof e !== 'object' || typeof e.username !== 'string' || e.username === '') {
      throw new Error(`pool entry ${i} in ${path} is not an object with a username`);
    }
    return { username: e.username, password: typeof e.password === 'string' ? e.password : '' };
  });
}

/**
 * The password for `username`, or an Error naming what is wrong with that entry.
 * Never returns another entry's password: a username in no entry, or in two, is a
 * refusal, because either way the field would be typed with a guess.
 */
export function passwordFor(accounts, username, path) {
  const hits = (accounts || []).filter(a => a && a.username === username);
  if (hits.length === 0) throw new Error(`no pool entry for that username in ${path}`);
  if (hits.length > 1) throw new Error(`that username has ${hits.length} entries in ${path} - which password is meant is ambiguous (SKILL.md step 5, case 10)`);
  if (!hits[0].password.trim()) throw new Error(`that pool entry has no password in ${path} (SKILL.md step 5, case 9)`);
  return hits[0].password;
}
