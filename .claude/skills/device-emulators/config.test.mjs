#!/usr/bin/env node
// config.test.mjs - the device-emulators skill's config TWINS, held in agreement.
//
// -- WHAT THIS GUARDS, AND WHY A COMMENT WOULD NOT --------------------------
// This skill splits into a MECHANISM half (SKILL.md, technical/, installation/)
// that names no value, and a VALUES half (the install's config.json, in the
// skill's install context). `config.example.json` is the third piece: the file
// an adopter copies, and the only place a key's meaning and how to obtain it
// are written down. Nothing executes any of the three, so all three drift
// silently and each drift has its own failure:
//
//   * A KEY IN THE INSTALL'S config.json AND NOT IN THE EXAMPLE is a key an
//     adopter never creates. Their copy is missing it, the code path that reads
//     it takes the `or 17`-style fallback, and the skill behaves differently on
//     their machine for a reason nothing prints.
//   * A KEY IN THE EXAMPLE AND NOT IN THE INSTALL'S config.json is a key that
//     install never filled in. `installation/check` reads that config.json, so
//     the check passes and the value is silently absent at the moment something
//     needs it.
//   * A KEY NOBODY DOCUMENTS is a key nobody fills in. The mechanism files refer
//     to keys and never to values, so an example key that appears in neither
//     `` `key` `` nor `<key>` form anywhere in the skill's universal prose is
//     unreachable from the documentation an adopter reads.
//
// WHICH config.json: the one `fleet where device-emulators config.json` names
// (lib/fleet-where.mjs, loaded from this file's realpath), or
// $DEVICE_EMULATORS_CONFIG when set. In the fleet's own suite that is the
// fixture install's (tests/run-all.sh exports FLEET_CONTEXT_ROOT); run from an
// install, it is that install's own copy - which is how an install keeps its
// config checked: it runs this file from its tree.
//
// WHAT THIS DELIBERATELY DOES NOT CHECK, SO NOBODY ADDS IT BACK AS AN
// "OVERSIGHT": that no config VALUE appears in SKILL.md. That check cannot hold
// here and would have to be neutered to pass, which is worse than not having it:
// the values include `ios`, `android` and `local`, and SKILL.md must be free to
// write "the iOS Simulator and the Android AVD" in English. A check whose only
// viable form is a list of exceptions is a check that teaches nothing and gets
// extended every time it fires.
//
// -- THE NEGATIVE CONTROL IS LOAD-BEARING. DO NOT DELETE IT FOR TIDINESS ------
// Every assertion here is of the form "these two sets are equal", and the answer
// we want is always "yes". So a clean tree and a comparator that has silently
// stopped comparing anything - a renamed reader, a `dotted()` that returns [],
// an exception swallowed into an empty list - are INDISTINGUISHABLE from each
// other, and the broken one prints PASS. The control injects a known divergence
// through the WHOLE comparator and requires it to come back out reported.
//
// IF THE NEGATIVE CONTROL PASSES, THIS FILE ISSUES NO VERDICT (exit 3). Not a
// pass with a warning: a green from an instrument that has been shown not to
// detect its own subject is worse than no green, because it is acted on.
//
// MEASURED, not asserted, on a throwaway copy:
//   * an extra key added to the install's config.json alone -> exit 1, the key
//     check naming it. The instrument detects its subject.
//   * `dotted()` blinded to return [] -> exit 3, and the key checks print PASS
//     on their way there. That is the shape the control exists to catch: every
//     assertion green, nothing measured.
//   * the same blinding WITH THIS CONTROL BLOCK DELETED -> "PASS - the
//     device-emulators config twins agree", exit 0. The control is the only
//     thing between a broken comparator and a confident green.
//
// -- EXIT CODES: THREE, NEVER TWO --------------------------------------------
//   0  every twin agrees
//   1  a twin DISAGREES - the finding this file exists for
//   3  NO VERDICT - a file could not be read, no install config resolved, or the
//      negative control did not fire. "Never actually ran" must never be
//      reported as "passed".
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

