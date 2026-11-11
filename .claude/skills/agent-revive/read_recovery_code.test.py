#!/usr/bin/env python3
"""Offline regression guard for read_recovery_code.py.  `python3 read_recovery_code.test.py`

NO NETWORK, NO CREDENTIAL, NO CONFIG OF THIS INSTALL. Both configs under test
are written into a temp directory, the minting helper's mint is replaced with a
stub token, and its transport is replaced with a fake Gmail that serves the
messages each case builds. Section 0 proves the first of those rather than
asserting it: the helper's urlopen seam is replaced with a function that fails
the run, so a call added straight to urllib reds here instead of reaching
Google from a test suite.

================================================================================
WHAT EACH SECTION IS FOR, AND WHAT BREAKS IF IT IS DELETED
================================================================================
 0. The network is unreachable from this file, and the real minter is never
    entered: the mint is stubbed at gsheets.token, so no key is opened.
 1. The extractor, against the fixture body and its controls. The NEGATIVE
    CONTROL is the one with teeth: prose with no code must yield None, because
    an extractor that returned the first 6 digits it saw passes every positive
    case and types a postcode into the challenge. The two-bare-numbers case
    pins the "lone number only" rule the same way.
 2. Window and sender. The newest Google message inside the window wins even
    when listed LAST (Gmail's order is not trusted); one outside the window is
    ignored and exits 1 with a reason; a message from another sender carrying
    a perfect code is ignored. Without the sender case, any 6-digit order
    confirmation in a shared mailbox is a "code".
 3. The subject claim. Every API call the helper makes is minted for the
    RECOVERY MAILBOX, never for the minter's own default user - the whole
    route depends on that one claim, and a helper that forgot to pass
    `subject=` would read the wrong mailbox, succeed, and exit 1 as "no code".
 4. Stdout is the code and nothing else. `$(...)` is how the code is used;
    one extra line on stdout is a paste that fails as a stale code.
 5. Config: a missing `recovery` block and a missing key each exit 2 NAMING the
    key, before anything is fetched; an absent minter is named by path. With no
    --config and no $AGENT_REVIVE_CONFIG the config is the install context's,
    through fleetlib - the fixture install in the fleet's CI, whose mailbox is a
    value no other config here carries, so a pass proves the file was READ - and
    an install context that does not resolve is exit 2 naming the remedy.
 7. The minter is the SIBLING skill's gsheets.py, reached through the fleet root
    with every symlink followed. An agent runs this script through a personal
    skill link; the unresolved path is the link directory, whose parent holds
    only the links an install chose. A run through such a link must reach the
    minter, and a MUTATION CONTROL - the same layout with realpath swapped for
    abspath in a copy - must stop earlier, at "does not resolve", or the case is
    not measuring the link. "Reached" is gsheets.py's OWN config refusal: the
    subprocess gets a gsheets config missing a required key, which the minter
    checks before it imports PyJWT or opens a key, so the case means the same
    thing on a host with or without PyJWT and never signs anything.
 6. HTML parts are read: the same code wrapped in tags, in a text/html part
    with no text/plain twin, is found. A Google mail with only an HTML body is
    the ordinary case, not the edge.
"""
import base64
import importlib.util
import io
import json
import os
import shutil
import sys
import subprocess
import tempfile
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.realpath(__file__))
FLEET_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
GSHEETS = os.path.join(FLEET_ROOT, ".claude", "skills", "google-spreadsheet", "gsheets.py")
# The fixture install context, unless the runner already named one (tests/run-all.sh does).
os.environ.setdefault("FLEET_CONTEXT_ROOT", os.path.join(FLEET_ROOT, "tests", "fixtures", "install"))
os.environ.pop("AGENT_REVIVE_CONFIG", None)
FIXTURE = os.path.join(HERE, "fixtures", "recovery-code-mail.txt")

_spec = importlib.util.spec_from_file_location("read_recovery_code",
                                               os.path.join(HERE, "read_recovery_code.py"))
rrc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rrc)

CHECKS = 0
FAILED = []
SECTION = "-"


def check(condition, label):
    global CHECKS
    CHECKS += 1
    if not condition:
        FAILED.append(f"{SECTION}: {label}")
        print(f"  FAIL  {label}")
    return bool(condition)


