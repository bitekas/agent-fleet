#!/usr/bin/env node
// web-hierarchy-server - the skill's self-updating viewer. Serves a spawn-tree
// graph + per-agent logs that the page refreshes every 10s IN PLACE: new log
// events are APPENDED (never a full reload), so the viewer's scroll position and
// selected agent are preserved. The formatting (transcript → document) runs here,
// server-side (format.mjs) - log content never passes through the root agent or
// its context window; the agent only starts this process once.
//
// THE TREE IS SERVED; THE LOGS ARE FETCHED. A session can have hundreds of
// agents, and a document carrying every agent's log is not a document anyone can
// open: on a 228-agent session that was 358MB at GET /, 110MB of it base64
// images, re-sent on every 10s poll. So:
//
//   GET /                 complete HTML document - CSS, the polling client, and
//                         a baked-in snapshot of THE TREE plus THE ROOT
//                         SESSION'S LOG (with that part's images inline as data
//                         URIs, so a saved copy still renders).
//   GET /state            JSON snapshot: the tree for every agent (type, task,
//                         model, times, alive/stopped, event count, last log
//                         line) and NO logs, unless ?logs=<id>,<id> names some.
//   GET /agent/<id>       JSON: that agent's rendered log, and nothing else.
//   GET /agent/<id>?since=<n>   only events from index n - what the poll uses,
//                         so a quiet agent costs an empty array per tick.
//   GET /img/<hash>       one image by content hash, from the deduplicated
//                         store. Immutable, so the browser caches it for ever.
//
// WHAT A SAVED PAGE THEREFORE HAS: the whole tree, and the root session's log.
// Not every agent's log - those were never in the document. For a frozen record
// of EVERY log in one file, build.mjs still bakes all of them.
//
// Usage: node serve.mjs [--port=N] [--session=<id>] [--host=<addr>] [--cap=KB]
//        node serve.mjs --help     (prints this usage and exits 0, binding nothing)
// Every flag defaults from config.json (see config.example.json); a flag wins.
// config.json is WEB_HIERARCHY_CONFIG when set, else the file
// `fleet where web-hierarchy-server config.json` names (format.mjs); --help
// prints the one it resolved.
// WHO CAN READ IT: the page carries every agent's transcript and has no login,
// so it listens on 127.0.0.1 unless `server.host` (or --host) names another
// address. A viewer on another device needs that address set: the VPN or LAN
// address it reaches this machine on, or 0.0.0.0 for every interface. And no
// response grants a cross-origin read (no Access-Control-Allow-Origin): the page
// fetches only from its own origin, and that header would let any web page a
// viewer has open read the transcripts through the viewer's browser.
// serve.exposure.test.mjs measures both.
//
// --help is a REAL operation, not a courtesy: reaching its output means node ran
// this file, resolved and loaded format.mjs, parsed config.json and resolved the
// identity roster, because all of that happens at import time. That is what
// installation/check drives instead of asking whether the files exist - a file
// that exists and a file the runtime can actually load are different claims, and
// stat(2) cannot tell them apart.
//
// SESSION FOLLOWING: without --session the server re-picks the most recently
// active session on EVERY snapshot, and serves a "waiting" page while none has
// subagents yet - so it can be started at boot by its service unit and outlive
// any individual Claude session (/exit, `claude --update`, a unit restart all
// mint a new session id). --session pins one for a frozen view.
// It scans all project slugs under CLAUDE_CONFIG_DIR (see format.mjs), so each
// agent serves its own tree by inheriting that env var.
import { createServer } from 'node:http';
import { gzipSync } from 'node:zlib';
import { networkInterfaces } from 'node:os';
import { pickSession, snapshot, agentLog, isSafeAgentId, imgBytes, svgMarkup, css, imgRuntimeJs, jsonForScript, cfg, defaultPort, PROJECTS, CONFIG_FILE } from './format.mjs';

