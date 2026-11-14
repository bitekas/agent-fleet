#!/usr/bin/env python3
"""Figma file comments over the REST API: read them threaded, see what is new,
post a reply. Python 3 standard library plus the fleet's own fleetlib.

    figma_comments.py list  [--file F] [--unresolved] [--since T] [--author A]... [--anchor X] [--json]
    figma_comments.py new   [--file F] [same filters] [--peek] [--json]
    figma_comments.py reply <comment-id> [--file F] (--message TEXT | --message-file PATH | stdin) [--dry-run]
    figma_comments.py post  --node NODE-ID [--offset X,Y] [--file F] (--message ... ) [--dry-run]

--file is an alias from config.json's `files`, a file key, or a Figma URL; it may
be left out when config.json names exactly one file. SKILL.md is the manual:
what every flag means, what each output field is, and the traps.

================================================================================
THREE TOKENS, THREE ROLES, AND WHY THE WRITE ONE IS SEPARATE
================================================================================
`tokens.read`    file_comments:read  - every GET of comments. Required.
`tokens.write`   file_comments:write - `reply` and `post`. Optional: null means
                 the install is READ-ONLY, and every write verb refuses before it
                 builds a request. A read-only install therefore cannot post by
                 accident, whatever a caller passes.
`tokens.content` file_content:read   - anchor NAMES (a node id to its frame and
                 page name). Optional; `names.token` says which token the name
                 lookup uses: "content", "read" (the read token also carries
                 file_content:read) or null (no lookup: the link is printed and
                 the name is marked unavailable, naming the scope).

A personal access token acts as the PERSON who generated it, on every file that
person can open. Whether an agent may post at all is its charter's call; this
file only makes the call possible and refuses when the install withheld it.

================================================================================
A TOKEN NEVER REACHES ARGV, STDOUT, STDERR OR A LOG
================================================================================
Tokens are read from their files inside this process and only ever placed in
the request header. A token file holds ONE line of printable non-space ASCII;
anything else is refused naming the path, because the HTTP layer rejects such a
header value and quotes it, escaped, where an exact-value scrub cannot see it. Every error text goes through scrub(), which removes every
token this process loaded and anything shaped like a Figma personal access
token (`figd_...`), because an error body is server text this code does not
control. figma_comments.test.py section 6 proves it with a fake server that
echoes the token back.

================================================================================
NOTHING HERE RESOLVES A THREAD
================================================================================
Figma's REST API has no call that resolves or reopens a comment thread, and
this file sends only GETs and POST /v1/files/<key>/comments. It also offers no
DELETE. figma_comments.test.py section 7 records every request a run makes and
fails on any other method or path.

================================================================================
EXIT CODES
================================================================================
    0  ok; for a write, POSTED (a cursor that could not be updated afterwards,
       or a response that did not parse, is only a warning on stderr)
    1  usage, configuration or local state (nothing was posted)
    2  a token file is missing, unreadable, empty, not one line or
       over-permissive, or the write token is not configured for a write verb
    3  Figma refused the token: invalid, expired or revoked (401), a missing
       scope (the message names the scope that call needs), or no access (403)
    4  any other API failure, every transport failure included: not found, rate
       limited (429), a timeout, a truncated body, server error, network
    5  a write whose outcome is UNKNOWN: it was sent and the answer was lost (a
       timeout or a broken connection after sending, or a 5xx). Read the thread
       before retrying, or the retry posts the comment twice.

2, 3 and 4 are three repairs by three different people: the machine's
operator, the token's owner, and nobody (wait, or fix the key). 0 and 5 exist
because a write reported as failed is retried, and a retry of a write that
landed posts twice under a person's name.
"""
import argparse
import datetime
import http.client
import json
import os
import re
import socket
import stat
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# realpath, never abspath: run or imported through an agent's skill link, the
# unresolved path is the link directory, and three levels up from there is not
# the fleet tree whose lib/ holds fleetlib.
HERE = os.path.dirname(os.path.realpath(__file__))
FLEET_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(FLEET_ROOT, "lib"))
from fleetlib import expand as _expand  # noqa: E402
from fleetlib import paths as _paths  # noqa: E402

SKILL = "figma-workspace"
# Figma's REST root and its link root. Identical for every install, so they are
# mechanism, not config keys; tests replace the transport, not the host.
API = "https://api.figma.com"
WEB = "https://www.figma.com"
# The scope each kind of call needs (Figma's scopes page, read 2026-11-14).
SCOPE = {"read": "file_comments:read", "write": "file_comments:write",
         "content": "file_content:read"}

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect: the 3xx reaches the caller as an HTTPError.

    urllib's default handler re-sends the request's headers - X-Figma-Token
    among them - to the redirect target, on any host and any scheme. Figma's
    REST API never answers with a redirect, so following one can only hand the
    token to somebody else."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# The seam every network call goes through: an opener that follows no
# redirect. Tests replace this attribute; nothing else in this file may open a URL.
_urlopen = urllib.request.build_opener(_NoRedirect).open

# Every token value loaded by this process, so scrub() can remove it from any
# text, whatever its shape.
_LOADED = set()
_PAT = re.compile(r"figd_[A-Za-z0-9_\-]+")
# A token as an HTTP header value can carry it: one run of printable, non-space ASCII.
_TOKEN = re.compile(r"[\x21-\x7e]+")
_KEY = re.compile(r"[0-9A-Za-z]+")
_URL = re.compile(r"figma\.com/(?:design|file|board|slides|proto)/([0-9A-Za-z]+)"
                  r"(?:/branch/([0-9A-Za-z]+))?")