def section(name):
    global SECTION
    SECTION = name
    print(name)


TMP = tempfile.mkdtemp(prefix="read-recovery-code-test-")


def write_json(name, doc):
    path = os.path.join(TMP, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f)
    return path


# A gsheets config of the test's own, so the helper never reads the install's.
GS_CONFIG = write_json("gsheets.json", {
    "identity": {"agent": "testagent", "subject_template": "{agent}@example.test"},
    "credential": {"key_path": os.path.join(TMP, "no-such-key.json")},
    "api": {"sheets_base": "https://sheets.invalid", "drive_base": "https://drive.invalid"},
    "scopes": {"sheets": "https://sheets.invalid/scope", "drive": "https://drive.invalid/scope"},
})
os.environ["GSHEETS_CONFIG"] = GS_CONFIG
MAILBOX = "recovery@example.com"
CONFIG = write_json("config.json", {"recovery": {"mailbox": MAILBOX}})

gs = rrc.load_helper(GSHEETS)


def _forbidden(*_a, **_kw):
    raise AssertionError("a real network call was attempted from the test suite")


gs._urlopen = _forbidden
MINTED = []


def _stub_token(scope_url, subject=gs._SENTINEL, cfg=None):
    MINTED.append((scope_url, subject))
    return "stub-token"


gs.token = _stub_token

# --------------------------------------------------------------------------
# Building messages and a fake Gmail
# --------------------------------------------------------------------------

with open(FIXTURE, encoding="utf-8") as f:
    FIXTURE_BODY = f.read()

NOW = 1_800_000_000_000  # ms


def b64(text):
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def message(mid, body, minutes_ago, sender=f"Google <{rrc.SENDERS[0]}>",
            subject="Google Verification Code", mime="text/plain"):
    return {
        "id": mid,
        "internalDate": str(NOW - minutes_ago * 60 * 1000),
        "snippet": body[:60].replace("\n", " "),
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [{"name": "From", "value": sender}, {"name": "Subject", "value": subject}],
            "parts": [{"mimeType": mime, "body": {"data": b64(body)}}],
        },
    }


CALLS = []


class Response:
    def __init__(self, doc):
        self._b = json.dumps(doc).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def fake_gmail(messages):
    by_id = {m["id"]: m for m in messages}

    def transport(request, *_a, **_kw):
        url = request.full_url
        CALLS.append(url)
        if url.startswith(rrc.GMAIL_BASE + "/messages?"):
            return Response({"messages": [{"id": m["id"]} for m in messages]})
        mid = url[len(rrc.GMAIL_BASE) + len("/messages/"):].split("?")[0]
        return Response(by_id[mid])
    return transport


def run(messages, argv=()):
    """Exit code, stdout, stderr of a main() run against MESSAGES."""
    CALLS.clear()
    MINTED.clear()
    gs.forget_tokens()
    gs._urlopen = fake_gmail(messages)
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = rrc.main(["--config", CONFIG, *argv], now_ms=NOW)
    finally:
        gs._urlopen = _forbidden
    return rc, out.getvalue(), err.getvalue()


# --------------------------------------------------------------------------
section("0. no network, no real mint")
gs._urlopen = _forbidden
rc, out, err = run([])
check(rc == 1 and out == "", "an empty mailbox exits 1 with nothing on stdout")
check("no message from" in err, "…and says why on stderr")
try:
    gs._urlopen = _forbidden
    gs.call("https://example.invalid/x", "scope", subject=MAILBOX)
    check(False, "a call outside the fake transport must fail the run")
except AssertionError:
    check(True, "the urlopen seam is the forbidden function between cases")
check(not os.path.exists(os.path.join(TMP, "no-such-key.json")),
      "the throwaway key path was never created (the real mint was never entered)")

# --------------------------------------------------------------------------
section("1. the extractor")
check(rrc.extract_code(FIXTURE_BODY) == "482913", "fixture body -> 482913")
check(rrc.extract_code("Your code: 123456. Thanks") == "123456", "'code:' form")
check(rrc.extract_code("Use G-654321 to verify") == "654321", "G-nnnnnn form")
check(rrc.extract_code("Sign-in attempt from 10.0.0.1 at 2026-09-23") is None,
      "NEGATIVE CONTROL: prose with no 6-digit group yields None")
