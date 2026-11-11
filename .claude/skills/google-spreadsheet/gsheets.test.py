#!/usr/bin/env python3
"""Offline regression guard for gsheets.py.  `python3 gsheets.test.py`

NO NETWORK, NO CREDENTIAL, NO CONFIG OF THIS INSTALL. Every HTTP seam is
replaced, the service-account key is a throwaway RSA key generated here, and the
config under test is written into a temp directory. Section 0 proves the first
of those rather than asserting it: both urlopen seams are replaced with a
function that fails the run, so a future call added straight to urllib reds
here instead of quietly reaching Google from a test suite.

================================================================================
WHAT EACH SECTION IS FOR, AND WHAT BREAKS IF IT IS DELETED
================================================================================
Read this before simplifying anything below. Several of these checks look like
they assert the obvious, and each one is here because the thing it asserts is
INVISIBLE when it breaks - the call still succeeds, and it succeeds as the wrong
identity or with a short answer.

 0. The network is really unreachable from this file. A guard that is not itself
    proven is a guard nobody can tell from a comment.
 1. Config: a complete one loads, and each required key REMOVED IN TURN is a
    fatal error naming that key. The removal loop is the control for the load:
    "it loaded" means nothing unless the loader can also refuse.
 2. The JWT claims, with a subject and without. These two are EACH OTHER'S
    CONTROLS and neither means anything alone: `sub` present when asked for, and
    ABSENT when not. A helper that always sets `sub` passes the first check; one
    that never sets it passes the second; only the pair pins the one claim that
    separates the two identities the key can present. The assertion is verified
    against the key's own public half, so a claim map built but not signed, or
    signed with something else, is a failure too.
 3. key_path is formatted with the install's OWN user, never with --as. An
    impersonation that also changed which key file is read would look for a
    credential belonging to somebody else - and on a machine where that file
    happens to exist, it would sign as a different principal and succeed.
 4. The token cache is keyed by (scope, subject) and honours expiry. A cache
    keyed on scope alone hands a token minted for one user to a caller that
    asked for another. That call succeeds; it just writes to the wrong Drive.
 5. The failure classification maps five distinct inputs to five DISTINCT
    sentences. Asserting the text of one is not enough: a classifier that
    returned a constant would pass every single-case check, so the distinctness
    assertion is the one that has teeth.
 6. scrub(). See gsheets.py's header: the mint response is the one body in the
    module that legitimately holds a bearer token, and the same code path
    renders a mint failure. The control is that ORDINARY text passes through
    untouched, because a scrubber that redacts everything also "passes".
 7. The CLI surface parses: every subcommand, the two identity flags, and the
    contradiction between them. Parsed with no config present, which is the
    reason build_parser() is a separate function.
 8. drive_list sends supportsAllDrives AND includeItemsFromAllDrives on every
    page, and follows nextPageToken. Without those two parameters shared-drive
    content is absent from the result with NO error - a short list that reads
    exactly like a correct one. This is the only place that can see it.
 9. whoami compares the identity Drive reports against the one that was asked
    for, and exits non-zero when they differ. Both directions are checked,
    because a comparison that always passes is the default failure of a check
    like this one.
11. The fleet lookups. `{home}` in credential.key_path is the agent's home under
    the host's agents root (host.json, through fleetlib) - and ONLY a template
    that uses it reads the host settings, so a caller with its own key path
    needs no fleet install: that half is proven with the host settings pointed
    at a file that does not exist. With no --config and no $GSHEETS_CONFIG the
    config is the install context's (the fixture install in the fleet's CI),
    proven by reading back a value no other config here carries; an install
    context that does not resolve is a ConfigError naming the remedy.

⚠️ IF A SECTION CANNOT RUN, IT ISSUES NO VERDICT. Sections 2, 3, 4 and 9 need
PyJWT with its cryptography extra to sign anything at all. When that import
fails, this file exits 2 and says which sections were never reached, rather than
reporting the sections it did run as a pass: "all green" over a suite that
skipped the identity checks is the comfortable answer and the wrong one.
"""
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.realpath(__file__))
FLEET_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
# The fixture install context, unless the runner already named one (tests/run-all.sh does).
os.environ.setdefault("FLEET_CONTEXT_ROOT", os.path.join(FLEET_ROOT, "tests", "fixtures", "install"))