// Local values come from config.json via format.mjs's cfg() (see
// config.example.json); a CLI flag still wins, which is what the service units
// use. The default port is the one this machine's `servers` entry gives the
// running CLAUDE_CONFIG_DIR, so a hand run cannot default onto another agent's
// port and collide with a live server.
const arg = (k, d) => { const a = process.argv.find((x) => x.startsWith(`--${k}=`)); return a ? a.split('=')[1] : d; };
if (process.argv.includes('--help') || process.argv.includes('-h')) {
  console.log('usage: node serve.mjs [--port=N] [--session=<id>] [--host=<addr>] [--cap=KB]');
  console.log(`  config:     ${CONFIG_FILE}`);
  console.log(`  transcripts: ${PROJECTS}`);
  console.log(`  default port: ${defaultPort()}`);
  process.exit(0);
}
const PORT = Number(arg('port', defaultPort()));
const HOST = arg('host', cfg('server.host', '127.0.0.1'));
const CAPKB = Number(arg('cap', cfg('server.cap_kb', 16)));
const PINNED = arg('session', null);
// Resolved per snapshot, not once at startup: as a boot-time service the
// server long outlives the session it first saw. Throws while the config root
// doesn't exist yet (fresh machine) - that's a wait state, not a failure.
const currentSession = () => { try { return pickSession(PINNED); } catch { return null; } };

// `logsFor` names the agents whose logs this payload carries; `bakeImgs` says
// whether its images travel as data URIs.
//
// The two flags move together and for one reason. A payload that is BAKED into
// a document (GET /) must be self-contained, so it carries the root log and the
// data URIs that log and the graph avatars need. A payload the page FETCHES
// (GET /state, every 10s, for ever) must carry neither: its logs come from
// /agent/<id> and its images from /img/<hash>, which the browser caches by
// content hash. Handing data URIs to the poll is the 358MB regression in
// miniature - the graph avatars alone are ~95KB of base64 every tick.
const statePayload = ({ logsFor = [], bakeImgs = false } = {}) => {
  const sid = currentSession();
  // No session has delegated yet: serve a complete, empty document rather than
  // exiting - the agent may not even be up, and the page must survive the wait.
  if (!sid) return { sessionId: '', stamp: 'waiting for a session…', workingCount: 0, firstId: null, svg: '', imgs: {}, agents: [] };
  const s = snapshot(sid, { capKB: CAPKB, logsFor });
  return {
    sessionId: s.sessionId, stamp: s.stamp, workingCount: s.workingCount, firstId: s.firstId,
    svg: svgMarkup(s), imgs: bakeImgs ? s.imgs : {},
    agents: s.agents.map((a) => ({
      id: a.id, type: a.type, desc: a.desc, header: a.header, active: a.active,
      // eventCount is the log's real length even when its HTML was not
      // rendered; it is what the client passes back as `since`.
      count: a.eventCount, lastLine: a.lastLine, eventsHtml: a.eventsHtml,
    })),
  };
};