check(rrc.extract_code("Order 111111 shipped; ref 222222") is None,
      "two bare 6-digit groups and no phrase yield None, not a guess")
check(rrc.extract_code("Enter 777777 on the page") == "777777",
      "a single bare 6-digit group with no phrase is accepted")
check(rrc.extract_code("Your verification code is 1234567") is None,
      "a 7-digit group is not a 6-digit code")

# --------------------------------------------------------------------------
section("2. window and sender")
older = message("old", FIXTURE_BODY.replace("482913", "111111"), minutes_ago=8)
newer = message("new", FIXTURE_BODY.replace("482913", "222222"), minutes_ago=2)
rc, out, err = run([older, newer])
check(rc == 0 and out == "222222\n", "newest inside the window wins when listed first")
rc, out, err = run([newer, older][::-1])
check(rc == 0 and out == "222222\n", "…and when listed LAST (list order is not trusted)")
stale = message("stale", FIXTURE_BODY, minutes_ago=25)
rc, out, err = run([stale])
check(rc == 1 and out == "", "a code older than the window exits 1")
check("in the last 10 min" in err, "…naming the window")
rc, out, err = run([stale], argv=["--minutes", "30"])
check(rc == 0 and out == "482913\n", "--minutes widens the window")
shop = message("shop", "Your order 482913 has shipped", minutes_ago=1,
               sender="Shop <orders@shop.example.com>", subject="Order 482913")
rc, out, err = run([shop, older])
check(rc == 0 and out == "111111\n", "a non-Google sender is ignored even when newer")
rc, out, err = run([shop])
check(rc == 1 and out == "", "…and alone it is exit 1, never a code")
nocode = message("nocode", "Security alert: a new sign-in on Linux.", minutes_ago=1)
rc, out, err = run([nocode])
check(rc == 1 and "none carrying" in err, "a fresh Google mail with no code exits 1 saying so")

# --------------------------------------------------------------------------
section("3. every call is minted for the recovery mailbox")
rc, out, err = run([newer])
check(rc == 0, "control: the run succeeded")
check(MINTED and all(s == MAILBOX for _u, s in MINTED),
      f"every mint carried subject={MAILBOX} (got {sorted(set(s for _u, s in MINTED))})")
check(all(u == rrc.GMAIL_READONLY for u, _s in MINTED), "…for the gmail.readonly scope")
check(len(CALLS) == 2 and CALLS[0].startswith(rrc.GMAIL_BASE + "/messages?"),
      "one list call, then one get per message")

# --------------------------------------------------------------------------
section("4. stdout is the code and nothing else")
rc, out, err = run([newer, older])
check(out == "222222\n", f"stdout is exactly the code plus newline (got {out!r})")
check("code read from message new" in err, "the provenance line is on stderr")

# --------------------------------------------------------------------------
section("5. config errors name what is wrong, before any fetch")
for name, doc, needle in (
    ("no-block.json", {"fleet": {}}, "no 'recovery' block"),
    ("no-mailbox.json", {"recovery": {}}, "recovery.mailbox"),
):
    path = write_json(name, doc)
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = rrc.main(["--config", path], now_ms=NOW)
    check(rc == 2 and needle in err.getvalue() and out.getvalue() == "",
          f"{name}: exit 2 naming {needle}")
saved = sys.modules.pop("gsheets")
try:
    rrc.load_helper(os.path.join(TMP, "nope.py"))
    check(False, "an absent helper must raise")
except rrc.ConfigError as e:
    check("does not resolve" in str(e) and "nope.py" in str(e), "an absent helper path is named")
finally:
    sys.modules["gsheets"] = saved
check(rrc.load_config(CONFIG)["helper"] == GSHEETS and os.path.isfile(GSHEETS),
      "the helper is the sibling gsheets.py under the fleet root, and it is there")
# The install context: the fixture install's config carries a mailbox no config in
# this file carries, so reading it back proves that file was the one read.
ctx_cfg = os.path.join(os.environ["FLEET_CONTEXT_ROOT"], ".claude", "skills", "agent-revive", "config.json")
check(os.path.isfile(ctx_cfg), f"control: the install context carries agent-revive's config.json ({ctx_cfg})")
try:
    want = json.load(open(ctx_cfg, encoding="utf-8"))["recovery"]["mailbox"]
    check(want != MAILBOX, "control: the install context's mailbox differs from this file's own")
    check(rrc.load_config(None)["mailbox"] == want,
          "no --config, no AGENT_REVIVE_CONFIG: the install context's config is the one read")