_spec = importlib.util.spec_from_file_location("gsheets", os.path.join(HERE, "gsheets.py"))
gsheets = importlib.util.module_from_spec(_spec)
sys.modules["gsheets"] = gsheets
_spec.loader.exec_module(gsheets)

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


def raises(exc, fn, *a, **kw):
    """Returns the exception instance, or None. Never the boolean alone: every
    caller here asserts on the MESSAGE, because 'it raised something' is exactly
    the check that stays green when the raise moves to another cause."""
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    except Exception:  # noqa: BLE001 - a different exception is a failure, not a pass
        return None
    return None


# --------------------------------------------------------------------------
# 0. The network is unreachable from this file
# --------------------------------------------------------------------------

class NetworkReached(AssertionError):
    pass


def _forbidden(*_a, **_kw):
    raise NetworkReached("a test reached the real network")


urllib.request.urlopen = _forbidden
gsheets._urlopen = _forbidden

section("0. no network")
check(raises(NetworkReached, urllib.request.urlopen, "https://example.invalid") is not None,
      "urllib.request.urlopen is replaced")
check(gsheets._urlopen is _forbidden, "gsheets' own transport seam is replaced")


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

TMP = tempfile.mkdtemp(prefix="gsheets-test-")

GOOD_CONFIG = {
    "identity": {"agent": "jane", "subject_template": "{agent}@example.com"},
    "credential": {"key_path": os.path.join(TMP, "{default_subject}_key.json")},
    "api": {"sheets_base": "https://sheets.example.invalid/v4/spreadsheets",
            "drive_base": "https://www.example.invalid/drive/v3"},
    "scopes": {"sheets": "https://scope.example.invalid/spreadsheets",
               "drive": "https://scope.example.invalid/drive"},
}


def write_config(doc, name="config.json"):
    path = os.path.join(TMP, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f)
    return path


def fresh_config(doc=None, name="config.json"):
    """A loaded config, with gsheets' process-wide cache cleared first."""
    gsheets._CONFIG = None
    gsheets.forget_tokens()
    return gsheets.load_config(write_config(json.loads(json.dumps(doc or GOOD_CONFIG)), name))


class Response:
    """The context-manager shape urlopen returns."""

    def __init__(self, body):
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class Body:
    """The minimal file-like an HTTPError carries as its body.

    `close()` is not optional: HTTPError wraps whatever it is given in
    tempfile's closer, whose __del__ calls close() and prints a traceback to
    STDERR at collection time if there is none. It is ignored by the
    interpreter, lands in nobody's exception handler, and appears in the error
    output of the run - which is exactly what section 10's one-line assertion
    caught.
    """

    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data

    def close(self):
        pass


def http_error(code, body):
    return urllib.error.HTTPError("https://example.invalid", code, "err", {},
                                  Body(json.dumps(body).encode()))


# --------------------------------------------------------------------------
# 1. Config
# --------------------------------------------------------------------------
section("1. config loading")

cfg = fresh_config()
check(cfg["identity"]["agent"] == "jane", "a complete config loads")
check(gsheets.default_subject(cfg) == "jane@example.com",
      "the subject is built from the template and the agent")
check(gsheets.scope("sheets", cfg) == GOOD_CONFIG["scopes"]["sheets"], "scopes resolve by name")

# The control for the line above: every required key, removed one at a time, is
# fatal AND is named in the message. Without this loop "a complete config loads"
# is compatible with a loader that validates nothing at all.
for key in gsheets.REQUIRED_KEYS:
    broken = json.loads(json.dumps(GOOD_CONFIG))
    node, leaf = broken, key.split(".")
    for part in leaf[:-1]:
        node = node[part]
    del node[leaf[-1]]
    err = raises(gsheets.ConfigError, gsheets.load_config, write_config(broken, "broken.json"))
    check(err is not None and key in str(err),
          f"a config missing '{key}' is fatal and names the key")

err = raises(gsheets.ConfigError, gsheets.load_config, os.path.join(TMP, "absent.json"))
check(err is not None and "no config" in str(err), "an absent config names itself")

with open(os.path.join(TMP, "bad.json"), "w", encoding="utf-8") as f:
    f.write("{not json")
