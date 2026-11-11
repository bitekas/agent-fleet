#!/usr/bin/env node
// serve.exposure.test.mjs - WHO CAN READ THE VIEWER. The page serves every
// agent's transcript and has no login, so two properties are all that keep it
// off the network and out of other sites' pages:
//
//   node .claude/skills/web-hierarchy-server/serve.exposure.test.mjs
//
//   1. NO CROSS-ORIGIN READ. No response carries Access-Control-Allow-Origin
//      (nor -Allow-Credentials), on any route, to a request carrying a foreign
//      Origin. The page fetches state, agent/<id> and img/<hash> from its own
//      origin, so it needs no such header. A browser lets a page READ a
//      response from another origin only when that header grants it; with `*`,
//      any web page a viewer has open can fetch http://<host>:<port>/state and
//      read every transcript, from the viewer's own browser, which reaches the
//      server wherever the viewer does.
//   2. THE DEFAULT LISTENER IS LOOPBACK. With no `server.host` in config.json
//      and no --host flag, the server answers on 127.0.0.1 and refuses every
//      other local address this test can reach (127.0.0.2 on Linux, which
//      routes all of 127/8 to lo, and every non-internal IPv4 interface
//      address). Bound to every interface by default, anyone on the network
//      reads the transcripts. An install that wants another device to read the
//      page names that address in `server.host` (config.example.json).
//
// WHY THIS IS NOT A LEG OF serve.test.mjs: that file runs on the fixture config,
// which binds 127.0.0.1 EXPLICITLY, so it cannot see the default change. This
// file writes a config with no `server` key at all and asserts that before it
// starts the server - without that assertion a fixture that names 127.0.0.1
// would turn leg 2 green whatever the default is.
//
// CONTROLS - each makes an absence mean something. Do not remove them as noise:
//   * every route answers the foreign-Origin request with the status that route
//     owes (200, or 404 for an unknown agent or image), so "no header" is about
//     the server's answer and not about a request that never arrived;
//   * the server answers on 127.0.0.1, so a refused connection elsewhere is not
//     a server that never listened;
//   * each other address first reaches a WILDCARD listener this test opens
//     itself, so a refused connection to the server there is about the
//     server's bind, not about an address that routes nowhere. An address that
//     does not reach even the wildcard listener is skipped, and when none
//     does, leg 2 is NO VERDICT, never a pass.
//
// Offline and hermetic: a temporary copy of fixtures/config-dir, a config file in
// the same temporary directory, one ephemeral port (read off the banner, never
// guessed), and nothing outside the temporary directory read or written.
//
// EXIT CODES - THREE, NEVER TWO:
//   0  PASS       both legs green.
//   1  FAIL       a header was sent, or another address reached the server.
//   2  NO VERDICT the server never printed a banner, a route did not answer, a
//                 control did not hold, or no address but 127.0.0.1 was
//                 reachable. Read a 2 as "this file measured nothing".
import { spawn } from 'node:child_process';
import { cpSync, mkdtempSync, readFileSync, writeFileSync, rmSync, existsSync } from 'node:fs';
import { request } from 'node:http';
import { createServer, createConnection } from 'node:net';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { tmpdir, networkInterfaces } from 'node:os';

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURES = join(HERE, 'fixtures');
const FOREIGN = 'http://foreign-site.example';

const fails = [];
const check = (name, cond, detail = '') => {
  console.log(`  ${cond ? 'ok  ' : 'FAIL'} ${name}${cond || !detail ? '' : ` - ${detail}`}`);
  if (!cond) fails.push(name);
};
let child = null;
const tmp = mkdtempSync(join(tmpdir(), 'web-hierarchy-exposure-test-'));
process.on('exit', () => {
  try { if (child && child.exitCode === null) child.kill('SIGKILL'); } catch { /* gone */ }
  try { rmSync(tmp, { recursive: true, force: true }); } catch { /* best effort */ }
});
const noVerdict = (why) => {
  console.log(`\nNO VERDICT: ${why}\nThis file measured nothing. Do not read this as a pass.`);
  process.exit(2);
};

// --- the config: the fixture's, with NO server key ----------------------------
if (!existsSync(join(FIXTURES, 'config-dir'))) noVerdict(`fixtures/config-dir is missing from ${FIXTURES}`);
const configDir = join(tmp, 'fixture-agent', '.claude');
cpSync(join(FIXTURES, 'config-dir'), configDir, { recursive: true });
// The fixture's alive transcript carries a __NOW__ token for its timestamp
// (serve.test.mjs, leg 3); a real timestamp keeps the session a valid one here.
const alive = join(configDir, 'projects', '-fixture-project', '11111111-1111-4111-8111-111111111111', 'subagents', 'agent-aaaa1111.jsonl');
if (!existsSync(alive)) noVerdict(`the copied fixture tree has no ${alive}`);
writeFileSync(alive, readFileSync(alive, 'utf8').split('__NOW__').join(new Date().toISOString()));
const config = JSON.parse(readFileSync(join(FIXTURES, 'config.fixture.json'), 'utf8'));
delete config.server;
const configFile = join(tmp, 'config.json');
writeFileSync(configFile, JSON.stringify(config, null, 2));
if ('server' in JSON.parse(readFileSync(configFile, 'utf8'))) noVerdict('the written config still has a server key');