_MISSING = object()


class ConfigError(Exception):
    exit_code = 1


class CredentialError(Exception):
    exit_code = 2


class AuthError(Exception):
    exit_code = 3


class ApiError(Exception):
    exit_code = 4

    def __init__(self, message, status=None, maybe_sent=False):
        super().__init__(message)
        self.status = status
        # True when the request may have reached Figma before the failure: a
        # timeout or a broken connection after sending, or a 5xx. Only a write
        # cares, because retrying a write that did land posts it twice.
        self.maybe_sent = maybe_sent


class WriteUnknown(Exception):
    """A write whose outcome is unknown: it may have been posted."""
    exit_code = 5


def scrub(text):
    """TEXT with every loaded token and every `figd_...` run replaced."""
    text = str(text)
    for t in _LOADED:
        if t:
            text = text.replace(t, "[redacted]")
    return _PAT.sub("[redacted]", text)


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

# Required: present and non-empty. Nullable: present, null allowed - each null
# has a meaning (SKILL.md, "The tokens"), so a MISSING key is still an error
# rather than a silent null.
REQUIRED = ("files", "tokens.read.path", "names.cache_hours", "state.dir")
NULLABLE = ("mcp.connector_name", "tokens.write.path", "tokens.content.path", "names.token",
            "post.prefix")


def _dig(doc, dotted):
    cur = doc
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return _MISSING
        cur = cur[part]
    return cur


def default_config_path():
    try:
        return str(_paths.skill_context(SKILL) / "config.json")
    except Exception as e:  # noqa: BLE001 - any resolution failure is a config fault
        raise ConfigError(f"cannot resolve the install's config.json ({e}); pass --config "
                          f"or set FIGMA_WORKSPACE_CONFIG") from None


def load_config(path=None):
    """The config as a dict, validated. Raises ConfigError naming the key."""
    path = path or os.environ.get("FIGMA_WORKSPACE_CONFIG") or default_config_path()
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
    except FileNotFoundError:
        raise ConfigError(f"no config at {path} (copy config.example.json there and fill it in)")
    except OSError as e:
        raise ConfigError(f"config at {path} cannot be read ({e.strerror or e})")
    except ValueError as e:
        raise ConfigError(f"config at {path} does not parse: {e}")
    if not isinstance(cfg, dict):
        raise ConfigError(f"config at {path} is not a JSON object")
    for key in REQUIRED:
        if _dig(cfg, key) in (_MISSING, None, "", []):
            raise ConfigError(f"config at {path} is missing required key '{key}'")
    for key in NULLABLE:
        if _dig(cfg, key) is _MISSING:
            raise ConfigError(f"config at {path} is missing key '{key}' (null is allowed, "
                              f"absent is not)")
    for i, f in enumerate(cfg["files"]):
        if not isinstance(f, dict) or not f.get("alias") or not _KEY.fullmatch(str(f.get("key", ""))):
            raise ConfigError(f"config at {path}: files[{i}] needs an alias and an alphanumeric key")
    who = cfg["names"]["token"]
    if who not in (None, "read", "content"):
        raise ConfigError(f"config at {path}: names.token is {who!r}; it is \"read\", "
                          f"\"content\" or null")
    if who == "content" and not cfg["tokens"]["content"]["path"]:
        raise ConfigError(f"config at {path}: names.token is \"content\" but "
                          f"tokens.content.path is null")
    if not isinstance(cfg["names"]["cache_hours"], (int, float)) or cfg["names"]["cache_hours"] < 0:
        raise ConfigError(f"config at {path}: names.cache_hours is not a number >= 0")
    cfg["_path"] = path
    return cfg


def file_key(cfg, given):
    """(key, alias) for --file: an alias, a key, or a Figma URL (its branch key
    when the URL names a branch). Left out, the one configured file."""
    if not given:
        if len(cfg["files"]) == 1:
            return cfg["files"][0]["key"], cfg["files"][0]["alias"]
        raise ConfigError("config.json names several files; pass --file <alias>: "
                          + ", ".join(f["alias"] for f in cfg["files"]))
    for f in cfg["files"]:
        if given == f["alias"]:
            return f["key"], f["alias"]
    m = _URL.search(given)
    if m:
        return (m.group(2) or m.group(1)), None
    if _KEY.fullmatch(given):
        return given, next((f["alias"] for f in cfg["files"] if f["key"] == given), None)
    raise ConfigError(f"--file {given!r} is not a configured alias, a file key or a Figma URL")


# --------------------------------------------------------------------------
# Tokens
# --------------------------------------------------------------------------

def token_path(cfg, role):
    raw = cfg["tokens"][role]["path"]
    if not raw:
        return None
    return str(_paths.resolve_config_path(raw, cfg["_path"]))


