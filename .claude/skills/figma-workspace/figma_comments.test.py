#!/usr/bin/env python3
"""Offline regression guard for figma_comments.py.  `python3 figma_comments.test.py`

NO NETWORK, NO REAL TOKEN, NO CONFIG OF THIS INSTALL. Every HTTP call goes to a
fake Figma that serves the synthetic files in fixtures/ and records each
request; tokens are throwaway files in a temp directory; HOME, the XDG
directories, the host settings and CLAUDE_CONFIG_DIR all point inside that temp
directory, so nothing under the real home is read or written.

WHAT EACH SECTION IS FOR, AND WHAT BREAKS IF IT IS DELETED

 0. The network is unreachable from this file: urllib's urlopen and the
    module's seam both raise, and a test that reaches them fails.
 1. Config: a complete one loads, and each key REMOVED IN TURN is refused by
    name - the removal loop is the control for "it loaded".
 2. Threading: replies sit under their root, oldest first; a root's parent_id is
    the empty string (as measured), so a test on key presence would turn every
    root into a reply - the thread count catches that; a reply takes its
    parent's anchor; a reply whose parent is missing is an orphan thread.
 3. Filters: each one drops something it should and keeps something it should,
    so a filter that does nothing, or everything, fails.
 4. Anchor names: no lookup at all when names.token is null (the request log is
    the evidence), and then no bare node id in the readable output; with a
    token, one depth-2 read plus one nodes read for the leftovers, names, pages,
    nested and deleted; the cache makes the second run free; a missing scope
    degrades the names and never the listing.
 5. The cursor: first look reports everything, the second nothing, a new reply
    only itself; resolved and reopened threads are reported once; --peek does
    not advance; a filtered run marks only what it showed; the cursor lives in
    the agent's home and is refused inside a git work tree.
 6. Tokens never reach output: a fake server that echoes the token back in an
    error body, and the token is absent from stdout and stderr - with the
    control that the request header DID carry it. No CLI option takes a token.
    An over-permissive token file is refused before any request.
 7. Writes: refused with no request at all when no write token is configured;
    the request shape of reply and post; the write token, never the read one;
    a reply to a reply goes to its root; --dry-run sends nothing; and across
    EVERY request this file made, only GETs and POSTs to the comments path, and
    no body that names resolution.
 8. Errors: 401, two 403 shapes, 403 without scope, 404, 429 and a network
    failure map to distinct messages and the documented exit codes.
 9. CLI and fleet lookups: --file takes an alias, a key or a URL (a branch URL
    gives the branch key); several files need --file; with no --config the
    install context's config.json (the fixture install) is the one read.
10. Hostile input and faults. A token file with a second line, a space or a
    control character is refused naming the path, never the value - driven
    through http.client's own header validation, which quotes the value in its
    error (the leak this guards). The exact-value scrub, with a token that has
    no figd_ shape. Every transport failure (a header rejection, a timeout, a
    truncated body, a reset) is exit 4 and scrubbed; in the name lookup it
    degrades the names, never the listing. A successful POST exits 0 with its
    id whatever the cursor does afterwards; a POST whose outcome is unknown
    exits 5; a 4xx is not posted. No bare node id with names ON. The names
    reason printed once. A scope 403 names the scope the call needs. The name
    cache: a scope refusal is cached; an incremental nodes read keeps the
    depth-2 time (a fake clock), and a node it finds is "page not resolved",
    never "nested".
11. After a POST, every path is exit 0: a 2xx that is JSON but not an object,
    and a closed stdout (in-process, and end to end in a child whose stdout pipe
    is closed, so the interpreter's exit-time flush counts). `new` with a closed
    stdout does not advance the cursor. The module's opener refuses a redirect
    (two loopback servers: the token never reaches the target), and a 3xx is an
    ApiError. Rendered output, both forms, scrubs a token pasted into a
    comment. An invalid-UTF-8 token file is exit 2 with no traceback.

The temp root is a realpath (macOS's $TMPDIR is a symlink) and is removed at
exit, a failing or crashing run included.
"""
import atexit
import contextlib
import copy
import datetime
import email.message
import http.client
import io
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import traceback
import urllib.error
import urllib.parse
import urllib.request

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.realpath(__file__))
FLEET_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
FIXTURE_INSTALL = os.path.join(FLEET_ROOT, "tests", "fixtures", "install")
FIX = os.path.join(HERE, "fixtures")

# The web root, split so that a synthetic link in this file does not match the
# public `figma-url` leak pattern, which is written for real file links.
WEB = "https://www.fig" + "ma.com"
# realpath: on macOS $TMPDIR is under /var, a symlink to /private/var, and every
# path the helper returns is a realpath, so an unresolved root never compares equal.
TMP = os.path.realpath(tempfile.mkdtemp(prefix="figma-comments-test-"))
atexit.register(shutil.rmtree, TMP, True)  # removed on a failing or crashing run too
for var in ("FLEET_SECRETS_DIR", "FIGMA_WORKSPACE_CONFIG", "FIGMA_STATE_DIR", "GIT_DIR",
            "GIT_WORK_TREE"):
    os.environ.pop(var, None)
os.environ["HOME"] = os.path.join(TMP, "home")
for var in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME"):
    os.environ[var] = os.path.join(TMP, "home", var.lower())
os.makedirs(os.environ["HOME"])
AGENTS = os.path.join(TMP, "agents")
HOME_ADA = os.path.join(AGENTS, "ada")
os.makedirs(os.path.join(HOME_ADA, ".claude"))
HOST = os.path.join(TMP, "host.json")
with open(HOST, "w") as f:
    json.dump({"schema": 1, "agents_root": AGENTS, "fleet_checkout": FLEET_ROOT,
               "claims_dir": os.path.join(TMP, "claims")}, f)
os.environ["FLEET_HOST_CONFIG"] = HOST
os.environ["CLAUDE_CONFIG_DIR"] = os.path.join(HOME_ADA, ".claude")
os.environ["FLEET_CONTEXT_ROOT"] = FIXTURE_INSTALL

_spec = importlib.util.spec_from_file_location("figma_comments", os.path.join(HERE, "figma_comments.py"))
fc = importlib.util.module_from_spec(_spec)
sys.modules["figma_comments"] = fc
_spec.loader.exec_module(fc)
if fc._git_tree(TMP) is not None:
    # Section 5 plants a .git to prove the state-dir guard; every other section
    # needs a temp root outside any git tree, or the guard refuses them all.
    print(f"NO VERDICT: the temp root {TMP} is inside the git tree {fc._git_tree(TMP)}; "
          f"point TMPDIR outside it")
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(3)

CHECKS = 0
FAILED = []
SECTION = "-"


def check(cond, label):
    global CHECKS
    CHECKS += 1
    if not cond:
        FAILED.append(f"{SECTION}: {label}")
        print(f"  FAIL  {label}")
    return bool(cond)