// realpath, never the link path: an agent reaches this skill through a personal
// skill link, and three directories above the link there is no fleet.
const HERE = fs.realpathSync(path.dirname(fileURLToPath(import.meta.url)));

let failures = 0;
const check = (name, cond, detail = '') => {
  console.log(`[${cond ? 'PASS' : 'FAIL'}] ${name}${detail ? ` - ${detail}` : ''}`);
  if (!cond) failures++;
};
const noVerdict = (why) => {
  console.log(`\nNO VERDICT (exit 3) - ${why}`);
  process.exit(3);
};

const readJson = (p) => {
  try { return JSON.parse(fs.readFileSync(p, 'utf8')); }
  catch (e) { noVerdict(`cannot read ${p}: ${e.message}`); }
};

// `_comment` keys are documentation, not configuration: config.example.json
// carries one per section and a filled-in config.json carries fewer, so
// comparing them would make this file red on a difference that is the intended
// state.
const dotted = (obj, prefix = '') => Object.entries(obj)
  .filter(([k]) => !k.startsWith('_'))
  .flatMap(([k, v]) => (v && typeof v === 'object' && !Array.isArray(v))
    ? dotted(v, `${prefix}${k}.`) : [`${prefix}${k}`]);

const eq = (a, b) => JSON.stringify([...a].sort()) === JSON.stringify([...b].sort());
const diff = (a, b) => [...a].filter((k) => !b.includes(k));

let configPath;
try {
  const { configFile } = await import(pathToFileURL(
    path.join(HERE, '..', '..', '..', 'lib', 'fleet-where.mjs')).href);
  configPath = configFile('device-emulators', 'DEVICE_EMULATORS_CONFIG');
} catch (e) {
  noVerdict(`no install config.json resolved (${e.message}), so the twins were not compared`);
}
const CONFIG = readJson(configPath);
const EXAMPLE = readJson(path.join(HERE, 'config.example.json'));

// The repository root the config's script paths resolve against: the install
// root, the nearest directory above config.json holding .claude/fleet.json.
// null when there is none (a config named directly, outside any install).
const installRoot = (() => {
  for (let d = path.dirname(configPath); ; d = path.dirname(d)) {
    if (fs.existsSync(path.join(d, '.claude', 'fleet.json'))) return d;
    if (path.dirname(d) === d) return null;
  }
})();

console.log(`device-emulators config twins (install config: ${configPath})\n`);

// -- 1. the install's config.json <-> config.example.json ------------------
{
  const c = dotted(CONFIG);
  const e = dotted(EXAMPLE);
  const onlyC = diff(c, e);
  const onlyE = diff(e, c);
  check('the install config.json and config.example.json declare the same keys', eq(c, e),
    onlyC.length || onlyE.length
      ? `only in config.json: [${onlyC}] / only in config.example.json: [${onlyE}]`
      : `${c.length} keys`);
}

// -- 2. every example key is named in the skill's own prose ----------------
// BOTH FORMS ARE ACCEPTED AND THAT IS NOT LAXNESS. This skill's prose refers
// to a key as `` `key` `` in sentences and as `<key>` inside command blocks,
// because a command block is meant to be read as a template with the value
// substituted in. Accepting only the backticked form would fail every key that
// is documented exactly where an operator looks for it. The install's CONTEXT.md
// is NOT read: a key documented only there is undocumented for every other
// install.
{
  const proseFiles = [
    'SKILL.md', path.join('installation', 'INSTRUCTION.md'),
    ...fs.readdirSync(path.join(HERE, 'technical')).filter((f) => f.endsWith('.md'))
      .map((f) => path.join('technical', f)),
  ];
  let prose = '';
  for (const f of proseFiles) {
    const p = path.join(HERE, f);
    if (!fs.existsSync(p)) noVerdict(`prose file ${f} is missing, so key coverage was not measured`);
    prose += fs.readFileSync(p, 'utf8');
  }
  const undocumented = dotted(EXAMPLE).filter((k) => !prose.includes(`\`${k}\``) && !prose.includes(`<${k}>`));
  check('every example key is named in the skill\'s prose', undocumented.length === 0,
    undocumented.length ? `undocumented: ${undocumented.join(', ')}` : `${proseFiles.length} files`);
}

