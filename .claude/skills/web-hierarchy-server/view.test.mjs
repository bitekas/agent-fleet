#!/usr/bin/env node
// view.test.mjs - the page's "active only / all" switch: format.mjs's
// filterView(), which decides which tree rows the graph draws.
//
//   node .claude/skills/web-hierarchy-server/view.test.mjs
//
// Offline and hermetic: no port, no transcript, no network. format.mjs is
// imported with WEB_HIERARCHY_CONFIG pointing at fixtures/config.fixture.json,
// so no fleet command, host config or install is consulted. The rows below are
// the fixture: a synthetic spawn tree in the {id, parentId, active} shape
// snapshot() hands to filterView().
//
//   root (stopped)
//   +- orch      (stopped)  waiting on its children: its transcript is silent
//   |  +- engA   (ACTIVE)
//   |  |  +- rev (stopped)  a finished child of an active agent
//   |  +- engB   (stopped)  a finished sibling under a kept parent
//   +- qa        (stopped)
//   |  +- qaKid  (stopped)  a whole finished subtree
//   +- lone      (ACTIVE)
//   stray        (ACTIVE)   its parent is not in the set
//
// WHAT IT MEASURES, and why each leg is here:
//
//   1. "ACTIVE" IS THE PAGE'S OWN ALIVE FLAG, PLUS WHAT CONNECTS IT. The view
//      keeps every active row, every ancestor of one, and the root - exactly
//      {root, orch, engA, lone, stray}. The ancestor rule is the load-bearing
//      half: a parent waiting on a long child writes nothing, so it reads as
//      stopped while its child runs, and a filter without the rule draws that
//      child with no edge to anything. `orch` is in the fixture for that, and
//      it is paired with `engB` and `rev` (stopped rows NEXT to kept ones),
//      because "orch is kept" alone also passes on a filter that keeps
//      everything.
//   2. THE ROOT ALWAYS SHOWS, and with nothing active the view is the root
//      alone. The root is the session the page follows; an empty graph would
//      read as "no session".
//   3. ORDER AND IDENTITY: the result is a subsequence of the input, made of
//      the same row objects. snapshot() lays out what it gets, so a filter that
//      reordered or rebuilt rows would move blocks between polls.
//   4. THE CONTROL: "all" returns every row, unchanged, and so does any other
//      value (undefined, an unknown word) - "all" is the default and today's
//      page. Without this, a filter that hid stopped rows in every view would
//      pass legs 1-3.
//
// PRECONDITION: the fixture must hold a stopped ancestor of an active row and
// a stopped row with no active descendant. Without the first, leg 1's ancestor
// half measures nothing; without the second, "active" cannot differ from
// "all". Either missing is NO VERDICT, not a pass.
//
// EXIT CODES - THREE, NEVER TWO:
//   0  PASS      every leg green.
//   1  FAIL      a leg disagreed, including format.mjs loading and offering no
//      filterView at all: the subject was reached and the feature is absent.
//   2  NO VERDICT the instrument could not be established (format.mjs did not
//      load, or the fixture lost a precondition). Read a 2 as "this file
//      measured nothing", never as a smaller pass.
import { join, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));

const fails = [];
const check = (name, cond, detail = '') => {
  if (cond) return console.log(`  ok   ${name}`);
  fails.push(name);
  console.log(`  FAIL ${name}${detail ? ` - ${detail}` : ''}`);
};
const noVerdict = (why) => {
  console.log(`\nNO VERDICT: ${why}\nThis file measured nothing. Do not read this as a pass.`);
  process.exit(2);
};

const row = (id, parentId, active) => ({ id, parentId, active });
const ROWS = [
  row('root', null, false),
  row('orch', 'root', false),
  row('engA', 'orch', true),
  row('rev', 'engA', false),
  row('engB', 'orch', false),
  row('qa', 'root', false),
  row('qaKid', 'qa', false),
  row('lone', 'root', true),
  row('stray', 'gone', true),
];
const byId = new Map(ROWS.map((r) => [r.id, r]));
const hasStoppedAncestorOfActive = ROWS.some((r) => r.active && byId.get(r.parentId) && !byId.get(r.parentId).active && r.parentId !== 'root');
const hasStoppedLeaf = ROWS.some((r) => !r.active && !ROWS.some((k) => k.parentId === r.id));
if (!hasStoppedAncestorOfActive) noVerdict('the fixture has no stopped non-root ancestor of an active row, so leg 1 cannot see the ancestor rule');
if (!hasStoppedLeaf) noVerdict('the fixture has no stopped leaf, so "active" cannot differ from "all"');

process.env.WEB_HIERARCHY_CONFIG = join(HERE, 'fixtures', 'config.fixture.json');
let mod;
try { mod = await import(pathToFileURL(join(HERE, 'format.mjs')).href); }
catch (e) { noVerdict(`format.mjs did not load (${e.message})`); }
console.log('view.test: format.mjs loaded');

const { filterView } = mod;
check('format.mjs exports filterView()', typeof filterView === 'function', `got ${typeof filterView}`);
if (typeof filterView !== 'function') {
  console.log(`\nFAIL - format.mjs has no filterView(): the switch has nothing to filter with.`);
  process.exit(1);
}
const ids = (rows) => rows.map((r) => r.id).join(',');

// --- leg 1: active rows, their ancestors, the root --------------------------
const act = filterView(ROWS, 'active');
check('the active view keeps exactly the active rows, their ancestors and the root',
  ids(act) === 'root,orch,engA,lone,stray', `got ${ids(act)}`);
check('...the stopped parent of an active row is kept (ancestor rule)', act.some((r) => r.id === 'orch'));
check('...its stopped sibling is dropped', !act.some((r) => r.id === 'engB'));
check('...the stopped child of an active row is dropped', !act.some((r) => r.id === 'rev'));
check('...a wholly stopped subtree is dropped', !act.some((r) => r.id === 'qa' || r.id === 'qaKid'));

// --- leg 2: the root always shows -----------------------------------------
const quiet = ROWS.map((r) => ({ ...r, active: false }));
check('with nothing active, the view is the root alone', ids(filterView(quiet, 'active')) === 'root',
  `got ${ids(filterView(quiet, 'active'))}`);

// --- leg 3: order and identity --------------------------------------------
check('the active view is the same row objects, in input order',
  act.every((r, i) => r === byId.get(r.id) && (i === 0 || ROWS.indexOf(act[i - 1]) < ROWS.indexOf(r))));

// --- leg 4: the control - "all" is everything, unchanged -------------------
for (const v of ['all', undefined, 'bogus']) {
  const out = filterView(ROWS, v);
  check(`view ${JSON.stringify(v)} returns every row, unchanged and in order`,
    out.length === ROWS.length && out.every((r, i) => r === ROWS[i]), `got ${ids(out)}`);
}

if (fails.length) {
  console.log(`\nFAIL - ${fails.length} check(s):`);
  for (const f of fails) console.log(`  - ${f}`);
  process.exit(1);
}
console.log('\nPASS - active view: active rows + ancestors + root; "all" (the default) unchanged.');
process.exit(0);