except (OSError, KeyError, ValueError, rrc.ConfigError) as e:
    check(False, f"the install context's config could not be read: {e}")
saved_ctx = os.environ["FLEET_CONTEXT_ROOT"]
os.environ["FLEET_CONTEXT_ROOT"] = os.path.join(TMP, "no-install-here")
os.makedirs(os.environ["FLEET_CONTEXT_ROOT"])
out, err = io.StringIO(), io.StringIO()
with redirect_stdout(out), redirect_stderr(err):
    rc = rrc.main([], now_ms=NOW)
os.environ["FLEET_CONTEXT_ROOT"] = saved_ctx
check(rc == 2 and "pass --config or set AGENT_REVIVE_CONFIG" in err.getvalue() and out.getvalue() == "",
      "an install context that does not resolve: exit 2 naming the remedy, nothing fetched")

# --------------------------------------------------------------------------
section("6. an HTML-only part is read")
html_only = message("html", "<html><body><p>Your Google verification code is</p>"
                            "<p><b>&#52;&#53;6789</b></p></body></html>",
                    minutes_ago=1, mime="text/html")
html_only["snippet"] = ""
rc, out, err = run([html_only])
check(rc == 0 and out == "456789\n", "code inside tags and entities in a text/html part")

# --------------------------------------------------------------------------
section("7. the minter is reached through the fleet root, through a skill link")


GS_INCOMPLETE = write_json("gsheets-incomplete.json", {"identity": {"agent": "testagent"}})
REACHED = "is missing required key 'identity.subject_template'"


def run_script(path):
    p = subprocess.run([sys.executable, path, "--config", CONFIG], capture_output=True, text=True,
                       env=dict(os.environ, GSHEETS_CONFIG=GS_INCOMPLETE), stdin=subprocess.DEVNULL)
    return p.returncode, p.stderr


link = os.path.join(TMP, "linkcfg", "skills")
os.makedirs(link)
os.symlink(HERE, os.path.join(link, "agent-revive"))
check(not os.path.exists(os.path.join(link, "google-spreadsheet")),
      "control: the link directory has no google-spreadsheet beside it")
rc, err = run_script(os.path.join(link, "agent-revive", "read_recovery_code.py"))
check(rc == 2 and REACHED in err and "does not resolve" not in err,
      f"through a skill link the minter is found and reached (it stops at its own config check): {err.strip()[-120:]!r}")
mfleet = os.path.join(TMP, "mfleet", ".claude", "skills")
os.makedirs(os.path.join(mfleet, "agent-revive"))
os.symlink(os.path.dirname(GSHEETS), os.path.join(mfleet, "google-spreadsheet"))
mlink = os.path.join(TMP, "mlink", "skills")
os.makedirs(mlink)
os.symlink(os.path.join(mfleet, "agent-revive"), os.path.join(mlink, "agent-revive"))
src = open(os.path.join(HERE, "read_recovery_code.py"), encoding="utf-8").read()
needle = "HERE = os.path.dirname(os.path.realpath(__file__))"
check(src.count(needle) == 1, "control: the mutation point exists exactly once")
for name, text, want in (("realpath", src, REACHED),
                         ("abspath", src.replace(needle, needle.replace("realpath", "abspath")), "does not resolve")):
    with open(os.path.join(mfleet, "agent-revive", "read_recovery_code.py"), "w", encoding="utf-8") as f:
        f.write(text)
    rc, err = run_script(os.path.join(mlink, "agent-revive", "read_recovery_code.py"))
    check(rc == 2 and want in err, f"control: the same layout with {name} stops at {want!r}")

# --------------------------------------------------------------------------
shutil.rmtree(TMP, ignore_errors=True)
print()
if FAILED:
    print(f"FAILED {len(FAILED)} of {CHECKS} checks:")
    for f in FAILED:
        print("  " + f)
    sys.exit(1)
print(f"ok: {CHECKS} checks passed")