// -- 3 and 4. the JDK floor and predicate the build script shares ----------
// CONDITIONAL, AND IT REPORTS WHICH BRANCH IT TOOK. A build script that reads
// android.jdk_min_major from the install's config at run time and keeps a
// fallback literal for a checkout without one writes it as
// ANDROID_JDK_MIN_MAJOR_FALLBACK=<n> (SKILL.md, "The two scripts"). The literal
// is a twin of the config value, and a twin nothing compares is how the fallback
// comes to differ from the number `installation/check` enforces: a machine the
// check calls READY would then be one the build refuses, and the two would
// disagree about a number neither prints. SKIPPED, loudly, when the build script
// is not reachable or carries no such literal: an adopter's build script owes
// this file nothing.
//
// THE NUMBER IS THE EASY HALF AND IT IS NOT WHERE THE DIVERGENCE LIVES.
// Check 4 pins the PREDICATE: without it the two can agree on "17 or newer"
// while disagreeing about what counts as a JDK - a check gating on `java` and a
// build gating on `javac` call a JRE-only machine READY and REFUSED at once.
// Both are pinned as SOURCE TEXT rather than by running them, because running
// either one measures THIS machine (which may have a JDK) and therefore cannot
// distinguish the two predicates at all.
{
  const chk = path.join(HERE, 'installation', 'check');
  if (!fs.existsSync(chk)) noVerdict('installation/check is missing, so the JDK predicate was not measured');
  const chkSrc = fs.readFileSync(chk, 'utf8');
  check('installation/check qualifies a JDK on javac, not on java',
    /which\("javac"\)/.test(chkSrc) && /"bin", "javac"/.test(chkSrc),
    'a JRE at or above the floor must not be reported READY');

  const script = String(CONFIG?.build?.script || '').replace(/^\.\//, '');
  const dep = installRoot && script ? path.join(installRoot, script) : '';
  const floor = CONFIG?.android?.jdk_min_major;
  if (!dep || !fs.existsSync(dep)) {
    console.log(`[SKIP] build.script (${script || 'unset'}) is not reachable from an install root - the JDK-floor twin and the build side of the predicate were not measured`);
  } else {
    const src = fs.readFileSync(dep, 'utf8');
    const m = src.match(/ANDROID_JDK_MIN_MAJOR_FALLBACK=(\d+)/);
    if (!m) {
      console.log(`[SKIP] ${script} carries no ANDROID_JDK_MIN_MAJOR_FALLBACK literal - nothing to twin`);
    } else {
      check(`${script}'s JDK fallback equals android.jdk_min_major`,
        Number(m[1]) === floor, `${script}=${m[1]} config=${floor}`);
      check(`${script} qualifies a JDK on bin/javac too`,
        /bin\/javac/.test(src), 'the two must refuse the same machines');
    }
  }
}

// -- THE NEGATIVE CONTROL ----------------------------------------------------
// Drives a KNOWN divergence through the same comparator the checks above use.
// If it comes back "equal", the comparator is not comparing and every green
// above is meaningless - so no verdict is issued, in either direction.
{
  const mutated = JSON.parse(JSON.stringify(CONFIG));
  mutated.zz_control_key_that_must_be_detected = true;
  const detected = !eq(dotted(mutated), dotted(CONFIG));
  const commentIgnored = dotted({ _comment: 'x', real: 1 }).join(',') === 'real';
  if (!detected) {
    noVerdict('the negative control PASSED: an injected extra key was not reported as a '
      + 'difference, so the comparator is not comparing and no green above means anything.');
  }
  if (!commentIgnored) {
    noVerdict('the control on _comment filtering did not hold, so key extraction is not '
      + 'behaving as this file assumes and its verdicts cannot be read.');
  }
  console.log('[CTRL] an injected key IS reported, and _comment IS filtered - the comparator works');
}

console.log('');
if (failures === 0) { console.log('PASS - the device-emulators config twins agree'); process.exit(0); }
console.log(`FAIL - ${failures} twin(s) disagree`);
process.exit(1);