def read_token(cfg, role):
    """The token for ROLE, read from its file. Raises CredentialError.

    OPENED, not stat'ed: a file that exists and cannot be read passes every
    exists() test and fails at the first call. Mode is checked on the open
    descriptor, so the file judged is the file read.
    """
    path = token_path(cfg, role)
    if path is None:
        if role == "write":
            raise CredentialError(
                "no write token is configured (tokens.write.path is null): this install is "
                "read-only, so nothing was posted")
        raise CredentialError(f"tokens.{role}.path is null in {cfg['_path']}")
    try:
        with open(path, "rb") as f:
            mode = stat.S_IMODE(os.fstat(f.fileno()).st_mode)
            # Bytes, decoded with replacement: a file that is not text reaches the
            # one-line check below as non-ASCII and is refused like any other.
            value = f.read().decode("utf-8", "replace").strip()
    except FileNotFoundError:
        raise CredentialError(f"no {role} token at {path} (tokens.{role}.path). Its owner "
                              f"generates a personal access token with {SCOPE[role]} and it is "
                              f"put there mode 600") from None
    except OSError as e:
        raise CredentialError(f"the {role} token at {path} cannot be read "
                              f"({e.strerror or e})") from None
    # Every line of the file is a candidate secret: remember them all for scrub()
    # before any check can fail, so no later message can carry one.
    _LOADED.update(part for part in re.split(r"\s+", value) if len(part) >= 8)
    if mode & 0o077:
        raise CredentialError(f"the {role} token at {path} is mode {mode:04o}; a credential is "
                              f"600 (chmod 600 {path}). Refused before use")
    if not value:
        raise CredentialError(f"the {role} token file at {path} is empty")
    if not _TOKEN.fullmatch(value):
        # The value is never quoted here. A second line or a pasted space is how
        # a token leaks: the transport rejects the header and quotes the whole
        # value, escaped, where the exact-value scrub cannot recognise it.
        raise CredentialError(f"the {role} token file at {path} does not hold one line of "
                              f"printable ASCII with no spaces (a second line, a space, a "
                              f"control character or a byte that is not ASCII is in it). Refused "
                              f"before use; rewrite the file with the token alone")
    _LOADED.add(value)
    return value


# --------------------------------------------------------------------------
# Transport
# --------------------------------------------------------------------------

def _figma_message(body):
    """Figma's own error text. Two body shapes are in use (measured 2026-11-14):
    {"status":..., "err": "..."} and {"error": true, "status":..., "message": "..."}."""
    try:
        doc = json.loads(body)
    except ValueError:
        return body[:300]
    if isinstance(doc, dict):
        return str(doc.get("err") or doc.get("message") or body[:300])
    return body[:300]


