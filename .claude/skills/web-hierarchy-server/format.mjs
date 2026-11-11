// web-hierarchy-server formatter - the skill's transcript→document formatting
// script.
// Reads the session's subagent transcripts and returns a structured snapshot
// (spawn-tree geometry + per-agent event HTML). Shared by serve.mjs (live) and
// build.mjs (static snapshot). Log content is read + formatted HERE, on disk -
// it never passes through the root agent or its context window.
//
// Look: the Claude Code console, dark-colorblind ("dark-daltonized") theme.
// Palette extracted verbatim from the Claude Code 2.1.206 bundle's
// dark-daltonized theme object (colorblind: success/diff-added are BLUE,
// removals orange-red): text #ffffff, claude #ff9933, permission #99ccff,
// success #3399ff, error #ff6666, warning #ffcc00, inactive #999999,
// subtle #505050, diffAdded #004466, diffRemoved #660000,
// diffAddedDimmed #3e515b, diffRemovedDimmed #3e2c2c, diffAddedWord #0077b3,
// diffRemovedWord #b30000, userMessageBackground #373737,
// composerSidebarBackground #262626, selectionBg #264f78, page bg #000000.
import { readFileSync, readdirSync, statSync, existsSync, realpathSync } from 'node:fs';
import { join, extname, basename, dirname, resolve, isAbsolute } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { homedir } from 'node:os';
import { createHash } from 'node:crypto';

const HERE = dirname(fileURLToPath(import.meta.url));
const SKILL_NAME = 'web-hierarchy-server';

// --- configuration ---------------------------------------------------------
// NOTHING install-, machine- or person-specific is hardcoded in this file or in
// serve.mjs/build.mjs, which read their local values through cfg() below. It all
// lives in config.json in this skill's INSTALL CONTEXT, never beside this
// script; WEB_HIERARCHY_CONFIG points the same viewer at a different agent set,
// transcript root or identity roster with no code edit. config.example.json
// documents every key.
const REQUIRED = Symbol('required');
const die = (msg) => { console.error(msg); process.exit(2); };

/**
 * Which config.json this process reads: WEB_HIERARCHY_CONFIG when set, else the
 * file `fleet where web-hierarchy-server config.json` names, through the fleet's
 * one lookup (lib/fleet-where.mjs, loaded from this file's realpath; its header
 * says why). Any failure exits 2 naming the command and the variable that
 * bypasses it, before anything is served.
 */
const FLEET_WHERE = pathToFileURL(join(realpathSync(HERE), '..', '..', '..', 'lib', 'fleet-where.mjs')).href;
const { configFile } = await import(FLEET_WHERE)
  .catch((e) => die(`[web-hierarchy] config: cannot load ${FLEET_WHERE} (${e.code || e.message})`));
export const CONFIG_FILE = (() => {
  try { return configFile(SKILL_NAME, 'WEB_HIERARCHY_CONFIG'); }
  catch (e) { return die(`[web-hierarchy] config: ${e.message}`); }
})();

const loadConfig = (file) => {
  let raw;
  try { raw = readFileSync(file, 'utf8'); }
  catch (e) { return die(`[web-hierarchy] config: cannot read ${file} (${e.code || e.message}) - copy config.example.json there and fill it in`); }
  try { return JSON.parse(raw); }
  catch (e) { return die(`[web-hierarchy] config: ${file} is not valid JSON - ${e.message}`); }
};

const CONFIG = loadConfig(CONFIG_FILE);

/**
 * Read a dotted key out of CONFIG. A missing REQUIRED key exits loudly NAMING
 * the key instead of defaulting, because the required values here fail
 * SILENTLY when guessed: a guessed transcript root finds A session, renders it
 * completely, and it belongs to a different agent. The optional ones default
 * because a wrong guess there fails loudly by itself (a taken port is
 * EADDRINUSE, a bad bind host refuses to listen) or has nothing to guess (the
 * roster defaults to the one shipped beside this file).
 */
export function cfg(dotted, dflt = REQUIRED) {
  let node = CONFIG;
  for (const part of dotted.split('.')) {
    if (node === null || typeof node !== 'object' || !(part in node)) {
      if (dflt === REQUIRED) die(`[web-hierarchy] config: ${CONFIG_FILE} is missing required key '${dotted}'`);
      return dflt;
    }
    node = node[part];
  }
  return node;
}

// _comment keys are documentation (JSON has no comment syntax) and are dropped
// wherever a map is iterated rather than indexed.
const stripComments = (o) => Object.fromEntries(Object.entries(o || {}).filter(([k]) => k !== '_comment'));
const expandUser = (p) => (p === '~' ? homedir() : String(p).startsWith('~/') ? join(homedir(), String(p).slice(2)) : String(p));
// A path read out of config.json: a leading ~/ expands against the home
// directory, an absolute path is used as given, and a RELATIVE path resolves
// against the directory holding the config file - never against this script's
// directory and never against the cwd. The config file lives in the install, so
// a value written relative to it means the same file from every caller.
const configPath = (p) => { const v = expandUser(p); return isAbsolute(v) ? v : resolve(dirname(CONFIG_FILE), v); };

// Resolved EAGERLY, at startup: a config that cannot say where the transcripts
// are should fail before the page is served, not on the tick that first needs
// the value.
for (const key of ['transcripts.config_dir', 'labels.root_owner']) cfg(key);

// Honor CLAUDE_CONFIG_DIR: a session may run against a non-default config root,
// and picking the configured fallback silently serves a stale session from the
// other install rather than failing. The environment therefore WINS over
// `transcripts.config_dir`, which is only for a run with it unset.
const CONFIG_DIR = process.env.CLAUDE_CONFIG_DIR || configPath(cfg('transcripts.config_dir'));
// A session's transcript lands under the project slug of its CWD - which for
// a worktree session is the WORKTREE's slug, not the canonical checkout's
// (EnterWorktree mid-session even moves the live transcript there). One config
// dir = one agent, so every slug under projects/ is this agent's work: scan
// them all instead of pinning one, or worktree sessions are invisible.
export const PROJECTS = join(CONFIG_DIR, cfg('transcripts.projects_subdir', 'projects'));
const slugDirs = () => {
  try { return readdirSync(PROJECTS, { withFileTypes: true }).filter((d) => d.isDirectory()).map((d) => join(PROJECTS, d.name)); }
  catch { return []; }
};
// Which slug dir holds this session's transcript (null if none does).
export const sessionDir = (sid) => slugDirs().find((d) => existsSync(join(d, `${sid}.jsonl`))) || null;
const ACTIVE_MS = 3 * 60000;
export const BW = 190, BH = 80, HGAP = 26, VGAP = 46, PAD = 14;
// Task-description block geometry. The description WRAPS to as many lines as it
// needs and the block grows vertically to fit (nodes are variable-height - the
// tidy-tree row layout and edge anchors below follow each node's real height,
// never a uniform BH). DESC_CHARS ≈ the 190px box width at the 9.5px monospace
// nd font (~5.7px/char over the ~171px text column, x=11 inset + right pad) -
// it is by construction the SAME width the pre-wrap single line was truncated
// to, so a ≤30-char description still lands on one line and the block stays the
// old 80px tall. DESC_Y0 = first line's baseline (below the 36px avatar, which
// ends at y≈49); TIMES_GAP/BOTTOM_PAD space the time range and lower edge below
// the last wrapped line. DESC_MAX_LINES caps a degenerate hundreds-of-chars
// description (last kept line gets an ellipsis) so one runaway string can't
// stretch a block off the graph - normal one-line task descriptions never hit
// it.
const DESC_CHARS = 30, DESC_MAX_LINES = 6, DESC_LH = 12, DESC_Y0 = 58, TIMES_GAP = 15, BOTTOM_PAD = 7;
// The model badge is one extra muted line the block grows to fit, sitting
// between the description and the time range (below the header for a no-desc /
// root block). MODEL_LH is its gap below the last description line; a no-desc
// block anchors it just under the header at DESC_NODESC_ANCHOR. A node whose
// transcript yields no model renders NO line and keeps the classic geometry
// byte-for-byte - the model path is purely additive.
const MODEL_LH = 12, DESC_NODESC_ANCHOR = 40;

// Greedy word-wrap into ≤maxChars lines (SVG has no native text wrap). Breaks
// on whitespace; hard-splits any single word longer than a full line; caps at
// maxLines, appending '...' to the last kept line when it overflows. Empty text
// (the root block, which shows the fleet identity instead) → [] → no desc rows.
function wrapDesc(text, maxChars = DESC_CHARS, maxLines = DESC_MAX_LINES) {
  const words = String(text || '').split(/\s+/).filter(Boolean);
  const lines = [];
  let cur = '';
  const flush = () => { if (cur) { lines.push(cur); cur = ''; } };
  for (const w of words) {
    let word = w;
    while (word.length > maxChars) { flush(); lines.push(word.slice(0, maxChars)); word = word.slice(maxChars); }
    if (!cur) cur = word;
    else if (cur.length + 1 + word.length <= maxChars) cur += ' ' + word;
    else { flush(); cur = word; }
  }
  flush();
  if (lines.length > maxLines) {
    lines.length = maxLines;
    const last = lines[maxLines - 1];
    lines[maxLines - 1] = (last.length > maxChars - 1 ? last.slice(0, maxChars - 1) : last).replace(/\s+$/, '') + '…';
  }
  return lines;
}

