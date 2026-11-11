#!/usr/bin/env node
// serve.test.mjs - the test for serve.mjs + format.mjs, driven end to end.
//
//   node .claude/skills/web-hierarchy-server/serve.test.mjs
//
// Offline and hermetic: it binds ONE ephemeral port on 127.0.0.1, reads only
// fixtures/ and a temporary copy of them, writes nothing outside its own
// tempdir, and touches no real transcript, no network and no credential.
//
// WHAT IT MEASURES, and why each leg is here rather than being obvious:
//
//   1. THE SERVER STARTS AND ANSWERS. Not "the file exists" - the process is
//      spawned, the banner is read off its stdout, and every route is fetched.
//      A skill whose check is `existsSync(serve.mjs)` is green on a file the
//      runtime cannot load at all (a syntax error, a missing export, a config
//      that throws at import time), because stat(2) opens nothing.
//   2. THE PORT IS READ OFF THE BANNER, NOT GUESSED. The test asks for
//      --port=0, the kernel picks a free one, and serve.mjs prints the BOUND
//      port. Picking a port ourselves and hoping it is still free at spawn time
//      is a race that fails as a mysterious ECONNREFUSED on a busy machine, and
//      a busy machine is exactly where this suite runs.
//   3. THE TREE IS THE REAL TREE. Root plus BOTH subagents, each with the
//      agentType its .meta.json declares, and exactly one of them alive. The
//      alive flag is time-derived (a transcript whose last event is under three
//      minutes old), so the fixture carries a `__NOW__` token that this file
//      substitutes on copy - a frozen timestamp would make "alive" depend on
//      the calendar and the leg would silently stop measuring anything.
//   4. THE ROOT BLOCK CARRIES THE FLEET LABEL, DERIVED THE NEW WAY. The fixture
//      tree is copied to <tmp>/fixture-agent/.claude, whose basename is the
//      literal `.claude`, and the fixture config maps `fixture-agent`. So this
//      leg passes ONLY through format.mjs's fleetKey() parent-basename rule. If
//      someone "simplifies" that back to a plain basename lookup, the label
//      disappears and this leg goes red, which is the entire reason the fixture
//      is nested under a synthetic agent home instead of sitting in a flat
//      tempdir.
//
// ---------------------------------------------------------------------------
// THE SIZE LEGS (6-9) - WHAT THEY PROTECT, AND WHY NOTHING ELSE CAN SEE IT
//
// The viewer carried every agent's log in every snapshot until it met a session
// with 228 agents, where `GET /` was 358MB - 110MB of it base64 images, re-sent
// on every 10s poll - which no browser opens usefully. The fix splits the
// payload: the TREE is served, the LOGS are fetched one agent at a time, and
// images are served by content hash instead of inlined.
//
// ⚠️ THAT SPLIT CAN BE UNDONE WITHOUT ANYTHING GOING RED. Every leg above
// passes on a server that inlines every log and every image again: the tree is
// still right, the labels are still right, the page still renders, and it is
// again hundreds of megabytes. The SIZE is the property under protection and
// legs 6-9 are the only thing here that can see it regress. Do not delete them
// as redundant with "the log renders" - they measure what the log renders
// WHERE.
//
// Each of them is a pair, because "X is absent" is free for the wrong reasons:
//
//   6. /state carries the tree and NO logs ... while /state?logs=<all> carries
//      them, and the tree's own event COUNT for that agent is non-zero. Without
//      the second half, an agent with no events at all would pass.
//   7. /agent/<id> carries THAT agent's log ... and neither of the other two
//      agents' logs, checked by a text unique to each. Without the cross-check,
//      a route returning the whole session would pass. This leg ALSO pins the
//      two render paths together byte for byte: snapshot() renders a log while
//      walking the whole session, agentLog() renders one from a single
//      transcript plus the metas, and the second reconstructs by hand what the
//      first gets for free (the spawner in a from/to header, what each Agent
//      call spawned). Drift between them is invisible - both still produce a
//      plausible log - so they are compared directly.
//   8. ?since=<n> returns only events from n ... and the full fetch returns
//      more than one, and the tail event is not the first. Without those, a
//      route that always returned exactly one event would pass.
//   9. An image the document does NOT bake is absent from it and served by hash
//      instead ... while an image it DOES bake (the root session's log) is
//      present inline. Same mechanism, same file type, two agents: the only
//      difference is whose log it is in. Without the baked half, this leg would
//      pass just as well on a build where image inlining is broken everywhere,
//      which is the standalone-document property gone.
//
// ---------------------------------------------------------------------------
// THE NEGATIVE CONTROL (leg 10) IS THE LOAD-BEARING PART. Every leg above
// passes on a server that read the transcripts ONCE and would keep serving that
// snapshot forever, and they pass on a formatter that fabricated a plausible
// tree from nothing. So one subagent's transcript is DELETED from the copied
// tree and /state is fetched again: the tree must LOSE that agent and keep the
// other, and /agent/<that id> must become a 404. A check that cannot be made to
// fail is not a check.
//
//   ⚠️ IF THE CONTROL DOES NOT FIRE - the agent is still in the tree after its
//   transcript is gone - this file issues NO VERDICT (exit 2) rather than a
//   failure or a pass. The subject and the instrument are indistinguishable at
//   that point: either the server is not reading from disk, or the test deleted
//   something the server never read, and a boolean cannot say which. Reporting
//   either a pass or a fail from there launders a broken instrument into a
//   confident answer.
//
//   ⚠️ The control is also guarded in the OTHER direction: leg 3 must have
//   SEEN that agent before the deletion. Deleting a file the tree never
//   contained makes "the tree lost it" true for free, and a vacuously true
//   control is a decorative one.
//
// EXIT CODES - THREE, NEVER TWO:
//   0  PASS      every leg green.
//   1  FAIL      a real disagreement between the server and the fixture.
//   2  NO VERDICT the instrument could not be established: the server never
//      printed a banner, a route did not answer, the fixture tree is missing or
//      empty, a fixture image is missing, or the negative control did not fire.
//      Read a 2 as "this file measured nothing", never as a smaller pass.
import { spawn } from 'node:child_process';
import { cpSync, mkdtempSync, readFileSync, writeFileSync, rmSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { tmpdir } from 'node:os';

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURES = join(HERE, 'fixtures');
const AGENT_DIR_NAME = 'fixture-agent'; // becomes the fleet KEY (see leg 4)
const SESSION = '11111111-1111-4111-8111-111111111111';
const ALIVE_AGENT = 'aaaa1111';   // its transcript carries __NOW__
const STOPPED_AGENT = 'bbbb2222'; // its transcript is years old
// One string that appears ONLY in each agent's log, never in the tree (the tree
// carries meta.description, which is different text). These are what make
// "this route returned that agent's log and nobody else's" checkable.
const ONLY_IN_ALIVE_LOG = 'FIXTURE TASK A - obviously fake';
const ONLY_IN_STOPPED_LOG = 'Fixture agent B finished long ago';
const ONLY_IN_ROOT_LOG = 'FIXTURE ROOT PROMPT - obviously fake';
const ALIVE_LAST_LINE = 'FIXTURE AGENT A LAST LINE - obviously fake.';

const fails = [];
const ok = (name) => console.log(`  ok   ${name}`);
const check = (name, cond, detail = '') => {
  if (cond) return ok(name);
  fails.push(`${name}${detail ? ` - ${detail}` : ''}`);
  console.log(`  FAIL ${name}${detail ? ` - ${detail}` : ''}`);
};
const noVerdict = (why) => {
  console.log(`\nNO VERDICT: ${why}`);
  console.log('This file measured nothing. Do not read this as a pass.');
  process.exit(2);
};

// --- the temporary transcript tree -----------------------------------------
// Copied rather than read in place for two reasons: leg 10 deletes a file, and a
// test that mutates its own committed fixtures is a test that passes once.
const tmp = mkdtempSync(join(tmpdir(), 'web-hierarchy-server-test-'));
const configDir = join(tmp, AGENT_DIR_NAME, '.claude');
let child = null;
const cleanup = () => {
  try { if (child && child.exitCode === null) child.kill('SIGKILL'); } catch { /* already gone */ }
  try { rmSync(tmp, { recursive: true, force: true }); } catch { /* best effort */ }
};
process.on('exit', cleanup);

if (!existsSync(join(FIXTURES, 'config-dir'))) noVerdict(`fixtures/config-dir is missing from ${FIXTURES}`);
cpSync(join(FIXTURES, 'config-dir'), configDir, { recursive: true });

// The two fixture images, read as BYTES. Leg 9 compares what /img/<hash> serves
// against these, byte for byte: an image route that served a plausible PNG of
// its own would pass a size check and fail this.
const AGENT_IMG = join(FIXTURES, 'fixture-image.png');
const ROOT_IMG = join(FIXTURES, 'fixture-root-image.png');
for (const p of [AGENT_IMG, ROOT_IMG]) if (!existsSync(p)) noVerdict(`the fixture image ${p} is missing, so leg 9 would measure nothing`);
const agentImgBytes = readFileSync(AGENT_IMG);
const rootImgBytes = readFileSync(ROOT_IMG);
const agentImgB64 = agentImgBytes.toString('base64');
const rootImgB64 = rootImgBytes.toString('base64');

const subagents = join(configDir, 'projects', '-fixture-project', SESSION, 'subagents');
const aliveJsonl = join(subagents, `agent-${ALIVE_AGENT}.jsonl`);
const aliveMeta = join(subagents, `agent-${ALIVE_AGENT}.meta.json`);
if (!existsSync(aliveJsonl)) noVerdict(`the copied fixture tree has no ${aliveJsonl}`);

// `__NOW__` -> a timestamp inside format.mjs's three-minute liveness window, so
// the alive/stopped distinction is a property of the data rather than of the
// date the suite happens to run on.
const now = new Date().toISOString();
const raw = readFileSync(aliveJsonl, 'utf8');
if (!raw.includes('__NOW__')) noVerdict('the alive fixture carries no __NOW__ token, so nothing can be alive');
writeFileSync(aliveJsonl, raw.split('__NOW__').join(now));
// The alive agent's log must actually contain the image the size legs are
// about; without it legs 9's "absent from the document" half is free.
if (!readFileSync(aliveJsonl, 'utf8').includes(agentImgB64)) {
  noVerdict('the alive fixture transcript does not carry fixture-image.png, so leg 9 would measure nothing');
}
if (!readFileSync(join(configDir, 'projects', '-fixture-project', `${SESSION}.jsonl`), 'utf8').includes(rootImgB64)) {
  noVerdict('the root fixture transcript does not carry fixture-root-image.png, so leg 9 has no baked control');
}

// --- start the server -------------------------------------------------------
console.log(`web-hierarchy-server test\n  tempdir: ${tmp}`);
child = spawn(process.execPath, [join(HERE, 'serve.mjs'), '--port=0'], {
  env: {
    ...process.env,
    CLAUDE_CONFIG_DIR: configDir,
    WEB_HIERARCHY_CONFIG: join(FIXTURES, 'config.fixture.json'),
  },
  stdio: ['ignore', 'pipe', 'pipe'],
});

const banner = await new Promise((resolve) => {
  let buf = '';
  const done = setTimeout(() => resolve(null), 20000);
  child.stdout.on('data', (d) => {
    buf += String(d);
    const m = buf.match(/http:\/\/localhost:(\d+)\//);
    if (m) { clearTimeout(done); resolve({ port: Number(m[1]), text: buf }); }
  });
  child.stderr.on('data', (d) => process.stderr.write(`  [serve.mjs stderr] ${d}`));
  child.on('exit', (code) => { clearTimeout(done); resolve(buf ? { port: null, text: buf, code } : null); });
});
if (!banner || !banner.port) {
  noVerdict(`serve.mjs printed no usable banner within 20s (exit ${banner?.code ?? 'none'}): ${banner?.text || '<no output>'}`);
}
const base = `http://127.0.0.1:${banner.port}`;
ok(`server up on ${base}`);

const get = async (path) => {
  try {
    const r = await fetch(base + path);
    return { status: r.status, body: await r.text(), type: r.headers.get('content-type') || '' };
  } catch (e) {
    return noVerdict(`GET ${path} did not answer (${e.message})`);
  }
};
const getBytes = async (path) => {
  try {
    const r = await fetch(base + path);
    return { status: r.status, buf: Buffer.from(await r.arrayBuffer()), type: r.headers.get('content-type') || '', cache: r.headers.get('cache-control') || '' };
  } catch (e) {
    return noVerdict(`GET ${path} did not answer (${e.message})`);
  }
};
const getJson = async (path, why) => {
  const r = await get(path);
  if (r.status !== 200) return { status: r.status, json: null };
  try { return { status: r.status, json: JSON.parse(r.body) }; }
  catch (e) { return noVerdict(`${path} is not JSON (${why}): ${e.message}`); }
};

// --- leg 1/2: the routes answer --------------------------------------------
const page = await get('/');
check('GET / returns 200', page.status === 200, `status ${page.status}`);
check('GET / is a complete standalone document',
  page.body.startsWith('<!doctype html>') && page.body.includes('</html>'));
check('GET / carries the page title', page.body.includes('<title>Agent hierarchy'));

const stateRes = await get('/state');
check('GET /state returns 200', stateRes.status === 200, `status ${stateRes.status}`);
let state;
try { state = JSON.parse(stateRes.body); } catch (e) { noVerdict(`/state is not JSON (${e.message})`); }

// --- leg 3: the tree is the fixture's tree ---------------------------------
if (!Array.isArray(state.agents) || state.agents.length === 0) {
  noVerdict('/state carries no agents at all, so every assertion below would pass or fail vacuously');
}
const byId = new Map(state.agents.map((a) => [a.id, a]));
check('/state follows the fixture session', state.sessionId === SESSION, `got ${state.sessionId}`);
check('the tree has the root node', byId.has('root'));
check('the tree has the alive subagent', byId.has(ALIVE_AGENT), `ids: ${[...byId.keys()].join(', ')}`);
check('the tree has the stopped subagent', byId.has(STOPPED_AGENT), `ids: ${[...byId.keys()].join(', ')}`);
check('the alive subagent carries its declared agentType',
  byId.get(ALIVE_AGENT)?.type === 'software-engineer', `got ${byId.get(ALIVE_AGENT)?.type}`);
check('the stopped subagent carries its declared agentType',
  byId.get(STOPPED_AGENT)?.type === 'qa-engineer', `got ${byId.get(STOPPED_AGENT)?.type}`);
check('the recent subagent reads as alive', byId.get(ALIVE_AGENT)?.active === true);
check('the years-old subagent reads as stopped', byId.get(STOPPED_AGENT)?.active === false);
check('exactly one agent is working', state.workingCount === 1, `got ${state.workingCount}`);
check('the graph rendered', typeof state.svg === 'string' && state.svg.includes('<svg'));

// --- leg 4: the fleet label came through fleetKey() ------------------------
// The config dir's basename is `.claude`; the fixture config maps the PARENT's
// basename. A basename-keyed lookup finds nothing and this goes red.
check('the root block is labelled with the fleet member (parent-basename key)',
  String(byId.get('root')?.type || '').includes('fixture-agent-label'),
  `got "${byId.get('root')?.type}"`);

// --- leg 5: the tree carries what a viewer navigates BY --------------------
// Without these the tree is a payload nobody can use: `count` is what a client
// passes back as `since`, and `lastLine` is what tells two same-type blocks
// apart when neither log is in the document.
const aliveCount = byId.get(ALIVE_AGENT)?.count;
check('the alive subagent carries a non-zero event count', typeof aliveCount === 'number' && aliveCount > 0, `got ${aliveCount}`);
check('the alive subagent carries its last log line as text',
  byId.get(ALIVE_AGENT)?.lastLine === ALIVE_LAST_LINE, `got "${byId.get(ALIVE_AGENT)?.lastLine}"`);
check('the graph tooltip carries the last log line',
  String(state.svg).includes(ALIVE_LAST_LINE), 'the <title> on the node block should end with it');

// --- leg 6: /state is the TREE, and the logs are not in it -----------------
// The pair: no logs here, logs there. Checked against the alive agent, which
// leg 5 just established HAS events - so "no log" cannot be true for free.
const noLogs = state.agents.filter((a) => (a.eventsHtml || []).length > 0).map((a) => a.id);
check('/state carries no agent logs at all', noLogs.length === 0, `agents with logs: ${noLogs.join(', ')}`);
check('/state carries none of the alive agent\'s log text', !stateRes.body.includes(ONLY_IN_ALIVE_LOG));

const allIds = [...byId.keys()].join(',');
const full = await get(`/state?logs=${encodeURIComponent(allIds)}`);
check('GET /state?logs=<all> returns 200', full.status === 200, `status ${full.status}`);
check('/state?logs=<all> DOES carry the alive agent\'s log', full.body.includes(ONLY_IN_ALIVE_LOG));
check('the tree-only /state is materially smaller than the all-logs one',
  stateRes.body.length * 2 < full.body.length,
  `tree ${stateRes.body.length}B vs all-logs ${full.body.length}B`);

// --- leg 7: /agent/<id> is ONE agent's log --------------------------------
const aliveLog = await getJson(`/agent/${ALIVE_AGENT}`, 'the per-agent route');
check(`GET /agent/${ALIVE_AGENT} returns 200`, aliveLog.status === 200, `status ${aliveLog.status}`);
if (!aliveLog.json) noVerdict(`/agent/${ALIVE_AGENT} did not answer with a log, so legs 7-9 would measure nothing`);
const aliveBody = (aliveLog.json.eventsHtml || []).join('');
check('the per-agent log reports since=0 and a total matching the tree',
  aliveLog.json.since === 0 && aliveLog.json.total === aliveCount,
  `since ${aliveLog.json.since}, total ${aliveLog.json.total}, tree count ${aliveCount}`);
check('the per-agent log ships exactly `total` events',
  (aliveLog.json.eventsHtml || []).length === aliveLog.json.total,
  `${(aliveLog.json.eventsHtml || []).length} vs ${aliveLog.json.total}`);
check('the per-agent log IS that agent\'s log', aliveBody.includes(ONLY_IN_ALIVE_LOG));
check('the per-agent log carries NOT the stopped agent\'s log', !aliveBody.includes(ONLY_IN_STOPPED_LOG));
check('the per-agent log carries NOT the root session\'s log', !aliveBody.includes(ONLY_IN_ROOT_LOG));

const stoppedLog = await getJson(`/agent/${STOPPED_AGENT}`, 'the per-agent route');
const stoppedBody = (stoppedLog.json?.eventsHtml || []).join('');
check('the other agent\'s route returns the OTHER log',
  stoppedBody.includes(ONLY_IN_STOPPED_LOG) && !stoppedBody.includes(ONLY_IN_ALIVE_LOG));

// The root log route must reproduce the spawn annotation, which is derived from
// EVERY agent's meta.json. That is the one thing a single-transcript route
// could plausibly lose, and losing it is invisible - the log still renders.
const rootLog = await getJson('/agent/root', 'the per-agent route');
const rootBody = (rootLog.json?.eventsHtml || []).join('');
check('the root log renders', rootBody.includes(ONLY_IN_ROOT_LOG));
check('the root log still annotates what each Agent call spawned',
  rootBody.includes('spawned <b>software-engineer</b>') && rootBody.includes('spawned <b>qa-engineer</b>'));

// TWO CODE PATHS RENDER A LOG, and they must not drift. snapshot() renders one
// while it walks the whole session; agentLog() renders one from a single
// transcript plus the session's .meta.json files. The second exists so a 10s
// poll does not re-parse hundreds of transcripts, and it reconstructs by hand
// what the first gets for free - the spawner in a from/to header, and what each
// Agent call spawned. Drift there is invisible: both still render a plausible
// log. So compare them byte for byte on the same agent.
// BOTH agents, because each covers a different half of what agentLog()
// reconstructs by hand: the subagent's log exercises the from/to header (its
// spawner has to be resolved from the metas), the root's exercises the spawn
// annotation (what each Agent call produced). Compare only one and the other
// half is a blind region.
const viaSnapshot = new Map(JSON.parse(full.body).agents.map((a) => [a.id, a]));
for (const [who, id, log] of [['subagent', ALIVE_AGENT, aliveLog.json], ['root', 'root', rootLog.json]]) {
  const mine = viaSnapshot.get(id);
  check(`the per-agent route renders EXACTLY what the snapshot path renders (${who})`,
    JSON.stringify(mine?.eventsHtml) === JSON.stringify(log?.eventsHtml),
    'agentLog() and snapshot() disagree about the same log');
  check(`...and that ${who} comparison was not vacuous`, (mine?.eventsHtml || []).length > 0);
}

const unknown = await get('/agent/nosuchagent99');
check('an unknown agent id is a 404, not an empty log', unknown.status === 404, `status ${unknown.status}`);
const traversal = await get('/agent/..%2F..%2F..%2Fetc%2Fpasswd');
check('a traversal-shaped agent id is refused', traversal.status === 404, `status ${traversal.status}`);

// --- leg 8: ?since ships only what is new ---------------------------------
if (aliveLog.json.total < 2) {
  noVerdict(`the alive agent has ${aliveLog.json.total} event(s); with fewer than two, "only the new one" is indistinguishable from "all of them"`);
}
const tailFrom = aliveLog.json.total - 1;
const tail = await getJson(`/agent/${ALIVE_AGENT}?since=${tailFrom}`, 'the incremental route');
check('?since=<total-1> returns exactly one event',
  (tail.json?.eventsHtml || []).length === 1, `got ${(tail.json?.eventsHtml || []).length}`);
check('?since echoes the offset it served from', tail.json?.since === tailFrom, `got ${tail.json?.since}`);
check('?since returns the LAST event, byte-identical to the full fetch\'s last',
  tail.json?.eventsHtml?.[0] === aliveLog.json.eventsHtml[tailFrom]);
check('?since did NOT return the first event',
  tail.json?.eventsHtml?.[0] !== aliveLog.json.eventsHtml[0],
  'the fixture\'s first and last events must differ or this leg is vacuous');
const caughtUp = await getJson(`/agent/${ALIVE_AGENT}?since=${aliveLog.json.total}`, 'the incremental route');
check('?since=<total> returns nothing at all - what a poll on a quiet agent costs',
  (caughtUp.json?.eventsHtml || []).length === 0, `got ${(caughtUp.json?.eventsHtml || []).length}`);

// --- leg 9: images by hash, and the baked/not-baked pair ------------------
const hashesIn = (html) => [...String(html).matchAll(/data-img="([0-9a-f]+)"/g)].map((m) => m[1]);
const aliveHashes = hashesIn(aliveBody);
const rootHashes = hashesIn(rootBody);
if (!aliveHashes.length) noVerdict('the alive agent\'s log references no image at all, so leg 9 would measure nothing');
if (!rootHashes.length) noVerdict('the root log references no image at all, so leg 9 has no baked control');

const served = await getBytes(`/img/${aliveHashes[0]}`);
check('GET /img/<hash> returns 200', served.status === 200, `status ${served.status}`);
check('GET /img/<hash> returns the fixture image BYTE FOR BYTE',
  served.buf && served.buf.equals(agentImgBytes), `${served.buf?.length} bytes vs ${agentImgBytes.length}`);
check('GET /img/<hash> declares the image content type', served.type.startsWith('image/'), `got "${served.type}"`);
check('GET /img/<hash> is cacheable for ever - the URL is a content hash',
  /immutable/.test(served.cache), `got "${served.cache}"`);
const missing = await get('/img/0000000000000000');
check('an unknown hash is a 404, never an empty 200 a browser would cache for ever',
  missing.status === 404, `status ${missing.status}`);

// THE PAIR. Same mechanism, same file type, two agents. The document bakes the
// root session's log, so ITS image must be inline (that is the standalone-page
// property); it does not bake a subagent's log, so THAT image must be absent
// and reachable only by hash.
check('GET / does NOT inline an image from a log it did not bake',
  !page.body.includes(agentImgB64),
  `${agentImgB64.length} base64 chars found in the ${page.body.length}B document`);
check('GET / DOES inline the image from the root log it bakes',
  page.body.includes(rootImgB64), 'without this, the leg above passes on a build that inlines nothing');
check('GET / bakes the root session\'s log', page.body.includes(ONLY_IN_ROOT_LOG));
check('GET / bakes NO subagent log', !page.body.includes(ONLY_IN_ALIVE_LOG));
check('GET / still carries the whole tree', page.body.includes(`"${STOPPED_AGENT}"`) && page.body.includes(`"${ALIVE_AGENT}"`));

// --- leg 10: the negative control -----------------------------------------
// Remove one subagent's transcript and ask again. See the header: a control
// that does not fire is NO VERDICT, and a control the tree never contained is
// vacuous, which is why the guard below runs first.
if (!byId.has(ALIVE_AGENT)) {
  noVerdict(`the negative control has nothing to remove: ${ALIVE_AGENT} was never in the tree`);
}
rmSync(aliveJsonl);
rmSync(aliveMeta);
const after = await get('/state');
let state2;
try { state2 = JSON.parse(after.body); } catch (e) { noVerdict(`/state is not JSON after the control (${e.message})`); }
const ids2 = new Set((state2.agents || []).map((a) => a.id));
if (ids2.has(ALIVE_AGENT)) {
  noVerdict(`NEGATIVE CONTROL DID NOT FIRE: ${ALIVE_AGENT} is still in the tree after its transcript was deleted. `
    + 'Either the server is not reading the transcripts per request, or this test deleted a file it never read. '
    + 'Those two are indistinguishable from here, so no verdict is issued about serve.mjs.');
}
ok(`negative control fired: ${ALIVE_AGENT} left the tree when its transcript was deleted`);
check('the control removed ONLY its own agent: the stopped one survived', ids2.has(STOPPED_AGENT));
check('the control removed ONLY its own agent: the root survived', ids2.has('root'));
// The per-agent route reads from disk per request too, and it answered 200 for
// this id moments ago - so this is the same control aimed at the new route.
const goneLog = await get(`/agent/${ALIVE_AGENT}`);
check('the per-agent route also loses the agent when its transcript is deleted',
  goneLog.status === 404, `status ${goneLog.status}`);

// --- verdict ----------------------------------------------------------------
if (fails.length) {
  console.log(`\nFAIL - ${fails.length} check(s):`);
  for (const f of fails) console.log(`  - ${f}`);
  process.exit(1);
}
console.log('\nPASS - server, tree, lazy logs, images by hash, and the negative control.');
process.exit(0);