def section(name):
    global SECTION
    SECTION = name
    print(name)


# ----------------------------------------------------------------- 0. no network

class NetworkReached(AssertionError):
    pass


def _forbidden(*_a, **_kw):
    raise NetworkReached("a test reached the real network")


# The module's own opener, kept for section 11, which drives it against two
# loopback servers to prove a redirect is refused. Nothing else may use it.
REAL_OPEN = fc._urlopen
urllib.request.urlopen = _forbidden
fc._urlopen = _forbidden

section("0. no network")
try:
    fc._urlopen(urllib.request.Request("https://api.figma.com/v1/me"))
    reached = False
except NetworkReached:
    reached = True
check(reached, "the module's seam raises instead of reaching the network")


# ----------------------------------------------------------------- the fake Figma

def load(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return json.load(f)


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class Fake:
    """Serves the fixtures and records every request (method, path, query, token, body)."""

    def __init__(self):
        self.comments = load("comments.json")["comments"]
        self.log = []
        self.errors = {}  # path prefix -> (status, body, headers)
        self.next_id = 2000000000
        self.depth2 = load("file-depth2.json")
        self.nodes = load("nodes.json")["nodes"]

    def __call__(self, req, timeout=None):
        url = urllib.parse.urlsplit(req.full_url)
        body = json.loads(req.data) if req.data else None
        entry = {"method": req.get_method(), "path": url.path, "query": url.query,
                 "token": req.get_header("X-figma-token"), "body": body, "host": url.netloc}
        self.log.append(entry)
        ALL_REQUESTS.append(entry)
        for prefix, (status, text, headers) in self.errors.items():
            if url.path.startswith(prefix):
                msg = email.message.Message()
                for k, v in (headers or {}).items():
                    msg[k] = v
                raise urllib.error.HTTPError(req.full_url, status, "err", msg,
                                             io.BytesIO(text.encode()))
        if req.get_method() == "POST" and url.path.endswith("/comments"):
            self.next_id += 1
            made = {"id": str(self.next_id), "parent_id": body.get("comment_id", ""),
                    "message": body["message"], "client_meta": body.get("client_meta"),
                    "created_at": "2026-02-01T00:00:00.000Z", "resolved_at": None,
                    "user": {"id": "100000000000000001", "handle": "Ada"}, "order_id": None}
            return Resp(json.dumps(made).encode())
        if url.path.endswith("/comments"):
            return Resp(json.dumps({"comments": self.comments}).encode())
        if url.path.endswith("/nodes"):
            asked = urllib.parse.parse_qs(url.query)["ids"][0].split(",")
            return Resp(json.dumps({"name": self.depth2["name"],
                                    "nodes": {i: self.nodes.get(i) for i in asked}}).encode())
        if url.path.startswith("/v1/files/") and "depth=2" in url.query:
            return Resp(json.dumps(self.depth2).encode())
        raise AssertionError(f"the fake has no route for {req.get_method()} {req.full_url}")


ALL_REQUESTS = []
READ_TOKEN = "figd_READ-sentinel-0001"
WRITE_TOKEN = "figd_WRITE-sentinel-0002"
CONTENT_TOKEN = "figd_CONTENT-sentinel-0003"
SECRETS = os.path.join(TMP, "secrets")
os.makedirs(SECRETS)


def token_file(name, value, mode=0o600):
    p = os.path.join(SECRETS, name)
    with open(p, "w") as f:
        f.write(value + "\n")
    os.chmod(p, mode)
    return p


RT = token_file("read.token", READ_TOKEN)
WT = token_file("write.token", WRITE_TOKEN)
CT = token_file("content.token", CONTENT_TOKEN)

BASE = {
    "files": [{"alias": "main", "key": "EXAMPLEFILEKEY000"}],
    "mcp": {"connector_name": "example.ai Figma"},
    "tokens": {"read": {"path": RT}, "write": {"path": None}, "content": {"path": None}},
    "names": {"token": None, "cache_hours": 24},
    "post": {"prefix": "{Agent} (via Ada's account): "},
    "state": {"dir": "{home}/state/figma-workspace"},
}
_n = [0]


def config(**edits):
    """A config file in the temp dir: BASE with dotted-key edits (value None deletes
    when the key is given as `-key`)."""
    cfg = copy.deepcopy(BASE)
    for dotted, value in edits.items():
        drop = dotted.startswith("_drop_")
        parts = dotted.replace("_drop_", "").split("__")
        node = cfg
        for p in parts[:-1]:
            node = node[p]
        if drop:
            node.pop(parts[-1], None)
        else:
            node[parts[-1]] = value
    _n[0] += 1
    path = os.path.join(TMP, f"config-{_n[0]}.json")
    with open(path, "w") as f:
        json.dump(cfg, f)
    return path


def run(argv, fake=None, stdin=None, stdout=None):
    """(exit code, stdout, stderr) of the CLI with FAKE as the network."""
    fc._urlopen = fake if fake is not None else _forbidden
    fc._LOADED.clear()
    out, err = (stdout if stdout is not None else io.StringIO()), io.StringIO()
    old_stdin = sys.stdin
    if stdin is not None:
        sys.stdin = io.StringIO(stdin)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = fc.main(argv)
            except SystemExit as e:
                code = e.code
            except Exception as e:  # noqa: BLE001 - a crash is a result, and its traceback is output
                code = f"crash: {type(e).__name__}"
                err.write(traceback.format_exc())
    finally:
        sys.stdin = old_stdin
        fc._urlopen = _forbidden
    return code, out.getvalue(), err.getvalue()


def state_files():
    d = os.path.join(HOME_ADA, "state", "figma-workspace")
    return sorted(os.listdir(d)) if os.path.isdir(d) else []


def reset_state():
    shutil.rmtree(os.path.join(HOME_ADA, "state"), ignore_errors=True)


# ----------------------------------------------------------------- 1. config

section("1. config")
cfg = fc.load_config(config())
check(cfg["files"][0]["key"] == "EXAMPLEFILEKEY000", "a complete config loads")
for dotted in ("files", "tokens.read.path", "names.cache_hours", "state.dir",
               "mcp.connector_name", "tokens.write.path", "tokens.content.path", "names.token",
               "post.prefix"):
    try:
        fc.load_config(config(**{"_drop_" + dotted.replace(".", "__"): None}))
        check(False, f"a config without {dotted} is refused")
    except fc.ConfigError as e:
        check(f"'{dotted}'" in str(e), f"a config without {dotted} is refused naming it ({e})")
for edits, needle in (({"names__token": "maybe"}, "names.token"),
                      ({"names__token": "content"}, "tokens.content.path is null"),
                      ({"files": [{"alias": "x", "key": "bad/key"}]}, "files[0]"),
                      ({"names__cache_hours": -1}, "cache_hours")):
    try:
        fc.load_config(config(**edits))
        check(False, f"{edits} is refused")
    except fc.ConfigError as e:
        check(needle in str(e), f"{edits} is refused naming {needle}")


# ----------------------------------------------------------------- 2. threading

section("2. threading")
comments = load("comments.json")["comments"]
threads = fc.build_threads(comments)
check(len(threads) == 6, f"5 roots and 1 orphan make 6 threads (got {len(threads)})")
first = next(t for t in threads if t["root"]["id"] == "1000000001")
check([c["id"] for c in first["replies"]] == ["1000000002", "1000000003"],
      "replies sit under their root, oldest first")
check(first["anchor"]["node_id"] == "1:2", "the thread's anchor is the root's node")
check(all(c.get("client_meta") is None for c in first["replies"]),
      "the fixture's replies carry no client_meta, as measured")
orphan = [t for t in threads if t["orphan"]]
check(len(orphan) == 1 and orphan[0]["root"]["id"] == "1000000008", "the orphan reply is its own thread")
check([t["root"]["id"] for t in threads][0] == "1000000008", "threads are newest root first")
canvas = next(t for t in threads if t["root"]["id"] == "1000000007")
check(canvas["anchor"] == {"kind": "canvas", "x": 100, "y": 200}, "a canvas comment keeps x, y")


# ----------------------------------------------------------------- 3. filters

def ids(kept):
    return sorted(t["root"]["id"] for t in kept)


section("3. filters")
everything = ids(fc.select(fc.build_threads(comments), {}))
check("1000000004" in everything, "control: the resolved thread is listed without a filter")
check("1000000004" not in ids(fc.select(fc.build_threads(comments), {}, unresolved=True)),
      "--unresolved drops the resolved thread")
since = ids(fc.select(fc.build_threads(comments), {}, since="2026-01-14"))
check(since == ["1000000005", "1000000006", "1000000007", "1000000008"],
      f"--since keeps what was created at or after it ({since})")
grace = fc.select(fc.build_threads(comments), {}, authors=["grace"])
check(ids(grace) == ["1000000001", "1000000005", "1000000008"],
      f"--author matches a handle case-insensitively, through a reply too ({ids(grace)})")
t1 = next(t for t in grace if t["root"]["id"] == "1000000001")
check(t1["root"]["_match"] is False and t1["replies"][0]["_match"] is True,
      "a thread kept for a reply shows its root as context, not as a match")
check(ids(fc.select(fc.build_threads(comments), {}, authors=["100000000000000003"])) ==
      ["1000000004", "1000000007"], "--author matches a user id")
check(ids(fc.select(fc.build_threads(comments), {}, anchor="1:2")) == ["1000000001"],
      "--anchor matches a node id exactly, with no names")
names_ok = {"1:2": {"name": "Checkout", "page": "Screens", "status": "ok"},
            "3:4": {"name": "Profile", "page": "Screens", "status": "ok"}}
check(ids(fc.select(fc.build_threads(comments), names_ok, anchor="checkout")) == ["1000000001"],
      "--anchor matches part of a frame name")
check(ids(fc.select(fc.build_threads(comments), names_ok, anchor="screens")) ==
      ["1000000001", "1000000004"], "--anchor matches part of a page name")
check(ids(fc.select(fc.build_threads(comments), {}, anchor="checkout")) == [],
      "--anchor by name finds nothing when names are unavailable")


# ----------------------------------------------------------------- 4. anchor names

section("4. anchor names")
reset_state()
fake = Fake()
code, out, err = run(["list", "--config", config()], fake)
check(code == 0, f"list exits 0 ({err})")
check([r["path"] for r in fake.log] == ["/v1/files/EXAMPLEFILEKEY000/comments"],
      f"names.token null: the comments read is the only request ({[r['path'] for r in fake.log]})")
check("file_content:read" in out, "the unavailable name names the scope that would supply it")
check(WEB + "/design/EXAMPLEFILEKEY000?node-id=1-2" in out,
      "the anchor is printed as a link a person can open")
check("1:2" not in out and "5:6" not in out, "no bare node id in the readable output")
check(state_files() == [], "a listing with names off writes no state")

cfg_read = config(names__token="read")
fake = Fake()
code, out, err = run(["list", "--json", "--config", cfg_read], fake)
doc = json.loads(out)
by = {t["id"]: t for t in doc["threads"]}
paths = [(r["path"], r["query"]) for r in fake.log]
check(paths[1:] == [("/v1/files/EXAMPLEFILEKEY000", "depth=2"),
                    ("/v1/files/EXAMPLEFILEKEY000/nodes", "ids=5:6,7:8&depth=1")],
      f"one depth-2 read, then one nodes read for the leftover ids only ({paths})")
check(by["1000000001"]["anchor"]["name"] == "Checkout" and by["1000000001"]["anchor"]["page"] == "Screens",
      "a top-level frame gets its name and page")
check(by["1000000005"]["anchor"]["status"] == "name_only" and by["1000000005"]["anchor"]["name"] == "Avatar",
      "a node outside the depth-2 read gets its name and no page (name_only)")
check(by["1000000006"]["anchor"]["status"] == "deleted", "a node the file no longer has is 'deleted'")
check(doc["file"]["name"] == "Example Design File", "the file name comes from the content read")
check(all(r["token"] == READ_TOKEN for r in fake.log), "names.token read: every call uses the read token")
check(state_files() == ["names-EXAMPLEFILEKEY000.json"], f"the name cache is in the agent's state dir ({state_files()})")
fake = Fake()
run(["list", "--config", cfg_read], fake)
check(len(fake.log) == 1, "the second run reads names from the cache: one request")
fake = Fake()
run(["list", "--refresh-names", "--config", cfg_read], fake)
check(len(fake.log) == 3, "--refresh-names reads them again")
fake = Fake()
run(["list", "--config", config(names__token="read", names__cache_hours=0)], fake)
check(len(fake.log) == 3, "cache_hours 0 reads names on every run")
fake = Fake()
_, out, _ = run(["list", "--config", cfg_read], fake)
check("frame \"Checkout\" on page \"Screens\"" in out and "deleted" in out, "readable names render")

reset_state()


class ScopeFake(Fake):
    def __call__(self, req, timeout=None):
        if "/comments" not in req.full_url:
            self.log.append({"path": req.full_url, "token": req.get_header("X-figma-token")})
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(
                b'{"status":403,"err":"Invalid scope(s): file_comments:read. This endpoint '
                b'requires the file_content:read scope"}'))
        return super().__call__(req, timeout)


