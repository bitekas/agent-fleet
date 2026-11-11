#!/usr/bin/env node
// Offline guard on the driver's two secrets: a pool account's Google password and the
// OAuth code. No browser, no network, no node_modules, no real pool file - it runs
// on a bare `node` in a fresh clone, which is the point (see redact.mjs's header).
//
//   node redaction.test.mjs
//
// ── EXIT CODES: THREE, NEVER TWO ─────────────────────────────────────────────
//   0  PASS      every property holds
//   1  FAIL      at least one property is broken - each one is named
//   3  NO VERDICT  a CONTROL misbehaved, so the instrument is not established and
//                  this file refuses to pronounce at all. ⚠️ NO VERDICT IS NOT A
//                  SMALLER PASS: anything consuming this must treat non-zero as
//                  "not green" and must never map 3 onto 0 because nothing was
//                  reported.
//
// ── WHY THE CONTROLS ARE LOAD-BEARING AND MUST NOT BE REMOVED FOR TIDINESS ───
// THE ANSWER WE WANT HERE IS AN ABSENCE - "the password is not in this string" -
// and an absence is exactly what a fixture that never contained the password
// produces. The two states are indistinguishable from outside. So before any
// redaction assertion counts, the IDENTITY control runs the SAME payload through
// the SAME wire with a do-nothing redactor and requires the secret to come out.
// If that control ever passes (no leak with redaction disabled), the payloads have
// stopped carrying the secret, every "redacted!" assertion below has become
// vacuous, and this file exits 3 rather than green.
//
// The second control is about the METHOD: the password fixtures deliberately
// contain regex metacharacters, and the test asserts that compiling one as a
// pattern does NOT match itself. That is the measurement behind redact.mjs using
// split/join - a `new RegExp(pw)` redactor leaks exactly the passwords that contain
// the characters humans put in passwords.
//
// The third is STRUCTURAL and it is the one that stops the security argument
// rotting: every byte the driver writes to a client must leave through
// `replyLine`. Redacting per call site would make the next command a maintainer
// adds unredacted BY DEFAULT, with nothing red to say so. So this file reads
// driver.mjs and requires its socket writes to be exactly the wired one.
//
// The fourth guards the `--secret` ROUTE ITSELF against the rule that protects it.
// The driver refuses a password handed to it on a command line; written in the
// obvious order that refusal also matched the password the `--secret` route had just
// resolved out of the pool file, so the driver could never type a password at
// all. The behavioural half below pins the three cases apart, and the STRUCTURAL
// half pins driver.mjs to the tested predicate - a unit test of an exported function
// says nothing about a fill case that kept its own inline copy of the comparison.