console.log(`web-hierarchy-server exposure test\n  tempdir: ${tmp}`);
child = spawn(process.execPath, [join(HERE, 'serve.mjs'), '--port=0'], {
  env: { ...process.env, CLAUDE_CONFIG_DIR: configDir, WEB_HIERARCHY_CONFIG: configFile },
  stdio: ['ignore', 'pipe', 'pipe'],
});
const banner = await new Promise((resolve) => {
  let buf = '';
  const done = setTimeout(() => resolve(null), 20000);
  child.stdout.on('data', (d) => {
    buf += String(d);
    const m = buf.match(/http:\/\/localhost:(\d+)\/[^\n]*\n[^\n]*network:[^\n]*\n/);
    if (m) { clearTimeout(done); resolve({ port: Number(m[1]), text: buf }); }
  });
  child.stderr.on('data', (d) => process.stderr.write(`  [serve.mjs stderr] ${d}`));
  child.on('exit', (code) => { clearTimeout(done); resolve(buf ? { port: null, text: buf, code } : null); });
});
if (!banner || !banner.port) noVerdict(`serve.mjs printed no usable banner within 20s: ${banner?.text || '<no output>'}`);
const PORT = banner.port;

// --- leg 1: no cross-origin read ----------------------------------------------
const get = (path, method = 'GET') => new Promise((resolve) => {
  const req = request({ host: '127.0.0.1', port: PORT, path, method,
    headers: { Origin: FOREIGN, 'Access-Control-Request-Method': 'GET' } }, (res) => {
    res.resume();
    res.on('end', () => resolve({ status: res.statusCode, headers: res.headers }));
  });
  req.on('error', (e) => noVerdict(`${method} ${path} did not answer (${e.message})`));
  req.setTimeout(20000, () => { req.destroy(); noVerdict(`${method} ${path} timed out`); });
  req.end();
});
const routes = [['/', 'GET', 200], ['/state', 'GET', 200], ['/state?logs=root', 'GET', 200],
  ['/agent/aaaa1111', 'GET', 200], ['/agent/nosuchagent', 'GET', 404], ['/img/0', 'GET', 404], ['/state', 'OPTIONS', 200]];
for (const [path, method, want] of routes) {
  const r = await get(path, method);
  if (r.status !== want) noVerdict(`${method} ${path} answered ${r.status}, not ${want}: the request is not reaching the route it names`);
  const granted = ['access-control-allow-origin', 'access-control-allow-credentials'].filter((h) => h in r.headers);
  check(`${method} ${path} with Origin ${FOREIGN}: no Access-Control-Allow-* header`, granted.length === 0,
    granted.map((h) => `${h}: ${r.headers[h]}`).join(', '));
}

// --- leg 2: the default listener is loopback ------------------------------------
const connects = (host, port) => new Promise((resolve) => {
  const s = createConnection({ host, port });
  const end = (v) => { s.destroy(); resolve(v); };
  s.setTimeout(3000, () => end(false));
  s.once('connect', () => end(true));
  s.once('error', () => end(false));
});
if (!(await connects('127.0.0.1', PORT))) noVerdict(`the server does not answer on 127.0.0.1:${PORT}`);
check('the server answers on 127.0.0.1', true);
// An interface address is printed by its position, never its value: this runs on
// CI machines whose logs are public, and their addresses are theirs.
const others = [['127.0.0.2', '127.0.0.2']];
for (const list of Object.values(networkInterfaces())) {
  for (const i of list || []) {
    if (i.family === 'IPv4' && !i.internal && !others.some(([a]) => a === i.address)) {
      others.push([i.address, `interface address #${others.length}`]);
    }
  }
}
const mask = (s) => String(s).replace(/\b(?!127\.)\d{1,3}(\.\d{1,3}){3}\b/g, '<address>');
const wildcard = createServer((s) => s.destroy());
await new Promise((r) => wildcard.listen(0, '0.0.0.0', r));
const ctlPort = wildcard.address().port;
let probed = 0;
for (const [addr, label] of others) {
  if (!(await connects(addr, ctlPort))) {
    console.log(`  skip ${label}: it does not reach even a wildcard listener here`);
    continue;
  }
  probed += 1;
  check(`the default listener refuses a connection at ${label}`, !(await connects(addr, PORT)),
    `${label} accepted on port ${PORT}: the server listens beyond loopback with no server.host set`);
}
wildcard.close();
if (probed === 0) noVerdict(`no address but 127.0.0.1 reaches a wildcard listener here (tried ${others.map(([, l]) => l).join(', ')}), so the bind is unmeasured`);
check('the banner advertises no network URL for a loopback listener',
  !/network:\s+http:\/\/(?!localhost|127\.)/.test(banner.text), mask(banner.text.trim()));

if (fails.length) {
  console.log(`\nFAIL - ${fails.length} check(s):\n  - ${fails.join('\n  - ')}`);
  process.exit(1);
}
console.log(`\nPASS - no cross-origin grant on any route; the default listener answers on loopback only (${probed} other address(es) probed).`);
process.exit(0);