// Which fleet member THIS server serves - derived from the CLAUDE_CONFIG_DIR
// the service unit (or the launch environment) already pins, one config dir per
// agent, so the root block can name itself with no extra CLI flag or env var to
// set (and none to forget - the fewest failure modes). Empty for an unmapped
// root, which then renders as the plain root block.
// The map is local values (which agent owns which config dir), so it lives in
// config.json under `fleet.by_config_dir`.
//
// THE KEY IS NOT SIMPLY THE BASENAME, and that is the whole point of fleetKey().
// A fleet whose agents each own a home directory puts every one of their config
// dirs at <home>/<agent>/.claude, so the BASENAME is the literal string
// `.claude` for ALL of them: keyed by basename, every agent in such a fleet
// collides on one entry and every root block is labelled with whichever agent
// that entry names. The failure is silent - the page renders completely, and it
// says the wrong agent's name, which is worse than no label at all, because a
// viewer with two pages open cannot tell them apart and does not know they
// cannot. So when the basename is `.claude` the key is the PARENT directory's
// basename (`.../ada/.claude` -> `ada`), which is what actually
// distinguishes them; any other basename (`.claude-2`, `.claude-slack`) is
// already distinguishing and is used as-is.
//
// The literal basename is tried SECOND, as a fallback, so a map written the old
// way (an entry keyed `.claude`) still labels instead of silently dropping the
// label. Both spellings are documented in config.example.json; prefer the
// derived key, because it is the one that can distinguish two agents.
const FLEET_BY_CONFIG = stripComments(cfg('fleet.by_config_dir', {}));
export const fleetKey = (dir) => {
  const b = basename(String(dir));
  return b === '.claude' ? basename(dirname(String(dir))) : b;
};
export const fleetName = () => FLEET_BY_CONFIG[fleetKey(CONFIG_DIR)] || FLEET_BY_CONFIG[basename(CONFIG_DIR)] || '';

// How the human at the top of the tree is named in a from/to header
// (`labels.root_owner`). Display only, and it grants nothing.
export const ROOT_OWNER_LABEL = String(cfg('labels.root_owner'));

// This machine's servers (`servers` in config.json): unit -> {config_dir,
// port}. serve.mjs takes its DEFAULT port from the entry whose config_dir
// resolves to the SAME fleet key as the running CLAUDE_CONFIG_DIR, so a hand
// run under one agent's config dir cannot default onto another agent's port and
// collide with a live server; the units pass --port explicitly and are
// unaffected either way.
//
// It matches on fleetKey(), NOT on the raw basename, for exactly the reason
// fleetKey() exists: in a fleet of <home>/<agent>/.claude config dirs every
// entry's basename is `.claude`, so a basename match picks the FIRST entry for
// every agent - which is the collision this default exists to prevent, arriving
// as a silent EADDRINUSE against a sibling's live server.
export const servers = () => stripComments(cfg('servers', {}));
export const defaultPort = () => {
  const entries = Object.values(servers());
  const mine = entries.find((d) => fleetKey(expandUser(d.config_dir || '')) === fleetKey(CONFIG_DIR));
  return Number((mine || entries[0] || {}).port) || 8090;
};

// ------------------------------------------------------------ identity ----
// Names + avatars are a DISPLAY LABEL, not state: assigned here, stored
// nowhere, and unknown to the agents themselves (the harness owns subagents/
// and writes agent-<id>.meta.json; this formatter is a read-only observer of
// it). Assignment is a pure function of (agentType, spawn order) recomputed
// from the transcripts on every refresh - so it is deterministic, identical
// across server restarts and across machines, and needs no store, lifecycle
// or reset story. NOT a hash of agentId: with 4 names and 4 software-engineers
// a hash collides by pigeonhole, spawn order cannot.
// The roster is a config key (`identities.file`), not a hardcoded filename, so
// an install can repoint it without editing this script. Absent or null means
// the identities.json shipped beside this file; a relative path resolves
// against the config file's directory, like every other config path; and a
// portrait or avatar path inside a roster resolves against the ROSTER's own
// directory, so an install's roster carries its own art. A roster that will
// not load is NOT fatal here: every block simply
// renders with no name and no avatar, which reads as a design choice rather
// than a fault, and taking the whole live view down for a cosmetic file is the
// worse trade. It is logged to stderr (journalctl for a service run) and it is
// one of installation/check's artifact tests, because that silence is the only
// thing standing between a missing roster and nobody noticing for weeks.
export const identitiesPath = (() => {
  const p = cfg('identities.file', null);
  return p ? configPath(p) : join(HERE, 'identities.json');
})();
const ROSTER_DIR = dirname(identitiesPath);
const POOLS = (() => {
  try {
    const j = JSON.parse(readFileSync(identitiesPath, 'utf8'));
    delete j._doc;
    return j;
  } catch (e) {
    console.error(`[web-hierarchy] identities: ${identitiesPath} not loaded (${e.code || e.message}) - graph renders with no names or avatars`);
    return {};
  }
})();
const SUP = ['', '', '²', '³', '⁴', '⁵', '⁶', '⁷', '⁸', '⁹'];

// agents: [{id, meta, startTs}] -> Map(id -> {name, avatarPath}). Types with no
// pool get no identity and render with no name and no avatar (incl. the synthetic
// root, which is the human operator's session, not an agent).
export function assignIdentities(list) {
  const out = new Map();
  const byType = new Map();
  for (const a of list) {
    const t = a.meta?.agentType;
    if (!t || !POOLS[t]) continue;
    if (!byType.has(t)) byType.set(t, []);
    byType.get(t).push(a);
  }
  for (const [t, arr] of byType) {
    const role = POOLS[t];
    const names = role.names || [];
    if (!names.length) continue;
    arr.sort((x, y) => (x.startTs || 0) - (y.startTs || 0) || String(x.id).localeCompare(String(y.id)));
    arr.forEach((a, i) => {
      const name = names[i % names.length];
      // 30 names per role, so the suffix is a backstop for the absurd case (a
      // 31st concurrent agent of one role), not an expected state.
      const cycle = Math.floor(i / names.length);
      const art = role.portraits?.[name] || role.avatar || null;
      out.set(a.id, {
        name: name + (SUP[Math.min(cycle + 1, SUP.length - 1)] || ''),
        avatarPath: art ? resolve(ROSTER_DIR, art) : null,
      });
    });
  }
  return out;
}

export const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
export const hhmmss = (ts) => (ts ? new Date(ts).toISOString().slice(11, 19) : '—');
export const ago = (ms) => { const m = Math.round(ms / 60000); return m < 1 ? 'just now' : m < 60 ? `${m}m ago` : `${Math.floor(m / 60)}h ${m % 60}m ago`; };

const subagentsDir = (sid, base = sessionDir(sid)) => (base ? join(base, sid, 'subagents') : null);

export function pickSession(explicit) {
  if (explicit) return explicit;
  // Newest ACTIVITY wins, root transcript included: a freshly started session
  // that hasn't delegated yet still has a root .jsonl, and must win over an
  // older session whose subagents stopped writing (dead processes keep their
  // mtimes forever). Only one live claude exists per config dir, so the live
  // session's root file always out-dates every finished one - the old
  // subagents-only scan instead pinned the view to the LAST session that
  // delegated, hiding the current one until its first spawn.
  let sid = null, bestMt = 0;
  for (const dir of slugDirs()) {
    for (const f of readdirSync(dir)) {
      if (!f.endsWith('.jsonl')) continue;
      const id = f.slice(0, -'.jsonl'.length);
      let mt = statSync(join(dir, f)).mtimeMs;
      const sub = join(dir, id, 'subagents');
      let subs = []; try { subs = readdirSync(sub).filter((x) => x.endsWith('.jsonl')); } catch {}
      for (const x of subs) { const m = statSync(join(sub, x)).mtimeMs; if (m > mt) mt = m; }
      if (mt > bestMt) { bestMt = mt; sid = id; }
    }
  }
  return sid;
}

// ---------------------------------------------------------------- images ----
// EVERYTHING renders as base64 data URIs - the page must stay one standalone
// HTML document (no served-by-reference assets), so a saved copy or a dead
// server still shows every image. ~2MB cap per image, placeholder note beyond.
//
// Dedup happens at the STORAGE level, not the display level: each unique
// image's data URI is embedded ONCE per document in a contentHash→dataURI
// store (the same file - design diagrams get referenced in dozens of messages
// - would otherwise multiply the payload by the reference count). EVERY
// occurrence, first or repeat, renders as an <img data-img="<hash>"> thumbnail
// whose src the client fills from the store (imgRuntimeJs below); clicking
// opens the full image in a new tab via Blob URL (browsers block top-level
// data: navigation).
const IMG_EXT = { '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif', '.webp': 'image/webp' };
export const imageMime = (p) => IMG_EXT[extname(String(p)).toLowerCase()] || null;
const DATA_CAP = 2 * 1024 * 1024; // ~2MB per image

// TWO STORES, SAME KEYS, OPPOSITE REQUIREMENTS - and the split is what keeps
// the page openable at hundreds of agents.
//
// `snapImgs` is what the CURRENT render referenced. It is handed out as data
// URIs and baked into a document, because a BAKED part must render with no
// server: save the page, or let the server die, and it still shows its images.
//
// `imgStore` is the same hash → data URI mapping kept ACROSS renders, and it is
// what `GET /img/<hash>` serves as bytes. Everything the page fetches AFTER the
// initial document - a log the viewer selected, an avatar for an agent type
// that appeared since - renders as `<img data-img>` carrying no data at all and
// resolves against that route. That is the whole economy: inlining every image
// into every snapshot made `GET /` 358MB on a 228-agent session (110MB of it
// base64 image data, re-sent on every 10s poll), which no browser opens
// usefully. By hash the browser caches each image permanently - the URL IS a
// content hash, so it can never go stale - and a poll ships none of them.
//
// DO NOT "simplify" this back to one store by letting a snapshot hand out data
// URIs again. Nothing goes red if you do: every image still renders, every test
// about trees and logs still passes, and the page silently returns to being
// hundreds of megabytes. The document SIZE is the property under protection,
// and the thing that can see it regress is the byte-budget leg in
// serve.test.mjs - keep that leg.
let snapImgs = new Map();
function resetImgStore() { snapImgs = new Map(); }
// Bounded, oldest-out. An operator walking agent after agent would otherwise
// accumulate every image in the session in RSS, and this process is long-lived
// by design (it outlives the sessions it renders). An evicted hash 404s and its
// thumbnail stays blank until that log is rendered again, which re-inserts it -
// so the cap trades a rare blank thumbnail for a bound, and it sits far above
// the number of images any one agent's log can reference.
const imgStore = new Map();
const IMG_STORE_MAX = 1200;
const hashOf = (s) => createHash('sha1').update(s).digest('hex').slice(0, 16);
function remember(h, uri) {
  if (!snapImgs.has(h)) snapImgs.set(h, uri);
  if (imgStore.has(h)) imgStore.delete(h); // re-insert so it counts as recently used
  imgStore.set(h, uri);
  while (imgStore.size > IMG_STORE_MAX) imgStore.delete(imgStore.keys().next().value);
}
// hash → bytes, for the by-hash image route. NULL for an unknown hash, and a
// caller must render that as a 404 and never as an empty 200: the URL is a
// content hash, so a browser caches the answer for ever - an empty 200 would be
// a permanently broken image for that viewer.
export function imgBytes(hash) {
  const uri = imgStore.get(String(hash));
  if (!uri) return null;
  const m = /^data:([^;,]+);base64,([\s\S]*)$/.exec(uri);
  if (!m) return null;
  return { mime: m[1], buf: Buffer.from(m[2], 'base64') };
}
function imgRefTag(hash, alt) { return `<img class="inline-img" data-img="${esc(hash)}" alt="${esc(alt)}" title="${esc(alt)} — click to open full size" loading="lazy">`; }
function imgRef(dataURI, alt) {
  const h = hashOf(dataURI);
  remember(h, dataURI);
  return imgRefTag(h, alt);
}

