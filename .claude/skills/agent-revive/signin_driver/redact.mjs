// The two secrets this driver handles, and the ONE place either of them is allowed
// to be turned back into text.
//
// ⚠️ WHY THIS IS A SEPARATE, DEPENDENCY-FREE MODULE AND MUST STAY ONE.
// The driver imports playwright and launches a browser; nothing in here does. That
// split is what lets `redaction.test.mjs` run on a bare `node` with no
// `node_modules`, no browser and no network - so the assertion that a password
// never reaches an output path is checked on EVERY clone, not only on a host where
// someone remembered to install 658 MB of Chromium. A check that can only run where
// the install is complete is a check that stops running.
//
// ⚠️ THE REDACTOR IS APPLIED AT THE WIRE, NOT AT EACH CALL SITE (see wire.mjs).
// Redacting per call site means the next `case` a maintainer adds to the driver's
// switch is unredacted by default, and nothing goes red. Redacting the single
// string that leaves the process means the default is safe and a new command
// inherits it.

// An OAuth "paste this into Claude Code" code is two url-safe segments joined by a
// `#`. Both segments are long, which is what keeps this from matching ordinary
// prose containing a hash (`#1`, `foo#bar`).
//
// ⚠️ THE 16-CHARACTER FLOOR IS A GUESS, NOT A MEASUREMENT - no real code's segment
// lengths are on record - AND ITS TWO FAILURE MODES ARRIVE TOGETHER AND HIDE EACH
// OTHER. If a real second segment is ever
// shorter than 16, this one constant makes `savecode` report `saved:false` AND stops
// the code being redacted on the wire - and the first failure (an operator hunting a
// code that "did not appear") is loud, so nobody looks for the second. If you ever
// see a code with this pattern failing to match, lower the floor AND say so here
// with the length you measured; do not lower it on a hunch, because the cost in the
// other direction is every `inspect` of a page containing a long hyphenated token
// coming back mangled, which makes the page unreadable to the agent driving it.
export const CODE_RE = /([A-Za-z0-9_-]{16,})#([A-Za-z0-9_-]{16,})/;

/**
 * Build the redactor for a set of passwords.
 *
 * ⚠️ SECRETS ARE REPLACED WITH split/join, NEVER WITH A RegExp. A password is
 * arbitrary text: `a.b*c` compiled as a pattern matches things that are not the
 * password and, far worse, fails to match the password itself - so a `new
 * RegExp(pw)` redactor leaks exactly the passwords that contain regex
 * metacharacters, which is the class humans pick. There is no escaping bug
 * available to a literal split.
 *
 * ⚠️ FALSY AND EMPTY SECRETS ARE DROPPED. `''.split()` on an empty needle inserts
 * the marker between every character, which both destroys the output and looks
 * like a redactor working very hard. An entry with no password is a defect in the
 * pool file (SKILL.md step 5, case 9), not a secret to redact.
 *
 * ⚠️ EACH SECRET IS ALSO REGISTERED IN ITS JSON-ESCAPED FORM, AND THAT IS NOT
 * BELT-AND-BRACES - IT IS THE LEAK. The redactor runs over the SERIALISED reply,
 * because that is the single string leaving the process (wire.mjs). By then
 * `JSON.stringify` has rewritten `\` as `\\`, `"` as `\"` and every control
 * character as `\uXXXX`, so the plain needle no longer occurs in the text and a
 * password containing any of those characters passes straight through - redacted
 * in appearance, intact on the wire. Registering `JSON.stringify(pw).slice(1, -1)`
 * alongside the raw form closes it, in exactly the direction humans pick
 * passwords. `redaction.test.mjs` pins both forms; its identity control is what
 * found this.
 */
export function makeRedactor(secrets) {
  const raw = (secrets || []).filter(s => typeof s === 'string' && s.length > 0);
  const needles = [...new Set(raw.flatMap(s => [s, JSON.stringify(s).slice(1, -1)]))];
  return function redact(s) {
    let out = String(s);
    for (const n of needles) out = out.split(n).join('[PW]');
    return out
      .replace(new RegExp(CODE_RE, 'g'), '[CODE]')
      .replace(/code=[A-Za-z0-9_%-]{16,}/g, 'code=[R]');
  };
}

/** The first OAuth code in a blob of page text, or null. Never logged by a caller. */
export function extractCode(text) {
  const m = String(text || '').match(CODE_RE);
  return m ? m[0] : null;
}

/**
 * Does this `fill` command refuse its value? The driver's fill case asks this and
 * throws when it is true; `redaction.test.mjs` exercises it directly, which is why
 * the predicate lives in this dependency-free module rather than in driver.mjs -
 * driver.mjs launches a browser at import time and cannot be loaded by a test.
 *
 * ⚠️ `!cmd.secret` IS THE WHOLE FUNCTION, AND LEAVING IT OUT BREAKS THE ONE ROUTE
 * THE GUARD EXISTS TO PROTECT. The guard refuses a password handed to the driver on
 * a COMMAND LINE (`--value`), because by the time it arrives the password is already
 * in a shell history and a transcript and nothing can unsay it. A value that came
 * from `--secret` was read out of the pool file inside the driver process and
 * never touched a command line - so it is the SUPPORTED route, not the refused one.
 * Written without this half, the guard matches the password the secret route just
 * resolved and refuses it: the driver can then never type a password at all, and the
 * failure arrives as "refusing --value" on a command that passed no --value, which
 * reads as a broken credential file rather than a broken guard (measured live
 * 2026-09-16).
 *
 * It can only catch a password this driver already knows about - the pool's -
 * and that is the case that matters.
 */
export function refusesValue(cmd, accounts, value) {
  if (cmd && cmd.secret) return false;
  return (accounts || []).some(a => a && typeof a.password === 'string' && a.password.length > 0 && a.password === value);
}