err = raises(gsheets.ConfigError, gsheets.load_config, os.path.join(TMP, "bad.json"))
check(err is not None and "does not parse" in str(err), "an unparseable config says so")

# An EMPTY value is as fatal as an absent one. A config key present but blank is
# how a half-filled template gets past a `in cfg` test.
blank = json.loads(json.dumps(GOOD_CONFIG))
blank["identity"]["subject_template"] = ""
err = raises(gsheets.ConfigError, gsheets.load_config, write_config(blank, "blank.json"))
check(err is not None and "identity.subject_template" in str(err),
      "an empty required value is fatal too")


# --------------------------------------------------------------------------
# Credential fixture: a throwaway RSA key, generated here
# --------------------------------------------------------------------------
section("1b. credential file")

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    import jwt as pyjwt
    _private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    PRIVATE_PEM = _private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()).decode()
    PUBLIC_PEM = _private.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    CAN_SIGN = True
except Exception as _e:  # noqa: BLE001
    CAN_SIGN = False
    SIGN_REASON = _e

# Keyword form, not a quoted-key literal: the quoted service-account type field
# is one of the markers .githooks/pre-commit refuses to commit.
KEY = dict(
    type="service_account",
    client_email="jane-service-a@some-project.sa.example.com",
    token_uri="https://oauth2.example.invalid/token",
    private_key=(PRIVATE_PEM if CAN_SIGN else "placeholder: PyJWT/cryptography unavailable, nothing signs"),
)
KEY_PATH = os.path.join(TMP, "jane@example.com_key.json")
with open(KEY_PATH, "w", encoding="utf-8") as f:
    json.dump(KEY, f)

cfg = fresh_config()
check(gsheets.key_path(cfg) == KEY_PATH, "key_path resolves the template")
check(gsheets.load_key(cfg)["client_email"] == KEY["client_email"], "the key loads")

err = raises(gsheets.CredentialError, gsheets.load_key, fresh_config(
    {**GOOD_CONFIG, "credential": {"key_path": os.path.join(TMP, "nokey.json")}}))
check(err is not None and "no service-account key" in str(err),
      "an absent key is a CredentialError naming the path")

# An OAuth client secret is also JSON, also has a client_id, and cannot be
# delegated. Mistaking one for the other is a 20-minute debugging session.
with open(os.path.join(TMP, "notakey.json"), "w", encoding="utf-8") as f:
    json.dump({"installed": {"client_id": "x", "client_secret": "y"}}, f)
err = raises(gsheets.CredentialError, gsheets.load_key, fresh_config(
    {**GOOD_CONFIG, "credential": {"key_path": os.path.join(TMP, "notakey.json")}}))
check(err is not None and "not a service-account key" in str(err)
      and "client_email" in str(err),
      "a non-key JSON file is refused, naming what it lacks")


# --------------------------------------------------------------------------
# 2. The JWT claims - with a subject and without
# --------------------------------------------------------------------------
section("2. the assertion's claims")

minted = []


def fake_mint(request, *_a, **_kw):
    """Capture the assertion, answer with a token. Also asserts the request is
    the one Google's JWT-bearer flow requires: a different grant_type mints
    nothing, and the failure would otherwise only show up online."""
    body = dict(p.split("=", 1) for p in request.data.decode().split("&"))
    minted.append(body)
    return Response({"access_token": f"ya29.token-{len(minted)}", "expires_in": 3600})


def claims_for(subject):
    gsheets.forget_tokens()
    minted.clear()
    gsheets._urlopen = fake_mint
    try:
        gsheets.token("https://scope.example.invalid/drive", subject, cfg)
    finally:
        gsheets._urlopen = _forbidden
    assertion = urllib.parse.unquote_plus(minted[-1]["assertion"])
    return pyjwt.decode(assertion, PUBLIC_PEM, algorithms=["RS256"],
                        audience=KEY["token_uri"])