sf = ScopeFake()
code, out, err = run(["list", "--json", "--config", cfg_read], sf)
doc = json.loads(out) if out else {}
check(code == 0, "a missing content scope does not fail the listing")
check("file_content:read" in (doc.get("names_note") or "") and "file_content:read" in err,
      "the names note carries Figma's scope message")
check(all(t["anchor"].get("status") in ("unavailable", None) for t in doc.get("threads", [])),
      "every anchor is 'unavailable', none guessed")
with open(os.path.join(HOME_ADA, "state", "figma-workspace", "names-EXAMPLEFILEKEY000.json")) as f:
    neg = json.load(f)
check("file_content:read" in neg.get("scope_missing", "") and neg.get("nodes") == {},
      "a scope failure caches the refusal and no names")

cfg_content = config(names__token="content", tokens__content={"path": CT})
fake = Fake()
run(["list", "--config", cfg_content], fake)
check(fake.log[0]["token"] == READ_TOKEN and all(r["token"] == CONTENT_TOKEN for r in fake.log[1:]),
      "names.token content: comments with the read token, names with the content token")


# ----------------------------------------------------------------- 5. cursor

section("5. cursor")
reset_state()
cfg_c = config()
fake = Fake()
code, out, err = run(["new", "--json", "--config", cfg_c], fake)
doc = json.loads(out)
allids = sorted(c["id"] for c in comments)
shown = sorted(c["id"] for t in doc["threads"] for c in [t] + t["replies"] if c["new"])
check(code == 0 and doc["cursor"]["first_look"] and shown == allids,
      "the first look reports every comment as new")