// ⚠️ EVERYTHING BELOW IS INSIDE ONE TEMPLATE LITERAL, comments included. A
// backtick or a ${...} in a comment here is not a comment - the first ends the
// literal and the second interpolates - and `node --check` reports it as a
// syntax error somewhere else entirely. Quote code in these comments with
// 'single quotes'.
const shell = () => `<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agent hierarchy · live</title><style>${css()}</style></head><body><main>
  <h1>Agent hierarchy <span style="font-size:11px;color:var(--success)">● live</span></h1>
  <p class="stamp" id="stamp">connecting…</p>
  <div class="graphwrap" id="graph"></div>
  <p class="hint">Blue = alive · grey = stopped. Click a block to load that agent's full log below; hover one to see what it is doing. Updates every 10s in place — your scroll and selection are preserved. Extended <em>thinking</em> is stored encrypted in subagent transcripts, so only its position is shown.</p>
  <div id="logs"></div>
</main>
<script>
(function () {
  var INIT = ${jsonForScript(statePayload({ logsFor: ['root'], bakeImgs: true }))};
  var CUR = null, rendered = {}, loading = {}, CURSESS = null, TREE = {};
  // image store: the images BAKED into this document (the graph avatars and the
  // root session's log). Anything that arrives later resolves through
  // img/<hash> instead - see imgSrc() in the runtime below.
  var IMGS = {};
  ${imgRuntimeJs}
  function mergeImgs(m) { if (m) for (var k in m) if (!IMGS[k]) IMGS[k] = m[k]; }
  function frag(html) { var t = document.createElement('template'); t.innerHTML = html; return t.content; }
  function streamOf(id) { var d = document.getElementById('log-' + id); return d ? d.querySelector('.stream') : null; }
  // A log container is created when the viewer first selects that agent, not
  // for every agent in the tree: at a few hundred agents, pre-building them all
  // is the same cost this whole design removes, one layer down.
  function ensureLog(a) {
    var div = document.getElementById('log-' + a.id);
    if (!div) {
      div = document.createElement('div'); div.className = 'agentlog'; div.id = 'log-' + a.id;
      div.innerHTML = '<header><span class="atype"></span><span class="adesc"></span><span class="ameta"></span></header><div class="stream"></div>';
      document.getElementById('logs').appendChild(div); rendered[a.id] = 0;
    }
    div.querySelector('.atype').textContent = a.type;
    div.querySelector('.adesc').textContent = a.desc;
    div.querySelector('.ameta').innerHTML = a.header;
    // mutable zone: alive flag drives the last-line marker animation, re-set
    // every tick and dropped when the agent stops (see format.mjs CSS)
    div.classList.toggle('alive', !!a.active);
    return div;
  }
  function appendEvents(id, html) {
    if (!html || !html.length) return;
    var stream = streamOf(id); if (!stream) return;
    // Measured BEFORE the append: a log now arrives asynchronously, so
    // "was the viewer at the bottom" has to be answered at append time rather
    // than once per refresh.
    var atBottom = (window.innerHeight + window.scrollY) >= (document.body.scrollHeight - 60);
    for (var i = 0; i < html.length; i++) stream.appendChild(frag(html[i]));
    hydrateImgs();
    if (atBottom) window.scrollTo(0, document.body.scrollHeight);
  }
  // Fetch only what this viewer is actually looking at, and only what it does
  // not already have: 'since' is the number of events already in the DOM, so a
  // poll on a quiet agent transfers an empty array.
  function loadLog(id) {
    if (!id || loading[id]) return;
    loading[id] = 1;
    fetch('agent/' + encodeURIComponent(id) + '?since=' + (rendered[id] || 0))
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        loading[id] = 0;
        if (!d || d.id !== id) return;
        // The server clamps 'since' into range, so a mismatch means the
        // transcript shrank or was replaced under us and the stream in the DOM
        // no longer describes it. Drop it and take the whole log again rather
        // than appending into a misaligned stream, which would silently show a
        // log that never existed.
        if (d.since !== (rendered[id] || 0)) {
          var st = streamOf(id); if (st) st.innerHTML = '';
          rendered[id] = 0;
          if (d.since !== 0) { loadLog(id); return; }
        }
        appendEvents(id, d.eventsHtml);
        rendered[id] = d.total;
      })
      .catch(function () { loading[id] = 0; });
  }
  function select(id, pushHash) {
    if (!id) return; CUR = id;
    if (TREE[id]) ensureLog(TREE[id]);
    var ls = document.querySelectorAll('.agentlog'); for (var i = 0; i < ls.length; i++) ls[i].style.display = 'none';
    var ns = document.querySelectorAll('.node'); for (var j = 0; j < ns.length; j++) ns[j].classList.remove('sel');
    var log = document.getElementById('log-' + id); if (log) log.style.display = 'block';
    var node = document.getElementById('node-' + id); if (node) node.classList.add('sel');
    if (pushHash) { try { location.hash = 'a-' + id; } catch (e) {} }
    loadLog(id);
  }
  function applyGraph(snap) {
    var g = document.getElementById('graph'); g.innerHTML = snap.svg;
    var ns = g.querySelectorAll('.node');
    for (var i = 0; i < ns.length; i++) (function (n) { n.addEventListener('click', function () { select(n.dataset.id, true); }); })(ns[i]);
  }
  function applyTree(snap) {
    TREE = {};
    for (var k = 0; k < snap.agents.length; k++) {
      var a = snap.agents[k];
      TREE[a.id] = a;
      // Refresh the header of a log that is already open (alive flag, times).
      if (document.getElementById('log-' + a.id)) ensureLog(a);
      // A payload that CARRIES a log seeds it: that is the baked-in root
      // session log at GET /, and build-style callers that ask for more.
      if (a.eventsHtml && a.eventsHtml.length && !rendered[a.id]) {
        ensureLog(a); appendEvents(a.id, a.eventsHtml); rendered[a.id] = a.eventsHtml.length;
      }
    }
  }
  function update(snap, first) {
    document.getElementById('stamp').innerHTML = snap.sessionId
      ? 'session <code>' + snap.sessionId.slice(0, 8) + '</code> · ' + snap.stamp + ' · <b>' + snap.workingCount + ' working</b> · ' + snap.agents.length + ' agents · live (10s)'
      : snap.stamp + ' · live (10s)';
    // The server follows the newest session, so the id can change under a
    // long-lived page (/exit, an agent restart). Agent ids are per-session:
    // keeping the old logs would strand CUR on a block the graph no longer has.
    if (snap.sessionId !== CURSESS) {
      CURSESS = snap.sessionId;
      document.getElementById('logs').innerHTML = ''; rendered = {}; loading = {}; CUR = null;
    }
    var y = window.scrollY;
    mergeImgs(snap.imgs); applyGraph(snap); applyTree(snap); hydrateImgs();
    if (first) { var want = (location.hash || '').replace(/^#a-/, ''); select(TREE[want] ? want : snap.firstId, false); }
    else { select(CUR || snap.firstId, false); window.scrollTo(0, y); }
  }
  // from/to headers: clicking a from-link selects that agent like its graph block
  document.addEventListener('click', function (ev) {
    var t = ev.target && ev.target.closest ? ev.target.closest('.fromlink') : null;
    if (t && t.dataset.id) { ev.preventDefault(); select(t.dataset.id, true); window.scrollTo(0, 0); }
  });
  update(INIT, true); // baked-in snapshot: the tree and the root log render with no server
  function tick() {
    fetch('state').then(function (r) { return r.json(); })
      .then(function (snap) { update(snap, false); })
      .catch(function () {})
      .then(function () { setTimeout(tick, 10000); });
  }
  setTimeout(tick, 10000);
})();
</script></body></html>`;