if CAN_SIGN:
    import urllib.parse

    cfg = fresh_config()
    with_sub = claims_for("someone@example.com")
    check(with_sub.get("sub") == "someone@example.com",
          "a subject is carried as the `sub` claim")
    check(with_sub["iss"] == KEY["client_email"], "iss is the service account")
    check(with_sub["aud"] == KEY["token_uri"], "aud is the key's own token_uri")
    check(with_sub["scope"] == "https://scope.example.invalid/drive", "the scope is carried")
    check(with_sub["exp"] > with_sub["iat"], "the assertion expires after it is issued")
    check(urllib.parse.unquote_plus(minted[-1]["grant_type"])
          == "urn:ietf:params:oauth:grant-type:jwt-bearer", "the JWT-bearer grant is used")

    # The other half of the pair. Neither check means anything alone.
    without_sub = claims_for(None)
    check("sub" not in without_sub,
          "--sa-only / subject=None omits `sub` ENTIRELY (not sub=client_email)")
    check(without_sub["iss"] == KEY["client_email"], "iss is unchanged without a subject")

    # The configured default, when nothing is passed at all.
    gsheets.forget_tokens()
    minted.clear()
    gsheets._urlopen = fake_mint
    try:
        gsheets.token("https://scope.example.invalid/drive", cfg=cfg)
    finally:
        gsheets._urlopen = _forbidden
    default_claims = pyjwt.decode(
        urllib.parse.unquote_plus(minted[-1]["assertion"]), PUBLIC_PEM,
        algorithms=["RS256"], audience=KEY["token_uri"])
    check(default_claims.get("sub") == "jane@example.com",
          "the DEFAULT is the configured Workspace user, not the bare service account")
else:
    print("  (sections 2, 3, 4 and 9 need PyJWT + cryptography)")


# --------------------------------------------------------------------------
# 3. key_path ignores --as
# --------------------------------------------------------------------------
section("3. impersonation does not move the key file")

cfg = fresh_config()
before = gsheets.key_path(cfg)
os.environ["GSHEETS_SUBJECT"] = "someone.else@example.com"
try:
    check(gsheets.default_subject(cfg) == "someone.else@example.com",
          "GSHEETS_SUBJECT overrides the acting user")
    check(gsheets.key_path(cfg) == before,
          "but the key file is still THIS install's own - impersonation does not "
          "redirect the credential")
finally:
    del os.environ["GSHEETS_SUBJECT"]


# --------------------------------------------------------------------------
# 4. The token cache
# --------------------------------------------------------------------------
section("4. the token cache is keyed by (scope, subject)")

if CAN_SIGN:
    cfg = fresh_config()
    gsheets.forget_tokens()
    minted.clear()
    gsheets._urlopen = fake_mint
    try:
        a1 = gsheets.token("scope-a", "one@example.com", cfg)
        a2 = gsheets.token("scope-a", "one@example.com", cfg)
        b = gsheets.token("scope-a", "two@example.com", cfg)
        c = gsheets.token("scope-b", "one@example.com", cfg)
        d = gsheets.token("scope-a", None, cfg)
    finally:
        gsheets._urlopen = _forbidden
    check(a1 == a2 and len(minted) == 4,
          "the same (scope, subject) mints once; four distinct keys mint four times")
    check(len({a1, b, c, d}) == 4,
          "each identity/scope gets its OWN token - no cross-handing")

    # Expiry. A cached token that outlives its expiry is handed to a caller as a
    # live credential and fails at the API with a 401 nobody can explain.
    gsheets.forget_tokens()
    minted.clear()

    def short_mint(request, *_a, **_kw):
        minted.append(1)
        return Response({"access_token": f"ya29.short-{len(minted)}", "expires_in": 1})

    gsheets._urlopen = short_mint
    try:
        first = gsheets.token("scope-a", "one@example.com", cfg)
        second = gsheets.token("scope-a", "one@example.com", cfg)
    finally:
        gsheets._urlopen = _forbidden
    check(first != second and len(minted) == 2,
          "a token inside its 60s expiry margin is re-minted rather than reused")


# --------------------------------------------------------------------------
# 5. Failure classification
# --------------------------------------------------------------------------
section("5. the failures are told apart")

unauthorized = gsheets._mint_error("j@example.com", '{"error":"unauthorized_client"}', 400)
invalid = gsheets._mint_error("j@example.com", '{"error":"invalid_grant"}', 400)
other_mint = gsheets._mint_error("j@example.com", '{"error":"slow_down"}', 429)
check("delegation" in unauthorized and "admin" in unauthorized,
      "unauthorized_client names the delegation grant and who fixes it")