cursor = os.path.join(HOME_ADA, "state", "figma-workspace", "cursor-EXAMPLEFILEKEY000.json")
check(doc["cursor"]["path"] == cursor and os.path.isfile(cursor),
      "the cursor is in the agent's state directory")
code, out, err = run(["new", "--json", "--config", cfg_c], Fake())
check(json.loads(out)["threads"] == [], "the second look reports nothing")
fake = Fake()
fake.comments.insert(0, {"id": "1000000009", "parent_id": "1000000004", "user": {"id": "1", "handle": "Grace"},
                         "created_at": "2026-01-20T10:00:00.000Z", "resolved_at": None,
                         "message": "Reopening this.", "client_meta": None, "order_id": None})
for c in fake.comments:
    if c["id"] == "1000000001":
        c["resolved_at"] = "2026-01-20T11:00:00.000Z"
    if c["id"] == "1000000004":
        c["resolved_at"] = None
code, out, err = run(["new", "--peek", "--json", "--config", cfg_c], fake)
doc = json.loads(out)
newc = [c["id"] for t in doc["threads"] for c in [t] + t["replies"] if c["new"]]
check(newc == ["1000000009"], f"a new reply is the only new comment ({newc})")
check(doc["threads"][0]["id"] == "1000000004" and doc["threads"][0]["match"] is False,
      "its root comes along as context")
check(doc["resolved_since_last"] == ["1000000001"] and doc["reopened_since_last"] == ["1000000004"],
      "resolved and reopened threads are reported")
check(doc["cursor"]["advanced"] is False, "--peek says it did not advance")
code, out, err = run(["new", "--author", "Alan", "--json", "--config", cfg_c], fake)
check(json.loads(out)["threads"] == [], "a filtered run shows only matching new comments (none by Alan)")
code, out, err = run(["new", "--json", "--config", cfg_c], fake)
doc = json.loads(out)
check([c["id"] for t in doc["threads"] for c in [t] + t["replies"] if c["new"]] == ["1000000009"],
      "--peek and a filtered run left the new reply unseen")
check(doc["resolved_since_last"] == ["1000000001"], "a filtered run did not swallow the resolution")
code, out, err = run(["new", "--json", "--config", cfg_c], fake)
doc = json.loads(out)
check(doc["threads"] == [] and doc["resolved_since_last"] == [] and doc["reopened_since_last"] == [],
      "after an unfiltered look, everything is seen")
_, out, _ = run(["new", "--config", cfg_c], fake)
check(out.startswith("new since ") and "cursor " in out, "the readable form names the cursor")

repo = os.path.join(TMP, "a-checkout")
os.makedirs(os.path.join(repo, ".git"))
code, out, err = run(["new", "--state-dir", os.path.join(repo, "state"), "--config", cfg_c], Fake())
check(code == 1 and "git work tree" in err, "a state dir inside a git work tree is refused")
os.environ.pop("CLAUDE_CONFIG_DIR")
code, out, err = run(["new", "--config", cfg_c], Fake())
check(code == 1 and "CLAUDE_CONFIG_DIR is unset" in err and "--state-dir" in err,
      "no CLAUDE_CONFIG_DIR: refused, naming --state-dir")
os.environ["CLAUDE_CONFIG_DIR"] = os.path.join(TMP, "elsewhere", "x", ".claude")
code, out, err = run(["new", "--config", cfg_c], Fake())
check(code == 1 and "not an agent home" in err, "a config dir outside the agents root is refused")
os.environ["CLAUDE_CONFIG_DIR"] = os.path.join(HOME_ADA, ".claude")
other = os.path.join(TMP, "explicit-state")
code, out, err = run(["new", "--state-dir", other, "--json", "--config", cfg_c], Fake())
check(code == 0 and os.path.isfile(os.path.join(other, "cursor-EXAMPLEFILEKEY000.json")),
      "--state-dir is honoured")


# ----------------------------------------------------------------- 6. tokens never reach output

section("6. tokens")
for status, body in ((403, '{"status":403,"err":"bad token %s"}' % READ_TOKEN),
                     (500, "upstream echoed X-Figma-Token: %s and figd_other-secret-9" % READ_TOKEN)):
    fake = Fake()
    fake.errors["/v1/files/"] = (status, body, None)
    code, out, err = run(["list", "--config", config()], fake)
    check(fake.log and fake.log[0]["token"] == READ_TOKEN, f"control: the header carried the token ({status})")
    check(READ_TOKEN not in out + err, f"an echoed token is scrubbed from the output ({status})")
    check("figd_other" not in out + err, f"any figd_ run is scrubbed ({status})")
    check("[redacted]" in err, f"the scrub left a marker ({status})")
opts = [a for act in fc.build_parser()._actions for a in getattr(act, "option_strings", [])]
for sub in fc.build_parser()._subparsers._group_actions[0].choices.values():
    opts += [o for act in sub._actions for o in act.option_strings]
check(not [o for o in opts if "token" in o], "no command-line option takes a token")
loose = token_file("loose.token", READ_TOKEN, 0o644)
fake = Fake()
code, out, err = run(["list", "--config", config(tokens__read={"path": loose})], fake)
check(code == 2 and "0644" in err and not fake.log, "a mode-644 token is refused before any request")
fake = Fake()
code, out, err = run(["list", "--config", config(tokens__read={"path": os.path.join(SECRETS, "none")})], fake)
check(code == 2 and "file_comments:read" in err and not fake.log, "a missing token names its scope")
empty = token_file("empty.token", "")
code, out, err = run(["list", "--config", config(tokens__read={"path": empty})], Fake())
check(code == 2 and "empty" in err, "an empty token file is refused")