// gzip when the client accepts it - the multi-MB documents (base64-image
// heavy) shave ~25-30%, and Content-Length lets the browser show progress
// instead of an opaque forever-load through forwarded/tunneled ports.
// No Access-Control-Allow-Origin, on purpose (the header comment, WHO CAN READ IT).
const send = (req, res, status, type, body, extra) => {
  const buf = Buffer.isBuffer(body) ? body : Buffer.from(body);
  const headers = { 'content-type': type, 'cache-control': 'no-store', ...(extra || {}) };
  // Not images: PNG/JPEG/WebP are already compressed, so gzipping one burns CPU
  // on every cold fetch to save nothing. They are also the one response class
  // the browser caches for ever, so the saving would be once per viewer anyway.
  const compressible = !String(type).startsWith('image/');
  if (compressible && /\bgzip\b/.test(String(req.headers['accept-encoding'] || '')) && buf.length > 8192) {
    const gz = gzipSync(buf);
    res.writeHead(status, { ...headers, 'content-encoding': 'gzip', 'content-length': gz.length });
    res.end(gz);
  } else {
    res.writeHead(status, { ...headers, 'content-length': buf.length });
    res.end(buf);
  }
};

// Every route builds its whole body BEFORE writeHead: snapshot generation can
// throw on a half-written transcript line or a file vanishing mid-read, and a
// 500 attempt after headers are sent crashes the whole server
// (ERR_HTTP_HEADERS_SENT - observed in the wild).
const guard = (req, res, make) => {
  try { make(); } catch (e) {
    if (!res.headersSent) res.writeHead(500, { 'content-type': 'text/plain' });
    res.end('error: ' + e.message);
  }
};
const ids = (s) => String(s || '').split(',').map((x) => x.trim()).filter(Boolean);