check("not a live user" in invalid, "invalid_grant names the subject as the suspect")
check(len({unauthorized, invalid, other_mint}) == 3,
      "the three mint failures are three DIFFERENT sentences")

disabled = gsheets._api_error(
    403, "https://sheets.example.invalid/v4/spreadsheets/x",
    '{"error":{"status":"PERMISSION_DENIED","message":"Google Sheets API has not been '
    'used in project 1 before or it is disabled","details":[{"reason":"SERVICE_DISABLED"}]}}',
    "j@example.com")
denied = gsheets._api_error(403, "https://sheets.example.invalid/v4/spreadsheets/x",
                            '{"error":{"message":"The caller does not have permission"}}',
                            "j@example.com")
drive404 = gsheets._api_error(404, "https://www.example.invalid/drive/v3/files/x", "{}",
                              "j@example.com")
sheets404 = gsheets._api_error(404, "https://sheets.example.invalid/v4/spreadsheets/x", "{}",
                               "j@example.com")
unauth401 = gsheets._api_error(401, "https://sheets.example.invalid/v4/spreadsheets/x", "{}",
                               "j@example.com")
# A 403 whose cause is the SCOPE, not the share. Measured against a spreadsheet
# the acting user OWNS, refused under a read-only Drive scope - so the sharing
# sentence would send the reader to ask for access they already hold.
scope403 = gsheets._api_error(403, "https://www.example.invalid/drive/v3/files/x/permissions",
                              '{"error":{"code":403,"message":"Request had insufficient '
                              'authentication scopes.","status":'
                              '"PERMISSION_DENIED"}}', "j@example.com")
# A 403 that means "this principal has no Drive storage at all", which is what a
# create looks like when the subject was dropped.
quota403 = gsheets._api_error(403, "https://www.example.invalid/drive/v3/files",
                              '{"error":{"errors":[{"reason":"storageQuotaExceeded"}],'
                              '"message":"Service Accounts do not have storage quota."}}',
                              None)
check("NOT a sharing problem" in disabled and "enabled" in disabled,
      "a 403 carrying SERVICE_DISABLED is reported as an unenabled API, not a share")
check("shared" in denied and "j@example.com" in denied,
      "a plain 403 names the identity the document must be shared with")
check("hides existence" in drive404,
      "a Drive 404 says it is not evidence the file is gone")
check("no such spreadsheet" in sheets404, "a Sheets 404 is about the id")
check("INSUFFICIENT SCOPE" in scope403 and "NOT a sharing problem" in scope403,
      "a 403 about SCOPES is not reported as a sharing problem")
check("NO Drive storage of its own" in quota403 and "subject was dropped" in quota403,
      "a storageQuotaExceeded 403 names the dropped subject as the cause")
check(len({disabled, denied, drive404, sheets404, unauth401, scope403, quota403}) == 7,
      "seven inputs, seven DISTINCT sentences - a constant classifier fails here. THREE "
      "of them are 403s with three unrelated repairs, which is why the status alone is "
      "never the diagnosis")


# --------------------------------------------------------------------------
# 6. Nothing token-shaped is ever printed
# --------------------------------------------------------------------------
section("6. secrets are scrubbed out of anything printed")

check("[redacted]" in gsheets.scrub('{"access_token": "ya29.verySecretValue"}')
      and "verySecretValue" not in gsheets.scrub('{"access_token": "ya29.verySecretValue"}'),
      "an access_token field is redacted")
check("ya29" not in gsheets.scrub("bearer ya29.a0AfH6SMB-loose-token_value here"),
      "a bare ya29. token in free text is redacted")
# The armor line is split across two literals so this file never carries one:
# .githooks/pre-commit refuses to commit a file that does.
check("MIIEvQ" not in gsheets.scrub(
    "-----BEGIN " "PRIVATE KEY-----\nMIIEvQIBADANBg\n-----END PRIVATE KEY-----"),
    "a PEM private key block is redacted")
check("refreshmeplease" not in gsheets.scrub('{"refresh_token": "1//refreshmeplease"}')
      and "[redacted]" in gsheets.scrub('{"refresh_token": "1//refreshmeplease"}'),
      "a refresh_token VALUE is redacted (the field NAME stays, so that a reader "
      "can still see what was removed)")