# ----------------------------------------------------------------- 7. writes

section("7. writes")
for argv in (["reply", "1000000001", "--message", "hi"], ["post", "--node", "1:2", "--message", "hi"],
             ["reply", "1000000001", "--message", "hi", "--dry-run"]):
    fake = Fake()
    code, out, err = run(argv + ["--config", config()], fake)
    check(code == 2 and "read-only" in err and fake.log == [],
          f"no write token: {argv[0]}{' --dry-run' if '--dry-run' in argv else ''} refused with no request")
cfg_w = config(tokens__write={"path": WT})
reset_state()
run(["new", "--config", cfg_w], Fake())
fake = Fake()
code, out, err = run(["reply", "1000000001", "--message", "Moved it.", "--config", cfg_w], fake)
post = [r for r in fake.log if r["method"] == "POST"]
check(code == 0 and len(post) == 1, f"reply posts once ({err})")
check(post and post[0]["path"] == "/v1/files/EXAMPLEFILEKEY000/comments", "reply posts to the comments path")
check(post and post[0]["body"] == {"message": "Ada (via Ada's account): Moved it.", "comment_id": "1000000001"},
      f"reply body is message + comment_id, prefixed ({post and post[0]['body']})")
check(post and post[0]["token"] == WRITE_TOKEN, "the write uses the write token")
check(fake.log[0]["method"] == "GET" and fake.log[0]["token"] == READ_TOKEN, "the target is checked with the read token")
with open(os.path.join(HOME_ADA, "state", "figma-workspace", "cursor-EXAMPLEFILEKEY000.json")) as f:
    check("2000000001" in json.load(f)["seen"], "the agent's own comment is marked seen")
fake = Fake()
code, out, err = run(["reply", "1000000003", "--config", cfg_w], fake, stdin="From stdin.\n")
post = [r for r in fake.log if r["method"] == "POST"]
check(post and post[0]["body"]["comment_id"] == "1000000001" and "is a reply" in err,
      "a reply to a reply goes to its root, and says so")
check(post and post[0]["body"]["message"].endswith("From stdin."), "the message can come from stdin")
fake = Fake()
code, out, err = run(["reply", "1000000001", "--message", "Ada (via Ada's account): already", "--config", cfg_w], fake)
check([r for r in fake.log if r["method"] == "POST"][0]["body"]["message"] == "Ada (via Ada's account): already",
      "the prefix is not doubled")
fake = Fake()
code, out, err = run(["reply", "1000000999", "--message", "x", "--config", cfg_w], fake)
check(code == 4 and not [r for r in fake.log if r["method"] == "POST"], "a reply to an unknown id posts nothing")
fake = Fake()
code, out, err = run(["post", "--node", "1:2", "--offset", "10,20", "--message", "New.", "--config",
                      config(tokens__write={"path": WT}, post__prefix=None)], fake)
post = [r for r in fake.log if r["method"] == "POST"]
check(post and post[0]["body"] == {"message": "New.", "client_meta": {"node_id": "1:2",
                                   "node_offset": {"x": 10.0, "y": 20.0}}},
      f"post pins to the node at the offset, with no prefix when post.prefix is null ({post and post[0]['body']})")
fake = Fake()
code, out, err = run(["reply", "1000000001", "--message", "x", "--dry-run", "--config", cfg_w], fake)
check(code == 0 and not [r for r in fake.log if r["method"] == "POST"], "--dry-run sends no POST")
check('"comment_id": "1000000001"' in out and WRITE_TOKEN not in out and READ_TOKEN not in out,
      "--dry-run prints the body and no token")
bad = [r for r in ALL_REQUESTS if r["method"] not in ("GET", "POST")
       or (r["method"] == "POST" and not r["path"].endswith("/comments"))
       or r["host"] != "api.figma.com"]
check(ALL_REQUESTS and not bad, f"every request this file made was a GET, or a POST of a comment ({bad[:1]})")
check(not [r for r in ALL_REQUESTS if r["body"] and ({"resolved", "resolved_at"} & set(r["body"]))],
      "no request body names resolution")


# ----------------------------------------------------------------- 8. errors

section("8. errors")
cases = [
    (401, '{"status":401,"err":"Invalid token"}', None, 3, "invalid"),
    (403, '{"status":403,"err":"Invalid scope(s): x. This endpoint requires the file_comments:read scope"}',
     None, 3, "this call needs file_comments:read"),
    (403, '{"error":true,"status":403,"message":"Invalid scope: [\\"x\\"]. This endpoint requires the '
          'current_user:read scope.","i18n":null}', None, 3, "current_user:read"),
    (403, '{"status":403,"err":"Forbidden"}', None, 3, "cannot open"),
    (404, '{"status":404,"err":"Not found"}', None, 4, "not found"),
    (429, '{"status":429,"err":"Rate limit exceeded"}',
     {"Retry-After": "30", "X-Figma-Rate-Limit-Type": "low", "X-Figma-Plan-Tier": "pro"}, 4, "Retry-After 30"),
]
messages = []
for status, body, headers, want, needle in cases:
    fake = Fake()
    fake.errors["/v1/files/"] = (status, body, headers)
    code, out, err = run(["list", "--config", config()], fake)
    messages.append(err)
    check(code == want and needle in err, f"HTTP {status} -> exit {want}, '{needle}' ({code}: {err.strip()[:120]})")
check("X-Figma-Rate-Limit-Type low" in messages[-1], "a 429 reports the rate-limit type")
check(len(set(messages)) == len(messages), "every error case reads differently")


def down(req, timeout=None):
    raise urllib.error.URLError("connection refused")


code, out, err = run(["list", "--config", config()], down)
check(code == 4 and "could not reach" in err, "a network failure is exit 4")


# ----------------------------------------------------------------- 9. CLI, fleet lookups

section("9. CLI and fleet lookups")
two = fc.load_config(config(files=[{"alias": "main", "key": "EXAMPLEFILEKEY000"},
                                   {"alias": "lib", "key": "EXAMPLEFILEKEY001"}]))
check(fc.file_key(two, "lib") == ("EXAMPLEFILEKEY001", "lib"), "--file takes an alias")
check(fc.file_key(two, "EXAMPLEFILEKEY001")[0] == "EXAMPLEFILEKEY001", "--file takes a key")
check(fc.file_key(two, WEB + "/design/EXAMPLEFILEKEY002/Name?node-id=1-2")[0] ==
      "EXAMPLEFILEKEY002", "--file takes a URL")
check(fc.file_key(two, WEB + "/design/EXAMPLEFILEKEY002/branch/EXAMPLEBRANCH01/Name")[0] ==
      "EXAMPLEBRANCH01", "a branch URL gives the branch key")
