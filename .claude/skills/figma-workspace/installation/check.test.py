#!/usr/bin/env python3
"""Regression guard for figma-workspace/installation/check.

Runs the real check as a subprocess against copies of the fleet's FIXTURE
INSTALL in a temp directory (HOME, XDG and CLAUDE_CONFIG_DIR inside it too), so
the exit-code contract is exercised end to end with no real install and no
network. The --online leg runs in-process with the helper's transport seam
replaced by a fake, because a subprocess cannot be handed one.

WHAT THIS PINS, and what removing each case would let through:

  - The fixture install as committed is NOT INSTALLED: its read token path
    names a file no test creates. The line must name that path, which proves
    the check read the fixture's config.json through the install context.
  - A complete copy (token mode 600 with the PAT prefix, connector in the
    client record, this host recorded at SKILL.md's version) is OK - the
    control for every red below.
  - Exit 2: a token file that is missing, mode 644, empty, or not a PAT; a
    configured write token whose file is missing; a connector the record does
    not name; a config missing a key.
  - Exit 1: no state file; a state file recording another host only; an older
    version; a client record without its list (NO VERDICT); online, a token
    Figma refuses; online, the network down (NO VERDICT, never a pass).
  - mcp.connector_name null skips that leg, and the line says so.
  - bash check is python3 check (the shell hand-off line).

Run: python3 .claude/skills/figma-workspace/installation/check.test.py
"""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.error

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.realpath(__file__))
CHECK = os.path.join(HERE, "check")
SKILL = os.path.dirname(HERE)
FLEET_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(SKILL)))
FIXTURE_INSTALL = os.path.join(FLEET_ROOT, "tests", "fixtures", "install")
REL = os.path.join(".claude", "skills", "figma-workspace")
ME = socket.gethostname()
with open(os.path.join(SKILL, "SKILL.md"), encoding="utf-8") as f:
    VERSION = int(re.search(r"^version:\s*(\d+)\s*$", f.read(), re.M).group(1))

TMP = tempfile.mkdtemp(prefix="figma-check-test-")
FAILED = []