import { readFileSync, writeFileSync, statSync, mkdtempSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { tmpdir } from 'node:os';
import { makeRedactor, extractCode, CODE_RE, refusesValue } from './redact.mjs';
import { replyLine, saveCodeFile } from './wire.mjs';
import { loadPool, passwordFor } from './pool.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
let pass = 0, fail = 0, inconclusive = [];
const ok = (what, got, want) => {
  if (got === want) { console.log(`ok   - ${what}`); pass++; }
  else { console.log(`FAIL - ${what}: expected ${JSON.stringify(want)}, got ${JSON.stringify(got)}`); fail++; }
};
const control = (what, got, want) => {
  if (got === want) { console.log(`ok   - control: ${what}`); pass++; }
  else { console.log(`CONTROL BROKEN - ${what}: expected ${JSON.stringify(want)}, got ${JSON.stringify(got)}`); inconclusive.push(what); }
};

// Fixtures. Both passwords carry regex metacharacters ON PURPOSE.
const PW_A = 'Tr0ub4dor&3.*+?[](){}|^$';
const PW_B = 'p@ss\\word|two';
const CODE = 'aBcDeFgHiJkLmNoP1234#zYxWvUtSrQpOnMl5678';
const redact = makeRedactor([PW_A, PW_B]);
const identity = s => String(s);

// ── control 1: the fixtures really are regex-hostile ─────────────────────────
// If a future edit softens the passwords to plain words, split/join and RegExp agree
// and the method assertion below stops measuring anything.
//
// "Faithful" is the property that actually matters: would a RegExp-based redactor
// produce the SAME output as a literal one? PW_A does not compile at all (`*+` is
// not a valid quantifier) - a redactor built that way throws at start-up. PW_B
// compiles into an alternation and redacts the innocent word "two" wherever it
// appears while leaving the password's own backslash text alone - which is the worse
// half, because it looks like redaction happening.
const regexRedactionIsFaithful = pw => {
  try {
    const probe = `prefix ${pw} middle two of a kind p@ssword suffix`;
    return probe.replace(new RegExp(pw, 'g'), '[PW]') === probe.split(pw).join('[PW]');
  } catch { return false; }
};
control('neither fixture password redacts correctly when compiled as a RegExp (so split/join is the method, not a preference)',
        regexRedactionIsFaithful(PW_A) || regexRedactionIsFaithful(PW_B), false);

// ── the wire: success payloads ───────────────────────────────────────────────
const echo = async cmd => cmd.payload;
const leakyLine = await replyLine(JSON.stringify({ op: 'x', payload: { filled: PW_A, note: `typed ${PW_B} into #password` } }), echo, identity);
const safeLine = await replyLine(JSON.stringify({ op: 'x', payload: { filled: PW_A, note: `typed ${PW_B} into #password` } }), echo, redact);

// ⚠️ `onWire` IS THE WHOLE POINT OF THIS BLOCK. A password does not appear on the
// wire as itself: the reply is serialised first, so `\`, `"` and control characters
// arrive escaped. Asserting against the RAW password would report "not present" for
// a password that is sitting there in escaped form - an absence that reads as
// safety. Every assertion here is made against the form the secret actually takes.
const onWire = pw => JSON.stringify(pw).slice(1, -1);
control('the fixtures differ between their raw and on-wire forms (so the escaping hazard is exercised)',
        onWire(PW_B) !== PW_B, true);

// ⚠️ IDENTITY CONTROL - read the header. This is what stops every assertion below
// from passing vacuously on a payload that never carried a password.
control('with redaction DISABLED the same payload leaks both passwords, in their on-wire form',
        leakyLine.includes(onWire(PW_A)) && leakyLine.includes(onWire(PW_B)), true);

ok('a password in a SUCCESS reply is redacted', safeLine.includes(onWire(PW_A)) || safeLine.includes(onWire(PW_B)), false);
ok('...and the raw form is absent too', safeLine.includes(PW_A) || safeLine.includes(PW_B), false);
ok('...and the redaction marker is what replaced it', safeLine.includes('[PW]'), true);

// ── the wire: the ERROR path, which is the one that actually leaks ───────────
// Playwright quotes the argument it failed on, and for the password fill that
// argument IS the password. A redactor applied only to successes is a redactor
// applied to the wrong half.
const thrower = async () => { throw new Error(`locator.fill: value "${PW_B}" rejected\n  at Frame.fill`); };
const leakyErr = await replyLine('{"op":"fill"}', thrower, identity);
const safeErr = await replyLine('{"op":"fill"}', thrower, redact);
control('with redaction DISABLED a thrown error leaks the password', leakyErr.includes(onWire(PW_B)), true);
ok('a password inside a THROWN error message is redacted', safeErr.includes(onWire(PW_B)) || safeErr.includes(PW_B), false);
ok('the error reply is still well-formed JSON with ok:false', JSON.parse(safeErr).ok, false);

// ⚠️ THE ESCAPING PROPERTY, PINNED ON ITS OWN. Registering only the raw password
// leaves every password containing a backslash, a quote or a control character
// intact on the wire while the reply LOOKS redacted. This case is what makes the
// escaped-form needle in redact.mjs non-negotiable; the control beside it proves
// the fixture is one where raw and escaped differ, so it cannot pass vacuously.
const rawOnlyRedactor = s => { let o = String(s); o = o.split(PW_B).join('[PW]'); return o; };
const rawOnlyLine = await replyLine(JSON.stringify({ op: 'x', payload: { note: PW_B } }), echo, rawOnlyRedactor);
control('a RAW-ONLY redactor leaks a backslash password (the defect the escaped needle fixes)',
        rawOnlyLine.includes(onWire(PW_B)), true);
ok('the real redactor catches the on-wire (JSON-escaped) form',
   (await replyLine(JSON.stringify({ op: 'x', payload: { note: PW_B } }), echo, redact)).includes(onWire(PW_B)), false);

// ── the wire: malformed input still produces one redacted JSON line ──────────
const bad = await replyLine('{not json', echo, redact);
ok('a malformed command line replies with JSON rather than throwing', JSON.parse(bad).ok, false);

// ── the OAuth code ───────────────────────────────────────────────────────────
const leakyCode = await replyLine(JSON.stringify({ op: 'x', payload: { text: `Paste this into Claude Code: ${CODE}` } }), echo, identity);
const safeCode = await replyLine(JSON.stringify({ op: 'x', payload: { text: `Paste this into Claude Code: ${CODE}` } }), echo, redact);
control('with redaction DISABLED the code leaks', leakyCode.includes(CODE), true);
ok('an OAuth code in a reply is redacted', safeCode.includes(CODE), false);
ok('...and it is replaced by the CODE marker, not the password one', safeCode.includes('[CODE]'), true);
ok('a code= query parameter is redacted', redact('https://x/callback?code=abcdefghijklmnopqrstuvwxyz&s=1').includes('code=[R]'), true);

// The shape must not fire on ordinary prose containing a hash, or every inspect of
// a page mentioning `issue#1234` comes back mangled and the agent cannot read it.
ok('the code shape does NOT match short hashed prose', CODE_RE.test('see issue#1234 and foo#bar'), false);
ok('extractCode finds a whole code', extractCode(`blah ${CODE} blah`), CODE);
ok('extractCode returns null when there is none', extractCode('nothing here'), null);

// ── empty / absent secrets must not corrupt the output ───────────────────────
// ⚠️ ''.split('') inserts the marker between EVERY character: the output is
// destroyed and it looks like a redactor working very hard. An entry with no
// password is a malformed pool file (SKILL.md step 5, case 9), not a secret.
const withEmpty = makeRedactor(['', null, undefined, PW_A]);
ok('an empty/absent secret is dropped rather than matching everything', withEmpty('hello world'), 'hello world');
ok('...and a real secret in the same set is still redacted', withEmpty(`x ${PW_A} y`), 'x [PW] y');
ok('a redactor with no secrets at all passes text through', makeRedactor([])('hello world'), 'hello world');

// ── savecode: the file gets the code, the REPLY never does ───────────────────
const tmp = mkdtempSync(join(tmpdir(), 'agent-revive-redaction-test-'));
try {
  const codeFile = join(tmp, 'code.txt');
  const r = saveCodeFile(`Paste this into Claude Code:\n${CODE}\n`, codeFile);
  ok('saveCodeFile reports it saved', r.saved, true);
  ok('saveCodeFile returns the LENGTH, not the code', r.length, CODE.length);
  ok('no field of the return value contains the code', JSON.stringify(r).includes(CODE), false);
  ok('the file holds the whole code, #tail included', readFileSync(codeFile, 'utf8'), CODE);
  ok('the file is mode 0600', (statSync(codeFile).mode & 0o777).toString(8), '600');
  // the end-to-end property: that reply, sent over the wire, carries no code.
  const overWire = await replyLine('{"op":"savecode"}', async () => r, redact);
  ok('the savecode reply crossing the wire contains no code', overWire.includes(CODE), false);
  ok('saveCodeFile on text with no code reports saved:false', saveCodeFile('nothing here', join(tmp, 'none.txt')).saved, false);
} finally {
  rmSync(tmp, { recursive: true, force: true });
}

// ── the --value guard, and the --secret route it must NOT refuse ─────────────
// The guard turns a documented rule into a mechanism: a password must never travel
// on a command line, so a `--value` the driver recognises as one of its own
// passwords is refused. `--secret` is the supported route - the driver reads the
// password out of the pool file inside its own process - and the guard must
// let it through. Ordered the other way round it refuses the secret route too, and
// the driver can never type a password; the error then names `--value` on a command
// that passed none, which reads as a broken pool file.
//
// ⚠️ THE CONTROL IS NOT DECORATION. Two of the three assertions below are ABSENCES
// ("not refused"), and an empty account list satisfies both of them without the
// predicate doing anything at all. So the control first requires the instrument to
// refuse something: a --value that IS a known password. If that control breaks, the
// fixture has stopped carrying a password the predicate can see, the two absences
// have gone vacuous, and this file refuses to pronounce.
const ACCOUNTS = [
  { username: 'agent@example.com', password: PW_A },
  { username: 'other@example.com', password: PW_B },
  { username: 'broken@example.com', password: '' },   // SKILL.md step 5, case 9
  null,
];
control('a --value that IS a known password is refused (the guard can refuse at all, so the absences below are not vacuous)',
        refusesValue({ value: PW_A }, ACCOUNTS, PW_A), true);
ok('a --secret resolving to that same password is NOT refused (the route the guard exists to protect)',
   refusesValue({ secret: 'agent@example.com' }, ACCOUNTS, PW_A), false);
ok('a --value that is not any password passes', refusesValue({ value: 'hello' }, ACCOUNTS, 'hello'), false);
// An entry with no password must not turn every empty --value into a refusal: a
// pool file missing a password is a defect to report, not a secret to match.
ok('an empty-password entry does not make an empty --value look like a password',
   refusesValue({ value: '' }, ACCOUNTS, ''), false);
ok('the guard tolerates an absent account list', refusesValue({ value: 'x' }, undefined, 'x'), false);

// ── the pool file: reading it must not quote it ──────────────────────────────
// The driver's start-up failures go to a permanent log that nothing redacts - the
// redactor is built FROM the pool, so it does not exist yet when the pool fails to
// load. V8's JSON.parse quotes the text around a syntax error, so passing its
// message on writes a slice of the file - a password - into that log.
// ⚠️ THE CONTROL IS WHAT MAKES THE ASSERTION MEAN ANYTHING: it proves the RAW parser
// message really does carry the sentinel on this fixture. If a future node stops
// quoting, the control breaks and this file says NO VERDICT rather than passing an
// assertion that has gone vacuous.
const POOL_DIR = mkdtempSync(join(tmpdir(), 'signin-pool-test-'));
try {
  const SENT = 'sentinel-leak-canary-5521';
  const unquoted = `[{"username":"a@example.com","password":${SENT}}]`;
  const badPool = join(POOL_DIR, 'bad.json');
  writeFileSync(badPool, unquoted);
  let rawMsg = '';
  try { JSON.parse(unquoted); } catch (e) { rawMsg = e.message; }
  control('the raw JSON.parse message on this fixture DOES quote the password (the leak path is real)',
          rawMsg.includes(SENT.slice(0, 10)), true);
  let poolMsg = '';
  try { loadPool(badPool); } catch (e) { poolMsg = e.message; }
  ok('loadPool refuses the malformed pool', poolMsg.length > 0, true);
  ok('...and its message carries no byte of the password', poolMsg.includes(SENT.slice(0, 10)), false);

  const goodPool = join(POOL_DIR, 'good.json');
  writeFileSync(goodPool, JSON.stringify([
    { username: 'one@example.com', password: PW_A, home_agent: 'x' },
    { username: 'two@example.com', password: PW_B, home_agent: 'y' },
    { username: 'empty@example.com', password: '', home_agent: 'y' },
    { username: 'dup@example.com', password: 'dup-1' },
    { username: 'dup@example.com', password: 'dup-2' },
  ]));
  const pool = loadPool(goodPool);
  ok('loadPool returns every entry, in file order', pool.map(a => a.username).join(','),
     'one@example.com,two@example.com,empty@example.com,dup@example.com,dup@example.com');
  ok('passwordFor returns THAT entry\'s password', passwordFor(pool, 'two@example.com', goodPool), PW_B);
  const refusal = u => { try { passwordFor(pool, u, goodPool); return 'returned'; } catch (e) { return e.message; } };
  ok('a username in no entry is refused', /no pool entry/.test(refusal('nobody@example.com')), true);
  ok('a username in TWO entries is refused, never resolved to either', /ambiguous/.test(refusal('dup@example.com')), true);
  ok('an entry with no password is refused', /no password/.test(refusal('empty@example.com')), true);
  ok('no refusal message carries a password',
     ['nobody@example.com', 'dup@example.com', 'empty@example.com'].map(refusal)
       .some(m => [PW_A, PW_B, 'dup-1', 'dup-2'].some(p => m.includes(p))), false);
  let missMsg = '';
  try { loadPool(join(POOL_DIR, 'absent.json')); } catch (e) { missMsg = e.message; }
  ok('a missing pool file is refused by name', /cannot read the pool file .*ENOENT/.test(missMsg), true);
  // An agent's own credential file is ONE { username, password } object, and
  // `--pool-file` pointed at it must resolve `--secret` exactly as a list does.
  const OBJ_PW = 'fake-single-object-pw-7731';
  const objFile = join(POOL_DIR, 'object.json');
  writeFileSync(objFile, JSON.stringify({ username: 'one@example.com', password: OBJ_PW }));
  const objPool = loadPool(objFile);
  ok('a single-object credential file loads as a one-entry pool', objPool.map(a => a.username).join(','), 'one@example.com');
  ok('...and passwordFor resolves its password', passwordFor(objPool, 'one@example.com', objFile), OBJ_PW);
  const objRefusal = (() => { try { passwordFor(objPool, 'two@example.com', objFile); return 'returned'; } catch (e) { return e.message; } })();
  ok('...and another username is still refused, without the password', /no pool entry/.test(objRefusal) && !objRefusal.includes(OBJ_PW), true);
  writeFileSync(join(POOL_DIR, 'nouser.json'), JSON.stringify({ password: OBJ_PW }));
  let noUserMsg = '';
  try { loadPool(join(POOL_DIR, 'nouser.json')); } catch (e) { noUserMsg = e.message; }
  ok('a single object with no username is refused, without the password', /not an object with a username/.test(noUserMsg) && !noUserMsg.includes(OBJ_PW), true);
  for (const shape of ['[]', '"just a string"', '42', 'null']) {
    writeFileSync(join(POOL_DIR, 'shape.json'), shape);
    let shapeMsg = '';
    try { loadPool(join(POOL_DIR, 'shape.json')); } catch (e) { shapeMsg = e.message; }
    ok(`a non-pool shape (${shape}) is still refused`, /must be a non-empty JSON list/.test(shapeMsg), true);
  }
  writeFileSync(join(POOL_DIR, 'blank.json'), JSON.stringify({ username: 'blank@example.com', password: '   ' }));
  const blankRefusal = (() => { try { passwordFor(loadPool(join(POOL_DIR, 'blank.json')), 'blank@example.com', 'blank.json'); return 'returned'; } catch (e) { return e.message; } })();
  ok('a whitespace-only password is refused as no password', /no password/.test(blankRefusal), true);
} finally {
  rmSync(POOL_DIR, { recursive: true, force: true });
}

// ── STRUCTURAL: every socket write in driver.mjs goes through replyLine ──────
// ⚠️ This is the assertion that keeps the security argument true for code nobody
// has written yet. A behavioural test can only cover the commands that exist
// today; this one fails the moment someone answers a client from anywhere else.
const driverSrc = readFileSync(join(HERE, 'driver.mjs'), 'utf8');

// ⚠️ TWO WEAKER FORMS OF THESE ASSERTIONS ARE GREEN WHEN THEY SHOULD NOT BE, and
// both are worth naming because both are the shape a structural check naturally
// takes: matching `/sock\.write\(/` and requiring each hit to contain the substring
// `replyLine(`.
//   - A second write through ANY OTHER NAME is invisible to them. `const conn = sock;
//     conn.write(JSON.stringify({leaked: accounts[0].password}))` scores ALL PASS:
//     the wired write is still there, so the arity control ("at least one write")
//     is satisfied too. A check keyed on one spelling measures that spelling.
//   - Matching the CALL rather than the ARGUMENTS is worse. `replyLine(line,
//     handle, s => s)` - the redactor replaced by the identity function - scores ALL
//     PASS while every password and every OAuth code leaves the process in clear.
//     The `makeRedactor(accounts.map` case proves the redactor is CONSTRUCTED; only
//     the exact wired expression proves it is USED.
// So: count EVERY write-shaped call on any object, require exactly one, and require
// it to be the exact wired expression. Both mutations above red here.
const WIRED = 'sock.write(await replyLine(line, handle, redact));';
const writeCalls = driverSrc.match(/\.\s*(write|end|send)\s*\(/g) || [];
control('the structural check found write-shaped calls to inspect (it is not passing on an empty set)', writeCalls.length >= 1, true);
ok('driver.mjs makes exactly ONE write/end/send call on any object', writeCalls.length, 1);
ok('...and it is the EXACT wired expression, redactor argument included', driverSrc.includes(WIRED), true);
ok('driver.mjs builds its redactor from the pool it read', /makeRedactor\(accounts\.map/.test(driverSrc), true);
// ⚠️ AND THE POOL IS READ THROUGH pool.mjs AND NOWHERE ELSE. The pool-file section
// above is a statement about loadPool; a driver that read the file with its own
// `JSON.parse(readFileSync(poolPath ...))` would log the quoting parser message again
// while every assertion there stayed green.
ok('driver.mjs loads the pool through loadPool', /accounts = loadPool\(poolPath\);/.test(driverSrc), true);
ok('...and never reads the pool file itself', /readFileSync\(\s*poolPath/.test(driverSrc), false);
ok('...and the fill case resolves --secret through passwordFor',
   /if \(cmd\.secret\) value = passwordFor\(accounts, cmd\.secret, poolPath\);/.test(driverSrc), true);

// ⚠️ AND THE FILL CASE MUST DELEGATE TO THE PREDICATE TESTED ABOVE. Without these
// two, every assertion in the guard section is a statement about a function the
// driver is free not to call: an inline `a.password === value` left behind in the
// fill case would keep the original defect while the unit tests stayed green. The
// second assertion is the load-bearing one - it fails on a COPY of the comparison,
// which is the shape a maintainer reaches for when inlining "just this one check".
const fillStart = driverSrc.indexOf("case 'fill': {");
const fillEnd = driverSrc.indexOf("case 'press': {");
control('the fill case is locatable and ends at the next case (so the slice below is the fill case, not the whole file)',
        fillStart > 0 && fillEnd > fillStart, true);
const fillCase = driverSrc.slice(fillStart, fillEnd);
ok("driver.mjs's fill case asks refusesValue rather than comparing passwords itself",
   /refusesValue\(\s*cmd\s*,\s*accounts\s*,\s*value\s*\)/.test(fillCase), true);
ok('...and holds no inline password comparison of its own',
   /\.password\s*===\s*value|value\s*===\s*\w+\.password/.test(fillCase), false);
ok('driver.mjs imports the predicate from the dependency-free module',
   /const \{[^}]*\brefusesValue\b[^}]*\} = await import\('\.\/redact\.mjs'\);/.test(driverSrc), true);

// ⚠️ AND STDOUT/STDERR ARE AN OUTPUT PATH TOO. The driver is spawned detached with
// both streams redirected into an append-only log that `quit` does not remove and
// that nothing redacts, so a `console.*` interpolating a secret-bearing identifier
// would put it somewhere permanent. The identifier list is the point: these are the
// names the secrets are bound to in this file.
const consoles = driverSrc.match(/console\.\w+\([^\n]*/g) || [];
control('the console scan found console calls to inspect', consoles.length >= 1, true);
ok('no console.* in driver.mjs interpolates a secret-bearing identifier',
   consoles.every(c => !/\baccounts\b|\bpassword\b|\bcmd\.value\b|\bCODE\b/.test(c)), true);

// ⚠️ AND THE TWO PURE MODULES MUST STAY DEPENDENCY-FREE, or this whole file stops
// running on a clone that has not installed Chromium - and a check that only runs
// where the install is complete is a check that stops running.
// ⚠️ `[ \t]*`, never `\s*`: under the `m` flag `\s*` happily consumes the NEWLINE
// before the line it is anchored to, so every extracted specifier came back with a
// leading "\n" and read as a bare package name. The assertion failed on two
// perfectly compliant files - a false red, which is the direction that gets a
// control deleted rather than fixed.
const importsOf = f => (readFileSync(join(HERE, f), 'utf8').match(/^[ \t]*import .*from ['"]([^'"]+)['"]/gm) || [])
  .map(l => l.replace(/.*from ['"]([^'"]+)['"].*/, '$1'));

// ⚠️ THE SCANNER IS PROVEN LIVE ON THE FILE THAT HAS IMPORTS, BECAUSE THE FILE THAT
// HAS NONE SATISFIES THE ASSERTION VACUOUSLY. redact.mjs imports nothing at all, so
// `every()` over its empty list is true whatever the regex does - including nothing.
// wire.mjs is where the regex has to actually work, and the control pins the
// specifier it must find, not merely that it found something.
control('the import scanner really resolves a specifier (it is not returning an empty set)',
        importsOf('wire.mjs').includes('node:fs'), true);
for (const f of ['redact.mjs', 'wire.mjs', 'pool.mjs']) {
  ok(`${f} imports only node: builtins and siblings (so this test needs no install)`,
     importsOf(f).every(m => m.startsWith('node:') || m.startsWith('./')), true);
}

console.log('');
if (inconclusive.length) {
  console.log(`NO VERDICT - ${inconclusive.length} control(s) misbehaved, so the instrument is not established: ${inconclusive.join('; ')}`);
  console.log('Do NOT read this as a pass. Fix the control, then re-run.');
  process.exit(3);
}
console.log(`passed ${pass}, failed ${fail}`);
process.exit(fail === 0 ? 0 : 1);