try:
    fc.file_key(two, None)
    check(False, "several files without --file are refused")
except fc.ConfigError as e:
    check("main, lib" in str(e), "several files without --file are refused, listing the aliases")
for argv in (["list"], ["new", "--peek"], ["reply", "1"], ["post", "--node", "1:2"]):
    try:
        fc.build_parser().parse_args(argv)
        check(True, "")
    except SystemExit:
        check(False, f"{argv} parses")
fixture = fc.load_config(None)
check(fc.file_key(fixture, "fixture-install-library")[0] == "EXAMPLEFILEKEY001",
      "with no --config, the install context's config.json is read (the fixture install)")
code, out, err = run(["list", "--file", "main"], Fake())
check(code == 2 and "/tmp/fleet-fixture-secrets/figma-comments-read.token" in err,
      "the fixture install's token path is the one resolved")
os.environ["FLEET_CONTEXT_ROOT"] = os.path.join(TMP, "no-install")
os.makedirs(os.environ["FLEET_CONTEXT_ROOT"])
code, out, err = run(["list"], Fake())
check(code == 1 and "FIGMA_WORKSPACE_CONFIG" in err, "an install context that does not resolve is a config error")
os.environ["FLEET_CONTEXT_ROOT"] = FIXTURE_INSTALL


# ----------------------------------------------------------------- 10. hostile input, faults, outcomes

section("10. hostile token files, transport faults, the write outcome, the name cache")


def header_checking(req, timeout=None):
    """The real transport's header validation, offline: http.client.putheader
    rejects an illegal header value with a ValueError that quotes the value,
    before any connection is made (nothing listens on the port)."""
    conn = http.client.HTTPConnection("127.0.0.1", 9)
    conn.putrequest(req.get_method(), "/")
    for k, v in req.header_items():
        conn.putheader(k, v)
    raise AssertionError("the header passed validation; this fake only validates")


# B2: a token file holds ONE line of printable non-space ASCII, or it is refused,
# naming the path and never the value. The newline case is the measured leak: the
# transport quotes the value in its error, where the exact-token scrub cannot see it.
for label, value, frags in (
        ("an embedded newline", "figd_HEAD-sentinel-0004\nTAILSECRET-sentinel-0005",
         ["HEAD-sentinel-0004", "TAILSECRET-sentinel-0005"]),
        ("an embedded space", "plainSECRET-sentinel-0006 more", ["plainSECRET-sentinel-0006"]),
        ("a control character", "plainSECRET-sentinel-0007\x07x", ["plainSECRET-sentinel-0007"])):
    p = token_file("hostile-" + re.sub(r"\W", "", label) + ".token", value)
    for fake in (Fake(), header_checking):
        code, out, err = run(["list", "--config", config(tokens__read={"path": p})], fake)
        check(code == 2 and p in err, f"{label}: refused as a credential, naming the path ({code})")
        check(not [f for f in frags if f in out + err], f"{label}: no part of the value is printed")
    check(not Fake().log, "control: a fresh fake has logged nothing")

# S3a: the exact-token pass of scrub(), with a token that has no figd_ shape, so the
# shape regex cannot be what removes it.
plain = token_file("plain.token", "plainREAD-sentinel-0008")
for status in (403, 500):
    fake = Fake()
    fake.errors["/v1/files/"] = (status, "echo plainREAD-sentinel-0008 back", None)
    code, out, err = run(["list", "--config", config(tokens__read={"path": plain})], fake)
    check(fake.log and fake.log[0]["token"] == "plainREAD-sentinel-0008", f"control: sent ({status})")
    check("plainREAD-sentinel-0008" not in out + err and "[redacted]" in err,
          f"a token of any shape is scrubbed by its exact value ({status})")


class Raises(Fake):
    """Raises EXC (or calls it with the request) for requests whose method is in ON."""

    def __init__(self, exc, on=("GET",), path=""):
        super().__init__()
        self.exc, self.on, self.path = exc, on, path

    def __call__(self, req, timeout=None):
        if req.get_method() in self.on and self.path in req.full_url:
            self.log.append({"method": req.get_method(), "path": req.full_url})
            raise self.exc(req) if callable(self.exc) and not isinstance(self.exc, type) else self.exc
        return super().__call__(req, timeout)


class Truncated(Resp):
    def read(self, *a):
        raise http.client.IncompleteRead(b"partial")


class TruncatedFake(Fake):
    def __call__(self, req, timeout=None):
        super().__call__(req, timeout)
        return Truncated(b"")


# B2 and S2: every transport failure is an ApiError, exit 4, scrubbed.
echo = lambda req: ValueError(f"Invalid header value {req.get_header('X-figma-token')!r}")  # noqa: E731
for label, fake, needle in (
        ("a header the transport rejects", Raises(echo), "Invalid header value"),
        ("a read timeout", Raises(TimeoutError("timed out")), "timed out"),
        ("a truncated body", TruncatedFake(), "IncompleteRead"),
        ("a connection reset", Raises(ConnectionResetError(104, "reset by peer")), "reset by peer")):
    code, out, err = run(["list", "--config", config()], fake)
    check(code == 4 and needle in err, f"{label}: ApiError, exit 4 ({code}: {err.strip()[:90]})")
    check(READ_TOKEN not in out + err, f"{label}: the token is not printed")

# S2: a fault in the NAME lookup degrades the names, never the listing.
for label, fake in (("a timeout", Raises(TimeoutError("timed out"), path="depth=2")),
                    ("a header rejection", Raises(echo, path="depth=2"))):
    reset_state()
    code, out, err = run(["list", "--json", "--config", config(names__token="read")], fake)
    doc = json.loads(out) if code == 0 else {}
    check(code == 0 and all(t["anchor"].get("status") in ("unavailable", None) for t in doc.get("threads", [])),
          f"{label} in the name lookup: the listing still exits 0, names unavailable ({code})")

# S1: once the POST succeeded, the id is printed and the exit is 0, whatever the cursor does.
cfg_w = config(tokens__write={"path": WT})
reset_state()
run(["new", "--config", cfg_w], Fake())
cur = os.path.join(HOME_ADA, "state", "figma-workspace", "cursor-EXAMPLEFILEKEY000.json")
with open(cur, "w") as f:
    f.write("{not json")
fake = Fake()
code, out, err = run(["reply", "1000000001", "--message", "x", "--config", cfg_w], fake)
check(len([r for r in fake.log if r["method"] == "POST"]) == 1 and code == 0 and "2000000001" in out
      and "warning" in err.lower(), f"a corrupt cursor after a successful post: exit 0, id printed, warned ({code}: {err.strip()[:80]})")