def check(name, cond, detail=""):
    print(("[PASS] " if cond else "[FAIL] ") + name + (" - " + detail if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


BASE_ENV = {k: v for k, v in os.environ.items()
            if k not in ("FIGMA_WORKSPACE_CONFIG", "FIGMA_SKILL_INSTALL_STATE", "FLEET_SECRETS_DIR")}
BASE_ENV["HOME"] = os.path.join(TMP, "home")
for var in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME"):
    BASE_ENV[var] = os.path.join(TMP, "home", var.lower())
os.makedirs(BASE_ENV["HOME"])


def client(name, ever=True):
    d = os.path.join(TMP, "client-" + name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, ".claude.json"), "w") as f:
        json.dump({"claudeAiMcpEverConnected": ["example.ai Figma"]} if ever is True else
                  {"claudeAiMcpEverConnected": ever} if isinstance(ever, list) else {"other": 1}, f)
    return d


def install(name, token="figd_fixture-token-0001", mode=0o600, state=True, edit=None):
    """A copy of the fixture install with a token file and a state file of its own."""
    root = os.path.join(TMP, name)
    shutil.copytree(FIXTURE_INSTALL, root)
    ctx = os.path.join(root, REL)
    cfg_path = os.path.join(ctx, "config.json")
    with open(cfg_path) as f:
        cfg = json.load(f)
    tok = os.path.join(TMP, name + "-read.token")
    if token is not None:
        with open(tok, "w") as f:
            f.write(token + "\n")
        os.chmod(tok, mode)
    cfg["tokens"]["read"]["path"] = tok
    if edit:
        edit(cfg)
    with open(cfg_path, "w") as f:
        json.dump(cfg, f)
    if state:
        os.makedirs(os.path.join(ctx, "installation"), exist_ok=True)
        hosts = state if isinstance(state, dict) else {ME: {"version": VERSION, "by": "INSTRUCTION.md",
                                                            "installed_at": "2026-01-15T12:00:00Z"}}
        with open(os.path.join(ctx, "installation", ".install-state.json"), "w") as f:
            json.dump({"hosts": hosts}, f)
    return root


def run(root, argv=(), cfg_dir=None, shell=False):
    env = dict(BASE_ENV, FLEET_CONTEXT_ROOT=root, CLAUDE_CONFIG_DIR=cfg_dir or client("default"))
    cmd = (["bash", CHECK] if shell else [sys.executable, CHECK]) + list(argv)
    p = subprocess.run(cmd, capture_output=True, text=True, env=env)
    return p.returncode, (p.stdout + p.stderr).strip()


code, text = run(FIXTURE_INSTALL)
check("the committed fixture install is NOT INSTALLED, naming its token path",
      code == 2 and "/tmp/fleet-fixture-secrets/figma-comments-read.token" in text, f"{code}: {text}")

good = install("good")
code, text = run(good)
check("a complete install is OK", code == 0 and text.startswith("OK:"), f"{code}: {text}")
check("the OK line says the write token is absent and the install read-only",
      "read-only install" in text and "online leg not run" in text, text)
code, text = run(good, shell=True)
check("bash check gives the same verdict as python3 check", code == 0 and text.startswith("OK:"), text)

for label, kwargs, needle in (
        ("a missing token", {"token": None}, "no read token"),
        ("a mode-644 token", {"mode": 0o644}, "0644"),
        ("an empty token", {"token": ""}, "empty"),
        ("a token without the PAT prefix", {"token": "not-a-pat"}, "figd_"),
        ("a configured write token with no file",
         {"edit": lambda c: c["tokens"].__setitem__("write", {"path": os.path.join(TMP, "nope")})}, "write token"),
        ("a config without names.token", {"edit": lambda c: c["names"].pop("token")}, "names.token")):
    code, text = run(install("bad-" + re.sub(r"\W", "", label), **kwargs))
    check(f"{label} is NOT INSTALLED", code == 2 and needle in text, f"{code}: {text}")

code, text = run(good, cfg_dir=client("other", ever=["some other connector"]))
check("a connector the record does not name is NOT INSTALLED", code == 2 and "never been connected" in text, text)
code, text = run(good, cfg_dir=client("noformat", ever=None))
check("a record without its list is NO VERDICT, exit 1", code == 1 and "NO VERDICT" in text, text)
code, text = run(install("nomcp", edit=lambda c: c["mcp"].__setitem__("connector_name", None)),
                 cfg_dir=client("noformat2", ever=None))
check("mcp.connector_name null skips the leg", code == 0 and "MCP leg not used" in text, f"{code}: {text}")

code, text = run(install("nostate", state=False))
check("no state file is STALE", code == 1 and "STALE" in text, text)
code, text = run(install("otherhost", state={"some-other-host": {"version": VERSION}}))
check("another host's record alone is STALE here", code == 1 and "some-other-host" in text, text)
code, text = run(install("twohosts", state={"some-other-host": {"version": VERSION}, ME: {"version": VERSION}}))
check("another host's record beside this one's leaves this one current", code == 0, text)
code, text = run(install("old", state={ME: {"version": VERSION - 1}}))
check("an older recorded version is STALE", code == 1 and "declares" in text, text)


# --online, in-process with a fake transport
def online(root, fake):
    env_keep = dict(os.environ)
    os.environ.clear()
    os.environ.update(BASE_ENV, FLEET_CONTEXT_ROOT=root, CLAUDE_CONFIG_DIR=client("default"))
    loader = importlib.machinery.SourceFileLoader("figma_check_under_test", CHECK)
    spec = importlib.util.spec_from_loader("figma_check_under_test", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    mod.fc._urlopen = fake
    out = io.StringIO()
    old_argv = sys.argv
    sys.argv = [CHECK, "--online"]
    try:
        with contextlib.redirect_stdout(out):
            try:
                mod.main()
                code = 0
            except SystemExit as e:
                code = e.code
    finally:
        sys.argv = old_argv
        os.environ.clear()
        os.environ.update(env_keep)
    return code, out.getvalue().strip()


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


seen = []


def ok(req, timeout=None):
    seen.append((req.get_method(), req.full_url))
    return Resp(b'{"comments": [{"id": "1"}, {"id": "2"}]}')


def refused(req, timeout=None):
    raise urllib.error.HTTPError(req.full_url, 401, "x", {}, io.BytesIO(b'{"status":401,"err":"Invalid token"}'))


def down(req, timeout=None):
    raise urllib.error.URLError("connection refused")


code, text = online(good, ok)
check("--online reads each configured file's comments once", code == 0 and "main: 2 comments" in text
      and "fixture-install-library: 2 comments" in text and len(seen) == 2
      and all(m == "GET" and u.endswith("/comments") for m, u in seen), f"{code}: {text} {seen}")
code, text = online(good, refused)
check("--online with a refused token is STALE", code == 1 and "STALE" in text and "invalid" in text, text)
code, text = online(good, down)
check("--online with the network down is NO VERDICT, never a pass", code == 1 and "NO VERDICT" in text, text)

shutil.rmtree(TMP, ignore_errors=True)
print()
if FAILED:
    print(f"{len(FAILED)} FAILED: " + "; ".join(FAILED))
    sys.exit(1)
print("ALL CHECKS PASSED")