// path → {hash, dataURI}, cached by path+mtime+size so the 10s poll doesn't
// re-encode unchanged files forever.
const fileCache = new Map();
const cacheGet = (key, make) => {
  if (fileCache.has(key)) return fileCache.get(key);
  if (fileCache.size > 300) fileCache.clear();
  const v = make(); fileCache.set(key, v); return v;
};
function inlineImageFile(p, mime, st) {
  if (st.size > DATA_CAP) return `<div class="dim">[image ${esc(basename(p))} — &gt;2MB, not inlined]</div>`;
  const { h, uri } = cacheGet(`img:${p}:${st.mtimeMs}:${st.size}`, () => {
    const uri = `data:${mime};base64,${readFileSync(p).toString('base64')}`;
    return { h: hashOf(uri), uri };
  });
  remember(h, uri);
  return imgRefTag(h, basename(p));
}

// Avatar → hash into the same dedup store, WITHOUT the click-to-open <img>
// wrapper inlineImageFile builds: node avatars live inside the SVG graph and
// are referenced by hash from an <image data-img>. One embed per unique file
// however many agents wear it.
function avatarRef(p) {
  if (!p) return null;
  const mime = imageMime(p); if (!mime) return null;
  let st; try { st = statSync(p); } catch { return null; }
  if (st.size > DATA_CAP) return null;
  const { h, uri } = cacheGet(`img:${p}:${st.mtimeMs}:${st.size}`, () => {
    const uri = `data:${mime};base64,${readFileSync(p).toString('base64')}`;
    return { h: hashOf(uri), uri };
  });
  remember(h, uri);
  return h;
}

// Client runtime for the image store (shared by serve.mjs and build.mjs; must
// run in the same scope as a `var IMGS = {...}` hash→dataURI object): fills
// <img data-img> srcs, and on click opens the FULL image in a new tab.
//
// TWO SOURCES, IN THIS ORDER, and the order is the standalone-document
// guarantee. IMGS first: an image BAKED into the document renders with no
// server, which is what makes a saved page and a build.mjs snapshot work at
// all. `img/<hash>` second: an image that arrived with a lazily-fetched log
// carries no data, and the server serves it by content hash. A page with no
// server behind it therefore renders exactly the images it was saved with and
// shows the rest as broken thumbnails - the documented cost of not shipping
// hundreds of megabytes to every viewer.
//
// The relative URL is deliberate: the page may be served through a port
// forward, a tunnel or a reverse proxy under a path prefix, and an absolute
// `/img/...` would leave the prefix behind. It matches the `fetch('state')`
// and `fetch('agent/...')` calls in serve.mjs for the same reason.
export const imgRuntimeJs = `
  function imgSrc(h) { return IMGS[h] || ('img/' + h); }
  function hydrateImgs() {
    var list = document.querySelectorAll('img[data-img]');
    for (var i = 0; i < list.length; i++) {
      var el = list[i], u = imgSrc(el.getAttribute('data-img'));
      if (u && el.getAttribute('src') !== u) el.setAttribute('src', u);
    }
    // SVG node avatars: <image> is NOT <img> — a different element that takes
    // href, not src. The graph is re-rendered wholesale on every refresh, so
    // this re-runs against fresh elements each time (hydrateImgs is called
    // right after applyGraph).
    var svgs = document.querySelectorAll('image[data-img]');
    for (var k = 0; k < svgs.length; k++) {
      var s = svgs[k], v = imgSrc(s.getAttribute('data-img'));
      if (v && s.getAttribute('href') !== v) s.setAttribute('href', v);
    }
  }
  document.addEventListener('click', function (ev) {
    var t = ev.target; if (!t || t.tagName !== 'IMG' || !t.hasAttribute('data-img')) return;
    var h = t.getAttribute('data-img'), uri = IMGS[h];
    // Not baked in: the by-hash route serves real bytes with a real
    // content-type, so a plain navigation works and no Blob is needed.
    if (!uri) { ev.preventDefault(); window.open('img/' + h, '_blank'); return; }
    var m = uri.match(/^data:([^;,]+);base64,(.*)$/); if (!m) return;
    var bin = atob(m[2]), arr = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
    var u = URL.createObjectURL(new Blob([arr], { type: m[1] }));
    window.open(u, '_blank');
    setTimeout(function () { URL.revokeObjectURL(u); }, 60000);
  });`;
// JSON inside a <script> must not terminate the tag early
export const jsonForScript = (o) => JSON.stringify(o).replace(/</g, '\\u003c');

// SendUserFile path → file chip + inline <img> for images
function renderSentFile(p) {
  const mime = imageMime(p);
  const chip = `<span class="filechip">↗ ${esc(p)}</span>`;
  if (!mime) return `<div class="sentfile">${chip}</div>`;
  try { return `<div class="sentfile">${chip}<br>${inlineImageFile(p, mime, statSync(p))}</div>`; }
  catch { return `<div class="sentfile">${chip} <span class="dim">(file no longer on disk)</span></div>`; }
}

function renderResultImages(images) {
  if (!images || !images.length) return '';
  return images.map((im) => im.data.length > DATA_CAP * 1.4
    ? '<div class="dim">[image &gt;2MB — not inlined]</div>'
    : imgRef(`data:${im.mt};base64,${im.data}`, 'tool result image')).join('');
}

// ------------------------------------------------------ handover packages ----
// When a message references handover artifacts by path (canonical case: a
// design package directory holding design.md, plan.md, diagram.svg/png,
// review.html), render a distinct foldable "📦 package" block at that point:
// every file collapsed by default; .md unfolds to its text, images unfold
// inline (data URIs), .html unfolds to an inert escaped-source view (never
// embedded live).
// Root for RELATIVE artifact paths only (`packages.repo_root`); an absolute
// path in a message is used as-is. Omitted or null means the server's own
// working directory, which is what a service unit sets anyway.
const REPO = cfg('packages.repo_root', null) ? configPath(cfg('packages.repo_root')) : process.cwd();
const PKG_RE = /\/?[\w.\-]+(?:\/[\w.\-]+)+\.(?:md|svg|png|jpe?g|webp|gif|html)\b/gi;
// Packages are usually referenced as a DIRECTORY ("the package at
// <dir>/<slug>/ (design.md, plan.md, ...)") - match the dir and expand to its
// artifact files. Where an install keeps its packages is its own convention,
// so the shape is the config key `packages.dir_pattern`: a repo-relative path
// with ONE `<slug>` segment (`docs/design/<slug>`). Every other character
// matches literally; `<slug>` matches one path segment; a mention may carry any
// leading directories (an absolute path, or a worktree's). Absent or null
// means no install convention: directory mentions render as plain text and
// file paths are still detected by PKG_RE above.
export const pkgDirRegExp = (pattern) => {
  if (!pattern) return null;
  const parts = String(pattern).replace(/^\/+|\/+$/g, '').split('<slug>');
  if (parts.length !== 2) die(`[web-hierarchy] config: packages.dir_pattern must contain exactly one <slug>, got ${JSON.stringify(pattern)}`);
  const lit = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return new RegExp(`(?:\\/[\\w.\\-]+)*\\/?${lit(parts[0])}[\\w.\\-]+${lit(parts[1])}`, 'g');
};
const PKG_DIR_RE = pkgDirRegExp(cfg('packages.dir_pattern', null));
const PKG_EXT_RE = /\.(?:md|svg|png|jpe?g|webp|gif|html)$/i;
const PKG_MAX = 12;

export function detectPackagePaths(text) {
  if (!text || text.length > 512 * 1024) return [];
  const s = String(text);
  const seen = new Set();
  const add = (p) => { if (seen.size < PKG_MAX && !seen.has(p) && existsSync(p)) { try { if (statSync(p).isFile()) seen.add(p); } catch {} } };
  for (const m of (PKG_DIR_RE && s.match(PKG_DIR_RE)) || []) {
    const d = m.startsWith('/') ? m : join(REPO, m);
    let st; try { st = statSync(d); } catch { continue; }
    if (!st.isDirectory()) continue;
    for (const f of readdirSync(d).sort()) if (PKG_EXT_RE.test(f)) add(join(d, f));
  }
  for (const m of s.match(PKG_RE) || []) add(m.startsWith('/') ? m : join(REPO, m));
  return [...seen];
}