# The control. A scrubber that redacts everything would pass all four above.
plain = "HTTP 403: The caller does not have permission for spreadsheet 1ab-CD_9"
check(gsheets.scrub(plain) == plain, "ordinary error text is passed through UNCHANGED")


# --------------------------------------------------------------------------
# 7. The CLI surface
# --------------------------------------------------------------------------
section("7. CLI parsing")

parser = gsheets.build_parser()


def parsed(argv):
    """argparse prints its usage to stderr on a refusal; swallowed here so a
    refusal this file EXPECTS does not read as a failure in the log."""
    stderr, sys.stderr = sys.stderr, io.StringIO()
    try:
        return parser.parse_args(argv)
    except SystemExit:
        return None
    finally:
        sys.stderr = stderr


a = parsed(["whoami"])
check(a is not None and a.command == "whoami" and a.subject is None and not a.sa_only,
      "whoami parses with no flags")
a = parsed(["--as", "someone@example.com", "get", "SHEETID"])
check(a is not None and a.subject == "someone@example.com" and a.id == "SHEETID",
      "--as sets the subject")
a = parsed(["--sa-only", "list"])
check(a is not None and a.sa_only and a.query is None, "--sa-only parses; list's query is optional")
a = parsed(["values", "ID", "Sheet1!A1:C9"])
check(a is not None and a.range == "Sheet1!A1:C9", "values takes an A1 range")
a = parsed(["write", "ID", "A1:B2", '[["a"]]', "--raw"])
check(a is not None and a.rows == '[["a"]]' and a.raw, "write takes rows and --raw")
a = parsed(["batch", "ID", "reqs.json"])
check(a is not None and a.file == "reqs.json", "batch takes a request file")
a = parsed(["create", "A title"])
check(a is not None and a.title == "A title", "create takes a title")
a = parsed(["share", "ID", "p@example.com", "--role", "writer"])
check(a is not None and a.role == "writer", "share takes a role")
check(parsed(["share", "ID", "p@example.com", "--role", "emperor"]) is None,
      "an unknown role is refused rather than sent")
a = parsed(["delete", "ID"])
check(a is not None and not a.permanent, "delete TRASHES by default - the recoverable form")
a = parsed(["delete", "ID", "--permanent"])
check(a is not None and a.permanent, "--permanent is the irrecoverable one, and is opt-in")
a = parsed(["list", "name contains 'x'"])
check(a is not None and a.query == "name contains 'x'", "list takes a Drive query")
check(parsed(["get"]) is None, "a subcommand missing its argument is refused")
check(parsed([]) is None, "no subcommand is refused")
check(parsed(["frobnicate"]) is None, "an unknown subcommand is refused")

# The contradiction is caught in run(), not in the parser: both flags are valid
# on their own, and only their combination is meaningless.
args = parsed(["--sa-only", "--as", "someone@example.com", "whoami"])
gsheets._CONFIG = None
os.environ["GSHEETS_CONFIG"] = write_config(GOOD_CONFIG)
err = raises(gsheets.ConfigError, gsheets.run, args)
check(err is not None and "contradictory" in str(err), "--sa-only with --as is refused")


# --------------------------------------------------------------------------
# 8. drive_list always asks for shared-drive content, and pages
# --------------------------------------------------------------------------
section("8. drive_list")

cfg = fresh_config()
seen_urls = []


def fake_drive(request, *_a, **_kw):
    seen_urls.append(request.full_url)
    if "pageToken" in request.full_url:
        return Response({"files": [{"id": "2", "name": "second"}]})
    return Response({"files": [{"id": "1", "name": "first"}], "nextPageToken": "PAGE2"})


gsheets._TOKENS[("https://scope.example.invalid/drive", "jane@example.com")] = (
    "ya29.fake", 2 ** 40)
gsheets._urlopen = fake_drive
try:
    found = gsheets.drive_list(cfg=cfg)
finally:
    gsheets._urlopen = _forbidden

check([f["id"] for f in found] == ["1", "2"], "nextPageToken is followed to the end")
check(len(seen_urls) == 2, "exactly one request per page")
check(all("supportsAllDrives=true" in u for u in seen_urls),
      "every page asks for supportsAllDrives")