code, out, err = run(["new", "--config", cfg_w], Fake())
check(code == 1 and cur in err, f"new with a corrupt cursor names the cursor file ({err.strip()[:90]})")
reset_state()
run(["new", "--config", cfg_w], Fake())
sdir_ro = os.path.dirname(cur)
os.chmod(sdir_ro, 0o500)  # an OSError on the cursor write, not a ConfigError
try:
    if os.access(sdir_ro, os.W_OK):
        check(False, "NO VERDICT: this user can write a mode-500 directory (root?), so the unwritable case is unmeasured")
    else:
        fake = Fake()
        code, out, err = run(["reply", "1000000001", "--message", "x", "--config", cfg_w], fake)
        check(len([r for r in fake.log if r["method"] == "POST"]) == 1 and code == 0 and "2000000001" in out
              and "warning" in err.lower(),
              f"an unwritable state dir after a successful post: exit 0, id printed, warned ({code}: {err.strip()[:80]})")
finally:
    os.chmod(sdir_ro, 0o700)
reset_state()

for label, exc, want in (
        ("a timeout after sending", TimeoutError("timed out"), 5),
        ("a connection reset", ConnectionResetError(104, "reset by peer"), 5),
        ("a 502", urllib.error.HTTPError("u", 502, "bad gateway", email.message.Message(),
                                         io.BytesIO(b'{"status":502,"err":"Bad gateway"}')), 5),
        ("a 400", urllib.error.HTTPError("u", 400, "bad", email.message.Message(),
                                         io.BytesIO(b'{"status":400,"err":"Bad request"}')), 4),
        ("a 403", urllib.error.HTTPError("u", 403, "no", email.message.Message(),
                                         io.BytesIO(b'{"status":403,"err":"Forbidden"}')), 3)):
    code, out, err = run(["reply", "1000000001", "--message", "x", "--config", cfg_w], Raises(exc, on=("POST",)))
    unknown = "may have been posted" in err
    check(code == want and unknown == (want == 5),
          f"POST failing with {label}: exit {want}{', outcome unknown' if want == 5 else ', not posted'} ({code}: {err.strip()[:90]})")


class Unparseable(Fake):
    def __call__(self, req, timeout=None):
        r = super().__call__(req, timeout)
        return Resp(b"<html>ok</html>") if req.get_method() == "POST" else r


code, out, err = run(["reply", "1000000001", "--message", "x", "--config", cfg_w], Unparseable())
check(code == 0 and "posted" in out and "warning" in err.lower(),
      f"a 2xx POST whose body does not parse is posted: exit 0, warned ({code})")

# S3b: no bare node id in the readable output with names ON: ok, name_only and deleted lines.
reset_state()
_, out, _ = run(["list", "--config", config(names__token="read")], Fake())
check("frame \"Checkout\" on page \"Screens\"" in out and "(page not resolved)" in out and "deleted" in out,
      "control: the names-on render carries an ok, a name_only and a deleted anchor")
check(not [n for n in ("1:2", "3:4", "5:6", "7:8") if n in out], "no bare node id with names on")

# N2: with names unavailable the reason is printed once, and each anchor carries a short marker.
_, out, _ = run(["list", "--config", config()], Fake())
check(out.count("file_content:read") == 1 and out.count("<name unavailable>") == 4,
      f"the names reason once, a short marker per anchor ({out.count('file_content:read')})")

# N8: a 403 for a scope names the scope THIS call needs, whatever Figma's text says.
for argv, path, scope in ((["list"], "/v1/files/", "file_comments:read"),
                          (["list", "--refresh-names"], "/v1/files/EXAMPLEFILEKEY000?", "file_content:read")):
    class OneScope(Fake):
        def __call__(self, req, timeout=None, _p=path):
            if _p.endswith("?") and "depth=2" not in req.full_url:
                return super().__call__(req, timeout)
            raise urllib.error.HTTPError(req.full_url, 403, "x", email.message.Message(),
                                         io.BytesIO(b'{"status":403,"err":"Invalid scope(s)"}'))
    reset_state()
    code, out, err = run(argv + ["--config", config(names__token="read")], OneScope())
    check(f"this call needs {scope}" in err, f"a scope 403 on {path} names {scope} ({err.strip()[:100]})")

# N9 and S4: the name cache.
reset_state()
def tier1(fake):
    return [r for r in fake.log if "/comments" not in r["path"]]


sf = ScopeFake()
run(["list", "--config", cfg_read], sf)
sf2 = ScopeFake()
code, out, err = run(["list", "--config", cfg_read], sf2)
check(len(tier1(sf)) == 1 and not tier1(sf2), "a scope failure is cached: the next run makes no Tier 1 call")
check("cached" in out and "file_content:read" in out, "the cached refusal still names the scope")
sf3 = ScopeFake()
run(["list", "--refresh-names", "--config", cfg_read], sf3)
check(len(tier1(sf3)) == 1, "--refresh-names retries after a cached scope failure")

UTC = datetime.timezone.utc
T0 = datetime.datetime(2026, 1, 20, 12, 0, tzinfo=UTC)
real_now = fc._now
names_file = os.path.join(HOME_ADA, "state", "figma-workspace", "names-EXAMPLEFILEKEY000.json")
try:
    reset_state()
    cfg1 = config(names__token="read", names__cache_hours=1)
    fc._now = lambda: T0
    run(["list", "--config", cfg1], Fake())
    with open(names_file) as f:
        stamp0 = json.load(f)["fetched_at"]
    fc._now = lambda: T0 + datetime.timedelta(minutes=50)
    fake = Fake()
    fake.comments.insert(0, dict(fake.comments[-1], id="1000000010", order_id="6",
                                 created_at="2026-01-20T12:40:00.000Z",
                                 client_meta={"node_id": "11:12", "node_offset": {"x": 1, "y": 1}}))
    fake.nodes["11:12"] = {"document": {"id": "11:12", "name": "Settings", "type": "FRAME"}}
    code, out, err = run(["list", "--config", cfg1], fake)
    paths = [(r["path"], r["query"]) for r in fake.log]
    check(paths[1:] == [("/v1/files/EXAMPLEFILEKEY000/nodes", "ids=11:12&depth=1")],
          f"a new anchor inside the window: one nodes read for it alone ({paths})")
    check("frame \"Settings\" (page not resolved)" in out and "nested" not in out,
          "a node the depth-2 read did not cover is 'page not resolved', never 'nested'")
    with open(names_file) as f:
        check(json.load(f)["fetched_at"] == stamp0, "an incremental nodes read keeps the depth-2 timestamp")
    fc._now = lambda: T0 + datetime.timedelta(minutes=70)
    fake = Fake()
    fake.depth2["document"]["children"][0]["children"][0]["name"] = "Checkout v2"
    code, out, err = run(["list", "--config", cfg1], fake)
    check("/v1/files/EXAMPLEFILEKEY000" in [r["path"] for r in fake.log] and "\"Checkout v2\"" in out,
          "past cache_hours from the depth-2 read, names are read again and a rename shows")
finally:
    fc._now = real_now