def api(cfg, role, path, method="GET", body=None, need=None):
    """One call to Figma's REST API with ROLE's token. Returns the parsed JSON.

    NEED is the scope this call needs (default: ROLE's), named in a scope 403.
    Raises AuthError (401/403), ApiError (anything else, every transport
    failure included), CredentialError (the token file). Every message is
    scrubbed. A 2xx POST whose body does not parse returns {"_unparsed": True}:
    the write happened, and reporting it as a failure invites a duplicate.
    """
    need = need or SCOPE[role]
    token = read_token(cfg, role)
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"X-Figma-Token": token}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(API + path, data=data, method=method, headers=headers)
    where = f"{method} {path.split('?')[0]}"
    try:
        with _urlopen(req, timeout=60) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        try:
            text = scrub(e.read().decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001 - an unreadable error body is still this status
            text = ""
        msg = scrub(_figma_message(text))
        if e.code == 401:
            raise AuthError(f"Figma refused the {role} token as invalid ({where}: HTTP 401 "
                            f"{msg}): it is expired, revoked or mistyped. A personal access "
                            f"token lives at most 90 days; its owner generates a new one") from None
        if e.code == 403 and "scope" in msg.lower():
            raise AuthError(f"the {role} token lacks a scope: this call needs {need} ({where}: "
                            f"HTTP 403 {msg})") from None
        if e.code == 403:
            raise AuthError(f"Figma refused the {role} token for this file ({where}: HTTP 403 "
                            f"{msg}): the token's owner cannot open it, or the token was "
                            f"revoked") from None
        if 300 <= e.code < 400:
            raise ApiError(f"{where}: HTTP {e.code}, a redirect, not followed: the REST API never "
                           f"redirects, and following one would send the token to its target",
                           e.code) from None
        if e.code == 404:
            raise ApiError(f"not found ({where}: HTTP 404 {msg}): a wrong file key, or a file or "
                           f"comment the token's owner cannot see", 404) from None
        if e.code == 429:
            h = e.headers or {}
            extra = ", ".join(f"{k} {h.get(k)}" for k in
                              ("Retry-After", "X-Figma-Plan-Tier", "X-Figma-Rate-Limit-Type",
                               "X-Figma-Upgrade-Link") if h.get(k))
            raise ApiError(f"rate limited ({where}: HTTP 429; {extra or 'no rate-limit headers'}). "
                           f"Retry after the Retry-After seconds; the budget is the token "
                           f"owner's, per plan, shared with every other use of it", 429) from None
        raise ApiError(f"{where}: HTTP {e.code} {msg}", e.code, maybe_sent=e.code >= 500) from None
    except urllib.error.URLError as e:
        # A refused connection or an unknown host never sent anything; any other
        # URLError (a timeout waiting for the answer) may have.
        unsent = isinstance(e.reason, (ConnectionRefusedError, socket.gaierror))
        raise ApiError(f"could not reach {API} ({where}: {scrub(e.reason)})",
                       maybe_sent=not unsent) from None
    except ValueError as e:
        # http.client rejects an illegal header value before anything is sent,
        # quoting the value; read_token keeps a token from being one.
        raise ApiError(f"{where}: the request could not be built ({scrub(e)})") from None
    except (http.client.HTTPException, OSError) as e:
        raise ApiError(f"{where}: the transport failed ({type(e).__name__}: {scrub(e)})",
                       maybe_sent=True) from None
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        if method == "POST":
            return {"_unparsed": True}
        raise ApiError(f"{where}: the response is not JSON") from None


def fetch_comments(cfg, key):
    """Every comment on the file, in one call. The endpoint is not paginated."""
    doc = api(cfg, "read", f"/v1/files/{key}/comments")
    comments = doc.get("comments")
    if not isinstance(comments, list):
        raise ApiError("the comments response carries no `comments` list")
    return comments


# --------------------------------------------------------------------------
# Threads, anchors, links
# --------------------------------------------------------------------------

def parse_time(text):
    """An aware UTC datetime. Figma writes UTC with milliseconds and `Z`; a time
    given without a zone is read as UTC."""
    t = datetime.datetime.fromisoformat(str(text).strip().replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=datetime.timezone.utc)
    return t.astimezone(datetime.timezone.utc)


def anchor_of(comment):
    """{"kind": "node"|"canvas"|"none", ...} from a comment's client_meta."""
    cm = comment.get("client_meta")
    if isinstance(cm, dict) and cm.get("node_id"):
        off = cm.get("node_offset") or {}
        return {"kind": "node", "node_id": str(cm["node_id"]),
                "offset": {"x": off.get("x"), "y": off.get("y")}}
    if isinstance(cm, dict) and "x" in cm and "y" in cm:
        return {"kind": "canvas", "x": cm["x"], "y": cm["y"]}
    return {"kind": "none"}


def node_link(key, node_id=None):
    url = f"{WEB}/design/{key}"
    if node_id:
        url += "?node-id=" + urllib.parse.quote(node_id.replace(":", "-"), safe="-;")
    return url


def build_threads(comments):
    """Roots with their replies, newest root first, replies oldest first.

    A root's `parent_id` is the EMPTY STRING, not absent (measured), so a root
    is a comment whose parent_id is falsy. A reply carries no client_meta of its
    own (measured): its anchor is its parent's. A reply whose parent is not in
    the list becomes a thread of its own, marked orphan, with no anchor.
    """
    roots = {c["id"]: c for c in comments if not c.get("parent_id")}
    kids = {}
    for c in comments:
        if c.get("parent_id"):
            kids.setdefault(c["parent_id"], []).append(c)
    threads = []
    for rid, root in roots.items():
        replies = sorted(kids.pop(rid, []), key=lambda c: c.get("created_at", ""))
        threads.append({"root": root, "replies": replies, "anchor": anchor_of(root),
                        "orphan": False})
    for pid, replies in kids.items():
        for c in sorted(replies, key=lambda c: c.get("created_at", "")):
            threads.append({"root": c, "replies": [], "anchor": {"kind": "none"},
                            "orphan": True})
    threads.sort(key=lambda t: t["root"].get("created_at", ""), reverse=True)
    return threads


# --------------------------------------------------------------------------
# Anchor names (a file-content read, cached in the agent's state directory)
# --------------------------------------------------------------------------

def _git_tree(path):
    p = Path(path)
    for d in (p, *p.parents):
        if os.path.lexists(d / ".git"):
            return d
    return None


def agent_home():
    """The calling agent's home: the parent of CLAUDE_CONFIG_DIR, which must be a
    direct child of the host's agents root (the agent skill's home layout)."""
    cfgdir = os.environ.get("CLAUDE_CONFIG_DIR")
    if not cfgdir:
        raise ConfigError("CLAUDE_CONFIG_DIR is unset, so there is no agent home to keep state "
                          "in; pass --state-dir or set FIGMA_STATE_DIR")
    home = Path(os.path.realpath(os.path.expanduser(cfgdir))).parent
    try:
        root = Path(os.path.realpath(os.path.expanduser(_paths.host()["agents_root"])))
    except Exception as e:  # noqa: BLE001
        raise ConfigError(f"the host's agents root cannot be read ({e}); pass --state-dir "
                          f"or set FIGMA_STATE_DIR") from None
    if home.parent != root:
        raise ConfigError(f"{home} is not an agent home (not a direct child of the agents root "
                          f"{root}); pass --state-dir or set FIGMA_STATE_DIR")
    return home


def state_dir(cfg, given=None):
    """Where the cursor and the name cache live: --state-dir, else
    $FIGMA_STATE_DIR, else `state.dir` with {home} (the agent's home) filled in.
    Never inside a git work tree: a cursor in a checkout is a different file in
    every worktree, and one `git add` away from a commit."""
    raw = given or os.environ.get("FIGMA_STATE_DIR")
    if not raw:
        raw = cfg["state"]["dir"]
        if "{home}" in raw:
            raw = raw.replace("{home}", str(agent_home()))
        raw = str(_paths.resolve_config_path(raw, cfg["_path"]))
    d = Path(os.path.realpath(_expand.value(raw)))
    tree = _git_tree(d)
    if tree is not None:
        raise ConfigError(f"the state directory {d} is inside the git work tree {tree}; state "
                          f"lives in the agent's state/ directory, never in a checkout")
    return d


def _read_json(path, default, strict=True):
    """The JSON at PATH, or DEFAULT when it is absent. A file that does not parse
    is a ConfigError naming it (strict), or DEFAULT (a cache, which is re-read)."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except ValueError as e:
        if not strict:
            return default
        raise ConfigError(f"{path} does not parse ({e}). It is state this helper wrote: repair "
                          f"it, or remove it and the next `new` reports every comment as new") from None


def _write_json(path, doc):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _stamp(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def resolve_names(cfg, key, node_ids, sdir, refresh=False, enabled=True):
    """({node_id: {"name", "type", "page", "status"}}, file_name, note, failed).

    status is "ok" (a top-level node of the depth-2 read: name and page),
    "name_only" (found by the nodes read, which returns no ancestors: its page is
    not resolved, whether it is nested or a top-level node newer than the cache),
    "deleted" (the file has no such node) or "unavailable" (no lookup was
    possible; NOTE says why and which scope would supply it). FAILED is True when
    a lookup was tried in this run and failed. A failed lookup never fails the
    listing.

    The cache's `fetched_at` is the time of the last depth-2 read and is never
    moved by an incremental nodes read, so names are re-read at most
    `names.cache_hours` after that read. A scope refusal is cached too, so a token
    without file_content:read costs one Tier 1 call per cache window, not one per
    run; --refresh-names retries at once.
    """
    who = cfg["names"]["token"]

    def unavailable(why, failed=False):
        return {n: {"status": "unavailable"} for n in node_ids}, None, why, failed
    if not enabled:
        return unavailable("name lookup turned off (--no-names)")
    if who is None:
        return unavailable(f"names.token is null; a token with {SCOPE['content']} supplies names")
    cache_file = None if sdir is None else Path(sdir) / f"names-{key}.json"
    cache = _read_json(cache_file, {}, strict=False) if cache_file else {}
    fresh = False
    if cache and not refresh:
        try:
            age = (_now() - parse_time(cache["fetched_at"])).total_seconds() / 3600
            fresh = age <= cfg["names"]["cache_hours"]
        except (KeyError, TypeError, ValueError):
            fresh = False
    if fresh and cache.get("scope_missing"):
        return unavailable(f"{cache['scope_missing']} (cached; --refresh-names retries)")
    nodes = dict(cache.get("nodes") or {}) if fresh else {}
    file_name = cache.get("file_name") if fresh else None
    fetched_at = cache.get("fetched_at") if fresh else None
    wanted = [n for n in node_ids if n not in nodes]
    if not wanted:
        return nodes, file_name, None, False
    try:
        if not fresh:
            # Pages and the top-level nodes on each page, with names: one Tier 1 call.
            doc = api(cfg, who, f"/v1/files/{key}?depth=2", need=SCOPE["content"])
            fetched_at = _stamp(_now())
            file_name = doc.get("name")
            nodes = {}
            for page in (doc.get("document") or {}).get("children") or []:
                for node in page.get("children") or []:
                    nodes[str(node.get("id"))] = {"name": node.get("name"), "type": node.get("type"),
                                                  "page": page.get("name"), "status": "ok"}
            wanted = [n for n in node_ids if n not in nodes]
        if wanted:
            # The rest: a null entry is a node the file does not have.
            doc = api(cfg, who, f"/v1/files/{key}/nodes?ids="
                      + urllib.parse.quote(",".join(wanted), safe=",:;") + "&depth=1",
                      need=SCOPE["content"])
            got = doc.get("nodes") or {}
            for n in wanted:
                entry = got.get(n)
                doc_n = (entry or {}).get("document") if isinstance(entry, dict) else None
                if doc_n:
                    nodes[n] = {"name": doc_n.get("name"), "type": doc_n.get("type"),
                                "page": None, "status": "name_only"}
                else:
                    nodes[n] = {"name": None, "type": None, "page": None, "status": "deleted"}
    except Exception as e:  # noqa: BLE001 - any failure degrades the names, never the listing
        why = f"names unavailable: {scrub(e)}"
        if cache_file is not None and not fresh and isinstance(e, AuthError) and "scope" in str(e):
            try:
                _write_json(cache_file, {"fetched_at": _stamp(_now()), "scope_missing": why,
                                         "nodes": {}, "file_name": None})
            except OSError:
                pass
        out = {n: nodes.get(n, {"status": "unavailable"}) for n in node_ids}
        return out, file_name, why, True
    if cache_file is not None:
        try:
            _write_json(cache_file, {"fetched_at": fetched_at, "file_name": file_name,
                                     "nodes": nodes})
        except OSError as e:
            _warn(f"warning: the name cache {cache_file} was not written ({e.strerror or e})")
    return nodes, file_name, None, False


# --------------------------------------------------------------------------
# Filters, cursor, views
# --------------------------------------------------------------------------

def _author_match(comment, authors):
    u = comment.get("user") or {}
    return any(a.lower() in (str(u.get("handle", "")).lower(), str(u.get("id", "")).lower())
               for a in authors)


def select(threads, names, unresolved=False, since=None, authors=(), anchor=None, unseen=None):
    """Mark every comment's `match` and drop threads with none.

    Thread filters: unresolved, anchor. Comment filters: since, authors, and
    unseen (the cursor's set of ids NOT yet seen). A thread survives when it
    passes the thread filters and at least one of its comments passes the
    comment filters.
    """
    since_t = parse_time(since) if since else None
    kept = []
    for t in threads:
        root = t["root"]
        if unresolved and root.get("resolved_at"):
            continue
        if anchor:
            a = t["anchor"]
            info = names.get(a.get("node_id"), {}) if a["kind"] == "node" else {}
            words = [info.get("name") or "", info.get("page") or ""]
            if anchor != a.get("node_id") and not any(anchor.lower() in w.lower()
                                                      for w in words if w):
                continue
        any_match = False
        for c in [root] + t["replies"]:
            ok = True
            if since_t and parse_time(c["created_at"]) < since_t:
                ok = False
            if authors and not _author_match(c, authors):
                ok = False
            if unseen is not None and c["id"] not in unseen:
                ok = False
            c["_match"] = ok
            any_match = any_match or ok
        if any_match:
            kept.append(t)
    return kept


def cursor_path(sdir, key):
    return Path(sdir) / f"cursor-{key}.json"


def load_cursor(sdir, key):
    doc = _read_json(cursor_path(sdir, key), None)
    if doc is None:
        return {"seen": [], "resolved": [], "updated_at": None}
    return doc


def resolution_changes(comments, cursor):
    """(resolved since last look, reopened since last look) as root ids."""
    was = set(cursor.get("resolved", []))
    seen = set(cursor.get("seen", []))
    now = {c["id"] for c in comments if not c.get("parent_id") and c.get("resolved_at")}
    roots = {c["id"] for c in comments if not c.get("parent_id")}
    return sorted((now - was) & seen), sorted((was - now) & roots)


def advance_cursor(sdir, key, cursor, shown_ids, comments, resolved_shown=True):
    seen = set(cursor.get("seen", [])) | set(shown_ids)
    resolved = {c["id"] for c in comments if not c.get("parent_id") and c.get("resolved_at")}
    doc = {"seen": sorted(seen), "resolved": sorted(resolved if resolved_shown else
                                                    set(cursor.get("resolved", []))),
           "updated_at": _stamp(_now())}
    _write_json(cursor_path(sdir, key), doc)
    return doc


def _who(c):
    u = c.get("user") or {}
    return {"id": u.get("id"), "handle": u.get("handle")}


def _anchor_view(key, anchor, names):
    if anchor["kind"] == "node":
        n = anchor["node_id"]
        info = names.get(n, {"status": "unavailable"})
        return {"kind": "node", "node_id": n, "offset": anchor["offset"],
                "name": info.get("name"), "type": info.get("type"), "page": info.get("page"),
                "status": info.get("status"), "link": node_link(key, n)}
    if anchor["kind"] == "canvas":
        return {"kind": "canvas", "x": anchor["x"], "y": anchor["y"], "link": node_link(key)}
    return {"kind": "none", "link": node_link(key)}


def to_json(key, file_name, threads, names, note, new_ids=()):
    new_ids = set(new_ids)

    def one(c):
        return {"id": c["id"], "created_at": c.get("created_at"), "author": _who(c),
                "message": c.get("message"), "match": c.get("_match", True),
                "new": c["id"] in new_ids}
    out = []
    for t in threads:
        r = t["root"]
        d = one(r)
        d.update({"number": r.get("order_id"), "resolved": bool(r.get("resolved_at")),
                  "resolved_at": r.get("resolved_at"), "orphan": t["orphan"],
                  "parent_id": r.get("parent_id") or None,
                  "anchor": _anchor_view(key, t["anchor"], names),
                  "replies": [one(c) for c in t["replies"]]})
        out.append(d)
    return {"file": {"key": key, "name": file_name}, "names_note": note, "threads": out}


def _short(ts):
    try:
        return parse_time(ts).strftime("%Y-%m-%d %H:%MZ")
    except (TypeError, ValueError):
        return str(ts)


def _where(key, anchor, names, note):
    v = _anchor_view(key, anchor, names)
    if v["kind"] == "canvas":
        return f"canvas position ({v['x']}, {v['y']}), page not recorded  {v['link']}"
    if v["kind"] == "none":
        return f"no anchor  {v['link']}"
    st = v["status"]
    if st == "ok":
        return f"{(v['type'] or 'node').lower()} \"{v['name']}\" on page \"{v['page']}\"  {v['link']}"
    if st == "name_only":
        return f"{(v['type'] or 'node').lower()} \"{v['name']}\" (page not resolved)  {v['link']}"
    if st == "deleted":
        return f"a node that is no longer in the file (deleted)  {v['link']}"
    return f"<name unavailable>  {v['link']}"


def render(key, file_name, threads, names, note, new_ids=(), total=None):
    new_ids = set(new_ids)
    lines = [f"{file_name or key}: {len(threads)} thread(s)"
             + (f" of {total}" if total is not None else "")]
    if note:
        lines.append(f"anchor names: {note}")  # once; each anchor then carries a short marker
    for t in threads:
        r = t["root"]
        state = ("RESOLVED " + _short(r["resolved_at"])) if r.get("resolved_at") else "OPEN"
        num = f"#{r.get('order_id')}" if r.get("order_id") else "#-"
        tag = "  NEW" if r["id"] in new_ids else ""
        ctx = "" if r.get("_match", True) else "  (context)"
        lines.append(f"{num} {state}  {_short(r.get('created_at'))}  "
                     f"{_who(r)['handle']}  [id {r['id']}]{tag}{ctx}")
        if t["orphan"]:
            lines.append("    reply to a comment that is not in the list (orphan)")
        else:
            lines.append("    on: " + _where(key, t["anchor"], names, note))
        lines += ["    | " + ln for ln in str(r.get("message", "")).split("\n")]
        for c in t["replies"]:
            if not c.get("_match", True):
                continue
            tag = "  NEW" if c["id"] in new_ids else ""
            lines.append(f"  reply  {_short(c.get('created_at'))}  {_who(c)['handle']}  "
                         f"[id {c['id']}]{tag}")
            lines += ["      | " + ln for ln in str(c.get("message", "")).split("\n")]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Verbs
# --------------------------------------------------------------------------

def _emit(text):
    """Print TEXT to stdout, scrubbed: comment text is Figma's, and a token pasted
    into a comment must not be printed back. False when stdout is closed (the
    reader went away); stdout is then pointed at the null device, so the
    interpreter's own flush at exit cannot fail a second time."""
    try:
        print(scrub(text))
        sys.stdout.flush()
        return True
    except BrokenPipeError:
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        except (OSError, ValueError, AttributeError):
            pass  # not a real file descriptor (a test's stream): nothing left to flush
        return False


def _warn(text):
    """A line on stderr that cannot raise: a warning never changes an outcome."""
    try:
        print(scrub(text), file=sys.stderr)
    except Exception:  # noqa: BLE001
        pass


def _names_for(cfg, key, threads, args, sdir):
    ids = sorted({t["anchor"]["node_id"] for t in threads if t["anchor"]["kind"] == "node"})
    if not ids:
        return {}, None, None, False
    return resolve_names(cfg, key, ids, sdir, refresh=args.refresh_names,
                         enabled=not args.no_names)


def _sdir_or_none(cfg, args):
    try:
        return state_dir(cfg, args.state_dir)
    except ConfigError as e:
        if cfg["names"]["token"] and not args.no_names:
            _warn(f"warning: no name cache ({e}); every run repeats the name lookup")
        return None


def cmd_list(cfg, args):
    key, _alias = file_key(cfg, args.file)
    comments = fetch_comments(cfg, key)
    threads = build_threads(comments)
    sdir = _sdir_or_none(cfg, args)
    names, fname, note, failed = _names_for(cfg, key, threads, args, sdir)
    kept = select(threads, names, args.unresolved, args.since, args.author or (), args.anchor)
    if failed:
        _warn(f"warning: {note}")  # a lookup was tried in this run and failed
    if args.json:
        _emit(json.dumps(to_json(key, fname, kept, names, note), indent=1))
    else:
        _emit(render(key, fname, kept, names, note, total=len(threads)))
    return 0


def cmd_new(cfg, args):
    key, _alias = file_key(cfg, args.file)
    sdir = state_dir(cfg, args.state_dir)
    cursor = load_cursor(sdir, key)
    comments = fetch_comments(cfg, key)
    threads = build_threads(comments)
    unseen = {c["id"] for c in comments} - set(cursor.get("seen", []))
    names, fname, note, failed = _names_for(cfg, key, threads, args, sdir)
    kept = select(threads, names, args.unresolved, args.since, args.author or (), args.anchor,
                  unseen=unseen)
    shown = [c["id"] for t in kept for c in [t["root"]] + t["replies"] if c.get("_match")]
    resolved, reopened = resolution_changes(comments, cursor)
    filtered = bool(args.unresolved or args.since or args.author or args.anchor)
    if failed:
        _warn(f"warning: {note}")  # a lookup was tried in this run and failed
    path = str(cursor_path(sdir, key))
    if args.json:
        doc = to_json(key, fname, kept, names, note, new_ids=shown)
        doc.update({"resolved_since_last": resolved, "reopened_since_last": reopened,
                    "cursor": {"path": path, "advanced": not args.peek,
                               "first_look": cursor.get("updated_at") is None}})
        text = json.dumps(doc, indent=1)
    else:
        first = " (first look: everything is new)" if cursor.get("updated_at") is None else ""
        lines = [f"new since {cursor.get('updated_at') or 'never'}{first}; cursor {path}"
                 + ("" if not args.peek else " (peek: not advanced)"),
                 render(key, fname, kept, names, note, new_ids=shown)]
        by_id = {c["id"]: c for c in comments}
        for label, ids in (("resolved since last look", resolved),
                           ("reopened since last look", reopened)):
            for i in ids:
                c = by_id[i]
                lines.append(f"{label}: #{c.get('order_id') or '-'} [id {i}] by {_who(c)['handle']}")
        text = "\n".join(lines)
    # The cursor advances only once the output was written: a reader that went
    # away has not seen these comments, so they stay new.
    if not _emit(text):
        _warn("warning: stdout was closed before the output was written; the cursor was not "
              "advanced")
        return 1
    if not args.peek:
        # With a filter, only what was shown is marked seen, so a filtered run
        # never swallows comments it did not display. Resolution changes are
        # advanced only by an unfiltered run, for the same reason.
        advance_cursor(sdir, key, cursor, shown, comments, resolved_shown=not filtered)
    return 0


def _message(args):
    if args.message is not None:
        text = args.message
    elif args.message_file:
        with open(args.message_file, encoding="utf-8") as f:
            text = f.read()
    else:
        text = sys.stdin.read()
    text = text.rstrip("\n")
    if not text.strip():
        raise ConfigError("the message is empty")
    return text


def _prefixed(cfg, text):
    prefix = cfg["post"]["prefix"]
    if not prefix:
        return text
    if "{agent}" in prefix or "{Agent}" in prefix:
        name = agent_home().name
        prefix = prefix.replace("{agent}", name).replace("{Agent}", name[:1].upper() + name[1:])
    return text if text.startswith(prefix) else prefix + text


def _write(cfg, args, key, body):
    read_token(cfg, "write")  # refuses on a read-only install before anything is built
    path = f"/v1/files/{key}/comments"
    if args.dry_run:
        _emit(json.dumps({"method": "POST", "url": API + path, "body": body}, indent=1))
        return 0
    try:
        made = api(cfg, "write", path, method="POST", body=body)
    except ApiError as e:
        if e.maybe_sent:
            raise WriteUnknown(f"{e}. The comment may have been posted: read the thread (list or "
                               f"new) before retrying, or a retry posts it twice under the token "
                               f"owner's name") from None
        raise
    # POSTED. Every path from here returns 0: an exit that says "not posted"
    # after a post is how a retry posts it a second time under a person's name.
    try:
        if not isinstance(made, dict):
            made = {"_unparsed": True}  # valid JSON that is not an object: no id to read
        cid = made.get("id")
        shown = _emit(json.dumps(made, indent=1) if args.json
                      else f"posted comment {cid or '(id unknown)'}")
        if made.get("_unparsed"):
            _warn("warning: the post succeeded but its response is not a comment object, so its "
                  "id is unknown")
        if not shown:
            _warn(f"warning: stdout is closed; the comment WAS posted (id {cid or 'unknown'})")
        sdir = state_dir(cfg, args.state_dir)
        cur = load_cursor(sdir, key)
        if cur.get("updated_at") is not None and cid:
            cur["seen"] = sorted(set(cur.get("seen", [])) | {cid})
            _write_json(cursor_path(sdir, key), cur)
    except Exception as e:  # noqa: BLE001 - the post stands; output and cursor are conveniences
        _warn(f"warning: posted, but the cursor was not updated ({type(e).__name__}: {e}); the "
              f"next `new` reports this comment as new")
    return 0


def cmd_reply(cfg, args):
    key, _alias = file_key(cfg, args.file)
    read_token(cfg, "write")
    by_id = {c["id"]: c for c in fetch_comments(cfg, key)}
    target = by_id.get(args.comment_id)
    if target is None:
        raise ApiError(f"no comment {args.comment_id} on file {key}")
    root = target["id"]
    if target.get("parent_id"):
        # Figma accepts a reply only to a ROOT comment; a reply's thread is its parent's.
        root = target["parent_id"]
        _warn(f"note: {args.comment_id} is a reply; replying in its thread, to root {root}")
    return _write(cfg, args, key, {"message": _prefixed(cfg, _message(args)), "comment_id": root})


def cmd_post(cfg, args):
    key, _alias = file_key(cfg, args.file)
    read_token(cfg, "write")
    try:
        x, y = (float(v) for v in (args.offset or "0,0").split(","))
    except ValueError:
        raise ConfigError("--offset is X,Y in the frame's own coordinates, e.g. 120,40") from None
    body = {"message": _prefixed(cfg, _message(args)),
            "client_meta": {"node_id": args.node, "node_offset": {"x": x, "y": y}}}
    return _write(cfg, args, key, body)


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", help="config.json (default: the install context's, or "
                        "$FIGMA_WORKSPACE_CONFIG)")
    common.add_argument("--file", help="an alias from config.json, a file key, or a Figma URL")
    common.add_argument("--json", action="store_true", help="machine-readable output")
    common.add_argument("--state-dir", help="where the cursor and name cache live (default: "
                        "state.dir under the calling agent's home, or $FIGMA_STATE_DIR)")
    reading = argparse.ArgumentParser(add_help=False)
    reading.add_argument("--unresolved", action="store_true", help="open threads only")
    reading.add_argument("--since", help="comments created at or after this ISO time (UTC "
                         "when no zone is given)")
    reading.add_argument("--author", action="append", help="a user handle or id; repeatable")
    reading.add_argument("--anchor", help="a node id, or part of a frame or page name")
    reading.add_argument("--no-names", action="store_true", help="skip the anchor-name lookup")
    reading.add_argument("--refresh-names", action="store_true", help="ignore the name cache")
    writing = argparse.ArgumentParser(add_help=False)
    msg = writing.add_mutually_exclusive_group()
    msg.add_argument("--message", help="the text (default: read from stdin)")
    msg.add_argument("--message-file", help="read the text from this file")
    writing.add_argument("--dry-run", action="store_true", help="print the request, send nothing")

    p = argparse.ArgumentParser(prog="figma_comments.py", description="Figma file comments.")
    sub = p.add_subparsers(dest="verb", required=True)
    sub.add_parser("list", parents=[common, reading], help="every thread, filtered")
    n = sub.add_parser("new", parents=[common, reading], help="what is new since the cursor")
    n.add_argument("--peek", action="store_true", help="show, but do not advance the cursor")
    r = sub.add_parser("reply", parents=[common, writing], help="reply in a thread")
    r.add_argument("comment_id")
    po = sub.add_parser("post", parents=[common, writing], help="a new comment pinned to a node")
    po.add_argument("--node", required=True, help="the node (frame) id to pin it to")
    po.add_argument("--offset", help="X,Y inside the node, from its top-left corner (default 0,0)")
    return p


VERBS = {"list": cmd_list, "new": cmd_new, "reply": cmd_reply, "post": cmd_post}


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
        return VERBS[args.verb](cfg, args)
    except (ConfigError, CredentialError, AuthError, ApiError, WriteUnknown) as e:
        _warn(f"{type(e).__name__}: {e}")
        return e.exit_code
    except Exception as e:  # noqa: BLE001 - never a traceback: one could quote a token
        # Nothing was posted when this is reached: every API failure is an
        # ApiError, a write that may have landed is WriteUnknown, and once a POST
        # has succeeded _write returns 0 on every path, catching all after it.
        _warn(f"Error: {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