function fmtSize(n) { return n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`; }

function packageItemBody(p, st) {
  const ext = extname(p).toLowerCase();
  if (ext === '.md') return cacheGet(`md:${p}:${st.mtimeMs}:${st.size}`, () => {
    const { body, note } = capBody(readFileSync(p, 'utf8'), 64 * 1024);
    return `<div class="pkgbody">${clamp(body + note, 40)}</div>`;
  });
  const mime = ext === '.svg' ? 'image/svg+xml' : imageMime(p);
  if (mime) return `<div class="pkgbody">${inlineImageFile(p, mime, st)}</div>`;
  if (ext === '.html') return cacheGet(`html:${p}:${st.mtimeMs}:${st.size}`, () => {
    const { body, note } = capBody(readFileSync(p, 'utf8'), 8 * 1024);
    return `<div class="pkgbody"><span class="filechip">${esc(p)}</span> <span class="dim">(${fmtSize(st.size)} — escaped source, not rendered)</span>${clamp(body + note, 15)}</div>`;
  });
  return '';
}

function renderPackageBlock(text) {
  const paths = detectPackagePaths(text);
  if (!paths.length) return '';
  const items = paths.map((p) => {
    let st; try { st = statSync(p); } catch { return ''; }
    const body = packageItemBody(p, st);
    if (!body) return '';
    return `<details class="pkgitem"><summary><span class="pkgname">${esc(basename(p))}</span> <span class="dim">· ${fmtSize(st.size)} · ${esc(p)}</span></summary>${body}</details>`;
  }).filter(Boolean).join('');
  if (!items) return '';
  return `<div class="ev pkg"><div class="pkghead">📦 package · ${paths.length} file${paths.length === 1 ? '' : 's'}</div>${items}</div>`;
}

// ------------------------------------------------------------ collapsing ----
// Console-style clamp: first `max` lines visible, rest behind "... +N lines".
function clamp(text, max) {
  const lines = String(text).split('\n');
  if (lines.length <= max + 1) return `<pre>${esc(text)}</pre>`;
  return `<pre>${esc(lines.slice(0, max).join('\n'))}</pre><details class="more"><summary>… +${lines.length - max} lines</summary><pre>${esc(lines.slice(max).join('\n'))}</pre></details>`;
}

function capBody(s, CAP) {
  return s.length <= CAP ? { body: s, note: '' } : { body: s.slice(0, CAP), note: `\n… [${Math.round((s.length - CAP) / 1024)} KB more truncated]` };
}

// ------------------------------------------------------------------ diffs ----
// Claude Code Edit display: file-path header line, then context / removed /
// added rows with a line-number gutter. Common prefix/suffix of old vs new
// render as context; the middle as a removed block then an added block -
// exactly the console's old-block/new-block rendering.
const DIFF_CTX = 3, DIFF_BLOCK_CAP = 40;

function diffRows(oldStr, newStr) {
  const o = oldStr === '' ? [] : oldStr.split('\n');
  const n = newStr === '' ? [] : newStr.split('\n');
  let p = 0; while (p < o.length && p < n.length && o[p] === n[p]) p++;
  let s = 0; while (s < o.length - p && s < n.length - p && o[o.length - 1 - s] === n[n.length - 1 - s]) s++;
  const rows = [];
  for (let i = Math.max(0, p - DIFF_CTX); i < p; i++) rows.push({ t: 'ctx', ln: i + 1, txt: o[i] });
  for (let i = p; i < o.length - s; i++) rows.push({ t: 'del', ln: i + 1, txt: o[i] });
  for (let i = p; i < n.length - s; i++) rows.push({ t: 'add', ln: i + 1, txt: n[i] });
  for (let i = 0; i < Math.min(DIFF_CTX, s); i++) rows.push({ t: 'ctx', ln: n.length - s + i + 1, txt: o[o.length - s + i] });
  return { rows, adds: Math.max(0, n.length - s - p), dels: Math.max(0, o.length - s - p) };
}

function renderDiffRows(rows) {
  const w = Math.max(2, ...rows.map((r) => String(r.ln).length));
  const row = (r) => `<div class="dl ${r.t}"><span class="ln">${String(r.ln).padStart(w)} ${r.t === 'add' ? '+' : r.t === 'del' ? '-' : ' '}</span><span class="dc">${esc(r.txt)}</span></div>`;
  if (rows.length <= DIFF_BLOCK_CAP + 5) return rows.map(row).join('');
  return rows.slice(0, DIFF_BLOCK_CAP).map(row).join('')
    + `<details class="dmore"><summary>… +${rows.length - DIFF_BLOCK_CAP} lines</summary>${rows.slice(DIFF_BLOCK_CAP).map(row).join('')}</details>`;
}

// Edit / Write / NotebookEdit tool_use body → Claude-style diff.
function renderFileChange(name, input) {
  const i = input || {};
  let path, oldS, newS, verb;
  if (name === 'Edit') { path = i.file_path; oldS = String(i.old_string ?? ''); newS = String(i.new_string ?? ''); verb = 'Updated'; }
  else if (name === 'Write') { path = i.file_path; oldS = ''; newS = String(i.content ?? ''); verb = 'Wrote'; }
  else { path = i.notebook_path; oldS = ''; newS = String(i.new_source ?? ''); verb = 'Updated cell in'; }
  if (!path) return null;
  const { rows, adds, dels } = diffRows(oldS, newS);
  const head = name === 'Write'
    ? `${verb} ${adds} line${adds === 1 ? '' : 's'} to <b>${esc(path)}</b>`
    : `${verb} <b>${esc(path)}</b> with ${adds} addition${adds === 1 ? '' : 's'} and ${dels} removal${dels === 1 ? '' : 's'}${i.replace_all ? ' <span class="dim">(replace_all)</span>' : ''}`;
  return `<div class="ev result"><span class="mark"></span><div class="rbody"><div class="dhead">${head}</div><div class="diff">${renderDiffRows(rows)}</div></div></div>`;
}

// --------------------------------------------------------- tool summaries ----
function argSummary(name, input) {
  if (input == null || typeof input !== 'object') return '';
  let s;
  if (name === 'Agent' || name === 'Task') s = [input.subagent_type, input.description].filter(Boolean).join(': ');
  else if (name === 'Bash') s = input.command;
  else if (name === 'SendUserFile') s = (Array.isArray(input.files) ? input.files : input.files ? [input.files] : []).map((f) => basename(String(f))).join(', ');
  else s = input.file_path ?? input.notebook_path ?? input.path ?? input.pattern ?? input.url ?? input.query ?? input.command ?? input.skill ?? input.description ?? input.prompt ?? input.message ?? input.caption;
  if (typeof s !== 'string' || !s) s = JSON.stringify(input);
  s = s.replace(/\s+/g, ' ').trim();
  return s.length > 100 ? s.slice(0, 99) + '…' : s;
}

// ------------------------------------------------------------ event HTML ----
// The ⎿ result body - shared by standalone tool_result events and results
// paired into their tool_use's block.
// NOTE: every leading marker glyph (⏺ .bull, ✻ .tg, > .gt, ⎿ .mark) is emitted
// as an EMPTY span whose glyph comes from a ::before pseudo-element (see css())
// - that's what lets the alive-agent last-line animation cycle the glyph's
// `content` frames without touching the markup.
function renderResultBody(ev, CAP) {
  const { body, note } = capBody(ev.text || '', CAP);
  const imgs = renderResultImages(ev.images);
  const txt = (body + note).trim();
  return `<div class="ev result${ev.error ? ' err' : ''}"><span class="mark"></span><div class="rbody">${txt ? clamp(txt, 5) : imgs ? '' : '<span class="dim">(no output)</span>'}${imgs}</div></div>`;
}

// One-line-collapsed Bash / Read / Write unit: tool_use + its result in ONE
// details block. Collapsed = a single nowrap line (tool name + content
// preview, CSS text-overflow ellipsis in gray); click = the full content and
// the execution result; click again = back to the one-liner.
function renderUnit(ev, CAP) {
  const i = ev.input || {};
  let preview, expanded = '';
  if (ev.name === 'Bash') {
    preview = String(i.command ?? '').replace(/\s+/g, ' ').trim();
    expanded = `<pre class="fullcmd">${esc(String(i.command ?? ''))}</pre>`;
  } else if (ev.name === 'Read') {
    preview = String(i.file_path ?? '');
    expanded = `<div class="dim">${esc(String(i.file_path ?? ''))}</div>`;
  } else { // Write
    const first = String(i.content ?? '').split('\n', 1)[0];
    preview = `${i.file_path ?? ''} — ${first}`;
    expanded = renderFileChange('Write', ev.input) || '';
  }
  const res = ev.result ? renderResultBody(ev.result, CAP) : '<div class="ev result"><span class="mark"></span><div class="rbody"><span class="dim">(no result yet)</span></div></div>';
  const err = ev.result?.error ? ' err' : '';
  return `<details class="ev unit${err}"><summary><span class="bull ok"></span><span class="oneline"><span class="tname">${esc(ev.name)}</span> <span class="prev">${esc(preview)}</span></span></summary><div class="unitbody">${expanded}${res}</div></details>`;
}

function renderEvent(ev, childType, CAP, hdr) {
  switch (ev.kind) {
    case 'task':
    case 'user': {
      const { body, note } = capBody(ev.text, CAP * 4);
      const head = `<div class="msghead">from: ${hdr.fromHtml} · to: ${hdr.toHtml} · ${hhmmss(ev.ts)}</div>`;
      return `<div class="ev msg">${head}<div class="prompt"><span class="gt"></span><div class="pbody">${clamp(body + note, 10)}</div></div></div>${renderPackageBlock(ev.text)}`;
    }
    case 'thinking': return ev.text
      ? `<div class="ev thinking"><div class="tmark"><span class="tg"></span> Thinking…</div><pre>${esc(ev.text)}</pre></div>`
      : `<div class="ev thinking empty"><span class="tmark"><span class="tg"></span> Thinking…</span> <span class="enc">(encrypted — not persisted as text)</span></div>`;
    case 'text': return `<div class="ev text"><span class="bull claude"></span><div class="tbody"><pre>${esc(ev.text)}</pre></div></div>${renderPackageBlock(ev.text)}`;
    case 'tool_use': {
      if (ev.name === 'Bash' || ev.name === 'Read' || ev.name === 'Write') return renderUnit(ev, CAP);
      const spawn = childType ? `<span class="spawn"> · spawned <b>${esc(childType)}</b> — select it in the graph ↑</span>` : '';
      const line = `<div class="tline"><span class="bull ok"></span><span class="tname">${esc(ev.name)}</span><span class="targs">(${esc(argSummary(ev.name, ev.input))})</span>${spawn}</div>`;
      let body = '';
      if (ev.name === 'Edit' || ev.name === 'NotebookEdit') body = renderFileChange(ev.name, ev.input) || '';
      else if (ev.name === 'SendUserFile' && Array.isArray(ev.input?.files)) {
        body = `<div class="ev result"><span class="mark"></span><div class="rbody">${ev.input.caption ? `<div class="dim">${esc(String(ev.input.caption))}</div>` : ''}${ev.input.files.map((f) => renderSentFile(typeof f === 'string' ? f : f?.path || String(f))).join('')}</div></div>`;
      } else if (ev.input != null && Object.keys(ev.input).length) {
        const json = JSON.stringify(ev.input, null, 2);
        if (json.length > 120 || json.includes('\n')) body = `<details class="jin"><summary>input · ${Object.keys(ev.input).length} field${Object.keys(ev.input).length === 1 ? '' : 's'}</summary><pre>${esc(json)}</pre></details>`;
      }
      // paired result (Edit/NotebookEdit) renders inside the same block
      const pairedRes = ev.result ? renderResultBody(ev.result, CAP) : '';
      // SendMessage relays hand artifacts across agents - surface their packages too
      const pkg = ev.name === 'SendMessage' ? renderPackageBlock([ev.input?.message, ev.input?.summary].filter(Boolean).join('\n')) : '';
      return `<div class="ev tool">${line}${body}${pairedRes}</div>${pkg}`;
    }
    case 'tool_result': return renderResultBody(ev, CAP);
    default: return '';
  }
}

// -------------------------------------------------------------- snapshot ----
// THE TREE AND THE LOGS ARE SEPARATE COSTS, and that split is the shape of
// everything below. A session's TREE costs about a kilobyte per agent whatever
// that agent did; its LOGS are unbounded, and rendering one drags its images in
// with it. A snapshot that always carried every agent's log made `GET /` 358MB
// on a 228-agent session - a document no browser opens usefully, and re-sent on
// every 10s poll.
//
// So there are two entry points and they cost differently:
//
//   snapshot(sid, { logsFor })  the whole tree, plus the logs of the agents
//                               named in `logsFor` and NOBODY else.
//   agentLog(sid, id, { since }) ONE agent's log, parsing one transcript, with
//                               `since` so a poll ships only what is new.
//
// `logsFor: null` still means every log - that is what build.mjs's static bake
// needs, because a frozen keepsake has no server to fetch anything from.
//
// Images: a rendered log's images go into the durable store and render as
// `<img data-img>` with no data (see the image section above). Only what the
// CALLER bakes into a document is handed out as data URIs.

const ROOT_ID = 'root';
// The synthetic root node's meta. Module-level because BOTH entry points need
// it: the tree draws the root block from it, and a subagent's log labels its
// `from:` header with it. Two copies would drift, and the drift would read as a
// log header naming a different spawner than the arrow in the graph above it.
const ROOT_META = { agentType: 'claude (root session)', description: 'main session — top instance', spawnDepth: 0 };

// One transcript file → parsed events + time bounds. Same event model for
// subagent files and the root session transcript; lines that don't fit
// (attachments, summaries, non-user/assistant roles) are skipped.
function parseTranscript(p) {
  const events = []; let model = '', startTs = null, endTs = null, ts = null;
  for (const line of readFileSync(p, 'utf8').split('\n')) {
    if (!line.trim()) continue;
    let e; try { e = JSON.parse(line); } catch { continue; }
    if (e.timestamp) { const t = Date.parse(e.timestamp); ts = t; if (!startTs || t < startTs) startTs = t; if (!endTs || t > endTs) endTs = t; }
    const msg = e.message; if (!msg || e.type === 'attachment') continue;
    if (msg.role === 'user') {
      const c = msg.content;
      if (typeof c === 'string') events.push({ kind: events.some((v) => v.kind === 'task') ? 'user' : 'task', text: c, ts });
      else if (Array.isArray(c)) for (const it of c) {
        if (it.type === 'tool_result') {
          const images = [];
          const body = typeof it.content === 'string' ? it.content
            : Array.isArray(it.content) ? it.content.map((x) => {
                if (x.type === 'text') return x.text;
                if (x.type === 'image') {
                  const src = x.source?.data ? { mt: x.source.media_type || 'image/png', data: x.source.data }
                    : x.file?.base64 ? { mt: x.file.mediaType || x.file.media_type || 'image/png', data: x.file.base64 } : null;
                  if (src) { images.push(src); return ''; }
                  return '[image]';
                }
                return `[${x.type}]`;
              }).filter(Boolean).join('\n') : JSON.stringify(it.content);
          events.push({ kind: 'tool_result', id: it.tool_use_id, text: body, error: !!it.is_error, images, ts });
        } else if (it.type === 'text') events.push({ kind: 'user', text: it.text, ts });
      }
    } else if (msg.role === 'assistant') {
      model ||= msg.model || '';
      for (const it of msg.content || []) {
        if (it.type === 'thinking') events.push({ kind: 'thinking', text: (it.thinking || '').trim(), ts });
        else if (it.type === 'text' && it.text?.trim()) events.push({ kind: 'text', text: it.text, ts });
        else if (it.type === 'tool_use') events.push({ kind: 'tool_use', id: it.id, name: it.name, input: it.input, ts });
      }
    }
  }
  // Pair Bash/Read/Write/Edit/NotebookEdit tool_uses with their tool_result
  // (by tool_use_id) into one block; the consumed results leave the stream.
  const PAIR = new Set(['Bash', 'Read', 'Write', 'Edit', 'NotebookEdit']);
  const resIdx = new Map();
  events.forEach((ev, idx) => { if (ev.kind === 'tool_result' && ev.id) resIdx.set(ev.id, idx); });
  const consumed = new Set();
  for (const ev of events) {
    if (ev.kind === 'tool_use' && PAIR.has(ev.name) && resIdx.has(ev.id)) {
      ev.result = events[resIdx.get(ev.id)];
      consumed.add(resIdx.get(ev.id));
    }
  }
  return { events: events.filter((_, idx) => !consumed.has(idx)), model: model.replace(/^claude-/, ''), startTs, endTs };
}

// The session's subagent metas, id → meta. One small JSON per agent, and it is
// the cheap half of a session: `agentLog` reads every meta (to label an `Agent`
// tool_use with what it spawned, and to name the spawner in a from/to header)
// while parsing exactly ONE transcript, which is what makes a per-agent fetch
// affordable at a 10s poll.
function subagentMetas(dir) {
  const metas = new Map();
  if (!dir) return metas;
  let files = []; try { files = readdirSync(dir).filter((f) => f.endsWith('.jsonl')); } catch { return metas; }
  for (const f of files) {
    const id = f.replace(/^agent-|\.jsonl$/g, '');
    let meta = {}; try { meta = JSON.parse(readFileSync(join(dir, `agent-${id}.meta.json`), 'utf8')); } catch {}
    metas.set(id, meta);
  }
  return metas;
}
// toolUseId → the agent that tool_use spawned, so an `Agent` call inside a log
// can name what came out of it without parsing that child's transcript.
function childByToolUse(metas) {
  const m = new Map();
  for (const [id, meta] of metas) if (meta && meta.toolUseId) m.set(meta.toolUseId, id);
  return m;
}
// Parent resolution, ONE rule for both entry points: an agent whose declared
// parent is not in this session hangs off the synthetic root, exactly as the
// tree draws it.
const parentOf = (meta, metas, hasRoot) => {
  const p = meta && meta.parentAgentId;
  if (p && metas.has(p)) return p;
  return hasRoot ? ROOT_ID : null;
};

const agentLabelHtml = (id, meta) => `${esc((meta && meta.agentType) || '?')} · ${esc(String(id).slice(0, 8))}`;
// from/to header for task + inter-agent messages: from = the spawner
// (clickable - selects that agent), or `labels.root_owner` when there is none,
// which is the root session's own log: those prompts come from a person, not
// from a spawning agent, so the header needs a word for them and it is a local
// value.
const hdrFor = (id, meta, parentId, parentMeta) => ({
  fromHtml: parentId
    ? `<a class="fromlink" href="#a-${esc(parentId)}" data-id="${esc(parentId)}">${agentLabelHtml(parentId, parentMeta)}</a>`
    : esc(ROOT_OWNER_LABEL),
  toHtml: agentLabelHtml(id, meta),
});
const headerHtml = (model, meta, startTs, endTs, active, now) =>
  `${model ? esc(model) + ' · ' : ''}depth ${(meta && meta.spawnDepth) ?? 1} · ${hhmmss(startTs)}–${active ? 'live' : hhmmss(endTs)} · ${active ? '<span class="live">working</span>' : `stopped · ${endTs ? ago(now - endTs) : '—'}`}`;

const firstLine = (s) => (String(s || '').split('\n').find((x) => x.trim()) || '').trim();
// Per-agent task summary. Source of truth: the spawning Agent tool call's
// `description` (the harness copies it into agent-<id>.meta.json). Fallback
// when absent: the first non-empty line of the agent's task prompt. The root
// carries the fleet identity instead, so it shows no desc line.
const descFrom = (isRoot, meta, events) => (isRoot ? '' : (meta && meta.description) || firstLine(events.find((e) => e.kind === 'task')?.text) || '');

// The tail of an agent's log as PLAIN TEXT, carried on every TREE row.
// At a few hundred agents this is the only thing that separates two blocks with
// the same type and the same description without opening either log, and for an
// alive agent it is what it is doing right now. It rides in the tree because it
// is the one piece of log content cheap enough to: deliberately not HTML, because
// the moment this renders markup it drags images and cap-expanders back into
// every snapshot, which is the payload this whole split exists to remove.
const LASTLINE_CHARS = 160;
function lastLineOf(events) {
  for (let i = events.length - 1; i >= 0; i--) {
    const ev = events[i];
    const raw = ev.kind === 'tool_use' ? `${ev.name}(${argSummary(ev.name, ev.input)})` : String(ev.text || '');
    const line = raw.replace(/\s+/g, ' ').trim();
    if (line) return line.length > LASTLINE_CHARS ? line.slice(0, LASTLINE_CHARS - 1) + '…' : line;
  }
  return '';
}

// Guard for anything that becomes part of a FILE PATH. `id` reaches
// `agent-<id>.jsonl`, so an unvalidated one is a directory traversal served
// over HTTP. It is checked HERE, where the path is built, and not only in the
// route: a guard that lives in the caller protects that one caller.
const SAFE_AGENT_ID = /^[A-Za-z0-9_-]{1,64}$/;
export const isSafeAgentId = (id) => SAFE_AGENT_ID.test(String(id));

// ONE agent's log - what `GET /agent/<id>` serves. Parses that agent's
// transcript and no other.
//
// `since` indexes the SAME filtered event array the tree counts as
// `eventCount`, so a client that has rendered N events asks for `since=N` and
// gets [N, total): a poll on a quiet agent transfers an empty array. The two
// numbers MUST come from the same parse for that to hold, which is why
// parseTranscript is shared rather than reimplemented here.
//
// Returns null for an unknown or unsafe id, which the route must turn into a
// 404: an empty log rendered as a 200 is indistinguishable from an agent that
// has not spoken yet, and the viewer would sit in front of it waiting.
export function agentLog(sessionId, id, { capKB = 16, since = 0 } = {}) {
  if (!isSafeAgentId(id)) return null;
  const CAP = capKB * 1024;
  const now = Date.now();
  const dir = subagentsDir(sessionId);
  const base = sessionDir(sessionId);
  const rootTranscript = base ? join(base, `${sessionId}.jsonl`) : '';
  const hasRoot = !!(rootTranscript && existsSync(rootTranscript));
  const isRoot = id === ROOT_ID;
  const file = isRoot ? rootTranscript : (dir ? join(dir, `agent-${id}.jsonl`) : '');
  if (!file || !existsSync(file)) return null;
  // Bounds snapImgs, which this route does not hand out: its images are
  // resolved by hash from the durable store instead (see the image section).
  resetImgStore();
  const metas = subagentMetas(dir);
  const meta = isRoot ? ROOT_META : (metas.get(id) || {});
  const t = parseTranscript(file);
  const model = t.model || meta.model || '';
  const active = t.endTs != null && now - t.endTs < ACTIVE_MS;
  const parentId = isRoot ? null : parentOf(meta, metas, hasRoot);
  const parentMeta = parentId === ROOT_ID ? ROOT_META : (parentId ? metas.get(parentId) || {} : {});
  const hdr = hdrFor(id, meta, parentId, parentMeta);
  const kids = childByToolUse(metas);
  const from = Math.max(0, Math.min(Math.floor(Number(since) || 0), t.events.length));
  const fleet = fleetName();
  return {
    id, since: from, total: t.events.length,
    eventsHtml: t.events.slice(from).map((ev) => {
      const child = ev.kind === 'tool_use' ? kids.get(ev.id) : null;
      return renderEvent(ev, child ? (metas.get(child) || {}).agentType || null : null, CAP, hdr);
    }),
    type: isRoot && fleet ? `${fleet} · root session` : (meta.agentType || '?'),
    desc: descFrom(isRoot, meta, t.events),
    model, active,
    header: headerHtml(model, meta, t.startTs, t.endTs, active, now),
  };
}

// The whole tree, plus the logs of the agents named in `logsFor`.
// `logsFor: null` = every log (build.mjs's self-contained bake); an array or
// Set = exactly those, and every other agent contributes its tree row only.
export function snapshot(sessionId, { capKB = 16, logsFor = null } = {}) {
  const CAP = capKB * 1024;
  const now = Date.now();
  const fleet = fleetName();
  const dir = subagentsDir(sessionId);
  resetImgStore();
  const wantSet = logsFor == null ? null : new Set(logsFor);
  const wantLog = (id) => wantSet == null || wantSet.has(id);

  const raw = new Map();
  // No subagents dir = a session that hasn't delegated yet (pickSession can
  // now select those) - render it as a root-only tree, don't throw.
  const metas = subagentMetas(dir);
  for (const [id, meta] of metas) {
    const t = parseTranscript(join(dir, `agent-${id}.jsonl`));
    // Model badge, two sources in priority order. The transcript's own assistant
    // turns are the precise one (`claude-opus-5` -> `opus-5`); the harness also
    // writes a COARSE alias into agent-<id>.meta.json (`opus`, `sonnet`), which
    // is used only when the transcript has no assistant turn yet - an agent that
    // has been spawned but has not answered. Without the fallback such a block
    // shows no model line at all until its first turn lands, which reads as
    // "this agent has no model" rather than "it has not spoken yet".
    raw.set(id, { id, meta, ...t, model: t.model || meta.model || '', active: t.endTs != null && now - t.endTs < ACTIVE_MS });
  }

  // Synthetic ROOT node: the main session transcript (the top instance the
  // human talks to, which spawns the depth-1 agents). Same formatter path;
  // every parentless agent hangs off it.
  const base = sessionDir(sessionId);
  const rootTranscript = base ? join(base, `${sessionId}.jsonl`) : '';
  if (existsSync(rootTranscript)) {
    const t = parseTranscript(rootTranscript);
    raw.set(ROOT_ID, { id: ROOT_ID, meta: { ...ROOT_META }, ...t, active: t.endTs != null && now - t.endTs < ACTIVE_MS });
    for (const a of raw.values()) {
      if (a.id === ROOT_ID) continue;
      a.meta.parentAgentId = parentOf(a.meta, raw, true);
    }
  }

  // spawn map + tidy-tree layout
  const kids = childByToolUse(metas);
  const childrenOf = (id) => [...raw.values()].filter((a) => a.meta.parentAgentId === id).sort((x, y) => (x.startTs || 0) - (y.startTs || 0));
  const roots = [...raw.values()].filter((a) => !a.meta.parentAgentId || !raw.has(a.meta.parentAgentId)).sort((x, y) => (x.startTs || 0) - (y.startTs || 0));
  const pos = new Map(); let leaf = 0, maxDepth = 0;
  const layout = (a, depth) => {
    maxDepth = Math.max(maxDepth, depth);
    const kk = childrenOf(a.id);
    if (!kk.length) pos.set(a.id, { col: leaf++, depth });
    else { kk.forEach((k) => layout(k, depth + 1)); const cs = kk.map((k) => pos.get(k.id).col); pos.set(a.id, { col: (Math.min(...cs) + Math.max(...cs)) / 2, depth }); }
  };
  roots.forEach((r) => layout(r, 0));
  const maxCol = Math.max(0, ...[...pos.values()].map((p) => p.col));
  const cx = (col) => PAD + col * (BW + HGAP) + BW / 2;

  // Per-node vertical geometry: wrap each description and derive the block's
  // real height. Nodes are NOT uniform BH, so rows can't be placed by a
  // single-height formula - instead each depth-row's top is the previous row's
  // top plus that row's TALLEST node plus VGAP. Node y = its row's top; edges
  // anchor to each node's own bottom/top (below), so a tall block never
  // overlaps the next row and arrows still meet box edges.
  const descOf = (a) => descFrom(a.id === ROOT_ID, a.meta, a.events);
  const dims = new Map(); // id -> { descLines, modelY, timesY, h }
  for (const a of raw.values()) {
    if (!pos.has(a.id)) continue;
    const descLines = wrapDesc(descOf(a));
    const n = descLines.length;
    const model = a.model || '';
    // No model → classic geometry, unchanged: n===0 (root / no desc) keeps the
    // 80px block with times at y73; n===1 also lands at 80px
    // (DESC_Y0 + 0 + TIMES_GAP + BOTTOM_PAD = 80).
    let modelY = null;
    let timesY;
    if (model) {
      // Model line sits below the last description line (or just under the
      // header for a no-desc/root block), pushing the time range down by one
      // line so the two muted rows never overlap.
      const descEndY = n ? DESC_Y0 + (n - 1) * DESC_LH : DESC_NODESC_ANCHOR;
      modelY = descEndY + (n ? MODEL_LH : 14);
      timesY = modelY + TIMES_GAP;
    } else {
      timesY = n ? DESC_Y0 + (n - 1) * DESC_LH + TIMES_GAP : 73;
    }
    const h = Math.max(BH, timesY + BOTTOM_PAD);
    dims.set(a.id, { descLines, modelY, timesY, h });
  }
  const rowH = []; // tallest node height per depth
  for (const [id, p] of pos) rowH[p.depth] = Math.max(rowH[p.depth] || BH, dims.get(id).h);
  const rowTop = []; rowTop[0] = PAD;
  for (let d = 1; d <= maxDepth; d++) rowTop[d] = rowTop[d - 1] + rowH[d - 1] + VGAP;

  const idents = assignIdentities([...raw.values()]);

  const nodes = [], edges = [], agents = [];
  for (const a of raw.values()) {
    const p = pos.get(a.id); if (!p) continue;
    const type = a.meta.agentType || '?';
    const ident = idents.get(a.id) || null;
    const isRoot = a.id === ROOT_ID;
    const descText = descOf(a);
    const dim = dims.get(a.id);
    const lastLine = lastLineOf(a.events);
    nodes.push({
      id: a.id, type, typeShort: type.length > 26 ? type.slice(0, 25) + '…' : type,
      name: ident?.name || '', avatarHash: ident ? avatarRef(ident.avatarPath) : null,
      desc: descText, descLines: dim.descLines, timesY: dim.timesY, h: dim.h,
      // The language model this agent runs on (claude- prefix already stripped
      // by parseTranscript). Empty → no badge line rendered (dim.modelY null).
      model: a.model || '', modelY: dim.modelY,
      isRoot, fleet: isRoot ? fleet : '',
      active: a.active, depth: p.depth, lastLine,
      x: cx(p.col) - BW / 2, y: rowTop[p.depth],
      times: `${hhmmss(a.startTs)} → ${a.active ? 'live' : hhmmss(a.endTs)}`,
    });
    if (a.meta.parentAgentId && pos.has(a.meta.parentAgentId)) {
      const pp = pos.get(a.meta.parentAgentId);
      edges.push({ x1: cx(pp.col), y1: rowTop[pp.depth] + dims.get(a.meta.parentAgentId).h, x2: cx(p.col), y2: rowTop[p.depth] });
    }
    const parentId = a.meta.parentAgentId && raw.has(a.meta.parentAgentId) ? a.meta.parentAgentId : null;
    const hdr = hdrFor(a.id, a.meta, parentId, parentId ? raw.get(parentId).meta : null);
    // THE EXPENSIVE PART, and the only part that is conditional. Everything
    // above is the tree row; this is the log, and it is rendered only for an
    // agent the caller asked for.
    const eventsHtml = wantLog(a.id)
      ? a.events.map((ev) => {
          const child = ev.kind === 'tool_use' ? kids.get(ev.id) : null;
          return renderEvent(ev, child && raw.has(child) ? raw.get(child).meta.agentType : null, CAP, hdr);
        })
      : [];
    agents.push({
      id: a.id, type: isRoot && fleet ? `${fleet} · root session` : type, desc: descText, model: a.model, depth: a.meta.spawnDepth ?? 1,
      startTs: a.startTs, endTs: a.endTs, active: a.active, eventsHtml,
      // eventCount is the log's TRUE length whether or not its HTML was
      // rendered, and it is the number a client passes back as `since`.
      // eventsHtml.length is NOT that number for an unrendered agent, and
      // reading it as one is how a lazy client would silently skip a log.
      eventCount: a.events.length, lastLine,
      header: headerHtml(a.model, a.meta, a.startTs, a.endTs, a.active, now),
    });
  }
  return {
    sessionId, now, workingCount: agents.filter((a) => a.active).length,
    // Variable node heights: canvas height is the last row's top + its tallest
    // node + bottom pad, not a uniform-BH formula.
    svgW: PAD * 2 + maxCol * (BW + HGAP) + BW,
    svgH: (rowTop[maxDepth] ?? PAD) + (rowH[maxDepth] ?? BH) + PAD,
    firstId: roots[0]?.id || agents[0]?.id || '', nodes, edges, agents,
    imgs: Object.fromEntries(snapImgs), // contentHash → data URI store for <img data-img> refs
    stamp: new Date(now).toISOString().replace('T', ' ').slice(0, 19) + ' UTC',
  };
}

// ---------------------------------------------------------------- theme ----
// Claude Code "Dark mode (colorblind-friendly)" - dark-daltonized. Every hex
// below is the exact rgb() from the bundled theme object (see header comment).
export function css() {
  return `
  :root {
    --bg:#000000;            /* clawd_background — terminal black */
    --fg:#ffffff;            /* text */
    --claude:#ff9933;        /* claude (brand ⏺ orange) */
    --permission:#99ccff;    /* permission / suggestion */
    --success:#3399ff;       /* success — colorblind theme: blue, not green */
    --error:#ff6666;         /* error */
    --warning:#ffcc00;       /* warning */
    --inactive:#999999;      /* inactive / dim text */
    --subtle:#505050;        /* subtle */
    --border:#888888;        /* promptBorder */
    --panel:#262626;         /* composerSidebarBackground */
    --user-bg:#373737;       /* userMessageBackground */
    --sel-bg:#264f78;        /* selectionBg */
    --diff-add:#004466;      /* diffAdded — BLUE additions */
    --diff-del:#660000;      /* diffRemoved — dark-red removals */
    --diff-add-dim:#3e515b;  /* diffAddedDimmed (gutter) */
    --diff-del-dim:#3e2c2c;  /* diffRemovedDimmed (gutter) */
    --diff-add-word:#0077b3; /* diffAddedWord */
    --diff-del-word:#b30000; /* diffRemovedWord */
  }
  * { box-sizing:border-box; }
  html { color-scheme: dark; }
  body { background:var(--bg); color:var(--fg); margin:0; padding:18px 14px 72px;
         font:12.5px/1.55 ui-monospace,"SF Mono",Menlo,Consolas,"DejaVu Sans Mono",monospace; }
  main { max-width:1000px; margin:0 auto; }
  h1 { font-size:15px; font-weight:700; margin:0 0 2px; color:var(--fg); }
  code { font:inherit; color:var(--permission); }
  .stamp { font-size:11.5px; color:var(--inactive); margin:0 0 12px; }
  .stamp b { color:var(--success); }
  .graphwrap { overflow-x:auto; border:1px solid var(--panel); border-radius:6px; background:var(--bg); padding:10px; margin-bottom:8px; }
  svg { display:block; }
  .edge { fill:none; stroke:var(--subtle); stroke-width:1.4; }
  .node { cursor:pointer; }
  .node rect { fill:var(--panel); stroke:var(--subtle); stroke-width:1.4; }
  .node.active rect { fill:rgba(51,153,255,.12); stroke:var(--success); }
  .node:hover rect { filter:brightness(1.25); }
  .node.sel rect { stroke:var(--permission); stroke-width:2.6; }
  .node .nt { font:700 12px ui-monospace,Menlo,monospace; fill:var(--fg); }
  .node.active .nt { fill:var(--success); }
  .node .nr { font:9.5px ui-monospace,Menlo,monospace; fill:var(--inactive); }
  /* per-agent task description — the "what it's doing" summary, one row below
     the header, italic so it reads distinctly from the type line */
  .node .nd { font:italic 9.5px ui-monospace,Menlo,monospace; fill:var(--permission); }
  .node.stopped .nd { fill:var(--inactive); }
  .node .nm { font:10.5px ui-monospace,Menlo,monospace; fill:var(--inactive); }
  /* model badge: the LLM the agent runs on — small + muted, tinted toward
     permission-blue (dimmed) so it reads as metadata distinct from both the
     italic description above and the grey time range below */
  .node .nml { font:9px ui-monospace,Menlo,monospace; fill:var(--permission); opacity:.6; }
  .node.stopped .nml { fill:var(--inactive); opacity:.65; }
  /* avatar gutter: dimmed on stopped agents so the graph reads alive-vs-done
     at a glance the same way the block colours already do */
  .node .nav { opacity:.95; }
  .node.stopped .nav { opacity:.45; filter:saturate(.35); }
  /* spinner on alive/working nodes: rotating arc next to the time range */
  .node .spin circle { fill:none; stroke:var(--success); stroke-width:2; stroke-linecap:round;
                       animation:dspin .9s linear infinite; transform-box:fill-box; transform-origin:center; }
  @keyframes dspin { to { transform:rotate(360deg); } }
  @media (prefers-reduced-motion: reduce) { .node .spin circle { animation:none; } }
  .hint { font-size:11px; color:var(--inactive); margin:0 0 16px; }
  .hint em { color:var(--inactive); }
  .agentlog { display:none; background:var(--bg); border:1px solid var(--panel); border-radius:6px; padding:12px 14px; }
  .agentlog > header { display:flex; flex-wrap:wrap; gap:8px; align-items:baseline; border-bottom:1px solid var(--panel); padding-bottom:8px; margin-bottom:8px; }
  .atype { font-weight:700; color:var(--claude); }
  .adesc { color:var(--fg); }
  .ameta { margin-left:auto; font-size:11px; color:var(--inactive); font-variant-numeric:tabular-nums; }
  .live { color:var(--success); font-weight:700; }
  pre { font:inherit; white-space:pre-wrap; overflow-wrap:anywhere; margin:0; }
  .dim { color:var(--inactive); }
  .ev { margin:10px 0; }
  /* all leading marker glyphs come from ::before pseudo-elements so the
     alive-last-line animation (below) can cycle their content frames */
  .bull { flex:0 0 18px; }
  .bull::before { content:"⏺"; }
  .bull.claude { color:var(--fg); }
  .bull.ok { color:var(--success); }
  /* console input (task prompt / user messages): framed like the prompt box */
  .msghead { font-size:11px; color:var(--inactive); margin-bottom:3px; font-variant-numeric:tabular-nums; }
  .fromlink { color:var(--permission); text-decoration:none; cursor:pointer; }
  .fromlink:hover { text-decoration:underline; }
  .prompt { display:flex; gap:8px; background:var(--user-bg); border-radius:4px; padding:7px 10px; }
  .prompt .gt { color:var(--inactive); flex:0 0 auto; }
  .gt::before { content:">"; }
  .prompt .pbody { flex:1; min-width:0; color:var(--fg); }
  /* assistant text: ⏺ bullet + prose */
  .text { display:flex; }
  .text .tbody { flex:1; min-width:0; }
  /* thinking: ✻ italic dim */
  .thinking { color:var(--inactive); }
  .thinking .tmark { font-style:italic; }
  .thinking pre { font-style:italic; color:var(--inactive); padding-left:18px; }
  .thinking.empty .enc { opacity:.7; font-style:italic; }
  .tg::before { content:"✻"; }
  /* LAST LINE OF AN ALIVE AGENT: whatever the last event is — Bash/Read/Write
     unit, any tool call, thinking, text, message, standalone result — its
     leading marker cycles the Claude-style frames · ✢ ✳ ✶ ✻ ✽ in
     claude-orange, like the console's progress indicator. .alive lives in the
     MUTABLE zone — re-set on every 10s tick, dropped when the agent goes
     stopped/stale — and :last-child self-downgrades to the normal static
     marker the moment a later event appends to the stream. Stopped agents
     never animate. Reduced motion: static orange ✻, no animation. */
  .agentlog.alive .stream > :last-child .bull,
  .agentlog.alive .stream > :last-child .tg,
  .agentlog.alive .stream > .ev.msg:last-child .gt,
  .agentlog.alive .stream > .ev.result:last-child > .mark { color:var(--claude); font-style:normal; }
  .agentlog.alive .stream > :last-child .bull::before,
  .agentlog.alive .stream > :last-child .tg::before,
  .agentlog.alive .stream > .ev.msg:last-child .gt::before,
  .agentlog.alive .stream > .ev.result:last-child > .mark::before { animation:tframes .9s infinite; }
  .agentlog.alive .stream > :last-child .tmark { animation:tpulse 1.6s ease-in-out infinite; }
  @keyframes tframes {
    0%,100%{content:"·"} 16.7%{content:"✢"} 33.3%{content:"✳"}
    50%{content:"✶"} 66.7%{content:"✻"} 83.3%{content:"✽"} }
  @keyframes tpulse { 0%,100%{opacity:.6} 50%{opacity:1} }
  @media (prefers-reduced-motion: reduce) {
    .agentlog.alive .stream > :last-child .bull::before,
    .agentlog.alive .stream > :last-child .tg::before,
    .agentlog.alive .stream > .ev.msg:last-child .gt::before,
    .agentlog.alive .stream > .ev.result:last-child > .mark::before { animation:none; content:"✻"; }
    .agentlog.alive .stream > :last-child .tmark { animation:none; } }
  /* Bash/Read/Write units: ONE line collapsed (gray CSS ellipsis), click to expand */
  details.unit > summary { display:flex; cursor:pointer; list-style:none; }
  details.unit > summary::-webkit-details-marker { display:none; }
  details.unit > summary .oneline { flex:1; min-width:0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; color:var(--inactive); }
  details.unit > summary .tname { font-weight:700; color:var(--fg); }
  details.unit > summary .prev { color:var(--inactive); }
  details.unit > summary:hover .prev { color:var(--fg); }
  details.unit.err > summary .bull { color:var(--error); }
  .unitbody { padding-left:18px; margin-top:2px; }
  .unitbody .fullcmd { color:var(--fg); background:var(--panel); border-radius:4px; padding:6px 8px; margin-bottom:2px; }
  .unitbody .ev.result { padding-left:0; margin:2px 0 0; }
  /* tool call: ⏺ Name(args) */
  .tool .tline { display:flex; }
  .tool .tname { font-weight:700; color:var(--fg); }
  .tool .targs { color:var(--inactive); overflow-wrap:anywhere; }
  .tool .spawn { color:var(--permission); margin-left:6px; }
  .tool .ev.result { margin:2px 0 0; }
  details.jin { margin:2px 0 0 18px; }
  details.jin > summary { cursor:pointer; font-size:11px; color:var(--inactive); }
  details.jin > pre { color:var(--inactive); background:var(--panel); border-radius:4px; padding:6px 8px; margin-top:4px; }
  /* tool result: ⎿ dim, clamped */
  .result { display:flex; padding-left:18px; color:var(--inactive); }
  .result .mark { flex:0 0 22px; color:var(--subtle); }
  .mark::before { content:"⎿"; }
  .result .rbody { flex:1; min-width:0; }
  .result.err, .result.err .mark { color:var(--error); }
  details.more { display:inline-block; width:100%; }
  details.more > summary, details.dmore > summary { cursor:pointer; color:var(--inactive); font-size:11.5px; list-style:none; }
  details.more > summary::-webkit-details-marker, details.dmore > summary::-webkit-details-marker { display:none; }
  details.more > summary:hover, details.dmore > summary:hover { color:var(--permission); }
  details[open].more > summary::after, details[open].dmore > summary::after { content:"  (collapse)"; color:var(--subtle); }
  /* diffs — the console's Edit display, dark-daltonized colors */
  .dhead { color:var(--inactive); margin-bottom:2px; }
  .dhead b { color:var(--fg); font-weight:700; }
  .diff { border:1px solid var(--panel); border-radius:4px; overflow:hidden; margin-top:2px; }
  .dl { display:flex; color:var(--fg); }
  .dl .ln { flex:0 0 auto; white-space:pre; padding:0 6px 0 8px; color:var(--inactive); user-select:none; }
  .dl .dc { flex:1; min-width:0; white-space:pre-wrap; overflow-wrap:anywhere; }
  .dl.ctx .dc { color:var(--inactive); }
  .dl.add { background:var(--diff-add); }
  .dl.add .ln { background:var(--diff-add-dim); color:var(--fg); }
  .dl.del { background:var(--diff-del); }
  .dl.del .ln { background:var(--diff-del-dim); color:var(--fg); }
  details.dmore > summary { padding:2px 8px; background:var(--panel); }
  /* files surfaced to the human */
  .sentfile { margin:4px 0; }
  .filechip { display:inline-block; background:var(--panel); border:1px solid var(--subtle); border-radius:4px; padding:1px 8px; color:var(--permission); overflow-wrap:anywhere; }
  /* image thumbnails: every occurrence renders ~200px tall; click opens full size in a new tab */
  .inline-img { display:block; max-width:100%; max-height:200px; margin-top:6px; border:1px solid var(--subtle); border-radius:4px; background:var(--panel); cursor:zoom-in; }
  .inline-img:hover { border-color:var(--permission); }
  /* 📦 handover packages — deliverables, visibly distinct from tool I/O */
  .pkg { border:1px solid var(--claude); border-left:3px solid var(--claude); border-radius:4px; background:rgba(255,153,51,.07); padding:7px 10px; }
  .pkghead { color:var(--claude); font-weight:700; margin-bottom:3px; }
  details.pkgitem { margin:2px 0; }
  details.pkgitem > summary { cursor:pointer; list-style:none; }
  details.pkgitem > summary::-webkit-details-marker { display:none; }
  details.pkgitem > summary::before { content:"▸ "; color:var(--claude); }
  details[open].pkgitem > summary::before { content:"▾ "; }
  details.pkgitem > summary:hover .pkgname { color:var(--warning); }
  .pkgname { color:var(--permission); font-weight:700; overflow-wrap:anywhere; }
  .pkgbody { margin:6px 0 6px 14px; color:var(--inactive); border-left:1px solid var(--panel); padding-left:10px; }
  ::selection { background:var(--sel-bg); }`;
}

// SVG for a node/edge set (used by both the static bake and the live client via /state geometry)
export function svgMarkup(snap) {
  const edges = snap.edges.map((e) => `<path class="edge" d="M${e.x1},${e.y1} C${e.x1},${(e.y1 + e.y2) / 2} ${e.x2},${(e.y1 + e.y2) / 2} ${e.x2},${e.y2}" marker-end="url(#arw)"/>`).join('');
  // active nodes carry a spinner arc next to the time range (CSS-animated;
  // static arc under prefers-reduced-motion); stopped nodes stay plain grey.
  // The time range sits at the block's own timesY (blocks are variable-height),
  // so the spinner tracks it rather than a fixed y.
  const spinnerAt = (y) => `<g class="spin" transform="translate(${BW - 15},${y - 5})"><circle r="5.5" stroke-dasharray="24 10.6"/></g>`;
  // Block layout, top to bottom: an optional avatar gutter (named agents; the
  // role is legible from the art's hue key), the header (root → fleet name +
  // "root session"; named agent → name + type; unnamed type → type only), the
  // per-agent task description (full width, below the avatar - WRAPS across as
  // many lines as it needs, the block growing to fit), then the time range.
  // Root shows the fleet identity instead of a description.
  const nodes = snap.nodes.map((n) => {
    let head;
    if (n.isRoot) {
      head = n.fleet
        ? `<text class="nt" x="11" y="24">${esc(n.fleet)}</text><text class="nr" x="11" y="38">root session</text>`
        : `<text class="nt" x="11" y="26">${esc(n.typeShort)}</text>`;
    } else if (n.name) {
      head = `<text class="nt" x="50" y="24">${esc(n.name)}</text><text class="nr" x="50" y="38">${esc(n.typeShort)}</text>`;
    } else {
      head = `<text class="nt" x="11" y="26">${esc(n.typeShort)}</text>`;
    }
    const av = n.avatarHash ? `<image class="nav" data-img="${esc(n.avatarHash)}" x="9" y="13" width="36" height="36" preserveAspectRatio="xMidYMid meet"/>` : '';
    // Wrapped description: one <text> anchored at DESC_Y0, one <tspan> per line
    // stepping down by DESC_LH. Empty (root) → no desc element.
    const descLine = (n.descLines && n.descLines.length)
      ? `<text class="nd" x="11" y="${DESC_Y0}">${n.descLines.map((l, i) => `<tspan x="11"${i ? ` dy="${DESC_LH}"` : ''}>${esc(l)}</tspan>`).join('')}</text>`
      : '';
    // Model badge - a small muted line naming the LLM the agent runs on. Only
    // rendered when the transcript yielded a model (modelY set); a leading ◇
    // sets it apart from the italic desc above and the plain time range below.
    const modelLine = (n.model && n.modelY != null)
      ? `<text class="nml" x="11" y="${n.modelY}">◇ ${esc(n.model)}</text>`
      : '';
    // Hover tooltip. It ends with the agent's LAST LOG LINE, which is the only
    // way to tell two same-type, same-description blocks apart - or to see what
    // an alive agent is doing - without opening a log. That matters here because
    // a log is not in the document: selecting one is a fetch, and at a few
    // hundred agents hovering is how a viewer finds the one worth fetching.
    const title = `${n.isRoot && n.fleet ? n.fleet + ' · ' : ''}${n.name ? n.name + ' · ' : ''}${n.type}${n.model ? ' · ' + n.model : ''}${n.desc ? ' — ' + n.desc : ''}${n.lastLine ? '\n' + n.lastLine : ''}`;
    return `<g class="node ${n.active ? 'active' : 'stopped'}" id="node-${esc(n.id)}" data-id="${esc(n.id)}" transform="translate(${n.x},${n.y})"><title>${esc(title)}</title><rect width="${BW}" height="${n.h}" rx="6"/>${av}${head}${descLine}${modelLine}<text class="nm" x="11" y="${n.timesY}">${esc(n.times)}</text>${n.active ? spinnerAt(n.timesY) : ''}</g>`;
  }).join('');
  return `<svg width="${snap.svgW}" height="${snap.svgH}" viewBox="0 0 ${snap.svgW} ${snap.svgH}" xmlns="http://www.w3.org/2000/svg"><defs><marker id="arw" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 Z" fill="var(--subtle)"/></marker></defs>${edges}${nodes}</svg>`;
}