reset_state()


# ----------------------------------------------------------------- 11. after a POST, redirects, output

section("11. after a POST, redirects, rendered text, undecodable token files")
import http.server  # noqa: E402
import subprocess  # noqa: E402
import threading  # noqa: E402

cfg_w = config(tokens__write={"path": WT})
reset_state()


# R-S1 (a): a 2xx POST whose body is JSON but not an object is posted: exit 0, id unknown.
class NonObject(Fake):
    def __init__(self, body):
        super().__init__()
        self.body = body

    def __call__(self, req, timeout=None):
        r = super().__call__(req, timeout)
        return Resp(self.body) if req.get_method() == "POST" else r


for body in (b"null", b"[]", b'"ok"'):
    fake = NonObject(body)
    code, out, err = run(["reply", "1000000001", "--message", "x", "--config", cfg_w], fake)
    check(len([r for r in fake.log if r["method"] == "POST"]) == 1 and code == 0 and "id unknown" in out,
          f"a 2xx POST answering {body.decode()} is posted: exit 0, id unknown ({code}: {err.strip()[:80]})")


# R-S1 (b): a closed stdout after the POST does not turn it into a failure.
class Closed(io.StringIO):
    def write(self, s):
        raise BrokenPipeError(32, "Broken pipe")


fake = Fake()
code, out, err = run(["reply", "1000000001", "--message", "x", "--config", cfg_w], fake, stdout=Closed())
check(len([r for r in fake.log if r["method"] == "POST"]) == 1 and code == 0,
      f"a closed stdout after the POST: exit 0 ({code}: {err.strip()[:80]})")

# `new` with a closed stdout: the reader never saw the comments, so they stay new.
reset_state()
code, out, err = run(["new", "--config", cfg_w], Fake(), stdout=Closed())
code2, out2, err2 = run(["new", "--json", "--config", cfg_w], Fake())
newc = [c["id"] for t in json.loads(out2)["threads"] for c in [t] + t["replies"] if c["new"]] if code2 == 0 else []
check(code == 1 and "not advanced" in err and len(newc) == 8,
      f"new with a closed stdout exits 1 and leaves the cursor where it was ({code}, {len(newc)} still new)")
reset_state()

# ... and end to end, in a child process whose stdout is a pipe already closed at
# the reading end, so the interpreter's own exit-time flush is part of the result.
CHILD = r"""
import importlib.util, io, json, sys
spec = importlib.util.spec_from_file_location("figma_comments", sys.argv[1])
fc = importlib.util.module_from_spec(spec); spec.loader.exec_module(fc)
class R(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): self.close()
def fake(req, timeout=None):
    if req.get_method() == "POST":
        return R(b'{"id": "3000000001"}')
    return R(json.dumps({"comments": [{"id": "1000000001", "parent_id": "", "user": {"id": "1", "handle": "Ada"},
             "created_at": "2026-01-10T09:00:00.000Z", "resolved_at": None, "message": "m",
             "client_meta": None, "order_id": "1"}]}).encode())
fc._urlopen = fake
sys.exit(fc.main(["reply", "1000000001", "--message", "x", "--config", sys.argv[2]]))
"""
rfd, wfd = os.pipe()
os.close(rfd)  # closed before the child starts: its first write to stdout fails
proc = subprocess.run([sys.executable, "-B", "-c", CHILD, os.path.join(HERE, "figma_comments.py"), cfg_w],
                      stdout=wfd, stderr=subprocess.PIPE, text=True, env=dict(os.environ))
os.close(wfd)
check(proc.returncode == 0 and "Traceback" not in proc.stderr,
      f"end to end, a posted comment with stdout closed exits 0 ({proc.returncode}: {proc.stderr.strip()[:120]})")

# Redirects are refused: urllib's default would send X-Figma-Token to the target.
SEEN = []


class Quiet(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass


class Sink(Quiet):
    def do_GET(self):
        SEEN.append(self.headers.get("X-Figma-Token"))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"comments": []}')


sink = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Sink)


class Redirect(Quiet):
    def do_GET(self):
        self.send_response(302)
        self.send_header("Location", f"http://127.0.0.1:{sink.server_address[1]}/elsewhere")
        self.end_headers()


redir = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
for srv in (sink, redir):
    threading.Thread(target=srv.serve_forever, daemon=True).start()
try:
    req = urllib.request.Request(f"http://127.0.0.1:{redir.server_address[1]}/v1/files/K/comments",
                                 headers={"X-Figma-Token": "figd_REDIRECT-sentinel-0009"})
    try:
        with REAL_OPEN(req, timeout=10) as resp:
            resp.read()
        status = "followed"
    except urllib.error.HTTPError as e:
        status = e.code
    check(status == 302 and not SEEN, f"the module's opener refuses a redirect and sends the token nowhere "
          f"({status}; tokens at the target: {len(SEEN)})")
finally:
    for srv in (sink, redir):
        srv.shutdown()
        srv.server_close()
fake = Fake()
fake.errors["/v1/files/"] = (302, "", {"Location": "https://elsewhere.example/x"})
code, out, err = run(["list", "--config", config()], fake)
check(code == 4 and "302" in err and "redirect" in err.lower() and "not followed" in err,
      f"a redirect is an ApiError naming its status, never followed ({code}: {err.strip()[:100]})")

# Rendered output is scrubbed: a token pasted into a comment is not printed back.
for argv in (["list"], ["list", "--json"], ["new", "--peek"], ["new", "--peek", "--json"]):
    reset_state()
    fake = Fake()
    fake.comments[-1] = dict(fake.comments[-1],
                             message=f"my token is {READ_TOKEN} and figd_PASTED-sentinel-0010")
    code, out, err = run(argv + ["--config", config()], fake)
    check(code == 0 and READ_TOKEN not in out + err and "PASTED-sentinel-0010" not in out + err
          and "my token is" in out, f"{' '.join(argv)}: a token in a comment's text is scrubbed ({code})")

# An undecodable token file: the same scrubbed refusal, exit 2, no traceback.
bad = os.path.join(SECRETS, "undecodable.token")
with open(bad, "wb") as f:
    f.write(b"\xff\xfefigd_UNDECODABLE-sentinel-0011\n")
os.chmod(bad, 0o600)
fake = Fake()
code, out, err = run(["list", "--config", config(tokens__read={"path": bad})], fake)
check(code == 2 and bad in err and "Traceback" not in err and "UNDECODABLE" not in out + err and not fake.log,
      f"an invalid-UTF-8 token file is refused as a credential, exit 2 ({code}: {err.strip()[:100]})")
reset_state()

print()
if FAILED:
    print(f"{len(FAILED)} of {CHECKS} checks FAILED")
    for f in FAILED:
        print("  " + f)
    sys.exit(1)
print(f"ALL {CHECKS} CHECKS PASSED")
