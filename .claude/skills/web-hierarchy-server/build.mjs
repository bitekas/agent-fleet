#!/usr/bin/env node
// web-hierarchy-server STATIC snapshot - bakes the current spawn-tree graph + per-agent
// logs into one self-contained HTML file for a frozen, shareable record (e.g.
// publish as a claude.ai Artifact). For the LIVE, self-updating view use
// serve.mjs instead (10s in-place updates, scroll/selection preserved).
// Formatting is done by format.mjs (shared) - content never passes through the
// root agent's context.
//
// Usage: node build.mjs <out.html> [sessionId] [--cap=KB]
import { writeFileSync } from 'node:fs';
import { pickSession, snapshot, svgMarkup, css, esc, imgRuntimeJs, jsonForScript, cfg } from './format.mjs';

const args = process.argv.slice(2);
const outPath = args[0];
// Local values come from config.json via format.mjs's cfg(); --cap still wins.
const capKB = Number((args.find((a) => a.startsWith('--cap=')) || '').split('=')[1]) || Number(cfg('server.cap_kb', 16));
const sessionId = pickSession(args[1] && !args[1].startsWith('--') ? args[1] : null);
if (!outPath) { console.error('usage: node build.mjs <out.html> [sessionId] [--cap=KB]'); process.exit(1); }
if (!sessionId) { console.error('no session found'); process.exit(1); }

// format.mjs always emits base64 data URIs (~2MB cap per image, placeholder
// note beyond), so this bake is fully self-contained by construction.
const s = snapshot(sessionId, { capKB });
const logs = s.agents.map((a) => `<div class="agentlog${a.active ? ' alive' : ''}" id="log-${esc(a.id)}">
    <header><span class="atype">${esc(a.type)}</span><span class="adesc">${esc(a.desc)}</span><span class="ameta">${a.header}</span></header>
    <div class="stream">${a.eventsHtml.join('')}</div>
  </div>`).join('');

writeFileSync(outPath, `<title>Agent hierarchy · ${esc(sessionId.slice(0, 8))}</title>
<style>${css()}</style>
<main>
  <h1>Agent hierarchy <span style="font-size:11px;color:var(--inactive)">snapshot</span></h1>
  <p class="stamp">session <code>${esc(sessionId.slice(0, 8))}</code> · built ${s.stamp} · <b>${s.workingCount} working</b> · ${s.agents.length} agents · auto-reloads every 60s</p>
  <div class="graphwrap">${svgMarkup(s)}</div>
  <p class="hint">Blue = alive · grey = stopped. Click a block to show that agent's full log below. Extended <em>thinking</em> is stored encrypted in subagent transcripts, so only its position is shown.</p>
  ${logs || '<p class="stamp">No subagents in this session yet.</p>'}
</main>
<script>
  (function () {
    // image store: unique images embedded once, every <img data-img> occurrence
    // hydrated from it; click opens full size (Blob URL)
    var IMGS = ${jsonForScript(s.imgs)};
    ${imgRuntimeJs}
    hydrateImgs();
    function sel(id) {
      var ls = document.querySelectorAll('.agentlog'); for (var i = 0; i < ls.length; i++) ls[i].style.display = 'none';
      var ns = document.querySelectorAll('.node'); for (var j = 0; j < ns.length; j++) ns[j].classList.remove('sel');
      var log = document.getElementById('log-' + id), node = document.getElementById('node-' + id);
      if (log) log.style.display = 'block'; if (node) node.classList.add('sel');
      if (id) { try { location.hash = 'a-' + id; } catch (e) {} }
    }
    var ns = document.querySelectorAll('.node');
    for (var i = 0; i < ns.length; i++) (function (n) { n.addEventListener('click', function () { sel(n.dataset.id); }); })(ns[i]);
    document.addEventListener('click', function (ev) {
      var t = ev.target && ev.target.closest ? ev.target.closest('.fromlink') : null;
      if (t && t.dataset.id) { ev.preventDefault(); sel(t.dataset.id); window.scrollTo(0, 0); }
    });
    var want = (location.hash || '').replace(/^#a-/, '');
    sel(document.getElementById('log-' + want) ? want : ${JSON.stringify(s.firstId)});
    setTimeout(function () { location.reload(); }, 60000);
  })();
</script>
`);
console.log(`built ${outPath} — session ${sessionId.slice(0, 8)}, ${s.agents.length} agents, ${s.workingCount} working`);