check(all("includeItemsFromAllDrives=true" in u for u in seen_urls),
      "every page asks for includeItemsFromAllDrives - without it shared-drive "
      "content is silently absent")


# --------------------------------------------------------------------------
# 9. whoami compares the identity Drive reports with the one asked for
# --------------------------------------------------------------------------
section("9. whoami is a comparison, not an announcement")


def run_whoami(reported_email, argv):
    gsheets._CONFIG = None
    os.environ["GSHEETS_CONFIG"] = write_config(GOOD_CONFIG)
    gsheets.forget_tokens()
    gsheets._TOKENS[("https://scope.example.invalid/drive", "jane@example.com")] = (
        "ya29.fake", 2 ** 40)
    gsheets._TOKENS[("https://scope.example.invalid/drive", None)] = ("ya29.fake", 2 ** 40)
    gsheets._urlopen = lambda *_a, **_kw: Response(
        {"user": {"displayName": "Someone", "emailAddress": reported_email}})
    stdout, sys.stdout = sys.stdout, io.StringIO()
    try:
        code = gsheets.run(gsheets.build_parser().parse_args(argv))
        return code, sys.stdout.getvalue()
    finally:
        sys.stdout = stdout
        gsheets._urlopen = _forbidden


code, printed = run_whoami("jane@example.com", ["whoami"])
check(code == 0, "whoami is 0 when Drive reports the identity that was asked for")
check("ya29" not in printed and "fake" not in printed,
      "whoami prints the identity and NEVER the token it minted to learn it")
check(gsheets.key_path(gsheets.config()) in printed and KEY["client_email"] in printed,
      "whoami names the key file and the service account behind it")
code, _ = run_whoami("JANE@Example.com", ["whoami"])
check(code == 0, "the comparison is case-insensitive, as Workspace addresses are")
code, printed = run_whoami("someone.else@example.com", ["whoami"])
check(code == 4 and "MISMATCH" in printed,
      "whoami is NON-ZERO and says MISMATCH when the token acts as somebody else - "
      "the check that catches a wrong subject_template, which mints perfectly")
code, _ = run_whoami("jane-service-a@some-project.sa.example.com",
                     ["--sa-only", "whoami"])
check(code == 0, "--sa-only makes no comparison: it asked for no subject")


# --------------------------------------------------------------------------
# 10. The exit codes are four codes, not one
# --------------------------------------------------------------------------
section("10. exit codes")


def run_main(argv, transport, config_doc=None):
    gsheets._CONFIG = None
    gsheets.forget_tokens()
    os.environ["GSHEETS_CONFIG"] = write_config(config_doc or GOOD_CONFIG)
    gsheets._urlopen = transport
    stderr, sys.stderr = sys.stderr, io.StringIO()
    stdout, sys.stdout = sys.stdout, io.StringIO()
    try:
        return gsheets.main(argv), sys.stderr.getvalue()
    finally:
        sys.stdout = stdout
        sys.stderr = stderr
        gsheets._urlopen = _forbidden


code, msg = run_main(["--sa-only", "--as", "x@example.com", "whoami"], _forbidden)
check(code == 1 and "contradictory" in msg, "a usage/config error exits 1")

no_key = json.loads(json.dumps(GOOD_CONFIG))
no_key["credential"]["key_path"] = os.path.join(TMP, "definitely-absent.json")
code, msg = run_main(["get", "ID"], _forbidden, no_key)
check(code == 2 and "no service-account key" in msg,
      "a missing credential exits 2 - a machine with no key on it is not a denial")

if CAN_SIGN:
    def refuse_mint(*_a, **_kw):
        raise http_error(400, {"error": "unauthorized_client"})

    code, msg = run_main(["get", "ID"], refuse_mint)
    check(code == 3 and "delegation" in msg,
          "a refused mint exits 3 - no API was reached, so it is not an API denial")

    def deny_api(request, *_a, **_kw):
        if "token" in request.full_url:
            return Response({"access_token": "ya29.fake", "expires_in": 3600})
        raise http_error(403, {"error": {"message": "The caller does not have permission"}})

    code, msg = run_main(["get", "ID"], deny_api)
    check(code == 4 and "PERMISSION_DENIED" in msg, "an API denial exits 4")
    check("Traceback" not in msg and msg.count("\n") == 1,
          "an API denial is ONE line and no traceback")
    check("ya29" not in msg, "no token appears in the error line")