const server = createServer((req, res) => {
  const u = new URL(req.url || '/', 'http://localhost');
  const path = u.pathname;
  if (path === '/state') {
    return guard(req, res, () => send(req, res, 200, 'application/json',
      JSON.stringify(statePayload({ logsFor: ids(u.searchParams.get('logs')), bakeImgs: false }))));
  }
  if (path.startsWith('/agent/')) {
    return guard(req, res, () => {
      const id = decodeURIComponent(path.slice('/agent/'.length));
      const sid = currentSession();
      // isSafeAgentId is also enforced inside agentLog, where the file path is
      // actually built; it is repeated here so a malformed id is a 404 rather
      // than an indistinguishable "no such agent".
      const log = sid && isSafeAgentId(id) ? agentLog(sid, id, { capKB: CAPKB, since: u.searchParams.get('since') }) : null;
      if (!log) return send(req, res, 404, 'application/json', JSON.stringify({ error: 'no such agent', id }));
      send(req, res, 200, 'application/json', JSON.stringify(log));
    });
  }
  if (path.startsWith('/img/')) {
    return guard(req, res, () => {
      const hash = decodeURIComponent(path.slice('/img/'.length));
      const img = /^[0-9a-f]{1,64}$/.test(hash) ? imgBytes(hash) : null;
      // 404, never an empty 200: the URL is a content hash, so whatever the
      // browser gets here it caches for ever.
      if (!img) return send(req, res, 404, 'text/plain', 'no such image');
      // Immutable by construction - the name IS the content - so the browser
      // fetches each image once per viewer, however many polls go by.
      send(req, res, 200, img.mime, img.buf, { 'cache-control': 'public, max-age=31536000, immutable' });
    });
  }
  guard(req, res, () => send(req, res, 200, 'text/html; charset=utf-8', shell()));
});

// A transient per-request failure (or client abort) must never take the
// whole live view down - log and keep serving; the 10s poll retries anyway.
process.on('uncaughtException', (e) => console.error('[serve] uncaught:', e && e.message ? e.message : e));

server.listen(PORT, HOST, () => {
  const ips = [];
  for (const list of Object.values(networkInterfaces())) for (const i of list || []) {
    if (i.family === 'IPv4' && !i.internal) ips.push(i.address);
  }
  // Which address to PRINT: with several interfaces, prefer the one the viewing
  // device can actually reach (`server.preferred_ip_prefix`).
  const pref = String(cfg('server.preferred_ip_prefix', ''));
  const tail = (pref && ips.find((a) => a.startsWith(pref))) || ips[0] || 'localhost';
  const sid = currentSession();
  // The BOUND port, never the requested one: --port=0 asks the kernel for an
  // ephemeral port, and a banner echoing the request would print `0` - a URL
  // nothing can open, and the only thing a test (or an operator) has to learn
  // which port the server actually took.
  const bound = server.address().port;
  // The URLs printed are the ones that answer: a loopback listener has no
  // network URL, and one bound to a single address answers only there.
  const loopback = /^127\.|^::1$|^localhost$/.test(HOST);
  const wildcard = HOST === '0.0.0.0' || HOST === '::';
  const at = HOST.includes(':') ? `[${HOST}]` : HOST;
  console.log(`web-hierarchy server — ${PINNED ? `pinned to session ${PINNED.slice(0, 8)}` : `following newest session${sid ? ` (${sid.slice(0, 8)})` : ' (none yet — waiting)'}`}`);
  console.log(`  local:    ${loopback || wildcard ? `http://localhost:${bound}/` : `none (bound to ${HOST} only)`}`);
  console.log(`  network:  ${loopback ? `none (bound to ${HOST}; set server.host to serve another device)` : `http://${wildcard ? tail : at}:${bound}/`}`);
});