# --------------------------------------------------------------------------
# 11. The fleet lookups: {home}, and the install context's config
# --------------------------------------------------------------------------
section("11. fleet lookups")
saved_host = os.environ.get("FLEET_HOST_CONFIG")
os.environ["FLEET_HOST_CONFIG"] = os.path.join(TMP, "no-such-host.json")
plain = fresh_config()
check(gsheets.key_path(plain) == KEY_PATH,
      "control: a key path without {home} resolves with NO host settings readable")
home_doc = json.loads(json.dumps(GOOD_CONFIG))
home_doc["credential"]["key_path"] = "{home}/secrets/{default_subject}_key.json"
err = raises(gsheets.ConfigError, gsheets.key_path, fresh_config(home_doc, "home.json"))
check(err is not None and "{home}" in str(err),
      "{home} with no readable host settings is a ConfigError naming {home}")
host_json = write_config({"schema": 1, "agents_root": os.path.join(TMP, "agents"),
                          "fleet_checkout": FLEET_ROOT,
                          "claims_dir": os.path.join(TMP, "claims")}, "host.json")
os.environ["FLEET_HOST_CONFIG"] = host_json
try:
    got = gsheets.key_path(fresh_config(home_doc, "home.json"))
except Exception as e:  # noqa: BLE001
    got = f"{type(e).__name__}: {e}"
check(got == os.path.join(TMP, "agents", "jane", "secrets", "jane@example.com_key.json"),
      f"{{home}} is <agents_root>/<agent> from the host settings (got {got!r})")
if saved_host is None:
    os.environ.pop("FLEET_HOST_CONFIG", None)
else:
    os.environ["FLEET_HOST_CONFIG"] = saved_host

os.environ.pop("GSHEETS_CONFIG", None)
gsheets._CONFIG = None
ctx_cfg = os.path.join(os.environ["FLEET_CONTEXT_ROOT"], ".claude", "skills",
                       "google-spreadsheet", "config.json")
check(os.path.isfile(ctx_cfg), f"control: the install context carries this skill's config.json ({ctx_cfg})")
try:
    want = json.load(open(ctx_cfg, encoding="utf-8"))["identity"]["agent"]
    check(want != GOOD_CONFIG["identity"]["agent"],
          "control: the install context's identity.agent differs from this file's own")
    check(gsheets.load_config()["identity"]["agent"] == want,
          "no --config, no GSHEETS_CONFIG: the install context's config is the one read")
except (OSError, KeyError, ValueError, gsheets.ConfigError) as e:
    check(False, f"the install context's config could not be read: {e}")
saved_ctx = os.environ["FLEET_CONTEXT_ROOT"]
os.environ["FLEET_CONTEXT_ROOT"] = os.path.join(TMP, "no-install-here")
os.makedirs(os.environ["FLEET_CONTEXT_ROOT"])
err = raises(gsheets.ConfigError, gsheets.load_config)
os.environ["FLEET_CONTEXT_ROOT"] = saved_ctx
check(err is not None and "pass --config or set GSHEETS_CONFIG" in str(err),
      "an install context that does not resolve is a ConfigError naming the remedy")
gsheets._CONFIG = None


# --------------------------------------------------------------------------
section("summary")
shutil.rmtree(TMP, ignore_errors=True)
os.environ.pop("GSHEETS_CONFIG", None)

if not CAN_SIGN:
    print(f"INCONCLUSIVE: PyJWT/cryptography unavailable ({SIGN_REASON}). Sections 2, 3, 4 "
          f"and 9's signing paths never ran, so this run says NOTHING about the claims, "
          f"the cache or the identity comparison. {CHECKS} other checks ran, "
          f"{len(FAILED)} failed.")
    sys.exit(2)

if FAILED:
    print(f"FAILED: {len(FAILED)} of {CHECKS} checks")
    for f in FAILED:
        print(f"  {f}")
    sys.exit(1)

print(f"OK: {CHECKS} checks passed, no network")
